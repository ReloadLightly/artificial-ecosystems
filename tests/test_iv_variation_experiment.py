"""End-to-end artifact contracts for the matched IV variation pilot."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location(
    "run_iv_variation",
    ROOT / "experiments" / "run_iv_variation.py",
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)

from evolve_modern.iv_variation import CacheIntegrityError


CONFIG = ROOT / "experiments" / "configs" / "iv-variation-pilot-v1.json"
QUALIFICATION_CONFIG = (
    ROOT / "experiments" / "configs" / "iv-variation-qualification-v1.json"
)
FROZEN_WORLD = (
    ROOT / "results" / "reference" / "iv-world-calibration-v1"
    / "frozen-world.json"
)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class IVVariationExperimentTests(unittest.TestCase):
    def tiny_config(self, directory: Path) -> Path:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        payload["seeds"] = [17, 19]
        payload["proposal_budget"] = 2
        payload["physics"].update(
            {
                "n_places": 8,
                "total_units": 160,
                "n_organisms": 6,
                "max_organisms": 20,
                "steps": 12,
                "condition_decay": 0.0,
            }
        )
        path = directory / "tiny-config.json"
        path.write_text(
            RUNNER.canonical_json(payload) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path

    def test_committed_config_freezes_all_five_honestly_named_arms(self) -> None:
        config = RUNNER.read_config(CONFIG)

        self.assertEqual(tuple(config["arms"]), RUNNER.ARM_IDS)
        self.assertEqual(len(config["seeds"]), 4)
        self.assertTrue(config["require_full_budget"])
        self.assertEqual(
            config["claim_status"],
            "exploratory_integration_replay_pilot",
        )
        self.assertIn("typed_homologous_recombination_v1", config["arms"])
        self.assertNotIn("gp", " ".join(config["arms"]))
        self.assertIn("fixture", config["arms"][-1])

    def test_descriptive_run_metric_definitions_and_empty_guard(self) -> None:
        trajectory = [
            {
                "step": 0,
                "n_alive": 4,
                "n_producers": 2,
                "n_recyclers": 2,
                "stored": 13,
                "births": 1,
                "deaths": 0,
                "capacity_blocked_births": 2,
                "capacity_gate_occupancy_peak": 5,
            },
            {
                "step": 1,
                "n_alive": 5,
                "n_producers": 3,
                "n_recyclers": 2,
                "stored": 17,
                "births": 2,
                "deaths": 1,
                "capacity_blocked_births": 0,
                "capacity_gate_occupancy_peak": 5,
            },
            {
                "step": 2,
                "n_alive": 0,
                "n_producers": 0,
                "n_recyclers": 0,
                "stored": 0,
                "births": 0,
                "deaths": 5,
                "capacity_blocked_births": 1,
                "capacity_gate_occupancy_peak": 5,
            },
        ]

        metrics = RUNNER._descriptive_run_metrics(
            trajectory,
            max_organisms=5,
        )

        self.assertAlmostEqual(
            metrics["population_occupancy_auc_normalized"],
            9 / 15,
        )
        self.assertAlmostEqual(metrics["population_ceiling_fraction"], 1 / 3)
        self.assertAlmostEqual(metrics["role_coexistence_fraction"], 2 / 3)
        self.assertEqual(metrics["extinction_step"], 2)
        self.assertEqual(metrics["final_living_body_stored_matter"], 0)
        self.assertEqual(metrics["turnover_total"], 9)
        self.assertEqual(metrics["capacity_blocked_births_total"], 3)
        self.assertEqual(metrics["capacity_gate_occupancy_peak"], 5)
        self.assertEqual(metrics["capacity_gate_occupancy_fraction"], 1.0)
        self.assertIsNone(
            RUNNER._descriptive_run_metrics(
                trajectory[:2],
                max_organisms=5,
            )["extinction_step"]
        )
        with self.assertRaisesRegex(ValueError, "at least one post-step"):
            RUNNER._descriptive_run_metrics([], max_organisms=5)

    def test_config_rejects_duplicate_members_and_nonfinite_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema":1,"schema":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate config key: schema"):
                RUNNER.read_config(duplicate)

            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"schema":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite config number: NaN"):
                RUNNER.read_config(nonfinite)

            overflow = root / "overflow.json"
            overflow.write_text('{"schema":1e999}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite config number: 1e999"):
                RUNNER.read_config(overflow)

    def test_direct_diagnostic_catches_capacity_hidden_by_mortality(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["physics"]["max_organisms"] = 120
        run, trajectory, _events = RUNNER.run_arm(
            config,
            seed=101,
            arm_id="inherit_only",
            operator=None,
        )

        self.assertEqual(run["population_ceiling_fraction"], 0.0)
        self.assertLess(max(row["n_alive"] for row in trajectory), 120)
        self.assertGreater(run["capacity_blocked_births_total"], 0)
        self.assertEqual(
            run["capacity_gate_occupancy_peak"],
            max(row["capacity_gate_occupancy_peak"] for row in trajectory),
        )

    def test_opportunity_subject_matching_is_descriptive_not_assumed(self) -> None:
        events: list[dict[str, object]] = []
        variation_arms = RUNNER.ARM_IDS[1:]
        for opportunity_id in (0, 1):
            for arm_id in variation_arms:
                events.append(
                    {
                        "arm_id": arm_id,
                        "mutation_attempted": True,
                        "opportunity_id": opportunity_id,
                        "replicate_id": "seed-17",
                        "birth_step": opportunity_id,
                        "parent_bug_id": (
                            99
                            if opportunity_id == 1
                            and arm_id == "typed_point_v1"
                            else 1
                        ),
                        "bug_id": opportunity_id + 2,
                        "parent_program": "parent",
                    }
                )
        for arm_id in variation_arms[:-1]:
            events.append(
                {
                    "arm_id": arm_id,
                    "mutation_attempted": True,
                    "opportunity_id": 2,
                    "replicate_id": "seed-17",
                    "birth_step": 2,
                    "parent_bug_id": 7,
                    "bug_id": 8,
                    "parent_program": "parent",
                }
            )

        report = RUNNER._opportunity_subject_matching(events)

        self.assertFalse(
            report["post_divergence_subject_identity_matched_by_design"]
        )
        self.assertEqual(report["ordinal_slots_observed"], 3)
        self.assertEqual(report["slots_with_all_variation_arms"], 2)
        self.assertEqual(report["subject_identity_matched_slots"], 1)
        self.assertEqual(
            report["subject_identity_diverged_slots"],
            [{"replicate_id": "seed-17", "opportunity_id": 1}],
        )
        self.assertEqual(
            report["incomplete_slots"],
            [
                {
                    "replicate_id": "seed-17",
                    "opportunity_id": 2,
                    "observed_arms": sorted(variation_arms[:-1]),
                    "missing_arms": [variation_arms[-1]],
                    "duplicate_arms": [],
                }
            ],
        )

    def test_fixture_replay_is_byte_deterministic_and_self_checking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self.tiny_config(root)
            config = RUNNER.read_config(config_path)
            cache_path = root / "fixture.jsonl"
            cache_copy = root / "fixture-copy.jsonl"
            config_copy = root / "same-config-different-name.json"
            config_copy.write_bytes(config_path.read_bytes())

            first_count = RUNNER.build_fixture_cache(config, cache_path)
            second_count = RUNNER.build_fixture_cache(config, cache_copy)
            self.assertEqual((first_count, second_count), (4, 4))
            self.assertEqual(cache_path.read_bytes(), cache_copy.read_bytes())

            first = root / "first"
            second = root / "second"
            RUNNER.run_experiment(config_path, cache_path, first)
            RUNNER.run_experiment(config_copy, cache_copy, second)

            expected_files = set(RUNNER.BUNDLE_FILES) | {"checksums.json"}
            self.assertEqual({path.name for path in first.iterdir()}, expected_files)
            for name in expected_files:
                self.assertEqual(
                    (first / name).read_bytes(),
                    (second / name).read_bytes(),
                    name,
                )

            checksums = json.loads((first / "checksums.json").read_text())
            self.assertTrue(checksums["self_excluded"])
            for name, expected in checksums["files"].items():
                actual = "sha256:" + hashlib.sha256((first / name).read_bytes()).hexdigest()
                self.assertEqual(actual, expected, name)

            cache = read_jsonl(cache_path)
            self.assertTrue(cache)
            self.assertTrue(all(row["provenance"] == "fixture" for row in cache))
            self.assertTrue(
                all(row["request"]["model"]["provider"] == "fixture" for row in cache)
            )
            self.assertTrue(
                all(row["response"]["usage"] == {"input_tokens": 0, "output_tokens": 0} for row in cache)
            )

            runs = read_jsonl(first / "runs.jsonl")
            trajectories = read_jsonl(first / "trajectories.jsonl")
            events = read_jsonl(first / "events.jsonl")
            summary = json.loads((first / "summary.json").read_text())
            manifest = json.loads((first / "manifest.json").read_text())
            self.assertEqual(manifest["schema"], 2)
            self.assertEqual(summary["schema"], 2)
            self.assertTrue(all(row["schema"] == 2 for row in runs))
            self.assertTrue(all(row["schema"] == 2 for row in trajectories))
            self.assertTrue(all(row["schema"] == 1 for row in events))
            self.assertEqual(
                manifest["record_schemas"],
                {
                    "runs.jsonl": 2,
                    "trajectories.jsonl": 2,
                    "events.jsonl": 1,
                    "summary.json": 2,
                },
            )
            self.assertEqual(manifest["source_commit"], RUNNER.source_commit())
            self.assertEqual(
                manifest["source_commit_scope"],
                "latest commit touching a path in source_files_sha256",
            )
            self.assertEqual(
                set(manifest["source_files_sha256"]),
                set(RUNNER.SOURCE_FILES),
            )
            for name, expected in manifest["source_files_sha256"].items():
                actual = "sha256:" + hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                self.assertEqual(actual, expected, name)
            self.assertEqual(
                {row["arm_id"] for row in runs},
                set(RUNNER.ARM_IDS),
            )
            self.assertIsNone(
                manifest["inputs"]["frozen_world_binding"]
            )
            self.assertEqual(
                manifest["matching"]["proposal_budget_semantics"],
                "birth_triggered_upper_cap",
            )
            self.assertTrue(
                manifest["matching"][
                    "at_most_one_candidate_validation_per_budgeted_birth"
                ]
            )
            self.assertTrue(
                manifest["matching"][
                    "realized_counts_may_differ_after_trajectory_divergence"
                ]
            )
            self.assertTrue(
                manifest["matching"][
                    "opportunity_subjects_not_matched_after_divergence"
                ]
            )
            self.assertEqual(len(runs), 2 * len(RUNNER.ARM_IDS))
            for replicate_id in {row["replicate_id"] for row in runs}:
                initial = {
                    (
                        row["initial_physical_sha256"],
                        row["initial_programs_sha256"],
                    )
                    for row in runs
                    if row["replicate_id"] == replicate_id
                }
                self.assertEqual(len(initial), 1)

                random_run_id = (
                    f"{replicate_id}--random_atomic_edit_v1"
                )
                cached_run_id = (
                    f"{replicate_id}--cached_proposal_fixture_v1"
                )
                random_trace = [
                    {k: v for k, v in row.items() if k not in {"run_id", "arm_id"}}
                    for row in trajectories
                    if row["run_id"] == random_run_id
                ]
                cached_trace = [
                    {k: v for k, v in row.items() if k not in {"run_id", "arm_id"}}
                    for row in trajectories
                    if row["run_id"] == cached_run_id
                ]
                self.assertEqual(random_trace, cached_trace)

            events_by_run: dict[str, list[dict[str, object]]] = {}
            for event in events:
                events_by_run.setdefault(str(event["run_id"]), []).append(event)
            trajectories_by_run: dict[str, list[dict[str, object]]] = {}
            for row in trajectories:
                trajectories_by_run.setdefault(str(row["run_id"]), []).append(row)
            for run in runs:
                attempted = [
                    event
                    for event in events_by_run[str(run["run_id"])]
                    if event["mutation_attempted"]
                ]
                self.assertEqual(
                    sum(event["proposal_budget_cost"] for event in attempted),
                    run["proposal_budget_used"],
                )
                expected = 0 if run["arm_id"] == "inherit_only" else 2
                self.assertEqual(run["proposal_budget_used"], expected)
                expected_cap = 0 if run["arm_id"] == "inherit_only" else 2
                self.assertEqual(run["proposal_budget_cap"], expected_cap)
                self.assertEqual(
                    run["proposal_budget_shortfall"],
                    run["proposal_budget_cap"]
                    - run["proposal_budget_used"],
                )

                run_trajectory = trajectories_by_run[str(run["run_id"])]
                duration = len(run_trajectory)
                max_organisms = 20
                self.assertGreater(duration, 0)
                self.assertAlmostEqual(
                    run["population_occupancy_auc_normalized"],
                    sum(row["n_alive"] for row in run_trajectory)
                    / (duration * max_organisms),
                )
                self.assertAlmostEqual(
                    run["population_ceiling_fraction"],
                    sum(
                        row["n_alive"] == max_organisms
                        for row in run_trajectory
                    )
                    / duration,
                )
                self.assertAlmostEqual(
                    run["role_coexistence_fraction"],
                    sum(
                        row["n_producers"] > 0 and row["n_recyclers"] > 0
                        for row in run_trajectory
                    )
                    / duration,
                )
                for key in (
                    "population_occupancy_auc_normalized",
                    "population_ceiling_fraction",
                    "role_coexistence_fraction",
                ):
                    self.assertGreaterEqual(run[key], 0.0)
                    self.assertLessEqual(run[key], 1.0)
                extinct = next(
                    (
                        row["step"]
                        for row in run_trajectory
                        if row["n_alive"] == 0
                    ),
                    None,
                )
                self.assertEqual(run["extinction_step"], extinct)
                self.assertEqual(
                    run["final_living_body_stored_matter"],
                    run_trajectory[-1]["stored"],
                )
                self.assertEqual(
                    run["turnover_total"],
                    run["births_total"] + run["deaths_total"],
                )
                self.assertEqual(
                    run["capacity_blocked_births_total"],
                    sum(row["capacity_blocked_births"] for row in run_trajectory),
                )

            cached_events = [
                event
                for event in events
                if event["arm_id"] == "cached_proposal_fixture_v1"
                and event["mutation_attempted"]
            ]
            self.assertEqual(len(cached_events), 4)
            self.assertTrue(
                all(event["proposal_provenance"] == "fixture_cache" for event in cached_events)
            )
            self.assertTrue(all(event["cache_key"] for event in cached_events))
            for replicate_id in {row["replicate_id"] for row in runs}:
                def candidate_trace(arm_id: str) -> list[tuple[object, ...]]:
                    return [
                        (
                            event["opportunity_id"],
                            event["operator_event_seed"],
                            event["parent_bug_id"],
                            event["bug_id"],
                            event["parent_program"],
                            event["candidate_program"],
                            event["program"],
                        )
                        for event in events
                        if event["replicate_id"] == replicate_id
                        and event["arm_id"] == arm_id
                        and event["mutation_attempted"]
                    ]

                self.assertEqual(
                    candidate_trace("random_atomic_edit_v1"),
                    candidate_trace("cached_proposal_fixture_v1"),
                )
            self.assertTrue(all(summary["protocol_checks"].values()))
            duplicate_summary = RUNNER.make_summary(
                [*runs, dict(runs[0])],
                events,
                require_full_budget=True,
            )
            self.assertFalse(
                duplicate_summary["protocol_checks"][
                    "one_run_per_arm_and_replicate"
                ]
            )
            self.assertIn("does not rank", summary["interpretation"])
            budget_contract = summary["proposal_budget_contract"]
            self.assertEqual(
                budget_contract["semantics"],
                "birth_triggered_upper_cap",
            )
            self.assertTrue(
                budget_contract["full_use_required_for_this_fixture_run"]
            )
            self.assertEqual(
                budget_contract["configured_cap_per_variation_run"],
                2,
            )
            self.assertFalse(
                budget_contract[
                    "opportunity_subjects_matched_after_divergence"
                ]
            )
            opportunity_matching = summary["opportunity_subject_matching"]
            self.assertFalse(
                opportunity_matching[
                    "post_divergence_subject_identity_matched_by_design"
                ]
            )
            for arm_id, arm_summary in summary["arms"].items():
                arm_runs = [row for row in runs if row["arm_id"] == arm_id]
                for key in (
                    "population_occupancy_auc_normalized",
                    "population_ceiling_fraction",
                    "role_coexistence_fraction",
                    "extinction_step",
                    "final_living_body_stored_matter",
                    "turnover_total",
                    "capacity_blocked_births_total",
                    "capacity_gate_occupancy_peak",
                    "capacity_gate_occupancy_fraction",
                ):
                    self.assertEqual(
                        arm_summary[key],
                        [row[key] for row in arm_runs],
                    )
                self.assertEqual(
                    arm_summary["proposal_budget_shortfall"],
                    [row["proposal_budget_shortfall"] for row in arm_runs],
                )
                self.assertEqual(
                    arm_summary["extinction_count"],
                    sum(row["extinction_step"] is not None for row in arm_runs),
                )
                for key in (
                    "population_occupancy_auc_normalized",
                    "population_ceiling_fraction",
                    "role_coexistence_fraction",
                    "final_living_body_stored_matter",
                    "turnover_total",
                    "capacity_gate_occupancy_fraction",
                ):
                    self.assertAlmostEqual(
                        arm_summary[f"{key}_mean"],
                        sum(row[key] for row in arm_runs) / len(arm_runs),
                    )

    def test_horizon_shortfall_is_preserved_when_full_use_is_not_required(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = json.loads(CONFIG.read_text(encoding="utf-8"))
            payload["seeds"] = [17]
            payload["proposal_budget"] = 100
            payload["require_full_budget"] = False
            payload["physics"].update(
                {
                    "n_places": 8,
                    "total_units": 160,
                    "n_organisms": 6,
                    "max_organisms": 20,
                    "steps": 1,
                    "condition_decay": 0.0,
                }
            )
            config_path = root / "shortfall.json"
            config_path.write_text(
                RUNNER.canonical_json(payload) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            config = RUNNER.read_config(config_path)
            cache = root / "shortfall-fixture.jsonl"
            cache_count = RUNNER.build_fixture_cache(config, cache)
            self.assertLess(cache_count, 100)

            output = root / "shortfall-output"
            RUNNER.run_experiment(config_path, cache, output)
            runs = read_jsonl(output / "runs.jsonl")
            summary = json.loads((output / "summary.json").read_text())
            variation_runs = [
                row for row in runs if row["arm_id"] != "inherit_only"
            ]
            self.assertTrue(
                all(0 <= row["proposal_budget_used"] <= 100 for row in runs)
            )
            self.assertTrue(
                all(
                    row["proposal_budget_shortfall"]
                    == 100 - row["proposal_budget_used"]
                    for row in variation_runs
                )
            )
            control_run = next(
                row for row in runs if row["arm_id"] == "inherit_only"
            )
            self.assertEqual(control_run["proposal_budget_cap"], 0)
            self.assertEqual(control_run["proposal_budget_used"], 0)
            self.assertEqual(control_run["proposal_budget_shortfall"], 0)
            self.assertTrue(
                any(row["proposal_budget_shortfall"] > 0 for row in variation_runs)
            )
            self.assertFalse(
                summary["proposal_budget_contract"][
                    "full_use_required_for_this_fixture_run"
                ]
            )
            self.assertTrue(all(summary["protocol_checks"].values()))

            parent = RUNNER.initial_programs(config)[0]
            unused_request = RUNNER.ProposalRequest(
                experiment_id=str(config["experiment_id"]),
                replicate_id="unused-replicate",
                opportunity_id=99,
                birth_step=0,
                parent_bug_id=1,
                child_bug_id=999,
                parent=parent,
                operator_event_seed=1,
            )
            unused_candidate = RUNNER.RandomAtomicEditOperator().propose(
                unused_request
            )
            extra = RUNNER.make_cache_record(
                RUNNER.PROFILE,
                unused_request,
                raw_text=unused_candidate.raw_candidate,
            )
            with cache.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(RUNNER.canonical_json(extra) + "\n")
            with self.assertRaisesRegex(
                CacheIntegrityError,
                "responses consumed by the cached trajectory",
            ):
                RUNNER.run_experiment(
                    config_path,
                    cache,
                    root / "unused-extra-output",
                )

    def test_qualification_is_cryptographically_bound_to_frozen_world(
        self,
    ) -> None:
        config = RUNNER.read_config(QUALIFICATION_CONFIG)
        binding = RUNNER.verify_frozen_world_binding(config)
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding["seed_role"], "qualification")
        self.assertEqual(
            binding["sha256"],
            RUNNER.sha256_bytes(FROZEN_WORLD.read_bytes()),
        )
        world = json.loads(FROZEN_WORLD.read_text(encoding="utf-8"))
        self.assertEqual(config["physics"], world["physics"])
        self.assertEqual(config["initial_programs"], world["initial_programs"])
        self.assertEqual(
            config["proposal_budget"],
            world["proposal_budget_policy"]["per_replicate_upper_cap"],
        )
        self.assertEqual(
            config["seeds"],
            world["qualification_seeds"]["master_seeds"],
        )
        self.assertTrue(config["require_full_budget"])
        self.assertFalse(
            world["proposal_budget_policy"][
                "authentic_evidence_requires_full_budget"
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "empty-cache.jsonl"
            cache.write_text("", encoding="utf-8")
            manifest = RUNNER.build_manifest(
                config,
                config_path=QUALIFICATION_CONFIG,
                cache_path=cache,
                cache_entries=0,
                frozen_world_binding=binding,
            )
        self.assertEqual(
            manifest["inputs"]["frozen_world_binding"],
            binding,
        )

        mutations = {
            "digest": lambda value: value["frozen_world_binding"].__setitem__(
                "sha256", "sha256:" + "0" * 64
            ),
            "seed-role": lambda value: value[
                "frozen_world_binding"
            ].__setitem__("seed_role", "evidence"),
            "physics": lambda value: value["physics"].__setitem__(
                "max_organisms", 159
            ),
            "budget": lambda value: value.__setitem__("proposal_budget", 7),
            "full-budget": lambda value: value.__setitem__(
                "require_full_budget", False
            ),
            "seeds": lambda value: value.__setitem__(
                "seeds", list(reversed(value["seeds"]))
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                tampered = json.loads(json.dumps(config))
                mutate(tampered)
                with self.assertRaises(ValueError):
                    RUNNER.verify_frozen_world_binding(tampered)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = json.loads(json.dumps(config))
            missing.pop("frozen_world_binding")
            missing_path = root / "missing-binding.json"
            missing_path.write_text(
                RUNNER.canonical_json(missing) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "frozen_world_binding"):
                RUNNER.read_config(missing_path)

            bad_digest = json.loads(json.dumps(config))
            bad_digest["frozen_world_binding"]["sha256"] = (
                "sha256:" + "0" * 64
            )
            bad_path = root / "bad-digest.json"
            bad_path.write_text(
                RUNNER.canonical_json(bad_digest) + "\n",
                encoding="utf-8",
            )
            output = root / "must-not-exist"
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                RUNNER.run_experiment(
                    bad_path,
                    root / "cache-is-never-read.jsonl",
                    output,
                )
            self.assertFalse(output.exists())

    def test_empty_cache_fails_closed_without_live_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self.tiny_config(root)
            empty_cache = root / "empty.jsonl"
            empty_cache.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(CacheIntegrityError, "exactly 4 records"):
                RUNNER.run_experiment(config_path, empty_cache, root / "out")
            self.assertFalse((root / "out").exists())

    def test_fixture_cache_rejects_valid_but_unused_extra_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self.tiny_config(root)
            config = RUNNER.read_config(config_path)
            cache_path = root / "fixture-with-extra.jsonl"
            RUNNER.build_fixture_cache(config, cache_path)
            parent = RUNNER.initial_programs(config)[0]
            unused_request = RUNNER.ProposalRequest(
                experiment_id=str(config["experiment_id"]),
                replicate_id="unused-replicate",
                opportunity_id=999,
                birth_step=0,
                parent_bug_id=1,
                child_bug_id=999,
                parent=parent,
                operator_event_seed=1,
            )
            unused_candidate = RUNNER.RandomAtomicEditOperator().propose(
                unused_request
            )
            extra = RUNNER.make_cache_record(
                RUNNER.PROFILE,
                unused_request,
                raw_text=unused_candidate.raw_candidate,
            )
            with cache_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(RUNNER.canonical_json(extra) + "\n")

            with self.assertRaisesRegex(
                CacheIntegrityError,
                "must contain exactly 4 records; found 5",
            ):
                RUNNER.run_experiment(config_path, cache_path, root / "out")
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
