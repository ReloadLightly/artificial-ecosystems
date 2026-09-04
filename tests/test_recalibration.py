"""Focused contracts introduced by the experiment-first recalibration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_niches", ROOT / "experiments" / "run_niches.py"
)
assert SPEC and SPEC.loader
RUN_NICHES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_NICHES)

from evolve4.simulation import Bug, MetabolicConfig, MetabolicSim


class RecalibrationContracts(unittest.TestCase):
    def test_sparse_initialization_never_mints_matter(self) -> None:
        sim = MetabolicSim(
            MetabolicConfig(
                n_places=1,
                total_units=2,
                n_organisms=4,
                max_organisms=8,
                steps=1,
                seed=7,
            )
        )
        self.assertEqual(sim.conserved(), 2)
        self.assertTrue(any(bug.stored == 0 for bug in sim.bugs))

    def test_edge_enrichment_adjusts_for_role_composition(self) -> None:
        bugs = [
            Bug(0, 1, True, 1, 0, 0, bug_id=1),
            Bug(0, 1, True, 1, 0, 0, bug_id=2),
            Bug(1, 1, False, -1, 0, 0, bug_id=3),
        ]
        metrics = RUN_NICHES.edge_metrics(bugs, n_places=8)
        self.assertEqual(metrics["adjacent_edges"], 3.0)
        self.assertAlmostEqual(metrics["edge_cross_fraction"], 2 / 3)
        self.assertAlmostEqual(metrics["edge_expected_cross_fraction"], 2 / 3)
        self.assertAlmostEqual(metrics["edge_enrichment"], 0.0)

    def test_scramble_preserves_condition_histogram(self) -> None:
        sim = MetabolicSim(
            MetabolicConfig(n_places=8, total_units=80, n_organisms=4, seed=5)
        )
        for place, value in zip(sim.places, [-3, -2, -1, 0, 0, 1, 2, 3]):
            place.condition = value
        before = sorted(place.condition for place in sim.places)
        RUN_NICHES.scramble_place_memory(sim, RUN_NICHES.np.random.default_rng(9))
        after = sorted(place.condition for place in sim.places)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
