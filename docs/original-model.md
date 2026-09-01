# Reconstructing Conrad & Pattee (1970)

Source paper:

> Michael Conrad & H. H. Pattee (1970).
> *Evolution experiments with an artificial ecosystem.*
> Journal of Theoretical Biology 28(3): 393–409.
> doi:10.1016/0022-5193(70)90077-9

The implementation in `src/evolve1970` is a *faithful reconstruction from
published descriptions*, not a line-by-line port of the 1970 source
(which was never released). Where the papers are silent we state the
assumption.

## What they were trying to do

Natural evolution is hierarchical: gene → individual → population →
ecosystem. Interactions *across* those levels matter. Conrad and Pattee
argued that the only honest way to study that hierarchy is to build an
artificial ecosystem you can test and modify — with **no explicit fitness
function**. Fitness, cooperation, and even “wasted” genomic sequence
should be allowed to appear.

That sentence from the 1970 framing is the project’s charter:

> “The only way to approach this problem is to design an artificial
> ecosystem which we can test and modify.”

Seventeen years later Langton would call the same stance “life as it
could be.” Ray’s Tierra (1992) reused the same conservation trick,
substituting CPU time for Conrad’s chips.

## The 1970 world

| Piece | Published detail | Reconstruction |
|---|---|---|
| Space | 1-D string of *places*, ends joined into a loop | Circular array, default 48 places |
| Place state | A or B, plus a count of *chips* | `state ∈ {0,1}`, `chips: int` |
| Matter | Strict conservation of chips | `places + organism stores + decay pool = constant` |
| Organisms | Cell-like, tied to a territory of contiguous places | `position` + `territory` radius |
| Time | Discrete two-phase events | Interaction then accounting |
| Death | Chips of the dead return to a matter pool | `World.decay_to_pool` + nutrient rain |
| Population | 200–400 in the original runs | Configurable; default 80 seed, cap 320 |

## Genotype → phenotype

Published:

- Sixteen possible pairs of genomic symbols map onto six phenome symbols.
- Immediate behaviour depends on an *internal state* and an *input state*.
- The program is a fixed repertoire of biological routines (collect,
  repair, reproduce, recombine, …) whose *use* is genetically gated.
- Mutation: point and size.
- Recombination: break and splice at random locations.
- Placement of daughters is restricted and partly under genetic control.

Reconstruction:

- Alphabet `{0,1,2,3}` → 16 pairs.
- Pair `(a,b)` maps to one of six actions:
  `collect, forage, cooperate, repair, reproduce, wait`.
- `next_action` mixes program counter, internal state, and a hash of
  the local abiotic pattern + crowding + richness.
- Amenability-to-evolution (Conrad & Rizki 1980) is itself a trait:
  it biases mutations toward small steps and is loosely encoded in
  the genome so it can hitchhike.

## What they reported

From the chapter that reprints and extends the 1970 work:

1. Match of phenotype to environment increased in noiseless runs.
2. Noise produced a diversity of types with no slide toward homogeneity.
3. Probability of recombination tended to decrease.
4. Utilization of the environment tended to increase.
5. Dominant organisms often carried phenome sequences that were never
   executed — sequence of no selective value.

Those five observations are the first experiments to replicate.

## The EVOLVE lineage

| System | Year | What was added |
|---|---|---|
| Conrad & Pattee | 1970 | 1-D world, chips, no explicit fitness |
| EVOLVE | 1981 | Light, temperature, mass recycling, 3 genes, amenability locus |
| EVOLVE II | 1985 (Conrad & Strizich) | Scheduled abiotic change; aging vs. amenability tradeoff |
| EVOLVE III | 1985 (Rizki & Conrad) | 15 quantitative traits, 2-D regions, producers/decomposers, food webs, nucleic-acid encoding with critical vs. modifier sections |

EVOLVE III’s fifteen traits, for later ports:

1. temperature optimum
2. temperature tolerance
3. light-intensity optimum
4. light-intensity tolerance
5. rate of energy intake
6. rate of energy outflow
7. minimum energy for self-repair
8. maximum energy capacity
9. energy required before reproduction
10. protection
11. aggression
12. developmental period
13. adult period
14. reproductive rate
15. mutation rate (self-adaptive)

## Assumptions we had to make

The 1970 paper is paywalled and the original code is lost. These choices
are ours, marked so they can be replaced if a better source turns up:

- Six primitives rather than the undocumented original routine set.
- Nutrient “rain” from the decay pool (the papers say chips return to a
  matter pool; they do not specify the redeposition schedule).
- Metabolic cost linear in genome length and territory.
- Death as age-dependent hazard plus starvation.
- Recombination only with a local neighbour, at a configurable rate.

## Why this still matters in the age of LLMs

Conrad’s move was to *refuse a fitness function* and let selection be
the physics of a finite world. Most modern multi-agent LLM demos do the
opposite: they score agents with a rubric. The interesting 2026
experiment is to keep Conrad’s physics and use an LLM only as a
**variation operator** — a way for a parent to rewrite a child’s
strategy text — never as a judge.
