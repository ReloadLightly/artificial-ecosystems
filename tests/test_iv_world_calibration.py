"""Contracts for the model-blind IV world calibration and qualification."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CALIBRATION = load_script(
    "calibrate_iv_world",
    ROOT / "experiments" / "calibrate_iv_world.py",
)
VARIATION = load_script(
    "run_iv_variation_for_calibration_tests",
    ROOT / "experiments" / "run_iv_variation.py",
)

CALIBRATION_CONFIG = (
    ROOT / "experiments" / "configs" / "iv-world-calibration-v1.json"
)
QUALIFICATION_CONFIG = (
    ROOT / "experiments" / "configs" / "iv-variation-qualification-v1.json"
)
PILOT_CONFIG = (
    ROOT / "experiments" / "configs" / "iv-variation-pilot-v1.json"
)
REFERENCE = ROOT / "results" / "reference" / "iv-world-calibration-v1"

CALIBRATION_SEEDS = (101, 503, 1601, 4099, 8081, 12007, 16001, 24001)
CANDIDATES = (112, 120, 128, 144, 160, 176)
SENTINEL = 192
QUALIFICATION_SEEDS = (
    5734163613718072789,
    10843568836493112964,
    5360109053914373194,
    9040270409388520618,
)
EVIDENCE_SEEDS = (
    7591592684187682497,
    2275270120458329610,
    18348701203143951756,
    10406254645250620281,
)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class IVWorldCalibrationTests(unittest.TestCase):
    def test_config_freezes_the_exact_model_blind_protocol(self) -> None:
        config = CALIBRATION.read_config(CALIBRATION_CONFIG)

        self.assertEqual(
            set(config),
            {
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
            },
        )
        self.assertEqual(config["schema"], 1)
        self.assertEqual(config["calibration_id"], "iv-world-calibration-v1")
        self.assertEqual(config["claim_status"], "model_blind_world_calibration")
        self.assertEqual(config["source_config"], str(PILOT_CONFIG.relative_to(ROOT)))
        self.assertEqual(config["calibration_arm"], "inherit_only")
        self.assertEqual(tuple(config["calibration_seeds"]), CALIBRATION_SEEDS)
        self.assertEqual(config["steps"], 64)
        self.assertEqual(tuple(config["candidate_max_organisms"]), CANDIDATES)
        self.assertEqual(config["sentinel_max_organisms"], SENTINEL)
        self.assertEqual(
            config["design_timing"],
            {
                "headroom_rule": "capacity_gate_occupancy_fraction_max",
                "headroom_threshold": 0.85,
                "status": "exploratory_post_scan_rule_finalization",
                "preregistered": False,
                "informed_by_variation_or_model_outcomes": False,
            },
        )

        qualification = config["qualification_seed_reservation"]
        evidence = config["evidence_seed_reservation"]
        self.assertEqual(
            qualification,
            {
                "derivation": "numpy-seedsequence-spawn-uint64",
                "derivation_version": 1,
                "root": 20260905,
                "count": 4,
            },
        )
        self.assertEqual(
            evidence,
            {
                "derivation": "numpy-seedsequence-spawn-uint64",
                "derivation_version": 1,
                "root": 20260906,
                "count": 4,
            },
        )
        self.assertEqual(
            tuple(
                CALIBRATION.derive_master_seeds(
                    qualification["root"], qualification["count"]
                )
            ),
            QUALIFICATION_SEEDS,
        )
        self.assertEqual(
            tuple(
                CALIBRATION.derive_master_seeds(evidence["root"], evidence["count"])
            ),
            EVIDENCE_SEEDS,
        )
        seed_sets = (
            set(CALIBRATION_SEEDS),
            set(QUALIFICATION_SEEDS),
            set(EVIDENCE_SEEDS),
        )
        self.assertTrue(
            all(
                left.isdisjoint(right)
                for index, left in enumerate(seed_sets)
                for right in seed_sets[index + 1 :]
            )
        )

        acceptance = config["acceptance"]
        self.assertEqual(
            acceptance,
            {
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
            },
        )
        self.assertNotIn("model", json.dumps(config["acceptance"]).lower())

    def test_config_validation_rejects_changes_to_the_frozen_design(self) -> None:
        original = json.loads(CALIBRATION_CONFIG.read_text(encoding="utf-8"))
        mutations = (
            (
                "arm",
                lambda value: value.__setitem__(
                    "calibration_arm", "typed_point_v1"
                ),
            ),
            ("steps", lambda value: value.__setitem__("steps", 63)),
            (
                "grid",
                lambda value: value.__setitem__(
                    "candidate_max_organisms",
                    [112, 120, 128, 144, 176, 160],
                ),
            ),
            (
                "overlap",
                lambda value: value["evidence_seed_reservation"].update(
                    value["qualification_seed_reservation"]
                ),
            ),
            (
                "blocked-birth-criterion",
                lambda value: value["acceptance"].pop(
                    "capacity_blocked_births_total_max"
                ),
            ),
            (
                "design-timing",
                lambda value: value["design_timing"].__setitem__(
                    "preregistered", True
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, mutate in mutations:
                with self.subTest(name=name):
                    payload = json.loads(json.dumps(original))
                    mutate(payload)
                    path = root / f"{name}.json"
                    path.write_text(
                        CALIBRATION.canonical_json(payload) + "\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    with self.assertRaises(ValueError):
                        CALIBRATION.read_config(path)

    @staticmethod
    def synthetic_trajectory(*, blocked_births: int = 0) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for step in range(64):
            rows.append(
                {
                    "step": step,
                    "n_alive": 80,
                    "n_producers": 40,
                    "n_recyclers": 40,
                    "nutrient": 200,
                    "waste": 200,
                    "stored": 400,
                    "niche_index": 0.5,
                    "construct_match": 0.5,
                    "condition_var": 0.0,
                    "condition_mean": 0.0,
                    "births": 1,
                    "deaths": 0,
                    "capacity_blocked_births": (
                        blocked_births if step == 0 else 0
                    ),
                    "capacity_gate_occupancy_peak": 80,
                    "conservation_ok": True,
                    "nonnegative_ok": True,
                }
            )
        return rows

    @classmethod
    def synthetic_rows(
        cls,
        config: dict[str, object],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        caps = [
            *config["candidate_max_organisms"],
            config["sentinel_max_organisms"],
        ]
        for cap in caps:
            for seed in config["calibration_seeds"]:
                trajectory = cls.synthetic_trajectory()
                rows.append(
                    {
                        "schema": 1,
                        "calibration_id": config["calibration_id"],
                        "run_kind": (
                            "sentinel" if cap == SENTINEL else "candidate"
                        ),
                        "arm_id": "inherit_only",
                        "master_seed": seed,
                        "max_organisms": cap,
                        "seed_plan": VARIATION.IVSeedPlan.from_master(
                            seed
                        ).to_dict(),
                        "initial_physical_sha256": f"sha256:{seed:064x}",
                        "initial_programs_sha256": "sha256:" + "1" * 64,
                        "final_physical_sha256": f"sha256:{seed + 1:064x}",
                        "final_programs_sha256": "sha256:" + "2" * 64,
                        "final_rng_states_sha256": "sha256:" + "3" * 64,
                        "ecology_trajectory_sha256": (
                            CALIBRATION.canonical_sha(trajectory)
                        ),
                        "metrics": CALIBRATION.trajectory_metrics(
                            trajectory, cap
                        ),
                        "ecology_trajectory": trajectory,
                    }
                )
        return rows

    @staticmethod
    def selected_cap(decision: object) -> int:
        if isinstance(decision, int):
            return decision
        assert isinstance(decision, dict)
        for key in ("selected_max_organisms", "selected_candidate"):
            if key in decision:
                return int(decision[key])
        raise AssertionError(f"selection result has no selected cap: {decision!r}")

    @staticmethod
    def refresh_row(row: dict[str, object]) -> None:
        trajectory = row["ecology_trajectory"]
        cap = row["max_organisms"]
        assert isinstance(trajectory, list)
        assert isinstance(cap, int)
        row["metrics"] = CALIBRATION.trajectory_metrics(trajectory, cap)
        row["ecology_trajectory_sha256"] = CALIBRATION.canonical_sha(
            trajectory
        )

    def test_selection_recomputes_criteria_and_chooses_smallest_passing_cap(
        self,
    ) -> None:
        config = CALIBRATION.read_config(CALIBRATION_CONFIG)
        rows = self.synthetic_rows(config)

        self.assertEqual(
            self.selected_cap(CALIBRATION.select_candidate(config, rows)),
            112,
        )

        # A zero post-step ceiling fraction does not prove that the ceiling was
        # non-binding: births can be blocked before mortality lowers n_alive.
        for row in rows:
            if row["max_organisms"] != SENTINEL and row["max_organisms"] < 176:
                row["ecology_trajectory"][0]["capacity_blocked_births"] = 1
                self.refresh_row(row)
        self.assertEqual(
            self.selected_cap(CALIBRATION.select_candidate(config, rows)),
            176,
        )

        rows = self.synthetic_rows(config)
        for row in rows:
            cap = row["max_organisms"]
            if cap != SENTINEL and cap < 176:
                row["ecology_trajectory"][0][
                    "capacity_gate_occupancy_peak"
                ] = int(0.85 * cap) + 1
                self.refresh_row(row)
        self.assertEqual(
            self.selected_cap(CALIBRATION.select_candidate(config, rows)),
            176,
        )

    def test_selection_rejects_incomplete_duplicate_and_unexpected_rows(self) -> None:
        config = CALIBRATION.read_config(CALIBRATION_CONFIG)
        rows = self.synthetic_rows(config)
        fractional_event = copy.deepcopy(rows)
        fractional_event[0]["ecology_trajectory"][0]["births"] = 1.9
        fractional_event[0]["ecology_trajectory_sha256"] = (
            CALIBRATION.canonical_sha(
                fractional_event[0]["ecology_trajectory"]
            )
        )
        malformed_digest = copy.deepcopy(rows)
        malformed_digest[0]["final_rng_states_sha256"] = "not-a-digest"

        cases = {
            "missing": rows[:-1],
            "duplicate": [*rows, dict(rows[0])],
            "unexpected-cap": [
                {**row, "max_organisms": 999} if index == 0 else row
                for index, row in enumerate(rows)
            ],
            "wrong-arm": [
                {**row, "arm_id": "typed_point_v1"} if index == 0 else row
                for index, row in enumerate(rows)
            ],
            "tampered-metrics": [
                {
                    **row,
                    "metrics": {**row["metrics"], "max_alive_fraction": 0.0},
                }
                if index == 0
                else row
                for index, row in enumerate(rows)
            ],
            "tampered-trajectory-hash": [
                {**row, "ecology_trajectory_sha256": "sha256:" + "0" * 64}
                if index == 0
                else row
                for index, row in enumerate(rows)
            ],
            "fractional-event-count": fractional_event,
            "malformed-digest": malformed_digest,
        }
        for name, sample in cases.items():
            with self.subTest(name=name), self.assertRaises(
                (ValueError, RuntimeError)
            ):
                CALIBRATION.select_candidate(config, sample)

    def test_selection_fails_closed_when_no_candidate_passes(self) -> None:
        config = CALIBRATION.read_config(CALIBRATION_CONFIG)
        rows = self.synthetic_rows(config)
        for row in rows:
            if row["max_organisms"] != SENTINEL:
                row["ecology_trajectory"][0]["capacity_blocked_births"] = 1
                self.refresh_row(row)
        with self.assertRaisesRegex(RuntimeError, "no .*candidate|no candidate"):
            CALIBRATION.select_candidate(config, rows)

        indexed = {
            (row["master_seed"], row["max_organisms"]): row for row in rows
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist"

            def invalid_run(source, *, seed: int, cap: int):
                del source
                return indexed[(seed, cap)]

            with mock.patch.object(
                CALIBRATION,
                "_run_row",
                side_effect=invalid_run,
            ), self.assertRaisesRegex(RuntimeError, "no .*candidate|no candidate"):
                CALIBRATION.run_calibration(CALIBRATION_CONFIG, output)
            self.assertFalse(output.exists())

    def test_reference_generation_fails_before_simulation_on_dirty_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist"
            with mock.patch.object(
                CALIBRATION,
                "source_commit",
                return_value="a" * 40,
            ), mock.patch.object(
                CALIBRATION,
                "source_files_match_commit",
                return_value=False,
            ), mock.patch.object(
                CALIBRATION,
                "_run_row",
            ) as run_row, self.assertRaisesRegex(
                RuntimeError,
                "reference generation requires",
            ):
                CALIBRATION.run_calibration(
                    CALIBRATION_CONFIG,
                    output,
                    require_committed_source=True,
                )
            run_row.assert_not_called()
            self.assertFalse(output.exists())

    def test_reference_generation_rejects_an_external_config_before_simulation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "byte-identical-but-external.json"
            external.write_bytes(CALIBRATION_CONFIG.read_bytes())
            output = root / "must-not-exist"
            with mock.patch.object(
                CALIBRATION,
                "source_commit",
            ) as source_commit, mock.patch.object(
                CALIBRATION,
                "_run_row",
            ) as run_row, self.assertRaisesRegex(
                RuntimeError,
                "requires --config to resolve",
            ):
                CALIBRATION.run_calibration(
                    external,
                    output,
                    require_committed_source=True,
                )
            source_commit.assert_not_called()
            run_row.assert_not_called()
            self.assertFalse(output.exists())

    def test_frozen_world_rejects_each_tampered_input_digest(self) -> None:
        config = CALIBRATION.read_config(CALIBRATION_CONFIG)
        rows = self.synthetic_rows(config)
        indexed = {
            (row["master_seed"], row["max_organisms"]): row
            for row in rows
        }

        def synthetic_run(source, *, seed: int, cap: int):
            del source
            return indexed[(seed, cap)]

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            CALIBRATION,
            "_run_row",
            side_effect=synthetic_run,
        ):
            output = Path(directory) / "calibration"
            CALIBRATION.run_calibration(CALIBRATION_CONFIG, output)
            frozen = json.loads(
                (output / "frozen-world.json").read_text(encoding="utf-8")
            )
            decision_bytes = (output / "calibration-decision.json").read_bytes()
            decision = json.loads(decision_bytes)
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(decision["design_timing"], config["design_timing"])
            self.assertEqual(frozen["design_timing"], config["design_timing"])
            self.assertEqual(
                manifest["protocol"]["design_timing"],
                config["design_timing"],
            )

            validation_inputs = {
                "calibration_config_bytes": CALIBRATION_CONFIG.read_bytes(),
                "source_config_bytes": PILOT_CONFIG.read_bytes(),
                "decision": decision,
                "calibration_decision_bytes": decision_bytes,
            }
            CALIBRATION.validate_frozen_world(
                config,
                frozen,
                **validation_inputs,
            )
            for key in (
                "calibration_config_sha256",
                "source_config_sha256",
                "calibration_decision_sha256",
            ):
                with self.subTest(binding=key), self.assertRaises(ValueError):
                    tampered = copy.deepcopy(frozen)
                    tampered["bindings"][key] = "sha256:" + "0" * 64
                    CALIBRATION.validate_frozen_world(
                        config,
                        tampered,
                        **validation_inputs,
                    )
            for key in (
                "calibration_config_bytes",
                "source_config_bytes",
                "calibration_decision_bytes",
            ):
                with self.subTest(input_bytes=key), self.assertRaises(
                    ValueError
                ):
                    tampered_inputs = dict(validation_inputs)
                    tampered_inputs[key] += b" "
                    CALIBRATION.validate_frozen_world(
                        config,
                        frozen,
                        **tampered_inputs,
                    )

    def test_reference_bundle_is_canonical_complete_and_hash_bound(self) -> None:
        config = CALIBRATION.read_config(CALIBRATION_CONFIG)
        expected_files = set(CALIBRATION.BUNDLE_FILES) | {"checksums.json"}
        self.assertEqual({path.name for path in REFERENCE.iterdir()}, expected_files)

        runs = read_jsonl(REFERENCE / "calibration-runs.jsonl")
        decision_bytes = (
            REFERENCE / "calibration-decision.json"
        ).read_bytes()
        decision = json.loads(decision_bytes)
        frozen = json.loads(
            (REFERENCE / "frozen-world.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (REFERENCE / "manifest.json").read_text(encoding="utf-8")
        )
        checksums = json.loads(
            (REFERENCE / "checksums.json").read_text(encoding="utf-8")
        )

        expected_order = [
            (cap, seed)
            for cap in (*CANDIDATES, SENTINEL)
            for seed in CALIBRATION_SEEDS
        ]
        self.assertEqual(
            [(row["max_organisms"], row["master_seed"]) for row in runs],
            expected_order,
        )
        self.assertTrue(all(row["arm_id"] == "inherit_only" for row in runs))
        self.assertTrue(
            {row["master_seed"] for row in runs}.isdisjoint(EVIDENCE_SEEDS)
        )
        self.assertEqual(set(runs[0]), CALIBRATION.RUN_KEYS)

        recomputed = CALIBRATION.select_candidate(config, runs)
        self.assertEqual(decision, recomputed)
        self.assertEqual(decision["selected_max_organisms"], 176)
        self.assertEqual(decision["design_timing"], config["design_timing"])
        self.assertEqual(
            decision["protocol_checks"]["trajectory_scope"],
            "projected_step_aggregate_summary_not_full_microstate",
        )
        self.assertTrue(
            decision["protocol_checks"][
                "projected_ecology_summary_compared_to_sentinel"
            ]
        )
        self.assertNotIn(
            "raw_trajectory_compared_to_sentinel",
            decision["protocol_checks"],
        )
        by_cap = {
            row["max_organisms"]: row
            for row in decision["candidate_evaluations"]
        }
        self.assertFalse(by_cap[160]["eligible"])
        self.assertTrue(by_cap[176]["eligible"])
        seed_24001 = next(
            row
            for row in by_cap[160]["seed_evaluations"]
            if row["master_seed"] == 24001
        )
        self.assertFalse(
            seed_24001["checks"]["capacity_gate_occupancy_fraction"]
        )
        self.assertEqual(
            seed_24001["metrics"]["capacity_gate_occupancy_peak"],
            138,
        )
        self.assertEqual(
            seed_24001["metrics"]["capacity_gate_occupancy_fraction"],
            0.8625,
        )
        self.assertTrue(
            seed_24001["checks"]["capacity_blocked_births_total"]
        )
        self.assertTrue(
            seed_24001["checks"]["projected_trajectory_matches_sentinel"]
        )

        pilot = json.loads(PILOT_CONFIG.read_text(encoding="utf-8"))
        simulator_source = VARIATION.read_config(PILOT_CONFIG)
        stored_runs = {
            (row["max_organisms"], row["master_seed"]): row
            for row in runs
        }
        # Re-run the complete matrix so both the selection and the rejection
        # rationale rest on fresh simulator output, not self-consistency of
        # stored rows alone.
        for cap in (*CANDIDATES, SENTINEL):
            for seed in CALIBRATION_SEEDS:
                with self.subTest(fresh_trajectory=(cap, seed)):
                    fresh = CALIBRATION._run_row(
                        simulator_source,
                        seed=seed,
                        cap=cap,
                    )
                    stored = stored_runs[(cap, seed)]
                    self.assertEqual(
                        fresh["ecology_trajectory_sha256"],
                        stored["ecology_trajectory_sha256"],
                    )
                    self.assertEqual(
                        fresh["ecology_trajectory"],
                        stored["ecology_trajectory"],
                    )
        expected_physics = dict(pilot["physics"])
        expected_physics["max_organisms"] = 176
        self.assertEqual(frozen["selected_max_organisms"], 176)
        self.assertEqual(frozen["design_timing"], config["design_timing"])
        self.assertEqual(frozen["physics"], expected_physics)
        expected_budget_policy = {
            "trigger": "birth_event",
            "per_replicate_upper_cap": 8,
            "terminal_shortfall": "preserved_as_outcome",
            "authentic_evidence_requires_full_budget": False,
        }
        self.assertEqual(
            frozen["proposal_budget_policy"],
            expected_budget_policy,
        )
        self.assertNotIn("require_full_budget", frozen)
        self.assertEqual(frozen["initial_programs"], pilot["initial_programs"])
        self.assertEqual(
            tuple(frozen["qualification_seeds"]["master_seeds"]),
            QUALIFICATION_SEEDS,
        )
        self.assertEqual(
            tuple(frozen["evidence_seeds"]["master_seeds"]),
            EVIDENCE_SEEDS,
        )
        validation_inputs = {
            "calibration_config_bytes": CALIBRATION_CONFIG.read_bytes(),
            "source_config_bytes": PILOT_CONFIG.read_bytes(),
            "decision": decision,
            "calibration_decision_bytes": decision_bytes,
        }
        CALIBRATION.validate_frozen_world(
            config,
            frozen,
            **validation_inputs,
        )
        reservation_names = {
            "qualification": "qualification_seeds",
            "evidence": "evidence_seeds",
        }
        for config_name, frozen_name in reservation_names.items():
            specification = config[f"{config_name}_seed_reservation"]
            reservation = frozen[frozen_name]
            self.assertEqual(
                set(reservation),
                CALIBRATION.RESERVATION_RECORD_KEYS,
            )
            self.assertEqual(
                {
                    key: reservation[key]
                    for key in (
                        "derivation",
                        "derivation_version",
                        "root",
                        "count",
                    )
                },
                specification,
            )
            expected_seeds = list(
                CALIBRATION.derive_master_seeds(
                    specification["root"],
                    specification["count"],
                )
            )
            self.assertEqual(reservation["master_seeds"], expected_seeds)
            self.assertEqual(
                reservation["master_seeds_sha256"],
                CALIBRATION.canonical_sha(expected_seeds),
            )
            expected_plans = [
                VARIATION.IVSeedPlan.from_master(seed).to_dict()
                for seed in expected_seeds
            ]
            self.assertEqual(reservation["seed_plans"], expected_plans)
            self.assertEqual(
                reservation["seed_plans_sha256"],
                CALIBRATION.canonical_sha(expected_plans),
            )

        tampered_worlds = {}
        for name in (
            "master-seed-hash",
            "seed-plan",
            "seed-plan-hash",
        ):
            tampered_worlds[name] = copy.deepcopy(frozen)
        tampered_worlds["master-seed-hash"]["qualification_seeds"][
            "master_seeds_sha256"
        ] = "sha256:" + "0" * 64
        tampered_worlds["seed-plan"]["evidence_seeds"]["seed_plans"][0][
            "streams"
        ]["operator"] += 1
        tampered_worlds["seed-plan-hash"]["evidence_seeds"][
            "seed_plans_sha256"
        ] = "sha256:" + "0" * 64
        for name, tampered in tampered_worlds.items():
            with self.subTest(tamper=name), self.assertRaises(ValueError):
                CALIBRATION.validate_frozen_world(
                    config,
                    tampered,
                    **validation_inputs,
                )

        bindings = frozen["bindings"]
        self.assertEqual(
            bindings["calibration_config_sha256"],
            sha256_bytes(CALIBRATION_CONFIG.read_bytes()),
        )
        self.assertEqual(
            bindings["source_config_sha256"],
            sha256_bytes(PILOT_CONFIG.read_bytes()),
        )
        self.assertEqual(
            bindings["calibration_decision_sha256"],
            sha256_bytes(decision_bytes),
        )
        self.assertEqual(
            bindings["physics_sha256"],
            CALIBRATION.canonical_sha(expected_physics),
        )
        self.assertEqual(
            bindings["initial_programs_sha256"],
            CALIBRATION.canonical_sha(pilot["initial_programs"]),
        )
        self.assertEqual(
            bindings["proposal_budget_policy_sha256"],
            CALIBRATION.canonical_sha(expected_budget_policy),
        )
        self.assertEqual(
            manifest["inputs"]["calibration_config_path"],
            CALIBRATION_CONFIG.relative_to(ROOT).as_posix(),
        )
        self.assertEqual(
            manifest["inputs"]["calibration_config_sha256"],
            sha256_bytes(CALIBRATION_CONFIG.read_bytes()),
        )
        self.assertEqual(
            manifest["inputs"]["source_config_path"],
            PILOT_CONFIG.relative_to(ROOT).as_posix(),
        )
        self.assertEqual(
            manifest["inputs"]["source_config_sha256"],
            sha256_bytes(PILOT_CONFIG.read_bytes()),
        )

        self.assertRegex(manifest["source_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(manifest["source_commit"], CALIBRATION.source_commit())
        self.assertEqual(
            manifest["source_commit_scope"],
            "latest commit touching any source_files_sha256 path",
        )
        self.assertIs(manifest["source_files_match_commit"], True)
        self.assertTrue(
            CALIBRATION.source_files_match_commit(manifest["source_commit"])
        )
        self.assertEqual(
            set(manifest["source_files_sha256"]),
            set(CALIBRATION.SOURCE_FILES),
        )
        for name, expected in manifest["source_files_sha256"].items():
            self.assertEqual(
                expected,
                sha256_bytes((ROOT / name).read_bytes()),
                name,
            )
        self.assertEqual(
            manifest["protocol"]["varied_physics_fields"],
            ["max_organisms"],
        )
        self.assertEqual(
            manifest["protocol"]["design_timing"],
            config["design_timing"],
        )
        self.assertEqual(
            manifest["protocol"]["trajectory_scope"],
            "projected_step_aggregate_summary_not_full_microstate",
        )
        self.assertTrue(manifest["protocol"]["no_model_calls"])
        self.assertEqual(
            manifest["protocol"]["proposal_budget_policy"],
            expected_budget_policy,
        )
        self.assertEqual(
            manifest["reserved_seeds"],
            {
                "qualification": frozen["qualification_seeds"],
                "evidence": frozen["evidence_seeds"],
            },
        )
        self.assertEqual(
            tuple(manifest["reserved_seeds"]["evidence"]["master_seeds"]),
            EVIDENCE_SEEDS,
        )
        for name in CALIBRATION.BUNDLE_FILES:
            payload = (REFERENCE / name).read_bytes()
            self.assertEqual(checksums["files"][name], sha256_bytes(payload))
            if name != "manifest.json":
                self.assertEqual(
                    manifest["artifacts_sha256"][name],
                    sha256_bytes(payload),
                )

        self.assertEqual(
            (REFERENCE / "calibration-runs.jsonl").read_bytes(),
            CALIBRATION.jsonl_bytes(runs),
        )
        for name, value in (
            ("calibration-decision.json", decision),
            ("frozen-world.json", frozen),
            ("manifest.json", manifest),
            ("checksums.json", checksums),
        ):
            self.assertEqual(
                (REFERENCE / name).read_text(encoding="utf-8"),
                CALIBRATION.canonical_json(value) + "\n",
            )

    def test_qualification_replays_all_arms_without_capacity_censoring(self) -> None:
        config = VARIATION.read_config(QUALIFICATION_CONFIG)
        calibration = CALIBRATION.read_config(CALIBRATION_CONFIG)
        self.assertEqual(tuple(config["seeds"]), QUALIFICATION_SEEDS)
        self.assertEqual(config["proposal_budget"], 8)
        self.assertEqual(config["physics"]["steps"], 64)
        self.assertEqual(config["physics"]["max_organisms"], 176)
        self.assertTrue(set(config["seeds"]).isdisjoint(EVIDENCE_SEEDS))

        pilot = json.loads(PILOT_CONFIG.read_text(encoding="utf-8"))
        for key, value in pilot["physics"].items():
            if key != "max_organisms":
                self.assertEqual(config["physics"][key], value, key)
        self.assertEqual(config["initial_programs"], pilot["initial_programs"])
        self.assertEqual(calibration["steps"], config["physics"]["steps"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "qualification-fixture.jsonl"
            output = root / "qualification"
            VARIATION.build_fixture_cache(config, cache)
            VARIATION.run_experiment(QUALIFICATION_CONFIG, cache, output)

            runs = read_jsonl(output / "runs.jsonl")
            trajectories = read_jsonl(output / "trajectories.jsonl")
            self.assertEqual(
                len(runs),
                len(QUALIFICATION_SEEDS) * len(VARIATION.ARM_IDS),
            )
            run_seeds = {row["master_seed"] for row in runs}
            self.assertEqual(run_seeds, set(QUALIFICATION_SEEDS))
            self.assertTrue(run_seeds.isdisjoint(EVIDENCE_SEEDS))
            for run in runs:
                expected_budget = 0 if run["arm_id"] == "inherit_only" else 8
                self.assertEqual(run["proposal_budget_used"], expected_budget)
                self.assertEqual(run["capacity_blocked_births_total"], 0)

            for seed in QUALIFICATION_SEEDS:

                def trace(arm_id: str) -> list[dict[str, object]]:
                    return [
                        {
                            key: value
                            for key, value in row.items()
                            if key not in {"run_id", "arm_id"}
                        }
                        for row in trajectories
                        if row["replicate_id"] == f"seed-{seed}"
                        and row["arm_id"] == arm_id
                    ]

                self.assertEqual(
                    trace("random_atomic_edit_v1"),
                    trace("cached_proposal_fixture_v1"),
                )


if __name__ == "__main__":
    unittest.main()
