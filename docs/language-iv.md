# Language as a mutator, on EVOLVE IV physics

The 1970 overlay in `evolve_modern` writes policies over the six
Conrad primitives. This page is the same stance on the *last*
numbered world: metabolites, construction, no fitness function.

The model is asked only at birth. The interpreter never calls it.

## Split

| layer | lives in | may do | may not do |
|---|---|---|---|
| physics | `src/evolve4` | convert N↔W, push condition, die, conserve | score anyone |
| compiler | `src/evolve_modern/iv_policies.py` | read role / taste / construct from English; pick a neighbour, withhold digging, shift the fission threshold | invent matter |
| mutator | same file, or your API | rewrite the child's policy | judge the parent |

`Intent` is the only thing the text is allowed to change in a step.
Metabolism, excretion, death, and the conservation check run
afterward, identically for a bit-string bug and a language bug.

## How a policy compiles

```
"I am a recycler. Eat waste. Lower the ground; I prefer acid.
 Seek a producer neighbour. Reproduce only when rich."
```

- `compile_traits` → recycler, taste −1, construct −1
- `interpret_iv_policy` + a local percept → stand next to a
  producer if one is adjacent, do not fission until stored is
  six above the default, keep digging

Unmentioned traits inherit from the parent. That is the IV analog
of a modifier section: the sentence you do not write is not
re-rolled.

## Offline mutator, and how to plug in a model

Default is `heuristic_mutate_iv_policy`: append, swap, or replace
a clause. No network.

To use a real model, wrap any `prompt → text` callable:

```python
from evolve_modern.iv import attach_language
from evolve_modern.iv_policies import make_llm_mutator

def complete(prompt: str) -> str:
    # your API
    return client.chat(...)

sim = MetabolicSim(MetabolicConfig(language=True, ...))
attach_language(sim, mutator=make_llm_mutator(complete))
```

Keep the interpreter deterministic. Two labs with the same seed
and the same child policies should replay each other.

## What we ran

```bash
PYTHONPATH=src python3 -m evolve_modern.iv
PYTHONPATH=src python3 experiments/run_language_iv.py
```

Sparse IV world (96 places, cap 90), four seeds, 200 steps.
Construction on. Language off versus on.

| | bits | language |
|---|---:|---:|
| producers late | 44.3 | 43.8 |
| recyclers late | 43.0 | 43.6 |
| niche late | 0.86 | **0.89** |
| construct-match late | 0.36 | **0.57** |
| distinct policies | — | 63.5 |
| conserved | yes | yes |

Both metabolic types persist. Niches still form. The new fact is
construct-match: in the bit world taste and construct mutate as
independent flips, so “build what I like” is an accident. In the
language world they are usually *the same sentence*, so they
hitchhike. That is not a fitness trick. It is a fact about how
English packages traits.

Surviving policies drift. Some stay long and specific. Some
collapse to a clause (“Prefer alkali.”). Role is then inherited,
the same way an unused codon hitchhiked in 1970.
