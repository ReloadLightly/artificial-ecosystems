"""Contracts for the compact frozen semantic-variation micro-study."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from evolve4.simulation import Bug


SPEC = importlib.util.spec_from_file_location(
    "run_semantic_variation",
    ROOT / "experiments" / "run_semantic_variation.py",
)
assert SPEC and SPEC.loader
STUDY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STUDY
SPEC.loader.exec_module(STUDY)


def cache_record(case, raw_text: str | None = None) -> dict[str, object]:
    if raw_text is None:
        raw_text = STUDY.typed_macro(case).to_json()
    validation = STUDY.validate_response(case, raw_text)
    return {
        "schema": STUDY.CACHE_SCHEMA,
        "study_id": STUDY.STUDY_ID,
        "sequence": case.sequence,
        "case_id": case.case_id,
        "parent_index": case.parent_index,
        "change_paths": list(case.change_paths),
        "parent_program": case.parent.to_json(),
        "prompt": case.prompt,
        "prompt_sha256": STUDY.sha256_text(case.prompt),
        "request_bank_sha256": STUDY.request_bank_sha256(),
        "protocol_commit": "0" * 40,
        "surface": {
            "kind": "chatgpt_work_codex_subagent_v1",
            "artifact_class": "orchestrator_attested_final_answer",
            "attestation_basis": "captured_fresh_subagent_final_channel",
            "auth_mode": "chatgpt_subscription",
            "study_supplied_api_key": False,
            "direct_api_billing_exposure": "not_applicable_no_direct_api_call",
            "subscription_usage_exposure": "not_exposed",
            "requested_model": STUDY.REQUESTED_MODEL,
            "reasoning_effort": STUDY.REASONING_EFFORT,
            "returned_model_revision": None,
            "revision_exposure": "not_exposed",
            "provider_request_id_exposure": "not_exposed",
            "provider_wire_exposure": "not_exposed",
            "hidden_instructions_exposure": "not_exposed",
            "tool_activity_exposure": "not_exposed",
            "internal_retry_exposure": "not_exposed",
            "context_fork": "none",
            "task_message_sha256": STUDY.sha256_text(case.prompt),
            "task_name": f"semantic_{case.sequence:02d}",
            "capture": "final_channel_only",
            "batch_id": "semantic-variation-v1-2026-09-04",
            "client_visible_turns": 1,
            "application_retries": 0,
            "orchestrator_task_path": f"/root/test-{case.sequence:02d}",
            "collected_at_utc": "2026-09-04T00:00:00Z",
        },
        "response": {
            "status": "ok",
            "captured_final_answer_text": raw_text,
            "captured_final_answer_sha256": STUDY.sha256_text(raw_text),
            "failure_detail": None,
        },
        "validation": validation.to_dict(),
    }


class CaseBankTests(unittest.TestCase):
    def test_case_bank_is_balanced_fixed_and_exactly_24(self) -> None:
        cases = STUDY.study_cases()
        self.assertEqual(len(cases), 24)
        self.assertEqual([case.sequence for case in cases], list(range(24)))
        self.assertTrue(all(len(case.change_paths) == 3 for case in cases))
        self.assertTrue(all(case.parent.construct != 0 for case in cases))
        roles = [case.parent.role.value for case in cases]
        self.assertEqual(roles.count("producer"), 12)
        self.assertEqual(roles.count("recycler"), 12)
        self.assertEqual(
            {case.change_paths for case in cases}, set(STUDY.CHANGE_MASKS)
        )
        self.assertTrue(set(STUDY.EVIDENCE_SEEDS).isdisjoint(STUDY.QUALIFICATION_SEEDS))

    def test_prompt_binds_parent_and_exact_mask_without_outcome_data(self) -> None:
        case = STUDY.study_cases()[0]
        self.assertIn(f"PARENT={case.parent.to_json()}", case.prompt)
        self.assertIn(
            f"CHANGE_PATHS={STUDY.canonical_json(list(case.change_paths))}",
            case.prompt,
        )
        self.assertNotIn("famine", case.prompt.lower())
        self.assertNotIn("fitness", case.prompt.lower().replace("fitness evaluator", ""))
        self.assertTrue(case.prompt.endswith("]"))

    def test_typed_and_random_controls_change_exactly_the_same_mask(self) -> None:
        for case in STUDY.study_cases():
            for candidate in (
                STUDY.typed_macro(case),
                STUDY.random_same_mask(case),
            ):
                with self.subTest(case=case.case_id, candidate=candidate.to_json()):
                    self.assertEqual(
                        set(STUDY.changed_paths(case.parent, candidate)),
                        set(case.change_paths),
                    )
                    self.assertEqual(candidate.traits(), case.parent.traits())


class ResponseCacheTests(unittest.TestCase):
    def test_validation_is_intention_to_treat_and_support_exact(self) -> None:
        case = STUDY.study_cases()[0]
        valid = STUDY.typed_macro(case).to_json()
        accepted = STUDY.validate_response(case, valid)
        self.assertTrue(accepted.valid)
        self.assertEqual(accepted.status, "valid")

        malformed = STUDY.validate_response(case, "```json\n{}\n```")
        self.assertFalse(malformed.valid)
        self.assertEqual(malformed.status, "malformed_or_wrong_schema")

        no_change = STUDY.validate_response(case, case.parent.to_json())
        self.assertFalse(no_change.valid)
        self.assertEqual(no_change.status, "wrong_change_support")

        wrong_traits = STUDY.validate_response(
            case,
            STUDY.replace(case.parent, taste=-case.parent.taste).to_json(),
        )
        self.assertFalse(wrong_traits.valid)
        self.assertEqual(wrong_traits.status, "wrong_traits")

    def test_cache_round_trip_is_strict_and_recomputes_validation(self) -> None:
        records = [cache_record(case) for case in STUDY.study_cases()]
        for record, case in zip(records, STUDY.study_cases(), strict=True):
            record["surface"]["orchestrator_task_path"] = (
                f"/root/semantic_{case.sequence:02d}"
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.jsonl"
            path.write_text(
                "\n".join(STUDY.canonical_json(record) for record in records) + "\n",
                encoding="utf-8",
            )
            loaded = STUDY.load_cache(path)
            self.assertEqual(len(loaded), 24)

            changed = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            changed["validation"]["valid"] = False
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0] = STUDY.canonical_json(changed)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(STUDY.CacheError, "validation"):
                STUDY.load_cache(path)

    def test_cache_rejects_boolean_integer_impersonation_and_bad_time(self) -> None:
        cases = STUDY.study_cases()
        records = [cache_record(case) for case in cases]
        for record, case in zip(records, cases, strict=True):
            record["surface"]["orchestrator_task_path"] = (
                f"/root/semantic_{case.sequence:02d}"
            )
        mutations = (
            ("schema", True),
            ("sequence", False),
            ("parent_index", False),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.jsonl"
            for key, value in mutations:
                changed = json.loads(json.dumps(records))
                changed[0][key] = value
                path.write_text(
                    "\n".join(STUDY.canonical_json(record) for record in changed)
                    + "\n",
                    encoding="utf-8",
                )
                with self.subTest(key=key), self.assertRaises(STUDY.CacheError):
                    STUDY.load_cache(path)
            changed = json.loads(json.dumps(records))
            changed[0]["surface"]["collected_at_utc"] = "not-a-timeZ"
            path.write_text(
                "\n".join(STUDY.canonical_json(record) for record in changed) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(STUDY.CacheError, "UTC second precision"):
                STUDY.load_cache(path)

    def test_invalid_cached_response_maps_to_exact_parent(self) -> None:
        case = STUDY.study_cases()[0]
        record = cache_record(case, case.parent.to_json())
        self.assertFalse(record["validation"]["valid"])
        self.assertIs(STUDY.candidate_from_cache(case, record), case.parent)


class EcologyAssayTests(unittest.TestCase):
    def test_behavioral_candidates_leave_initial_physics_identical(self) -> None:
        case = STUDY.study_cases()[0]
        candidates = (
            case.parent,
            STUDY.typed_macro(case),
            STUDY.random_same_mask(case),
        )
        simulations = [STUDY.build_assay(case, candidate, 1234) for candidate in candidates]
        self.assertEqual(
            {STUDY.physical_state_hash(simulation) for simulation in simulations},
            {STUDY.physical_state_hash(simulations[0])},
        )
        self.assertEqual(
            {simulation.conserved() for simulation in simulations},
            {STUDY.WORLD["total_units"]},
        )

    def test_recovery_requires_three_consecutive_reference_hits(self) -> None:
        self.assertEqual(
            STUDY.recovery_time([8, 9, 9, 9, 2], [10, 10, 10, 10, 10]),
            2,
        )
        self.assertIsNone(STUDY.recovery_time([9, 8, 9, 8], [10, 10, 10, 10]))

    def test_one_full_assay_conserves_and_branches_from_exact_state(self) -> None:
        case = STUDY.study_cases()[0]
        row = STUDY.run_assay(
            case,
            "typed_macro",
            STUDY.typed_macro(case),
            STUDY.QUALIFICATION_SEEDS[0],
            candidate_status="valid",
        )
        self.assertTrue(row["conservation_ok"])
        self.assertEqual(row["field_hamming"], 3)
        self.assertEqual(row["initial_physical_sha256"][:7], "sha256:")
        self.assertEqual(row["pre_shock_state_sha256"][:7], "sha256:")

    def test_lineage_establishment_requires_a_living_granddescendant(self) -> None:
        case = STUDY.study_cases()[0]
        sim = STUDY.build_assay(case, case.parent, 1234)
        controller = sim.controller
        root = case.parent_index + 1
        seed_record = controller.records[root]
        controller.records[17] = STUDY.replace(
            seed_record, bug_id=17, parent_bug_id=root, birth_step=1
        )
        sim.bugs.append(Bug(0, 1, True, 1, 1, 0, bug_id=17, parent=root))
        self.assertFalse(STUDY.lineage_snapshot(sim, root)["established"])
        controller.records[18] = STUDY.replace(
            seed_record, bug_id=18, parent_bug_id=17, birth_step=2
        )
        sim.bugs.append(Bug(0, 1, True, 1, 1, 0, bug_id=18, parent=17))
        self.assertTrue(STUDY.lineage_snapshot(sim, root)["established"])

    def test_seed_contrast_averages_cases_inside_each_ecology_seed(self) -> None:
        rows = []
        for seed_index, seed in enumerate(STUDY.EVIDENCE_SEEDS):
            for case in STUDY.study_cases():
                rows.extend(
                    (
                        {
                            "case_id": case.case_id,
                            "seed": seed,
                            "arm": "codex_agent_itt",
                            "metric": float(seed_index),
                        },
                        {
                            "case_id": case.case_id,
                            "seed": seed,
                            "arm": "typed_macro",
                            "metric": 0.0,
                        },
                    )
                )
        result = STUDY.seed_level_contrast(rows, "metric", "typed_macro")
        self.assertEqual(result["seed_effects"], [float(value) for value in range(8)])
        self.assertEqual(result["estimate"], 3.5)
        self.assertEqual(result["n_ecology_seeds"], 8)

    def test_qualification_does_not_load_authentic_cache(self) -> None:
        row = {
            "arm": "parent",
            "initial_physical_sha256": "same",
            "established_at_shock": False,
            "lineage_share_auc_gap": 0.0,
            "lineage_alive_auc_gap": 0.0,
            "population_recovery_censored": False,
            "conservation_ok": True,
            "capacity_blocked_births": 0,
        }

        def fake_assay(_case, arm, _candidate, _seed, **_kwargs):
            return {**row, "arm": arm}

        with mock.patch.object(
            STUDY, "load_cache", side_effect=AssertionError("cache read")
        ), mock.patch.object(STUDY, "run_assay", side_effect=fake_assay):
            result = STUDY.qualify()
        self.assertTrue(result["all_conserved"])

    def test_source_snapshot_covers_transitive_variation_module(self) -> None:
        self.assertIn(
            "src/evolve_modern/iv_variation.py",
            STUDY.source_hashes(),
        )


if __name__ == "__main__":
    unittest.main()
