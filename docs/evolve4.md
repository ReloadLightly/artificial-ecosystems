# EVOLVE IV-inspired metabolism and construction

> **Status: runnable construction ablation, not an EVOLVE IV replication.** The
> current world is a compact reconstruction choice informed by Brewster and
> Conrad's published program. Its contact statistic has no spatial null, so it
> does not establish niche formation.

Primary starting points:

- Jon Brewster and Michael Conrad, *Evolve IV: A Metabolically-Based Artificial
  Ecosystem Model* (1998).
- Jon J. Brewster and Michael Conrad, *Computer Experiments on the Development
  of Niche Specialization in an Artificial Ecosystem* (1999),
  <https://doi.org/10.1109/CEC.1999.781957>.

The papers motivate a world in which organisms exchange metabolites and modify
local conditions, allowing ecological dependencies and niches to be outcomes
rather than scores. The repository has not yet demonstrated that its detailed
mechanisms match those papers.

## Current world

`src/evolve4` contains a one-dimensional ring with two conserved material pools
at every place: nutrient and waste. Living bodies store the same conserved
matter, so the accounting invariant is:

```text
nutrient + waste + stored in living bodies = constant
```

Organisms are seeded as one of two conversion types. Producers consume nutrient
and emit waste; recyclers consume waste and emit nutrient. They also carry a
preferred condition and a construction direction. Construction changes a
bounded, non-material local condition that relaxes toward zero.

These roles, yields, inheritance rules, ring geometry, and construction dynamics
are implementation choices. Calling the roles “metabolic types” does not show
that reciprocal dependence evolved: type is initialized directly, and the
current experiment lacks partner-removal or metabolite-knockout tests.

## Current measurements

| Output | What it measures | What it does not establish |
|---|---|---|
| `n_producers`, `n_recyclers` | Abundance of seeded conversion types | Evolved specialization or reciprocal necessity |
| `niche_index` | Raw fraction with a nearest neighbour of the opposite type | Above-random spatial association |
| `construct_match` | Builders whose construction sign equals their preference | Individual benefit or adaptation |
| `condition_var` | Spatial variance in the constructed condition | Functional niche formation |
| conserved total | Nutrient, waste, and body matter | Historical fidelity |

The raw cross-type contact rate is strongly density-sensitive and saturates in
packed worlds. `experiments/run_niches.py` therefore labels it
`cross_type_contact`; a difference between treatments is descriptive until it
is compared with density- and occupancy-preserving null models.

## Run the diagnostic

```bash
PYTHONPATH=src python3 -m evolve4
PYTHONPATH=src python3 experiments/run_niches.py
```

The experiment compares dense and sparse rings with construction enabled or
disabled over four fixed seeds. It checks total matter at the beginning and end
of each run. The current command prints raw trajectories and explicitly states
that they do not establish niche formation. No numerical table is canonical
until it is generated from a recorded result bundle with revision, environment,
configuration, seeds, trajectories, and checksums.

## Stronger causal test

1. Trace nutrient and waste provenance through places, bodies, and conversion
   events.
2. Compare contact and flux dependence against occupancy-preserving spatial
   permutations and matched-density placebo worlds.
3. Remove one conversion type or disable its conversion after communities form;
   measure collapse, recovery, and metabolite accumulation.
4. Permute or neutralize construction while preserving movement and density.
5. Test whether associations persist across descendants and unseen
   environmental changes.
6. Reconstruct paper-specific mechanisms from page-level citations and report
   every deviation in an ambiguity register.

Only after association exceeds appropriate nulls and survives causal
interventions should this implementation claim emergent niche specialization.
