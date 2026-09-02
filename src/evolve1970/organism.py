"""Cell-like organisms with a genotype–phenotype map and conserved chips.

Reconstruction notes (Conrad & Pattee 1970; later EVOLVE work):

* Genome pairs map onto six local action symbols; the alphabet and modulo
  decoder are reconstruction choices.
* A later-EVOLVE-inspired modifier pair is available only when explicitly
  enabled.
* The default conserved-chip prototype executes every complete genome pair.
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


def decode_program(
    genome: Sequence[int], *, reserve_modifier: bool = False
) -> List[int]:
    """Decode genome into a cyclic behavioural program.

    ``reserve_modifier`` is an explicit later-EVOLVE-inspired extension. When
    enabled, the final pair is withheld from execution if at least one other
    complete pair remains.
    """
    g = list(genome)
    if reserve_modifier and len(g) >= 4:
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
    modifier_enabled: bool = False
    program_index: int = 0
    chips_collected: int = 0
    chips_donated: int = 0
    executed_actions: set[int] = field(default_factory=set, repr=False)
    executed_slots: set[int] = field(default_factory=set, repr=False)
    decision_count: int = 0
    program: List[int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.genome = [int(g) % 4 for g in self.genome]
        if len(self.genome) < 2:
            self.genome = [0, 1]
        if len(self.genome) % 2 == 1:
            self.genome.append(0)
        if self.modifier_enabled and len(self.genome) < 4:
            self.genome.extend([0, 0])
        self.territory = max(0, min(4, int(self.territory)))
        self.program = decode_program(
            self.genome, reserve_modifier=self.modifier_enabled
        )
        if self.modifier_enabled and len(self.genome) >= 4:
            rate = self.genome[-2] / 3.0
            step = self.genome[-1] / 3.0
            self.amenability = 0.05 + 0.15 * rate + 0.15 * step

    def next_action(self, input_state: int) -> int:
        idx = (self.program_index + self.internal_state + input_state) % len(self.program)
        action = self.program[idx]
        self.executed_actions.add(action)
        self.executed_slots.add(idx)
        self.decision_count += 1
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

    def repeated_action_slot_fraction(self) -> float:
        """Fraction of slots duplicating an action identity used elsewhere.

        This is a repetition measure, not a measure of nonexecution or
        selective neutrality.
        """
        if not self.program:
            return 1.0
        return max(0.0, 1.0 - len(set(self.program)) / len(self.program))

    def unexecuted_slot_fraction(self) -> float:
        """Fraction of indexed program slots not selected in this lifetime."""
        if not self.program:
            return 1.0
        return max(0.0, 1.0 - len(self.executed_slots) / len(self.program))

    def program_names(self) -> List[str]:
        return [ACTION_NAMES[a] for a in self.program]


def random_genome(rng: np.random.Generator, length: int = 12) -> List[int]:
    length = max(2, length if length % 2 == 0 else length + 1)
    return rng.integers(0, 4, size=length).tolist()


def mutate(
    genome: Sequence[int],
    rng: np.random.Generator,
    amenability: float,
    *,
    reserve_modifier: bool = False,
) -> List[int]:
    g = list(genome)
    if len(g) % 2 == 1:
        g.append(int(rng.integers(0, 4)))
    if reserve_modifier:
        if not g:
            g = [0, 1, 0, 1]
        elif len(g) == 2:
            # Preserve the supplied pair as the modifier and prepend the
            # smallest executable section.
            g = [0, 1] + g

    p_point = 0.08 + 0.25 * amenability
    for i in range(len(g)):
        if rng.random() < p_point:
            if rng.random() < amenability:
                g[i] = (g[i] + rng.choice([-1, 1])) % 4
            else:
                g[i] = int(rng.integers(0, 4))
    if rng.random() < 0.05 + 0.1 * amenability:
        if reserve_modifier:
            executable = g[:-2]
            modifier = g[-2:]
            delete_pair = rng.random() < 0.5
            if delete_pair and len(executable) >= 4:
                cut = 2 * int(rng.integers(0, len(executable) // 2))
                del executable[cut : cut + 2]
            elif not delete_pair and len(g) < 40:
                insertion = rng.integers(0, 4, size=2).tolist()
                position = 2 * int(
                    rng.integers(0, len(executable) // 2 + 1)
                )
                executable = (
                    executable[:position]
                    + insertion
                    + executable[position:]
                )
            g = executable + modifier
        else:
            if rng.random() < 0.5 and len(g) >= 4:
                cut = int(rng.integers(0, len(g) - 1))
                if cut % 2 == 1:
                    cut -= 1
                del g[cut : cut + 2]
            elif len(g) < 40:
                insertion = rng.integers(0, 4, size=2).tolist()
                position = int(rng.integers(0, len(g) + 1))
                if position % 2 == 1:
                    position -= 1
                g = g[:position] + insertion + g[position:]
    minimum_length = 4 if reserve_modifier else 2
    while len(g) < minimum_length:
        g.extend([0, 1])
    return g


def recombine(
    a: Sequence[int],
    b: Sequence[int],
    rng: np.random.Generator,
    *,
    reserve_modifier: bool = False,
) -> List[int]:
    """Splice two genomes without crossing an enabled modifier boundary.

    In modifier mode, only executable pairs recombine. The first (reproducing)
    parent's modifier is inherited intact here and can subsequently change in
    :func:`mutate`. This is an explicit extension rule, not a historical claim.
    """
    if len(a) < 2 or len(b) < 2:
        return list(a)

    left = list(a)
    right = list(b)
    if len(left) % 2 == 1:
        left.append(0)
    if len(right) % 2 == 1:
        right.append(0)

    if reserve_modifier:
        if len(left) < 4:
            left = [0, 1] + left
        if len(right) < 4:
            right = [0, 1] + right
        executable_a, modifier = left[:-2], left[-2:]
        executable_b = right[:-2]
    else:
        executable_a = left
        executable_b = right
        modifier = []

    ca = len(executable_a) // 2
    cb = len(executable_b) // 2
    cut_a = int(rng.integers(1, max(2, ca))) * 2
    cut_b = int(rng.integers(1, max(2, cb))) * 2
    child_executable = executable_a[:cut_a] + executable_b[cut_b:]
    if len(child_executable) < 2:
        child_executable = executable_a or [0, 1]

    max_executable = 38 if reserve_modifier else 40
    return child_executable[:max_executable] + modifier
