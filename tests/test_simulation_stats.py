"""Integration-level unit tests for repaired EVOLVE diagnostics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from statistics import fmean


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve1970.organism import Organism
from evolve1970.simulation import Simulation, SimulationConfig


def small_config(*, modifier_enabled: bool, seed: int = 7301) -> SimulationConfig:
    return SimulationConfig(
        n_places=12,
        total_chips=600,
        n_organisms=12,
        max_organisms=48,
        steps=24,
        seed=seed,
        verbose_every=0,
        modifier_enabled=modifier_enabled,
    )


class SimulationStatisticTests(unittest.TestCase):
    def test_step_statistics_equal_direct_living_population_calculations(self) -> None:
        for modifier_enabled in (False, True):
            with self.subTest(modifier_enabled=modifier_enabled):
                simulation = Simulation(
                    small_config(modifier_enabled=modifier_enabled, seed=8104)
                )

                stats = simulation.step()
                living = [organism for organism in simulation.organisms if organism.alive]

                self.assertTrue(living)
                self.assertEqual(
                    stats.n_genotype_signatures,
                    len({organism.genotype_signature() for organism in living}),
                )
                self.assertEqual(
                    stats.n_lineages,
                    stats.n_genotype_signatures,
                )
                self.assertAlmostEqual(
                    stats.repeated_action_fraction,
                    fmean(
                        organism.repeated_action_slot_fraction()
                        for organism in living
                    ),
                )
                self.assertAlmostEqual(
                    stats.mean_unexecuted_slot_fraction,
                    fmean(organism.unexecuted_slot_fraction() for organism in living),
                )
                self.assertAlmostEqual(
                    stats.mean_amenability_proxy,
                    fmean(organism.amenability for organism in living),
                )
                self.assertAlmostEqual(
                    stats.mean_decision_count,
                    fmean(organism.decision_count for organism in living),
                )

                for fraction in (
                    stats.repeated_action_fraction,
                    stats.mean_unexecuted_slot_fraction,
                    stats.mean_amenability_proxy,
                ):
                    self.assertGreaterEqual(fraction, 0.0)
                    self.assertLessEqual(fraction, 1.0)

    def test_modifier_setting_reaches_seeded_organisms(self) -> None:
        for modifier_enabled in (False, True):
            with self.subTest(modifier_enabled=modifier_enabled):
                simulation = Simulation(
                    small_config(modifier_enabled=modifier_enabled, seed=4815)
                )

                self.assertTrue(simulation.organisms)
                self.assertTrue(
                    all(
                        organism.modifier_enabled is modifier_enabled
                        for organism in simulation.organisms
                    )
                )

    def test_modifier_setting_is_inherited_by_newborns(self) -> None:
        for modifier_enabled in (False, True):
            with self.subTest(modifier_enabled=modifier_enabled):
                config = SimulationConfig(
                    n_places=8,
                    total_chips=240,
                    n_organisms=1,
                    max_organisms=4,
                    steps=1,
                    seed=1776,
                    recombination_rate=0.0,
                    verbose_every=0,
                    modifier_enabled=modifier_enabled,
                )
                simulation = Simulation(config)
                seeded = simulation.organisms[0]
                target_store = 20
                extra = simulation.world.take_chips(
                    seeded.position,
                    target_store - seeded.stored_chips,
                )
                self.assertEqual(seeded.stored_chips + extra, target_store)

                # A single executable reproduce slot guarantees a birth. In
                # modifier mode the second pair is reserved for the proxy.
                genome = [1, 0, 3, 3] if modifier_enabled else [1, 0]
                simulation.organisms[0] = Organism(
                    genome=genome,
                    position=seeded.position,
                    stored_chips=target_store,
                    territory=0,
                    organism_id=seeded.organism_id,
                    modifier_enabled=modifier_enabled,
                )

                stats = simulation.step()

                self.assertEqual(stats.births, 1)
                newborns = [
                    organism
                    for organism in simulation.organisms
                    if organism.parent_id is not None
                ]
                self.assertEqual(len(newborns), 1)
                self.assertIs(newborns[0].modifier_enabled, modifier_enabled)
                self.assertEqual(simulation.conserved_chips(), config.total_chips)

    def test_conservation_holds_at_every_step_in_both_modes(self) -> None:
        for modifier_enabled in (False, True):
            with self.subTest(modifier_enabled=modifier_enabled):
                config = small_config(
                    modifier_enabled=modifier_enabled,
                    seed=9917,
                )
                simulation = Simulation(config)

                for _ in range(config.steps):
                    stats = simulation.step()
                    observed = (
                        stats.chips_places + stats.chips_bodies + stats.chips_pool
                    )
                    self.assertEqual(observed, config.total_chips)
                    self.assertEqual(simulation.conserved_chips(), config.total_chips)

    def test_same_seed_replays_identical_histories_in_both_modes(self) -> None:
        for modifier_enabled in (False, True):
            with self.subTest(modifier_enabled=modifier_enabled):
                config = small_config(
                    modifier_enabled=modifier_enabled,
                    seed=20260902,
                )

                first = Simulation(config).run()
                second = Simulation(config).run()

                self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
