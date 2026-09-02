#!/usr/bin/env python3
"""Conserved-chip prototype smoke run and descriptive telemetry.

This script does not test all five historical observations. In particular,
recombination propensity is not heritable in the present implementation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve1970.simulation import Simulation, SimulationConfig


def run(seed: int, steps: int = 250) -> dict:
    sim = Simulation(
        SimulationConfig(
            steps=steps,
            n_organisms=80,
            n_places=48,
            total_chips=4000,
            seed=seed,
            verbose_every=0,
        )
    )
    start = sim.conserved_chips()
    sim.run()
    end = sim.conserved_chips()
    h = sim.history
    early = h[:20]
    late = h[-20:]
    return {
        "seed": seed,
        "conserved_start": start,
        "conserved_end": end,
        "conservation_ok": start == end,
        "n_alive_final": late[-1].n_alive if late else 0,
        "n_genotype_signatures_final": (
            late[-1].n_genotype_signatures if late else 0
        ),
        "mean_coop_early": sum(s.cooperations for s in early) / max(1, len(early)),
        "mean_coop_late": sum(s.cooperations for s in late) / max(1, len(late)),
        "mean_genome_early": sum(s.mean_genome_len for s in early) / max(1, len(early)),
        "mean_genome_late": sum(s.mean_genome_len for s in late) / max(1, len(late)),
        "chips_in_bodies_early": sum(s.chips_bodies for s in early)
        / max(1, len(early)),
        "chips_in_bodies_late": sum(s.chips_bodies for s in late)
        / max(1, len(late)),
        "final_action_hist": late[-1].action_hist if late else {},
    }


def main() -> None:
    results = [run(seed) for seed in (1970, 1971, 2026)]
    print(json.dumps(results, indent=2))
    print("\nConservation held in every run:", all(r["conservation_ok"] for r in results))


if __name__ == "__main__":
    main()
