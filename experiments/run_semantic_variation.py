#!/usr/bin/env python3
"""Replay a frozen 24-case semantic-variation micro-study.

The model-facing surface is deliberately outside this script.  This file only
defines the fixed requests, validates one recorded JSONL response per request,
constructs proposal-count and edit-mask matched controls, and runs the ecology
offline.  Invalid recorded responses consume their opportunity and inherit the
parent program exactly; there is no repair, retry, ranking, or model call here.
"""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Iterable, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evolve4.control import IVPercept
from evolve4.randomness import EcologyRandomStreams, IVSeedPlan
from evolve4.simulation import MetabolicConfig, MetabolicSim
from evolve_modern.iv import IVProgramController, build_controlled_sim
from evolve_modern.iv_policies import (
    Construction,
    DEFAULT_IV_PROGRAMS,
    IVProgram,
    Movement,
    PolicyValidationError,
    decide_program,
)


STUDY_ID = "semantic-variation-v1"
CACHE_SCHEMA = 1
CACHE_PATH = ROOT / "experiments" / "cache" / f"{STUDY_ID}.jsonl"
RESULT_PATH = ROOT / "results" / STUDY_ID
REQUESTED_MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "low"

# Programs with a nonzero construction trait.  This leaves three producers and
# three recyclers and ensures every construction-policy edit can be expressed.
PARENT_INDICES = (0, 1, 3, 4, 6, 7)
CHANGE_MASKS = (
    ("movement", "construction", "reproduce_at"),
    ("movement", "construction", "require_uncrowded"),
    ("movement", "reproduce_at", "require_uncrowded"),
    ("construction", "reproduce_at", "require_uncrowded"),
)
ARMS = ("parent", "typed_macro", "random_same_mask", "codex_agent_itt")
EVIDENCE_SEEDS = tuple(range(7100, 7108))
QUALIFICATION_SEEDS = tuple(range(7096, 7100))

# Audit log for two model-blind qualification executions on the same held-out
# seeds.  The second followed code review: it added an absolute lineage AUC,
# fixed recovery-step/capacity accounting, and replaced a saturated novelty
# diagnostic.  It did not tune the world, horizon, intervention, case bank, or
# primary establishment endpoint.  No authentic proposal had been collected.
QUALIFICATION_LOG = {
    "runs": 2,
    "date_utc": "2026-09-04",
    "performed_before_authentic_responses": True,
    "changes_after_first_run": [
        "added absolute lineage-alive AUC and demoted lineage share to a compositional diagnostic",
        "made recovery steps one-based",
        "corrected copied-history capacity accounting and made capacity blocking non-exclusionary",
        "replaced raw-intent novelty with component-wise effective-action novelty",
        "strengthened cache and collection-envelope validation",
    ],
    "changes_after_second_run": [],
    "seeds": list(QUALIFICATION_SEEDS),
    "command": "PYTHONPATH=src python3 experiments/run_semantic_variation.py --qualify",
    "result": {
        "all_conserved": True,
        "capacity_blocked_births": 0,
        "arm_diagnostics": {
            "parent": {
                "establishment_rate": 0.375,
                "mean_lineage_alive_auc_gap": -34.875,
                "mean_lineage_auc_gap": -0.35258025569304846,
                "recovery_censor_rate": 0.75,
            },
            "random_same_mask": {
                "establishment_rate": 0.40625,
                "mean_lineage_alive_auc_gap": -21.729166666666668,
                "mean_lineage_auc_gap": -0.16862819767775875,
                "recovery_censor_rate": 0.4479166666666667,
            },
            "typed_macro": {
                "establishment_rate": 0.4479166666666667,
                "mean_lineage_alive_auc_gap": -71.15625,
                "mean_lineage_auc_gap": -1.1563901396715568,
                "recovery_censor_rate": 0.4375,
            },
        },
    },
}

PRE_STEPS = 80
FAMINE_STEPS = 20
POST_RESTORE_STEPS = 60
TOTAL_STEPS = PRE_STEPS + FAMINE_STEPS + POST_RESTORE_STEPS
NORMAL_HARVEST = 4
FAMINE_HARVEST = 1
PRE_WINDOW = 20
RECOVERY_FRACTION = 0.90
RECOVERY_RUN = 3

WORLD = {
    "n_places": 128,
    "total_units": 800,
    "n_organisms": 16,
    "max_organisms": 176,
    "steps": TOTAL_STEPS,
    "harvest": NORMAL_HARVEST,
    "convert_yield": 3,
    "excrete": 2,
    "repro_threshold": 14,
    "mut_prob": 0.0,
    "construction": True,
    "condition_decay": 0.18,
    "verbose_every": 0,
}

PROMPT_PREFIX = (
    "You are a program-variation operator, not a fitness evaluator. Return "
    "exactly one JSON object and nothing else. The object must have exactly "
    "schema, traits, movement, construction, reproduce_at, "
    "require_uncrowded; traits must have exactly role, taste, construct. "
    "Domains: schema=1; role producer|recycler; taste -1|1; construct "
    "-1|0|1; movement default|stay_if_fed|seek_resource|seek_opposite; "
    "construction always|never|until_nonzero; reproduce_at integer 8..30; "
    "require_uncrowded boolean. Preserve traits and every field not listed "
    "in CHANGE_PATHS exactly. Change every field in CHANGE_PATHS to a "
    "different legal value. Choose their new values jointly as one coherent "
    "alternative strategy. Do not score, rank, explain, use tools, or wrap "
    "the JSON in Markdown."
)

PROGRAM_PATHS = (
    "traits.role",
    "traits.taste",
    "traits.construct",
    "movement",
    "construction",
    "reproduce_at",
    "require_uncrowded",
)

TOP_CACHE_KEYS = frozenset(
    {
        "schema",
        "study_id",
        "sequence",
        "case_id",
        "parent_index",
        "change_paths",
        "parent_program",
        "prompt",
        "prompt_sha256",
        "request_bank_sha256",
        "protocol_commit",
        "surface",
        "response",
        "validation",
    }
)
SURFACE_KEYS = frozenset(
    {
        "kind",
        "artifact_class",
        "attestation_basis",
        "auth_mode",
        "study_supplied_api_key",
        "direct_api_billing_exposure",
        "subscription_usage_exposure",
        "requested_model",
        "reasoning_effort",
        "returned_model_revision",
        "revision_exposure",
        "provider_request_id_exposure",
        "provider_wire_exposure",
        "hidden_instructions_exposure",
        "tool_activity_exposure",
        "internal_retry_exposure",
        "context_fork",
        "task_message_sha256",
        "task_name",
        "capture",
        "batch_id",
        "client_visible_turns",
        "application_retries",
        "orchestrator_task_path",
        "collected_at_utc",
    }
)
RESPONSE_KEYS = frozenset(
    {
        "status",
        "captured_final_answer_text",
        "captured_final_answer_sha256",
        "failure_detail",
    }
)
VALIDATION_KEYS = frozenset(
    {"valid", "status", "candidate_program", "changed_paths"}
)


class CacheError(RuntimeError):
    """Raised when frozen responses do not exactly match the study plan."""


@dataclass(frozen=True)
class StudyCase:
    sequence: int
    case_id: str
    parent_index: int
    parent: IVProgram
    change_paths: tuple[str, ...]
    prompt: str


@dataclass(frozen=True)
class Validation:
    valid: bool
    status: str
    candidate_program: str | None
    changed_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "status": self.status,
            "candidate_program": self.candidate_program,
            "changed_paths": list(self.changed_paths),
        }


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CacheError(f"value is not canonical JSON data: {exc}") from exc


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def strict_json(value: str, label: str) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise CacheError(f"{label} has duplicate JSON key {key!r}")
            result[key] = item
        return result

    def reject_constant(token: str) -> None:
        raise CacheError(f"{label} contains non-finite number {token}")

    try:
        return json.loads(
            value,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except CacheError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CacheError(f"malformed {label}: {exc}") from exc


def exact_keys(value: object, expected: frozenset[str], label: str) -> dict:
    if type(value) is not dict:
        raise CacheError(f"{label} must be a JSON object")
    if set(value) != expected:
        raise CacheError(
            f"{label} keys differ; missing={sorted(expected - set(value))}, "
            f"unknown={sorted(set(value) - expected)}"
        )
    return value


def build_prompt(parent: IVProgram, change_paths: Sequence[str]) -> str:
    return (
        f"{PROMPT_PREFIX}\n"
        f"PARENT={parent.to_json()}\n"
        f"CHANGE_PATHS={canonical_json(list(change_paths))}"
    )


def study_cases() -> tuple[StudyCase, ...]:
    result: list[StudyCase] = []
    for parent_index in PARENT_INDICES:
        parent = DEFAULT_IV_PROGRAMS[parent_index]
        for change_paths in CHANGE_MASKS:
            sequence = len(result)
            result.append(
                StudyCase(
                    sequence=sequence,
                    case_id=f"case-{sequence:02d}",
                    parent_index=parent_index,
                    parent=parent,
                    change_paths=change_paths,
                    prompt=build_prompt(parent, change_paths),
                )
            )
    return tuple(result)


def field_value(program: IVProgram, path: str) -> object:
    if path == "traits.role":
        return program.role
    if path == "traits.taste":
        return program.taste
    if path == "traits.construct":
        return program.construct
    return getattr(program, path)


def changed_paths(parent: IVProgram, candidate: IVProgram) -> tuple[str, ...]:
    return tuple(
        path
        for path in PROGRAM_PATHS
        if field_value(parent, path) != field_value(candidate, path)
    )


def validate_response(case: StudyCase, raw_text: str | None) -> Validation:
    if raw_text is None:
        return Validation(False, "surface_error", None, ())
    try:
        candidate = IVProgram.from_json(raw_text)
    except PolicyValidationError:
        return Validation(False, "malformed_or_wrong_schema", None, ())

    actual = changed_paths(case.parent, candidate)
    if any(
        field_value(case.parent, path) != field_value(candidate, path)
        for path in ("traits.role", "traits.taste", "traits.construct")
    ):
        return Validation(False, "wrong_traits", candidate.to_json(), actual)
    if set(actual) != set(case.change_paths) or len(actual) != len(case.change_paths):
        return Validation(
            False,
            "wrong_change_support",
            candidate.to_json(),
            actual,
        )
    return Validation(True, "valid", candidate.to_json(), actual)


def request_payloads() -> list[dict[str, object]]:
    """Return the exact independent requests used by the external collector."""
    return [
        {
            "schema": CACHE_SCHEMA,
            "study_id": STUDY_ID,
            "sequence": case.sequence,
            "case_id": case.case_id,
            "parent_index": case.parent_index,
            "change_paths": list(case.change_paths),
            "parent_program": case.parent.to_json(),
            "prompt": case.prompt,
            "prompt_sha256": sha256_text(case.prompt),
            "requested_model": REQUESTED_MODEL,
            "reasoning_effort": REASONING_EFFORT,
        }
        for case in study_cases()
    ]


def request_bank_sha256() -> str:
    return sha256_text(canonical_json(request_payloads()))


def load_cache(path: Path = CACHE_PATH) -> tuple[dict[str, object], ...]:
    if not path.is_file():
        raise CacheError(f"missing frozen response cache: {path}")
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    if any(not line for line in raw_lines):
        raise CacheError("response cache must not contain blank lines")
    cases = study_cases()
    if len(raw_lines) != len(cases):
        raise CacheError(
            f"response cache has {len(raw_lines)} lines; expected {len(cases)}"
        )

    records: list[dict[str, object]] = []
    task_paths: set[str] = set()
    protocol_commits: set[str] = set()
    for line, case in zip(raw_lines, cases, strict=True):
        record = exact_keys(strict_json(line, "cache record"), TOP_CACHE_KEYS, "cache record")
        if canonical_json(record) != line:
            raise CacheError(f"{case.case_id} cache line is not canonical JSON")
        expected_scalars = {
            "schema": CACHE_SCHEMA,
            "study_id": STUDY_ID,
            "sequence": case.sequence,
            "case_id": case.case_id,
            "parent_index": case.parent_index,
            "change_paths": list(case.change_paths),
            "parent_program": case.parent.to_json(),
            "prompt": case.prompt,
            "prompt_sha256": sha256_text(case.prompt),
            "request_bank_sha256": request_bank_sha256(),
        }
        for key, expected in expected_scalars.items():
            if type(record[key]) is not type(expected) or record[key] != expected:
                raise CacheError(f"{case.case_id} {key} does not match study plan")

        surface = exact_keys(record["surface"], SURFACE_KEYS, "surface")
        expected_surface = {
            "kind": "chatgpt_work_codex_subagent_v1",
            "artifact_class": "orchestrator_attested_final_answer",
            "attestation_basis": "captured_fresh_subagent_final_channel",
            "auth_mode": "chatgpt_subscription",
            "study_supplied_api_key": False,
            "direct_api_billing_exposure": "not_applicable_no_direct_api_call",
            "subscription_usage_exposure": "not_exposed",
            "requested_model": REQUESTED_MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "returned_model_revision": None,
            "revision_exposure": "not_exposed",
            "provider_request_id_exposure": "not_exposed",
            "provider_wire_exposure": "not_exposed",
            "hidden_instructions_exposure": "not_exposed",
            "tool_activity_exposure": "not_exposed",
            "internal_retry_exposure": "not_exposed",
            "context_fork": "none",
            "task_message_sha256": sha256_text(case.prompt),
            "task_name": f"semantic_{case.sequence:02d}",
            "capture": "final_channel_only",
            "batch_id": "semantic-variation-v1-2026-09-04",
            "client_visible_turns": 1,
            "application_retries": 0,
        }
        for key, expected in expected_surface.items():
            if type(surface[key]) is not type(expected) or surface[key] != expected:
                raise CacheError(f"{case.case_id} surface {key} is invalid")
        task_path = surface["orchestrator_task_path"]
        if type(task_path) is not str or not task_path.startswith("/root/"):
            raise CacheError(f"{case.case_id} has invalid orchestrator task path")
        if task_path in task_paths:
            raise CacheError("orchestrator task paths must be unique")
        if task_path != f"/root/semantic_{case.sequence:02d}":
            raise CacheError(f"{case.case_id} task path does not match task name")
        task_paths.add(task_path)
        protocol_commit = record["protocol_commit"]
        if (
            type(protocol_commit) is not str
            or len(protocol_commit) != 40
            or any(character not in "0123456789abcdef" for character in protocol_commit)
        ):
            raise CacheError(f"{case.case_id} protocol commit is not a full SHA")
        protocol_commits.add(protocol_commit)
        collected_at = surface["collected_at_utc"]
        if type(collected_at) is not str:
            raise CacheError(f"{case.case_id} has invalid collection time")
        try:
            parsed_time = datetime.strptime(collected_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise CacheError(
                f"{case.case_id} collection time must be UTC second precision"
            ) from exc
        if parsed_time.year < 2026:
            raise CacheError(f"{case.case_id} collection time is implausible")

        response = exact_keys(record["response"], RESPONSE_KEYS, "response")
        if response["status"] == "ok":
            raw_text = response["captured_final_answer_text"]
            if type(raw_text) is not str:
                raise CacheError(f"{case.case_id} ok response needs raw text")
            if response["captured_final_answer_sha256"] != sha256_text(raw_text):
                raise CacheError(f"{case.case_id} raw response checksum mismatch")
            if response["failure_detail"] is not None:
                raise CacheError(f"{case.case_id} ok response has failure detail")
        elif response["status"] == "surface_error":
            raw_text = None
            if (
                response["captured_final_answer_text"] is not None
                or response["captured_final_answer_sha256"] is not None
            ):
                raise CacheError(f"{case.case_id} surface error has raw response")
            if type(response["failure_detail"]) is not str or not response["failure_detail"]:
                raise CacheError(f"{case.case_id} surface error needs detail")
        else:
            raise CacheError(f"{case.case_id} has unknown response status")

        observed_validation = exact_keys(
            record["validation"], VALIDATION_KEYS, "validation"
        )
        if type(observed_validation["valid"]) is not bool:
            raise CacheError(f"{case.case_id} validation valid must be boolean")
        if type(observed_validation["status"]) is not str:
            raise CacheError(f"{case.case_id} validation status must be text")
        if type(observed_validation["changed_paths"]) is not list or not all(
            type(path) is str for path in observed_validation["changed_paths"]
        ):
            raise CacheError(f"{case.case_id} validation paths must be text list")
        expected_validation = validate_response(case, raw_text).to_dict()
        if observed_validation != expected_validation:
            raise CacheError(f"{case.case_id} validation does not recompute")
        records.append(record)
    if len(protocol_commits) != 1:
        raise CacheError("all records must bind the same protocol commit")
    return tuple(records)


def candidate_from_cache(case: StudyCase, record: Mapping[str, object]) -> IVProgram:
    validation = record["validation"]
    assert isinstance(validation, Mapping)
    if validation["valid"] is not True:
        return case.parent
    candidate = validation["candidate_program"]
    assert isinstance(candidate, str)
    return IVProgram.from_json(candidate)


def replace_program_field(program: IVProgram, path: str, value: object) -> IVProgram:
    if path == "movement":
        return replace(program, movement=value)
    if path == "construction":
        return replace(program, construction=value)
    if path == "reproduce_at":
        return replace(program, reproduce_at=value)
    if path == "require_uncrowded":
        return replace(program, require_uncrowded=value)
    raise ValueError(f"unsupported behavioral path {path}")


def typed_macro(case: StudyCase) -> IVProgram:
    """A predeclared domain heuristic changing the same three controls."""
    candidate = case.parent
    for path in case.change_paths:
        current = field_value(candidate, path)
        if path == "movement":
            value = (
                Movement.SEEK_OPPOSITE
                if current is Movement.SEEK_RESOURCE
                else Movement.SEEK_RESOURCE
            )
        elif path == "construction":
            value = (
                Construction.ALWAYS
                if current is Construction.UNTIL_NONZERO
                else Construction.UNTIL_NONZERO
            )
        elif path == "reproduce_at":
            value = 18 if int(current) <= 14 else 12
        else:
            value = not bool(current)
        candidate = replace_program_field(candidate, path, value)
    if set(changed_paths(case.parent, candidate)) != set(case.change_paths):
        raise RuntimeError(f"typed macro failed exact mask for {case.case_id}")
    return candidate


def random_same_mask(case: StudyCase) -> IVProgram:
    """Uniform independent alternative per field under the same fixed mask."""
    rng = np.random.Generator(
        np.random.PCG64(
            int(
                np.random.SeedSequence([2026, case.sequence, 0x53454D]).generate_state(
                    1, dtype=np.uint64
                )[0]
            )
        )
    )
    candidate = case.parent
    domains: dict[str, tuple[object, ...]] = {
        "movement": tuple(Movement),
        "construction": tuple(Construction),
        "reproduce_at": tuple(range(8, 31)),
        "require_uncrowded": (False, True),
    }
    for path in case.change_paths:
        current = field_value(candidate, path)
        alternatives = tuple(value for value in domains[path] if value != current)
        value = alternatives[int(rng.integers(0, len(alternatives)))]
        candidate = replace_program_field(candidate, path, value)
    if set(changed_paths(case.parent, candidate)) != set(case.change_paths):
        raise RuntimeError(f"random baseline failed exact mask for {case.case_id}")
    return candidate


def percept_panel() -> tuple[IVPercept, ...]:
    result = []
    stocks = ((0, 0, 0), (3, 1, 0), (0, 3, 1), (0, 1, 3))
    opposites = ((False, False), (True, False), (False, True), (True, True))
    for stock_here, stock_left, stock_right in stocks:
        for condition in (-1, 0, 1):
            for stored in (7, 10, 14, 18, 24, 30):
                for crowded in (False, True):
                    for opposite_left, opposite_right in opposites:
                        result.append(
                            IVPercept(
                                bug_id=1,
                                step=0,
                                position=0,
                                left=7,
                                right=1,
                                stock_here=stock_here,
                                stock_left=stock_left,
                                stock_right=stock_right,
                                condition_here=condition,
                                stored=stored,
                                repro_threshold=14,
                                crowded=crowded,
                                opposite_left=opposite_left,
                                opposite_right=opposite_right,
                                n_opposite=int(opposite_left) + int(opposite_right),
                            )
                        )
    return tuple(result)


PERCEPT_PANEL = percept_panel()


def effective_actions(program: IVProgram, percept: IVPercept) -> tuple[object, ...]:
    intent = decide_program(program, percept)
    return (
        intent.movement.value,
        intent.target_position,
        intent.construct,
        intent.reproduce
        and intent.repro_threshold is not None
        and percept.stored >= intent.repro_threshold,
    )


def behavioral_novelty_components(
    parent: IVProgram,
    candidate: IVProgram,
) -> dict[str, float]:
    counts = [0, 0, 0]
    for percept in PERCEPT_PANEL:
        before = effective_actions(parent, percept)
        after = effective_actions(candidate, percept)
        counts[0] += before[:2] != after[:2]
        counts[1] += before[2] != after[2]
        counts[2] += before[3] != after[3]
    components = {
        "movement": counts[0] / len(PERCEPT_PANEL),
        "construction": counts[1] / len(PERCEPT_PANEL),
        "reproduction": counts[2] / len(PERCEPT_PANEL),
    }
    components["mean"] = mean(components.values())
    return components


def initial_programs(case: StudyCase, candidate: IVProgram) -> tuple[IVProgram, ...]:
    programs = list(DEFAULT_IV_PROGRAMS) * 2
    programs[case.parent_index] = candidate
    return tuple(programs)


def build_assay(case: StudyCase, candidate: IVProgram, seed: int) -> MetabolicSim:
    plan = IVSeedPlan.from_master(seed)
    sim, _controller = build_controlled_sim(
        MetabolicConfig(seed=seed, **WORLD),
        controller_seed=plan.variation_gate,
        proposal_seed=plan.operator,
        mutation_probability=0.0,
        programs=initial_programs(case, candidate),
        experiment_id=STUDY_ID,
        replicate_id=f"{case.case_id}-seed-{seed}",
        random_streams=EcologyRandomStreams.from_plan(plan),
    )
    return sim


def jsonable(value: object) -> object:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def physical_state_payload(sim: MetabolicSim) -> dict[str, object]:
    return {
        "places": [asdict(place) for place in sim.places],
        "bugs": [asdict(bug) for bug in sim.bugs],
        "next_bug_id": sim._next,
        "ecology_rng": sim.random_streams.state_dict(),
    }


def complete_state_hash(sim: MetabolicSim) -> str:
    controller = sim.controller
    if not isinstance(controller, IVProgramController):
        raise TypeError("semantic assay requires IVProgramController")
    payload = {
        "config": asdict(sim.cfg),
        "physical": physical_state_payload(sim),
        "history": [asdict(row) for row in sim.history],
        "controller_records": controller.record_payload(),
        "controller_rng": controller.rng.bit_generator.state,
        "proposal_rng": controller.proposal_rng.bit_generator.state,
    }
    return sha256_text(canonical_json(jsonable(payload)))


def physical_state_hash(sim: MetabolicSim) -> str:
    return sha256_text(canonical_json(jsonable(physical_state_payload(sim))))


def lineage_snapshot(sim: MetabolicSim, root_bug_id: int) -> dict[str, float | int | bool]:
    controller = sim.controller
    if not isinstance(controller, IVProgramController):
        raise TypeError("semantic assay requires IVProgramController")
    depths = {root_bug_id: 0}
    for bug_id in sorted(controller.records):
        if bug_id == root_bug_id:
            continue
        parent_id = controller.records[bug_id].parent_bug_id
        if parent_id in depths:
            depths[bug_id] = depths[parent_id] + 1
    living = [bug for bug in sim.bugs if bug.alive]
    living_lineage = [bug for bug in living if bug.bug_id in depths]
    living_depth_two = [bug for bug in living_lineage if depths[bug.bug_id] >= 2]
    return {
        "lineage_alive": len(living_lineage),
        "depth_two_alive": len(living_depth_two),
        "lineage_share": len(living_lineage) / len(living) if living else 0.0,
        "alive": len(living),
        "established": bool(living_depth_two),
    }


def recovery_time(shocked: Sequence[int], shadow: Sequence[int]) -> int | None:
    flags = [left >= RECOVERY_FRACTION * right for left, right in zip(shocked, shadow)]
    for index in range(len(flags) - RECOVERY_RUN + 1):
        if all(flags[index : index + RECOVERY_RUN]):
            # The first comparison is the state after one restored-harvest step.
            return index + 1
    return None


def run_assay(
    case: StudyCase,
    arm: str,
    candidate: IVProgram,
    seed: int,
    *,
    candidate_status: str,
) -> dict[str, object]:
    sim = build_assay(case, candidate, seed)
    initial_hash = physical_state_hash(sim)
    root_bug_id = case.parent_index + 1
    pre_snapshots = []
    conservation_ok = sim.conserved() == WORLD["total_units"]
    for _step in range(PRE_STEPS):
        sim.step()
        conservation_ok = conservation_ok and sim.conserved() == WORLD["total_units"]
        pre_snapshots.append(lineage_snapshot(sim, root_bug_id))

    shock_state = lineage_snapshot(sim, root_bug_id)
    pre_hash = complete_state_hash(sim)
    shocked = copy.deepcopy(sim)
    shadow = copy.deepcopy(sim)
    if complete_state_hash(shocked) != pre_hash or complete_state_hash(shadow) != pre_hash:
        raise RuntimeError("deep-copied pre-shock branches are not identical")

    shocked_post: list[dict[str, float | int | bool]] = []
    shadow_post: list[dict[str, float | int | bool]] = []
    shocked.cfg.harvest = FAMINE_HARVEST
    for offset in range(FAMINE_STEPS + POST_RESTORE_STEPS):
        if offset == FAMINE_STEPS:
            shocked.cfg.harvest = NORMAL_HARVEST
        shocked.step()
        shadow.step()
        conservation_ok = (
            conservation_ok
            and shocked.conserved() == WORLD["total_units"]
            and shadow.conserved() == WORLD["total_units"]
        )
        shocked_post.append(lineage_snapshot(shocked, root_bug_id))
        shadow_post.append(lineage_snapshot(shadow, root_bug_id))

    restore = FAMINE_STEPS
    shocked_recovery = shocked_post[restore:]
    shadow_recovery = shadow_post[restore:]
    shocked_lineage_auc = sum(float(row["lineage_share"]) for row in shocked_recovery)
    shadow_lineage_auc = sum(float(row["lineage_share"]) for row in shadow_recovery)
    shocked_lineage_alive_auc = sum(int(row["lineage_alive"]) for row in shocked_recovery)
    shadow_lineage_alive_auc = sum(int(row["lineage_alive"]) for row in shadow_recovery)
    shocked_population_auc = sum(int(row["alive"]) for row in shocked_recovery)
    shadow_population_auc = sum(int(row["alive"]) for row in shadow_recovery)
    recovery = recovery_time(
        [int(row["alive"]) for row in shocked_recovery],
        [int(row["alive"]) for row in shadow_recovery],
    )
    pre_blocked = sum(row.capacity_blocked_births for row in sim.history)
    shocked_blocked = sum(
        row.capacity_blocked_births for row in shocked.history[PRE_STEPS:]
    )
    shadow_blocked = sum(
        row.capacity_blocked_births for row in shadow.history[PRE_STEPS:]
    )
    novelty = behavioral_novelty_components(case.parent, candidate)
    return {
        "study_id": STUDY_ID,
        "case_id": case.case_id,
        "parent_index": case.parent_index,
        "change_paths": canonical_json(list(case.change_paths)),
        "seed": seed,
        "arm": arm,
        "candidate_status": candidate_status,
        "candidate_program": candidate.to_json(),
        "field_hamming": len(changed_paths(case.parent, candidate)),
        "behavioral_novelty": novelty["mean"],
        "movement_novelty": novelty["movement"],
        "construction_novelty": novelty["construction"],
        "reproduction_novelty": novelty["reproduction"],
        "initial_physical_sha256": initial_hash,
        "pre_shock_state_sha256": pre_hash,
        "established_at_shock": bool(shock_state["established"]),
        "pre_shock_lineage_share": sum(
            float(row["lineage_share"]) for row in pre_snapshots[-PRE_WINDOW:]
        )
        / PRE_WINDOW,
        "focal_survived_famine": bool(shocked_post[FAMINE_STEPS - 1]["lineage_alive"]),
        "shocked_lineage_share_auc": shocked_lineage_auc,
        "shadow_lineage_share_auc": shadow_lineage_auc,
        "lineage_share_auc_gap": shocked_lineage_auc - shadow_lineage_auc,
        "shocked_lineage_alive_auc": shocked_lineage_alive_auc,
        "shadow_lineage_alive_auc": shadow_lineage_alive_auc,
        "lineage_alive_auc_gap": shocked_lineage_alive_auc
        - shadow_lineage_alive_auc,
        "shocked_population_auc": shocked_population_auc,
        "shadow_population_auc": shadow_population_auc,
        "population_auc_gap": shocked_population_auc - shadow_population_auc,
        "population_recovery_steps": recovery,
        "population_recovery_censored": recovery is None,
        "conservation_ok": conservation_ok,
        "pre_capacity_blocked_births": pre_blocked,
        "shocked_capacity_blocked_births": shocked_blocked,
        "shadow_capacity_blocked_births": shadow_blocked,
        "capacity_blocked_births": pre_blocked + shocked_blocked + shadow_blocked,
    }


def case_candidates(
    case: StudyCase,
    cache_record: Mapping[str, object] | None,
) -> dict[str, tuple[IVProgram, str]]:
    candidates = {
        "parent": (case.parent, "exact_parent"),
        "typed_macro": (typed_macro(case), "valid"),
        "random_same_mask": (random_same_mask(case), "valid"),
    }
    if cache_record is not None:
        validation = cache_record["validation"]
        assert isinstance(validation, Mapping)
        candidates["codex_agent_itt"] = (
            candidate_from_cache(case, cache_record),
            str(validation["status"]),
        )
    return candidates


def run_study(
    cache_records: Sequence[Mapping[str, object]],
    seeds: Sequence[int] = EVIDENCE_SEEDS,
) -> list[dict[str, object]]:
    cases = study_cases()
    if len(cache_records) != len(cases):
        raise ValueError("one cache record is required per study case")
    rows: list[dict[str, object]] = []
    for case, record in zip(cases, cache_records, strict=True):
        candidates = case_candidates(case, record)
        for seed in seeds:
            initial_hashes = set()
            for arm in ARMS:
                candidate, status = candidates[arm]
                row = run_assay(
                    case,
                    arm,
                    candidate,
                    seed,
                    candidate_status=status,
                )
                rows.append(row)
                initial_hashes.add(str(row["initial_physical_sha256"]))
            if len(initial_hashes) != 1:
                raise RuntimeError(
                    f"candidate arms changed initial physics for {case.case_id}, seed {seed}"
                )
    return rows


def qualify() -> dict[str, object]:
    """Model-blind endpoint check; it never reads the authentic cache."""
    rows: list[dict[str, object]] = []
    for case in study_cases():
        candidates = case_candidates(case, None)
        for seed in QUALIFICATION_SEEDS:
            initial_hashes = set()
            for arm in ("parent", "typed_macro", "random_same_mask"):
                candidate, status = candidates[arm]
                row = run_assay(case, arm, candidate, seed, candidate_status=status)
                rows.append(row)
                initial_hashes.add(str(row["initial_physical_sha256"]))
            if len(initial_hashes) != 1:
                raise RuntimeError("qualification candidate changed initial physics")
    by_arm = {
        arm: {
            "n": sum(row["arm"] == arm for row in rows),
            "establishment_rate": float(
                np.mean(
                    [
                        float(row["established_at_shock"])
                        for row in rows
                        if row["arm"] == arm
                    ]
                )
            ),
            "mean_lineage_auc_gap": float(
                np.mean(
                    [
                        float(row["lineage_share_auc_gap"])
                        for row in rows
                        if row["arm"] == arm
                    ]
                )
            ),
            "mean_lineage_alive_auc_gap": float(
                np.mean(
                    [
                        float(row["lineage_alive_auc_gap"])
                        for row in rows
                        if row["arm"] == arm
                    ]
                )
            ),
            "recovery_censor_rate": float(
                np.mean(
                    [
                        float(row["population_recovery_censored"])
                        for row in rows
                        if row["arm"] == arm
                    ]
                )
            ),
        }
        for arm in ("parent", "typed_macro", "random_same_mask")
    }
    return {
        "study_id": STUDY_ID,
        "status": "model_blind_qualification_not_evidence",
        "seeds": list(QUALIFICATION_SEEDS),
        "arm_diagnostics": by_arm,
        "all_conserved": all(row["conservation_ok"] for row in rows),
        "capacity_blocked_births": sum(
            int(row["capacity_blocked_births"]) for row in rows
        ),
    }


def mean(values: Iterable[float]) -> float:
    values = tuple(values)
    return sum(values) / len(values)


def seed_level_contrast(
    rows: Sequence[Mapping[str, object]],
    metric: str,
    baseline: str,
) -> dict[str, object]:
    lookup = {
        (str(row["case_id"]), int(row["seed"]), str(row["arm"])): float(row[metric])
        for row in rows
    }
    cases = study_cases()
    seed_effects = []
    for seed in EVIDENCE_SEEDS:
        seed_effects.append(
            mean(
                lookup[(case.case_id, seed, "codex_agent_itt")]
                - lookup[(case.case_id, seed, baseline)]
                for case in cases
            )
        )
    estimate = mean(seed_effects)
    standard_error = float(np.std(seed_effects, ddof=1) / math.sqrt(len(seed_effects)))
    t_critical_df7 = 2.364624251
    leave_one_out = [
        mean(value for index, value in enumerate(seed_effects) if index != omitted)
        for omitted in range(len(seed_effects))
    ]
    case_effects = [
        mean(
            lookup[(case.case_id, seed, "codex_agent_itt")]
            - lookup[(case.case_id, seed, baseline)]
            for seed in EVIDENCE_SEEDS
        )
        for case in cases
    ]
    if metric == "established_at_shock" and baseline in (
        "typed_macro",
        "random_same_mask",
    ):
        tier = "primary"
    elif metric == "lineage_alive_auc_gap" and baseline in (
        "typed_macro",
        "random_same_mask",
    ):
        tier = "secondary"
    else:
        tier = "exploratory"
    return {
        "estimand_tier": tier,
        "metric": metric,
        "treatment": "codex_agent_itt",
        "baseline": baseline,
        "estimate": estimate,
        "seed_effects": seed_effects,
        "standard_error": standard_error,
        "exploratory_t7_95_reference_interval": [
            estimate - t_critical_df7 * standard_error,
            estimate + t_critical_df7 * standard_error,
        ],
        "leave_one_seed_out_range": [min(leave_one_out), max(leave_one_out)],
        "case_effects_fixed_bank": case_effects,
        "n_ecology_seeds": len(seed_effects),
        "n_fixed_cases": len(case_effects),
    }


def source_hashes() -> dict[str, str]:
    paths = (
        Path(__file__),
        ROOT / "requirements.txt",
        ROOT / "src" / "evolve4" / "__init__.py",
        ROOT / "src" / "evolve4" / "control.py",
        ROOT / "src" / "evolve4" / "randomness.py",
        ROOT / "src" / "evolve4" / "simulation.py",
        ROOT / "src" / "evolve_modern" / "__init__.py",
        ROOT / "src" / "evolve_modern" / "iv.py",
        ROOT / "src" / "evolve_modern" / "iv_policies.py",
        ROOT / "src" / "evolve_modern" / "iv_variation.py",
    )
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in paths}


def summarize(
    rows: Sequence[Mapping[str, object]],
    cache_records: Sequence[Mapping[str, object]],
    cache_path: Path,
    cache_sha256: str,
    source_snapshot: Mapping[str, str],
) -> dict[str, object]:
    try:
        displayed_cache_path = str(cache_path.resolve().relative_to(ROOT))
    except ValueError:
        displayed_cache_path = str(cache_path.resolve())
    arm_means = {
        arm: {
            "establishment_rate": mean(
                float(row["established_at_shock"])
                for row in rows
                if row["arm"] == arm
            ),
            "pre_shock_lineage_share": mean(
                float(row["pre_shock_lineage_share"])
                for row in rows
                if row["arm"] == arm
            ),
            "famine_survival_rate": mean(
                float(row["focal_survived_famine"])
                for row in rows
                if row["arm"] == arm
            ),
            "lineage_share_auc_gap": mean(
                float(row["lineage_share_auc_gap"])
                for row in rows
                if row["arm"] == arm
            ),
            "lineage_alive_auc_gap": mean(
                float(row["lineage_alive_auc_gap"])
                for row in rows
                if row["arm"] == arm
            ),
            "population_auc_gap": mean(
                float(row["population_auc_gap"])
                for row in rows
                if row["arm"] == arm
            ),
            "behavioral_novelty": mean(
                float(row["behavioral_novelty"])
                for row in rows
                if row["arm"] == arm
            ),
            "movement_novelty": mean(
                float(row["movement_novelty"])
                for row in rows
                if row["arm"] == arm
            ),
            "construction_novelty": mean(
                float(row["construction_novelty"])
                for row in rows
                if row["arm"] == arm
            ),
            "reproduction_novelty": mean(
                float(row["reproduction_novelty"])
                for row in rows
                if row["arm"] == arm
            ),
        }
        for arm in ARMS
    }
    validity = [bool(record["validation"]["valid"]) for record in cache_records]
    raw_texts = [
        record["response"]["captured_final_answer_text"]
        for record in cache_records
    ]
    contrasts = [
        seed_level_contrast(rows, metric, baseline)
        for metric in (
            "established_at_shock",
            "lineage_alive_auc_gap",
            "lineage_share_auc_gap",
            "population_auc_gap",
        )
        for baseline in ("typed_macro", "random_same_mask", "parent")
    ]
    checks = {
        "complete_design": len(rows)
        == len(study_cases()) * len(EVIDENCE_SEEDS) * len(ARMS),
        "all_runs_conserved": all(bool(row["conservation_ok"]) for row in rows),
        "initial_physics_matched_within_case_seed": all(
            len(
                {
                    row["initial_physical_sha256"]
                    for row in rows
                    if row["case_id"] == case.case_id and row["seed"] == seed
                }
            )
            == 1
            for case in study_cases()
            for seed in EVIDENCE_SEEDS
        ),
    }
    return {
        "schema": 1,
        "study_id": STUDY_ID,
        "claim_status": "exploratory_fixed_bank_microstudy",
        "question": (
            "Do frozen Codex-agent policy proposals differ descriptively from "
            "same-mask typed and random proposals when ecology alone determines "
            "rare-lineage establishment and famine resilience?"
        ),
        "design": {
            "cases": len(study_cases()),
            "parent_indices": list(PARENT_INDICES),
            "change_masks": [list(mask) for mask in CHANGE_MASKS],
            "arms": list(ARMS),
            "evidence_seeds": list(EVIDENCE_SEEDS),
            "world": WORLD,
            "one_focal_founder": True,
            "later_variation": False,
            "establishment_endpoint": (
                "at least one living focal descendant of ancestry depth >=2 "
                "after pre-shock step 79"
            ),
            "famine": {
                "start_step": PRE_STEPS,
                "restore_step": PRE_STEPS + FAMINE_STEPS,
                "normal_harvest": NORMAL_HARVEST,
                "famine_harvest": FAMINE_HARVEST,
            },
            "recovery_reference": "matched no-famine shadow from exact step-80 state",
            "randomness": {
                "seed_plan": "IVSeedPlan-v1",
                "ecology_streams": list(IVSeedPlan.ECOLOGY_STREAM_NAMES),
            },
        },
        "estimand_hierarchy": {
            "primary_endpoint": "established_at_shock",
            "primary_contrasts": [
                "codex_agent_itt - typed_macro",
                "codex_agent_itt - random_same_mask",
            ],
            "secondary_endpoint": "lineage_alive_auc_gap",
            "secondary_contrasts": [
                "codex_agent_itt - typed_macro",
                "codex_agent_itt - random_same_mask",
            ],
            "exploratory": [
                "all contrasts against exact parent",
                "compositional lineage_share_auc_gap",
                "population_auc_gap",
                "famine survival",
                "population recovery time",
                "behavioral novelty",
                "case and parent heterogeneity",
            ],
        },
        "model_blind_qualification": QUALIFICATION_LOG,
        "collection": {
            "surface": "chatgpt_work_codex_subagent_v1",
            "auth_mode": "chatgpt_subscription",
            "requested_model": REQUESTED_MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "study_supplied_api_key": False,
            "direct_api_billing_exposure": "not_applicable_no_direct_api_call",
            "subscription_usage_exposure": "not_exposed",
            "recorded_attempts": len(cache_records),
            "protocol_commit": next(
                iter({str(record["protocol_commit"]) for record in cache_records})
            ),
            "request_bank_sha256": request_bank_sha256(),
            "context_fork": "none",
            "capture": "final_channel_only",
            "application_retries": 0,
            "surface_successes": sum(
                record["response"]["status"] == "ok"
                for record in cache_records
            ),
            "valid_responses": sum(validity),
            "parent_fallbacks": len(validity) - sum(validity),
            "distinct_nonnull_final_answers": len(
                {text for text in raw_texts if text is not None}
            ),
            "artifact_class": "orchestrator_attested_final_answer",
            "provider_authenticated": False,
            "attestation_basis": "captured_fresh_subagent_final_channel",
            "provider_model_revision": "not_exposed",
            "provider_request_ids": "not_exposed",
            "provider_wire": "not_exposed",
            "hidden_instructions": "not_exposed",
            "tool_activity": "not_exposed",
            "internal_retries": "not_exposed",
            "orchestrator_task_paths_are_provider_ids": False,
        },
        "arm_means": arm_means,
        "contrasts": contrasts,
        "checks": checks,
        "diagnostics": {
            "capacity_blocked_births": sum(
                int(row["capacity_blocked_births"]) for row in rows
            ),
            "runs_with_capacity_blocking": sum(
                int(row["capacity_blocked_births"]) > 0 for row in rows
            ),
            "no_capacity_blocking": all(
                int(row["capacity_blocked_births"]) == 0 for row in rows
            ),
        },
        "provenance": {
            "cache_path": displayed_cache_path,
            "cache_sha256": cache_sha256,
            "source_sha256": dict(source_snapshot),
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "bit_generator": "PCG64",
        },
        "interpretation_rule": (
            "Describe results only for this fixed 24-case bank and eight ecology "
            "seeds. Intervals cover ecology-seed variation, not model sampling, "
            "future prompts, programs, worlds, or agent surfaces."
        ),
        "metric_units": {
            "lineage_alive_auc_gap": "famine minus shadow; descendant-count steps over the 60 restored steps; negative is worse under famine",
            "lineage_share_auc_gap": "famine minus shadow; compositional lineage-share steps over the 60 restored steps; negative is worse under famine",
            "population_auc_gap": "famine minus shadow; organism-count steps over the 60 restored steps; negative is worse under famine",
            "population_recovery_steps": "one-based restored-harvest steps until three consecutive shocked counts reach at least 90% of the shadow; otherwise censored",
        },
        "limitations": [
            "The Codex agent surface is not a direct provider API and hides backend revision, wire data, built-in instructions, tool telemetry, and internal retries.",
            "One response per fixed case does not estimate model-sampling variability.",
            "One fixed random proposal per case does not estimate random-operator proposal-sampling variability.",
            "The typed-program language has only seven fixed controls; this is semantic recombination, not generated executable code or genetic programming.",
            "Proposal count, changed fields, and field Hamming distance are matched; compute, token use, marginal value magnitudes, and semantic knowledge are not.",
            "The typed macro is a hand-authored semantic baseline, not an uninformative or compute-matched control.",
            "Common random numbers remain aligned only until treatment trajectories diverge.",
            "The t7 intervals are exploratory Monte Carlo summaries requiring iid-seed and normality assumptions; they exclude case-bank and both proposal-sampling uncertainties.",
        ],
    }


RUN_FIELDS = (
    "study_id",
    "case_id",
    "parent_index",
    "change_paths",
    "seed",
    "arm",
    "candidate_status",
    "candidate_program",
    "field_hamming",
    "behavioral_novelty",
    "movement_novelty",
    "construction_novelty",
    "reproduction_novelty",
    "initial_physical_sha256",
    "pre_shock_state_sha256",
    "established_at_shock",
    "pre_shock_lineage_share",
    "focal_survived_famine",
    "shocked_lineage_share_auc",
    "shadow_lineage_share_auc",
    "lineage_share_auc_gap",
    "shocked_lineage_alive_auc",
    "shadow_lineage_alive_auc",
    "lineage_alive_auc_gap",
    "shocked_population_auc",
    "shadow_population_auc",
    "population_auc_gap",
    "population_recovery_steps",
    "population_recovery_censored",
    "conservation_ok",
    "pre_capacity_blocked_births",
    "shocked_capacity_blocked_births",
    "shadow_capacity_blocked_births",
    "capacity_blocked_births",
)


def write_svg(path: Path, summary: Mapping[str, object]) -> None:
    means = summary["arm_means"]
    assert isinstance(means, Mapping)
    labels = {
        "parent": "parent",
        "typed_macro": "typed",
        "random_same_mask": "random",
        "codex_agent_itt": "Codex ITT",
    }
    colors = ("#bbbbbb", "#476f95", "#8b8b8b", "#d2643f")
    establishment = [float(means[arm]["establishment_rate"]) for arm in ARMS]
    resilience = [float(means[arm]["lineage_alive_auc_gap"]) for arm in ARMS]
    resilience_scale = 90 / max(1.0, max(abs(value) for value in resilience))
    bars = []
    for index, arm in enumerate(ARMS):
        x = 70 + index * 95
        height = 150 * establishment[index]
        bars.append(
            f'<rect x="{x}" y="{235-height:.2f}" width="58" height="{height:.2f}" fill="{colors[index]}" rx="3"/>'
        )
        bars.append(
            f'<text x="{x+29}" y="255" text-anchor="middle">{labels[arm]}</text>'
        )
        bars.append(
            f'<text x="{x+29}" y="{225-height:.2f}" text-anchor="middle">{establishment[index]:.2f}</text>'
        )
        rx = 500 + index * 95
        zero = 150
        scaled = resilience[index] * resilience_scale
        y = zero - max(0.0, scaled)
        bars.append(
            f'<rect x="{rx}" y="{y:.2f}" width="58" height="{abs(scaled):.2f}" fill="{colors[index]}" rx="3"/>'
        )
        bars.append(
            f'<text x="{rx+29}" y="255" text-anchor="middle">{labels[arm]}</text>'
        )
        bars.append(
            f'<text x="{rx+29}" y="{145-scaled:.2f}" text-anchor="middle">{resilience[index]:+.3f}</text>'
        )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="940" height="320" viewBox="0 0 940 320">
<rect width="100%" height="100%" fill="white"/>
<style>text{{font-family:Inter,Arial,sans-serif;fill:#171717;font-size:12px}}.title{{font-size:21px;font-weight:700}}.sub{{font-size:13px;fill:#555}}</style>
<text x="35" y="35" class="title">Frozen semantic proposals, selected only by ecology</text>
<text x="35" y="58" class="sub">24 fixed cases × 8 ecology seeds · identical starts · matched no-famine shadows</text>
<text x="65" y="88" class="sub">granddescendant lineage established by step 80</text>
<line x1="55" y1="235" x2="445" y2="235" stroke="#999"/>
<text x="500" y="88" class="sub">post-restore lineage abundance AUC: famine − shadow</text>
<line x1="485" y1="150" x2="875" y2="150" stroke="#999"/>
{''.join(bars)}
<text x="35" y="297" class="sub">Descriptive micro-study only; uncertainty covers the eight ecology seeds, not model sampling.</text>
</svg>'''
    path.write_text(svg + "\n", encoding="utf-8")


def write_bundle(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    checks = summary["checks"]
    assert isinstance(checks, Mapping)
    if not all(checks.values()):
        raise RuntimeError(f"study checks failed: {checks}")
    path.mkdir(parents=True)
    with (path / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: (
                        ""
                        if row[field] is None
                        else format(row[field], ".12g")
                        if isinstance(row[field], float)
                        else row[field]
                    )
                    for field in RUN_FIELDS
                }
            )
    (path / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_svg(path / "figure.svg", summary)
    checksums = {
        name: sha256_file(path / name)
        for name in ("runs.csv", "summary.json", "figure.svg")
    }
    (path / "checksums.json").write_text(
        json.dumps(checksums, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--print-requests", action="store_true")
    parser.add_argument("--qualify", action="store_true")
    args = parser.parse_args()

    if args.print_requests:
        for request in request_payloads():
            print(canonical_json(request))
        return
    if args.qualify:
        print(json.dumps(qualify(), indent=2, sort_keys=True))
        return
    if args.output is None:
        parser.error("--output is required for evidence replay")

    cache_path = args.cache.resolve()
    cache_sha256 = sha256_file(cache_path)
    source_snapshot = source_hashes()
    cache_records = load_cache(cache_path)
    rows = run_study(cache_records)
    if sha256_file(cache_path) != cache_sha256:
        raise RuntimeError("frozen cache changed during replay")
    if source_hashes() != source_snapshot:
        raise RuntimeError("study source changed during replay")
    summary = summarize(
        rows,
        cache_records,
        cache_path,
        cache_sha256,
        source_snapshot,
    )
    write_bundle(args.output, rows, summary)
    print(f"wrote {STUDY_ID} to {args.output}")
    for arm in ARMS:
        values = summary["arm_means"][arm]
        print(
            f"{arm:18} establishment={values['establishment_rate']:.3f} "
            f"lineage shock gap={values['lineage_alive_auc_gap']:+.3f}"
        )


if __name__ == "__main__":
    main()
