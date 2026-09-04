# Typed controllers on EVOLVE IV-inspired physics

> **Status: executable controller integration.** The physics now executes typed
> controller intents and every seed and newborn has an ID-keyed program record.
> The former English-policy table remains withdrawn. A separate
> [matched-variation pilot](iv-variation.md) now exercises four variation paths
> and an inheritance control, but its cache is synthetic and non-inferential.

## What was repaired

The earlier façade failed before simulation and never connected policies to the
step loop or reproduction. The repaired boundary now provides:

- immutable `IVPercept`, `IVIntent`, and `IVTraits` values;
- explicit movement modes: native `default`, deliberate `stay`, or a validated
  current/left/right `target`;
- construction, reproduction-gate, and reproduction-threshold intents that
  remain subordinate to ecological physics;
- a strict JSON-v1 executable program rather than substring matching over
  English;
- a persistent `bug_id -> PolicyRecord` registry outside `Bug`;
- exactly one inherited or proposed child program per birth;
- rejection-to-parent fallback for malformed proposals; and
- a controller RNG seeded independently from the ecosystem RNG.

The controller is passed into `MetabolicSim` before seeding, so a program's
metabolic role is known before the organism withdraws its initial nutrient or
waste. Controller mode also permits zero stored matter when a chosen pile is
empty instead of fabricating a unit.

## Separation of responsibilities

| Layer | Owns | Cannot do |
|---|---|---|
| `src/evolve4/simulation.py` | Matter, scheduling, metabolism, movement application, construction, fission, death | Parse programs or call a model |
| `src/evolve4/control.py` | Frozen percept/intent/trait types and lifecycle protocol | Mutate bodies or hold policy text |
| `src/evolve_modern/iv_policies.py` | JSON validation, canonical serialization, and pure decisions | Access simulator state or ecological RNG |
| `src/evolve_modern/iv.py` | Program registry, inheritance, proposal provenance, variation-gate and operator-event RNGs | Own or create matter |
| `src/evolve_modern/iv_variation.py` | Shared atomic-edit adjudication, matched operators, and strict offline cache replay | Select organisms or call a provider |

With no controller, the original physics takes a literal bypass path. A frozen
fixed-seed trace covers its history, final organisms, places, next ID, and RNG
state. A neutral controller also reproduces native physics and ecosystem RNG
exactly when legacy trait mutation is disabled, demonstrating that controller
randomness is isolated.

## Executable program

Programs use exactly six top-level keys and reject missing, unknown, duplicate,
or malformed fields:

```json
{
  "construction": "always",
  "movement": "seek_opposite",
  "reproduce_at": 14,
  "require_uncrowded": false,
  "schema": 1,
  "traits": {
    "construct": 1,
    "role": "producer",
    "taste": 1
  }
}
```

Allowed fields are deliberately small:

- role: `producer` or `recycler`;
- taste: `-1` or `1`;
- construction trait: `-1`, `0`, or `1`;
- movement: `default`, `stay_if_fed`, `seek_resource`, or `seek_opposite`;
- construction rule: `always`, `never`, or `until_nonzero`;
- reproduction threshold: integer `8..30`; and
- uncrowded requirement: JSON boolean.

Canonical JSON is the heritable representation. Matched operators may propose
one atomic edit through the shared adjudicator. Invalid cached output is logged,
costs its one proposal opportunity, and gives the child the exact parent program
without retry or silent repair. Cache integrity failures stop the run.

## Run the pilot

```bash
PYTHONPATH=src python3 -m evolve_modern.iv
PYTHONPATH=src python3 experiments/run_language_iv.py
```

The first command runs one controller-enabled ecosystem and reports conserved
matter, executable-program diversity, and accepted/rejected proposal counts.
The second retains its old filename for continuity but compares native physics
with the typed integration across four fixed seeds. It labels raw cross-type
contact correctly and prints the central limitation:

> The arms differ in seed programs, control rules, and variation.

Consequently, differences between their population statistics are debugging
observations—not evidence that semantic variation helps, that English packages
traits advantageously, or that niches emerged.

## What the matched repair adds

The [matched IV variation protocol](iv-variation.md) now supplies identical
initial executable programs and physics within each seed; named initialization,
scheduling, reproduction, mortality, condition-decay, variation-gate, and
operator-event streams; a shared birth-triggered proposal cap with exact
one-response/no-retry accounting; and event-level proposal provenance in a
deterministic checksummed bundle. Later proposal subjects and realized counts
can diverge because earlier proposals change the birth trajectories.

It compares typed point edits, uniform random atomic edits, homologous typed-leaf
recombination, and cached synthetic proposals against inheritance only. The
schema remains a flat seven-leaf product, so the recombination treatment is not
subtree GP. The fixture responses are not model observations.

## Evidence still needed

1. Pre-register primary estimands and use enough independent master seeds for a
   planned inferential analysis.
2. Add lineage-aware establishment, persistence, robustness, novelty, and shock
   tests instead of treating final abundance or genotype count as evolvability.
3. Introduce a recursive typed language before claiming a genuine GP treatment.
4. Collect authentic model responses under a frozen prompt/model/decoding
   protocol, retain failures and usage, and replay them offline.
5. Add density-preserving nulls and causal interventions before making niche or
   ecological-innovation claims.

Only that later evidence design can test whether an operator changes
evolvability while ecological persistence remains the sole selector.
