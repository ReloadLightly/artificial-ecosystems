"""Unit tests for executable-program and modifier diagnostics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve1970.organism import (
    Organism,
    decode_program,
    mutate,
    pair_to_action,
    recombine,
)


class ScriptedRng:
    """Minimal deterministic RNG for forcing mutation branches."""

    def __init__(self, random_values: list[float], integer_values: list[object]):
        self.random_values = iter(random_values)
        self.integer_values = iter(integer_values)

    def random(self) -> float:
        return float(next(self.random_values))

    def integers(
        self,
        low: int,
        high: int | None = None,
        size: int | None = None,
    ) -> int | np.ndarray:
        del low, high
        value = next(self.integer_values)
        if size is not None:
            result = np.asarray(value, dtype=int)
            if result.shape != (size,):
                raise AssertionError(f"scripted value has shape {result.shape}, expected {(size,)}")
            return result
        return int(value)

    def choice(self, values: object) -> int:
        raise AssertionError(f"unexpected choice call with {values!r}")


class DecodeProgramTests(unittest.TestCase):
    def test_strict_mode_exposes_every_complete_genome_pair(self) -> None:
        genome = [0, 0, 0, 1, 1, 0, 3, 3]

        program = decode_program(genome, reserve_modifier=False)

        expected = [
            pair_to_action(genome[i], genome[i + 1])
            for i in range(0, len(genome), 2)
        ]
        self.assertEqual(program, expected)
        self.assertEqual(len(program), len(genome) // 2)

    def test_modifier_mode_withholds_exactly_the_final_pair(self) -> None:
        genome = [0, 0, 0, 1, 1, 0, 3, 3]

        strict = decode_program(genome, reserve_modifier=False)
        modifier = decode_program(genome, reserve_modifier=True)

        self.assertEqual(modifier, strict[:-1])
        self.assertEqual(len(strict) - len(modifier), 1)


class ProgramMetricTests(unittest.TestCase):
    def test_duplicate_actions_can_occupy_separately_executed_slots(self) -> None:
        # Both pairs decode to action 0. With zero input, next_action visits the
        # two program positions in sequence even though their actions match.
        organism = Organism(
            genome=[0, 0, 0, 0],
            position=0,
            modifier_enabled=False,
        )

        self.assertAlmostEqual(organism.repeated_action_slot_fraction(), 0.5)
        self.assertAlmostEqual(organism.unexecuted_slot_fraction(), 1.0)

        organism.next_action(input_state=0)
        self.assertEqual(organism.executed_actions, {0})
        self.assertEqual(organism.executed_slots, {0})
        self.assertEqual(organism.decision_count, 1)
        self.assertAlmostEqual(organism.unexecuted_slot_fraction(), 0.5)

        organism.next_action(input_state=0)
        self.assertEqual(organism.executed_actions, {0})
        self.assertEqual(organism.executed_slots, {0, 1})
        self.assertEqual(organism.decision_count, 2)
        self.assertAlmostEqual(organism.unexecuted_slot_fraction(), 0.0)

    def test_strict_organism_executes_the_former_modifier_pair(self) -> None:
        organism = Organism(
            genome=[0, 0, 0, 0, 0, 0],
            position=0,
            modifier_enabled=False,
        )

        for _ in range(3):
            organism.next_action(input_state=0)

        self.assertEqual(organism.program, [0, 0, 0])
        self.assertEqual(organism.executed_slots, {0, 1, 2})
        self.assertEqual(organism.decision_count, 3)
        self.assertAlmostEqual(organism.unexecuted_slot_fraction(), 0.0)

    def test_modifier_pair_is_reserved_and_changes_amenability_proxy(self) -> None:
        genome = [0, 0, 3, 3]

        strict = Organism(
            genome=genome,
            position=0,
            modifier_enabled=False,
        )
        modifier = Organism(
            genome=genome,
            position=0,
            modifier_enabled=True,
        )

        self.assertEqual(strict.program, [0, 3])
        self.assertEqual(modifier.program, [0])
        self.assertAlmostEqual(strict.amenability, 0.15)
        self.assertAlmostEqual(modifier.amenability, 0.35)
        self.assertNotEqual(strict.amenability, modifier.amenability)

    def test_program_fractions_are_bounded_before_and_after_decisions(self) -> None:
        organism = Organism(
            genome=[0, 0, 0, 0, 0, 1],
            position=0,
            modifier_enabled=False,
        )

        for _ in range(8):
            repeated = organism.repeated_action_slot_fraction()
            unexecuted = organism.unexecuted_slot_fraction()
            self.assertGreaterEqual(repeated, 0.0)
            self.assertLessEqual(repeated, 1.0)
            self.assertGreaterEqual(unexecuted, 0.0)
            self.assertLessEqual(unexecuted, 1.0)
            organism.next_action(input_state=0)

    def test_modifier_mutation_preserves_executable_and_modifier_pairs(self) -> None:
        rng = np.random.default_rng(1970)

        for _ in range(100):
            genome = mutate(
                [0, 0, 3, 3],
                rng,
                amenability=0.35,
                reserve_modifier=True,
            )
            self.assertGreaterEqual(len(genome), 4)
            self.assertEqual(len(genome) % 2, 0)
            self.assertGreaterEqual(
                len(decode_program(genome, reserve_modifier=True)),
                1,
            )

    def test_modifier_mode_deletion_cannot_consume_modifier_pair(self) -> None:
        parent = [0, 0, 3, 3, 2, 2]
        rng = ScriptedRng(
            random_values=[1.0] * len(parent) + [0.0, 0.0],
            integer_values=[0],
        )

        child = mutate(parent, rng, amenability=0.0, reserve_modifier=True)

        self.assertEqual(child, [3, 3, 2, 2])
        self.assertEqual(child[-2:], parent[-2:])
        self.assertEqual(decode_program(child, reserve_modifier=True), [3])

    def test_modifier_mode_end_insertion_stays_before_modifier_pair(self) -> None:
        parent = [0, 0, 2, 2]
        rng = ScriptedRng(
            random_values=[1.0] * len(parent) + [0.0, 1.0],
            integer_values=[[1, 1], 1],
        )

        child = mutate(parent, rng, amenability=0.0, reserve_modifier=True)

        self.assertEqual(child, [0, 0, 1, 1, 2, 2])
        self.assertEqual(child[-2:], parent[-2:])
        self.assertEqual(decode_program(child, reserve_modifier=True), [0, 5])

    def test_modifier_recombination_caps_code_before_inherited_modifier(self) -> None:
        parent_a = [0, 0] * 19 + [2, 3]
        parent_b = [3, 3] * 19 + [1, 2]
        rng = ScriptedRng(random_values=[], integer_values=[18, 1])

        child = recombine(
            parent_a,
            parent_b,
            rng,
            reserve_modifier=True,
        )

        self.assertEqual(len(child), 40)
        self.assertEqual(child[-2:], parent_a[-2:])
        self.assertEqual(len(decode_program(child, reserve_modifier=True)), 19)
        self.assertEqual(child[:36], [0, 0] * 18)
        self.assertEqual(child[36:38], [3, 3])


if __name__ == "__main__":
    unittest.main()
