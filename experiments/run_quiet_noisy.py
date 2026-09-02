#!/usr/bin/env python3
"""Quiet versus noisy reconstruction diagnostic.

Quiet world: abiotic A/B patches never flip.
Noisy world: each place independently flips state with probability p each step.

The historical observations motivate this comparison, but the current
mechanisms and metrics are reconstruction choices rather than a replication.

This script reruns that contrast. Matching is not a fitness function
handed to the organisms; it is a consequence of harvest. An organism
whose preferred abiotic bit (genome[0] % 2) equals the place it is
standing on takes two extra chips. Selection is still chip bookkeeping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve1970.simulation import Simulation, SimulationConfig


SEEDS = (1970, 1971, 1985, 2026)
STEPS = 280
NOISE = 0.10  # fraction of places that flip each step in the noisy world


def window_mean(history, attr: str, start: int, end: int) -> float:
    sl = history[start:end]
    if not sl:
        return 0.0
    return sum(getattr(s, attr) for s in sl) / len(sl)


def run_one(seed: int, flip_prob: float) -> dict:
    sim = Simulation(
        SimulationConfig(
            steps=STEPS,
            n_organisms=80,
            n_places=48,
            total_chips=4000,
            seed=seed,
            abiotic_flip_prob=flip_prob,
            match_bonus=True,
            verbose_every=0,
        )
    )
    start_chips = sim.conserved_chips()
    sim.run()
    end_chips = sim.conserved_chips()
    h = sim.history
    early_end = min(30, len(h))
    late_start = max(0, len(h) - 30)
    last = h[-1]
    return {
        "seed": seed,
        "flip_prob": flip_prob,
        "conservation_ok": start_chips == end_chips == 4000,
        "n_alive_final": last.n_alive,
        "n_genotype_signatures_final": last.n_genotype_signatures,
        "match_early": window_mean(h, "match_ratio", 0, early_end),
        "match_late": window_mean(h, "match_ratio", late_start, len(h)),
        "match_w_early": window_mean(h, "match_weighted", 0, early_end),
        "match_w_late": window_mean(h, "match_weighted", late_start, len(h)),
        "diversity_early": window_mean(h, "shannon_diversity", 0, early_end),
        "diversity_late": window_mean(h, "shannon_diversity", late_start, len(h)),
        "genotype_signatures_early": window_mean(
            h, "n_genotype_signatures", 0, early_end
        ),
        "genotype_signatures_late": window_mean(
            h, "n_genotype_signatures", late_start, len(h)
        ),
        "chips_in_bodies_early": window_mean(h, "chips_bodies", 0, early_end),
        "chips_in_bodies_late": window_mean(
            h, "chips_bodies", late_start, len(h)
        ),
        "repeated_actions_late": window_mean(
            h, "repeated_action_fraction", late_start, len(h)
        ),
        "mean_flips": window_mean(h, "abiotic_flips", 0, len(h)),
    }


def mean(rows: list[dict], key: str) -> float:
    return sum(r[key] for r in rows) / max(1, len(rows))


def main() -> None:
    quiet = [run_one(seed, 0.0) for seed in SEEDS]
    noisy = [run_one(seed, NOISE) for seed in SEEDS]
    payload = {"quiet": quiet, "noisy": noisy, "noise_p": NOISE, "steps": STEPS}
    print(json.dumps(payload, indent=2))

    print("\n" + "=" * 64)
    print("Quiet versus noisy reconstruction diagnostic")
    print("=" * 64)
    print(f"{'':18} {'quiet':>12} {'noisy':>12} {'delta':>12}")
    rows = [
        ("match early", "match_early"),
        ("match late", "match_late"),
        ("weighted match early", "match_w_early"),
        ("weighted match late", "match_w_late"),
        ("diversity early", "diversity_early"),
        ("diversity late", "diversity_late"),
        ("genotype types", "n_genotype_signatures_final"),
        ("chips in bodies late", "chips_in_bodies_late"),
        ("repeated actions", "repeated_actions_late"),
        ("alive final", "n_alive_final"),
    ]
    for label, key in rows:
        q = mean(quiet, key)
        n = mean(noisy, key)
        print(f"{label:18} {q:12.3f} {n:12.3f} {n - q:+12.3f}")

    q_gain = mean(quiet, "match_late") - mean(quiet, "match_early")
    n_gain = mean(noisy, "match_late") - mean(noisy, "match_early")
    qw = mean(quiet, "match_w_late") - mean(quiet, "match_w_early")
    nw = mean(noisy, "match_w_late") - mean(noisy, "match_w_early")
    print()
    print(f"match gain (late-early)            quiet={q_gain:+.3f}   noisy={n_gain:+.3f}")
    print(f"weighted match gain (late-early)   quiet={qw:+.3f}   noisy={nw:+.3f}")
    print(
        "conservation held:",
        all(r["conservation_ok"] for r in quiet + noisy),
    )
    print()
    print("Historical hypotheses motivating this diagnostic:")
    print("  matching should rise more in the quiet world;")
    print("  noisy worlds should sustain continuing type turnover.")
    print("These four seeds do not establish either historical claim.")


if __name__ == "__main__":
    main()
