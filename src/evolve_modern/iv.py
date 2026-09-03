"""Typed controller integration for the EVOLVE IV-inspired world.

This module owns controller programs, their dedicated random stream, and the
``bug_id -> PolicyRecord`` registry. Ecological matter and organism bodies stay
inside :mod:`evolve4`; no policy text is attached to ``Bug``.

Usage:
    PYTHONPATH=src python3 -m evolve_modern.iv
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from evolve4.control import IVIntent, IVPercept, IVTraits
from evolve4.randomness import EcologyRandomStreams
from evolve4.simulation import MetabolicConfig, MetabolicSim
from evolve_modern.iv_policies import (
    DEFAULT_IV_PROGRAMS,
    IVProgram,
    coerce_program,
    decide_program,
    heuristic_mutate_iv_program,
)
from evolve_modern.iv_variation import (
    Donor,
    OperatorContractError,
    ProposalProvenance,
    ProposalRequest,
    RawProposal,
    VariationOperator,
    adjudicate_proposal,
    program_field_value,
)


ProgramMutator = Callable[[IVProgram, Mapping[str, Any]], object]


@dataclass(frozen=True)
class PolicyRecord:
    """One immutable seed, inheritance, acceptance, or rejection record."""

    bug_id: int
    parent_bug_id: int | None
    birth_step: int
    program: IVProgram
    mutation_attempted: bool
    proposal_accepted: bool | None
    proposal: str | None
    reason: str
    experiment_id: str | None = None
    replicate_id: str | None = None
    opportunity_id: int | None = None
    proposal_budget_cost: int = 0
    operator_event_seed: int | None = None
    operator_id: str | None = None
    operator_revision: str | None = None
    proposal_provenance: str | None = None
    proposal_status: str | None = None
    source_failure: str | None = None
    failure_detail: str | None = None
    selected_path: str | None = None
    donor_bug_id: int | None = None
    donor_program: str | None = None
    cache_key: str | None = None
    parent_program: str | None = None
    candidate_program: str | None = None
    changed_paths: tuple[str, ...] = ()
    field_hamming: int | None = None
    atomic_distance: int | None = None
    exact_parent_inheritance: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "bug_id": self.bug_id,
            "parent_bug_id": self.parent_bug_id,
            "birth_step": self.birth_step,
            "program": self.program.to_json(),
            "mutation_attempted": self.mutation_attempted,
            "proposal_accepted": self.proposal_accepted,
            "proposal": self.proposal,
            "reason": self.reason,
            "experiment_id": self.experiment_id,
            "replicate_id": self.replicate_id,
            "opportunity_id": self.opportunity_id,
            "proposal_budget_cost": self.proposal_budget_cost,
            "operator_event_seed": self.operator_event_seed,
            "operator_id": self.operator_id,
            "operator_revision": self.operator_revision,
            "proposal_provenance": self.proposal_provenance,
            "proposal_status": self.proposal_status,
            "source_failure": self.source_failure,
            "failure_detail": self.failure_detail,
            "selected_path": self.selected_path,
            "donor_bug_id": self.donor_bug_id,
            "donor_program": self.donor_program,
            "cache_key": self.cache_key,
            "parent_program": self.parent_program,
            "candidate_program": self.candidate_program,
            "changed_paths": list(self.changed_paths),
            "field_hamming": self.field_hamming,
            "atomic_distance": self.atomic_distance,
            "exact_parent_inheritance": self.exact_parent_inheritance,
        }


class IVProgramController:
    """Population controller with validated programs and an isolated RNG."""

    def __init__(
        self,
        *,
        seed: int,
        mutation_probability: float,
        programs: Sequence[IVProgram | str] = DEFAULT_IV_PROGRAMS,
        mutator: ProgramMutator = heuristic_mutate_iv_program,
        proposal_seed: int | None = None,
        proposal_budget: int | None = None,
        experiment_id: str = "iv-controller",
        replicate_id: str = "default",
        operator: VariationOperator | None = None,
    ):
        if not 0.0 <= mutation_probability <= 1.0:
            raise ValueError("mutation_probability must be between 0 and 1")
        typed_programs = tuple(coerce_program(program) for program in programs)
        if not typed_programs:
            raise ValueError("at least one initial IV program is required")
        if not callable(mutator):
            raise TypeError("mutator must be callable")
        if proposal_seed is not None and (
            type(proposal_seed) is not int or proposal_seed < 0
        ):
            raise ValueError("proposal_seed must be a nonnegative integer or None")
        if proposal_budget is not None and (
            type(proposal_budget) is not int or proposal_budget < 0
        ):
            raise ValueError("proposal_budget must be a nonnegative integer or None")
        if type(experiment_id) is not str or not experiment_id.strip():
            raise ValueError("experiment_id must be a nonempty string")
        if type(replicate_id) is not str or not replicate_id.strip():
            raise ValueError("replicate_id must be a nonempty string")
        if operator is not None and not callable(getattr(operator, "propose", None)):
            raise TypeError("operator must provide propose(ProposalRequest)")
        if operator is not None and mutator is not heuristic_mutate_iv_program:
            raise ValueError("operator and a custom legacy mutator are mutually exclusive")

        self.seed = int(seed)
        self.mutation_probability = float(mutation_probability)
        self.programs = typed_programs
        self.mutator = mutator
        self.rng = np.random.Generator(np.random.PCG64(self.seed))
        self.proposal_seed = self.seed if proposal_seed is None else proposal_seed
        self.proposal_rng = np.random.Generator(np.random.PCG64(self.proposal_seed))
        self._proposal_stream_is_explicit = proposal_seed is not None
        self.proposal_budget = proposal_budget
        self.experiment_id = experiment_id
        self.replicate_id = replicate_id
        self.operator = operator
        self.records: dict[int, PolicyRecord] = {}
        self._last_step: dict[int, int] = {}
        self._proposal_budget_used = 0
        self._prepared_births: dict[int, tuple[int, tuple[Donor, ...]]] = {}

    def _register(self, record: PolicyRecord) -> None:
        if record.bug_id in self.records:
            raise RuntimeError(f"controller record already exists for {record.bug_id}")
        self.records[record.bug_id] = record

    def initial_traits(
        self,
        bug_id: int,
        index: int,
        base_traits: IVTraits,
    ) -> IVTraits:
        del base_traits
        program = self.programs[index % len(self.programs)]
        self._register(
            PolicyRecord(
                bug_id=bug_id,
                parent_bug_id=None,
                birth_step=-1,
                program=program,
                mutation_attempted=False,
                proposal_accepted=None,
                proposal=None,
                reason="seed",
                experiment_id=self.experiment_id,
                replicate_id=self.replicate_id,
                proposal_status="seed",
            )
        )
        return program.traits()

    def decide(self, percept: IVPercept) -> IVIntent:
        try:
            record = self.records[percept.bug_id]
        except KeyError as exc:
            raise RuntimeError(
                f"no controller record for bug {percept.bug_id}"
            ) from exc
        self._last_step[percept.bug_id] = percept.step
        return decide_program(record.program, percept)

    def prepare_birth(
        self,
        parent_bug_id: int,
        child_bug_id: int,
        living_bug_ids: Sequence[int],
    ) -> None:
        """Freeze the exact living donor pool before the child hook runs.

        The simulator's lifecycle protocol intentionally keeps
        :meth:`offspring_traits` small and physics-oriented.  This companion
        hook captures population context without exposing mutable ``Bug``
        objects to a variation operator.  The prepared context is single-use.
        """
        if type(parent_bug_id) is not int or type(child_bug_id) is not int:
            raise TypeError("parent_bug_id and child_bug_id must be integers")
        if parent_bug_id not in self.records:
            raise RuntimeError(f"no parent controller record for bug {parent_bug_id}")
        if child_bug_id in self.records:
            raise RuntimeError(f"controller record already exists for {child_bug_id}")
        if child_bug_id in self._prepared_births:
            raise RuntimeError(f"birth context already prepared for {child_bug_id}")

        ids = tuple(living_bug_ids)
        if any(type(bug_id) is not int for bug_id in ids):
            raise TypeError("living_bug_ids must contain only integers")
        if len(set(ids)) != len(ids):
            raise ValueError("living_bug_ids must not contain duplicates")
        missing = sorted(set(ids) - self.records.keys())
        if missing:
            joined = ", ".join(str(bug_id) for bug_id in missing)
            raise RuntimeError(f"no controller records for living bugs: {joined}")
        if parent_bug_id not in ids:
            raise ValueError("living_bug_ids must include the reproducing parent")

        donors = tuple(
            Donor(bug_id=bug_id, program=self.records[bug_id].program)
            for bug_id in sorted(ids)
        )
        self._prepared_births[child_bug_id] = (parent_bug_id, donors)

    @staticmethod
    def _proposal_text(candidate: object) -> str:
        if isinstance(candidate, IVProgram):
            return candidate.to_json()
        if type(candidate) is str:
            return candidate
        return repr(candidate)

    @staticmethod
    def _enum_text(value: object | None) -> str | None:
        if value is None:
            return None
        enum_value = getattr(value, "value", None)
        return str(enum_value if enum_value is not None else value)

    def _birth_donors(
        self,
        parent_bug_id: int,
        child_bug_id: int,
    ) -> tuple[Donor, ...]:
        prepared = self._prepared_births.pop(child_bug_id, None)
        if prepared is None:
            return ()
        prepared_parent, donors = prepared
        if prepared_parent != parent_bug_id:
            raise RuntimeError(
                "prepared birth parent does not match offspring_traits parent"
            )
        return donors

    def _budget_available(self) -> bool:
        return (
            self.proposal_budget is None
            or self._proposal_budget_used < self.proposal_budget
        )

    def _next_operator_event_seed(self) -> int:
        return int(
            self.proposal_rng.integers(
                0,
                np.iinfo(np.int64).max,
                dtype=np.int64,
            )
        )

    def _register_inheritance(
        self,
        *,
        parent: PolicyRecord,
        child_bug_id: int,
        reason: str,
        status: str,
    ) -> IVTraits:
        self._register(
            PolicyRecord(
                bug_id=child_bug_id,
                parent_bug_id=parent.bug_id,
                birth_step=self._last_step.get(parent.bug_id, -1),
                program=parent.program,
                mutation_attempted=False,
                proposal_accepted=None,
                proposal=None,
                reason=reason,
                experiment_id=self.experiment_id,
                replicate_id=self.replicate_id,
                proposal_status=status,
                parent_program=parent.program.to_json(),
                exact_parent_inheritance=True,
            )
        )
        return parent.program.traits()

    def _operator_offspring(
        self,
        *,
        parent: PolicyRecord,
        child_bug_id: int,
        donors: tuple[Donor, ...],
    ) -> IVTraits:
        if self.operator is None:
            raise RuntimeError("operator offspring requested without an operator")

        opportunity_id = self._proposal_budget_used
        event_seed = self._next_operator_event_seed()
        self._proposal_budget_used += 1
        request = ProposalRequest(
            experiment_id=self.experiment_id,
            replicate_id=self.replicate_id,
            opportunity_id=opportunity_id,
            birth_step=self._last_step.get(parent.bug_id, -1),
            parent_bug_id=parent.bug_id,
            child_bug_id=child_bug_id,
            parent=parent.program,
            operator_event_seed=event_seed,
            living_donors=donors,
        )

        # No broad catch belongs here. Cache integrity failures and trusted
        # operator contract violations are infrastructure errors and must stop
        # the run rather than masquerade as ordinary rejected proposals.
        proposal = self.operator.propose(request)
        if not isinstance(proposal, RawProposal):
            raise OperatorContractError("operator.propose must return RawProposal")
        if proposal.operator_id != self.operator.operator_id:
            raise OperatorContractError("proposal operator_id does not match operator")
        if proposal.operator_revision != self.operator.operator_revision:
            raise OperatorContractError(
                "proposal operator_revision does not match operator"
            )

        donor_program: str | None = None
        donor: Donor | None = None
        if proposal.donor_bug_id is not None:
            donor_by_id = {item.bug_id: item for item in donors}
            if proposal.donor_bug_id not in donor_by_id:
                raise OperatorContractError(
                    "proposal donor_bug_id is not in the prepared living donor pool"
                )
            donor = donor_by_id[proposal.donor_bug_id]
            donor_program = donor.program.to_json()

        decision = adjudicate_proposal(parent.program, proposal)
        delta = decision.delta
        if decision.accepted and proposal.provenance is ProposalProvenance.TRUSTED:
            if proposal.selected_path is None or delta is None:
                raise OperatorContractError(
                    "accepted trusted proposal must identify its changed path"
                )
            if delta.changed_paths != (proposal.selected_path,):
                raise OperatorContractError(
                    "proposal selected_path does not match the accepted edit"
                )
            if donor is not None and program_field_value(
                decision.program, proposal.selected_path
            ) != program_field_value(donor.program, proposal.selected_path):
                raise OperatorContractError(
                    "recombination proposal did not copy the recorded donor leaf"
                )
        changed_paths = (
            tuple(self._enum_text(path) or "" for path in delta.changed_paths)
            if delta is not None
            else ()
        )
        selected_path = self._enum_text(proposal.selected_path)
        provenance = self._enum_text(proposal.provenance)
        source_failure = self._enum_text(proposal.source_failure)
        status = self._enum_text(decision.status)
        if status is None:
            raise OperatorContractError("proposal decision is missing a status")

        raw_candidate = (
            None
            if proposal.raw_candidate is None
            else self._proposal_text(proposal.raw_candidate)
        )
        candidate_program = (
            decision.candidate.to_json()
            if decision.candidate is not None
            else None
        )
        reason = "accepted" if decision.accepted else status
        if proposal.failure_detail:
            reason = f"{reason}: {proposal.failure_detail}"

        self._register(
            PolicyRecord(
                bug_id=child_bug_id,
                parent_bug_id=parent.bug_id,
                birth_step=self._last_step.get(parent.bug_id, -1),
                program=decision.program,
                mutation_attempted=True,
                proposal_accepted=decision.accepted,
                proposal=raw_candidate,
                reason=reason,
                experiment_id=self.experiment_id,
                replicate_id=self.replicate_id,
                opportunity_id=opportunity_id,
                proposal_budget_cost=1,
                operator_event_seed=event_seed,
                operator_id=proposal.operator_id,
                operator_revision=proposal.operator_revision,
                proposal_provenance=provenance,
                proposal_status=status,
                source_failure=source_failure,
                failure_detail=proposal.failure_detail,
                selected_path=selected_path,
                donor_bug_id=proposal.donor_bug_id,
                donor_program=donor_program,
                cache_key=proposal.cache_key,
                parent_program=parent.program.to_json(),
                candidate_program=candidate_program,
                changed_paths=changed_paths,
                field_hamming=(delta.field_hamming if delta is not None else None),
                atomic_distance=(
                    delta.atomic_distance if delta is not None else None
                ),
                exact_parent_inheritance=decision.program is parent.program,
            )
        )
        return decision.program.traits()

    def offspring_traits(
        self,
        parent_bug_id: int,
        child_bug_id: int,
        base_traits: IVTraits,
    ) -> IVTraits:
        del base_traits
        try:
            parent = self.records[parent_bug_id]
        except KeyError as exc:
            raise RuntimeError(
                f"no parent controller record for bug {parent_bug_id}"
            ) from exc

        donors = self._birth_donors(parent_bug_id, child_bug_id)
        mutation_selected = bool(self.rng.random() < self.mutation_probability)
        if not mutation_selected:
            return self._register_inheritance(
                parent=parent,
                child_bug_id=child_bug_id,
                reason="inherited",
                status="inherited",
            )
        if not self._budget_available():
            return self._register_inheritance(
                parent=parent,
                child_bug_id=child_bug_id,
                reason="proposal budget exhausted",
                status="budget_exhausted",
            )
        if self.operator is not None:
            return self._operator_offspring(
                parent=parent,
                child_bug_id=child_bug_id,
                donors=donors,
            )

        opportunity_id = self._proposal_budget_used
        self._proposal_budget_used += 1
        program = parent.program
        accepted: bool | None = None
        proposal: str | None = None
        reason = "inherited"
        event_seed: int | None = None
        if self._proposal_stream_is_explicit:
            event_seed = self._next_operator_event_seed()
            roll = float(np.random.Generator(np.random.PCG64(event_seed)).random())
        else:
            # The default path is a frozen compatibility contract.  It draws
            # the legacy mutator roll from the original controller stream.
            roll = float(self.rng.random())
        context = {
            "roll": roll,
            "parent_bug_id": parent_bug_id,
            "child_bug_id": child_bug_id,
            "birth_step": self._last_step.get(parent_bug_id, -1),
        }
        if event_seed is not None:
            context["operator_event_seed"] = event_seed
            context["opportunity_id"] = opportunity_id
        try:
            candidate = self.mutator(parent.program, context)
            proposal = self._proposal_text(candidate)
            program = coerce_program(candidate)
            accepted = True
            reason = "accepted"
        except Exception as exc:
            # Legacy mutators are an untrusted compatibility boundary.
            # Rejection inherits once; there is no retry or ecological RNG use.
            program = parent.program
            accepted = False
            reason = f"{type(exc).__name__}: {exc}"

        self._register(
            PolicyRecord(
                bug_id=child_bug_id,
                parent_bug_id=parent_bug_id,
                birth_step=self._last_step.get(parent_bug_id, -1),
                program=program,
                mutation_attempted=True,
                proposal_accepted=accepted,
                proposal=proposal,
                reason=reason,
                experiment_id=self.experiment_id,
                replicate_id=self.replicate_id,
                opportunity_id=opportunity_id,
                proposal_budget_cost=1,
                operator_event_seed=event_seed,
                operator_id="legacy_mutator",
                operator_revision="v1",
                proposal_provenance="legacy",
                proposal_status=(
                    "legacy_accepted" if accepted else "legacy_invalid_candidate"
                ),
                parent_program=parent.program.to_json(),
                candidate_program=(program.to_json() if accepted else None),
                exact_parent_inheritance=program is parent.program,
            )
        )
        return program.traits()

    def program_for(self, bug_id: int) -> IVProgram:
        return self.records[bug_id].program

    def record_payload(self) -> list[dict[str, object]]:
        return [self.records[bug_id].to_dict() for bug_id in sorted(self.records)]

    @property
    def mutation_attempts(self) -> int:
        return sum(record.mutation_attempted for record in self.records.values())

    @property
    def accepted_proposals(self) -> int:
        return sum(
            record.proposal_accepted is True for record in self.records.values()
        )

    @property
    def rejected_proposals(self) -> int:
        return sum(
            record.proposal_accepted is False for record in self.records.values()
        )

    @property
    def proposal_budget_used(self) -> int:
        """Number of one-candidate proposal opportunities consumed."""
        return self._proposal_budget_used

    @property
    def proposal_budget_remaining(self) -> int | None:
        """Remaining proposal opportunities, or ``None`` when uncapped."""
        if self.proposal_budget is None:
            return None
        return self.proposal_budget - self._proposal_budget_used


def build_controlled_sim(
    config: MetabolicConfig,
    *,
    controller_seed: int,
    mutator: ProgramMutator = heuristic_mutate_iv_program,
    mutation_probability: float | None = None,
    programs: Sequence[IVProgram | str] = DEFAULT_IV_PROGRAMS,
    proposal_seed: int | None = None,
    proposal_budget: int | None = None,
    experiment_id: str = "iv-controller",
    replicate_id: str = "default",
    operator: VariationOperator | None = None,
    random_streams: EcologyRandomStreams | None = None,
) -> tuple[MetabolicSim, IVProgramController]:
    """Construct controller and physics together so seed traits precede intake."""
    controller = IVProgramController(
        seed=controller_seed,
        mutation_probability=(
            config.mut_prob
            if mutation_probability is None
            else mutation_probability
        ),
        programs=programs,
        mutator=mutator,
        proposal_seed=proposal_seed,
        proposal_budget=proposal_budget,
        experiment_id=experiment_id,
        replicate_id=replicate_id,
        operator=operator,
    )
    return (
        MetabolicSim(
            config,
            controller=controller,
            random_streams=random_streams,
        ),
        controller,
    )


def unique_policies(sim: MetabolicSim) -> list[str]:
    """Return canonical executable programs among living organisms."""
    controller = sim.controller
    if not isinstance(controller, IVProgramController):
        return []
    seen: list[str] = []
    for bug in sim.bugs:
        if not bug.alive:
            continue
        policy = controller.program_for(bug.bug_id).to_json()
        if policy not in seen:
            seen.append(policy)
    return seen


def main() -> None:
    config = MetabolicConfig(
        steps=220,
        n_organisms=36,
        n_places=96,
        max_organisms=90,
        harvest=5,
        seed=2026,
        construction=True,
        verbose_every=40,
    )
    sim, controller = build_controlled_sim(
        config,
        controller_seed=2026001,
    )
    print(f"IV typed-controller pilot | initial conserved: {sim.conserved()}")
    print(f"seed programs: {len(unique_policies(sim))}")
    sim.run()
    print(f"IV typed-controller pilot | final conserved:   {sim.conserved()}")
    last = sim.history[-1]
    print(
        f"{last.n_alive} alive, P/R={last.n_producers}/{last.n_recyclers}, "
        f"cross-type contact={last.niche_index:.2f}"
    )
    print(
        f"programs={len(unique_policies(sim))}, "
        f"proposals={controller.mutation_attempts}, "
        f"accepted={controller.accepted_proposals}, "
        f"rejected={controller.rejected_proposals}"
    )
    print("Integration pilot only; no historical, niche, or LLM claim.")


if __name__ == "__main__":
    main()
