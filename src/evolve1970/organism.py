"""Cell-like organisms with a genotype–phenotype map and conserved chips.

Reconstruction notes (Conrad & Pattee 1970; Conrad 1981; Rizki & Conrad 1985):

* The genome is a string of symbols. Sixteen possible genomic pairs map onto
  six phenome symbols. We use a compact analog: each codon is two symbols
  drawn from {0,1,2,3} (16 combinations) mapped to one of six actions.
* Immediate behaviour depends on an internal state and an input state
  (local abiotic pattern + presence of neighbours).
* Chips are stored internally and spent on self-repair and reproduction.
* Reproduction uses point mutation, length mutation, and optional
  recombination (break-and-splice of two parental genomes).
* No explicit fitness function is imposed. Persistence and reproduction
  emerge from chip accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

import numpy as np


GENOME_ALPHABET = (0, 1, 2, 3)  # 4 symbols → 16 possible pairs
N_PHENOME = 6

# Phenome / action vocabulary (the "fixed set of routines")
# 0 collect   – take chips from the current place
# 1 forage    – take chips from a random place in territory
# 2 cooperate – donate chips to a neighbouring organism
# 3 repair    – spend chips to reset wear / age pressure
# 4 reproduce – attempt fission if enough chips stored
# 5 wait      – hold position, small metabolic cost only
ACTION_NAMES = ("collect", "forage", "cooperate", "repair", "reproduce", "wait")


def pair_to_action(a: int, b: int) -> int:
    """Map a genomic pair onto one of six phenome symbols."""
    return (a * 4 + b) % N_PHENOME


def decode_program(genome: Sequence[int]) -> List[int]:
    """Decode genome into a cyclic behavioural program."""
    if len(genome) < 2:
        return [5]  # wait
    program = []
    for i in range(0, len(genome) - 1, 2):
        program.append(pair_to_action(int(genome[i]), int(genome[i + 1])))
    return program or [5]


@dataclass
class Organism:
    genome: List[int]
    position: int
    stored_chips: int = 8
    age: int = 0
    reproductions: int = 0
    internal_state: int = 0
    alive: bool = True
    territory: int = 1
    parent_id: int | None = None
    organism_id: int = 0
    amenability: float = 0.15  # Conrad: evolvability itself is a trait
    program_index: int = 0
    chips_collected: int = 0
    chips_donated: int = 0

    program: List[int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.genome = [int(g) % 4 for g in self.genome]
        if len(self.genome) < 2:
            self.genome = [0, 1]
        self.territory = max(0, min(4, int(self.territory)))
        self.program = decode_program(self.genome)
        # Amenability is also encoded loosely in genome length / composition
        # so it can evolve rather than stay a free parameter.
        if len(self.genome) >= 4:
            self.amenability = 0.05 + 0.25 * (self.genome[-1] / 3.0)

    def next_action(self, input_state: int) -> int:
        """Behaviour depends on internal state + input state (1970)."""
        idx = (self.program_index + self.internal_state + input_state) % len(self.program)
        action = self.program[idx]
        self.program_index = (self.program_index + 1) % len(self.program)
        self.internal_state = (self.internal_state + input_state + action) % 8
        return action

    def metabolic_cost(self) -> int:
        # Longer genomes and larger territories cost more to maintain.
        return 1 + (len(self.genome) // 16) + (self.territory // 4)

    def reproduction_threshold(self) -> int:
        return 8 + len(self.genome) // 2

    def wear(self) -> float:
        """Probability of death this step before repair. Rises with age."""
        return min(0.12, 0.002 + 0.0015 * self.age)

    def genotype_signature(self) -> tuple:
        return tuple(self.genome[:16])


def random_genome(rng: np.random.Generator, length: int = 12) -> List[int]:
    length = max(2, length if length % 2 == 0 else length + 1)
    return rng.integers(0, 4, size=length).tolist()


def mutate(
    genome: Sequence[int],
    rng: np.random.Generator,
    amenability: float,
) -> List[int]:
    """Point mutations plus occasional insertions/deletions of codon pairs.

    Amenability raises the chance that a mutation is a *small* change
    (Conrad's 'modifier sections' / amenability-to-evolution).
    """
    g = list(genome)
    p_point = 0.08 + 0.25 * amenability
    for i in range(len(g)):
        if rng.random() < p_point:
            if rng.random() < amenability:
                # Small step: ±1 on the alphabet, wrapping.
                g[i] = (g[i] + rng.choice([-1, 1])) % 4
            else:
                g[i] = int(rng.integers(0, 4))

    # Size mutations (codon pair insert/delete)
    if rng.random() < 0.05 + 0.1 * amenability:
        if rng.random() < 0.5 and len(g) >= 4:
            cut = rng.integers(0, len(g) - 1)
            if cut % 2 == 1:
                cut -= 1
            del g[cut : cut + 2]
        elif len(g) < 40:
            ins = rng.integers(0, 4, size=2).tolist()
            pos = int(rng.integers(0, len(g) + 1))
            if pos % 2 == 1:
                pos -= 1
            g = g[:pos] + ins + g[pos:]
    if len(g) < 2:
        g = [0, 1]
    if len(g) % 2 == 1:
        g.append(int(rng.integers(0, 4)))
    return g


def recombine(
    a: Sequence[int],
    b: Sequence[int],
    rng: np.random.Generator,
) -> List[int]:
    """Break-and-splice at a random codon boundary (1970 recombination)."""
    if len(a) < 2 or len(b) < 2:
        return list(a)
    ca = (len(a) // 2)
    cb = (len(b) // 2)
    cut_a = int(rng.integers(1, max(2, ca))) * 2
    cut_b = int(rng.integers(1, max(2, cb))) * 2
    child = list(a[:cut_a]) + list(b[cut_b:])
    if len(child) < 2:
        child = list(a)
    if len(child) % 2 == 1:
        child.append(0)
    return child[:40]
