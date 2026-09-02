"""Typed controller boundary for the EVOLVE IV-inspired world.

Controllers observe immutable values and return validated intents.  They do
not receive the simulator, its random-number generator, or mutable organisms.
This keeps ecological physics and controller variation separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class MovementMode(str, Enum):
    """How a controller participates in the simulator's movement decision."""

    DEFAULT = "default"
    STAY = "stay"
    TARGET = "target"


@dataclass(frozen=True)
class IVPercept:
    """Immutable local observation supplied to an IV controller."""

    bug_id: int
    step: int
    position: int
    left: int
    right: int
    stock_here: int
    stock_left: int
    stock_right: int
    condition_here: int
    stored: int
    repro_threshold: int
    crowded: bool
    opposite_left: bool
    opposite_right: bool
    n_opposite: int


@dataclass(frozen=True)
class IVIntent:
    """A controller request that the simulator may apply this step.

    ``DEFAULT`` delegates movement to the original simulator rule, ``STAY``
    explicitly suppresses movement, and ``TARGET`` requests the supplied ring
    position.  The simulator remains responsible for checking that a target is
    in range and locally reachable.
    """

    movement: MovementMode = MovementMode.DEFAULT
    target_position: int | None = None
    construct: bool = True
    reproduce: bool = True
    repro_threshold: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.movement, MovementMode):
            raise TypeError("movement must be a MovementMode")
        if type(self.construct) is not bool:
            raise TypeError("construct must be a bool")
        if type(self.reproduce) is not bool:
            raise TypeError("reproduce must be a bool")

        if self.movement is MovementMode.TARGET:
            if type(self.target_position) is not int:
                raise ValueError("TARGET movement requires an integer target_position")
        elif self.target_position is not None:
            raise ValueError("target_position is only valid for TARGET movement")

        if self.repro_threshold is not None:
            if type(self.repro_threshold) is not int:
                raise TypeError("repro_threshold must be an integer or None")
            if self.repro_threshold < 1:
                raise ValueError("repro_threshold must be at least 1")


@dataclass(frozen=True)
class IVTraits:
    """Validated heritable metabolic and construction traits."""

    producer: bool
    taste: int
    construct: int

    def __post_init__(self) -> None:
        if type(self.producer) is not bool:
            raise TypeError("producer must be a bool")
        if type(self.taste) is not int:
            raise TypeError("taste must be an integer")
        if self.taste not in (-1, 1):
            raise ValueError("taste must be -1 or +1")
        if type(self.construct) is not int:
            raise TypeError("construct must be an integer")
        if self.construct not in (-1, 0, 1):
            raise ValueError("construct must be -1, 0, or +1")


class IVController(Protocol):
    """Minimal lifecycle contract for a deterministic IV controller."""

    def initial_traits(
        self, bug_id: int, index: int, base_traits: IVTraits
    ) -> IVTraits:
        """Return traits for a seeded organism."""
        ...

    def decide(self, percept: IVPercept) -> IVIntent:
        """Map one immutable local observation to a typed intent."""
        ...

    def offspring_traits(
        self, parent_bug_id: int, child_bug_id: int, base_traits: IVTraits
    ) -> IVTraits:
        """Return traits for a child after ordinary physical inheritance."""
        ...
