"""Integration tests for the typed EVOLVE IV controller boundary."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.control import IVIntent, IVPercept, IVTraits, MovementMode
from evolve4.simulation import MetabolicConfig, MetabolicSim


class NeutralController:
    """Returns native behavior while exercising a separate random stream."""

    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.initial_calls = 0
        self.decision_calls = 0
        self.offspring_calls = 0
        self.offspring_arguments: list[tuple[int, int, IVTraits]] = []

    def initial_traits(
        self,
        bug_id: int,
        index: int,
        base_traits: IVTraits,
    ) -> IVTraits:
        del bug_id, index
        self.initial_calls += 1
        return base_traits

    def decide(self, percept: IVPercept) -> IVIntent:
        del percept
        self.decision_calls += 1
        return IVIntent()

    def offspring_traits(
        self,
        parent_bug_id: int,
        child_bug_id: int,
        base_traits: IVTraits,
    ) -> IVTraits:
        self.offspring_arguments.append(
            (parent_bug_id, child_bug_id, base_traits)
        )
        self.offspring_calls += 1
        self.rng.random(100)
        return base_traits


class AllProducerController(NeutralController):
    def initial_traits(
        self,
        bug_id: int,
        index: int,
        base_traits: IVTraits,
    ) -> IVTraits:
        del bug_id, index, base_traits
        self.initial_calls += 1
        return IVTraits(producer=True, taste=1, construct=0)


class IntentController(NeutralController):
    def __init__(self, intent_factory):
        super().__init__(seed=0)
        self.intent_factory = intent_factory

    def decide(self, percept: IVPercept) -> IVIntent:
        self.decision_calls += 1
        return self.intent_factory(percept)


class FixedTraitsController(IntentController):
    def __init__(self, intent_factory, traits: IVTraits):
        super().__init__(intent_factory)
        self.traits = traits

    def initial_traits(
        self,
        bug_id: int,
        index: int,
        base_traits: IVTraits,
    ) -> IVTraits:
        del bug_id, index, base_traits
        self.initial_calls += 1
        return self.traits


def physical_state(simulation: MetabolicSim) -> tuple:
    bugs = [
        (
            bug.position,
            bug.stored,
            bug.producer,
            bug.taste,
            bug.construct,
            bug.genome_tag,
            bug.age,
            bug.alive,
            bug.parent,
            bug.bug_id,
        )
        for bug in simulation.bugs
    ]
    places = [
        (place.nutrient, place.waste, place.condition)
        for place in simulation.places
    ]
    return (
        simulation.history,
        bugs,
        places,
        simulation._next,
        copy.deepcopy(simulation.rng.bit_generator.state),
    )


class ControllerBoundaryTests(unittest.TestCase):
    def test_neutral_controller_preserves_physics_and_ecosystem_rng(self) -> None:
        config = MetabolicConfig(
            n_places=6,
            total_units=120,
            n_organisms=3,
            max_organisms=8,
            steps=5,
            seed=2026,
            harvest=4,
            convert_yield=3,
            excrete=2,
            repro_threshold=8,
            mut_prob=0.0,
            construction=True,
            condition_decay=0.18,
            verbose_every=0,
        )
        native = MetabolicSim(config)
        controller = NeutralController(seed=991)
        controlled = MetabolicSim(config, controller=controller)

        native.run()
        controlled.run()

        self.assertEqual(physical_state(controlled), physical_state(native))
        self.assertEqual(controller.initial_calls, config.n_organisms)
        self.assertEqual(
            controller.offspring_calls,
            sum(row.births for row in controlled.history),
        )
        self.assertGreater(controller.decision_calls, 0)

    def test_controller_seed_traits_cannot_create_matter(self) -> None:
        config = MetabolicConfig(
            n_places=1,
            total_units=4,
            n_organisms=4,
            max_organisms=4,
            steps=0,
            seed=19,
            verbose_every=0,
        )

        simulation = MetabolicSim(
            config,
            controller=AllProducerController(seed=7),
        )

        self.assertEqual(simulation.conserved(), config.total_units)
        self.assertEqual(sum(bug.stored for bug in simulation.bugs), 2)
        self.assertEqual(
            sum(place.nutrient + place.waste for place in simulation.places),
            2,
        )
        self.assertTrue(all(bug.producer for bug in simulation.bugs))

    def test_default_stay_and_target_have_distinct_local_semantics(self) -> None:
        config = MetabolicConfig(
            n_places=3,
            total_units=60,
            n_organisms=1,
            max_organisms=1,
            steps=1,
            seed=17,
            harvest=4,
            convert_yield=3,
            excrete=2,
            repro_threshold=999,
            mut_prob=0.0,
            construction=False,
            condition_decay=0.0,
            verbose_every=0,
        )
        cases = {
            "default": (
                lambda percept: IVIntent(),
                (1, 8, 20, 32, 8),
            ),
            "stay": (
                lambda percept: IVIntent(movement=MovementMode.STAY),
                (2, 5, 24, 31, 5),
            ),
            "target_right": (
                lambda percept: IVIntent(
                    movement=MovementMode.TARGET,
                    target_position=percept.right,
                ),
                (0, 8, 20, 32, 8),
            ),
        }

        for label, (intent_factory, expected) in cases.items():
            with self.subTest(label=label):
                simulation = MetabolicSim(
                    config,
                    controller=IntentController(intent_factory),
                )
                self.assertEqual(simulation.bugs[0].position, 2)
                for place, nutrient in zip(
                    simulation.places,
                    (11, 13, 0),
                    strict=True,
                ):
                    place.nutrient = nutrient

                row = simulation.step()
                observed = (
                    simulation.bugs[0].position,
                    simulation.bugs[0].stored,
                    row.nutrient,
                    row.waste,
                    row.stored,
                )

                self.assertEqual(observed, expected)
                self.assertEqual(simulation.conserved(), config.total_units)

    def test_nonlocal_target_fails_before_physical_mutation(self) -> None:
        config = MetabolicConfig(
            n_places=5,
            total_units=100,
            n_organisms=1,
            max_organisms=1,
            steps=1,
            seed=17,
            verbose_every=0,
        )
        controller = IntentController(
            lambda percept: IVIntent(
                movement=MovementMode.TARGET,
                target_position=(percept.position + 2) % config.n_places,
            )
        )
        simulation = MetabolicSim(config, controller=controller)
        bugs_before = copy.deepcopy(simulation.bugs)
        places_before = copy.deepcopy(simulation.places)
        conserved_before = simulation.conserved()
        rng_before = copy.deepcopy(simulation.rng.bit_generator.state)
        next_before = simulation._next

        with self.assertRaisesRegex(ValueError, "current, left, or right"):
            simulation.step()

        self.assertEqual(simulation.bugs, bugs_before)
        self.assertEqual(simulation.places, places_before)
        self.assertEqual(simulation.history, [])
        self.assertEqual(simulation.conserved(), conserved_before)
        self.assertEqual(simulation.rng.bit_generator.state, rng_before)
        self.assertEqual(simulation._next, next_before)

    def test_construction_intent_only_controls_construction(self) -> None:
        config = MetabolicConfig(
            n_places=3,
            total_units=60,
            n_organisms=1,
            max_organisms=1,
            steps=1,
            seed=17,
            harvest=4,
            repro_threshold=999,
            mut_prob=0.0,
            construction=True,
            condition_decay=0.0,
            verbose_every=0,
        )
        traits = IVTraits(producer=True, taste=1, construct=1)

        for enabled, expected in (
            (True, [0, 0, 1]),
            (False, [0, 0, 0]),
        ):
            with self.subTest(enabled=enabled):
                controller = FixedTraitsController(
                    lambda percept, enabled=enabled: IVIntent(
                        movement=MovementMode.STAY,
                        construct=enabled,
                    ),
                    traits,
                )
                simulation = MetabolicSim(config, controller=controller)

                simulation.step()

                self.assertEqual(
                    [place.condition for place in simulation.places],
                    expected,
                )
                self.assertEqual(simulation.conserved(), config.total_units)

    def test_reproduction_threshold_controls_birth_and_child_hook(self) -> None:
        config = MetabolicConfig(
            n_places=3,
            total_units=60,
            n_organisms=1,
            max_organisms=2,
            steps=1,
            seed=17,
            harvest=4,
            repro_threshold=999,
            mut_prob=0.0,
            construction=False,
            condition_decay=0.0,
            verbose_every=0,
        )
        traits = IVTraits(producer=True, taste=1, construct=1)

        birth_controller = FixedTraitsController(
            lambda percept: IVIntent(
                movement=MovementMode.STAY,
                repro_threshold=8,
            ),
            traits,
        )
        birth_simulation = MetabolicSim(config, controller=birth_controller)
        row = birth_simulation.step()

        self.assertEqual(row.births, 1)
        self.assertEqual(birth_controller.offspring_calls, 1)
        self.assertEqual(
            birth_controller.offspring_arguments,
            [(1, 2, traits)],
        )
        self.assertEqual(len(birth_simulation.bugs), 2)
        self.assertEqual(birth_simulation.bugs[1].parent, 1)
        self.assertEqual(birth_simulation.conserved(), config.total_units)

        no_birth_controller = FixedTraitsController(
            lambda percept: IVIntent(
                movement=MovementMode.STAY,
                repro_threshold=999,
            ),
            traits,
        )
        no_birth_simulation = MetabolicSim(config, controller=no_birth_controller)
        no_birth_row = no_birth_simulation.step()

        self.assertEqual(no_birth_row.births, 0)
        self.assertEqual(no_birth_controller.offspring_calls, 0)
        self.assertEqual(no_birth_simulation.conserved(), config.total_units)

        gated_controller = FixedTraitsController(
            lambda percept: IVIntent(
                movement=MovementMode.STAY,
                reproduce=False,
                repro_threshold=8,
            ),
            traits,
        )
        gated_simulation = MetabolicSim(config, controller=gated_controller)
        gated_row = gated_simulation.step()

        self.assertEqual(gated_row.births, 0)
        self.assertEqual(gated_controller.offspring_calls, 0)
        self.assertEqual(gated_simulation.conserved(), config.total_units)


if __name__ == "__main__":
    unittest.main()
