"""Lifecycle, provenance, replay, and conservation tests for IV programs."""

from __future__ import annotations

import copy
from dataclasses import replace
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.simulation import CONDITION_MAX, CONDITION_MIN, MetabolicConfig
from evolve_modern.iv import IVProgramController, build_controlled_sim
from evolve_modern.iv_policies import (
    Construction,
    DEFAULT_IV_PROGRAMS,
    IVProgram,
    Movement,
    Role,
)


def parent_program() -> IVProgram:
    return IVProgram(
        role=Role.PRODUCER,
        taste=1,
        construct=1,
        movement=Movement.STAY_IF_FED,
        construction=Construction.NEVER,
        reproduce_at=8,
        require_uncrowded=False,
    )


def one_birth_config() -> MetabolicConfig:
    return MetabolicConfig(
        n_places=3,
        total_units=60,
        n_organisms=1,
        max_organisms=2,
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


def replay_state(simulation, controller: IVProgramController) -> tuple:
    return (
        copy.deepcopy(simulation.history),
        copy.deepcopy(simulation.bugs),
        copy.deepcopy(simulation.places),
        simulation._next,
        copy.deepcopy(simulation.rng.bit_generator.state),
        controller.record_payload(),
        copy.deepcopy(controller.rng.bit_generator.state),
    )


class IVProgramControllerLifecycleTests(unittest.TestCase):
    def test_seed_registry_has_exactly_one_typed_record_per_bug(self) -> None:
        config = MetabolicConfig(
            n_places=8,
            total_units=160,
            n_organisms=6,
            max_organisms=12,
            steps=0,
            seed=1998,
            verbose_every=0,
        )
        simulation, controller = build_controlled_sim(
            config,
            controller_seed=991,
            mutation_probability=0.0,
        )

        self.assertEqual(set(controller.records), {bug.bug_id for bug in simulation.bugs})
        self.assertEqual(len(controller.records), config.n_organisms)
        for index, bug in enumerate(simulation.bugs):
            with self.subTest(bug_id=bug.bug_id):
                record = controller.records[bug.bug_id]
                expected_program = DEFAULT_IV_PROGRAMS[index % len(DEFAULT_IV_PROGRAMS)]
                self.assertIs(record.program, expected_program)
                self.assertIsNone(record.parent_bug_id)
                self.assertEqual(record.birth_step, -1)
                self.assertFalse(record.mutation_attempted)
                self.assertIsNone(record.proposal_accepted)
                self.assertIsNone(record.proposal)
                self.assertEqual(record.reason, "seed")
                self.assertEqual(
                    (bug.producer, bug.taste, bug.construct),
                    (
                        expected_program.traits().producer,
                        expected_program.traits().taste,
                        expected_program.traits().construct,
                    ),
                )
                self.assertFalse(hasattr(bug, "policy"))

    def test_valid_mutation_is_registered_once_and_controls_child_traits(self) -> None:
        calls: list[tuple[IVProgram, dict[str, object]]] = []
        child_program = replace(
            parent_program(),
            role=Role.RECYCLER,
            taste=-1,
            construct=0,
        )

        def mutate(program: IVProgram, context: dict[str, object]) -> IVProgram:
            calls.append((program, dict(context)))
            return child_program

        simulation, controller = build_controlled_sim(
            one_birth_config(),
            controller_seed=7301,
            mutation_probability=1.0,
            programs=(parent_program(),),
            mutator=mutate,
        )

        row = simulation.step()

        self.assertEqual(row.births, 1)
        self.assertEqual(len(calls), 1)
        parent, child = simulation.bugs
        self.assertEqual((parent.bug_id, child.bug_id, child.parent), (1, 2, 1))
        self.assertEqual(calls[0][0], parent_program())
        self.assertEqual(calls[0][1]["parent_bug_id"], 1)
        self.assertEqual(calls[0][1]["child_bug_id"], 2)
        self.assertEqual(calls[0][1]["birth_step"], 0)
        self.assertGreaterEqual(float(calls[0][1]["roll"]), 0.0)
        self.assertLess(float(calls[0][1]["roll"]), 1.0)

        child_record = controller.records[2]
        self.assertEqual(child_record.parent_bug_id, 1)
        self.assertEqual(child_record.birth_step, 0)
        self.assertTrue(child_record.mutation_attempted)
        self.assertIs(child_record.proposal_accepted, True)
        self.assertEqual(child_record.proposal, child_program.to_json())
        self.assertEqual(child_record.reason, "accepted")
        self.assertEqual(child_record.program, child_program)
        self.assertEqual(
            (child.producer, child.taste, child.construct),
            (False, -1, 0),
        )
        self.assertEqual(controller.program_for(1), parent_program())
        self.assertEqual(set(controller.records), {1, 2})
        self.assertEqual(simulation.conserved(), one_birth_config().total_units)

    def test_rejected_mutation_inherits_exact_parent_and_records_rejection(self) -> None:
        calls = 0

        def malformed(program: IVProgram, context: dict[str, object]) -> str:
            nonlocal calls
            del program, context
            calls += 1
            return "{}"

        parent = parent_program()
        simulation, controller = build_controlled_sim(
            one_birth_config(),
            controller_seed=7301,
            mutation_probability=1.0,
            programs=(parent,),
            mutator=malformed,
        )

        row = simulation.step()

        self.assertEqual(row.births, 1)
        self.assertEqual(calls, 1)
        child = simulation.bugs[1]
        record = controller.records[child.bug_id]
        self.assertIs(record.program, parent)
        self.assertEqual(controller.program_for(child.bug_id), parent)
        self.assertTrue(record.mutation_attempted)
        self.assertIs(record.proposal_accepted, False)
        self.assertEqual(record.proposal, "{}")
        self.assertTrue(record.reason.startswith("PolicyValidationError:"))
        self.assertEqual(
            (child.producer, child.taste, child.construct),
            (parent.traits().producer, parent.taste, parent.construct),
        )
        self.assertEqual(simulation.conserved(), one_birth_config().total_units)

    def test_mutator_is_not_called_when_no_birth_occurs(self) -> None:
        for label, config in (
            (
                "population cap",
                replace(one_birth_config(), max_organisms=1, steps=3),
            ),
            (
                "threshold unreachable",
                replace(one_birth_config(), steps=1),
            ),
        ):
            calls = 0

            def mutate(program: IVProgram, context: dict[str, object]) -> IVProgram:
                nonlocal calls
                del context
                calls += 1
                return program

            program = parent_program()
            if label == "threshold unreachable":
                program = replace(program, reproduce_at=30)
            simulation, controller = build_controlled_sim(
                config,
                controller_seed=811,
                mutation_probability=1.0,
                programs=(program,),
                mutator=mutate,
            )

            simulation.run()

            with self.subTest(label=label):
                self.assertEqual(sum(row.births for row in simulation.history), 0)
                self.assertEqual(calls, 0)
                self.assertEqual(controller.mutation_attempts, 0)
                self.assertEqual(len(controller.records), config.n_organisms)
                self.assertEqual(simulation.conserved(), config.total_units)

    def test_uncrowded_rule_blocks_birth_after_harvest(self) -> None:
        config = MetabolicConfig(
            n_places=1,
            total_units=100,
            n_organisms=2,
            max_organisms=4,
            steps=1,
            seed=42,
            harvest=4,
            convert_yield=3,
            excrete=2,
            repro_threshold=8,
            mut_prob=0.0,
            construction=False,
            condition_decay=0.0,
            verbose_every=0,
        )
        base = replace(
            parent_program(),
            movement=Movement.DEFAULT,
            reproduce_at=8,
        )

        open_simulation, _ = build_controlled_sim(
            config,
            controller_seed=4,
            mutation_probability=0.0,
            programs=(replace(base, require_uncrowded=False),),
        )
        gated_simulation, gated_controller = build_controlled_sim(
            config,
            controller_seed=4,
            mutation_probability=0.0,
            programs=(replace(base, require_uncrowded=True),),
        )

        self.assertEqual(open_simulation.step().births, 2)
        gated_row = gated_simulation.step()

        self.assertEqual(gated_row.births, 0)
        self.assertEqual(len(gated_simulation.bugs), config.n_organisms)
        self.assertEqual(len(gated_controller.records), config.n_organisms)
        self.assertTrue(all(bug.stored >= 8 for bug in gated_simulation.bugs))
        self.assertEqual(gated_simulation.conserved(), config.total_units)


class IVProgramControllerRunTests(unittest.TestCase):
    @staticmethod
    def replay_config() -> MetabolicConfig:
        return MetabolicConfig(
            n_places=8,
            total_units=160,
            n_organisms=6,
            max_organisms=20,
            steps=12,
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

    def test_same_physics_and_controller_seeds_replay_full_state(self) -> None:
        first_sim, first_controller = build_controlled_sim(
            self.replay_config(),
            controller_seed=772,
            mutation_probability=0.6,
        )
        second_sim, second_controller = build_controlled_sim(
            self.replay_config(),
            controller_seed=772,
            mutation_probability=0.6,
        )

        first_sim.run()
        second_sim.run()

        self.assertEqual(
            replay_state(first_sim, first_controller),
            replay_state(second_sim, second_controller),
        )
        births = sum(row.births for row in first_sim.history)
        self.assertGreater(births, 0)
        self.assertEqual(len(first_controller.records), self.replay_config().n_organisms + births)
        self.assertGreater(first_controller.mutation_attempts, 0)
        self.assertEqual(
            set(first_controller.records),
            {bug.bug_id for bug in first_sim.bugs},
        )

    def test_controller_run_conserves_nonnegative_matter_at_every_step(self) -> None:
        config = MetabolicConfig(
            n_places=12,
            total_units=600,
            n_organisms=12,
            max_organisms=48,
            steps=40,
            seed=7301,
            harvest=4,
            convert_yield=3,
            excrete=2,
            repro_threshold=14,
            mut_prob=0.5,
            construction=True,
            condition_decay=0.18,
            verbose_every=0,
        )
        simulation, controller = build_controlled_sim(
            config,
            controller_seed=7301001,
            mutation_probability=0.5,
        )

        for _ in range(config.steps):
            row = simulation.step()
            self.assertEqual(
                row.nutrient + row.waste + row.stored,
                config.total_units,
            )
            self.assertEqual(simulation.conserved(), config.total_units)
            self.assertTrue(
                all(
                    place.nutrient >= 0
                    and place.waste >= 0
                    and CONDITION_MIN <= place.condition <= CONDITION_MAX
                    for place in simulation.places
                )
            )
            self.assertTrue(all(bug.stored >= 0 for bug in simulation.bugs))
            self.assertTrue(
                {bug.bug_id for bug in simulation.bugs if bug.alive}
                <= set(controller.records)
            )


if __name__ == "__main__":
    unittest.main()
