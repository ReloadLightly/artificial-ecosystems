# The EVOLVE episodes

> **Pre-audit document.** This timeline contains unresolved attributions,
> historical errors, and reconstruction claims that are being corrected. Do
> not treat it as the current evidence statement. See the README's
> reviewed-baseline and fidelity sections; a source-by-source rewrite is a
> pending repair.

One research program, four numbered models, twenty-nine years.
The invariant is the sentence from 1970: do not impose a fitness
function. Let selection be the bookkeeping of a finite world.
What changes, episode to episode, is how rich that world is allowed
to be.

```
1970  Conrad & Pattee     chips, 1-D ring, six routines
1981  EVOLVE              light, temperature, amenability locus
1985  EVOLVE II           scheduled abiotic change, canalization
1985  EVOLVE III          2-D, fifteen traits, modifier sections
1989  "artificial worlds" the method gets a name
1992  Tierra (sideways)   CPU time as the conserved resource
1998  EVOLVE IV           metabolites + niche construction
2004  —                   Conrad dies. There is no V.
2026  this repo           same refusal, language as a mutator
```

## 1970 — Conrad & Pattee

*Journal of Theoretical Biology* 28: 393–409.

A one-dimensional loop of places. Each place has an abiotic state
(A or B) and a pile of conserved chips. Cell-like organisms decode
a genome of symbol pairs into a short cyclic program. They collect,
forage, cooperate, repair, reproduce, wait. The dead return chips
to a matter pool. Mutation is point and length. Recombination is
break-and-splice.

What they reported, and what this repo has rerun:

1. Matching of phenotype to environment rises when the world is quiet.
2. Noise produces types rather than a slide toward one type.
3. Recombination rate tends to fall. *(not yet isolated here)*
4. Utilization of the environment tends to rise.
5. Dominant genomes carry sequences that are never executed.

This is `src/evolve1970`.

They also wrote the line that becomes the field’s motto seventeen
years later: the only way to study the hierarchy is to build an
artificial ecosystem you can test and modify.

## 1981 — EVOLVE

Conrad, *BioSystems* and related papers.

Light, temperature, and a conserved mass that recycles. Organisms
now have three genes. One of them is an amenability locus: how
easily a trait changes under mutation. Fitness is still not a
score. Food is allocated by how well an organism matches the
current abiotic schedule.

The new claim: **evolvability itself is selectable.** Amenability
can hitchhike with useful traits. A system that is better at
evolving can outlast one that is merely well adapted right now.

`experiments/run_amenability.py` is this claim, reconstructed.

## 1985 — EVOLVE II

Conrad & Strizich, *BioSystems*.

The abiotic world is put on a schedule. Light and temperature
drift. Aging trades off against amenability. Two lineages with
different survival strategies can coexist in the same conditions.

The result that surprised them: in a *slowly* varying world,
organisms developed resistance to phenotypic change. Traits that
help the individual at the expense of the offspring can still
change, which means gene structure can be good for the lineage
and bad for a given child.

That is canalization appearing without being programmed.

## 1985 — EVOLVE III

Rizki & Conrad, *BioSystems*. Also Rizki & Conrad 1986,
O’Callaghan & Conrad 1992.

The world becomes two-dimensional and regional. Fifteen quantitative
traits (temperature and light optima and tolerances, energy budget,
protection, aggression, developmental timing, self-adaptive mutation
rate). The genome is a nucleic-acid string with **critical sections**
and **modifier sections**. Populations include producers and
decomposers. Waste becomes food after a delay. A food cycle is a
physical fact, not a diagram.

Experiments: generalists versus specialists; sources of diversity
(transient polymorphisms, selection-driven polymorphisms, character
displacement); later, parasitic feeding. Obligate and facultative
parasitism appeared. Stable mutualism did not, because an organism
could not eat both the environment and a neighbour at once.

This repo’s modifier codon — the last pair, not executed — is the
III split in miniature.

## 1989 — “artificial worlds”

Conrad & Rizki, *BioSystems* 23: 247–258.

They step back and name the family. An artificial world has mass,
energy input, physical states, genomes, phenomes, and a map between
them. Space is limited. Matter cycles. Fitness values are not
assigned. Population dynamics are not assigned either. Both emerge
from local interaction.

This is the paper that makes the 1970 move into a method.

## 1992 — Tierra, sideways

Thomas Ray reads the same conservation trick and substitutes CPU
time for chips. Parasites and hyperparasites appear. The lineage
is no longer only Conrad’s, but the stance is the same.

## 1998–1999 — EVOLVE IV

Brewster & Conrad.

- 1998. *Evolve IV: a metabolically-based artificial ecosystem
  model.* Lecture Notes in Computer Science 1447: 473–482.
- 1999. *Computer experiments on the development of niche
  specialization in an artificial ecosystem.* CEC-99.

The new ingredients are metabolites and niche construction.
Organisms exchange chemical species. They modify the local
environment to the benefit or detriment of whoever is standing
next door. The question is no longer only “does a type match
the paint on the wall?” It is “does a type *make* a wall that
another type can live on?”

They report that niche formation occurs.

There is no EVOLVE V in the published record. Conrad died in
2004. IV is the last numbered episode.

`src/evolve4` reconstructs both published interactions: two
conserved metabolites on the 1970 ring, plus a signed condition
of the ground that organisms can push. Conversion direction,
taste, and construct are heritable. On a sparse ring,
construction is what sorts producers next to recyclers
(niche 0.74 without digging, 0.88 with it). Write-up:
[`docs/evolve4.md`](evolve4.md).

## 2026 — this repo

`src/evolve1970` is I, with amenability and a modifier section
borrowed from III.

`src/evolve4` is IV.

`src/evolve_modern` keeps the chip physics and lets a language
model act only as a mutator.

The through-line across fifty-six years is one refusal. Do not
hand the organisms a rubric. Hand them a world that closes.
