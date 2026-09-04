#!/usr/bin/env python3
"""Test whether persistent local conditions cause metabolic niche mixing.

Three matched arms are run on the EVOLVE IV-inspired ring:

* ``construction_off``: no place modification;
* ``local_construction``: ordinary local construction;
* ``place_memory_scrambled``: construction remains active, but condition
  values are permuted across places after each complete step.

The primary statistic is the fraction of local producer--recycler edges minus
its random-mixing expectation given the current role counts. Raw contact is
reported only as a density-sensitive diagnostic.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from typing import Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evolve4.simulation import Bug, MetabolicConfig, MetabolicSim


EXPERIMENT_ID = "causal-niches-v1"
ARMS = ("construction_off", "local_construction", "place_memory_scrambled")
SEEDS = range(6000, 6064)
LATE_STEPS = 80
CONFIG = dict(
    n_places=128,
    total_units=800,
    n_organisms=16,
    max_organisms=176,
    steps=240,
    harvest=4,
    convert_yield=3,
    excrete=2,
    repro_threshold=14,
    mut_prob=0.08,
    condition_decay=0.18,
    verbose_every=0,
)
METRICS = (
    "edge_enrichment",
    "edge_cross_fraction",
    "adjacent_edges",
    "raw_contact",
    "condition_variance",
    "alive",
    "role_balance",
    "blocked_births",
)


def edge_metrics(bugs: Sequence[Bug], n_places: int) -> dict[str, float]:
    """Composition-adjusted role mixing among same/neighbor-place pairs."""
    edges = cross = 0
    for index, left in enumerate(bugs):
        for right in bugs[index + 1 :]:
            distance = abs(left.position - right.position)
            if min(distance, n_places - distance) <= 1:
                edges += 1
                cross += left.producer != right.producer

    n_alive = len(bugs)
    producers = sum(bug.producer for bug in bugs)
    recyclers = n_alive - producers
    observed = cross / edges if edges else 0.0
    expected = (
        2 * producers * recyclers / (n_alive * (n_alive - 1))
        if n_alive > 1
        else 0.0
    )
    return {
        "edge_cross_fraction": observed,
        "edge_expected_cross_fraction": expected,
        "edge_enrichment": observed - expected,
        "adjacent_edges": float(edges),
    }


def scramble_place_memory(sim: MetabolicSim, rng: np.random.Generator) -> None:
    values = np.array([place.condition for place in sim.places])
    for place, value in zip(sim.places, values[rng.permutation(len(values))]):
        place.condition = int(value)


def run_one(seed: int, arm: str) -> dict[str, object]:
    sim = MetabolicSim(
        MetabolicConfig(
            seed=seed,
            construction=arm != "construction_off",
            **CONFIG,
        )
    )
    scramble_rng = np.random.default_rng(
        np.random.SeedSequence([seed, 0x4E49434845])
    )
    late: list[dict[str, float]] = []

    for step in range(CONFIG["steps"]):
        row = sim.step()
        if arm == "place_memory_scrambled":
            scramble_place_memory(sim, scramble_rng)
        if sim.conserved() != CONFIG["total_units"]:
            raise RuntimeError(f"matter drift: seed={seed}, arm={arm}, step={step}")

        if step >= CONFIG["steps"] - LATE_STEPS:
            living = [bug for bug in sim.bugs if bug.alive]
            roles = sum(bug.producer for bug in living)
            values = edge_metrics(living, CONFIG["n_places"])
            values.update(
                raw_contact=row.niche_index,
                condition_variance=float(
                    np.var([place.condition for place in sim.places])
                ),
                alive=float(len(living)),
                role_balance=(
                    min(roles, len(living) - roles) / len(living)
                    if living
                    else 0.0
                ),
                blocked_births=float(row.capacity_blocked_births),
            )
            late.append(values)

    result: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "seed": seed,
        "arm": arm,
        "conservation_ok": sim.conserved() == CONFIG["total_units"],
    }
    for metric in METRICS:
        result[metric] = sum(row[metric] for row in late) / len(late)
    return result


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def paired_contrast(
    rows: list[dict[str, object]], treatment: str, control: str, metric: str
) -> dict[str, object]:
    lookup = {
        (int(row["seed"]), str(row["arm"])): float(row[metric]) for row in rows
    }
    diffs = [lookup[(seed, treatment)] - lookup[(seed, control)] for seed in SEEDS]
    data = np.asarray(diffs)
    rng = np.random.default_rng(
        20260904 + sum(map(ord, treatment + control + metric))
    )
    boot = data[rng.integers(0, len(data), size=(20_000, len(data)))].mean(axis=1)
    return {
        "treatment": treatment,
        "control": control,
        "metric": metric,
        "mean_difference": mean(diffs),
        "standard_error": float(np.std(data, ddof=1) / math.sqrt(len(data))),
        "bootstrap_95_interval": [float(x) for x in np.quantile(boot, [0.025, 0.975])],
        "wins": sum(value > 0 for value in diffs),
        "losses": sum(value < 0 for value in diffs),
        "n_pairs": len(diffs),
    }


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    means = {
        arm: {
            metric: mean(
                [float(row[metric]) for row in rows if row["arm"] == arm]
            )
            for metric in METRICS
        }
        for arm in ARMS
    }
    contrasts = [
        paired_contrast(rows, "local_construction", "construction_off", "edge_enrichment"),
        paired_contrast(rows, "local_construction", "place_memory_scrambled", "edge_enrichment"),
        paired_contrast(rows, "local_construction", "construction_off", "adjacent_edges"),
        paired_contrast(rows, "local_construction", "place_memory_scrambled", "adjacent_edges"),
        paired_contrast(rows, "local_construction", "construction_off", "alive"),
    ]
    return {
        "schema": 1,
        "experiment_id": EXPERIMENT_ID,
        "claim_status": "exploratory_causal_diagnostic",
        "question": "Does persistent place-specific environmental memory cause producer-recycler spatial complementarity?",
        "design": {
            "arms": list(ARMS),
            "seeds": list(SEEDS),
            "late_steps": LATE_STEPS,
            "config": CONFIG,
            "primary_metric": "edge_enrichment",
            "primary_contrast": "local_construction - place_memory_scrambled",
        },
        "arm_means": means,
        "contrasts": contrasts,
        "checks": {
            "complete_matched_design": len(rows) == len(ARMS) * len(SEEDS),
            "all_runs_conserved": all(row["conservation_ok"] for row in rows),
            "no_capacity_blocking": all(row["blocked_births"] == 0 for row in rows),
        },
        "interpretation": (
            "Construction increases raw contact and local clustering relative to "
            "construction-off, but local construction does not beat a placebo "
            "that preserves condition values while scrambling their locations. "
            "The current mechanism creates environmental structure and clumping, "
            "not demonstrated niche specialization caused by place memory."
        ),
        "limitations": [
            "Scrambling breaks cross-step place identity, not within-step sequential effects.",
            "This tests the repository's EVOLVE IV-inspired mechanism, not the historical implementation.",
            "Metabolite provenance and lineage establishment are not measured.",
        ],
    }


def write_svg(path: Path, summary: dict[str, object]) -> None:
    means = summary["arm_means"]
    labels = {"construction_off": "off", "local_construction": "local", "place_memory_scrambled": "scrambled"}
    values = [float(means[arm]["edge_enrichment"]) for arm in ARMS]
    bars = []
    for index, (arm, value) in enumerate(zip(ARMS, values)):
        x = 100 + index * 150
        zero = 245
        y = zero - value * 1200
        top, height = min(y, zero), max(2, abs(y - zero))
        shade = ("#b8b8b8", "#222222", "#777777")[index]
        bars.append(f'<rect x="{x}" y="{top:.1f}" width="80" height="{height:.1f}" fill="{shade}" rx="3"/>')
        bars.append(f'<text x="{x+40}" y="{top-8:.1f}" text-anchor="middle">{value:+.3f}</text>')
        bars.append(f'<text x="{x+40}" y="275" text-anchor="middle">{labels[arm]}</text>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="620" height="350" viewBox="0 0 620 350">
<rect width="100%" height="100%" fill="white"/>
<style>text{{font-family:Inter,Arial,sans-serif;fill:#171717}}.title{{font-size:22px;font-weight:700}}.sub{{font-size:13px;fill:#555}}</style>
<text x="35" y="40" class="title">Place memory does not explain the mixing signal</text>
<text x="35" y="65" class="sub">Opposite-role edge enrichment · 64 matched seeds</text>
<line x1="75" y1="245" x2="555" y2="245" stroke="#999"/>
{''.join(bars)}
<text x="35" y="315" class="sub">Local construction beats construction-off, but not the scrambled-place placebo.</text>
<text x="35" y="336" class="sub">The mechanism changes clustering; niche specialization is not yet demonstrated.</text>
</svg>'''
    path.write_text(svg + "\n", encoding="utf-8")


def write_bundle(path: Path, rows: list[dict[str, object]], summary: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    if not all(summary["checks"].values()):
        raise RuntimeError(f"failed checks: {summary['checks']}")
    path.mkdir(parents=True)
    with (path / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    (path / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_svg(path / "figure.svg", summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = [run_one(seed, arm) for seed in SEEDS for arm in ARMS]
    summary = summarize(rows)
    if args.output:
        write_bundle(args.output, rows, summary)
        print(f"wrote {EXPERIMENT_ID} to {args.output}")

    print("\narm                       edge enrich.   local edges   raw contact   alive")
    for arm in ARMS:
        values = summary["arm_means"][arm]
        print(f"{arm:26} {values['edge_enrichment']:12.3f} {values['adjacent_edges']:13.1f} {values['raw_contact']:13.3f} {values['alive']:7.1f}")
    primary = summary["contrasts"][1]
    print(f"\nlocal - scrambled edge enrichment: {primary['mean_difference']:+.3f} "
          f"(95% bootstrap {primary['bootstrap_95_interval'][0]:+.3f} to "
          f"{primary['bootstrap_95_interval'][1]:+.3f})")
    print("Conclusion: construction changes clustering, but persistent place memory is not the demonstrated cause of complementary mixing.")


if __name__ == "__main__":
    main()
