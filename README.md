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
src/evolve1970/       faithful reconstruction of the 1970 physics + genetics
src/evolve_modern/    same physics; controllers may be language policies
docs/original-model.md
experiments/run_classic.py
```

The reconstruction is documented, including the assumptions we had to make because the 1970 source code is lost and the paper is paywalled. See [`docs/original-model.md`](docs/original-model.md).

## Run it

```bash
python3 -m pip install -r requirements.txt
PYTHONPATH=src python3 -m evolve1970
PYTHONPATH=src python3 -m evolve_modern
PYTHONPATH=src python3 experiments/run_classic.py
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

## The 2026 extension

`evolve_modern` keeps the chip world untouched. What changes is the **variation operator**:

- a lineage can carry a short natural-language policy
- a tiny deterministic interpreter compiles that policy + a local percept into one of the six 1970 primitives
- an LLM, when present, is asked only at birth to rewrite the child’s policy

The model is a mutator, not a judge. That is the whole point.

Plug in your own mutator by replacing `heuristic_mutate_policy` in `src/evolve_modern/agents.py` with a call to whatever API you like. Keep the interpreter deterministic so two labs can reproduce each other’s runs.

## Lineage this sits in

| Year | System | Note |
|---|---|---|
| 1970 | Conrad & Pattee | this paper |
| 1981 | EVOLVE | light, temperature, amenability locus |
| 1985 | EVOLVE II / III | 15 traits, 2-D regions, food cycles |
| 1989 | Conrad & Rizki | “artificial worlds” framing |
| 1992 | Ray, Tierra | CPU-time as the conserved resource |
| 1987 | Langton | “life as it could be” |

Conrad’s later claim that **evolvability itself is selectable** (amenability to evolution, hitchhiking with useful traits) is implemented as a first-class gene in `evolve1970`.

## Status

This is a research sketch, not a museum-grade replica. The six primitives, the rain schedule, and the metabolic-cost rule are reconstruction choices. If you have the 1970 paper PDF, EVOLVE source, or a clearer description of the original routine set, open an issue.

## License

MIT. The 1970 paper remains under its publisher’s copyright; this repo contains no verbatim text from it.
