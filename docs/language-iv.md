# Natural-language policy prototype

This is a small, offline demonstration of a possible 2026 extension: organisms can carry short strategy text while a deterministic compiler maps that text onto the same primitive actions used by the conserved-chip world.

It does **not** call a language model. Offspring policies are changed by a hand-written heuristic. The prototype demonstrates an interface, not model-assisted evolution.

## Why keep it

The design separates three roles that should remain separate in a future experiment:

1. a proposal mechanism writes or rewrites a program;
2. a deterministic interpreter executes the program;
3. the ecosystem—not a model judge—selects through survival and reproduction.

That separation is the useful idea. The former collection, qualification, cached-response, and matched-variation scaffolding was removed from `main` because it had not produced an authentic model comparison. It remains in Git history at commit `82938ca`. A much smaller replacement has now completed one fixed-proposal comparison and published its cache and results.

## Current pieces

| file | role |
|---|---|
| `src/evolve_modern/agents.py` | text policies, keyword interpreter, heuristic rewrite |
| `src/evolve_modern/simulation.py` | policy-carrying organisms on the conserved-chip world |
| `src/evolve_modern/iv_policies.py` | typed EVOLVE IV program schema and validation |
| `src/evolve_modern/iv.py` | controller boundary between programs and metabolic physics |
| `experiments/run_semantic_variation.py` | frozen-proposal offline founder assay |
| `experiments/cache/semantic-variation-v1.jsonl` | 24 attested agent-surface responses |
| `results/semantic-variation-v1/` | complete rows, summary, figure, and checksums |

Run the toy text-policy world:

```bash
PYTHONPATH=src python3 -m evolve_modern
```

Run the typed-controller integration:

```bash
PYTHONPATH=src python3 experiments/run_language_iv.py
```

## The completed first model study

The first study uses 24 frozen program-level proposals and compares them with same-mask typed and random proposals plus exact-parent inheritance. Ecology alone determines rare-lineage establishment and an absolute, unnormalized famine-response endpoint. The model sees the parent program and requested change fields, but no fitness score or ecological observations in the explicit task message.

No live model call occurs inside the simulation. The cache contains 24/24 strict-valid final answers and the offline replay produces all 768 case–seed–arm rows. In this fixed bank, the model-assigned arm showed no observed establishment advantage over either baseline; the wide intervals are not evidence of equivalence. See the [README](../README.md#current-result-no-observed-semantic-proposal-establishment-advantage-in-the-first-fixed-bank) for the result, limitations, and exact replay command.

The next step is replication across proposal samples and held-out worlds, with a normalized recovery endpoint. It is not a larger collection framework or a claim that this agent-surface comparison is genetic programming.
