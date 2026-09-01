# artificial-ecosystems

A 2026 reconstruction of **Conrad & Pattee (1970), "Evolution Experiments with an Artificial Ecosystem"** — and a place to rerun that experiment with LLMs and multi-agent systems, 56 years later.

> “The only way to approach this problem is to design an artificial ecosystem which we can test and modify.”
> — Conrad & Pattee, 1970

[Journal of Theoretical Biology 28: 393–409](https://doi.org/10.1016/0022-5193(70)90077-9)

## Why this paper

Most evolutionary simulations impose a fitness function. Conrad and Pattee refused to. They built a small closed world with a **conservation law for matter** (“chips”), cell-like organisms that could collect, cooperate, repair, recombine, and reproduce, and then *watched what appeared*.

Selection was not a score. It was bookkeeping.

That move is the ancestor of Tierra, Avida, and a lot of artificial life. It is also the opposite of how most LLM-agent demos work today (a rubric, a judge, a leaderboard). The bet of this repo is that Conrad’s stance is the more interesting one to revive.

## What is in here

```
src/evolve1970/       1970 world + amenability + modifier codon
src/evolve4/          IV: two metabolites, producers/recyclers, construction
src/evolve_modern/    same 1970 physics; controllers may be language policies
docs/evolve-family.md
docs/original-model.md
docs/quiet-vs-noisy.md
docs/unused-sequences.md
docs/amenability.md
docs/evolve4.md
experiments/run_classic.py
experiments/run_quiet_noisy.py
experiments/run_unused.py
experiments/run_amenability.py
experiments/run_niches.py
```

The reconstruction is documented, including the assumptions we had to make because the 1970 source code is lost and the paper is paywalled. See [`docs/original-model.md`](docs/original-model.md).

## Run it

```bash
python3 -m pip install -r requirements.txt
PYTHONPATH=src python3 -m evolve1970
PYTHONPATH=src python3 -m evolve_modern
PYTHONPATH=src python3 experiments/run_classic.py
PYTHONPATH=src python3 experiments/run_quiet_noisy.py
PYTHONPATH=src python3 experiments/run_unused.py
PYTHONPATH=src python3 experiments/run_amenability.py
PYTHONPATH=src python3 -m evolve4
PYTHONPATH=src python3 experiments/run_niches.py
```

You should see population size, lineage count, and a running conservation check:

```
chips[place/body/pool] = …   conserved = 4000
```

If that number ever drifts, the world is broken.

## The 1970 design, in one paragraph

A circular one-dimensional world of *places*. Each place has an abiotic state (A or B) and a pile of chips. Organisms occupy a territory of contiguous places. Each organism has a genome of symbol pairs that decode into a cyclic program over six primitives (`collect`, `forage`, `cooperate`, `repair`, `reproduce`, `wait`). Behaviour also depends on an internal state and a local input state. Chips are spent on metabolism, repair, and offspring. The dead return their chips to a matter pool that rains back onto the world. Mutation is point + length; recombination is break-and-splice. No fitness function.

## What Conrad reported, and what we want to see again

1. Phenotype–environment matching rises when the world is quiet.
2. Noise produces diversity rather than a slide toward one type.
3. Recombination rate tends to fall.
4. Utilization of the environment tends to rise.
5. Successful genomes carry sequences that are never executed.

`experiments/run_classic.py` is the start of that checklist.
`experiments/run_quiet_noisy.py` is observations (1) and (2): a still
A/B world versus one where places flicker. First rerun, four seeds,
280 steps:

- matching rose in both worlds and rose *more* when the world was quiet
  (0.56 → 0.84 quiet, 0.55 → 0.72 noisy)
- the noisy world kept more lineages and higher Shannon diversity
- chips stayed conserved

Write-up: [`docs/quiet-vs-noisy.md`](docs/quiet-vs-noisy.md).

`experiments/run_unused.py` is observation (5). Structural unused *rises*
among the rich (0.30 → 0.35) while dynamic unused falls. Winners fire
the distinct actions they encode and keep extra copies of `forage`.
Dead tape hitchhikes. Write-up: [`docs/unused-sequences.md`](docs/unused-sequences.md).

`experiments/run_amenability.py` is the 1980/1985 claim that evolvability
is selectable. A modifier codon, not executed, sets how children mutate.
Amenability falls in every world and falls most in a slowly flickering
one — EVOLVE II’s “resistance to change.” Write-up: [`docs/amenability.md`](docs/amenability.md).

## The EVOLVE episodes

One program, four numbered models, twenty-nine years. The invariant
is the 1970 refusal: do not impose a fitness function. What changes
is how rich the closed world is allowed to be. Full write-up:
[`docs/evolve-family.md`](docs/evolve-family.md).

```
1970   Conrad & Pattee      chips, 1-D ring, six routines
1981   EVOLVE               light, temperature, amenability locus
1985   EVOLVE II            scheduled abiotic change → canalization
1985   EVOLVE III           2-D, 15 traits, critical vs modifier DNA
1989   "artificial worlds"  the method gets a name
1992   Tierra (sideways)    CPU time as the conserved resource
1998   EVOLVE IV            metabolites + niche construction
2004   —                    Conrad dies. There is no V.
2026   this repo            same refusal; language as a mutator
```

**1970 — Conrad & Pattee.** A 1-D ring, chips, six routines, no
score. Matching rises when the world is quiet. Noise keeps types
around. Successful tapes carry unused sequence. This is
`src/evolve1970`.

**1981 — EVOLVE.** Light, temperature, three genes, an amenability
locus. The new claim: evolvability itself is selectable.
`experiments/run_amenability.py`.

**1985 — EVOLVE II.** The abiotic world is put on a schedule. In
slowly varying conditions, organisms develop resistance to
phenotypic change — canalization without being programmed.

**1985 — EVOLVE III** (Rizki & Conrad). Two-dimensional regions,
fifteen quantitative traits, producers and decomposers, a nucleic
acid string split into critical sections and modifier sections.
Parasitism appears in a 1992 extension. Mutualism does not, because
an organism cannot eat both the environment and a neighbour at once.
This repo’s last codon pair, not executed, is that split in miniature.

**1989 — “artificial worlds.”** Conrad & Rizki name the method.
Mass, energy, genomes, phenomes, a map between them. Fitness and
population dynamics both emerge.

**1998–1999 — EVOLVE IV** (Brewster & Conrad). Metabolites and
niche construction. Organisms exchange chemical species *and*
modify the ground under their neighbours. They report that niches
form. There is no EVOLVE V.

`src/evolve4` reconstructs both published interactions. Producers
turn nutrient into waste. Recyclers turn waste back into nutrient.
Each body also carries a taste for the local condition and a
construct gene that pushes that condition up or down. Conversion,
taste, and construct are heritable. No score.

First rerun, four seeds. Both metabolic types persist in roughly
equal numbers. On a packed ring the neighbour-niche index saturates
either way. On a sparse ring, construction is what sorts them
(niche 0.74 without digging, 0.88 with it). Chips stay conserved.

```
PYTHONPATH=src python3 -m evolve4
# t=225  N=273  P/R=147/128  conserved=4000  niche=1.00
PYTHONPATH=src python3 experiments/run_niches.py
```

Write-up: [`docs/evolve4.md`](docs/evolve4.md).

**Sideways, 1991–92.** Ray’s Tierra substitutes CPU time for chips.
Same stance, different conserved resource.

**2026.** `evolve_modern` keeps the chip physics and lets a language
model act only as a mutator. Not a judge.

## The 2026 extension

`evolve_modern` keeps the chip world untouched. What changes is the **variation operator**:

- a lineage can carry a short natural-language policy
- a tiny deterministic interpreter compiles that policy + a local percept into one of the six 1970 primitives
- an LLM, when present, is asked only at birth to rewrite the child’s policy

The model is a mutator, not a judge. That is the whole point.

Plug in your own mutator by replacing `heuristic_mutate_policy` in `src/evolve_modern/agents.py` with a call to whatever API you like. Keep the interpreter deterministic so two labs can reproduce each other’s runs.

## Status

This is a research sketch, not a museum-grade replica. The six primitives, the rain schedule, and the metabolic-cost rule are reconstruction choices. If you have the 1970 paper PDF, EVOLVE source, or a clearer description of the original routine set, open an issue.

## License

MIT. The 1970 paper remains under its publisher’s copyright; this repo contains no verbatim text from it.
