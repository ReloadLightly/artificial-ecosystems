"""Cell-like organisms with a genotype–phenotype map and conserved chips.

Reconstruction notes (Conrad & Pattee 1970; Conrad 1981; Rizki & Conrad 1985):

* Sixteen genomic pairs map onto six phenome symbols.
* Last codon pair is a modifier section (EVOLVE III) and is not executed.
* Amenability is read from that modifier pair.
* No explicit fitness function. Persistence emerges from chip accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

import numpy as np


GENOME_ALPHABET = (0, 1, 2, 3)
N_PHENOME = 6
ACTION_NAMES = ("collect", "forage", "cooperate", "repair", "reproduce", "wait")


def pair_to_action(a: int, b: int) -> int:
    return (a * 4 + b) % N_PHENOME


def decode_program(genome: Sequence[int]) -> List[int]:
    """Decode genome into a cyclic behavioural program.

    If the genome is long enough, the last codon pair is a modifier
    section (EVOLVE III) and is not executed.
    """
    g = list(genome)
    if len(g) >= 4:
        g = g[:-2]
    if len(g) < 2:
        return [5]
    program = []
    for i in range(0, len(g) - 1, 2):
        program.append(pair_to_action(int(g[i]), int(g[i + 1])))
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
    amenability: float = 0.15
    program_index: int = 0
    chips_collected: int = 0
    chips_donated: int = 0
    executed: set = field(default_factory=set, repr=False)
    program: List[int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.genome = [int(g) % 4 for g in self.genome]
        if len(self.genome) < 2:
            self.genome = [0, 1]
        self.territory = max(0, min(4, int(self.territory)))
        self.program = decode_program(self.genome)
        if len(self.genome) >= 4:
            rate = self.genome[-2] / 3.0
            step = self.genome[-1] / 3.0
            self.amenability = 0.05 + 0.15 * rate + 0.15 * step

    def next_action(self, input_state: int) -> int:
        idx = (self.program_index + self.internal_state + input_state) % len(self.program)
        action = self.program[idx]
        self.executed.add(action)
        self.program_index = (self.program_index + 1) % len(self.program)
        self.internal_state = (self.internal_state + input_state + action) % 8
        return action

    def metabolic_cost(self) -> int:
        return 1 + (len(self.genome) // 16) + (self.territory // 4)

    def reproduction_threshold(self) -> int:
        return 8 + len(self.genome) // 2

    def wear(self) -> float:
        return min(0.12, 0.002 + 0.0015 * self.age)

    def genotype_signature(self) -> tuple:
        return tuple(self.genome[:16])

    @property
    def preferred_state(self) -> int:
        return self.genome[0] % 2

    def unused_program_fraction(self) -> float:
        if not self.program:
            return 1.0
        return max(0.0, 1.0 - len(set(self.program)) / len(self.program))

    def dynamic_unused_fraction(self) -> float:
        encoded = set(self.program)
        if not encoded:
            return 1.0
        return max(0.0, 1.0 - len(self.executed & encoded) / len(encoded))

    def program_names(self) -> List[str]:
        return [ACTION_NAMES[a] for a in self.program]


def random_genome(rng: np.random.Generator, length: int = 12) -> List[int]:
    length = max(2, length if length % 2 == 0 else length + 1)
    return rng.integers(0, 4, size=length).tolist()


def mutate(genome: Sequence[int], rng: np.random.Generator, amenability: float) -> List[int]:
    g = list(genome)
    p_point = 0.08 + 0.25 * amenability
    for i in range(len(g)):
        if rng.random() < p_point:
            if rng.random() < amenability:
                g[i] = (g[i] + rng.choice([-1, 1])) % 4
            else:
                g[i] = int(rng.integers(0, 4))
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


def recombine(a: Sequence[int], b: Sequence[int], rng: np.random.Generator) -> List[int]:
    if len(a) < 2 or len(b) < 2:
        return list(a)
    ca = len(a) // 2
    cb = len(b) // 2
    cut_a = int(rng.integers(1, max(2, ca))) * 2
    cut_b = int(rng.integers(1, max(2, cb))) * 2
    child = list(a[:cut_a]) + list(b[cut_b:])
    if len(child) < 2:
        child = list(a)
    if len(child) % 2 == 1:
        child.append(0)
    return child[:40]
