#!/usr/bin/env python3
"""Amenability to evolution — Conrad & Rizki (1980), EVOLVE II (1985)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve1970.simulation import Simulation, SimulationConfig

SEEDS = (1970, 1971, 1985, 2026)
STEPS = 300
CONDITIONS = (("still", 0.0), ("slow", 0.02), ("fast", 0.15))


def window_mean(history, attr, start, end):
    sl = history[start:end]
    return sum(getattr(s, attr) for s in sl) / max(1, len(sl))


def run_one(seed, flip_prob):
    sim = Simulation(SimulationConfig(steps=STEPS, n_organisms=80, n_places=48, total_chips=4000, seed=seed, abiotic_flip_prob=flip_prob, match_bonus=True, verbose_every=0))
    start = sim.conserved_chips()
    sim.run()
    h = sim.history
    alive = [o for o in sim.organisms if o.alive]
    if alive:
        by_store = sorted(alive, key=lambda o: o.stored_chips)
        nq = max(1, len(by_store) // 4)
        amen_rich = sum(o.amenability for o in by_store[-nq:]) / nq
        amen_poor = sum(o.amenability for o in by_store[:nq]) / nq
    else:
        amen_rich = amen_poor = 0.0
    last = h[-1]
    return {
        "seed": seed,
        "flip_prob": flip_prob,
        "conservation_ok": start == sim.conserved_chips() == 4000,
        "amen_early": window_mean(h, "mean_amenability", 0, 30),
        "amen_late": window_mean(h, "mean_amenability", len(h) - 30, len(h)),
        "amen_rich": amen_rich,
        "amen_poor": amen_poor,
        "match_late": window_mean(h, "match_ratio", len(h) - 30, len(h)),
        "diversity_late": window_mean(h, "shannon_diversity", len(h) - 30, len(h)),
        "n_alive_final": last.n_alive,
        "n_lineages_final": last.n_lineages,
    }


def mean(rows, key):
    return sum(r[key] for r in rows) / max(1, len(rows))


def main():
    grouped = {name: [run_one(seed, p) for seed in SEEDS] for name, p in CONDITIONS}
    print(json.dumps(grouped, indent=2))
    print("\nAmenability — still / slow / fast")
    print(f"{'':20}" + "".join(f"{n:>12}" for n, _ in CONDITIONS))
    for label, key in [
        ("amen early", "amen_early"),
        ("amen late", "amen_late"),
        ("amen rich", "amen_rich"),
        ("match late", "match_late"),
        ("diversity late", "diversity_late"),
    ]:
        line = f"{label:20}"
        for name, _ in CONDITIONS:
            line += f"{mean(grouped[name], key):12.3f}"
        print(line)
    print("amenability gain")
    for name, _ in CONDITIONS:
        print(f"  {name:8} {mean(grouped[name], 'amen_late') - mean(grouped[name], 'amen_early'):+.4f}")
    print("conservation", all(r["conservation_ok"] for rows in grouped.values() for r in rows))


if __name__ == "__main__":
    main()
