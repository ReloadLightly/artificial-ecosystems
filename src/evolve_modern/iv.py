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
from evolve4.simulation import MetabolicConfig, MetabolicSim
from evolve_modern.iv_policies import (
    DEFAULT_IV_PROGRAMS,
    IVProgram,
    coerce_program,
    decide_program,
    heuristic_mutate_iv_program,
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
    ):
        if not 0.0 <= mutation_probability <= 1.0:
            raise ValueError("mutation_probability must be between 0 and 1")
        typed_programs = tuple(coerce_program(program) for program in programs)
        if not typed_programs:
            raise ValueError("at least one initial IV program is required")
        if not callable(mutator):
            raise TypeError("mutator must be callable")

        self.seed = int(seed)
        self.mutation_probability = float(mutation_probability)
        self.programs = typed_programs
        self.mutator = mutator
        self.rng = np.random.default_rng(self.seed)
        self.records: dict[int, PolicyRecord] = {}
        self._last_step: dict[int, int] = {}

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

    @staticmethod
    def _proposal_text(candidate: object) -> str:
        if isinstance(candidate, IVProgram):
            return candidate.to_json()
        if type(candidate) is str:
            return candidate
        return repr(candidate)

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

        program = parent.program
        attempted = bool(self.rng.random() < self.mutation_probability)
        accepted: bool | None = None
        proposal: str | None = None
        reason = "inherited"

        if attempted:
            context = {
                "roll": float(self.rng.random()),
                "parent_bug_id": parent_bug_id,
                "child_bug_id": child_bug_id,
                "birth_step": self._last_step.get(parent_bug_id, -1),
            }
            try:
                candidate = self.mutator(parent.program, context)
                proposal = self._proposal_text(candidate)
                program = coerce_program(candidate)
                accepted = True
                reason = "accepted"
            except Exception as exc:
                # A proposal is untrusted data. Rejection inherits the exact
                # parent program and never retries or touches ecological RNG.
                program = parent.program
                accepted = False
                reason = f"{type(exc).__name__}: {exc}"

        self._register(
            PolicyRecord(
                bug_id=child_bug_id,
                parent_bug_id=parent_bug_id,
                birth_step=self._last_step.get(parent_bug_id, -1),
                program=program,
                mutation_attempted=attempted,
                proposal_accepted=accepted,
                proposal=proposal,
                reason=reason,
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


def build_controlled_sim(
    config: MetabolicConfig,
    *,
    controller_seed: int,
    mutator: ProgramMutator = heuristic_mutate_iv_program,
    mutation_probability: float | None = None,
    programs: Sequence[IVProgram | str] = DEFAULT_IV_PROGRAMS,
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
    )
    return MetabolicSim(config, controller=controller), controller


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
