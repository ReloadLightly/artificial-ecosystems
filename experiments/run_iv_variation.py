#!/usr/bin/env python3
"""Build or replay the matched EVOLVE IV variation integration pilot.

The cached arm is strictly offline. ``--build-fixture-cache`` records an
explicit deterministic test fixture; it is not a model result. Ordinary runs
fail closed if any exact request is absent from the supplied cache.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields
import hashlib
import json
import math
import platform
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from evolve4.randomness import EcologyRandomStreams, IVSeedPlan
from evolve4.simulation import CONDITION_MAX, CONDITION_MIN, MetabolicConfig
from evolve_modern.iv import IVProgramController, build_controlled_sim
from evolve_modern.iv_policies import IVProgram
from evolve_modern.iv_variation import (
    CacheIntegrityError,
    CacheProvenance,
    CachedProposalOperator,
    CachedProposalProfile,
    CachedProposalStore,
    ProposalProvenance,
    ProposalRequest,
    RandomAtomicEditOperator,
    RawProposal,
    TypedHomologousRecombinationOperator,
    TypedPointOperator,
    make_cache_record,
)


EXPERIMENT_SCHEMA = 1
ARM_IDS = (
    "inherit_only",
    "typed_point_v1",
    "random_atomic_edit_v1",
    "typed_homologous_recombination_v1",
    "cached_proposal_fixture_v1",
)
BUNDLE_FILES = (
    "manifest.json",
    "runs.jsonl",
    "trajectories.jsonl",
    "events.jsonl",
    "summary.json",
)
SOURCE_FILES = (
    "experiments/run_iv_variation.py",
    "src/evolve4/control.py",
    "src/evolve4/randomness.py",
    "src/evolve4/simulation.py",
    "src/evolve_modern/iv.py",
    "src/evolve_modern/iv_policies.py",
    "src/evolve_modern/iv_variation.py",
)
PROFILE = CachedProposalProfile(
    provenance=CacheProvenance.FIXTURE,
    prompt_revision="one-atomic-edit-fixture-v1",
    prompt=(
        "Fixture only: return one deterministic atomic edit as canonical "
        "EVOLVE IV schema-v1 JSON."
    ),
    model_provider="fixture",
    model_name="random-atomic-test-double",
    model_revision="1",
    decoding={"temperature": 0.0, "max_output_tokens": 0},
)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sha256_text(payload: str) -> str:
    return sha256_bytes(payload.encode("utf-8"))


def canonical_sha(value: object) -> str:
    return sha256_text(canonical_json(value))


def jsonl_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    return ("".join(canonical_json(dict(row)) + "\n" for row in rows)).encode(
        "utf-8"
    )


def read_config(path: Path) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
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
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cannot load experiment config: {exc}") from exc
    required = {
        "schema",
        "experiment_id",
        "claim_status",
        "arms",
        "seeds",
        "proposal_budget",
        "require_full_budget",
        "physics",
        "initial_programs",
    }
    if type(payload) is not dict or set(payload) != required:
        raise ValueError(f"config keys must be exactly {sorted(required)}")
    if payload["schema"] != EXPERIMENT_SCHEMA:
        raise ValueError(f"config schema must be {EXPERIMENT_SCHEMA}")
    if tuple(payload["arms"]) != ARM_IDS:
        raise ValueError(f"config arms must be exactly {ARM_IDS}")
    if type(payload["experiment_id"]) is not str or not payload["experiment_id"]:
        raise ValueError("experiment_id must be nonempty text")
    if payload["claim_status"] != "exploratory_integration_replay_pilot":
        raise ValueError("claim_status must identify this non-inferential pilot")
    seeds = payload["seeds"]
    if (
        type(seeds) is not list
        or not seeds
        or any(type(seed) is not int or seed < 0 for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("seeds must be distinct nonnegative integers")
    budget = payload["proposal_budget"]
    if type(budget) is not int or budget <= 0:
        raise ValueError("proposal_budget must be a positive integer")
    if type(payload["require_full_budget"]) is not bool:
        raise ValueError("require_full_budget must be boolean")
    physics = payload["physics"]
    allowed_physics = {field.name for field in fields(MetabolicConfig)} - {"seed"}
    if type(physics) is not dict or set(physics) != allowed_physics:
        raise ValueError(
            "physics keys must be every MetabolicConfig field except seed"
        )
    programs = payload["initial_programs"]
    if type(programs) is not list or not programs:
        raise ValueError("initial_programs must be a nonempty list")
    typed = tuple(IVProgram.from_json(value) for value in programs)
    if [program.to_json() for program in typed] != programs:
        raise ValueError("initial_programs must contain canonical JSON strings")
    return payload


def initial_programs(config: Mapping[str, object]) -> tuple[IVProgram, ...]:
    values = config["initial_programs"]
    assert isinstance(values, list)
    return tuple(IVProgram.from_json(value) for value in values)


def make_physics(config: Mapping[str, object], seed: int) -> MetabolicConfig:
    values = dict(config["physics"])
    values["seed"] = seed
    return MetabolicConfig(**values)


def source_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


class FixtureRecorder:
    """Cache-addressed deterministic stand-in used only to build fixtures."""

    operator_id = CachedProposalOperator.operator_id
    operator_revision = CachedProposalOperator.operator_revision

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self._keys: set[str] = set()

    def propose(self, request: ProposalRequest) -> RawProposal:
        raw = RandomAtomicEditOperator().propose(request).raw_candidate
        record = make_cache_record(
            PROFILE,
            request,
            raw_text=raw,
            finish_reason="fixture",
            usage={"input_tokens": 0, "output_tokens": 0},
        )
        key = record["cache_key"]
        assert isinstance(key, str)
        if key in self._keys:
            raise RuntimeError(f"duplicate fixture request: {key}")
        self._keys.add(key)
        self.records.append(record)
        return RawProposal(
            operator_id=self.operator_id,
            operator_revision=self.operator_revision,
            provenance=ProposalProvenance.FIXTURE_CACHE,
            raw_candidate=raw,
            cache_key=key,
        )


def arm_operator(
    arm_id: str,
    store: CachedProposalStore | None,
) -> object | None:
    if arm_id == "inherit_only":
        return None
    if arm_id == "typed_point_v1":
        return TypedPointOperator()
    if arm_id == "random_atomic_edit_v1":
        return RandomAtomicEditOperator()
    if arm_id == "typed_homologous_recombination_v1":
        return TypedHomologousRecombinationOperator()
    if store is None:
        raise ValueError("the cached-proposal arm requires an offline cache")
    return CachedProposalOperator(profile=PROFILE, store=store)


def physical_state(simulation) -> dict[str, object]:
    return {
        "next_bug_id": simulation._next,
        "places": [asdict(place) for place in simulation.places],
        "bugs": [asdict(bug) for bug in sorted(simulation.bugs, key=lambda b: b.bug_id)],
    }


def program_population(controller: IVProgramController) -> list[dict[str, object]]:
    return [
        {"bug_id": bug_id, "program": controller.program_for(bug_id).to_json()}
        for bug_id in sorted(controller.records)
    ]


def _event_rows(
    *,
    run_id: str,
    arm_id: str,
    controller: IVProgramController,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in controller.record_payload():
        row = dict(record)
        row.update(
            {
                "schema": 1,
                "run_id": run_id,
                "arm_id": arm_id,
                "event_type": (
                    "seed" if record["parent_bug_id"] is None else "birth"
                ),
                "program_sha256": sha256_text(str(record["program"])),
                "parent_program_sha256": (
                    sha256_text(str(record["parent_program"]))
                    if record["parent_program"] is not None
                    else None
                ),
                "candidate_program_sha256": (
                    sha256_text(str(record["candidate_program"]))
                    if record["candidate_program"] is not None
                    else None
                ),
            }
        )
        rows.append(row)
    return rows


def _descriptive_run_metrics(
    trajectory: Sequence[Mapping[str, object]],
    *,
    max_organisms: int,
) -> dict[str, object]:
    """Return finite-horizon descriptors from post-step observations."""

    if not trajectory:
        raise ValueError("trajectory must contain at least one post-step observation")
    if type(max_organisms) is not int or max_organisms <= 0:
        raise ValueError("max_organisms must be a positive integer")

    population = [int(row["n_alive"]) for row in trajectory]
    producers = [int(row["n_producers"]) for row in trajectory]
    recyclers = [int(row["n_recyclers"]) for row in trajectory]
    if any(value < 0 or value > max_organisms for value in population):
        raise ValueError("recorded population must be within the configured ceiling")
    if any(
        producer < 0
        or recycler < 0
        or producer + recycler != alive
        for alive, producer, recycler in zip(population, producers, recyclers)
    ):
        raise ValueError("recorded producer/recycler counts must partition population")

    duration = len(trajectory)
    extinction_step = next(
        (
            int(row["step"])
            for row, alive in zip(trajectory, population)
            if alive == 0
        ),
        None,
    )
    births_total = sum(int(row["births"]) for row in trajectory)
    deaths_total = sum(int(row["deaths"]) for row in trajectory)
    return {
        "population_occupancy_auc_normalized": (
            sum(population) / (duration * max_organisms)
        ),
        "population_ceiling_fraction": (
            sum(alive == max_organisms for alive in population) / duration
        ),
        "role_coexistence_fraction": (
            sum(
                producer > 0 and recycler > 0
                for producer, recycler in zip(producers, recyclers)
            )
            / duration
        ),
        "extinction_step": extinction_step,
        "final_living_body_stored_matter": int(trajectory[-1]["stored"]),
        "turnover_total": births_total + deaths_total,
    }


def run_arm(
    config: Mapping[str, object],
    *,
    seed: int,
    arm_id: str,
    operator: object | None,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    plan = IVSeedPlan.from_master(seed)
    replicate_id = f"seed-{seed}"
    run_id = f"{replicate_id}--{arm_id}"
    mutation_probability = 0.0 if arm_id == "inherit_only" else 1.0
    simulation, controller = build_controlled_sim(
        make_physics(config, seed),
        controller_seed=plan.variation_gate,
        proposal_seed=plan.operator,
        mutation_probability=mutation_probability,
        proposal_budget=int(config["proposal_budget"]),
        programs=initial_programs(config),
        experiment_id=str(config["experiment_id"]),
        replicate_id=replicate_id,
        operator=operator,
        random_streams=EcologyRandomStreams.from_plan(plan),
    )
    initial_physical_sha = canonical_sha(physical_state(simulation))
    initial_program_sha = canonical_sha(program_population(controller))
    trajectory: list[dict[str, object]] = []
    for _ in range(simulation.cfg.steps):
        step = simulation.step()
        conserved = simulation.conserved() == simulation.cfg.total_units
        nonnegative = all(
            place.nutrient >= 0
            and place.waste >= 0
            and CONDITION_MIN <= place.condition <= CONDITION_MAX
            for place in simulation.places
        ) and all(bug.stored >= 0 for bug in simulation.bugs)
        if not conserved or not nonnegative:
            raise RuntimeError(f"physical invariant failed in {run_id} at {step.step}")
        row = asdict(step)
        row.update(
            {
                "schema": 1,
                "run_id": run_id,
                "replicate_id": replicate_id,
                "arm_id": arm_id,
                "conservation_ok": conserved,
                "nonnegative_ok": nonnegative,
                "proposal_budget_used": controller.proposal_budget_used,
                "n_unique_programs_alive": len(
                    {
                        controller.program_for(bug.bug_id).to_json()
                        for bug in simulation.bugs
                        if bug.alive
                    }
                ),
            }
        )
        trajectory.append(row)

    budget = int(config["proposal_budget"])
    if (
        arm_id != "inherit_only"
        and bool(config["require_full_budget"])
        and controller.proposal_budget_used != budget
    ):
        raise RuntimeError(
            f"{run_id} used {controller.proposal_budget_used}/{budget} proposals"
        )
    events = _event_rows(run_id=run_id, arm_id=arm_id, controller=controller)
    final_alive = [bug for bug in simulation.bugs if bug.alive]
    descriptive_metrics = _descriptive_run_metrics(
        trajectory,
        max_organisms=simulation.cfg.max_organisms,
    )
    run = {
        "schema": 1,
        "run_id": run_id,
        "replicate_id": replicate_id,
        "arm_id": arm_id,
        "master_seed": seed,
        "seed_plan": plan.to_dict(),
        "initial_physical_sha256": initial_physical_sha,
        "initial_programs_sha256": initial_program_sha,
        "final_physical_sha256": canonical_sha(physical_state(simulation)),
        "final_programs_sha256": canonical_sha(program_population(controller)),
        "final_rng_states_sha256": canonical_sha(
            {
                "ecology": simulation.random_streams.state_dict(),
                "variation_gate": controller.rng.bit_generator.state,
                "operator": controller.proposal_rng.bit_generator.state,
            }
        ),
        "steps_completed": len(trajectory),
        "proposal_budget_cap": budget,
        "proposal_budget_used": controller.proposal_budget_used,
        "proposals_accepted": controller.accepted_proposals,
        "proposals_rejected": controller.rejected_proposals,
        "births_total": sum(int(row["births"]) for row in trajectory),
        "deaths_total": sum(int(row["deaths"]) for row in trajectory),
        "alive_final": len(final_alive),
        "unique_programs_final": len(
            {controller.program_for(bug.bug_id).to_json() for bug in final_alive}
        ),
        "conservation_all_steps": all(row["conservation_ok"] for row in trajectory),
        "nonnegative_all_steps": all(row["nonnegative_ok"] for row in trajectory),
        **descriptive_metrics,
    }
    return run, trajectory, events


def build_fixture_cache(config: Mapping[str, object], path: Path) -> int:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite fixture cache: {path}")
    recorder = FixtureRecorder()
    for seed in config["seeds"]:
        run_arm(
            config,
            seed=int(seed),
            arm_id="cached_proposal_fixture_v1",
            operator=recorder,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(jsonl_bytes(recorder.records))
    return len(recorder.records)


def _arm_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    def values(key: str) -> list[int]:
        return [int(row[key]) for row in rows]

    def mean(key: str) -> float:
        sample = values(key)
        return sum(sample) / len(sample)

    def real_values(key: str) -> list[float]:
        return [float(row[key]) for row in rows]

    def real_mean(key: str) -> float:
        sample = real_values(key)
        return sum(sample) / len(sample)

    return {
        "runs": len(rows),
        "proposal_budget_used": values("proposal_budget_used"),
        "proposals_accepted_total": sum(values("proposals_accepted")),
        "proposals_rejected_total": sum(values("proposals_rejected")),
        "births_total": values("births_total"),
        "deaths_total": values("deaths_total"),
        "turnover_total": values("turnover_total"),
        "turnover_total_mean": mean("turnover_total"),
        "alive_final": values("alive_final"),
        "alive_final_mean": mean("alive_final"),
        "unique_programs_final": values("unique_programs_final"),
        "population_occupancy_auc_normalized": real_values(
            "population_occupancy_auc_normalized"
        ),
        "population_occupancy_auc_normalized_mean": real_mean(
            "population_occupancy_auc_normalized"
        ),
        "population_ceiling_fraction": real_values(
            "population_ceiling_fraction"
        ),
        "population_ceiling_fraction_mean": real_mean(
            "population_ceiling_fraction"
        ),
        "role_coexistence_fraction": real_values("role_coexistence_fraction"),
        "role_coexistence_fraction_mean": real_mean(
            "role_coexistence_fraction"
        ),
        "extinction_step": [row["extinction_step"] for row in rows],
        "extinction_count": sum(row["extinction_step"] is not None for row in rows),
        "final_living_body_stored_matter": values(
            "final_living_body_stored_matter"
        ),
        "final_living_body_stored_matter_mean": mean(
            "final_living_body_stored_matter"
        ),
    }


def make_summary(runs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    grouped = {
        arm: [row for row in runs if row["arm_id"] == arm] for arm in ARM_IDS
    }
    fingerprints_match = all(
        len(
            {
                (row["initial_physical_sha256"], row["initial_programs_sha256"])
                for row in runs
                if row["replicate_id"] == replicate
            }
        )
        == 1
        for replicate in {str(row["replicate_id"]) for row in runs}
    )
    return {
        "schema": 1,
        "claim_status": "exploratory_integration_replay_pilot",
        "interpretation": (
            "Descriptive integration metrics only. The fixture cache is not a "
            "model result, and this pilot does not rank variation operators."
        ),
        "protocol_checks": {
            "arm_ids_exact": tuple(grouped) == ARM_IDS,
            "initial_fingerprints_match_within_seed": fingerprints_match,
            "conservation_all_runs": all(
                bool(row["conservation_all_steps"]) for row in runs
            ),
            "nonnegative_all_runs": all(
                bool(row["nonnegative_all_steps"]) for row in runs
            ),
            "operator_budgets_full": all(
                arm == "inherit_only"
                or all(
                    row["proposal_budget_used"] == row["proposal_budget_cap"]
                    for row in rows
                )
                for arm, rows in grouped.items()
            ),
            "no_live_model_calls": True,
            "fixture_cache_only": True,
        },
        "arms": {arm: _arm_summary(rows) for arm, rows in grouped.items()},
    }


def build_manifest(
    config: Mapping[str, object],
    *,
    config_path: Path,
    cache_path: Path,
    cache_entries: int,
) -> dict[str, object]:
    programs = list(config["initial_programs"])
    return {
        "schema": 1,
        "experiment_id": config["experiment_id"],
        "claim_status": config["claim_status"],
        "source_commit": source_commit(),
        "source_files_sha256": {
            name: sha256_bytes((ROOT / name).read_bytes()) for name in SOURCE_FILES
        },
        "generated_by": "experiments/run_iv_variation.py",
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "rng": "numpy.random.PCG64",
            "seed_derivation": "IVSeedPlan-v1",
        },
        "inputs": {
            "config_sha256": sha256_bytes(config_path.read_bytes()),
            "cache_sha256": sha256_bytes(cache_path.read_bytes()),
            "cache_entries": cache_entries,
            "cache_provenance": "fixture",
            "initial_programs_sha256": canonical_sha(programs),
        },
        "arms": list(ARM_IDS),
        "seeds": [
            IVSeedPlan.from_master(int(seed)).to_dict() for seed in config["seeds"]
        ],
        "matching": {
            "same_initial_program_bytes": True,
            "same_physics_and_named_ecology_seeds": True,
            "one_candidate_per_budgeted_birth": True,
            "proposal_budget_cost": 1,
            "proposal_budget": config["proposal_budget"],
            "common_random_seeds_not_paired_counterfactuals": True,
        },
        "record_schemas": {
            "runs.jsonl": 1,
            "trajectories.jsonl": 1,
            "events.jsonl": 1,
            "summary.json": 1,
        },
        "metric_definitions": {
            "population_occupancy_auc_normalized": (
                "sum of post-step n_alive divided by the product of recorded "
                "steps and max_organisms"
            ),
            "population_ceiling_fraction": (
                "fraction of recorded post-step observations with n_alive equal "
                "to max_organisms"
            ),
            "role_coexistence_fraction": (
                "fraction of recorded post-step observations with at least one "
                "producer and one recycler alive"
            ),
            "extinction_step": (
                "first recorded step with n_alive equal to zero, otherwise null"
            ),
            "final_living_body_stored_matter": (
                "stored matter in living organisms at the final recorded step"
            ),
            "turnover_total": "births_total plus deaths_total within the run",
        },
        "limitations": [
            "This small fixed-seed pilot is descriptive and non-inferential.",
            "The cached arm replays synthetic fixture proposals, not model output.",
            "Homologous typed-leaf recombination is not recursive subtree GP.",
            "Common stateful streams do not preserve draw-level pairing after divergence.",
        ],
        "reproduce": (
            "PYTHONPATH=src python3 experiments/run_iv_variation.py "
            "--config <config> --cache <cache> --output <new-directory>"
        ),
    }


def run_experiment(config_path: Path, cache_path: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output directory: {output}")
    config = read_config(config_path)
    store = CachedProposalStore.from_jsonl(cache_path)
    expected_cache_entries = len(config["seeds"]) * int(config["proposal_budget"])
    if len(store) != expected_cache_entries:
        raise CacheIntegrityError(
            "fixture cache must contain exactly "
            f"{expected_cache_entries} records; found {len(store)}"
        )
    runs: list[dict[str, object]] = []
    trajectories: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    for seed in config["seeds"]:
        for arm_id in ARM_IDS:
            run, arm_trajectory, arm_events = run_arm(
                config,
                seed=int(seed),
                arm_id=arm_id,
                operator=arm_operator(arm_id, store),
            )
            runs.append(run)
            trajectories.extend(arm_trajectory)
            events.extend(arm_events)

    summary = make_summary(runs)
    if not all(summary["protocol_checks"].values()):
        raise RuntimeError(f"pilot protocol check failed: {summary['protocol_checks']}")
    output.mkdir(parents=True)
    payloads = {
        "manifest.json": (
            canonical_json(
                build_manifest(
                    config,
                    config_path=config_path,
                    cache_path=cache_path,
                    cache_entries=len(store),
                )
            )
            + "\n"
        ).encode("utf-8"),
        "runs.jsonl": jsonl_bytes(runs),
        "trajectories.jsonl": jsonl_bytes(trajectories),
        "events.jsonl": jsonl_bytes(events),
        "summary.json": (canonical_json(summary) + "\n").encode("utf-8"),
    }
    for name in BUNDLE_FILES:
        (output / name).write_bytes(payloads[name])
    checksums = {
        "schema": 1,
        "algorithm": "sha256",
        "self_excluded": True,
        "files": {name: sha256_bytes(payloads[name]) for name in BUNDLE_FILES},
    }
    (output / "checksums.json").write_text(
        canonical_json(checksums) + "\n", encoding="utf-8", newline="\n"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--build-fixture-cache", type=Path)
    action.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.cache is not None and args.output is None:
        parser.error("--cache requires --output")
    if args.build_fixture_cache is not None and args.output is not None:
        parser.error("--build-fixture-cache does not accept --output")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    config = read_config(args.config)
    if args.build_fixture_cache is not None:
        count = build_fixture_cache(config, args.build_fixture_cache)
        print(f"wrote {count} deterministic fixture responses")
        print("Fixture provenance only: no live or cached model was used.")
        return
    run_experiment(args.config, args.cache, args.output)
    print(f"wrote deterministic pilot bundle to {args.output}")
    print("Descriptive integration metrics only; no operator ranking or LLM claim.")


if __name__ == "__main__":
    main()
