# Typed controllers on EVOLVE IV-inspired physics

> **Status: executable integration pilot.** The physics now executes typed
> controller intents and every seed and newborn has an ID-keyed program record.
> The former English-policy table remains withdrawn: this stage makes no model
> call and is not a causal comparison of variation operators.

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
| `src/evolve_modern/iv_policies.py` | JSON validation, canonical serialization, pure decisions, typed mutation | Access simulator state or ecological RNG |
| `src/evolve_modern/iv.py` | Program registry, inheritance, proposal provenance, controller RNG | Own or create matter |

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

Canonical JSON is the heritable representation. The offline heuristic changes
at most one typed field. A future model adapter may propose JSON, but invalid
output is logged and the exact parent program is inherited without retry or
silent repair.

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

## Evidence still needed for a real operator experiment

1. Give every arm identical initial executable programs and physics.
2. Compare point mutation, grammar-preserving GP, matched random edits, and
   cached model proposals with matched proposal probability and edit distance.
3. Separate ecosystem, scheduler, mortality, reproduction, and controller/model
   random streams sufficiently for paired counterfactual runs.
4. Record raw proposals, validation failures, parent/child programs, model and
   prompt revisions, token use, and checksums.
5. Measure offspring validity, viability, descendant establishment, robustness,
   novelty, and recovery under unseen perturbations with uncertainty intervals.
6. Generate every table from a versioned result bundle.

Only that later design can test whether semantic variation changes
evolvability while ecological persistence remains the sole selector.
