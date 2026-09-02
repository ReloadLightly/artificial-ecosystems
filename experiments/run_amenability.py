#!/usr/bin/env python3
"""EVOLVE-inspired mutation-control locus diagnostic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve1970.simulation import Simulation, SimulationConfig

SEEDS = (1970, 1971, 1985, 2026)
STEPS = 300
CONDITIONS = (("static", 0.0), ("iid-0.02", 0.02), ("iid-0.15", 0.15))


def window_mean(history, attr, start, end):
    sample = history[start:end]
    return sum(getattr(row, attr) for row in sample) / max(1, len(sample))


def run_one(seed, flip_probability):
    sim = Simulation(
        SimulationConfig(
            steps=STEPS,
            n_organisms=80,
            n_places=48,
            total_chips=4000,
            seed=seed,
            abiotic_flip_prob=flip_probability,
            match_bonus=True,
            modifier_enabled=True,
            verbose_every=0,
        )
    )
    start = sim.conserved_chips()
    sim.run()
    history = sim.history
    alive = [organism for organism in sim.organisms if organism.alive]
    if alive:
        by_store = sorted(alive, key=lambda organism: organism.stored_chips)
        quartile_size = max(1, len(by_store) // 4)
        mutation_control_top_store = (
            sum(
                organism.amenability
                for organism in by_store[-quartile_size:]
            )
            / quartile_size
        )
        mutation_control_bottom_store = (
            sum(
                organism.amenability for organism in by_store[:quartile_size]
            )
            / quartile_size
        )
    else:
        mutation_control_top_store = None
        mutation_control_bottom_store = None
    last = history[-1]
    late_start = max(0, len(history) - 30)
    extinct_final = last.n_alive == 0
    return {
        "seed": seed,
        "flip_probability": flip_probability,
        "conservation_ok": start == sim.conserved_chips() == 4000,
        "extinct_final": extinct_final,
        "mutation_control_early": window_mean(
            history, "mean_amenability_proxy", 0, 30
        ),
        "mutation_control_late": (
            None
            if extinct_final
            else window_mean(
                history,
                "mean_amenability_proxy",
                late_start,
                len(history),
            )
        ),
        "mutation_control_top_store": mutation_control_top_store,
        "mutation_control_bottom_store": mutation_control_bottom_store,
        "match_late": (
            None
            if extinct_final
            else window_mean(history, "match_ratio", late_start, len(history))
        ),
        "diversity_late": (
            None
            if extinct_final
            else window_mean(
                history,
                "shannon_diversity",
                late_start,
                len(history),
            )
        ),
        "n_alive_final": last.n_alive,
        "n_genotype_signatures_final": last.n_genotype_signatures,
    }


def mean(rows, key):
    observed = [row[key] for row in rows if row[key] is not None]
    return sum(observed) / len(observed) if observed else float("nan")


def paired_mean_change(rows, early_key, late_key):
    observed = [
        row[late_key] - row[early_key]
        for row in rows
        if row[late_key] is not None
    ]
    return sum(observed) / len(observed) if observed else float("nan")


def main():
    grouped = {
        name: [run_one(seed, probability) for seed in SEEDS]
        for name, probability in CONDITIONS
    }
    print(json.dumps(grouped, indent=2))
    print("\nEVOLVE-inspired mutation-control diagnostic")
    print(f"{'':28}" + "".join(f"{name:>12}" for name, _ in CONDITIONS))
    for label, key in [
        ("mutation control early", "mutation_control_early"),
        ("mutation control late", "mutation_control_late"),
        ("top-store control", "mutation_control_top_store"),
        ("match late", "match_late"),
        ("genotype entropy late", "diversity_late"),
    ]:
        line = f"{label:28}"
        for name, _ in CONDITIONS:
            line += f"{mean(grouped[name], key):12.3f}"
        print(line)
    print("descriptive paired mutation-control change among surviving runs")
    for name, _ in CONDITIONS:
        change = paired_mean_change(
            grouped[name],
            "mutation_control_early",
            "mutation_control_late",
        )
        print(f"  {name:10} {change:+.4f}")
    print(
        "final extinctions",
        " ".join(
            f"{name}={sum(row['extinct_final'] for row in grouped[name])}"
            for name, _ in CONDITIONS
        ),
    )
    print(
        "conservation",
        all(
            row["conservation_ok"]
            for rows in grouped.values()
            for row in rows
        ),
    )
    print(
        "Interpretation: this is a custom mutation-control locus under static "
        "or IID environmental flips. It is not evidence of canalization or "
        "selection for evolvability."
    )


if __name__ == "__main__":
    main()
