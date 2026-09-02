# Mutation-control proxy

Later work in the EVOLVE family asked whether evolution could alter how
offspring vary. That is a valuable historical motivation for studying
evolvability, but the present implementation is only a modern proxy. It does
not yet recreate the later EVOLVE genotype–phenotype machinery or demonstrate
selection for canalization.

## How the proxy is encoded

The modifier experiment explicitly enables `modifier_enabled`. In that mode,
the final pair is treated as a modifier and excluded from the cyclic
behavioural program; ordinary `evolve1970` runs execute every complete pair.
The modifier's two values are mapped to a scalar in approximately
`[0.05, 0.35]`.

That scalar affects the repository's mutation operator in three ways:

- it changes the probability of point changes; and
- conditional on a point change, it changes the balance between a modulo-4
  `±1` update and a fresh symbol draw; and
- it changes the probability of a length mutation.

The population statistic is named `mean_amenability_proxy`. The suffix matters:
the value combines mutation incidence and mutation locality in one
implementation-specific number. It does not measure phenotypic robustness,
offspring fitness, adaptive potential, or canalization directly.

## Run the diagnostic

```bash
PYTHONPATH=src python3 experiments/run_amenability.py
```

The current protocol compares independent per-place environmental flip
probabilities of `0.00`, `0.02`, and `0.15` per step over fixed seeds. These are
three stochastic forcing rates, not a validated reconstruction of historical
environmental schedules. The command checks chip conservation and reports
`mean_amenability_proxy` alongside contextual population statistics in its
opening JSON block. A late-population statistic is `null` when that run ends in
extinction; absence of organisms is reported separately rather than encoded as
a modifier value of zero. Aggregate late values omit extinct runs, paired
changes use the same surviving-run cohort at both time points, and the command
prints final-extinction counts alongside them.

No numerical table is treated as a repository result until this repaired
experiment has tests, recorded revision and dependency metadata, and a
regenerable result bundle.

## How to interpret a change

A rise or fall in `mean_amenability_proxy` says only that the modifier values
became more or less common in a population under this simulator. On its own it
does not show that evolvability was selected:

- modifier values can hitchhike with behavioural loci;
- mutation rate and mutation locality are confounded in the scalar;
- population composition, birth rate, and extinction can change the mean;
- the three forcing conditions can expose different behaviours without
  isolating the modifier's causal contribution.

Terms such as "canalization," "resistance to phenotypic change," and
"selectable evolvability" require additional evidence and are deliberately not
used as conclusions here.

## Evidence needed for a stronger experiment

1. Separate mutation-incidence and mutation-locality controls.
2. Measure parent–offspring behavioural or phenotypic distance under a common
   mutation assay, rather than inferring it from the modifier value.
3. Compare an evolvable modifier with fixed, shuffled, and neutral-locus
   controls using paired seeds and uncertainty intervals.
4. Demonstrate by intervention that changing the modifier changes descendant
   variation and longer-run ecological persistence.
5. Implement the documented later-EVOLVE mechanisms before presenting the
   result as a historical reconstruction.

Until then, this command is useful as an implementation diagnostic and as a
starting point for a properly controlled evolvability experiment.
