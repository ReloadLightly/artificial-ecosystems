# Unused phenome sequences

Conrad and Pattee’s fifth qualitative result:

> Dominant organisms often carried phenome sequences that were never
> executed — sequence of no selective value.

This is the junk-DNA observation, twenty years before anyone called it
that.

## What “unused” means here

The genome decodes into a short cyclic program over six primitives.
Two different kinds of unused tape are logged.

**Structural unused.** Slots that only repeat an action already on the
tape. A program `forage, forage, repair` is one-third structural unused.
The second `forage` does not add a phenome symbol.

**Dynamic unused.** Unique encoded actions that never fired during that
organism’s life. An organism that carries `cooperate` but never meets a
neighbour has dynamic unused tape.

Random genomes of typical seed length already have about 0.28
structural unused. The question is whether selection *cleans* the tape
or whether the extra slots ride along with winners.

## What we ran

```bash
PYTHONPATH=src python3 experiments/run_unused.py
```

Four seeds, 280 steps, quiet world, 4000 chips. Conservation held.

| metric | early | late |
|---|---:|---:|
| structural unused | 0.264 | **0.313** |
| dynamic unused | 0.141 | 0.061 |
| rich structural | 0.298 | **0.350** |
| poor structural | 0.236 | 0.254 |
| mean genome length | 11.7 | 10.7 |

Final snapshot: structural unused is 0.337 in the richest quartile and
0.263 in the poorest. The largest lineage sits at 0.317. Dynamic unused
among organisms that lived at least five steps is 0.057.

Richest organism in each seed:

- 1970 — `forage forage repair` — fired forage, repair
- 1971 — `repair cooperate forage collect forage repair` — fired forage, repair
- 1985 — `forage collect forage` — fired collect, forage
- 2026 — `collect repair wait forage forage` — fired collect, forage, repair, wait

## How to read it

The tape gets *messier*, not cleaner, among the organisms that hold the
chips. Dynamic unused falls: winners do fire the distinct actions they
bother to encode. Structural unused rises and is higher in the rich
quartile than in the poor one. The extra slots are copies of an action
that already works — usually `forage`.

That is hitchhiking. A second `forage` codon is nearly invisible to
selection. It costs a little metabolism (genome length) and does no
new work, so it is “of no selective value” in Conrad’s sentence. It
is also not costly enough to be purged, so it travels with the lineage
that found a paying routine.

The last codon pair is now a modifier section and is not executed
(see amenability). Structural unused is measured on the critical
section only. The observation survives that split.

## What this is not

It is not a claim that longer genomes win. Mean length fell. It is a
claim about *composition*: the remaining tape of successful organisms
is more repetitive than the tape of unsuccessful ones, and more
repetitive than a random draw.
