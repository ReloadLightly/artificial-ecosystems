#!/usr/bin/env python3
"""Program repetition and position-level execution coverage diagnostic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve1970.organism import ACTION_NAMES, decode_program, random_genome
from evolve1970.simulation import Simulation, SimulationConfig

SEEDS = (1970, 1971, 1985, 2026)
STEPS = 280


def window_mean(history, attr, start, end):
    sample = history[start:end]
    return sum(getattr(row, attr) for row in sample) / max(1, len(sample))


def mean_for(organisms, measure):
    return sum(measure(organism) for organism in organisms) / max(
        1, len(organisms)
    )


def random_repetition_baseline(n=400, length=12):
    import numpy as np

    rng = np.random.default_rng(0)
    values = []
    for _ in range(n):
        program = decode_program(random_genome(rng, length=length))
        values.append(1.0 - len(set(program)) / len(program))
    return float(sum(values) / len(values))


def snapshot(sim):
    alive = [organism for organism in sim.organisms if organism.alive]
    if not alive:
        return {"n_alive": 0}

    by_store = sorted(alive, key=lambda organism: organism.stored_chips)
    quartile_size = max(1, len(by_store) // 4)
    bottom_store = by_store[:quartile_size]
    top_store = by_store[-quartile_size:]
    exposure_qualified = [
        organism
        for organism in alive
        if organism.decision_count >= 2 * len(organism.program)
    ]
    example = max(top_store, key=lambda organism: organism.stored_chips)
    example_program = [
        f"{slot}:{ACTION_NAMES[action]}"
        for slot, action in enumerate(example.program)
    ]
    example_executed = [
        f"{slot}:{ACTION_NAMES[example.program[slot]]}"
        for slot in sorted(example.executed_slots)
    ]

    return {
        "n_alive": len(alive),
        "repetition_all": mean_for(
            alive, lambda organism: organism.repeated_action_slot_fraction()
        ),
        "repetition_top_store": mean_for(
            top_store, lambda organism: organism.repeated_action_slot_fraction()
        ),
        "repetition_bottom_store": mean_for(
            bottom_store,
            lambda organism: organism.repeated_action_slot_fraction(),
        ),
        "unexecuted_all": mean_for(
            alive, lambda organism: organism.unexecuted_slot_fraction()
        ),
        "unexecuted_top_store": mean_for(
            top_store, lambda organism: organism.unexecuted_slot_fraction()
        ),
        "unexecuted_bottom_store": mean_for(
            bottom_store, lambda organism: organism.unexecuted_slot_fraction()
        ),
        "exposure_qualified_n": len(exposure_qualified),
        "unexecuted_exposure_qualified": mean_for(
            exposure_qualified,
            lambda organism: organism.unexecuted_slot_fraction(),
        ),
        "mean_decisions": mean_for(
            alive, lambda organism: organism.decision_count
        ),
        "example_program": example_program,
        "example_executed_slots": example_executed,
        "example_stored": example.stored_chips,
        "example_decisions": example.decision_count,
        "example_repetition": example.repeated_action_slot_fraction(),
        "example_unexecuted": example.unexecuted_slot_fraction(),
    }


def run_one(seed):
    sim = Simulation(
        SimulationConfig(
            steps=STEPS,
            n_organisms=80,
            n_places=48,
            total_chips=4000,
            seed=seed,
            match_bonus=True,
            verbose_every=0,
        )
    )
    start = sim.conserved_chips()
    sim.run()
    history = sim.history
    late_start = max(0, len(history) - 30)
    return {
        "seed": seed,
        "conservation_ok": start == sim.conserved_chips() == 4000,
        "repetition_early": window_mean(
            history, "repeated_action_fraction", 0, 30
        ),
        "repetition_late": window_mean(
            history, "repeated_action_fraction", late_start, len(history)
        ),
        "unexecuted_early": window_mean(
            history, "mean_unexecuted_slot_fraction", 0, 30
        ),
        "unexecuted_late": window_mean(
            history,
            "mean_unexecuted_slot_fraction",
            late_start,
            len(history),
        ),
        "decisions_early": window_mean(
            history, "mean_decision_count", 0, 30
        ),
        "decisions_late": window_mean(
            history, "mean_decision_count", late_start, len(history)
        ),
        "genome_length_early": window_mean(
            history, "mean_genome_len", 0, 30
        ),
        "genome_length_late": window_mean(
            history, "mean_genome_len", late_start, len(history)
        ),
        "final": snapshot(sim),
    }


def mean(rows, key):
    return sum(row[key] for row in rows) / max(1, len(rows))


def main():
    results = [run_one(seed) for seed in SEEDS]
    baseline = random_repetition_baseline()
    print(
        json.dumps(
            {"random_repetition_baseline": baseline, "runs": results},
            indent=2,
        )
    )
    print("\nProgram repetition and execution coverage diagnostic")
    print(f"random-genome repetition baseline: {baseline:.3f}")
    for label, early_key, late_key in [
        ("repeated-action slots", "repetition_early", "repetition_late"),
        ("unexecuted positions", "unexecuted_early", "unexecuted_late"),
        ("mean decisions", "decisions_early", "decisions_late"),
    ]:
        early = mean(results, early_key)
        late = mean(results, late_key)
        print(
            f"{label:24} {early:.3f} -> {late:.3f} "
            f"({late - early:+.3f})"
        )

    finals = [row["final"] for row in results]
    top = mean(finals, "unexecuted_top_store")
    bottom = mean(finals, "unexecuted_bottom_store")
    print(
        f"final unexecuted positions: top-store={top:.3f} "
        f"bottom-store={bottom:.3f}"
    )
    print("conservation", all(row["conservation_ok"] for row in results))
    for row in results:
        final = row["final"]
        if final.get("n_alive"):
            print(
                f"  seed {row['seed']}: program={final['example_program']} "
                f"executed={final['example_executed_slots']}"
            )
    print(
        "Conclusion: this pilot measures repetition and lifetime execution "
        "coverage. It does not establish selectively neutral or historically "
        "unexecuted sequence."
    )


if __name__ == "__main__":
    main()
