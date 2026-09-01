"""Run the 1970 physics with language-policy controllers instead of genomes.

Usage:
    python -m evolve_modern
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evolve1970.simulation import Simulation, SimulationConfig
from evolve_modern.agents import DEFAULT_POLICIES, heuristic_mutate_policy, interpret_policy


class PolicySimulation(Simulation):
    """Same world, same chips; action choice reads a text policy."""

    def __init__(self, config: SimulationConfig | None = None):
        super().__init__(config)
        for i, org in enumerate(self.organisms):
            org.policy = DEFAULT_POLICIES[i % len(DEFAULT_POLICIES)]  # type: ignore[attr-defined]

    def step(self):
        living = [o for o in self.organisms if o.alive]
        occupants = {}
        for o in living:
            occupants.setdefault(o.position, []).append(o)

        for org in living:
            if not hasattr(org, "policy"):
                continue
            view = self.world.local_view(org.position, org.territory)
            percept = {
                "chips_here": self.world.places[org.position].chips,
                "local_chips": view["total_chips"],
                "stored": org.stored_chips,
                "age": org.age,
                "n_neighbors": sum(
                    len(occupants.get(i, [])) for i in view["indices"]
                )
                - 1,
                "repro_threshold": org.reproduction_threshold(),
            }
            action_name = interpret_policy(org.policy, percept)  # type: ignore[attr-defined]
            action_id = {
                "collect": 0,
                "forage": 1,
                "cooperate": 2,
                "repair": 3,
                "reproduce": 4,
                "wait": 5,
            }[action_name]

            def make_next(aid: int):
                def _next(_input_state: int) -> int:
                    return aid

                return _next

            org.next_action = make_next(action_id)  # type: ignore[method-assign]

        stats = super().step()

        for org in self.organisms:
            if org.alive and not hasattr(org, "policy"):
                parent = next(
                    (p for p in self.organisms if p.organism_id == org.parent_id),
                    None,
                )
                base = (
                    parent.policy
                    if parent and hasattr(parent, "policy")
                    else DEFAULT_POLICIES[0]
                )
                org.policy = heuristic_mutate_policy(base, float(self.rng.random()))
        return stats


def main() -> None:
    sim = PolicySimulation(
        SimulationConfig(
            steps=200,
            n_organisms=60,
            n_places=40,
            total_chips=3000,
            seed=2026,
            verbose_every=25,
        )
    )
    print(f"Modern overlay | initial conserved chips: {sim.conserved_chips()}")
    sim.run()
    print(f"Modern overlay | final conserved chips:   {sim.conserved_chips()}")
    alive = [o for o in sim.organisms if o.alive]
    print(f"{len(alive)} organisms remain.")
    seen = []
    for o in alive:
        p = getattr(o, "policy", None)
        if p and p not in seen:
            seen.append(p)
        if len(seen) >= 5:
            break
    print("Sample surviving policies:")
    for p in seen:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
