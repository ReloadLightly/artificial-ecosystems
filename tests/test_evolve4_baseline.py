"""Golden-trace contract for controller-free EVOLVE IV-inspired physics."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.simulation import MetabolicConfig, MetabolicSim


class Evolve4BaselineTests(unittest.TestCase):
    def test_controller_free_golden_trace_is_unchanged(self) -> None:
        config = MetabolicConfig(
            n_places=8,
            total_units=160,
            n_organisms=6,
            max_organisms=20,
            steps=8,
            seed=1998,
            harvest=4,
            convert_yield=3,
            excrete=2,
            repro_threshold=10,
            mut_prob=0.35,
            construction=True,
            condition_decay=0.18,
            verbose_every=0,
        )
        simulation = MetabolicSim(config)

        history = simulation.run()

        trace = [
            (
                row.n_alive,
                row.n_producers,
                row.n_recyclers,
                row.nutrient,
                row.waste,
                row.stored,
                row.births,
                row.deaths,
                row.condition_mean,
                row.condition_var,
            )
            for row in history
        ]
        self.assertEqual(
            trace,
            [
                (6, 3, 3, 61, 57, 42, 0, 0, -0.25, 0.6875),
                (10, 5, 5, 57, 49, 54, 4, 0, -0.5, 2.0),
                (10, 5, 5, 47, 44, 69, 1, 1, -0.5, 3.25),
                (11, 6, 5, 35, 43, 82, 1, 0, -0.875, 3.109375),
                (13, 6, 7, 27, 42, 91, 2, 0, -1.0, 1.75),
                (15, 8, 7, 21, 39, 100, 2, 0, -1.625, 1.234375),
                (18, 11, 7, 14, 27, 119, 3, 0, -1.875, 0.859375),
                (20, 11, 9, 6, 21, 133, 2, 0, -2.375, 0.734375),
            ],
        )

        bug_trace = [
            (
                bug.bug_id,
                bug.parent,
                bug.position,
                bug.stored,
                bug.producer,
                bug.taste,
                bug.construct,
                bug.genome_tag,
                bug.age,
                bug.alive,
            )
            for bug in simulation.bugs
        ]
        self.assertEqual(
            bug_trace,
            [
                (1, None, 1, 4, True, 1, 0, 7, 8, True),
                (2, None, 0, 8, False, -1, -1, 1, 8, True),
                (3, None, 6, 5, True, -1, 0, 8, 8, True),
                (4, None, 4, 8, False, -1, -1, 12, 8, True),
                (5, None, 6, 6, True, -1, -1, 1, 8, True),
                (6, None, 2, 0, False, 1, 1, 13, 3, False),
                (7, 2, 3, 5, False, -1, -1, 1, 6, True),
                (8, 3, 3, 9, True, 1, 0, 11, 6, True),
                (9, 1, 3, 9, True, 1, 1, 8, 6, True),
                (10, 4, 5, 11, False, 1, -1, 15, 6, True),
                (11, 6, 2, 6, False, 1, -1, 15, 5, True),
                (12, 5, 5, 8, True, -1, -1, 1, 4, True),
                (13, 10, 6, 6, False, 1, -1, 15, 3, True),
                (14, 7, 4, 10, False, 1, -1, 4, 3, True),
                (15, 8, 0, 6, True, 1, 0, 11, 2, True),
                (16, 3, 7, 6, True, -1, 0, 8, 2, True),
                (17, 4, 4, 5, True, -1, -1, 14, 1, True),
                (18, 1, 0, 4, True, -1, 0, 10, 1, True),
                (19, 12, 5, 7, True, -1, 0, 2, 1, True),
                (20, 13, 7, 5, False, 1, -1, 15, 0, True),
                (21, 7, 2, 5, False, -1, -1, 1, 0, True),
            ],
        )
        self.assertEqual(
            [
                (place.nutrient, place.waste, place.condition)
                for place in simulation.places
            ],
            [
                (0, 1, -3),
                (0, 4, -1),
                (1, 0, -3),
                (0, 1, -2),
                (1, 6, -3),
                (4, 4, -3),
                (0, 2, -3),
                (0, 3, -1),
            ],
        )
        self.assertTrue(
            all(
                row.nutrient + row.waste + row.stored == config.total_units
                for row in history
            )
        )
        self.assertEqual(simulation.conserved(), config.total_units)
        rng_state = json.dumps(
            simulation.rng.bit_generator.state,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(rng_state).hexdigest(),
            "856372359d4b333e7bf6e05240628e0ed7f0afd61766c7f5a1ba1fcdcd1712b7",
        )
        self.assertEqual(simulation._next, 21)


if __name__ == "__main__":
    unittest.main()
