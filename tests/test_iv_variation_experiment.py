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
            },
            {
                "step": 1,
                "n_alive": 5,
                "n_producers": 3,
                "n_recyclers": 2,
                "stored": 17,
                "births": 2,
                "deaths": 1,
            },
            {
                "step": 2,
                "n_alive": 0,
                "n_producers": 0,
                "n_recyclers": 0,
                "stored": 0,
                "births": 0,
                "deaths": 5,
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
            self.assertIn("does not rank", summary["interpretation"])
            for arm_id, arm_summary in summary["arms"].items():
                arm_runs = [row for row in runs if row["arm_id"] == arm_id]
                for key in (
                    "population_occupancy_auc_normalized",
                    "population_ceiling_fraction",
                    "role_coexistence_fraction",
                    "extinction_step",
                    "final_living_body_stored_matter",
                    "turnover_total",
                ):
                    self.assertEqual(
                        arm_summary[key],
                        [row[key] for row in arm_runs],
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
                ):
                    self.assertAlmostEqual(
                        arm_summary[f"{key}_mean"],
                        sum(row[key] for row in arm_runs) / len(arm_runs),
                    )

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
