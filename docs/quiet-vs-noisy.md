# Quiet versus noisy reconstruction diagnostic

> **Status: runnable diagnostic, not a historical replication.** Earlier
> numerical tables and claims on this page were withdrawn after the executable
> program metric and modifier boundary were repaired. No canonical result will
> be published here until it is generated from a versioned result bundle.

## Historical motivation

Conrad and Pattee compared a stable System I with a disturbed System III. The
published observations motivate two questions for a future source-faithful
suite: does phenotype–environment matching increase in the stable treatment,
and does disturbance sustain continuing compositional change?

The current command tests analogous questions in the repository's compact
conserved-chip prototype. Its six actions, sequential scheduler, matching
bonus, environmental representation, and disturbance process are
reconstruction choices. A result here cannot be attributed to the 1970 model.

## Current operationalization

The world is a 48-place ring. Each place has a binary abiotic state arranged in
stable patches.

- **Quiet:** place states do not change.
- **Noisy:** every place independently flips state each step with probability
  `0.10` by default.

Each organism's first genomic symbol defines a preferred binary state. A match
changes harvest amount and forage choice; it is therefore part of the simulated
ecology, not a score assigned after a run.

The command reports:

- `match_ratio`, observed as organisms act during the sequential update;
- `match_weighted`, recomputed over post-step survivors and weighted by stored
  chips;
- Shannon entropy over truncated genotype signatures;
- the count of distinct truncated genotype signatures;
- chips stored in living bodies;
- repeated-action slots; and
- population size and chip conservation.

These measures have deliberately narrow names. Genotype signatures are not
genealogical lineages, body-chip stock is not automatically environmental
utilization, and action repetition is not unexecuted or neutral sequence.
Because `match_ratio` and `match_weighted` use different observation frames,
they also should not be read as unweighted and weighted versions of precisely
the same sample.

## Run it

```bash
PYTHONPATH=src python3 experiments/run_quiet_noisy.py
```

The default audit uses seeds 1970, 1971, 1985, and 2026 for 280 steps and checks
start-to-finish conservation. In the current repaired run, matching increases
more in the quiet treatment. The noisy treatment does **not** finish with
higher mean genotype-signature entropy or more genotype signatures. Four seeds
without uncertainty intervals establish neither historical claim; the script
prints that limitation explicitly.

## Evidence needed next

1. Implement the published A–F phenome and mark-then-resolve update semantics.
2. Reconstruct the documented System I and System III disturbance rules from
   page-level primary-source citations.
3. Separate genealogy, full genotype identity, turnover, and abundance
   diversity instead of calling one signature count “lineages.”
4. Use paired seeds, uncertainty intervals, and predeclared early/late windows.
5. Save trajectories, configuration, environment, revision, and checksums in a
   versioned result bundle from which this page is generated.
6. Report a failed reproduction of a historical pattern as a result, not as a
   reason to retune the reconstruction after seeing the answer.
