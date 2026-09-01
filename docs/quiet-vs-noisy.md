# Quiet vs noisy world

Conrad and Pattee’s first two qualitative results:

1. The match between phenotypic characters and environmental conditions
   increased when the world contained no noise.
2. Adding noise produced a diversity of types, with no slide toward one type.

This document says what those sentences mean, how the reconstruction
implements them, and what the first rerun showed.

## What “quiet” and “noisy” are

The world is a ring of places. Each place has an abiotic state, A or B,
arranged in stable patches of four. That pattern is the environment.

- **Quiet:** the A/B pattern never changes. A place that is A at step 0
  is still A at step 280. The only things that move are organisms and chips.
- **Noisy:** each step, every place independently flips A↔B with
  probability `p` (default `0.10`). About five of the 48 places change
  every generation. An organism that sat down in matching habitat wakes
  up mismatched.

Noise here is **environmental flicker**, not mutation. Mutation happens
in both conditions. What changes is whether the world holds still long
enough for a specialist bit to keep paying.

## What “matching” is

Each organism has a preferred state encoded in the first genomic symbol
(`genome[0] % 2`). That is the reconstruction of Conrad’s
phenotype–environment character.

Matching is not a fitness function given to the organism. It shows up
in two physical ways:

- A matched harvest takes two extra chips (EVOLVE II allocated food by
  relative match; we use a bonus rather than a starvation penalty).
- Foraging is biased toward places that match the preferred state.

An organism that prefers A and sits on A therefore tends to store more
chips, reach the reproduction threshold sooner, and leave more
daughters nearby. In a quiet world those daughters keep finding A.
In a noisy world the patch flips under them.

Two numbers are logged:

- `match_ratio` — fraction of living organisms sitting on their
  preferred state.
- `match_weighted` — the same fraction, weighted by stored chips.
  This asks whether the *successful* organisms are the matched ones.

## What we ran

```bash
PYTHONPATH=src python3 experiments/run_quiet_noisy.py
```

Four seeds (1970, 1971, 1985, 2026), 280 steps, 80 seed organisms,
4000 chips, `p = 0.10` in the noisy condition. Conservation held in
every run.

Means across seeds:

| metric | quiet | noisy |
|---|---:|---:|
| match early | 0.556 | 0.554 |
| match late | 0.844 | 0.719 |
| weighted match late | 0.856 | 0.754 |
| match gain (late − early) | +0.288 | +0.165 |
| Shannon diversity late | 6.256 | 6.726 |
| distinct lineages late | 93 | 119 |
| living organisms final | 126 | 158 |
| chips in bodies late | 2330 | 2211 |
| unused program fraction | 0.33 | 0.37 |

## How to read it

Observation (1) holds. Matching starts at chance in both worlds and
climbs. It climbs further when the world does not move. By the end,
about six in seven quiet-world organisms sit on the abiotic state their
genome prefers. The chip-weighted number is even higher: the rich ones
are the matched ones.

Observation (2) holds. The noisy world finishes with more lineages,
higher Shannon diversity, and more living organisms. Specialists cannot
lock the habitat, so types that would have been squeezed out in the
quiet world keep a foothold.

Two other Conrad notes appear as side effects. Utilization of the
environment (chips stored in bodies) rises in both conditions. And
roughly a third of each decoded program is redundant — sequences that
are never required for the cyclic walk. That is their fifth
observation, sitting in the same runs.

## What this is not

It is not a claim that noise is “good” or that specialists are “better.”
It is a claim about a closed material world: a still environment lets
a heritable preference become a sorting process; a flickering
environment keeps that sorting from finishing.

The six primitives, the size of the harvest bonus, and the forage bias
are reconstruction choices. If you have the 1970 PDF, the thing to
check is how they generated environmental noise and how they scored
the matching ratio. Until then these knobs stay in
`SimulationConfig.abiotic_flip_prob` and `match_bonus`.
