# Amenability to evolution

Conrad and Rizki (1980) argued that evolvability is itself subject to
selection. EVOLVE II (Conrad & Strizich, 1985) reported that in slowly
varying environments, organisms developed resistance to phenotypic
change — gene structure that buffered mutation.

## How it is encoded

EVOLVE III split the nucleic-acid string into critical sections and
modifier sections. We do the same.

- If the genome has at least two codon pairs, the last pair is a
  **modifier**. It is not decoded into the behavioural program.
- Amenability is read from that pair and sits in roughly `[0.05, 0.35]`.
- In `mutate`, higher amenability raises the chance of a point change
  and, given a change, the chance that it is a ±1 step rather than a
  redraw.

Amenability is therefore a heritable policy about *how children differ
from parents*. It is not a fitness score.

## What we ran

```bash
PYTHONPATH=src python3 experiments/run_amenability.py
```

Three worlds, four seeds, 300 steps.

- still — patches never flip
- slow — 2% of places flip each step
- fast — 15% of places flip each step

| metric | still | slow | fast |
|---|---:|---:|---:|
| amenability early | 0.209 | 0.207 | 0.206 |
| amenability late | 0.189 | **0.174** | 0.194 |
| amenability gain | −0.020 | **−0.034** | −0.013 |
| amenability of the rich | 0.198 | 0.185 | 0.195 |
| match late | 0.844 | 0.817 | 0.677 |
| diversity late | 6.57 | 6.76 | 6.85 |

Conservation held in every run.

## How to read it

Amenability fell in every world. Once a working routine exists,
most mutations are not gifts. The *amount* of the fall tracks the
environment.

- The slow world canalized the most. That is the EVOLVE II sentence:
  resistance to phenotypic change when the world varies gradually.
- The fast world kept the most amenability. A habitat that flips under
  you still pays for children who can take a small step.
- The still world sits in between. Matching is already high; there is
  less pressure either to lock the tape or to keep exploring.

Diversity and lineage count still rise with flicker, which is the
quiet-vs-noisy result showing up again.

## What to treat as reconstruction

The map from modifier bases onto mutation rate versus step size is
ours. So is the 2% / 15% split. If the 1985 code turns up, the thing
to check is whether amenability was a mutation-rate locus, a
step-size locus, or a buffer on phenotypic effect. The qualitative
shape — slow worlds suppress change more than fast worlds — is the
part that belongs to Conrad.
