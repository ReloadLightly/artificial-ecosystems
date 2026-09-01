#!/usr/bin/env python3
"""EVOLVE IV — metabolite exchange vs exchange + niche construction.

Two densities. On a packed ring everyone already has an opposite
neighbour, so the metabolic-niche index saturates. On a sparse ring
there is room not to sort — and construction is what makes them sort.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.simulation import MetabolicSim, MetabolicConfig


def window_mean(history, attr, start, end):
    sl = history[start:end]
    return sum(getattr(s, attr) for s in sl) / max(1, len(sl))


WORLDS = {
    "dense": dict(n_places=48, n_organisms=80, max_organisms=280, harvest=4),
    "sparse": dict(n_places=96, n_organisms=36, max_organisms=90, harvest=5),
}


def run_one(seed: int, construction: bool, world: str) -> dict:
    sim = MetabolicSim(
        MetabolicConfig(
            steps=220,
            seed=seed,
            construction=construction,
            verbose_every=0,
            **WORLDS[world],
        )
    )
    start = sim.conserved()
    sim.run()
    end = sim.conserved()
    h = sim.history
    last = h[-1]
    return {
        "seed": seed,
        "world": world,
        "construction": construction,
        "conservation_ok": start == end == 4000,
        "producers_late": window_mean(h, "n_producers", len(h) - 40, len(h)),
        "recyclers_late": window_mean(h, "n_recyclers", len(h) - 40, len(h)),
        "niche_early": window_mean(h, "niche_index", 0, 30),
        "niche_late": window_mean(h, "niche_index", len(h) - 40, len(h)),
        "cmatch_late": window_mean(h, "construct_match", len(h) - 40, len(h)),
        "cvar_late": window_mean(h, "condition_var", len(h) - 40, len(h)),
        "alive_final": last.n_alive,
    }


def mean(rows, key):
    return sum(r[key] for r in rows) / max(1, len(rows))


def block(label: str, rows: list[dict]) -> None:
    print(f"\n{label}")
    print(f"{'':24} {'value':>10}")
    for name, key in [
        ("producers late", "producers_late"),
        ("recyclers late", "recyclers_late"),
        ("niche early", "niche_early"),
        ("niche late", "niche_late"),
        ("construct-match late", "cmatch_late"),
        ("condition var late", "cvar_late"),
        ("alive final", "alive_final"),
    ]:
        print(f"{name:24} {mean(rows, key):10.3f}")
    print("conservation", all(r["conservation_ok"] for r in rows))


def main() -> None:
    seeds = (1998, 1999, 1970, 2026)
    results = {}
    for world in WORLDS:
        for construction in (False, True):
            key = f"{world}_{'construct' if construction else 'flat'}"
            results[key] = [run_one(s, construction, world) for s in seeds]
    print(json.dumps(results, indent=2))
    block("dense / exchange only", results["dense_flat"])
    block("dense / exchange + construction", results["dense_construct"])
    block("sparse / exchange only", results["sparse_flat"])
    block("sparse / exchange + construction", results["sparse_construct"])
    print()
    print("On a packed ring the metabolic-niche index saturates either way.")
    print("On a sparse ring construction is what sorts producers next to")
    print("recyclers — the 1999 claim, in miniature.")


if __name__ == "__main__":
    main()
