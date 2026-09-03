"""Integration contracts for the matched EVOLVE IV controller arms."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.randomness import EcologyRandomStreams, IVSeedPlan
from evolve4.simulation import MetabolicConfig
from evolve_modern.iv import IVProgramController, build_controlled_sim
from evolve_modern.iv_policies import DEFAULT_IV_PROGRAMS
from evolve_modern.iv_variation import (
    CacheProvenance,
    CachedProposalOperator,
    CachedProposalProfile,
    CachedProposalStore,
    ProgramPath,
    ProposalProvenance,
    ProposalRequest,
    RandomAtomicEditOperator,
    RawProposal,
    TypedHomologousRecombinationOperator,
    TypedPointOperator,
    make_cache_record,
)


MASTER_SEED = 1234
STARTING_PROGRAMS = DEFAULT_IV_PROGRAMS[:4]
EXPERIMENT_ID = "iv-matched-test-v1"
REPLICATE_ID = "master-1234"


def tiny_config(*, steps: int = 5, max_organisms: int = 12) -> MetabolicConfig:
    return MetabolicConfig(
        n_places=4,
        total_units=160,
        n_organisms=4,
        max_organisms=max_organisms,
        steps=steps,
        seed=MASTER_SEED,
        harvest=4,
        convert_yield=3,
        excrete=2,
        repro_threshold=8,
        mut_prob=0.0,
        construction=False,
        condition_decay=0.0,
        verbose_every=0,
    )


def build_arm(
    operator,
    *,
    plan: IVSeedPlan,
    config: MetabolicConfig,
    mutation_probability: float,
    proposal_budget: int,
):
    return build_controlled_sim(
        config,
        controller_seed=plan.variation_gate,
        proposal_seed=plan.operator,
        proposal_budget=proposal_budget,
        mutation_probability=mutation_probability,
        programs=STARTING_PROGRAMS,
        experiment_id=EXPERIMENT_ID,
        replicate_id=REPLICATE_ID,
        operator=operator,
        random_streams=EcologyRandomStreams.from_plan(plan),
    )


def run_state(simulation, controller: IVProgramController) -> tuple[object, ...]:
    return copy.deepcopy(
        (
            simulation.history,
            simulation.bugs,
            simulation.places,
            simulation._next,
            simulation.random_streams.state_dict(),
            controller.record_payload(),
            controller.rng.bit_generator.state,
            controller.proposal_rng.bit_generator.state,
            controller.proposal_budget_used,
            controller.proposal_budget_remaining,
        )
    )


class CountingOperator:
    def __init__(self, delegate):
        self.delegate = delegate
        self.operator_id = delegate.operator_id
        self.operator_revision = delegate.operator_revision
        self.requests: list[ProposalRequest] = []

    def propose(self, request: ProposalRequest) -> RawProposal:
        self.requests.append(request)
        return self.delegate.propose(request)


class BurningTasteOperator:
    """Return one fixed atomic edit after consuming only event-local RNG."""

    operator_id = "burning_taste_test"
    operator_revision = "1"

    def __init__(self, draws: int):
        self.draws = draws
        self.requests: list[ProposalRequest] = []

    def propose(self, request: ProposalRequest) -> RawProposal:
        self.requests.append(request)
        np.random.Generator(np.random.PCG64(request.operator_event_seed)).random(
            self.draws
        )
        candidate = replace(request.parent, taste=-request.parent.taste)
        return RawProposal(
            operator_id=self.operator_id,
            operator_revision=self.operator_revision,
            provenance=ProposalProvenance.TRUSTED,
            raw_candidate=candidate.to_json(),
            selected_path=ProgramPath.TASTE,
        )


class MislabelledTasteOperator(BurningTasteOperator):
    operator_id = "mislabelled_taste_test"

    def propose(self, request: ProposalRequest) -> RawProposal:
        proposal = super().propose(request)
        return replace(proposal, selected_path=ProgramPath.ROLE)


def fixture_profile() -> CachedProposalProfile:
    return CachedProposalProfile(
        provenance=CacheProvenance.FIXTURE,
        prompt_revision="atomic-edit-test-v1",
        prompt="Return one atomic schema-v1 edit.",
        model_provider="fixture",
        model_name="deterministic-test-double",
        model_revision="1",
        decoding={"temperature": 0.0},
    )


class MatchedControllerIntegrationTests(unittest.TestCase):
    def test_disabled_variation_keeps_all_four_arms_identical(self) -> None:
        plan = IVSeedPlan.from_master(MASTER_SEED)
        profile = fixture_profile()
        operators = (
            TypedPointOperator(),
            RandomAtomicEditOperator(),
            TypedHomologousRecombinationOperator(),
            CachedProposalOperator(
                profile=profile,
                store=CachedProposalStore([]),
            ),
        )
        initial_states = []
        final_states = []

        for operator in operators:
            simulation, controller = build_arm(
                operator,
                plan=plan,
                config=tiny_config(),
                mutation_probability=0.0,
                proposal_budget=3,
            )
            initial_states.append(run_state(simulation, controller))
            simulation.run()
            final_states.append(run_state(simulation, controller))

        self.assertTrue(all(state == initial_states[0] for state in initial_states))
        self.assertTrue(all(state == final_states[0] for state in final_states))
        self.assertGreater(sum(row.births for row in final_states[0][0]), 0)
        self.assertEqual(final_states[0][-2:], (0, 3))

    def test_budget_seeds_atomic_cost_and_records_reconcile(self) -> None:
        plan = IVSeedPlan.from_master(MASTER_SEED)
        budget = 3
        expected_rng = np.random.Generator(np.random.PCG64(plan.operator))
        expected_event_seeds = [
            int(
                expected_rng.integers(
                    0,
                    np.iinfo(np.int64).max,
                    dtype=np.int64,
                )
            )
            for _ in range(budget)
        ]
        observed_event_seeds = []

        for delegate in (
            TypedPointOperator(),
            RandomAtomicEditOperator(),
            TypedHomologousRecombinationOperator(),
        ):
            with self.subTest(operator=delegate.operator_id):
                operator = CountingOperator(delegate)
                simulation, controller = build_arm(
                    operator,
                    plan=plan,
                    config=tiny_config(),
                    mutation_probability=1.0,
                    proposal_budget=budget,
                )
                simulation.run()
                proposals = [
                    record
                    for record in controller.records.values()
                    if record.mutation_attempted
                ]
                exhausted = [
                    record
                    for record in controller.records.values()
                    if record.proposal_status == "budget_exhausted"
                ]

                self.assertEqual(len(operator.requests), budget)
                self.assertEqual(len(proposals), budget)
                self.assertEqual(controller.proposal_budget_used, budget)
                self.assertEqual(controller.proposal_budget_remaining, 0)
                self.assertEqual(controller.accepted_proposals, budget)
                self.assertGreater(len(exhausted), 0)
                self.assertEqual(
                    len(controller.records),
                    tiny_config().n_organisms
                    + sum(row.births for row in simulation.history),
                )
                self.assertEqual(
                    sum(record.proposal_budget_cost for record in controller.records.values()),
                    budget,
                )
                self.assertEqual(
                    [request.opportunity_id for request in operator.requests],
                    list(range(budget)),
                )
                event_seeds = [
                    record.operator_event_seed
                    for record in sorted(
                        proposals,
                        key=lambda record: record.opportunity_id,
                    )
                ]
                self.assertEqual(event_seeds, expected_event_seeds)
                observed_event_seeds.append(event_seeds)

                for record in proposals:
                    parent = controller.records[record.parent_bug_id]
                    self.assertEqual(record.proposal_budget_cost, 1)
                    self.assertTrue(record.proposal_accepted)
                    self.assertEqual(record.proposal_status, "accepted")
                    self.assertEqual(record.proposal_provenance, "trusted")
                    self.assertEqual(record.operator_id, delegate.operator_id)
                    self.assertEqual(record.parent_program, parent.program.to_json())
                    self.assertEqual(record.proposal, record.candidate_program)
                    self.assertEqual(record.program.to_json(), record.candidate_program)
                    self.assertEqual(record.changed_paths, (record.selected_path,))
                    self.assertEqual((record.field_hamming, record.atomic_distance), (1, 1))
                    self.assertFalse(record.exact_parent_inheritance)
                    self.assertIsNone(record.source_failure)
                    self.assertIsNone(record.cache_key)

                for record in exhausted:
                    self.assertFalse(record.mutation_attempted)
                    self.assertEqual(record.proposal_budget_cost, 0)
                    self.assertTrue(record.exact_parent_inheritance)

        self.assertEqual(observed_event_seeds, [expected_event_seeds] * 3)

    def test_living_donor_hook_enables_atomic_recombination(self) -> None:
        plan = IVSeedPlan.from_master(MASTER_SEED)
        operator = CountingOperator(TypedHomologousRecombinationOperator())
        simulation, controller = build_arm(
            operator,
            plan=plan,
            config=tiny_config(steps=2),
            mutation_probability=1.0,
            proposal_budget=1,
        )

        simulation.run()

        self.assertEqual(len(operator.requests), 1)
        request = operator.requests[0]
        donor_by_id = {donor.bug_id: donor.program for donor in request.living_donors}
        self.assertGreater(len(donor_by_id), 1)
        self.assertEqual(tuple(donor_by_id), tuple(sorted(donor_by_id)))
        record = next(
            record for record in controller.records.values() if record.mutation_attempted
        )
        self.assertTrue(record.proposal_accepted)
        self.assertIn(record.donor_bug_id, donor_by_id)
        self.assertNotEqual(record.donor_bug_id, record.parent_bug_id)
        self.assertEqual(
            record.donor_program,
            donor_by_id[record.donor_bug_id].to_json(),
        )
        self.assertEqual((record.field_hamming, record.atomic_distance), (1, 1))

    def test_trusted_operator_cannot_mislabel_the_accepted_path(self) -> None:
        plan = IVSeedPlan.from_master(MASTER_SEED)
        simulation, _controller = build_arm(
            MislabelledTasteOperator(0),
            plan=plan,
            config=tiny_config(steps=2),
            mutation_probability=1.0,
            proposal_budget=1,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "selected_path does not match",
        ):
            simulation.run()

    def test_operator_local_draws_cannot_perturb_gates_seeds_or_ecology(self) -> None:
        plan = IVSeedPlan.from_master(MASTER_SEED)
        runs = []
        operators = (BurningTasteOperator(1), BurningTasteOperator(10_000))

        for operator in operators:
            simulation, controller = build_arm(
                operator,
                plan=plan,
                config=tiny_config(steps=8, max_organisms=16),
                mutation_probability=0.6,
                proposal_budget=5,
            )
            self.assertIsNot(controller.rng, controller.proposal_rng)
            self.assertEqual(controller.rng.bit_generator.__class__.__name__, "PCG64")
            self.assertEqual(
                controller.proposal_rng.bit_generator.__class__.__name__,
                "PCG64",
            )
            simulation.run()
            runs.append(run_state(simulation, controller))

        self.assertGreater(len(operators[0].requests), 1)
        self.assertEqual(
            [request.operator_event_seed for request in operators[0].requests],
            [request.operator_event_seed for request in operators[1].requests],
        )
        self.assertEqual(runs[0], runs[1])

    def test_reverse_arm_execution_order_is_deterministic(self) -> None:
        plan = IVSeedPlan.from_master(MASTER_SEED)
        config = tiny_config()
        capture = BurningTasteOperator(0)
        cache_source, _controller = build_arm(
            capture,
            plan=plan,
            config=config,
            mutation_probability=1.0,
            proposal_budget=3,
        )
        cache_source.run()
        profile = fixture_profile()
        store = CachedProposalStore(
            make_cache_record(
                profile,
                request,
                raw_text=replace(request.parent, taste=-request.parent.taste).to_json(),
            )
            for request in capture.requests
        )
        factories = {
            "point": TypedPointOperator,
            "random": RandomAtomicEditOperator,
            "recombination": TypedHomologousRecombinationOperator,
            "cached": lambda: CachedProposalOperator(profile=profile, store=store),
        }

        def execute(order: tuple[str, ...]) -> dict[str, tuple[object, ...]]:
            states = {}
            for name in order:
                simulation, controller = build_arm(
                    factories[name](),
                    plan=plan,
                    config=config,
                    mutation_probability=1.0,
                    proposal_budget=3,
                )
                simulation.run()
                states[name] = run_state(simulation, controller)
            return states

        forward = tuple(factories)
        self.assertEqual(execute(forward), execute(tuple(reversed(forward))))


if __name__ == "__main__":
    unittest.main()
