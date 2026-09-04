# EVOLVE IV-inspired metabolism and construction

> **Status: runnable reconstruction with one causal intervention.** The code is
> informed by Brewster and Conrad's EVOLVE IV papers, but it is not their
> recovered implementation and should not be cited as a replication.

## World

The ring contains two conserved material types:

- producers consume nutrient and return waste;
- recyclers consume waste and return nutrient.

Living organisms store matter, pay maintenance, move locally, reproduce by
splitting stored matter, and return their remaining matter to the environment
when they die. The signed `condition` of each place is not material. Organisms
may push it toward −1 or +1, and it decays toward zero.

The invariant is checked throughout the current evidence-bearing experiment:

```text
nutrient + waste + stored matter in living bodies = total_units
```

This model is intentionally compact. It does not recreate the full EVOLVE IV
chemistry, genotype–phenotype map, or niche measurements.

## Why the old niche statistic was insufficient

`StepRow.niche_index` reports the fraction of organisms with at least one
opposite metabolic type in the same or a neighboring place. It rises when:

- organisms become more spatially concentrated;
- population density rises;
- role frequencies become more balanced; or
- organisms form genuinely complementary local associations.

It therefore cannot distinguish niche organization from crowding.

## Causal place-memory experiment

[`experiments/run_niches.py`](../experiments/run_niches.py) runs 64 matched seeds
under three interventions:

1. construction off;
2. ordinary local construction;
3. construction on, with condition values permuted across places after each
   complete step.

The permutation keeps the distribution of environmental conditions but breaks
their cross-step location identity. All arms derive independent named streams
for initialization, scheduling, reproduction, mortality, and condition decay
from the same master seed, avoiding cross-mechanism RNG coupling. The
primary metric forms undirected edges between organisms in the same or
neighboring places and subtracts the expected opposite-role edge fraction given
the current producer/recycler counts.

The result bundle is in
[`results/causal-niches-v1`](../results/causal-niches-v1).

| arm | edge enrichment | local edges | raw contact |
|---|---:|---:|---:|
| construction off | −0.068 | 75.2 | 0.635 |
| local construction | +0.018 | 112.6 | 0.814 |
| place memory scrambled | +0.023 | 64.1 | 0.762 |

Local construction raises adjusted mixing relative to construction-off, but it
is statistically indistinguishable from the scrambled-place placebo (difference
−0.005; paired-bootstrap 95% interval −0.021 to +0.011). The current mechanism
therefore changes clustering and environmental heterogeneity
without establishing that persistent local environmental memory causes niche
specialization.

## Limits

The permutation occurs between complete steps. Because the simulator updates
organisms sequentially, construction can still affect later organisms within
the same step. The experiment also does not trace metabolite provenance or
measure lineage establishment. Those are substantive next experiments—not
reasons to add a larger protocol layer before running them.
