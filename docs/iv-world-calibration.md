# Calibrating the EVOLVE IV world

> **Status: exploratory, model-blind world calibration.** This protocol changes one physical
> limit before any authentic model response is collected. It selects a
> less ceiling-saturated world on inheritance-only runs, freezes that choice,
> and reserves disjoint seeds for engineering qualification and later evidence.
> It is not an operator comparison and does not support biological or model
> performance claims.

## Why calibrate first?

The matched-variation pilot used `max_organisms = 40`. Population capacity was
therefore often part of the causal dynamics: a reproduction-ready organism
could be denied a birth simply because the world was full. When most treatments
press against that boundary, genuine differences in reproductive behavior can
be compressed into the same capped population trajectory.

The calibration changes only `max_organisms`. The initial programs, remaining
physics, 64-step horizon, and inheritance-only controller stay fixed. This
one-axis design targets the diagnosed ceiling problem without tuning the world
against treatment outcomes.

## Frozen protocol

The complete machine-readable protocol is
[`experiments/configs/iv-world-calibration-v1.json`](../experiments/configs/iv-world-calibration-v1.json).

| Contract item | Calibration v1 |
|---|---|
| Arm | `inherit_only` only |
| Horizon | 64 steps |
| Calibration seeds | `101`, `503`, `1601`, `4099`, `8081`, `12007`, `16001`, `24001` |
| Candidate capacities | `112`, `120`, `128`, `144`, `160`, `176` |
| High-capacity sentinel | `192` |
| Changed physics field | `max_organisms` only |
| Selection rule | Smallest candidate passing every criterion for every calibration seed |
| Design timing | Exploratory; the 85% headroom rule was finalized after the inheritance-only scan and was not preregistered |
| Model/provider access | None |

For every seed, a candidate must:

- conserve matter and retain nonnegative state on every recorded step;
- avoid extinction and retain producer/recycler coexistence for at least 95%
  of steps;
- produce at least 32 births, with the eighth birth no later than step 15;
- spend no time at the post-step ceiling;
- keep the actual capacity-gate occupancy at or below 85% of configured
  capacity;
- record zero births blocked by capacity; and
- reproduce the same projected step-summary trajectory as the cap-192
  sentinel.

The sentinel comparison covers a declared projection of aggregate step
summaries: population and role counts, birth/death and capacity-gate events,
material totals, construction statistics, contact statistics, and invariant
flags. It is not a full organism-level microstate comparison. The capacity
value and its derived fingerprints necessarily differ, while every field in
that projected summary must agree.

## The direct blocked-birth diagnostic

`population_ceiling_fraction` alone cannot establish that capacity was
irrelevant. A step can reach capacity, reject one or more otherwise eligible
births, and then lose organisms to mortality before its post-step row is
recorded. The row is below the ceiling even though the ceiling changed the
step.

The simulator therefore records `capacity_blocked_births` at the decision
site: it increments whenever an organism is reproduction-ready but no slot is
available. Calibration sums this as `capacity_blocked_births_total` and
requires exactly zero.

It also records `capacity_gate_occupancy_peak` using the gate's actual
occupancy expression: the size of the living cohort captured at the start of
the step plus newborns accepted so far. Deaths during that sequential step do
not reopen one of those reserved slots, because the gate itself continues to
use the fixed step-start cohort. The calibration takes the maximum of that
quantity across steps and requires its ratio to capacity to be no greater than
0.85. The separate projected-summary match to the cap-192 sentinel then checks
the observable aggregate consequence: raising the cap again must not change
any declared step-summary field.

Normalized occupancy AUC and maximum post-step population remain descriptive
metrics, but they are not selection criteria. Normalizing an identical
trajectory by a larger safety cap mechanically lowers its score, and a
post-step census can miss the higher occupancy seen by the within-step gate.

## Why cap 176, not 160?

Cap 160 is dynamically non-binding in the calibration sample: it records no
capacity-blocked births and its projected summaries match the cap-192
sentinel. It nevertheless fails the corrected v1 engineering headroom rule.
On seed `24001`, the post-step population reaches only 134, but the gate sees a
peak occupancy of 138:

| Candidate | Maximum post-step alive | Gate occupancy peak | Gate capacity used | Decision |
|---:|---:|---:|---:|---|
| 160 | 134 | 138 | 86.25% | Fails the 85% gate-headroom limit |
| 176 | 134 | 138 | 78.4% | Passes and matches the sentinel projection |

Cap 176 is therefore the smallest candidate that satisfies **all** criteria
for **all** eight calibration seeds. The extra margin is intentional: later
variation treatments may explore trajectories that the inheritance-only
control does not, and beginning those comparisons immediately beside a hard
boundary would recreate the original problem.

The 85% margin is a conservative design choice finalized after the exploratory
inheritance-only scan; it was not prospectively preregistered. No variation-arm
or model outcome informed it, and the evidence seeds remained untouched, but
the calibration itself is engineering evidence rather than a confirmatory
analysis. Cap 176 is not proven optimal. A new horizon, program language,
initial population, or physical regime requires a new versioned calibration.
That timing is not only narrative metadata: the configuration, selection
decision, frozen world, and manifest all carry the validated
`exploratory_post_scan_rule_finalization` record and `preregistered: false`.

## Three disjoint seed sets

Calibration, engineering qualification, and later evidence do not reuse seeds.
The latter two reservations use NumPy `SeedSequence(root).spawn(4)`, taking one
unsigned 64-bit state value from each child under derivation version 1.

| Purpose | Seed source | Frozen seeds | Permitted use |
|---|---|---|---|
| World selection | Explicit calibration list | `101`, `503`, `1601`, `4099`, `8081`, `12007`, `16001`, `24001` | Choose the capacity; inheritance only |
| Engineering qualification | Root `20260905` | `5734163613718072789`, `10843568836493112964`, `5360109053914373194`, `9040270409388520618` | Exercise all arms, budgets, cache replay, and invariants |
| Later evidence | Root `20260906` | `7591592684187682497`, `2275270120458329610`, `18348701203143951756`, `10406254645250620281` | Reserved and unrun during calibration/qualification |

The qualification seeds cease to be pristine as soon as their results are
inspected. Qualification is an engineering test of the frozen machinery, not
an inferential result and not a rehearsal on the evidence seeds. The evidence
reservation must not be used to retune capacity, prompts, budgets, operators,
or endpoints.

## Run the calibration

The output directory must not already exist.

```bash
IV_CALIBRATION_DIR="$(mktemp -d)/iv-world-calibration-v1"

PYTHONPATH=src python3 experiments/calibrate_iv_world.py \
  --config experiments/configs/iv-world-calibration-v1.json \
  --output "$IV_CALIBRATION_DIR"
```

For a committed reference bundle, add `--require-committed-source`. That mode
refuses generation unless every critical source and configuration byte matches
the Git revision recorded in the manifest. It also requires `--config` to
resolve to the repository's versioned
`experiments/configs/iv-world-calibration-v1.json`; a byte-identical external
copy is deliberately insufficient. The manifest records that canonical input
path and its exact byte digest.

The deterministic bundle contains:

| Artifact | Contents |
|---|---|
| `calibration-runs.jsonl` | Per-candidate, per-seed metrics and projected step-summary comparisons |
| `calibration-decision.json` | Candidate pass/fail reasons and the selected capacity |
| `frozen-world.json` | The selected non-seed physics and reserved seed provenance |
| `manifest.json` | Protocol, source, runtime, input, and selection provenance |
| `checksums.json` | SHA-256 digests for the other bundle files |

Run the focused contract tests with:

```bash
PYTHONPATH=src python3 -m unittest tests.test_iv_world_calibration
```

## Qualify the frozen world

The separate qualification configuration fixes cap 176, the same 64-step
horizon, the four qualification seeds, and eight opportunities per variation
arm. Its cached arm remains a deterministic fixture, not a model:

```bash
IV_QUALIFICATION_DIR="$(mktemp -d)"

PYTHONPATH=src python3 experiments/run_iv_variation.py \
  --config experiments/configs/iv-variation-qualification-v1.json \
  --build-fixture-cache "$IV_QUALIFICATION_DIR/fixture.jsonl"

PYTHONPATH=src python3 experiments/run_iv_variation.py \
  --config experiments/configs/iv-variation-qualification-v1.json \
  --cache "$IV_QUALIFICATION_DIR/fixture.jsonl" \
  --output "$IV_QUALIFICATION_DIR/results"
```

The repository retains the exact
[qualification fixture](../experiments/cache/iv-variation-qualification-fixture-v1.jsonl)
and its checksummed [reference replay](../results/reference/iv-variation-qualification-v1).

Passing qualification shows that all five implementations execute, consume
their declared budgets, preserve invariants, and replay their fixture input in
the frozen world. It cannot rank the operators, estimate effects, validate the
future model treatment, or turn fixture responses into model observations.

The qualification configuration binds the frozen-world artifact by world ID,
calibration ID, seed role, repository-relative path, and SHA-256 digest. Before
building its fixture or replaying it, the runner verifies those bytes and
requires exact agreement on physics, initial programs, proposal cap, and the
ordered qualification seeds. Full use of the cap is local to this engineering
qualification; the frozen evidence policy preserves a horizon-complete
shortfall as an outcome.

## Claim boundary

This calibration can support the narrow statement that cap 176 was selected
after an exploratory, model-blind, inheritance-only scan, was then frozen
before authentic model outcomes, and was non-binding on the eight calibration
trajectories. It cannot establish treatment superiority,
evolvability, open-endedness, ecological innovation, model quality, or
generalization beyond this world and horizon.

Authentic model collection is a separate protocol. It begins only after the
world, evidence seeds, prompt bytes, provider/model identity, decoding,
tokenizer, price snapshot, and spending authorization are frozen.
