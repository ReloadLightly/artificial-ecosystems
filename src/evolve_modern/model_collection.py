"""Fail-closed, provider-neutral records for authentic model responses.

This module deliberately contains no provider implementation, networking, or
credential access.  It defines the immutable schema used to plan a bounded
collection, bind the exact payload sent to a provider, and verify an offline
cache before replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from evolve_modern.iv_policies import IVProgram, PolicyValidationError


PROFILE_SCHEMA = 2
REQUEST_SCHEMA = 2
CACHE_SCHEMA = 2
HARD_MAX_CALLS = 32
HARD_MAX_INPUT_TOKENS_PER_CALL = 1024
HARD_MAX_OUTPUT_TOKENS_PER_CALL = 192
HARD_MAX_COST_USD = 1.0
UNSELECTED = "UNSELECTED"
FROZEN_WORLD_PATH = "results/reference/iv-world-calibration-v1/frozen-world.json"
_ENVIRONMENT_VARIABLE_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_CREDENTIAL_NAME_MARKERS = (
    "KEY", "TOKEN", "SECRET", "CREDENTIAL", "PASSWORD",
)
_DECODING_KEYS = {
    "temperature", "top_p", "max_output_tokens", "response_format", "tools",
}
_SECRET_BEARING_KEYS = {
    "authorization", "proxy_authorization", "header", "headers", "cookie",
    "cookies", "api_key", "api_token", "access_token", "auth_token", "token",
    "secret", "client_secret", "password",
}


class CollectionIntegrityError(RuntimeError):
    """Raised when a collection identity or offline cache is not exact."""


def canonical_json(value: object, label: str = "value") -> str:
    try:
        return json.dumps(
            _deep_thaw(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CollectionIntegrityError(
            f"{label} is not canonical JSON data: {exc}"
        ) from exc


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_sha256(value: object, label: str = "value") -> str:
    return sha256_text(canonical_json(value, label))


def _deep_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_thaw(item) for item in value]
    return value


def _deep_freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    return value


def _copy_json(value: object, label: str) -> object:
    return json.loads(canonical_json(_deep_thaw(value), label))


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise CollectionIntegrityError(
            f"{label} keys differ; missing={sorted(expected - set(value))}, "
            f"unknown={sorted(set(value) - expected)}"
        )


def _sha(value: object, label: str) -> str:
    if type(value) is not str or not value.startswith("sha256:") or len(value) != 71:
        raise CollectionIntegrityError(f"{label} must be a sha256: digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise CollectionIntegrityError(f"{label} must be a sha256: digest") from exc
    return value


def _text(value: object, label: str, *, allow_unselected: bool = False) -> str:
    if type(value) is not str or not value:
        raise CollectionIntegrityError(f"{label} must be nonempty text")
    if not allow_unselected and value == UNSELECTED:
        raise CollectionIntegrityError(f"{label} is not selected")
    return value


def _reject_secret_bearing_keys(value: object, label: str) -> None:
    """Reject credential-like fields at every depth of an adapter payload."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if (
                normalized in _SECRET_BEARING_KEYS
                or normalized.endswith("_token")
                or normalized.endswith("_secret")
                or normalized.endswith("_password")
            ):
                raise CollectionIntegrityError(
                    f"{label} contains forbidden secret-bearing key: {key}"
                )
            _reject_secret_bearing_keys(item, label)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secret_bearing_keys(item, label)


@dataclass(frozen=True)
class CollectionProfile:
    """A fully hash-addressed collection contract, or an explicit blocked one."""

    _mapping: Mapping[str, object]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CollectionProfile":
        if type(value) is not dict:
            raise CollectionIntegrityError("collection profile must be an object")
        expected = {
            "collection_profile_schema", "profile_id", "experiment_id", "status",
            "frozen_world_path", "frozen_world_sha256", "prompt", "provider",
            "tokenizer", "transport", "implementation", "decoding", "budget",
            "pricing", "trajectory_dependency",
        }
        _exact_keys(value, expected, "collection profile")
        if value["collection_profile_schema"] != PROFILE_SCHEMA:
            raise CollectionIntegrityError(f"collection_profile_schema must be {PROFILE_SCHEMA}")
        for key in ("profile_id", "experiment_id", "frozen_world_path"):
            _text(value[key], key)
        frozen_world_path = Path(str(value["frozen_world_path"]))
        if (
            frozen_world_path.is_absolute()
            or ".." in frozen_world_path.parts
            or frozen_world_path.as_posix() != value["frozen_world_path"]
            or value["frozen_world_path"] != FROZEN_WORLD_PATH
        ):
            raise CollectionIntegrityError(
                "frozen_world_path must be the canonical repository-relative v1 path"
            )
        status = value["status"]
        if status not in {
            "blocked_pending_provider_selection", "ready_for_explicit_authorization"
        }:
            raise CollectionIntegrityError("invalid collection profile status")
        _sha(value["frozen_world_sha256"], "frozen_world_sha256")

        prompt = value["prompt"]
        if type(prompt) is not dict:
            raise CollectionIntegrityError("prompt must be an object")
        _exact_keys(prompt, {"revision", "template", "template_sha256", "render_revision"}, "prompt")
        for key in ("revision", "template", "render_revision"):
            _text(prompt[key], f"prompt.{key}")
        if str(prompt["template"]).count("{{parent_program}}") != 1:
            raise CollectionIntegrityError(
                "prompt template must contain {{parent_program}} exactly once"
            )
        if prompt["template_sha256"] != sha256_text(prompt["template"]):
            raise CollectionIntegrityError("prompt template checksum mismatch")

        provider = value["provider"]
        if type(provider) is not dict:
            raise CollectionIntegrityError("provider must be an object")
        _exact_keys(
            provider,
            {
                "name", "model", "model_revision", "adapter_revision",
                "credential_env_var", "endpoint", "http_method",
                "wire_protocol_revision",
            },
            "provider",
        )
        for key in provider:
            _text(provider[key], f"provider.{key}", allow_unselected=True)
        credential_env_var = provider["credential_env_var"]
        if (
            credential_env_var != UNSELECTED
            and (
                not _ENVIRONMENT_VARIABLE_NAME.fullmatch(credential_env_var)
                or not any(
                    marker in credential_env_var
                    for marker in _CREDENTIAL_NAME_MARKERS
                )
            )
        ):
            raise CollectionIntegrityError(
                "provider.credential_env_var must be a credential-like uppercase "
                "environment-variable name, never a credential value or generic variable"
            )

        tokenizer = value["tokenizer"]
        if type(tokenizer) is not dict:
            raise CollectionIntegrityError("tokenizer must be an object")
        _exact_keys(
            tokenizer,
            {"identity", "revision", "definition_sha256", "counter_revision"},
            "tokenizer",
        )
        for key in tokenizer:
            _text(tokenizer[key], f"tokenizer.{key}", allow_unselected=True)

        transport = value["transport"]
        if type(transport) is not dict:
            raise CollectionIntegrityError("transport must be an object")
        _exact_keys(
            transport,
            {
                "automatic_retries", "max_attempts_per_request", "timeout",
                "idempotency",
            },
            "transport",
        )
        if (
            type(transport["automatic_retries"]) is not int
            or transport["automatic_retries"] != 0
        ):
            raise CollectionIntegrityError("automatic_retries must be zero")
        if (
            type(transport["max_attempts_per_request"]) is not int
            or transport["max_attempts_per_request"] != 1
        ):
            raise CollectionIntegrityError(
                "max_attempts_per_request must be one"
            )
        timeout = transport["timeout"]
        if type(timeout) is not dict:
            raise CollectionIntegrityError("transport.timeout must be an object")
        _exact_keys(timeout, {"kind", "seconds"}, "transport.timeout")
        if timeout["kind"] != "total_wall_clock":
            raise CollectionIntegrityError(
                "transport timeout kind must be total_wall_clock"
            )
        timeout_seconds = timeout["seconds"]
        if timeout_seconds is not None and (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) <= 0
        ):
            raise CollectionIntegrityError(
                "transport timeout seconds must be positive and finite"
            )
        idempotency = transport["idempotency"]
        if type(idempotency) is not dict:
            raise CollectionIntegrityError(
                "transport.idempotency must be an object"
            )
        _exact_keys(
            idempotency,
            {"mode", "key_derivation", "ambiguous_outcome"},
            "transport.idempotency",
        )
        _text(
            idempotency["mode"],
            "transport.idempotency.mode",
            allow_unselected=True,
        )
        if idempotency["key_derivation"] != "request_sha256":
            raise CollectionIntegrityError(
                "idempotency key_derivation must be request_sha256"
            )
        if idempotency["ambiguous_outcome"] != "stop_collection_no_retry":
            raise CollectionIntegrityError(
                "ambiguous outcomes must stop collection without retry"
            )

        implementation = value["implementation"]
        if type(implementation) is not dict:
            raise CollectionIntegrityError("implementation must be an object")
        _exact_keys(
            implementation,
            {
                "operator", "adapter", "collector", "token_counter",
                "terminal_manifest", "adjudicator", "parser", "verifier",
                "source_files_sha256", "source_bundle_sha256",
            },
            "implementation",
        )
        component_keys = {"id", "revision", "source_path"}
        component_names = (
            "operator", "adapter", "collector", "token_counter",
            "terminal_manifest", "adjudicator", "parser", "verifier",
        )
        for component_name in component_names:
            component = implementation[component_name]
            if type(component) is not dict:
                raise CollectionIntegrityError(
                    f"implementation.{component_name} must be an object"
                )
            _exact_keys(
                component,
                component_keys,
                f"implementation.{component_name}",
            )
            for key in component:
                _text(
                    component[key],
                    f"implementation.{component_name}.{key}",
                    allow_unselected=True,
                )
        source_files = implementation["source_files_sha256"]
        if type(source_files) is not dict or not source_files:
            raise CollectionIntegrityError(
                "implementation.source_files_sha256 must be a nonempty object"
            )
        required_sources = {
            "experiments/plan_model_collection.py",
            "experiments/run_iv_variation.py",
            "src/evolve4/control.py",
            "src/evolve4/randomness.py",
            "src/evolve4/simulation.py",
            "src/evolve_modern/iv.py",
            "src/evolve_modern/iv_policies.py",
            "src/evolve_modern/iv_variation.py",
            "src/evolve_modern/model_collection.py",
        }
        if not required_sources <= set(source_files):
            raise CollectionIntegrityError(
                "implementation source map omits a required collection source"
            )
        for source_path, source_sha256 in source_files.items():
            _text(source_path, "implementation source path")
            path = Path(source_path)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != source_path
            ):
                raise CollectionIntegrityError(
                    "implementation source paths must be repository-relative"
                )
            _sha(source_sha256, f"implementation source {source_path}")
        _sha(
            implementation["source_bundle_sha256"],
            "implementation.source_bundle_sha256",
        )
        if implementation["source_bundle_sha256"] != canonical_sha256(
            source_files,
            "implementation source file map",
        ):
            raise CollectionIntegrityError(
                "implementation source bundle checksum mismatch"
            )
        for component_name in ("adjudicator", "parser", "verifier"):
            component = implementation[component_name]
            if any(component[key] == UNSELECTED for key in component):
                raise CollectionIntegrityError(
                    f"implementation.{component_name} must be selected"
                )
            source_path = component["source_path"]
            if source_path not in source_files:
                raise CollectionIntegrityError(
                    f"implementation.{component_name} source is not hash-bound"
                )

        decoding = value["decoding"]
        if type(decoding) is not dict or not decoding:
            raise CollectionIntegrityError("decoding must be a nonempty object")
        unknown_decoding = set(decoding) - _DECODING_KEYS
        if unknown_decoding:
            raise CollectionIntegrityError(
                f"decoding contains unsupported keys: {sorted(unknown_decoding)}"
            )
        if not {"temperature", "max_output_tokens"} <= set(decoding):
            raise CollectionIntegrityError(
                "decoding must define temperature and max_output_tokens"
            )
        temperature = decoding["temperature"]
        if (
            type(temperature) not in (int, float)
            or not math.isfinite(float(temperature))
            or float(temperature) < 0
        ):
            raise CollectionIntegrityError(
                "decoding.temperature must be finite and nonnegative"
            )
        if "top_p" in decoding:
            top_p = decoding["top_p"]
            if (
                type(top_p) not in (int, float)
                or not math.isfinite(float(top_p))
                or not 0 < float(top_p) <= 1
            ):
                raise CollectionIntegrityError(
                    "decoding.top_p must lie in (0, 1]"
                )
        if "response_format" in decoding and decoding["response_format"] != "text":
            raise CollectionIntegrityError(
                "decoding.response_format must be text"
            )
        if "tools" in decoding and decoding["tools"] != []:
            raise CollectionIntegrityError(
                "decoding.tools must be an empty list"
            )
        _reject_secret_bearing_keys(decoding, "decoding")
        _copy_json(decoding, "decoding")

        budget = value["budget"]
        if type(budget) is not dict:
            raise CollectionIntegrityError("budget must be an object")
        _exact_keys(
            budget,
            {
                "replicates", "proposals_per_replicate", "max_calls",
                "max_input_tokens_per_call", "input_token_cap_status",
                "max_output_tokens_per_call", "max_input_tokens_total",
                "max_output_tokens_total", "max_cost_usd",
            },
            "budget",
        )
        ints = (
            "replicates", "proposals_per_replicate", "max_calls",
            "max_input_tokens_per_call", "max_output_tokens_per_call",
            "max_input_tokens_total", "max_output_tokens_total",
        )
        if any(type(budget[key]) is not int or budget[key] <= 0 for key in ints):
            raise CollectionIntegrityError("budget token and call limits must be positive integers")
        if budget["max_calls"] != budget["replicates"] * budget["proposals_per_replicate"]:
            raise CollectionIntegrityError("max_calls must equal replicates times proposals_per_replicate")
        if budget["max_calls"] > HARD_MAX_CALLS:
            raise CollectionIntegrityError(f"max_calls exceeds hard cap {HARD_MAX_CALLS}")
        if budget["max_input_tokens_per_call"] > HARD_MAX_INPUT_TOKENS_PER_CALL:
            raise CollectionIntegrityError(
                "max_input_tokens_per_call exceeds hard cap "
                f"{HARD_MAX_INPUT_TOKENS_PER_CALL}"
            )
        if budget["max_output_tokens_per_call"] > HARD_MAX_OUTPUT_TOKENS_PER_CALL:
            raise CollectionIntegrityError(
                f"max_output_tokens_per_call exceeds hard cap {HARD_MAX_OUTPUT_TOKENS_PER_CALL}"
            )
        if budget["max_input_tokens_total"] != budget["max_calls"] * budget["max_input_tokens_per_call"]:
            raise CollectionIntegrityError("max_input_tokens_total is inconsistent")
        if budget["max_output_tokens_total"] != budget["max_calls"] * budget["max_output_tokens_per_call"]:
            raise CollectionIntegrityError("max_output_tokens_total is inconsistent")
        cost = budget["max_cost_usd"]
        if type(cost) not in (int, float) or not 0 < float(cost) <= HARD_MAX_COST_USD:
            raise CollectionIntegrityError(f"max_cost_usd must be at most {HARD_MAX_COST_USD}")
        cap_status = budget["input_token_cap_status"]
        if cap_status not in {
            "provisional_pending_provider_tokenizer", "exact_provider_tokenizer_frozen"
        }:
            raise CollectionIntegrityError("invalid input_token_cap_status")
        if decoding.get("max_output_tokens") != budget["max_output_tokens_per_call"]:
            raise CollectionIntegrityError("decoding max_output_tokens must equal the budget limit")

        pricing = value["pricing"]
        if type(pricing) is not dict:
            raise CollectionIntegrityError("pricing must be an object")
        _exact_keys(
            pricing,
            {
                "status", "input_usd_per_million_tokens",
                "output_usd_per_million_tokens", "request_usd",
                "effective_date", "currency", "snapshot_path",
                "snapshot_sha256", "snapshot_source_url",
            },
            "pricing",
        )
        if pricing["status"] not in {"pending_provider_selection", "frozen"}:
            raise CollectionIntegrityError("invalid pricing status")
        if pricing["currency"] != "USD":
            raise CollectionIntegrityError("pricing currency must be USD")
        if pricing["status"] == "frozen":
            for key in (
                "input_usd_per_million_tokens",
                "output_usd_per_million_tokens",
            ):
                if (
                    type(pricing[key]) not in (int, float)
                    or not math.isfinite(float(pricing[key]))
                    or float(pricing[key]) <= 0
                ):
                    raise CollectionIntegrityError(
                        f"pricing.{key} must be positive and finite"
                    )
            request_rate = pricing["request_usd"]
            if (
                type(request_rate) not in (int, float)
                or not math.isfinite(float(request_rate))
                or float(request_rate) < 0
            ):
                raise CollectionIntegrityError(
                    "pricing.request_usd must be nonnegative and finite"
                )
            effective_date = _text(
                pricing["effective_date"], "pricing.effective_date"
            )
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_date):
                raise CollectionIntegrityError(
                    "pricing.effective_date must be an ISO YYYY-MM-DD date"
                )
            try:
                date.fromisoformat(effective_date)
            except ValueError as exc:
                raise CollectionIntegrityError(
                    "pricing.effective_date must be a valid calendar date"
                ) from exc
            snapshot_path = _text(
                pricing["snapshot_path"], "pricing.snapshot_path"
            )
            path = Path(snapshot_path)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != snapshot_path
            ):
                raise CollectionIntegrityError(
                    "pricing.snapshot_path must be repository-relative"
                )
            _sha(pricing["snapshot_sha256"], "pricing.snapshot_sha256")
            source_url = _text(
                pricing["snapshot_source_url"], "pricing.snapshot_source_url"
            )
            if not source_url.startswith("https://") or any(
                character.isspace() for character in source_url
            ):
                raise CollectionIntegrityError(
                    "pricing.snapshot_source_url must be an HTTPS URL"
                )
        else:
            if any(
                pricing[key] is not None
                for key in (
                    "input_usd_per_million_tokens",
                    "output_usd_per_million_tokens",
                    "request_usd", "effective_date", "snapshot_path",
                    "snapshot_sha256", "snapshot_source_url",
                )
            ):
                raise CollectionIntegrityError("pending pricing values must be null")

        dependency = value["trajectory_dependency"]
        if type(dependency) is not dict:
            raise CollectionIntegrityError("trajectory_dependency must be an object")
        _exact_keys(
            dependency,
            {"schedule", "future_requests_precomputable", "offline_replay_required", "disclosure"},
            "trajectory_dependency",
        )
        if dependency["schedule"] != "sequential" or dependency["future_requests_precomputable"] is not False or dependency["offline_replay_required"] is not True:
            raise CollectionIntegrityError("trajectory dependency must be sequential and offline replayable")
        _text(dependency["disclosure"], "trajectory_dependency.disclosure")

        selected = all(provider[key] != UNSELECTED for key in provider)
        unselected = all(provider[key] == UNSELECTED for key in provider)
        tokenizer_selected = all(
            tokenizer[key] != UNSELECTED for key in tokenizer
        )
        tokenizer_unselected = all(
            tokenizer[key] == UNSELECTED for key in tokenizer
        )
        operator = implementation["operator"]
        pending_components = (
            "operator", "adapter", "collector", "token_counter",
            "terminal_manifest",
        )
        pending_selected = all(
            all(implementation[name][key] != UNSELECTED for key in component_keys)
            for name in pending_components
        )
        pending_unselected = all(
            all(implementation[name][key] == UNSELECTED for key in component_keys)
            for name in pending_components
        )
        if status == "blocked_pending_provider_selection":
            if (
                not unselected
                or not tokenizer_unselected
                or not pending_unselected
                or timeout_seconds is not None
                or idempotency["mode"] != UNSELECTED
                or pricing["status"] != "pending_provider_selection"
                or cap_status != "provisional_pending_provider_tokenizer"
            ):
                raise CollectionIntegrityError(
                    "blocked profile must retain unselected provider, tokenizer, "
                    "transport, and operator identities"
                )
        else:
            if (
                not selected
                or not tokenizer_selected
                or not pending_selected
                or timeout_seconds is None
                or idempotency["mode"] not in {
                    "provider_guaranteed", "unsupported"
                }
                or pricing["status"] != "frozen"
                or cap_status != "exact_provider_tokenizer_frozen"
            ):
                raise CollectionIntegrityError(
                    "ready profile must freeze provider, tokenizer, transport, "
                    "operator, pricing, and input counter"
                )
            _sha(tokenizer["definition_sha256"], "tokenizer definition")
            for component_name in pending_components:
                if implementation[component_name]["source_path"] not in source_files:
                    raise CollectionIntegrityError(
                        f"implementation.{component_name} source is not hash-bound"
                    )
            if provider["endpoint"] == UNSELECTED:
                raise CollectionIntegrityError("ready profile must freeze an endpoint")
            try:
                endpoint = urlsplit(str(provider["endpoint"]))
                hostname = endpoint.hostname
            except ValueError as exc:
                raise CollectionIntegrityError("provider endpoint is invalid") from exc
            try:
                address = ipaddress.ip_address(hostname) if hostname else None
            except ValueError:
                address = None
            if (
                endpoint.scheme != "https"
                or not hostname
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
                or hostname.lower() == "localhost"
                or hostname.lower().endswith(".localhost")
                or (
                    address is not None
                    and (
                        not address.is_global
                        or address.is_multicast
                        or address.is_unspecified
                    )
                )
            ):
                raise CollectionIntegrityError(
                    "ready profile endpoint must be credential-free HTTPS on a public host"
                )
            if provider["http_method"] != "POST":
                raise CollectionIntegrityError("ready profile HTTP method must be POST")
            worst_cost = (
                budget["max_input_tokens_total"]
                * pricing["input_usd_per_million_tokens"]
                + budget["max_output_tokens_total"]
                * pricing["output_usd_per_million_tokens"]
            ) / 1_000_000 + budget["max_calls"] * pricing["request_usd"]
            if worst_cost > float(cost):
                raise CollectionIntegrityError(
                    "worst-case frozen-pricing cost exceeds max_cost_usd"
                )
        normalized = _copy_json(value, "collection profile")
        assert isinstance(normalized, dict)
        frozen = _deep_freeze(normalized)
        assert isinstance(frozen, Mapping)
        return cls(frozen)

    @classmethod
    def from_json(cls, path: str | Path) -> "CollectionProfile":
        try:
            value = _strict_json(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise CollectionIntegrityError(f"cannot read collection profile: {exc}") from exc
        if type(value) is not dict:
            raise CollectionIntegrityError("collection profile must be an object")
        return cls.from_mapping(value)

    def to_mapping(self) -> dict[str, object]:
        value = _copy_json(self._mapping, "collection profile")
        assert isinstance(value, dict)
        return value

    @property
    def profile_sha256(self) -> str:
        return canonical_sha256(
            _deep_thaw(self._mapping),
            "collection profile",
        )

    @property
    def status(self) -> str:
        return str(self._mapping["status"])


def render_messages(
    profile: CollectionProfile,
    parent_program: str,
) -> tuple[dict[str, str], ...]:
    """Render the sole v1 model-visible input from one canonical parent."""
    try:
        parent = IVProgram.from_json(parent_program)
    except PolicyValidationError as exc:
        raise CollectionIntegrityError(
            f"parent_program is not valid schema-v1 JSON: {exc}"
        ) from exc
    if parent.to_json() != parent_program:
        raise CollectionIntegrityError("parent_program must use canonical JSON bytes")
    prompt = profile.to_mapping()["prompt"]
    assert isinstance(prompt, Mapping)
    content = str(prompt["template"]).replace(
        "{{parent_program}}",
        parent_program,
    )
    return ({"role": "user", "content": content},)


@dataclass(frozen=True)
class RenderedRequest:
    """One trajectory-produced request and its normalized adapter payload.

    Schema v2 fixes the wire contract to the canonical UTF-8 JSON bytes of
    ``normalized_adapter_payload``.  A selected adapter must send those bytes
    unchanged to the profile-bound endpoint with the profile-bound method.
    """

    sequence_index: int
    replicate_id: str
    opportunity_id: int
    birth_step: int
    parent_bug_id: int
    child_bug_id: int
    operator_event_seed: int
    parent_program: str
    messages: Sequence[Mapping[str, object]]
    normalized_adapter_payload: Mapping[str, object]
    profile_sha256: str
    frozen_world_sha256: str
    prompt_revision: str
    render_revision: str

    def __post_init__(self) -> None:
        if type(self.messages) not in (list, tuple) or not self.messages:
            raise CollectionIntegrityError("messages must be a nonempty sequence")
        if not isinstance(self.normalized_adapter_payload, Mapping):
            raise CollectionIntegrityError(
                "normalized_adapter_payload must be an object"
            )
        _reject_secret_bearing_keys(
            self.normalized_adapter_payload,
            "normalized adapter payload",
        )
        messages = _copy_json(list(self.messages), "messages")
        payload = _copy_json(
            dict(self.normalized_adapter_payload),
            "normalized adapter payload",
        )
        frozen_messages = _deep_freeze(messages)
        frozen_payload = _deep_freeze(payload)
        assert isinstance(frozen_messages, tuple)
        assert isinstance(frozen_payload, Mapping)
        object.__setattr__(self, "messages", frozen_messages)
        object.__setattr__(self, "normalized_adapter_payload", frozen_payload)

    @classmethod
    def create(
        cls,
        profile: CollectionProfile,
        *,
        sequence_index: int,
        replicate_id: str,
        opportunity_id: int,
        birth_step: int,
        parent_bug_id: int,
        child_bug_id: int,
        operator_event_seed: int,
        parent_program: str,
        messages: Sequence[Mapping[str, object]],
        normalized_adapter_payload: Mapping[str, object],
    ) -> "RenderedRequest":
        prompt = profile._mapping["prompt"]
        assert isinstance(prompt, Mapping)
        return cls(
            sequence_index=sequence_index,
            replicate_id=replicate_id,
            opportunity_id=opportunity_id,
            birth_step=birth_step,
            parent_bug_id=parent_bug_id,
            child_bug_id=child_bug_id,
            operator_event_seed=operator_event_seed,
            parent_program=parent_program,
            messages=messages,
            normalized_adapter_payload=normalized_adapter_payload,
            profile_sha256=profile.profile_sha256,
            frozen_world_sha256=str(profile._mapping["frozen_world_sha256"]),
            prompt_revision=str(prompt["revision"]),
            render_revision=str(prompt["render_revision"]),
        ).validated(profile)

    def _identity(self) -> dict[str, object]:
        messages = _copy_json(list(self.messages), "messages")
        payload = _copy_json(
            dict(self.normalized_adapter_payload),
            "normalized adapter payload",
        )
        return {
            "request_schema": REQUEST_SCHEMA,
            "sequence_index": self.sequence_index,
            "replicate_id": self.replicate_id,
            "opportunity_id": self.opportunity_id,
            "birth_step": self.birth_step,
            "parent_bug_id": self.parent_bug_id,
            "child_bug_id": self.child_bug_id,
            "operator_event_seed": self.operator_event_seed,
            "parent_program": self.parent_program,
            "parent_sha256": sha256_text(self.parent_program),
            "profile_sha256": self.profile_sha256,
            "frozen_world_sha256": self.frozen_world_sha256,
            "prompt_revision": self.prompt_revision,
            "render_revision": self.render_revision,
            "messages": messages,
            "messages_sha256": canonical_sha256(messages, "messages"),
            "normalized_adapter_payload": payload,
            "normalized_adapter_payload_sha256": canonical_sha256(
                payload, "normalized adapter payload"
            ),
            "wire_body_sha256": sha256_text(
                canonical_json(payload, "normalized adapter payload")
            ),
        }

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(self._identity(), "rendered request")

    @property
    def messages_sha256(self) -> str:
        return canonical_sha256(list(self.messages), "messages")

    @property
    def normalized_adapter_payload_sha256(self) -> str:
        return canonical_sha256(
            dict(self.normalized_adapter_payload),
            "normalized adapter payload",
        )

    @property
    def cache_key(self) -> str:
        return self.request_sha256

    def to_mapping(self) -> dict[str, object]:
        value = self._identity()
        value["request_sha256"] = self.request_sha256
        return value

    def validated(self, profile: CollectionProfile | None = None) -> "RenderedRequest":
        if type(self.sequence_index) is not int or self.sequence_index < 0:
            raise CollectionIntegrityError("sequence_index must be nonnegative")
        if type(self.opportunity_id) is not int or self.opportunity_id < 0:
            raise CollectionIntegrityError("opportunity_id must be nonnegative")
        if type(self.birth_step) is not int or self.birth_step < 0:
            raise CollectionIntegrityError("birth_step must be nonnegative")
        for key in ("parent_bug_id", "child_bug_id"):
            value = getattr(self, key)
            if type(value) is not int or value <= 0:
                raise CollectionIntegrityError(f"{key} must be positive")
        if (
            type(self.operator_event_seed) is not int
            or not 0 <= self.operator_event_seed < 2**64
        ):
            raise CollectionIntegrityError("operator_event_seed must be uint64")
        _text(self.replicate_id, "replicate_id", allow_unselected=True)
        _text(self.parent_program, "parent_program", allow_unselected=True)
        _sha(self.profile_sha256, "profile_sha256")
        _sha(self.frozen_world_sha256, "frozen_world_sha256")
        _text(self.prompt_revision, "prompt_revision")
        _text(self.render_revision, "render_revision")
        if type(self.messages) not in (list, tuple) or not self.messages:
            raise CollectionIntegrityError("messages must be a nonempty sequence")
        if not isinstance(self.normalized_adapter_payload, Mapping):
            raise CollectionIntegrityError(
                "normalized_adapter_payload must be an object"
            )
        _copy_json(list(self.messages), "messages")
        _reject_secret_bearing_keys(
            self.normalized_adapter_payload,
            "normalized adapter payload",
        )
        _copy_json(
            dict(self.normalized_adapter_payload),
            "normalized adapter payload",
        )
        if canonical_json(
            _deep_thaw(self.normalized_adapter_payload.get("messages")),
            "payload messages",
        ) != canonical_json(_deep_thaw(self.messages), "messages"):
            raise CollectionIntegrityError(
                "normalized adapter payload must contain the exact messages"
            )
        if profile is not None:
            if profile.status != "ready_for_explicit_authorization":
                raise CollectionIntegrityError(
                    "cannot render or validate requests for an unselected provider"
                )
            if self.profile_sha256 != profile.profile_sha256:
                raise CollectionIntegrityError("request/profile checksum mismatch")
            if self.frozen_world_sha256 != profile._mapping["frozen_world_sha256"]:
                raise CollectionIntegrityError("request/frozen-world checksum mismatch")
            budget = profile._mapping["budget"]
            assert isinstance(budget, Mapping)
            if self.sequence_index >= budget["max_calls"]:
                raise CollectionIntegrityError(
                    "sequence_index exceeds the profile call cap"
                )
            if self.opportunity_id >= budget["proposals_per_replicate"]:
                raise CollectionIntegrityError(
                    "opportunity_id exceeds the per-replicate proposal cap"
                )
            if canonical_json(list(self.messages), "messages") != canonical_json(
                list(render_messages(profile, self.parent_program)),
                "rendered messages",
            ):
                raise CollectionIntegrityError(
                    "messages do not match the frozen prompt renderer"
                )
            prompt = profile._mapping["prompt"]
            assert isinstance(prompt, Mapping)
            if (
                self.prompt_revision != prompt["revision"]
                or self.render_revision != prompt["render_revision"]
            ):
                raise CollectionIntegrityError("request prompt-render/profile mismatch")
            provider = profile._mapping["provider"]
            assert isinstance(provider, Mapping)
            decoding = profile._mapping["decoding"]
            assert isinstance(decoding, Mapping)
            expected_payload = {
                "model": provider["model"],
                "messages": list(render_messages(profile, self.parent_program)),
                **dict(decoding),
            }
            if canonical_json(
                dict(self.normalized_adapter_payload),
                "normalized adapter payload",
            ) != canonical_json(
                expected_payload, "expected normalized adapter payload"
            ):
                raise CollectionIntegrityError(
                    "normalized adapter payload differs from the frozen "
                    "model/messages/decoding"
                )
        return self

    @classmethod
    def from_mapping(cls, value: Mapping[str, object], profile: CollectionProfile | None = None) -> "RenderedRequest":
        if type(value) is not dict:
            raise CollectionIntegrityError("rendered request must be an object")
        expected = {
            "request_schema", "sequence_index", "replicate_id", "opportunity_id",
            "birth_step", "parent_bug_id", "child_bug_id", "operator_event_seed",
            "parent_program", "parent_sha256", "profile_sha256", "frozen_world_sha256",
            "prompt_revision", "render_revision",
            "messages", "messages_sha256", "normalized_adapter_payload",
            "normalized_adapter_payload_sha256", "wire_body_sha256",
            "request_sha256",
        }
        _exact_keys(value, expected, "rendered request")
        if value["request_schema"] != REQUEST_SCHEMA:
            raise CollectionIntegrityError(f"request_schema must be {REQUEST_SCHEMA}")
        request = cls(
            sequence_index=value["sequence_index"],
            replicate_id=value["replicate_id"],
            opportunity_id=value["opportunity_id"],
            birth_step=value["birth_step"],
            parent_bug_id=value["parent_bug_id"],
            child_bug_id=value["child_bug_id"],
            operator_event_seed=value["operator_event_seed"],
            parent_program=value["parent_program"],
            messages=value["messages"],
            normalized_adapter_payload=value["normalized_adapter_payload"],
            profile_sha256=value["profile_sha256"],
            frozen_world_sha256=value["frozen_world_sha256"],
            prompt_revision=value["prompt_revision"],
            render_revision=value["render_revision"],
        ).validated(profile)
        expected_mapping = request.to_mapping()
        if canonical_json(value, "rendered request") != canonical_json(expected_mapping, "rendered request"):
            raise CollectionIntegrityError("rendered request checksum or identity mismatch")
        return request


@dataclass(frozen=True)
class ModelResponse:
    """Normalized authentic provider result retained without interpretation."""

    status: str
    raw_text: str | None
    definitive_error: str | None
    provider_request_id: str
    returned_model_revision: str
    finish_reason: str | None
    usage: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.usage, Mapping):
            raise CollectionIntegrityError("usage must be an object")
        usage = _deep_freeze(_copy_json(dict(self.usage), "usage"))
        assert isinstance(usage, Mapping)
        object.__setattr__(self, "usage", usage)

    def to_mapping(self) -> dict[str, object]:
        if self.status not in {"ok", "definitive_error"}:
            raise CollectionIntegrityError("response status must be ok or definitive_error")
        _text(self.provider_request_id, "provider_request_id")
        _text(self.returned_model_revision, "returned_model_revision")
        if not isinstance(self.usage, Mapping):
            raise CollectionIntegrityError("usage must be an object")
        for key in ("input_tokens", "output_tokens"):
            if type(self.usage.get(key)) is not int or self.usage[key] < 0:
                raise CollectionIntegrityError(f"usage.{key} must be a nonnegative integer")
        if self.status == "ok":
            if type(self.raw_text) is not str or self.definitive_error is not None:
                raise CollectionIntegrityError("ok response requires raw_text and no error")
            if self.finish_reason is not None and type(self.finish_reason) is not str:
                raise CollectionIntegrityError("finish_reason must be text or null")
        else:
            if self.raw_text is not None or type(self.definitive_error) is not str or not self.definitive_error or self.finish_reason is not None:
                raise CollectionIntegrityError("definitive_error response requires only an error detail")
        usage = _copy_json(dict(self.usage), "usage")
        return {
            "status": self.status,
            "raw_text": self.raw_text,
            "raw_sha256": sha256_text(self.raw_text) if self.raw_text is not None else None,
            "definitive_error": self.definitive_error,
            "provider_request_id": self.provider_request_id,
            "returned_model_revision": self.returned_model_revision,
            "finish_reason": self.finish_reason,
            "usage": usage,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ModelResponse":
        if type(value) is not dict:
            raise CollectionIntegrityError("response must be an object")
        _exact_keys(value, {"status", "raw_text", "raw_sha256", "definitive_error", "provider_request_id", "returned_model_revision", "finish_reason", "usage"}, "response")
        response = cls(
            status=value["status"], raw_text=value["raw_text"],
            definitive_error=value["definitive_error"],
            provider_request_id=value["provider_request_id"],
            returned_model_revision=value["returned_model_revision"],
            finish_reason=value["finish_reason"], usage=value["usage"],
        )
        if canonical_json(response.to_mapping()) != canonical_json(value):
            raise CollectionIntegrityError("response checksum mismatch")
        return response


class ProviderAdapter(Protocol):
    """Interface a future, explicitly authorized collector must implement."""

    provider_name: str
    adapter_revision: str

    def collect(self, request: RenderedRequest, *, idempotency_key: str) -> ModelResponse: ...


def make_collection_record(
    profile: CollectionProfile,
    request: RenderedRequest,
    response: ModelResponse,
) -> dict[str, object]:
    request.validated(profile)
    body = {
        "cache_schema": CACHE_SCHEMA,
        "cache_key": request.cache_key,
        "sequence_index": request.sequence_index,
        "profile_sha256": profile.profile_sha256,
        "frozen_world_sha256": request.frozen_world_sha256,
        "request": request.to_mapping(),
        "response": response.to_mapping(),
    }
    body["record_sha256"] = canonical_sha256(body, "cache record")
    return validate_collection_record(body, profile)


def validate_collection_record(
    record: Mapping[str, object],
    profile: CollectionProfile | None = None,
) -> dict[str, object]:
    if type(record) is not dict:
        raise CollectionIntegrityError("cache record must be an object")
    _exact_keys(record, {"cache_schema", "cache_key", "sequence_index", "profile_sha256", "frozen_world_sha256", "request", "response", "record_sha256"}, "cache record")
    if record["cache_schema"] != CACHE_SCHEMA:
        raise CollectionIntegrityError(f"cache_schema must be {CACHE_SCHEMA}")
    request = RenderedRequest.from_mapping(record["request"], profile)
    response = ModelResponse.from_mapping(record["response"])
    if record["cache_key"] != request.cache_key or record["sequence_index"] != request.sequence_index:
        raise CollectionIntegrityError("cache record/request identity mismatch")
    if record["profile_sha256"] != request.profile_sha256 or record["frozen_world_sha256"] != request.frozen_world_sha256:
        raise CollectionIntegrityError("cache record provenance mismatch")
    if profile is not None:
        budget = profile._mapping["budget"]
        provider = profile._mapping["provider"]
        assert isinstance(budget, Mapping) and isinstance(provider, Mapping)
        usage = response.usage
        if usage["input_tokens"] > budget["max_input_tokens_per_call"]:
            raise CollectionIntegrityError("record exceeds per-call input-token cap")
        if usage["output_tokens"] > budget["max_output_tokens_per_call"]:
            raise CollectionIntegrityError("record exceeds per-call output-token cap")
        if response.returned_model_revision != provider["model_revision"]:
            raise CollectionIntegrityError("returned model revision/profile mismatch")
    body = dict(record)
    actual = body.pop("record_sha256")
    if actual != canonical_sha256(body, "cache record"):
        raise CollectionIntegrityError("cache record checksum mismatch")
    normalized = _copy_json(record, "cache record")
    assert isinstance(normalized, dict)
    return normalized


@dataclass(frozen=True)
class ResumeInspection:
    completed_count: int
    next_sequence_index: int
    pending_request_sha256: str | None
    at_call_ceiling: bool


def inspect_resume(
    records: Iterable[Mapping[str, object]],
    profile: CollectionProfile,
    *,
    pending: Mapping[str, object] | None = None,
    expected_rendered_prefix: Sequence[RenderedRequest] | None = None,
    expected_schedule: Sequence[tuple[str, int]] | None = None,
) -> ResumeInspection:
    """Validate a contiguous cache sequence in the maximum-slot order.

    Moving to a later replicate provisionally represents a terminal shortfall
    in the earlier one.  Only trajectory replay plus the planned terminal
    manifest can authenticate that transition; this structural inspection
    deliberately does not mark a cache replay-ready.
    """
    seen: set[str] = set()
    provider_request_ids: set[str] = set()
    normalized: list[dict[str, object]] = []
    budget = profile._mapping["budget"]
    assert isinstance(budget, Mapping)
    if (
        expected_schedule is not None
        and len(expected_schedule) != budget["max_calls"]
    ):
        raise CollectionIntegrityError(
            "expected schedule must contain exactly max_calls entries"
        )
    slot_positions = (
        {slot: index for index, slot in enumerate(expected_schedule)}
        if expected_schedule is not None
        else None
    )
    if (
        expected_schedule is not None
        and len(slot_positions) != len(expected_schedule)
    ):
        raise CollectionIntegrityError("maximum slot order contains duplicates")
    last_slot_position = -1
    last_slot: tuple[str, int] | None = None

    def accept_slot(replicate_id: str, opportunity_id: int) -> None:
        nonlocal last_slot_position, last_slot
        assert slot_positions is not None
        slot = (replicate_id, opportunity_id)
        try:
            position = slot_positions[slot]
        except KeyError as exc:
            raise CollectionIntegrityError(
                "request is outside the frozen maximum slot order"
            ) from exc
        if position <= last_slot_position:
            raise CollectionIntegrityError(
                "request reorders the frozen maximum slot order"
            )
        if last_slot is None or replicate_id != last_slot[0]:
            if opportunity_id != 0:
                raise CollectionIntegrityError(
                    "a replicate must begin at opportunity zero"
                )
        elif opportunity_id != last_slot[1] + 1:
            raise CollectionIntegrityError(
                "a replicate contains an opportunity gap"
            )
        last_slot_position = position
        last_slot = slot

    for expected_index, record in enumerate(records):
        entry = validate_collection_record(record, profile)
        if entry["cache_key"] in seen:
            raise CollectionIntegrityError(f"duplicate cache key: {entry['cache_key']}")
        seen.add(str(entry["cache_key"]))
        response = entry["response"]
        assert isinstance(response, Mapping)
        request_id = str(response["provider_request_id"])
        if request_id in provider_request_ids:
            raise CollectionIntegrityError(
                f"duplicate provider request ID: {request_id}"
            )
        provider_request_ids.add(request_id)
        if entry["sequence_index"] != expected_index:
            raise CollectionIntegrityError(f"cache sequence has a hole or is out of order at {expected_index}")
        if expected_index >= budget["max_calls"]:
            raise CollectionIntegrityError("cache contains records beyond max_calls")
        if expected_schedule is not None:
            request = entry["request"]
            assert isinstance(request, Mapping)
            accept_slot(
                str(request["replicate_id"]),
                int(request["opportunity_id"]),
            )
        normalized.append(entry)
    input_tokens = sum(
        int(entry["response"]["usage"]["input_tokens"])
        for entry in normalized
    )
    output_tokens = sum(
        int(entry["response"]["usage"]["output_tokens"])
        for entry in normalized
    )
    if input_tokens > budget["max_input_tokens_total"]:
        raise CollectionIntegrityError("cache exceeds aggregate input-token cap")
    if output_tokens > budget["max_output_tokens_total"]:
        raise CollectionIntegrityError("cache exceeds aggregate output-token cap")
    if expected_rendered_prefix is not None:
        if len(normalized) > len(expected_rendered_prefix):
            raise CollectionIntegrityError("cache has extras beyond the known rendered prefix")
        for index, entry in enumerate(normalized):
            if entry["cache_key"] != expected_rendered_prefix[index].validated(profile).cache_key:
                raise CollectionIntegrityError(f"cache is not the exact rendered prefix at {index}")
    pending_sha: str | None = None
    if pending is not None:
        if len(normalized) >= budget["max_calls"]:
            raise CollectionIntegrityError(
                "pending request exists after the call ceiling"
            )
        request_value = pending.get("request") if type(pending) is dict and set(pending) == {"request"} else None
        if type(request_value) is not dict:
            raise CollectionIntegrityError("pending.json must contain exactly one request")
        pending_request = RenderedRequest.from_mapping(request_value, profile)
        if pending_request.sequence_index != len(normalized):
            raise CollectionIntegrityError("pending request is not the next sequence index")
        if expected_schedule is not None:
            accept_slot(
                pending_request.replicate_id,
                pending_request.opportunity_id,
            )
        if pending_request.cache_key in seen:
            raise CollectionIntegrityError("pending request duplicates a committed record")
        pending_sha = pending_request.request_sha256
    return ResumeInspection(
        completed_count=len(normalized),
        next_sequence_index=len(normalized),
        pending_request_sha256=pending_sha,
        at_call_ceiling=len(normalized) == budget["max_calls"],
    )


def read_jsonl_cache(
    path: str | Path,
    profile: CollectionProfile,
    *,
    expected_schedule: Sequence[tuple[str, int]] | None = None,
) -> ResumeInspection:
    records: list[Mapping[str, object]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CollectionIntegrityError(f"cannot read collection cache: {exc}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        value = _strict_json(line)
        if type(value) is not dict:
            raise CollectionIntegrityError(f"cache line {number} must be an object")
        records.append(value)
    return inspect_resume(records, profile, expected_schedule=expected_schedule)


def inspect_spool(
    path: str | Path,
    profile: CollectionProfile,
    *,
    expected_schedule: Sequence[tuple[str, int]] | None = None,
) -> ResumeInspection:
    root = Path(path)
    record_dir = root / "records"
    try:
        root_entries = list(root.iterdir())
        record_mode = record_dir.stat(follow_symlinks=False).st_mode
    except OSError as exc:
        raise CollectionIntegrityError(f"cannot inspect collection spool: {exc}") from exc
    if not stat.S_ISDIR(record_mode):
        raise CollectionIntegrityError(
            "spool records entry must be a real directory"
        )
    unknown = {entry.name for entry in root_entries} - {"records", "pending.json"}
    if unknown:
        raise CollectionIntegrityError(f"unknown spool entries: {sorted(unknown)}")
    try:
        record_entries = sorted(record_dir.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise CollectionIntegrityError(f"cannot list spool records: {exc}") from exc
    records: list[Mapping[str, object]] = []
    for expected_index, record_path in enumerate(record_entries):
        try:
            record_mode = record_path.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise CollectionIntegrityError(
                f"cannot inspect spool record {record_path.name}: {exc}"
            ) from exc
        if not stat.S_ISREG(record_mode) or record_path.suffix != ".json":
            raise CollectionIntegrityError(
                f"unrecognized or non-regular spool record: {record_path.name}"
            )
        expected_prefix = f"{expected_index:06d}-"
        if not record_path.name.startswith(expected_prefix):
            raise CollectionIntegrityError("spool record filenames have a hole or extra")
        try:
            text = record_path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CollectionIntegrityError(
                f"cannot read spool record {record_path.name} as UTF-8: {exc}"
            ) from exc
        value = _strict_json(text)
        if type(value) is not dict:
            raise CollectionIntegrityError("spool record must be an object")
        expected_name = f"{expected_index:06d}-{str(value.get('cache_key', ''))[7:]}.json"
        if record_path.name != expected_name:
            raise CollectionIntegrityError("spool record filename/cache key mismatch")
        records.append(value)
    pending_path = root / "pending.json"
    pending = None
    if any(entry.name == "pending.json" for entry in root_entries):
        try:
            pending_mode = pending_path.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise CollectionIntegrityError(
                f"cannot inspect pending.json: {exc}"
            ) from exc
        if not stat.S_ISREG(pending_mode):
            raise CollectionIntegrityError("pending.json must be a regular file")
        try:
            pending_text = pending_path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CollectionIntegrityError(
                f"cannot read pending.json as UTF-8: {exc}"
            ) from exc
        pending = _strict_json(pending_text)
        if type(pending) is not dict:
            raise CollectionIntegrityError("pending.json must be an object")
    return inspect_resume(
        records,
        profile,
        pending=pending,
        expected_schedule=expected_schedule,
    )


@dataclass(frozen=True)
class CollectionPlan:
    status: str
    profile_sha256: str
    max_calls: int
    max_input_tokens_per_call: int
    max_input_tokens_total: int
    max_output_tokens_per_call: int
    max_output_tokens_total: int
    max_cost_usd: float
    cost_formula: str
    pricing: Mapping[str, object]
    worst_case_cost_usd: float | None
    input_token_cap_status: str
    blockers: Sequence[str]
    trajectory_dependency: Mapping[str, object]

    def __post_init__(self) -> None:
        pricing = _deep_freeze(_copy_json(self.pricing, "pricing"))
        dependency = _deep_freeze(
            _copy_json(self.trajectory_dependency, "trajectory dependency")
        )
        assert isinstance(pricing, Mapping)
        assert isinstance(dependency, Mapping)
        object.__setattr__(self, "pricing", pricing)
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "trajectory_dependency", dependency)

    @classmethod
    def from_profile(cls, profile: CollectionProfile) -> "CollectionPlan":
        budget = profile._mapping["budget"]
        pricing = profile._mapping["pricing"]
        dependency = profile._mapping["trajectory_dependency"]
        assert isinstance(budget, Mapping) and isinstance(pricing, Mapping) and isinstance(dependency, Mapping)
        status = (
            "blocked_pending_provider_selection"
            if profile.status == "blocked_pending_provider_selection"
            else "blocked_pending_explicit_authorization"
        )
        blockers = (
            (
                "provider_selection",
                "tokenizer_identity",
                "input_counter_revision",
                "timeout_policy",
                "idempotency_policy",
                "wire_protocol",
                "provider_adapter",
                "sequential_collector",
                "schema_v2_replay_operator",
                "pricing",
                "terminal_manifest_support",
            )
            if profile.status == "blocked_pending_provider_selection"
            else ("explicit_authorization",)
        )
        formula = (
            f"({budget['max_input_tokens_total']} * input_usd_per_million_tokens + "
            f"{budget['max_output_tokens_total']} * output_usd_per_million_tokens) / "
            f"1000000 + ({budget['max_calls']} * request_usd)"
        )
        worst_cost = None
        if pricing["status"] == "frozen":
            worst_cost = (
                budget["max_input_tokens_total"]
                * pricing["input_usd_per_million_tokens"]
                + budget["max_output_tokens_total"]
                * pricing["output_usd_per_million_tokens"]
            ) / 1_000_000 + budget["max_calls"] * pricing["request_usd"]
        return cls(
            status=status, profile_sha256=profile.profile_sha256,
            max_calls=int(budget["max_calls"]),
            max_input_tokens_per_call=int(
                budget["max_input_tokens_per_call"]
            ),
            max_input_tokens_total=int(budget["max_input_tokens_total"]),
            max_output_tokens_per_call=int(
                budget["max_output_tokens_per_call"]
            ),
            max_output_tokens_total=int(budget["max_output_tokens_total"]),
            max_cost_usd=float(budget["max_cost_usd"]), cost_formula=formula,
            pricing=_copy_json(pricing, "pricing"),
            worst_case_cost_usd=worst_cost,
            input_token_cap_status=str(budget["input_token_cap_status"]),
            blockers=blockers,
            trajectory_dependency=_copy_json(dependency, "trajectory dependency"),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": 1, "status": self.status,
            "profile_sha256": self.profile_sha256,
            "limits": {
                "max_calls": self.max_calls,
                "max_input_tokens_per_call": self.max_input_tokens_per_call,
                "max_input_tokens_total": self.max_input_tokens_total,
                "max_output_tokens_per_call": self.max_output_tokens_per_call,
                "max_output_tokens_total": self.max_output_tokens_total,
                "max_cost_usd": self.max_cost_usd,
            },
            "cost_formula": self.cost_formula,
            "pricing": _copy_json(self.pricing, "pricing"),
            "worst_case_cost_usd": self.worst_case_cost_usd,
            "input_token_cap_status": self.input_token_cap_status,
            "blockers": list(self.blockers),
            "trajectory_dependency": _copy_json(self.trajectory_dependency, "trajectory dependency"),
            "network_calls_made": 0,
            "credentials_read": False,
        }


def _strict_json(text: str) -> object:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CollectionIntegrityError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject(token: str) -> None:
        raise CollectionIntegrityError(f"non-finite JSON number: {token}")

    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=reject)
    except CollectionIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CollectionIntegrityError(f"malformed JSON: {exc}") from exc


__all__ = [
    "CACHE_SCHEMA", "CollectionIntegrityError", "CollectionPlan",
    "CollectionProfile", "HARD_MAX_CALLS", "HARD_MAX_COST_USD",
    "HARD_MAX_INPUT_TOKENS_PER_CALL",
    "HARD_MAX_OUTPUT_TOKENS_PER_CALL", "ModelResponse", "ProviderAdapter",
    "RenderedRequest", "ResumeInspection", "canonical_json",
    "canonical_sha256", "inspect_resume", "inspect_spool",
    "make_collection_record", "read_jsonl_cache", "render_messages",
    "sha256_bytes", "sha256_text",
    "validate_collection_record",
]
