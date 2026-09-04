#!/usr/bin/env python3
"""Select and freeze a less ceiling-saturated EVOLVE IV world.

This calibration is deliberately model-blind.  It runs only the inherited
program controller, varies only ``max_organisms``, and requires every selected
projected step-summary trajectory to equal a higher-cap sentinel before
freezing any evidence seeds.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import platform
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

import run_iv_variation as pilot


CONFIG_SCHEMA = 1
CALIBRATION_ID = "iv-world-calibration-v1"
CANONICAL_CONFIG_RELATIVE = Path(
    "experiments/configs/iv-world-calibration-v1.json"
)
CANONICAL_CONFIG_PATH = ROOT / CANONICAL_CONFIG_RELATIVE
CALIBRATION_SEEDS = (101, 503, 1601, 4099, 8081, 12007, 16001, 24001)
CANDIDATE_CAPS = (112, 120, 128, 144, 160, 176)
SENTINEL_CAP = 192
STEPS = 64
ARM_ID = "inherit_only"
SEED_DERIVATION = "numpy-seedsequence-spawn-uint64"
BUNDLE_FILES = (
    "calibration-runs.jsonl",
    "calibration-decision.json",
    "frozen-world.json",
    "manifest.json",
)
SOURCE_FILES = (
    "experiments/calibrate_iv_world.py",
    "experiments/run_iv_variation.py",
    "experiments/configs/iv-world-calibration-v1.json",
    "experiments/configs/iv-variation-pilot-v1.json",
    "src/evolve4/control.py",
    "src/evolve4/randomness.py",
    "src/evolve4/simulation.py",
    "src/evolve_modern/iv.py",
    "src/evolve_modern/iv_policies.py",
    "src/evolve_modern/iv_variation.py",
)
TRAJECTORY_KEYS = (
    "step",
    "n_alive",
    "n_producers",
    "n_recyclers",
    "nutrient",
    "waste",
    "stored",
    "niche_index",
    "construct_match",
    "condition_var",
    "condition_mean",
    "births",
    "deaths",
    "capacity_blocked_births",
    "capacity_gate_occupancy_peak",
    "conservation_ok",
    "nonnegative_ok",
)
TRAJECTORY_INTEGER_KEYS = (
    "step",
    "n_alive",
    "n_producers",
    "n_recyclers",
    "nutrient",
    "waste",
    "stored",
    "births",
    "deaths",
    "capacity_blocked_births",
    "capacity_gate_occupancy_peak",
)
TRAJECTORY_FLOAT_KEYS = (
    "niche_index",
    "construct_match",
    "condition_var",
    "condition_mean",
)
TRAJECTORY_BOOLEAN_KEYS = ("conservation_ok", "nonnegative_ok")
RUN_SHA256_KEYS = (
    "initial_physical_sha256",
    "initial_programs_sha256",
    "final_physical_sha256",
    "final_programs_sha256",
    "final_rng_states_sha256",
    "ecology_trajectory_sha256",
)
ACCEPTANCE = {
    "require_conservation_all_steps": True,
    "require_nonnegative_all_steps": True,
    "require_no_extinction": True,
    "role_coexistence_fraction_min": 0.95,
    "births_total_min": 32,
    "eighth_birth_step_max": 15,
    "population_ceiling_fraction_max": 0.0,
    "capacity_gate_occupancy_fraction_max": 0.85,
    "capacity_blocked_births_total_max": 0,
    "require_projected_trajectory_match_to_sentinel": True,
}
CONFIG_KEYS = {
    "schema",
    "calibration_id",
    "claim_status",
    "source_config",
    "calibration_arm",
    "calibration_seeds",
    "steps",
    "candidate_max_organisms",
    "sentinel_max_organisms",
    "design_timing",
    "qualification_seed_reservation",
    "evidence_seed_reservation",
    "acceptance",
}
RUN_KEYS = {
    "schema",
    "calibration_id",
    "run_kind",
    "arm_id",
    "master_seed",
    "max_organisms",
    "seed_plan",
    "initial_physical_sha256",
    "initial_programs_sha256",
    "final_physical_sha256",
    "final_programs_sha256",
    "final_rng_states_sha256",
    "ecology_trajectory_sha256",
    "metrics",
    "ecology_trajectory",
}
RESERVATION_RECORD_KEYS = {
    "derivation",
    "derivation_version",
    "root",
    "count",
    "master_seeds",
    "master_seeds_sha256",
    "seed_plans",
    "seed_plans_sha256",
}
FROZEN_WORLD_KEYS = {
    "schema",
    "world_id",
    "calibration_id",
    "claim_status",
    "design_timing",
    "selected_max_organisms",
    "physics",
    "proposal_budget_policy",
    "initial_programs",
    "qualification_seeds",
    "evidence_seeds",
    "bindings",
}
FROZEN_BINDING_KEYS = {
    "calibration_config_sha256",
    "source_config_sha256",
    "calibration_decision_sha256",
    "physics_sha256",
    "initial_programs_sha256",
    "proposal_budget_policy_sha256",
}
DESIGN_TIMING = {
    "headroom_rule": "capacity_gate_occupancy_fraction_max",
    "headroom_threshold": 0.85,
    "status": "exploratory_post_scan_rule_finalization",
    "preregistered": False,
    "informed_by_variation_or_model_outcomes": False,
}


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        sort_keys=True,
    )


def canonical_sha(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def is_sha256(value: object) -> bool:
    if type(value) is not str or len(value) != 71 or not value.startswith(
        "sha256:"
    ):
        return False
    digest = value[7:]
    try:
        int(digest, 16)
    except ValueError:
        return False
    return digest == digest.lower()


def source_commit() -> str:
    """Return the latest commit touching any calibration/replay input."""
    try:
        return subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", *SOURCE_FILES],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def source_files_match_commit(commit: str) -> bool:
    """Check that every recorded source byte is present at ``commit``."""
    if commit == "unavailable" or not commit:
        return False
    for name in SOURCE_FILES:
        try:
            committed = subprocess.run(
                ["git", "show", f"{commit}:{name}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            return False
        if committed != (ROOT / name).read_bytes():
            return False
    return True


def jsonl_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    return ("".join(canonical_json(dict(row)) + "\n" for row in rows)).encode()


def _load_json(path: Path) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate config key: {key}")
            result[key] = value
        return result

    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite config number: {token}")

    def finite_float(token: str) -> float:
        value = float(token)
        if not math.isfinite(value):
            raise ValueError(f"non-finite config number: {token}")
        return value

    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique,
            parse_constant=reject_constant, parse_float=finite_float,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cannot load calibration config: {exc}") from exc


def _load_bound_json(payload: bytes, *, label: str) -> object:
    """Parse a byte-bound JSON input with the same fail-closed rules as config."""
    if type(payload) is not bytes:
        raise ValueError(f"{label} must be supplied as bytes")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate {label} key: {key}")
            result[key] = value
        return result

    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite {label} number: {token}")

    def finite_float(token: str) -> float:
        value = float(token)
        if not math.isfinite(value):
            raise ValueError(f"non-finite {label} number: {token}")
        return value

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cannot load bound {label}: {exc}") from exc


def _manifest_input_path(path: Path) -> str:
    """Return an honest stable path label for a calibration input."""
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _validate_reservation(value: object, *, root: int) -> None:
    expected = {
        "derivation": SEED_DERIVATION,
        "derivation_version": 1,
        "root": root,
        "count": 4,
    }
    if type(value) is not dict or value != expected:
        raise ValueError(f"seed reservation must be exactly {expected}")


def derive_master_seeds(root: int, count: int) -> tuple[int, ...]:
    if type(root) is not int or root < 0 or type(count) is not int or count <= 0:
        raise ValueError("seed root and count must be nonnegative/positive integers")
    return tuple(
        int(child.generate_state(1, dtype=np.uint64)[0])
        for child in np.random.SeedSequence(root).spawn(count)
    )


def read_config(path: Path) -> dict[str, object]:
    payload = _load_json(path)
    if type(payload) is not dict or set(payload) != CONFIG_KEYS:
        raise ValueError(f"config keys must be exactly {sorted(CONFIG_KEYS)}")
    exact = {
        "schema": CONFIG_SCHEMA,
        "calibration_id": CALIBRATION_ID,
        "claim_status": "model_blind_world_calibration",
        "source_config": "experiments/configs/iv-variation-pilot-v1.json",
        "calibration_arm": ARM_ID,
        "calibration_seeds": list(CALIBRATION_SEEDS),
        "steps": STEPS,
        "candidate_max_organisms": list(CANDIDATE_CAPS),
        "sentinel_max_organisms": SENTINEL_CAP,
        "design_timing": DESIGN_TIMING,
        "acceptance": ACCEPTANCE,
    }
    for key, expected in exact.items():
        if payload[key] != expected:
            raise ValueError(f"{key} must be exactly {expected!r}")
    _validate_reservation(payload["qualification_seed_reservation"], root=20260905)
    _validate_reservation(payload["evidence_seed_reservation"], root=20260906)
    qualification = derive_master_seeds(20260905, 4)
    evidence = derive_master_seeds(20260906, 4)
    groups = (set(CALIBRATION_SEEDS), set(qualification), set(evidence))
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise ValueError("calibration, qualification, and evidence seeds overlap")
    return payload


def _projected_ecology_trajectory(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    projected: list[dict[str, object]] = []
    for row in rows:
        if not set(TRAJECTORY_KEYS) <= set(row):
            raise ValueError("trajectory row lacks a required ecology field")
        projected.append({key: row[key] for key in TRAJECTORY_KEYS})
    return projected


def trajectory_metrics(
    trajectory: Sequence[Mapping[str, object]], max_organisms: int,
) -> dict[str, object]:
    if (
        len(trajectory) != STEPS
        or type(max_organisms) is not int
        or max_organisms <= 0
    ):
        raise ValueError(f"trajectory must contain exactly {STEPS} steps")
    for row in trajectory:
        if type(row) is not dict or set(row) != set(TRAJECTORY_KEYS):
            raise ValueError("trajectory row has invalid schema")
        if any(type(row[key]) is not int for key in TRAJECTORY_INTEGER_KEYS):
            raise ValueError("trajectory integer fields must be exact integers")
        if any(type(row[key]) is not float for key in TRAJECTORY_FLOAT_KEYS):
            raise ValueError("trajectory continuous fields must be floats")
        if any(
            not math.isfinite(row[key])
            for key in TRAJECTORY_FLOAT_KEYS
        ):
            raise ValueError("trajectory continuous fields must be finite")
        if any(type(row[key]) is not bool for key in TRAJECTORY_BOOLEAN_KEYS):
            raise ValueError("trajectory invariant fields must be booleans")
    if [row.get("step") for row in trajectory] != list(range(STEPS)):
        raise ValueError("trajectory steps must be consecutive from zero")
    alive = [row["n_alive"] for row in trajectory]
    producers = [row["n_producers"] for row in trajectory]
    recyclers = [row["n_recyclers"] for row in trajectory]
    if any(a < 0 or a > max_organisms for a in alive):
        raise ValueError("population lies outside the configured capacity")
    if any(p < 0 or r < 0 or p + r != a for a, p, r in zip(alive, producers, recyclers)):
        raise ValueError("producer/recycler counts do not partition population")
    cumulative = 0
    eighth_birth_step: int | None = None
    for row in trajectory:
        births = row["births"]
        if (
            births < 0
            or row["deaths"] < 0
            or row["capacity_blocked_births"] < 0
        ):
            raise ValueError("event counts must be nonnegative")
        cumulative += births
        if eighth_birth_step is None and cumulative >= 8:
            eighth_birth_step = row["step"]
    gate_occupancy = [
        row["capacity_gate_occupancy_peak"] for row in trajectory
    ]
    if any(
        occupancy < alive_count or occupancy > max_organisms
        for occupancy, alive_count in zip(gate_occupancy, alive)
    ):
        raise ValueError("capacity-gate occupancy is inconsistent")
    return {
        "conservation_all_steps": all(row["conservation_ok"] is True for row in trajectory),
        "nonnegative_all_steps": all(row["nonnegative_ok"] is True for row in trajectory),
        "extinction_step": next((row["step"] for row in trajectory if row["n_alive"] == 0), None),
        "role_coexistence_fraction": sum(p > 0 and r > 0 for p, r in zip(producers, recyclers)) / STEPS,
        "births_total": cumulative,
        "eighth_birth_step": eighth_birth_step,
        "population_ceiling_fraction": sum(a == max_organisms for a in alive) / STEPS,
        "population_occupancy_auc_normalized": sum(alive) / (STEPS * max_organisms),
        "max_alive": max(alive),
        "max_alive_fraction": max(alive) / max_organisms,
        "capacity_gate_occupancy_peak": max(gate_occupancy),
        "capacity_gate_occupancy_fraction": (
            max(gate_occupancy) / max_organisms
        ),
        "capacity_blocked_births_total": sum(row["capacity_blocked_births"] for row in trajectory),
    }


def _run_row(source: Mapping[str, object], *, seed: int, cap: int) -> dict[str, object]:
    candidate = copy.deepcopy(dict(source))
    physics = dict(candidate["physics"])
    physics["max_organisms"] = cap
    candidate["physics"] = physics
    run, simulation_trajectory, _ = pilot.run_arm(
        candidate, seed=seed, arm_id=ARM_ID, operator=None,
    )
    trajectory = _projected_ecology_trajectory(simulation_trajectory)
    return {
        "schema": 1,
        "calibration_id": CALIBRATION_ID,
        "run_kind": "sentinel" if cap == SENTINEL_CAP else "candidate",
        "arm_id": ARM_ID,
        "master_seed": seed,
        "max_organisms": cap,
        "seed_plan": run["seed_plan"],
        "initial_physical_sha256": run["initial_physical_sha256"],
        "initial_programs_sha256": run["initial_programs_sha256"],
        "final_physical_sha256": run["final_physical_sha256"],
        "final_programs_sha256": run["final_programs_sha256"],
        "final_rng_states_sha256": run["final_rng_states_sha256"],
        "ecology_trajectory_sha256": canonical_sha(trajectory),
        "metrics": trajectory_metrics(trajectory, cap),
        "ecology_trajectory": trajectory,
    }


def _validate_run(row: Mapping[str, object], config: Mapping[str, object]) -> None:
    if (
        type(row) is not dict
        or set(row) != RUN_KEYS
        or type(row["schema"]) is not int
        or row["schema"] != 1
        or row["calibration_id"] != CALIBRATION_ID
    ):
        raise ValueError("calibration run row has invalid schema")
    if row["arm_id"] != ARM_ID:
        raise ValueError("calibration rows must be inheritance-only")
    seed = row["master_seed"]
    cap = row["max_organisms"]
    if type(seed) is not int or type(cap) is not int:
        raise ValueError("run seed and capacity must be integers")
    if any(not is_sha256(row[key]) for key in RUN_SHA256_KEYS):
        raise ValueError("calibration run contains an invalid sha256 digest")
    expected_kind = "sentinel" if cap == SENTINEL_CAP else "candidate"
    if row["run_kind"] != expected_kind:
        raise ValueError("run kind does not match its capacity")
    expected_plan = pilot.IVSeedPlan.from_master(seed).to_dict()
    if canonical_json(row["seed_plan"]) != canonical_json(expected_plan):
        raise ValueError("run seed plan is not the canonical derivation")
    trajectory = row["ecology_trajectory"]
    if type(trajectory) is not list or any(type(item) is not dict or set(item) != set(TRAJECTORY_KEYS) for item in trajectory):
        raise ValueError("calibration ecology trajectory has invalid schema")
    metrics = trajectory_metrics(trajectory, cap)
    if (
        type(row["metrics"]) is not dict
        or canonical_json(row["metrics"]) != canonical_json(metrics)
        or row["ecology_trajectory_sha256"] != canonical_sha(trajectory)
    ):
        raise ValueError("calibration row metrics or trajectory hash is inconsistent")


def evaluate_candidate(
    config: Mapping[str, object], candidate: Mapping[str, object], sentinel: Mapping[str, object],
) -> dict[str, object]:
    _validate_run(candidate, config)
    _validate_run(sentinel, config)
    if candidate["master_seed"] != sentinel["master_seed"]:
        raise ValueError("candidate and sentinel seeds differ")
    if candidate["initial_physical_sha256"] != sentinel["initial_physical_sha256"] or candidate["initial_programs_sha256"] != sentinel["initial_programs_sha256"]:
        raise ValueError("candidate and sentinel initial states differ")
    metrics = candidate["metrics"]
    assert isinstance(metrics, Mapping)
    acceptance = config["acceptance"]
    assert isinstance(acceptance, Mapping)
    eighth = metrics["eighth_birth_step"]
    checks = {
        "conservation_all_steps": metrics["conservation_all_steps"] is True,
        "nonnegative_all_steps": metrics["nonnegative_all_steps"] is True,
        "no_extinction": metrics["extinction_step"] is None,
        "role_coexistence_fraction": float(metrics["role_coexistence_fraction"]) >= float(acceptance["role_coexistence_fraction_min"]),
        "births_total": int(metrics["births_total"]) >= int(acceptance["births_total_min"]),
        "eighth_birth_step": type(eighth) is int and eighth <= int(acceptance["eighth_birth_step_max"]),
        "population_ceiling_fraction": float(metrics["population_ceiling_fraction"]) <= float(acceptance["population_ceiling_fraction_max"]),
        "capacity_gate_occupancy_fraction": float(metrics["capacity_gate_occupancy_fraction"]) <= float(acceptance["capacity_gate_occupancy_fraction_max"]),
        "capacity_blocked_births_total": int(metrics["capacity_blocked_births_total"]) <= int(acceptance["capacity_blocked_births_total_max"]),
        "projected_trajectory_matches_sentinel": candidate["ecology_trajectory"] == sentinel["ecology_trajectory"],
    }
    return {
        "master_seed": candidate["master_seed"],
        "metrics": metrics,
        "checks": checks,
        "passed": all(checks.values()),
    }


def select_candidate(
    config: Mapping[str, object], runs: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    caps = (*CANDIDATE_CAPS, SENTINEL_CAP)
    indexed: dict[tuple[int, int], Mapping[str, object]] = {}
    for row in runs:
        _validate_run(row, config)
        key = (int(row["master_seed"]), int(row["max_organisms"]))
        if key in indexed:
            raise ValueError(f"duplicate calibration run: {key}")
        indexed[key] = row
    expected = {(seed, cap) for cap in caps for seed in CALIBRATION_SEEDS}
    if set(indexed) != expected:
        raise ValueError("calibration runs must form the exact seed-by-capacity matrix")
    evaluations: list[dict[str, object]] = []
    for cap in CANDIDATE_CAPS:
        seeds = [
            evaluate_candidate(config, indexed[(seed, cap)], indexed[(seed, SENTINEL_CAP)])
            for seed in CALIBRATION_SEEDS
        ]
        evaluations.append({
            "max_organisms": cap,
            "seed_evaluations": seeds,
            "eligible": all(bool(item["passed"]) for item in seeds),
        })
    eligible = [int(item["max_organisms"]) for item in evaluations if item["eligible"]]
    if not eligible:
        raise RuntimeError("no candidate capacity passed every calibration criterion")
    return {
        "schema": 1,
        "calibration_id": CALIBRATION_ID,
        "claim_status": "model_blind_world_calibration",
        "design_timing": config["design_timing"],
        "selection_rule": "smallest candidate passing every criterion on every calibration seed",
        "selected_max_organisms": min(eligible),
        "sentinel_max_organisms": SENTINEL_CAP,
        "candidate_evaluations": evaluations,
        "protocol_checks": {
            "exact_seed_capacity_matrix": True,
            "inheritance_only": True,
            "only_max_organisms_varied": True,
            "projected_ecology_summary_compared_to_sentinel": True,
            "trajectory_scope": (
                "projected_step_aggregate_summary_not_full_microstate"
            ),
            "no_model_calls": True,
            "no_variation_operator": True,
        },
    }


def _reservation(config: Mapping[str, object], key: str) -> dict[str, object]:
    spec = config[key]
    assert isinstance(spec, Mapping)
    seeds = list(derive_master_seeds(int(spec["root"]), int(spec["count"])))
    plans = [pilot.IVSeedPlan.from_master(seed).to_dict() for seed in seeds]
    return {
        **dict(spec),
        "master_seeds": seeds,
        "master_seeds_sha256": canonical_sha(seeds),
        "seed_plans": plans,
        "seed_plans_sha256": canonical_sha(plans),
    }


def validate_reservation_record(
    record: object,
    specification: object,
) -> None:
    """Validate a loaded frozen reservation down to every named RNG stream."""
    if type(record) is not dict or set(record) != RESERVATION_RECORD_KEYS:
        raise ValueError("frozen seed reservation has invalid schema")
    if type(specification) is not dict:
        raise ValueError("seed reservation specification must be an object")
    metadata = {
        key: record[key]
        for key in ("derivation", "derivation_version", "root", "count")
    }
    if metadata != specification:
        raise ValueError("frozen seed reservation metadata differs from config")
    expected_seeds = list(
        derive_master_seeds(
            int(specification["root"]),
            int(specification["count"]),
        )
    )
    if record["master_seeds"] != expected_seeds:
        raise ValueError("frozen master seeds do not match their derivation")
    if record["master_seeds_sha256"] != canonical_sha(expected_seeds):
        raise ValueError("frozen master-seed checksum mismatch")
    expected_plans = [
        pilot.IVSeedPlan.from_master(seed).to_dict()
        for seed in expected_seeds
    ]
    if record["seed_plans"] != expected_plans:
        raise ValueError("frozen seed plans do not match IVSeedPlan-v1")
    if record["seed_plans_sha256"] != canonical_sha(expected_plans):
        raise ValueError("frozen seed-plan checksum mismatch")


def validate_frozen_world(
    config: Mapping[str, object],
    world: object,
    *,
    calibration_config_bytes: bytes,
    source_config_bytes: bytes,
    decision: Mapping[str, object],
    calibration_decision_bytes: bytes,
) -> None:
    """Validate a frozen world against every supplied byte-bound input."""
    loaded_config = _load_bound_json(
        calibration_config_bytes,
        label="calibration config",
    )
    if canonical_json(loaded_config) != canonical_json(dict(config)):
        raise ValueError("calibration config bytes differ from parsed config")
    source_path = ROOT / str(config["source_config"])
    if source_config_bytes != source_path.read_bytes():
        raise ValueError("source config bytes differ from configured source")
    if (
        type(decision) is not dict
        or type(decision.get("schema")) is not int
        or decision.get("schema") != 1
        or decision.get("calibration_id") != CALIBRATION_ID
        or type(decision.get("selected_max_organisms")) is not int
    ):
        raise ValueError("calibration decision has invalid schema")
    loaded_decision = _load_bound_json(
        calibration_decision_bytes,
        label="calibration decision",
    )
    expected_decision_bytes = (canonical_json(decision) + "\n").encode()
    if (
        canonical_json(loaded_decision) != canonical_json(decision)
        or calibration_decision_bytes != expected_decision_bytes
    ):
        raise ValueError("calibration decision bytes are not canonical")
    if type(world) is not dict or set(world) != FROZEN_WORLD_KEYS:
        raise ValueError("frozen world has invalid schema")
    if (
        type(world["schema"]) is not int
        or world["schema"] != 1
        or world["world_id"] != "iv-variation-world-v1"
        or world["calibration_id"] != CALIBRATION_ID
        or world["claim_status"]
        != "model_blind_selected_before_authentic_model_evidence"
    ):
        raise ValueError("frozen world identity is invalid")
    selected = world["selected_max_organisms"]
    if type(selected) is not int or selected not in CANDIDATE_CAPS:
        raise ValueError("frozen world has an invalid selected capacity")
    if selected != decision.get("selected_max_organisms"):
        raise ValueError("frozen world and calibration decision disagree")
    if (
        config.get("design_timing") != DESIGN_TIMING
        or decision.get("design_timing") != DESIGN_TIMING
        or world["design_timing"] != DESIGN_TIMING
    ):
        raise ValueError("calibration design timing is inconsistent")
    source = pilot.read_config(source_path)
    expected_physics = dict(source["physics"])
    expected_physics["max_organisms"] = selected
    if world["physics"] != expected_physics:
        raise ValueError("frozen physics differ beyond max_organisms")
    if world["initial_programs"] != source["initial_programs"]:
        raise ValueError("frozen initial programs differ from the calibrated source")
    expected_policy = {
        "trigger": "birth_event",
        "per_replicate_upper_cap": source["proposal_budget"],
        "terminal_shortfall": "preserved_as_outcome",
        "authentic_evidence_requires_full_budget": False,
    }
    if world["proposal_budget_policy"] != expected_policy:
        raise ValueError("frozen proposal budget is not an endogenous upper cap")
    validate_reservation_record(
        world["qualification_seeds"],
        config["qualification_seed_reservation"],
    )
    validate_reservation_record(
        world["evidence_seeds"],
        config["evidence_seed_reservation"],
    )
    qualification = set(world["qualification_seeds"]["master_seeds"])
    evidence = set(world["evidence_seeds"]["master_seeds"])
    if qualification & evidence or qualification & set(CALIBRATION_SEEDS) or evidence & set(CALIBRATION_SEEDS):
        raise ValueError("frozen calibration, qualification, and evidence seeds overlap")
    bindings = world["bindings"]
    if type(bindings) is not dict or set(bindings) != FROZEN_BINDING_KEYS:
        raise ValueError("frozen world bindings have invalid schema")
    expected_bindings = {
        "calibration_config_sha256": sha256_bytes(calibration_config_bytes),
        "source_config_sha256": sha256_bytes(source_config_bytes),
        "calibration_decision_sha256": sha256_bytes(
            calibration_decision_bytes
        ),
        "physics_sha256": canonical_sha(expected_physics),
        "initial_programs_sha256": canonical_sha(source["initial_programs"]),
        "proposal_budget_policy_sha256": canonical_sha(expected_policy),
    }
    if any(bindings[key] != value for key, value in expected_bindings.items()):
        raise ValueError("frozen world input or semantic checksum mismatch")


def run_calibration(
    config_path: Path,
    output: Path,
    *,
    require_committed_source: bool = False,
) -> None:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output directory: {output}")
    if require_committed_source:
        try:
            supplied_config = config_path.resolve(strict=True)
            canonical_config = CANONICAL_CONFIG_PATH.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(
                "reference generation requires the repository's canonical "
                "calibration config"
            ) from exc
        if supplied_config != canonical_config:
            raise RuntimeError(
                "reference generation requires --config to resolve to "
                f"{CANONICAL_CONFIG_RELATIVE.as_posix()}"
            )
    config = read_config(config_path)
    calibration_config_bytes = config_path.read_bytes()
    commit = source_commit()
    committed_source = source_files_match_commit(commit)
    if require_committed_source and not committed_source:
        raise RuntimeError(
            "reference generation requires every critical source byte to "
            "match the recorded Git commit"
        )
    source_path = ROOT / str(config["source_config"])
    source_config_bytes = source_path.read_bytes()
    source = pilot.read_config(source_path)
    if int(source["physics"]["steps"]) != STEPS:
        raise ValueError(f"source world must have exactly {STEPS} steps")
    runs = [
        _run_row(source, seed=seed, cap=cap)
        for cap in (*CANDIDATE_CAPS, SENTINEL_CAP)
        for seed in CALIBRATION_SEEDS
    ]
    decision = select_candidate(config, runs)
    selected = int(decision["selected_max_organisms"])
    physics = dict(source["physics"])
    physics["max_organisms"] = selected
    qualification = _reservation(config, "qualification_seed_reservation")
    evidence = _reservation(config, "evidence_seed_reservation")
    decision_bytes = (canonical_json(decision) + "\n").encode()
    proposal_budget_policy = {
        "trigger": "birth_event",
        "per_replicate_upper_cap": source["proposal_budget"],
        "terminal_shortfall": "preserved_as_outcome",
        "authentic_evidence_requires_full_budget": False,
    }
    frozen = {
        "schema": 1,
        "world_id": "iv-variation-world-v1",
        "calibration_id": CALIBRATION_ID,
        "claim_status": "model_blind_selected_before_authentic_model_evidence",
        "design_timing": config["design_timing"],
        "selected_max_organisms": selected,
        "physics": physics,
        "proposal_budget_policy": proposal_budget_policy,
        "initial_programs": source["initial_programs"],
        "qualification_seeds": qualification,
        "evidence_seeds": evidence,
        "bindings": {
            "calibration_config_sha256": sha256_bytes(
                calibration_config_bytes
            ),
            "source_config_sha256": sha256_bytes(source_config_bytes),
            "calibration_decision_sha256": sha256_bytes(decision_bytes),
            "physics_sha256": canonical_sha(physics),
            "initial_programs_sha256": canonical_sha(source["initial_programs"]),
            "proposal_budget_policy_sha256": canonical_sha(
                proposal_budget_policy
            ),
        },
    }
    validate_frozen_world(
        config,
        frozen,
        calibration_config_bytes=calibration_config_bytes,
        source_config_bytes=source_config_bytes,
        decision=decision,
        calibration_decision_bytes=decision_bytes,
    )
    runs_bytes = jsonl_bytes(runs)
    frozen_bytes = (canonical_json(frozen) + "\n").encode()
    manifest = {
        "schema": 1,
        "calibration_id": CALIBRATION_ID,
        "claim_status": "model_blind_world_calibration",
        "generated_by": "experiments/calibrate_iv_world.py",
        "source_commit": commit,
        "source_commit_scope": "latest commit touching any source_files_sha256 path",
        "source_files_match_commit": committed_source,
        "source_files_sha256": {name: sha256_bytes((ROOT / name).read_bytes()) for name in SOURCE_FILES},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "rng": "numpy.random.PCG64",
            "run_seed_derivation": "IVSeedPlan-v1",
            "reservation_seed_derivation": SEED_DERIVATION + "-v1",
        },
        "inputs": {
            "calibration_config_path": _manifest_input_path(config_path),
            "calibration_config_sha256": sha256_bytes(
                calibration_config_bytes
            ),
            "source_config_path": _manifest_input_path(source_path),
            "source_config_sha256": sha256_bytes(source_config_bytes),
            "initial_programs_sha256": canonical_sha(source["initial_programs"]),
        },
        "protocol": {
            "arm": ARM_ID,
            "steps": STEPS,
            "calibration_seeds": list(CALIBRATION_SEEDS),
            "candidate_max_organisms": list(CANDIDATE_CAPS),
            "sentinel_max_organisms": SENTINEL_CAP,
            "design_timing": config["design_timing"],
            "varied_physics_fields": ["max_organisms"],
            "trajectory_scope": (
                "projected_step_aggregate_summary_not_full_microstate"
            ),
            "acceptance": config["acceptance"],
            "proposal_budget_policy": proposal_budget_policy,
            "no_model_calls": True,
            "no_variation_operator": True,
        },
        "reserved_seeds": {"qualification": qualification, "evidence": evidence},
        "artifacts_sha256": {
            "calibration-runs.jsonl": sha256_bytes(runs_bytes),
            "calibration-decision.json": sha256_bytes(decision_bytes),
            "frozen-world.json": sha256_bytes(frozen_bytes),
        },
        "reproduce": (
            "PYTHONPATH=src python3 experiments/calibrate_iv_world.py "
            "--config experiments/configs/iv-world-calibration-v1.json "
            "--output <new-directory> --require-committed-source"
        ),
    }
    payloads = {
        "calibration-runs.jsonl": runs_bytes,
        "calibration-decision.json": decision_bytes,
        "frozen-world.json": frozen_bytes,
        "manifest.json": (canonical_json(manifest) + "\n").encode(),
    }
    output.mkdir(parents=True, exist_ok=False)
    for name in BUNDLE_FILES:
        (output / name).write_bytes(payloads[name])
    checksums = {
        "schema": 1,
        "algorithm": "sha256",
        "self_excluded": True,
        "files": {name: sha256_bytes(payloads[name]) for name in BUNDLE_FILES},
    }
    (output / "checksums.json").write_text(
        canonical_json(checksums) + "\n", encoding="utf-8", newline="\n",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-committed-source", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    run_calibration(
        args.config,
        args.output,
        require_committed_source=args.require_committed_source,
    )
    print(f"wrote deterministic model-blind calibration bundle to {args.output}")
    print("No model was called and no evidence seed was simulated.")


if __name__ == "__main__":
    main()
