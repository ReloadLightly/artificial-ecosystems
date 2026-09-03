"""Matched, deterministic variation operators for typed EVOLVE IV programs.

The operators in this module all emit raw proposals which pass through one
adjudicator.  A proposal is accepted only when it changes exactly one typed
leaf by exactly one atomic step.  Model output is replayed from an integrity-
checked offline cache; this module has no provider or network integration.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

import numpy as np

from evolve_modern.iv_policies import (
    Construction,
    IVProgram,
    Movement,
    PolicyValidationError,
    Role,
    coerce_program,
)


class ProgramPath(str, Enum):
    """The seven mutable leaves in the schema-v1 program."""

    ROLE = "traits.role"
    TASTE = "traits.taste"
    CONSTRUCT = "traits.construct"
    MOVEMENT = "movement"
    CONSTRUCTION = "construction"
    REPRODUCE_AT = "reproduce_at"
    REQUIRE_UNCROWDED = "require_uncrowded"


PROGRAM_PATHS: tuple[ProgramPath, ...] = tuple(ProgramPath)


@dataclass(frozen=True)
class ProgramDelta:
    """Typed distance between two valid schema-v1 programs."""

    changed_paths: tuple[ProgramPath, ...]
    field_hamming: int
    atomic_distance: int


class ProposalProvenance(str, Enum):
    """Whether a proposal came from trusted code or an offline response."""

    TRUSTED = "trusted"
    MODEL_CACHE = "model_cache"
    FIXTURE_CACHE = "fixture_cache"


class ProposalFailure(str, Enum):
    """Expected cases in which an operator has no candidate to adjudicate."""

    NO_ELIGIBLE_DONOR = "no_eligible_donor"
    PROVIDER_FAILURE = "provider_failure"


class ProposalStatus(str, Enum):
    """Result of applying the shared one-atomic-edit contract."""

    ACCEPTED = "accepted"
    SOURCE_FAILURE = "source_failure"
    INVALID_CANDIDATE = "invalid_candidate"
    NO_CHANGE = "no_change"
    MULTI_FIELD_EDIT = "multi_field_edit"
    NON_ATOMIC_EDIT = "non_atomic_edit"


class OperatorContractError(RuntimeError):
    """Raised when a trusted in-repository operator violates its contract."""


class CacheIntegrityError(RuntimeError):
    """Raised when an offline cache cannot support an exact replay."""


@dataclass(frozen=True)
class Donor:
    """One living program made available for homologous recombination."""

    bug_id: int
    program: IVProgram

    def __post_init__(self) -> None:
        if type(self.bug_id) is not int or self.bug_id <= 0:
            raise ValueError("donor bug_id must be a positive integer")
        if not isinstance(self.program, IVProgram):
            raise TypeError("donor program must be an IVProgram")


@dataclass(frozen=True, kw_only=True)
class ProposalRequest:
    """Complete deterministic input for one budgeted proposal attempt."""

    experiment_id: str
    replicate_id: str
    opportunity_id: int
    birth_step: int
    parent_bug_id: int
    child_bug_id: int
    parent: IVProgram
    operator_event_seed: int
    living_donors: tuple[Donor, ...] = ()

    def __post_init__(self) -> None:
        for label in ("experiment_id", "replicate_id"):
            value = getattr(self, label)
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty string")
        for label in ("opportunity_id", "birth_step"):
            value = getattr(self, label)
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a nonnegative integer")
        for label in ("parent_bug_id", "child_bug_id"):
            value = getattr(self, label)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if not isinstance(self.parent, IVProgram):
            raise TypeError("parent must be an IVProgram")
        if (
            type(self.operator_event_seed) is not int
            or not 0 <= self.operator_event_seed < 2**64
        ):
            raise ValueError("operator_event_seed must be a uint64 integer")
        donors = tuple(self.living_donors)
        if not all(isinstance(donor, Donor) for donor in donors):
            raise TypeError("living_donors must contain Donor values")
        donor_ids = [donor.bug_id for donor in donors]
        if len(set(donor_ids)) != len(donor_ids):
            raise ValueError("living donor bug IDs must be unique")
        object.__setattr__(self, "living_donors", donors)


@dataclass(frozen=True, kw_only=True)
class RawProposal:
    """One operator response before parsing and edit-budget adjudication."""

    operator_id: str
    operator_revision: str
    provenance: ProposalProvenance
    raw_candidate: str | None
    selected_path: ProgramPath | None = None
    donor_bug_id: int | None = None
    cache_key: str | None = None
    source_failure: ProposalFailure | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not self.operator_id or not self.operator_revision:
            raise ValueError("operator ID and revision must be non-empty")
        object.__setattr__(self, "provenance", ProposalProvenance(self.provenance))
        if self.selected_path is not None:
            object.__setattr__(self, "selected_path", ProgramPath(self.selected_path))
        if self.source_failure is not None:
            object.__setattr__(
                self,
                "source_failure",
                ProposalFailure(self.source_failure),
            )
            if self.raw_candidate is not None:
                raise ValueError("a source failure cannot also contain a candidate")
        elif type(self.raw_candidate) is not str:
            raise ValueError("a proposal without source failure needs raw candidate text")


@dataclass(frozen=True)
class ProposalDecision:
    """The accepted child program or an exact-parent rejection."""

    accepted: bool
    status: ProposalStatus
    program: IVProgram
    candidate: IVProgram | None
    delta: ProgramDelta | None
    proposal: RawProposal


class VariationOperator(Protocol):
    """Uniform interface shared by every matched variation arm."""

    operator_id: str
    operator_revision: str

    def propose(self, request: ProposalRequest) -> RawProposal: ...


def _field_value(program: IVProgram, path: ProgramPath) -> object:
    if path is ProgramPath.ROLE:
        return program.role
    if path is ProgramPath.TASTE:
        return program.taste
    if path is ProgramPath.CONSTRUCT:
        return program.construct
    if path is ProgramPath.MOVEMENT:
        return program.movement
    if path is ProgramPath.CONSTRUCTION:
        return program.construction
    if path is ProgramPath.REPRODUCE_AT:
        return program.reproduce_at
    return program.require_uncrowded


def program_field_value(program: IVProgram, path: ProgramPath) -> object:
    """Return one typed leaf value for provenance consistency checks."""
    if not isinstance(program, IVProgram):
        raise TypeError("program must be an IVProgram")
    return _field_value(program, ProgramPath(path))


def _replace_field(
    program: IVProgram,
    path: ProgramPath,
    value: object,
) -> IVProgram:
    if path is ProgramPath.ROLE:
        return replace(program, role=value)
    if path is ProgramPath.TASTE:
        return replace(program, taste=value)
    if path is ProgramPath.CONSTRUCT:
        return replace(program, construct=value)
    if path is ProgramPath.MOVEMENT:
        return replace(program, movement=value)
    if path is ProgramPath.CONSTRUCTION:
        return replace(program, construction=value)
    if path is ProgramPath.REPRODUCE_AT:
        return replace(program, reproduce_at=value)
    return replace(program, require_uncrowded=value)


def _field_distance(path: ProgramPath, before: object, after: object) -> int:
    if before == after:
        return 0
    if path in (ProgramPath.CONSTRUCT, ProgramPath.REPRODUCE_AT):
        return abs(int(after) - int(before))
    return 1


def program_delta(parent: IVProgram, candidate: IVProgram) -> ProgramDelta:
    """Compute schema-aware Hamming and atomic distances."""
    if not isinstance(parent, IVProgram) or not isinstance(candidate, IVProgram):
        raise TypeError("program_delta requires two IVProgram values")
    changed: list[ProgramPath] = []
    distance = 0
    for path in PROGRAM_PATHS:
        before = _field_value(parent, path)
        after = _field_value(candidate, path)
        field_distance = _field_distance(path, before, after)
        if field_distance:
            changed.append(path)
            distance += field_distance
    return ProgramDelta(
        changed_paths=tuple(changed),
        field_hamming=len(changed),
        atomic_distance=distance,
    )


def _decision_or_contract_error(
    *,
    parent: IVProgram,
    proposal: RawProposal,
    status: ProposalStatus,
    candidate: IVProgram | None,
    delta: ProgramDelta | None,
) -> ProposalDecision:
    if proposal.provenance is ProposalProvenance.TRUSTED:
        raise OperatorContractError(
            f"{proposal.operator_id} emitted {status.value}"
        )
    return ProposalDecision(
        accepted=False,
        status=status,
        program=parent,
        candidate=candidate,
        delta=delta,
        proposal=proposal,
    )


def adjudicate_proposal(
    parent: IVProgram,
    proposal: RawProposal,
) -> ProposalDecision:
    """Apply the common exact-one-atomic-edit acceptance contract."""
    if not isinstance(parent, IVProgram):
        raise TypeError("parent must be an IVProgram")
    if not isinstance(proposal, RawProposal):
        raise TypeError("proposal must be a RawProposal")
    if proposal.source_failure is not None:
        return ProposalDecision(
            accepted=False,
            status=ProposalStatus.SOURCE_FAILURE,
            program=parent,
            candidate=None,
            delta=None,
            proposal=proposal,
        )
    try:
        candidate = coerce_program(proposal.raw_candidate)
    except PolicyValidationError:
        return _decision_or_contract_error(
            parent=parent,
            proposal=proposal,
            status=ProposalStatus.INVALID_CANDIDATE,
            candidate=None,
            delta=None,
        )
    delta = program_delta(parent, candidate)
    if delta.field_hamming == 0:
        return _decision_or_contract_error(
            parent=parent,
            proposal=proposal,
            status=ProposalStatus.NO_CHANGE,
            candidate=candidate,
            delta=delta,
        )
    if delta.field_hamming != 1:
        return _decision_or_contract_error(
            parent=parent,
            proposal=proposal,
            status=ProposalStatus.MULTI_FIELD_EDIT,
            candidate=candidate,
            delta=delta,
        )
    if delta.atomic_distance != 1:
        return _decision_or_contract_error(
            parent=parent,
            proposal=proposal,
            status=ProposalStatus.NON_ATOMIC_EDIT,
            candidate=candidate,
            delta=delta,
        )
    return ProposalDecision(
        accepted=True,
        status=ProposalStatus.ACCEPTED,
        program=candidate,
        candidate=candidate,
        delta=delta,
        proposal=proposal,
    )


def _atomic_values(program: IVProgram, path: ProgramPath) -> tuple[object, ...]:
    current = _field_value(program, path)
    if path is ProgramPath.ROLE:
        return tuple(value for value in Role if value is not current)
    if path is ProgramPath.TASTE:
        return tuple(value for value in (-1, 1) if value != current)
    if path is ProgramPath.CONSTRUCT:
        return tuple(
            value
            for value in (-1, 0, 1)
            if abs(value - int(current)) == 1
        )
    if path is ProgramPath.MOVEMENT:
        return tuple(value for value in Movement if value is not current)
    if path is ProgramPath.CONSTRUCTION:
        return tuple(value for value in Construction if value is not current)
    if path is ProgramPath.REPRODUCE_AT:
        return tuple(
            value
            for value in (int(current) - 1, int(current) + 1)
            if 8 <= value <= 30
        )
    return (not bool(current),)


def atomic_neighbors(
    program: IVProgram,
) -> tuple[tuple[ProgramPath, IVProgram], ...]:
    """Enumerate every atomic neighbor in a stable field/value order."""
    if not isinstance(program, IVProgram):
        raise TypeError("program must be an IVProgram")
    return tuple(
        (path, _replace_field(program, path, value))
        for path in PROGRAM_PATHS
        for value in _atomic_values(program, path)
    )


class TypedPointOperator:
    """Field-uniform point mutation with a deterministic atomic successor."""

    operator_id = "typed_point_v1"
    operator_revision = "1"

    def propose(self, request: ProposalRequest) -> RawProposal:
        rng = np.random.Generator(np.random.PCG64(request.operator_event_seed))
        path = PROGRAM_PATHS[int(rng.integers(0, len(PROGRAM_PATHS)))]
        current = _field_value(request.parent, path)
        if path is ProgramPath.ROLE:
            value = Role.RECYCLER if current is Role.PRODUCER else Role.PRODUCER
        elif path is ProgramPath.TASTE:
            value = -int(current)
        elif path is ProgramPath.CONSTRUCT:
            value = int(current) + 1 if int(current) < 1 else 0
        elif path is ProgramPath.MOVEMENT:
            values = tuple(Movement)
            value = values[(values.index(current) + 1) % len(values)]
        elif path is ProgramPath.CONSTRUCTION:
            values = tuple(Construction)
            value = values[(values.index(current) + 1) % len(values)]
        elif path is ProgramPath.REPRODUCE_AT:
            value = int(current) + 1 if int(current) < 30 else 29
        else:
            value = not bool(current)
        candidate = _replace_field(request.parent, path, value)
        return RawProposal(
            operator_id=self.operator_id,
            operator_revision=self.operator_revision,
            provenance=ProposalProvenance.TRUSTED,
            raw_candidate=candidate.to_json(),
            selected_path=path,
        )


class RandomAtomicEditOperator:
    """Uniform mutation over the complete set of valid atomic neighbors."""

    operator_id = "random_atomic_edit_v1"
    operator_revision = "1"

    def propose(self, request: ProposalRequest) -> RawProposal:
        neighbors = atomic_neighbors(request.parent)
        rng = np.random.Generator(np.random.PCG64(request.operator_event_seed))
        path, candidate = neighbors[int(rng.integers(0, len(neighbors)))]
        return RawProposal(
            operator_id=self.operator_id,
            operator_revision=self.operator_revision,
            provenance=ProposalProvenance.TRUSTED,
            raw_candidate=candidate.to_json(),
            selected_path=path,
        )


class TypedHomologousRecombinationOperator:
    """Copy one atomic-compatible homologous leaf from a living donor."""

    operator_id = "typed_homologous_recombination_v1"
    operator_revision = "1"

    def propose(self, request: ProposalRequest) -> RawProposal:
        eligible: list[tuple[Donor, ProgramPath, IVProgram]] = []
        for donor in sorted(request.living_donors, key=lambda item: item.bug_id):
            if donor.bug_id == request.parent_bug_id:
                continue
            for path in PROGRAM_PATHS:
                before = _field_value(request.parent, path)
                after = _field_value(donor.program, path)
                if _field_distance(path, before, after) == 1:
                    eligible.append(
                        (donor, path, _replace_field(request.parent, path, after))
                    )
        if not eligible:
            return RawProposal(
                operator_id=self.operator_id,
                operator_revision=self.operator_revision,
                provenance=ProposalProvenance.TRUSTED,
                raw_candidate=None,
                source_failure=ProposalFailure.NO_ELIGIBLE_DONOR,
                failure_detail="no living donor has an atomic-compatible leaf",
            )
        rng = np.random.Generator(np.random.PCG64(request.operator_event_seed))
        donor, path, candidate = eligible[int(rng.integers(0, len(eligible)))]
        return RawProposal(
            operator_id=self.operator_id,
            operator_revision=self.operator_revision,
            provenance=ProposalProvenance.TRUSTED,
            raw_candidate=candidate.to_json(),
            selected_path=path,
            donor_bug_id=donor.bug_id,
        )


class CacheProvenance(str, Enum):
    """A real recorded model response or an explicitly synthetic fixture."""

    MODEL = "model"
    FIXTURE = "fixture"


class CacheResponseStatus(str, Enum):
    OK = "ok"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True, kw_only=True)
class CachedProposalProfile:
    """Frozen prompt, model, and decoding identity used by a cache."""

    provenance: CacheProvenance
    prompt_revision: str
    prompt: str
    model_provider: str
    model_name: str
    model_revision: str
    decoding: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", CacheProvenance(self.provenance))
        for label in (
            "prompt_revision",
            "prompt",
            "model_provider",
            "model_name",
            "model_revision",
        ):
            if type(getattr(self, label)) is not str or not getattr(self, label):
                raise ValueError(f"{label} must be a non-empty string")
        if self.provenance is CacheProvenance.FIXTURE:
            if self.model_provider != "fixture":
                raise ValueError("fixture cache profiles must use provider 'fixture'")
        elif self.model_provider == "fixture":
            raise ValueError("model cache profiles cannot use provider 'fixture'")
        if not isinstance(self.decoding, Mapping):
            raise TypeError("decoding must be a mapping")
        normalized = _json_round_trip(dict(self.decoding), "decoding")
        if type(normalized) is not dict:
            raise TypeError("decoding must be a JSON object")
        object.__setattr__(self, "decoding", normalized)


_CACHE_REQUEST_KEYS = frozenset(
    {
        "operator_id",
        "operator_revision",
        "experiment_id",
        "replicate_id",
        "opportunity_id",
        "birth_step",
        "parent_bug_id",
        "child_bug_id",
        "parent_program",
        "parent_sha256",
        "operator_event_seed",
        "provenance",
        "prompt_revision",
        "prompt",
        "prompt_sha256",
        "model",
        "decoding",
    }
)
_CACHE_MODEL_KEYS = frozenset({"provider", "name", "revision"})
_CACHE_ENTRY_KEYS = frozenset(
    {"cache_schema", "cache_key", "provenance", "request", "response"}
)
_CACHE_RESPONSE_KEYS = frozenset(
    {
        "status",
        "raw_text",
        "raw_sha256",
        "failure_detail",
        "finish_reason",
        "usage",
    }
)


def _canonical_json(value: object, label: str = "value") -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CacheIntegrityError(f"{label} is not canonical JSON data: {exc}") from exc


def _json_round_trip(value: object, label: str) -> object:
    return json.loads(_canonical_json(value, label))


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def cached_request_identity(
    profile: CachedProposalProfile,
    request: ProposalRequest,
) -> dict[str, object]:
    """Return the exact canonical identity addressed by the offline cache."""
    parent_json = request.parent.to_json()
    return {
        "operator_id": CachedProposalOperator.operator_id,
        "operator_revision": CachedProposalOperator.operator_revision,
        "experiment_id": request.experiment_id,
        "replicate_id": request.replicate_id,
        "opportunity_id": request.opportunity_id,
        "birth_step": request.birth_step,
        "parent_bug_id": request.parent_bug_id,
        "child_bug_id": request.child_bug_id,
        "parent_program": parent_json,
        "parent_sha256": _digest_text(parent_json),
        "operator_event_seed": request.operator_event_seed,
        "provenance": profile.provenance.value,
        "prompt_revision": profile.prompt_revision,
        "prompt": profile.prompt,
        "prompt_sha256": _digest_text(profile.prompt),
        "model": {
            "provider": profile.model_provider,
            "name": profile.model_name,
            "revision": profile.model_revision,
        },
        "decoding": dict(profile.decoding),
    }


def canonical_cache_key(request_identity: Mapping[str, object]) -> str:
    """Address one exact cached request by its canonical SHA-256 digest."""
    return _digest_text(_canonical_json(dict(request_identity), "cache request"))


def make_cache_record(
    profile: CachedProposalProfile,
    request: ProposalRequest,
    *,
    raw_text: str | None,
    status: CacheResponseStatus = CacheResponseStatus.OK,
    failure_detail: str | None = None,
    finish_reason: str | None = "stop",
    usage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build one canonical cache record without making a provider call."""
    status = CacheResponseStatus(status)
    if status is CacheResponseStatus.OK:
        if type(raw_text) is not str:
            raise ValueError("an ok cache record requires raw response text")
        if failure_detail is not None:
            raise ValueError("an ok cache record cannot have failure detail")
    else:
        if raw_text is not None:
            raise ValueError("a provider-error record cannot have response text")
        if type(failure_detail) is not str or not failure_detail:
            raise ValueError("a provider-error record requires failure detail")
        finish_reason = None
    identity = cached_request_identity(profile, request)
    return {
        "cache_schema": 1,
        "cache_key": canonical_cache_key(identity),
        "provenance": profile.provenance.value,
        "request": identity,
        "response": {
            "status": status.value,
            "raw_text": raw_text,
            "raw_sha256": _digest_text(raw_text) if raw_text is not None else None,
            "failure_detail": failure_detail,
            "finish_reason": finish_reason,
            "usage": dict(usage or {}),
        },
    }


def _exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise CacheIntegrityError(
            f"{label} keys differ; missing={missing}, unknown={unknown}"
        )


def _validate_sha(value: object, expected: str, label: str) -> None:
    if value != expected:
        raise CacheIntegrityError(f"{label} checksum mismatch")


def _validate_cache_record(record: object) -> dict[str, object]:
    if type(record) is not dict:
        raise CacheIntegrityError("cache entry must be a JSON object")
    _exact_keys(record, _CACHE_ENTRY_KEYS, "cache entry")
    if type(record["cache_schema"]) is not int or record["cache_schema"] != 1:
        raise CacheIntegrityError("cache_schema must be the integer 1")
    try:
        provenance = CacheProvenance(record["provenance"])
    except (TypeError, ValueError) as exc:
        raise CacheIntegrityError("invalid cache provenance") from exc

    request = record["request"]
    if type(request) is not dict:
        raise CacheIntegrityError("cache request must be a JSON object")
    _exact_keys(request, _CACHE_REQUEST_KEYS, "cache request")
    if request["provenance"] != provenance.value:
        raise CacheIntegrityError("cache provenance/request mismatch")
    for label in (
        "operator_id",
        "operator_revision",
        "experiment_id",
        "replicate_id",
        "parent_program",
        "parent_sha256",
        "prompt_revision",
        "prompt",
        "prompt_sha256",
    ):
        if type(request[label]) is not str or not request[label]:
            raise CacheIntegrityError(f"cache request {label} must be non-empty text")
    if request["operator_id"] != CachedProposalOperator.operator_id:
        raise CacheIntegrityError("cache request operator ID mismatch")
    if request["operator_revision"] != CachedProposalOperator.operator_revision:
        raise CacheIntegrityError("cache request operator revision mismatch")
    for label in ("opportunity_id", "birth_step", "operator_event_seed"):
        value = request[label]
        if type(value) is not int or value < 0:
            raise CacheIntegrityError(f"cache request {label} must be nonnegative")
    for label in ("parent_bug_id", "child_bug_id"):
        value = request[label]
        if type(value) is not int or value <= 0:
            raise CacheIntegrityError(f"cache request {label} must be positive")
    if request["operator_event_seed"] >= 2**64:
        raise CacheIntegrityError("operator_event_seed exceeds uint64")

    try:
        parent = IVProgram.from_json(request["parent_program"])
    except PolicyValidationError as exc:
        raise CacheIntegrityError(f"invalid cached parent program: {exc}") from exc
    if parent.to_json() != request["parent_program"]:
        raise CacheIntegrityError("cached parent program is not canonical")
    _validate_sha(
        request["parent_sha256"],
        _digest_text(request["parent_program"]),
        "parent program",
    )
    _validate_sha(
        request["prompt_sha256"],
        _digest_text(request["prompt"]),
        "prompt",
    )
    model = request["model"]
    if type(model) is not dict:
        raise CacheIntegrityError("cache model identity must be an object")
    _exact_keys(model, _CACHE_MODEL_KEYS, "cache model")
    if not all(type(value) is str and value for value in model.values()):
        raise CacheIntegrityError("cache model fields must be non-empty text")
    if provenance is CacheProvenance.FIXTURE and model["provider"] != "fixture":
        raise CacheIntegrityError("fixture provenance requires fixture provider")
    if provenance is CacheProvenance.MODEL and model["provider"] == "fixture":
        raise CacheIntegrityError("model provenance cannot use fixture provider")
    if type(request["decoding"]) is not dict:
        raise CacheIntegrityError("cache decoding settings must be an object")
    _canonical_json(request["decoding"], "cache decoding settings")

    expected_key = canonical_cache_key(request)
    if record["cache_key"] != expected_key:
        raise CacheIntegrityError("cache request key mismatch")

    response = record["response"]
    if type(response) is not dict:
        raise CacheIntegrityError("cache response must be a JSON object")
    _exact_keys(response, _CACHE_RESPONSE_KEYS, "cache response")
    try:
        status = CacheResponseStatus(response["status"])
    except (TypeError, ValueError) as exc:
        raise CacheIntegrityError("invalid cache response status") from exc
    if type(response["usage"]) is not dict:
        raise CacheIntegrityError("cache response usage must be an object")
    _canonical_json(response["usage"], "cache response usage")
    if status is CacheResponseStatus.OK:
        if type(response["raw_text"]) is not str:
            raise CacheIntegrityError("ok cache response needs raw text")
        _validate_sha(
            response["raw_sha256"],
            _digest_text(response["raw_text"]),
            "raw response",
        )
        if response["failure_detail"] is not None:
            raise CacheIntegrityError("ok cache response has failure detail")
        if response["finish_reason"] is not None and type(
            response["finish_reason"]
        ) is not str:
            raise CacheIntegrityError("finish_reason must be text or null")
    else:
        if response["raw_text"] is not None or response["raw_sha256"] is not None:
            raise CacheIntegrityError("provider-error response cannot have raw text")
        if type(response["failure_detail"]) is not str or not response[
            "failure_detail"
        ]:
            raise CacheIntegrityError("provider-error response needs failure detail")
        if response["finish_reason"] is not None:
            raise CacheIntegrityError("provider-error finish_reason must be null")

    normalized = _json_round_trip(record, "cache entry")
    assert type(normalized) is dict
    return normalized


def _strict_json(text: str) -> object:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CacheIntegrityError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(token: str) -> None:
        raise CacheIntegrityError(f"non-finite cache number: {token}")

    try:
        return json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except CacheIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CacheIntegrityError(f"malformed cache JSON: {exc}") from exc


class CachedProposalStore:
    """Read-only, fail-closed store of canonical offline responses."""

    def __init__(self, records: Iterable[Mapping[str, object]]):
        entries: dict[str, dict[str, object]] = {}
        for candidate in records:
            record = _validate_cache_record(candidate)
            key = record["cache_key"]
            assert isinstance(key, str)
            if key in entries:
                raise CacheIntegrityError(f"duplicate cache key: {key}")
            entries[key] = record
        self._entries = entries

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "CachedProposalStore":
        records: list[Mapping[str, object]] = []
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise CacheIntegrityError(f"cannot read proposal cache: {exc}") from exc
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = _strict_json(line)
                if type(value) is not dict:
                    raise CacheIntegrityError("cache line must be a JSON object")
                records.append(value)
            except CacheIntegrityError as exc:
                raise CacheIntegrityError(
                    f"invalid proposal cache line {line_number}: {exc}"
                ) from exc
        return cls(records)

    def lookup(
        self,
        profile: CachedProposalProfile,
        request: ProposalRequest,
    ) -> tuple[str, Mapping[str, object]]:
        identity = cached_request_identity(profile, request)
        key = canonical_cache_key(identity)
        try:
            record = self._entries[key]
        except KeyError as exc:
            raise CacheIntegrityError(f"proposal cache miss: {key}") from exc
        if _canonical_json(record["request"]) != _canonical_json(identity):
            raise CacheIntegrityError(f"proposal cache identity mismatch: {key}")
        if record["provenance"] != profile.provenance.value:
            raise CacheIntegrityError(f"proposal cache provenance mismatch: {key}")
        response = record["response"]
        assert isinstance(response, Mapping)
        # Never expose the validated internal entry. Otherwise a caller could
        # mutate later replay behavior without triggering checksum validation.
        return key, copy.deepcopy(response)

    def __len__(self) -> int:
        return len(self._entries)


class CachedProposalOperator:
    """Replay raw cached output exactly; never call a live provider."""

    # The operator is provenance-neutral: a cache may contain authenticated
    # model responses or an explicitly synthetic integration fixture.
    operator_id = "cached_proposal_v1"
    operator_revision = "1"

    def __init__(
        self,
        *,
        profile: CachedProposalProfile,
        store: CachedProposalStore,
    ):
        if not isinstance(profile, CachedProposalProfile):
            raise TypeError("profile must be a CachedProposalProfile")
        if not isinstance(store, CachedProposalStore):
            raise TypeError("store must be a CachedProposalStore")
        self.profile = profile
        self.store = store

    def propose(self, request: ProposalRequest) -> RawProposal:
        key, response = self.store.lookup(self.profile, request)
        provenance = (
            ProposalProvenance.FIXTURE_CACHE
            if self.profile.provenance is CacheProvenance.FIXTURE
            else ProposalProvenance.MODEL_CACHE
        )
        status = CacheResponseStatus(response["status"])
        if status is CacheResponseStatus.PROVIDER_ERROR:
            return RawProposal(
                operator_id=self.operator_id,
                operator_revision=self.operator_revision,
                provenance=provenance,
                raw_candidate=None,
                cache_key=key,
                source_failure=ProposalFailure.PROVIDER_FAILURE,
                failure_detail=str(response["failure_detail"]),
            )
        return RawProposal(
            operator_id=self.operator_id,
            operator_revision=self.operator_revision,
            provenance=provenance,
            raw_candidate=str(response["raw_text"]),
            cache_key=key,
        )


__all__ = [
    "CacheIntegrityError",
    "CacheProvenance",
    "CacheResponseStatus",
    "CachedProposalOperator",
    "CachedProposalProfile",
    "CachedProposalStore",
    "Donor",
    "OperatorContractError",
    "PROGRAM_PATHS",
    "ProgramDelta",
    "ProgramPath",
    "ProposalDecision",
    "ProposalFailure",
    "ProposalProvenance",
    "ProposalRequest",
    "ProposalStatus",
    "RandomAtomicEditOperator",
    "RawProposal",
    "TypedHomologousRecombinationOperator",
    "TypedPointOperator",
    "VariationOperator",
    "adjudicate_proposal",
    "atomic_neighbors",
    "cached_request_identity",
    "canonical_cache_key",
    "make_cache_record",
    "program_delta",
    "program_field_value",
]
