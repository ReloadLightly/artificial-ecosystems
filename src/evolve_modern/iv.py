"""EVOLVE IV physics with a language policy as the variation operator.

Usage:
    PYTHONPATH=src python3 -m evolve_modern.iv
"""

from __future__ import annotations

from evolve4.simulation import MetabolicSim, MetabolicConfig
from evolve_modern.iv_policies import (
    DEFAULT_IV_POLICIES,
    compile_traits,
    heuristic_mutate_iv_policy,
    interpret_iv_policy,
)


def attach_language(sim: MetabolicSim, mutator=None) -> MetabolicSim:
    """Hang a text policy on every living bug. Physics unchanged."""
    sim.cfg.language = True
    sim.decide = lambda bug, percept: interpret_iv_policy(bug.policy or "", percept)
    sim.policy_mutator = mutator or heuristic_mutate_iv_policy
    sim.compile_traits = compile_traits
    for i, bug in enumerate(sim.bugs):
        if not bug.alive:
            continue
        if not bug.policy:
            bug.policy = DEFAULT_IV_POLICIES[i % len(DEFAULT_IV_POLICIES)]
        producer, taste, construct = compile_traits(bug.policy, bug)
        bug.producer = producer
        bug.taste = taste
        bug.construct = construct
    return sim


def unique_policies(sim: MetabolicSim) -> list[str]:
    seen: list[str] = []
    for b in sim.bugs:
        if not b.alive or not b.policy:
            continue
        if b.policy not in seen:
            seen.append(b.policy)
    return seen


def main() -> None:
    sim = MetabolicSim(
        MetabolicConfig(
            steps=220,
            n_organisms=36,
            n_places=96,
            max_organisms=90,
            harvest=5,
            seed=2026,
            construction=True,
            language=True,
            verbose_every=40,
        )
    )
    attach_language(sim)
    print(f"IV + language | initial conserved: {sim.conserved()}")
    print(f"seed policies: {len(unique_policies(sim))}")
    sim.run()
    print(f"IV + language | final conserved:   {sim.conserved()}")
    last = sim.history[-1]
    print(
        f"{last.n_alive} alive, P/R={last.n_producers}/{last.n_recyclers}, "
        f"niche={last.niche_index:.2f}"
    )
    print("surviving policies:")
    for p in unique_policies(sim)[:8]:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
