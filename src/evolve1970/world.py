"""One-dimensional circular 'world' of places, chips, and abiotic state.

Conrad & Pattee (1970) modelled the environment as a 1-D loop of places.
Each place has a binary abiotic state (A or B) and a pile of conserved
material particles called chips. Dead organisms return chips to a shared
matter pool that can later be redistributed onto places.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np


@dataclass
class Place:
    """A single location in the 1-D world."""

    state: int  # 0 = A, 1 = B
    chips: int = 0


@dataclass
class World:
    n_places: int = 48
    total_chips: int = 4000
    seed: int | None = None
    places: List[Place] = field(default_factory=list)
    matter_pool: int = 0  # chips from decayed organisms not yet redeposited

    def __post_init__(self) -> None:
        rng = np.random.default_rng(self.seed)
        if not self.places:
            patch = 4
            self.places = [
                Place(state=int((i // patch) % 2), chips=0) for i in range(self.n_places)
            ]
        remaining = self.total_chips
        self.matter_pool = remaining // 10
        remaining -= self.matter_pool
        base, extra = divmod(remaining, self.n_places)
        for i, p in enumerate(self.places):
            p.chips = base + (1 if i < extra else 0)

    def neighbor_indices(self, index: int, radius: int) -> List[int]:
        if radius < 0:
            raise ValueError("radius must be >= 0")
        return [
            (index + offset) % self.n_places
            for offset in range(-radius, radius + 1)
        ]

    def local_view(self, index: int, radius: int) -> dict:
        idxs = self.neighbor_indices(index, radius)
        return {
            "indices": idxs,
            "states": [self.places[i].state for i in idxs],
            "chips": [self.places[i].chips for i in idxs],
            "total_chips": sum(self.places[i].chips for i in idxs),
        }

    def take_chips(self, index: int, amount: int) -> int:
        taken = min(amount, self.places[index].chips)
        self.places[index].chips -= taken
        return taken

    def deposit_chips(self, index: int, amount: int) -> None:
        self.places[index].chips += amount

    def decay_to_pool(self, amount: int) -> None:
        self.matter_pool += amount

    def rain_from_pool(self, rng: np.random.Generator, fraction: float = 0.15) -> int:
        raining = int(self.matter_pool * fraction)
        if raining <= 0:
            return 0
        self.matter_pool -= raining
        targets = rng.integers(0, self.n_places, size=raining)
        for t in targets:
            self.places[t].chips += 1
        return raining

    def chip_count_on_places(self) -> int:
        return sum(p.chips for p in self.places)

    def abiotic_vector(self) -> List[int]:
        return [p.state for p in self.places]
