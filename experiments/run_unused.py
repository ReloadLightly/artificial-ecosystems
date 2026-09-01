#!/usr/bin/env python3
"""Unused phenome sequences — Conrad & Pattee observation (5)."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve1970.organism import ACTION_NAMES, decode_program, random_genome
from evolve1970.simulation import Simulation, SimulationConfig

SEEDS = (1970, 1971, 1985, 2026)
STEPS = 280


def window_mean(history, attr, start, end):
    sl = history[start:end]
    return sum(getattr(s, attr) for s in sl) / max(1, len(sl))


def random_structural_unused(n=400, length=12):
    import numpy as np
    rng = np.random.default_rng(0)
    vals = []
    for _ in range(n):
        prog = decode_program(random_genome(rng, length=length))
        vals.append(1.0 - len(set(prog)) / len(prog))
    return float(sum(vals) / len(vals))


def snapshot(sim):
    alive = [o for o in sim.organisms if o.alive]
    if not alive:
        return {"n_alive": 0}
    by_store = sorted(alive, key=lambda o: o.stored_chips)
    nq = max(1, len(by_store) // 4)
    rich, poor = by_store[-nq:], by_store[:nq]
    counts = Counter(o.genotype_signature() for o in alive)
    top_sig, top_n = counts.most_common(1)[0]
    top_line = [o for o in alive if o.genotype_signature() == top_sig]
    example = max(rich, key=lambda o: o.stored_chips)
    aged = [o for o in alive if o.age >= 5]
    return {
        "n_alive": len(alive),
        "structural_all": sum(o.unused_program_fraction() for o in alive) / len(alive),
        "structural_rich": sum(o.unused_program_fraction() for o in rich) / len(rich),
        "structural_poor": sum(o.unused_program_fraction() for o in poor) / len(poor),
        "structural_top_lineage": sum(o.unused_program_fraction() for o in top_line) / len(top_line),
        "dynamic_aged": sum(o.dynamic_unused_fraction() for o in aged) / len(aged) if aged else 0.0,
        "dynamic_rich": sum(o.dynamic_unused_fraction() for o in rich) / len(rich),
        "top_lineage_size": top_n,
        "example_program": example.program_names(),
        "example_executed": sorted(ACTION_NAMES[a] for a in example.executed),
        "example_stored": example.stored_chips,
        "example_unused_structural": example.unused_program_fraction(),
        "example_unused_dynamic": example.dynamic_unused_fraction(),
    }


def run_one(seed):
    sim = Simulation(SimulationConfig(steps=STEPS, n_organisms=80, n_places=48, total_chips=4000, seed=seed, match_bonus=True, verbose_every=0))
    start = sim.conserved_chips()
    sim.run()
    h = sim.history
    return {
        "seed": seed,
        "conservation_ok": start == sim.conserved_chips() == 4000,
        "structural_early": window_mean(h, "unused_frac", 0, 30),
        "structural_late": window_mean(h, "unused_frac", len(h) - 30, len(h)),
        "dynamic_early": window_mean(h, "unused_dynamic", 0, 30),
        "dynamic_late": window_mean(h, "unused_dynamic", len(h) - 30, len(h)),
        "rich_early": window_mean(h, "unused_rich", 0, 30),
        "rich_late": window_mean(h, "unused_rich", len(h) - 30, len(h)),
        "poor_early": window_mean(h, "unused_poor", 0, 30),
        "poor_late": window_mean(h, "unused_poor", len(h) - 30, len(h)),
        "genome_early": window_mean(h, "mean_genome_len", 0, 30),
        "genome_late": window_mean(h, "mean_genome_len", len(h) - 30, len(h)),
        "final": snapshot(sim),
    }


def mean(rows, key):
    return sum(r[key] for r in rows) / max(1, len(rows))


def main():
    results = [run_one(seed) for seed in SEEDS]
    null = random_structural_unused()
    print(json.dumps({"null_structural": null, "runs": results}, indent=2))
    print("\nUnused phenome sequences — Conrad observation (5)")
    print(f"random-genome null: {null:.3f}")
    for label, ke, kl in [
        ("structural unused", "structural_early", "structural_late"),
        ("dynamic unused", "dynamic_early", "dynamic_late"),
        ("rich structural", "rich_early", "rich_late"),
        ("poor structural", "poor_early", "poor_late"),
    ]:
        e, l = mean(results, ke), mean(results, kl)
        print(f"{label:22} {e:.3f} -> {l:.3f} ({l-e:+.3f})")
    print("conservation", all(r["conservation_ok"] for r in results))
    for r in results:
        f = r["final"]
        if f.get("n_alive"):
            print(f"  seed {r['seed']}: tape={f['example_program']} fired={f['example_executed']}")


if __name__ == "__main__":
    main()
