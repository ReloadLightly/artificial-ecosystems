#!/usr/bin/env python3
"""Offline typed-controller integration pilot on EVOLVE IV-inspired physics.

The filename is retained for continuity with the withdrawn language prototype.
No natural-language policy or model call executes in this repair stage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.simulation import MetabolicConfig, MetabolicSim
from evolve_modern.iv import build_controlled_sim, unique_policies


SEEDS = (1998, 1999, 1970, 2026)
STEPS = 200


def window_mean(history, attr, start, end):
    sample = history[start:end]
    return sum(getattr(row, attr) for row in sample) / max(1, len(sample))


def run_one(seed: int, controlled: bool) -> dict:
    config = MetabolicConfig(
        steps=STEPS,
        n_places=96,
        n_organisms=36,
        max_organisms=90,
        harvest=5,
        seed=seed,
        construction=True,
        verbose_every=0,
    )
    controller = None
    if controlled:
        sim, controller = build_controlled_sim(
            config,
            controller_seed=1_000_003 + seed,
        )
    else:
        sim = MetabolicSim(config)

    start = sim.conserved()
    sim.run()
    end = sim.conserved()
    history = sim.history
    last = history[-1]
    late_start = max(0, len(history) - 40)
    policies = unique_policies(sim) if controlled else []
    return {
        "seed": seed,
        "arm": "typed-controller" if controlled else "native",
        "controller_seed": (1_000_003 + seed) if controlled else None,
        "conservation_ok": start == end == config.total_units,
        "producers_late": window_mean(
            history, "n_producers", late_start, len(history)
        ),
        "recyclers_late": window_mean(
            history, "n_recyclers", late_start, len(history)
        ),
        "cross_type_contact_early": window_mean(
            history, "niche_index", 0, 30
        ),
        "cross_type_contact_late": window_mean(
            history, "niche_index", late_start, len(history)
        ),
        "construct_match_late": window_mean(
            history, "construct_match", late_start, len(history)
        ),
        "condition_variance_late": window_mean(
            history, "condition_var", late_start, len(history)
        ),
        "alive_final": last.n_alive,
        "n_executable_programs": len(policies),
        "mutation_attempts": (
            controller.mutation_attempts if controller is not None else 0
        ),
        "accepted_proposals": (
            controller.accepted_proposals if controller is not None else 0
        ),
        "rejected_proposals": (
            controller.rejected_proposals if controller is not None else 0
        ),
    }


def mean(rows, key):
    return sum(row[key] for row in rows) / max(1, len(rows))


def block(label: str, rows: list[dict]) -> None:
    print(f"\n{label}")
    print(f"{'':28} {'value':>10}")
    for name, key in [
        ("producers late", "producers_late"),
        ("recyclers late", "recyclers_late"),
        ("cross-type contact early", "cross_type_contact_early"),
        ("cross-type contact late", "cross_type_contact_late"),
        ("construct-match late", "construct_match_late"),
        ("condition variance late", "condition_variance_late"),
        ("alive final", "alive_final"),
        ("executable programs", "n_executable_programs"),
        ("mutation attempts", "mutation_attempts"),
        ("accepted proposals", "accepted_proposals"),
        ("rejected proposals", "rejected_proposals"),
    ]:
        print(f"{name:28} {mean(rows, key):10.3f}")
    print("conservation", all(row["conservation_ok"] for row in rows))


def main() -> None:
    native = [run_one(seed, False) for seed in SEEDS]
    controlled = [run_one(seed, True) for seed in SEEDS]
    payload = {"native": native, "typed_controller": controlled}
    print(json.dumps(payload, indent=2))
    block("native IV-inspired physics", native)
    block("typed-controller integration", controlled)
    print()
    print("Integration diagnostic only: the arms differ in seed programs,")
    print("control rules, and variation. This is not a causal operator")
    print("comparison, an LLM result, or evidence of niche formation.")


if __name__ == "__main__":
    main()
