#!/usr/bin/env python3
"""Language mutator on EVOLVE IV physics.

Compare the bit-string IV world to the same world where conversion,
taste, construct, and step intent are compiled from English policies
that mutate only at birth.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.simulation import MetabolicSim, MetabolicConfig
from evolve_modern.iv import attach_language, unique_policies


def window_mean(history, attr, start, end):
    sl = history[start:end]
    return sum(getattr(s, attr) for s in sl) / max(1, len(sl))


def run_one(seed: int, language: bool) -> dict:
    sim = MetabolicSim(
        MetabolicConfig(
            steps=200,
            n_places=96,
            n_organisms=36,
            max_organisms=90,
            harvest=5,
            seed=seed,
            construction=True,
            language=language,
            verbose_every=0,
        )
    )
    if language:
        attach_language(sim)
    start = sim.conserved()
    sim.run()
    end = sim.conserved()
    h = sim.history
    last = h[-1]
    policies = unique_policies(sim) if language else []
    return {
        "seed": seed,
        "language": language,
        "conservation_ok": start == end == 4000,
        "producers_late": window_mean(h, "n_producers", len(h) - 40, len(h)),
        "recyclers_late": window_mean(h, "n_recyclers", len(h) - 40, len(h)),
        "niche_early": window_mean(h, "niche_index", 0, 30),
        "niche_late": window_mean(h, "niche_index", len(h) - 40, len(h)),
        "cmatch_late": window_mean(h, "construct_match", len(h) - 40, len(h)),
        "cvar_late": window_mean(h, "condition_var", len(h) - 40, len(h)),
        "alive_final": last.n_alive,
        "n_policies": len(policies),
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
        ("distinct policies", "n_policies"),
    ]:
        print(f"{name:24} {mean(rows, key):10.3f}")
    print("conservation", all(r["conservation_ok"] for r in rows))


def main() -> None:
    seeds = (1998, 1999, 1970, 2026)
    bits = [run_one(s, False) for s in seeds]
    words = [run_one(s, True) for s in seeds]
    print(json.dumps({"bits": bits, "language": words}, indent=2))
    block("IV bits (no language)", bits)
    block("IV + language mutator", words)
    print()
    print("Same conserved metabolites. Same construction. The only")
    print("change is that role, taste, construct, and step intent")
    print("are written in English and rewritten at birth.")


if __name__ == "__main__":
    main()
