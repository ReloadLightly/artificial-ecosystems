"""Smoke tests for repaired experiment entry points."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

import run_amenability
import run_quiet_noisy
import run_unused


class ExperimentSmokeTests(unittest.TestCase):
    def test_repetition_and_execution_diagnostic_runs(self) -> None:
        with patch.object(run_unused, "STEPS", 8):
            result = run_unused.run_one(seed=73)

        self.assertTrue(result["conservation_ok"])
        self.assertIn("repetition_late", result)
        self.assertIn("unexecuted_late", result)
        self.assertIn("example_executed_slots", result["final"])

    def test_mutation_control_diagnostic_runs_in_modifier_mode(self) -> None:
        with patch.object(run_amenability, "STEPS", 8):
            result = run_amenability.run_one(seed=73, flip_probability=0.02)

        self.assertTrue(result["conservation_ok"])
        self.assertIn("mutation_control_early", result)
        self.assertIn("mutation_control_late", result)

    def test_extinction_is_not_averaged_as_zero_mutation_control(self) -> None:
        rows = [
            {"early": 0.20, "late": None},
            {"early": 0.18, "late": 0.16},
        ]

        self.assertAlmostEqual(run_amenability.mean(rows, "late"), 0.16)
        self.assertAlmostEqual(
            run_amenability.paired_mean_change(rows, "early", "late"),
            -0.02,
        )

    def test_quiet_noisy_diagnostic_uses_repaired_metric(self) -> None:
        with patch.object(run_quiet_noisy, "STEPS", 8):
            result = run_quiet_noisy.run_one(seed=73, flip_prob=0.1)

        self.assertTrue(result["conservation_ok"])
        self.assertIn("repeated_actions_late", result)
        self.assertIn("n_genotype_signatures_final", result)
        self.assertIn("chips_in_bodies_late", result)


if __name__ == "__main__":
    unittest.main()
