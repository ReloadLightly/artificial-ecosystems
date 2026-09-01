# EVOLVE IV — metabolites and niche construction

Brewster & Conrad, 1998–1999. The last numbered episode.

- 1998. *Evolve IV: a metabolically-based artificial ecosystem model.*
  Lecture Notes in Computer Science 1447: 473–482.
- 1999. *Computer experiments on the development of niche
  specialization in an artificial ecosystem.* CEC-99.
  doi:10.1109/CEC.1999.781957

The 1999 abstract is the whole brief:

> Organisms can interact by exchanging metabolites and by modifying
> their environment either to the benefit or detriment of neighboring
> organisms. Experiments indicate that niche formation occurs in
> the model.

Source is lost. This reconstruction is the smallest closed world
in which both sentences can be true.

## Physics

Same 1-D ring as 1970. Two conserved metabolite piles on every
place — nutrient (N) and waste (W) — plus a signed *condition*
of the ground (soil / pH / moisture). Condition is a state, not
matter. `N + W + stored = constant`.

Each organism carries three heritable bits:

| trait | values | meaning |
|---|---|---|
| conversion | producer / recycler | eats N makes W, or eats W makes N |
| taste | −1 / +1 | preferred sign of local condition |
| construct | −1 / 0 / +1 | how this body pushes the ground |

Harvest yield is one unit better when condition matches taste,
one unit worse when it opposes. After acting, the organism adds
`construct` to the place (clamped to ±3). Condition slowly
relaxes toward 0. Death returns the body as a mix of N and W.
No fitness function.

A *metabolic niche* is spatial sorting: producers standing next
to recyclers so each one's waste is the other's food. The index
is the fraction of living organisms whose nearest neighbour has
the opposite conversion type.

A *constructed niche* is a patch whose condition has been pushed
off zero. `condition_var` measures how structured the ground is.
`construct_match` is the fraction of builders whose construct
sign equals their own taste.

## What we ran

```bash
PYTHONPATH=src python3 -m evolve4
PYTHONPATH=src python3 experiments/run_niches.py
```

Four seeds, 220 steps, two densities, construction on or off.

| world | construction | P late | R late | niche late | c-var late | conserved |
|---|---|---:|---:|---:|---:|---|
| dense (48 places, cap 280) | off | 136.3 | 135.9 | **1.00** | 0.00 | yes |
| dense | on | 135.7 | 136.2 | **1.00** | 2.63 | yes |
| sparse (96 places, cap 90) | off | 44.4 | 42.9 | 0.74 | 0.00 | yes |
| sparse | on | 47.0 | 40.3 | **0.88** | 2.05 | yes |

## What to take from it

1. Both metabolic types persist in every world, in roughly equal
   numbers. The food cycle is physics, not a diagram: if producers
   die the recyclers starve, and the other way around.
2. On a packed ring the metabolic-niche index saturates whether
   or not anyone is digging. Everyone already has an opposite
   neighbour. Density hides the construction effect.
3. On a sparse ring there is room *not* to sort. Construction
   is what raises the niche index (0.74 → 0.88). That is the
   1999 sentence, measured.
4. `construct_match` does not rise. Builders that like what they
   build do not take over. The ground is a commons: a neighbour
   can overwrite the patch you just prepared. Metabolic pairing
   is the stronger force on this ring. We report that rather
   than tune it away.

There is no EVOLVE V in the published record. Conrad died in 2004.
