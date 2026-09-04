#!/usr/bin/env python3
"""Plan or verify an authentic-response cache without provider access."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evolve_modern.model_collection import (
    canonical_sha256,
    CollectionIntegrityError,
    CollectionPlan,
    CollectionProfile,
    inspect_spool,
    read_jsonl_cache,
    sha256_bytes,
    _strict_json,
)
from evolve4.randomness import IVSeedPlan

import numpy as np


CANONICAL_WORLD_PATH = Path(
    "results/reference/iv-world-calibration-v1/frozen-world.json"
)
CALIBRATION_CONFIG_PATH = Path(
    "experiments/configs/iv-world-calibration-v1.json"
)
SOURCE_CONFIG_PATH = Path("experiments/configs/iv-variation-pilot-v1.json")
EXPECTED_CALIBRATION_CONFIG_SHA256 = (
    "sha256:de68318a8bfb298b012b825ab21d90bf83eecc7777caed187ab264b08a555a6e"
)
EXPECTED_SOURCE_CONFIG_SHA256 = (
    "sha256:b54fcef9af069912320d31b4e3cfb2ce1cc0983d7f8b040e020ce238312d66b1"
)
CALIBRATION_SEEDS = (101, 503, 1601, 4099, 8081, 12007, 16001, 24001)
SELECTED_CAPACITY = 176
DESIGN_TIMING = {
    "headroom_rule": "capacity_gate_occupancy_fraction_max",
    "headroom_threshold": 0.85,
    "status": "exploratory_post_scan_rule_finalization",
    "preregistered": False,
    "informed_by_variation_or_model_outcomes": False,
}
CALIBRATION_BUNDLE_FILES = {
    "calibration-runs.jsonl", "calibration-decision.json", "frozen-world.json",
    "manifest.json",
}
CALIBRATION_SOURCE_FILES = {
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
}


def _exact_keys(value: object, expected: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        actual = set(value) if type(value) is dict else set()
        raise CollectionIntegrityError(
            f"{label} keys differ; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )
    return value


def _sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 71 or not value.startswith("sha256:"):
        raise CollectionIntegrityError(f"{label} must be a sha256 digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise CollectionIntegrityError(f"{label} must be a sha256 digest") from exc
    return value


def _repository_file(configured: str | Path, label: str) -> Path:
    relative = Path(configured)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != str(configured)
    ):
        raise CollectionIntegrityError(
            f"{label} must be a canonical repository-relative path"
        )
    root = ROOT.resolve()
    unresolved = ROOT / relative
    if unresolved.is_symlink():
        raise CollectionIntegrityError(f"{label} must not be a symlink")
    try:
        resolved = unresolved.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise CollectionIntegrityError(
            f"{label} is unavailable within the repository: {exc}"
        ) from exc
    return resolved


def _read_json(path: Path, label: str) -> tuple[bytes, object]:
    try:
        mode = path.stat(follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode):
            raise CollectionIntegrityError(f"{label} must be a regular file")
        payload = path.read_bytes()
        value = _strict_json(payload.decode("utf-8"))
    except CollectionIntegrityError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise CollectionIntegrityError(f"cannot read {label}: {exc}") from exc
    return payload, value


def _world_path(profile_path: Path, profile: CollectionProfile) -> Path:
    del profile_path
    configured = str(profile.to_mapping()["frozen_world_path"])
    return _repository_file(configured, "frozen_world_path")


def verify_frozen_world(
    profile_path: Path,
    profile: CollectionProfile,
) -> dict[str, object]:
    path = _world_path(profile_path, profile)
    payload, world = _read_json(path, "frozen world")
    digest = sha256_bytes(payload)
    expected = profile.to_mapping()["frozen_world_sha256"]
    if digest != expected:
        raise CollectionIntegrityError("frozen world checksum mismatch")
    if type(world) is not dict:
        raise CollectionIntegrityError("frozen world must be a JSON object")
    _validate_frozen_world(world)
    if profile.to_mapping()["frozen_world_path"] == CANONICAL_WORLD_PATH.as_posix():
        _validate_calibration_bundle(path.parent, payload, world)
    return world


def _contract_configs() -> tuple[dict[str, object], dict[str, object]]:
    calibration_path = _repository_file(
        CALIBRATION_CONFIG_PATH, "calibration config"
    )
    source_path = _repository_file(SOURCE_CONFIG_PATH, "source config")
    calibration_bytes, calibration = _read_json(
        calibration_path, "calibration config"
    )
    source_bytes, source = _read_json(source_path, "source config")
    if sha256_bytes(calibration_bytes) != EXPECTED_CALIBRATION_CONFIG_SHA256:
        raise CollectionIntegrityError(
            "calibration config differs from the versioned v1 contract"
        )
    if sha256_bytes(source_bytes) != EXPECTED_SOURCE_CONFIG_SHA256:
        raise CollectionIntegrityError(
            "source config differs from the versioned v1 contract"
        )
    assert isinstance(calibration, dict) and isinstance(source, dict)
    return calibration, source


def _validate_frozen_world(world: dict[str, object]) -> None:
    _exact_keys(
        world,
        {
            "schema", "world_id", "calibration_id", "claim_status",
            "design_timing", "selected_max_organisms", "physics",
            "proposal_budget_policy",
            "initial_programs", "qualification_seeds", "evidence_seeds",
            "bindings",
        },
        "frozen world",
    )
    if (
        world["schema"] != 1
        or world["world_id"] != "iv-variation-world-v1"
        or world["calibration_id"] != "iv-world-calibration-v1"
        or world["claim_status"]
        != "model_blind_selected_before_authentic_model_evidence"
        or world["design_timing"] != DESIGN_TIMING
        or world["selected_max_organisms"] != SELECTED_CAPACITY
    ):
        raise CollectionIntegrityError(
            "frozen world identity, calibration, or selected capacity is invalid"
        )
    calibration, source = _contract_configs()
    if calibration.get("calibration_seeds") != list(CALIBRATION_SEEDS):
        raise CollectionIntegrityError("calibration seed contract is invalid")
    expected_physics = dict(source["physics"])
    expected_physics["max_organisms"] = SELECTED_CAPACITY
    expected_programs = source["initial_programs"]
    expected_policy = {
        "trigger": "birth_event",
        "per_replicate_upper_cap": source["proposal_budget"],
        "terminal_shortfall": "preserved_as_outcome",
        "authentic_evidence_requires_full_budget": False,
    }
    if world["physics"] != expected_physics:
        raise CollectionIntegrityError("frozen world physics differ from v1")
    if world["initial_programs"] != expected_programs:
        raise CollectionIntegrityError("frozen initial programs differ from v1")
    if world["proposal_budget_policy"] != expected_policy:
        raise CollectionIntegrityError("frozen proposal-budget policy differs from v1")

    qualification_spec = calibration.get("qualification_seed_reservation")
    evidence_spec = calibration.get("evidence_seed_reservation")
    qualification = validate_reservation_record(
        world["qualification_seeds"],
        expected_specification=qualification_spec,
        label="qualification",
    )
    evidence = validate_reservation_record(
        world["evidence_seeds"],
        expected_specification=evidence_spec,
        label="evidence",
    )
    groups = (set(CALIBRATION_SEEDS), set(qualification), set(evidence))
    if any(groups[i] & groups[j] for i in range(3) for j in range(i + 1, 3)):
        raise CollectionIntegrityError(
            "calibration, qualification, and evidence seeds must be disjoint"
        )

    bindings = _exact_keys(
        world["bindings"],
        {
            "calibration_config_sha256", "source_config_sha256",
            "calibration_decision_sha256", "physics_sha256",
            "initial_programs_sha256", "proposal_budget_policy_sha256",
        },
        "frozen world bindings",
    )
    for key, expected in {
        "calibration_config_sha256": EXPECTED_CALIBRATION_CONFIG_SHA256,
        "source_config_sha256": EXPECTED_SOURCE_CONFIG_SHA256,
        "physics_sha256": canonical_sha256(expected_physics, "physics"),
        "initial_programs_sha256": canonical_sha256(
            expected_programs, "initial programs"
        ),
        "proposal_budget_policy_sha256": canonical_sha256(
            expected_policy, "proposal budget policy"
        ),
    }.items():
        if bindings[key] != expected:
            raise CollectionIntegrityError(f"frozen world {key} mismatch")
    _sha(bindings["calibration_decision_sha256"], "calibration decision binding")


def _validate_calibration_bundle(
    directory: Path,
    frozen_bytes: bytes,
    world: dict[str, object],
) -> None:
    payloads: dict[str, bytes] = {"frozen-world.json": frozen_bytes}
    values: dict[str, object] = {"frozen-world.json": world}
    for name in CALIBRATION_BUNDLE_FILES - {"frozen-world.json"}:
        path = directory / name
        if name == "calibration-runs.jsonl":
            try:
                raw = path.read_bytes()
                for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
                    if line.strip():
                        value = _strict_json(line)
                        if type(value) is not dict:
                            raise CollectionIntegrityError(
                                f"calibration run line {number} must be an object"
                            )
            except (OSError, UnicodeDecodeError) as exc:
                raise CollectionIntegrityError(
                    f"cannot read calibration bundle {name}: {exc}"
                ) from exc
            value = None
        else:
            raw, value = _read_json(path, f"calibration bundle {name}")
        payloads[name] = raw
        values[name] = value
    checksums_raw, checksums_value = _read_json(
        directory / "checksums.json", "calibration bundle checksums"
    )
    del checksums_raw
    checksums = _exact_keys(
        checksums_value,
        {"schema", "algorithm", "self_excluded", "files"},
        "calibration checksums",
    )
    if (
        checksums["schema"] != 1
        or checksums["algorithm"] != "sha256"
        or checksums["self_excluded"] is not True
    ):
        raise CollectionIntegrityError("calibration checksums identity is invalid")
    files = _exact_keys(
        checksums["files"], CALIBRATION_BUNDLE_FILES, "calibration checksum files"
    )
    for name, raw in payloads.items():
        if files[name] != sha256_bytes(raw):
            raise CollectionIntegrityError(
                f"calibration bundle checksum mismatch: {name}"
            )

    decision = _exact_keys(
        values["calibration-decision.json"],
        {
            "schema", "calibration_id", "claim_status", "selection_rule",
            "design_timing",
            "selected_max_organisms", "sentinel_max_organisms",
            "candidate_evaluations", "protocol_checks",
        },
        "calibration decision",
    )
    if (
        decision["schema"] != 1
        or decision["calibration_id"] != "iv-world-calibration-v1"
        or decision["claim_status"] != "model_blind_world_calibration"
        or decision["design_timing"] != DESIGN_TIMING
        or decision["selected_max_organisms"] != SELECTED_CAPACITY
        or decision["sentinel_max_organisms"] != 192
        or type(decision["protocol_checks"]) is not dict
        or not all(bool(value) for value in decision["protocol_checks"].values())
    ):
        raise CollectionIntegrityError("calibration decision is invalid")
    evaluations = decision["candidate_evaluations"]
    expected_caps = [112, 120, 128, 144, 160, 176]
    if (
        type(evaluations) is not list
        or len(evaluations) != len(expected_caps)
        or [item.get("max_organisms") for item in evaluations] != expected_caps
        or any(
            type(item) is not dict
            or set(item) != {"max_organisms", "seed_evaluations", "eligible"}
            or type(item["eligible"]) is not bool
            or type(item["seed_evaluations"]) is not list
            or len(item["seed_evaluations"]) != len(CALIBRATION_SEEDS)
            for item in evaluations
        )
        or not any(item["eligible"] for item in evaluations)
        or min(
            item["max_organisms"] for item in evaluations if item["eligible"]
        ) != SELECTED_CAPACITY
    ):
        raise CollectionIntegrityError(
            "calibration decision candidate selection is inconsistent"
        )
    decision_sha = sha256_bytes(payloads["calibration-decision.json"])
    if world["bindings"]["calibration_decision_sha256"] != decision_sha:
        raise CollectionIntegrityError(
            "frozen world calibration-decision binding mismatch"
        )

    manifest = _exact_keys(
        values["manifest.json"],
        {
            "schema", "calibration_id", "claim_status", "generated_by",
            "source_commit", "source_commit_scope", "source_files_match_commit",
            "source_files_sha256", "environment", "inputs", "protocol",
            "reserved_seeds", "artifacts_sha256", "reproduce",
        },
        "calibration manifest",
    )
    if (
        manifest["schema"] != 1
        or manifest["calibration_id"] != "iv-world-calibration-v1"
        or manifest["claim_status"] != "model_blind_world_calibration"
        or manifest["generated_by"] != "experiments/calibrate_iv_world.py"
        or manifest["source_files_match_commit"] is not True
        or manifest["source_commit_scope"]
        != "latest commit touching any source_files_sha256 path"
    ):
        raise CollectionIntegrityError("calibration manifest identity is invalid")
    calibration, source = _contract_configs()
    inputs = _exact_keys(
        manifest["inputs"],
        {
            "calibration_config_path", "calibration_config_sha256",
            "source_config_path", "source_config_sha256",
            "initial_programs_sha256",
        },
        "calibration manifest inputs",
    )
    if inputs != {
        "calibration_config_path": CALIBRATION_CONFIG_PATH.as_posix(),
        "calibration_config_sha256": EXPECTED_CALIBRATION_CONFIG_SHA256,
        "source_config_path": SOURCE_CONFIG_PATH.as_posix(),
        "source_config_sha256": EXPECTED_SOURCE_CONFIG_SHA256,
        "initial_programs_sha256": canonical_sha256(
            source["initial_programs"], "initial programs"
        ),
    }:
        raise CollectionIntegrityError("calibration manifest input binding mismatch")
    protocol = _exact_keys(
        manifest["protocol"],
        {
            "arm", "steps", "calibration_seeds", "candidate_max_organisms",
            "sentinel_max_organisms", "design_timing", "varied_physics_fields",
            "trajectory_scope", "acceptance", "proposal_budget_policy",
            "no_model_calls", "no_variation_operator",
        },
        "calibration manifest protocol",
    )
    expected_protocol = {
        "arm": "inherit_only",
        "steps": 64,
        "calibration_seeds": list(CALIBRATION_SEEDS),
        "candidate_max_organisms": expected_caps,
        "sentinel_max_organisms": 192,
        "design_timing": DESIGN_TIMING,
        "varied_physics_fields": ["max_organisms"],
        "trajectory_scope": "projected_step_aggregate_summary_not_full_microstate",
        "acceptance": calibration["acceptance"],
        "proposal_budget_policy": world["proposal_budget_policy"],
        "no_model_calls": True,
        "no_variation_operator": True,
    }
    if protocol != expected_protocol:
        raise CollectionIntegrityError("calibration manifest protocol mismatch")
    artifacts = _exact_keys(
        manifest["artifacts_sha256"],
        {"calibration-runs.jsonl", "calibration-decision.json", "frozen-world.json"},
        "calibration manifest artifacts",
    )
    for name in artifacts:
        if artifacts[name] != sha256_bytes(payloads[name]):
            raise CollectionIntegrityError(
                f"calibration manifest artifact mismatch: {name}"
            )
    if manifest["reserved_seeds"] != {
        "qualification": world["qualification_seeds"],
        "evidence": world["evidence_seeds"],
    }:
        raise CollectionIntegrityError("calibration manifest seed reservations mismatch")
    source_files = _exact_keys(
        manifest["source_files_sha256"],
        CALIBRATION_SOURCE_FILES,
        "calibration manifest source files",
    )
    commit = manifest["source_commit"]
    if (
        type(commit) is not str
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise CollectionIntegrityError("calibration source_commit must be a full Git SHA")
    for name, expected in source_files.items():
        actual = sha256_bytes(_git_blob(commit, name))
        if actual != expected:
            raise CollectionIntegrityError(
                f"calibration source checksum mismatch: {name}"
            )


def _git_blob(commit: str, path: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CollectionIntegrityError(
            f"cannot resolve calibration source {path} at {commit}"
        ) from exc


def validate_reservation_record(
    record: object,
    *,
    expected_specification: object | None = None,
    label: str = "evidence",
) -> tuple[int, ...]:
    """Validate a frozen seed reservation down to every named RNG stream."""
    expected_keys = {
        "derivation", "derivation_version", "root", "count", "master_seeds",
        "master_seeds_sha256", "seed_plans", "seed_plans_sha256",
    }
    if type(record) is not dict or set(record) != expected_keys:
        raise CollectionIntegrityError(
            f"frozen {label}-seed reservation has an invalid schema"
        )
    if (
        record["derivation"] != "numpy-seedsequence-spawn-uint64"
        or record["derivation_version"] != 1
        or type(record["root"]) is not int
        or not 0 <= record["root"] < 2**64
        or type(record["count"]) is not int
        or record["count"] <= 0
    ):
        raise CollectionIntegrityError(
            f"frozen {label}-seed derivation metadata is invalid"
        )
    metadata = {
        key: record[key]
        for key in ("derivation", "derivation_version", "root", "count")
    }
    if expected_specification is not None and metadata != expected_specification:
        raise CollectionIntegrityError(
            f"frozen {label}-seed reservation differs from calibration config"
        )
    children = np.random.SeedSequence(record["root"]).spawn(record["count"])
    expected_seeds = tuple(
        int(child.generate_state(1, dtype=np.uint64)[0])
        for child in children
    )
    if record["master_seeds"] != list(expected_seeds):
        raise CollectionIntegrityError(
            f"frozen {label} master seeds differ from their derivation"
        )
    if record["master_seeds_sha256"] != canonical_sha256(
        list(expected_seeds),
        "frozen evidence master seeds",
    ):
        raise CollectionIntegrityError(
            f"frozen {label} master-seed checksum mismatch"
        )
    expected_plans = [
        IVSeedPlan.from_master(seed).to_dict() for seed in expected_seeds
    ]
    if record["seed_plans"] != expected_plans:
        raise CollectionIntegrityError(
            f"frozen {label} seed plans differ from IVSeedPlan-v1"
        )
    if record["seed_plans_sha256"] != canonical_sha256(
        expected_plans,
        "frozen evidence seed plans",
    ):
        raise CollectionIntegrityError(
            f"frozen {label} seed-plan checksum mismatch"
        )
    return expected_seeds


def maximum_slot_order(
    profile: CollectionProfile,
    world: dict[str, object],
) -> tuple[tuple[str, int], ...]:
    try:
        if (
            world["schema"] != 1
            or world["world_id"] != "iv-variation-world-v1"
            or world["claim_status"]
            != "model_blind_selected_before_authentic_model_evidence"
        ):
            raise CollectionIntegrityError("frozen world identity is invalid")
        seeds = validate_reservation_record(world["evidence_seeds"])
        budget = profile.to_mapping()["budget"]
        assert isinstance(budget, dict)
        replicates = int(budget["replicates"])
        opportunities = int(budget["proposals_per_replicate"])
        policy = world["proposal_budget_policy"]
        assert isinstance(policy, dict)
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        raise CollectionIntegrityError(
            "frozen world lacks a valid evidence-seed reservation"
        ) from exc
    if (
        len(seeds) != replicates
        or any(
            type(seed) is not int or not 0 <= seed < 2**64
            for seed in seeds
        )
        or len(set(seeds)) != len(seeds)
    ):
        raise CollectionIntegrityError(
            "frozen evidence seeds do not match the profile replicate count"
        )
    expected_policy = {
        "trigger": "birth_event",
        "per_replicate_upper_cap": opportunities,
        "terminal_shortfall": "preserved_as_outcome",
        "authentic_evidence_requires_full_budget": False,
    }
    if policy != expected_policy:
        raise CollectionIntegrityError(
            "frozen proposal-budget policy differs from the profile upper cap"
        )
    return tuple(
        (f"seed-{seed}", opportunity)
        for seed in seeds
        for opportunity in range(opportunities)
    )


def verify_implementation_sources(profile: CollectionProfile) -> str:
    """Verify every hash-bound implementation source as repository bytes."""
    values = profile.to_mapping()["implementation"]
    assert isinstance(values, dict)
    source_files = values["source_files_sha256"]
    assert isinstance(source_files, dict)
    repository = ROOT.resolve()
    for source_path, expected_sha256 in source_files.items():
        candidate = (ROOT / source_path).resolve()
        try:
            candidate.relative_to(repository)
        except ValueError as exc:
            raise CollectionIntegrityError(
                "implementation source resolves outside the repository"
            ) from exc
        try:
            actual_sha256 = sha256_bytes(candidate.read_bytes())
        except OSError as exc:
            raise CollectionIntegrityError(
                f"cannot read implementation source {source_path}: {exc}"
            ) from exc
        if actual_sha256 != expected_sha256:
            raise CollectionIntegrityError(
                f"implementation source checksum mismatch: {source_path}"
            )
    return str(values["source_bundle_sha256"])


def verify_pricing_snapshot(profile: CollectionProfile) -> str:
    """Verify a ready profile's versioned pricing source as repository bytes."""
    pricing = profile.to_mapping()["pricing"]
    assert isinstance(pricing, dict)
    if pricing["status"] == "pending_provider_selection":
        return "pending_provider_selection"
    path = _repository_file(
        str(pricing["snapshot_path"]), "pricing snapshot"
    )
    try:
        actual = sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise CollectionIntegrityError(
            f"cannot read pricing snapshot: {exc}"
        ) from exc
    if actual != pricing["snapshot_sha256"]:
        raise CollectionIntegrityError("pricing snapshot checksum mismatch")
    try:
        date.fromisoformat(str(pricing["effective_date"]))
    except ValueError as exc:
        raise CollectionIntegrityError("pricing effective date is invalid") from exc
    return "verified"


def build_plan(profile_path: str | Path) -> dict[str, object]:
    path = Path(profile_path)
    profile = CollectionProfile.from_json(path)
    world = verify_frozen_world(path, profile)
    maximum_slots = maximum_slot_order(profile, world)
    source_bundle_sha256 = verify_implementation_sources(profile)
    pricing_snapshot_verification = verify_pricing_snapshot(profile)
    result = CollectionPlan.from_profile(profile).to_mapping()
    result["frozen_world_verification"] = "verified"
    result["implementation_sources_verification"] = "verified"
    result["implementation_source_bundle_sha256"] = source_bundle_sha256
    result["pricing_snapshot_verification"] = pricing_snapshot_verification
    result["maximum_request_slots"] = len(maximum_slots)
    return result


def verify_cache(profile_path: str | Path, input_path: str | Path) -> dict[str, object]:
    profile_file = Path(profile_path)
    profile = CollectionProfile.from_json(profile_file)
    if profile.status != "ready_for_explicit_authorization":
        raise CollectionIntegrityError(
            "cannot verify an authentic cache against an unselected provider"
        )
    world = verify_frozen_world(profile_file, profile)
    maximum_slots = maximum_slot_order(profile, world)
    source_bundle_sha256 = verify_implementation_sources(profile)
    pricing_snapshot_verification = verify_pricing_snapshot(profile)
    path = Path(input_path)
    inspection = (
        inspect_spool(path, profile, expected_schedule=maximum_slots)
        if path.is_dir()
        else read_jsonl_cache(path, profile, expected_schedule=maximum_slots)
    )
    if inspection.pending_request_sha256 is not None:
        raise CollectionIntegrityError(
            "cache verification cannot pass with an unresolved pending request"
        )
    return {
        "schema": 1,
        "status": (
            "structurally_valid_ordered_sequence_at_call_ceiling"
            if inspection.at_call_ceiling
            else "structurally_valid_ordered_sequence"
        ),
        "profile_sha256": profile.profile_sha256,
        "completed_count": inspection.completed_count,
        "next_sequence_index": inspection.next_sequence_index,
        "pending_request_sha256": inspection.pending_request_sha256,
        "at_call_ceiling": inspection.at_call_ceiling,
        "maximum_slot_order_verified": True,
        "implementation_sources_verified": True,
        "implementation_source_bundle_sha256": source_bundle_sha256,
        "pricing_snapshot_verification": pricing_snapshot_verification,
        "trajectory_verified": False,
        "replay_ready": False,
        "replay_validation_required": True,
        "network_calls_made": 0,
        "credentials_read": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="print a bounded offline plan")
    plan.add_argument("--profile", type=Path, required=True)
    plan.add_argument("--output", type=Path)
    verify = commands.add_parser("verify", help="verify a JSONL cache or spool")
    verify.add_argument("--profile", type=Path, required=True)
    verify.add_argument("--input", type=Path, required=True)
    return parser


PARSER = _parser()


def main(argv: list[str] | None = None) -> int:
    args = PARSER.parse_args(argv)
    try:
        result = (
            build_plan(args.profile)
            if args.command == "plan"
            else verify_cache(args.profile, args.input)
        )
    except CollectionIntegrityError as exc:
        print(f"collection integrity error: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    output = getattr(args, "output", None)
    if output is None:
        sys.stdout.write(rendered)
    else:
        if output.exists():
            print(f"refusing to overwrite: {output}", file=sys.stderr)
            return 2
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
