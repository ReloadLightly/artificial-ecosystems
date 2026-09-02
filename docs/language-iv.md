# Language-guided variation on EVOLVE IV-inspired physics

> **Status: withdrawn integration design.** The IV-language experiment is not
> executable. Both previously advertised commands fail because
> `MetabolicConfig` has no `language` option, and the simulator has no complete
> policy execution, inheritance, or mutation path. The former numerical table
> and empirical interpretation have been removed because they were not results
> of the current engine.

## What exists

The repository contains useful but disconnected scaffolding:

- `src/evolve4` implements a two-metabolite, construction-capable world inspired
  by EVOLVE IV;
- `src/evolve_modern/iv_policies.py` contains text-policy parsing and heuristic
  mutation helpers; and
- `src/evolve_modern/iv.py` sketches how the two layers might be attached.

That is design material, not an integrated experiment. IV organisms do not
currently store a policy, the step loop does not ask a policy for an action,
newborns do not inherit or mutate policies, and no working run invokes a real
model.

## Intended separation

| Layer | Responsibility | Constraint |
|---|---|---|
| Physics | Metabolism, movement, construction, fission, death, conservation | Never delegate matter accounting to text or a model |
| Controller | Convert a typed local percept into a typed intent | Deterministic and replayable for a fixed program |
| Variation operator | Propose a child controller at reproduction | Never score or select organisms |
| Experiment harness | Match budgets, cache proposals, record provenance | Compare operators in the same ecological world |

The research question is not whether fluent text can control a bug. It is
whether semantic variation changes evolvability while ecological persistence
remains the only selector.

## Repair design

A safe integration should introduce explicit types such as `IVPercept`,
`IVIntent`, `IVTraits`, and `IVController`. Movement needs a tri-state intent
(`default`, `stay`, or a validated target) so omission cannot accidentally mean
an action. Controllers should live in a registry keyed by organism ID until the
physics model has a deliberate controller field and inheritance contract.

The first executable controller format should be a small typed DSL or JSON AST,
not substring matching over unrestricted English. That gives grammar-preserving
mutation, validation, serialization, and deterministic replay a common target.
Language models can later propose typed rewrites that pass the same parser and
validator as every other operator.

Randomness for scheduling, physics, reproduction, controller mutation, and any
model sampling should be separated. A no-controller golden trace must remain
unchanged when the integration is disabled.

## Evidence bar before re-advertising commands

1. The ordinary EVOLVE IV-inspired run is unchanged with controllers disabled.
2. A fixed controller produces a deterministic, unit-tested intent.
3. Intent changes the intended action without bypassing metabolism or
   conservation.
4. Every newborn receives the specified inherited or mutated controller.
5. Fixed seeds replay identical trajectories with cached model responses.
6. All documented commands have smoke tests.
7. Bit, GP, random-edit, and model-assisted treatments use matched proposal and
   edit-size budgets.
8. Results are generated from raw artifacts with failure rates and uncertainty,
   not copied into this page by hand.

Until those conditions hold, this page is a roadmap and the IV-language result
claim remains withdrawn.
