# Program repetition and execution coverage

Conrad and Pattee reported that some successful organisms carried phenome
sequences that were not executed. That observation is historically important:
it asks whether an evolving system can retain encoded material that is not
expressed under the conditions it encounters.

The present simulator does **not** yet implement the original A–F phenome and
its conditional, parametric execution semantics. This experiment is therefore
a diagnostic of the current cyclic controller, not a reproduction of the 1970
result.

## What is measured

The repaired experiment keeps two questions separate.

### Repeated action fraction

`repeated_action_fraction` is

```text
1 - number of distinct action symbols / number of program slots
```

For example, `forage, forage, repair` has a repeated-action fraction of
one-third. This measures symbol repetition only. A repeated slot is not
necessarily redundant: in a cyclic controller it can change action frequency,
phase, internal-state transitions, and downstream behaviour. The metric must
therefore not be described as an "unused" or selectively neutral fraction.

### Position-level execution coverage

`mean_unexecuted_slot_fraction` measures decoded **positions** that were not
selected during the observation period. Positions are tracked separately even
when they encode the same action. This corrects the former implementation,
which remembered only which action types had fired and could not distinguish
two occurrences of `forage`.

Execution coverage remains exposure-dependent. A young organism, or one
observed for only a few steps, has had fewer opportunities to visit its whole
program. Results should therefore report the age or observation-window rule
and should not equate an unvisited slot with a functionless slot.

## Run the diagnostic

```bash
PYTHONPATH=src python3 experiments/run_unused.py
```

The command uses the repository's fixed-seed diagnostic configuration and
checks chip conservation. Its opening JSON block reports
`repeated_action_fraction` and `mean_unexecuted_slot_fraction`. No canonical
numerical result is published here until the repaired metric has been tested
and the result bundle can be regenerated from a recorded revision and
environment.

## Questions this diagnostic can answer

- Does action-symbol repetition change between predefined early and late
  windows in this implementation?
- How much of each program has actually been visited after controlling for
  organism age and program length?
- Do observed repetition levels differ from length-matched random programs?
- Are any differences robust across seeds rather than driven by one population?

Stored-chip strata may be reported as exploratory descriptions, but they are
not independent samples and should not be called "winners" and "losers."
Lineage-aware or population-level uncertainty is needed for comparisons.

## What would support the historical claim

A source-faithful test requires the original-style phenome semantics, including
conditional branches, followed by position-level traces across each
organism's life. A stronger test would also intervene on an unexecuted segment:
delete or replace it and show that behaviour and reproductive persistence are
unchanged in the relevant environments. Until those pieces exist, this page
documents a controller diagnostic rather than evidence for neutral sequence,
hitchhiking, or an analogy to noncoding DNA.
