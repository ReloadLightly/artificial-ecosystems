# Natural-language policy prototype

This is a small, offline demonstration of a possible 2026 extension: organisms can carry short strategy text while a deterministic compiler maps that text onto the same primitive actions used by the conserved-chip world.

It does **not** call a language model. Offspring policies are changed by a hand-written heuristic. The prototype demonstrates an interface, not model-assisted evolution.

## Why keep it

The design separates three roles that should remain separate in a future experiment:

1. a proposal mechanism writes or rewrites a program;
2. a deterministic interpreter executes the program;
3. the ecosystem—not a model judge—selects through survival and reproduction.

That separation is the useful idea. The former collection, qualification, cached-response, and matched-variation scaffolding was removed from `main` because it had not produced an authentic model comparison. It remains in Git history at commit `82938ca`.

## Current pieces

| file | role |
|---|---|
| `src/evolve_modern/agents.py` | text policies, keyword interpreter, heuristic rewrite |
| `src/evolve_modern/simulation.py` | policy-carrying organisms on the conserved-chip world |
| `src/evolve_modern/iv_policies.py` | typed EVOLVE IV program schema and validation |
| `src/evolve_modern/iv.py` | controller boundary between programs and metabolic physics |

Run the toy text-policy world:

```bash
PYTHONPATH=src python3 -m evolve_modern
```

Run the typed-controller integration:

```bash
PYTHONPATH=src python3 experiments/run_language_iv.py
```

## The next legitimate model study

Use one frozen batch of at most 24 coherent program-level proposals. Compare them with cost-matched typed and random proposals under identical ecological seeds. Evaluate only ecological consequences: descendant establishment, persistence, recovery after a shock, and behavioral novelty.

No live model calls should occur inside the simulation, and no new collection framework should be built unless this minimal study reveals a concrete failure that requires one.
