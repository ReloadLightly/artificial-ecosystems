"""Validated policy programs for the EVOLVE IV controller experiment.

An IV policy is data, not prose to be searched for instruction-like
substrings. Version 1 has one deliberately small, closed JSON schema. This
module owns parsing, canonical serialization, and the pure mapping from a
validated program and an immutable percept to a typed intent. It does not own
ecological physics or simulator state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
import math
from typing import Any, Callable, Mapping, TypeAlias

from evolve4.control import IVIntent, IVPercept, IVTraits, MovementMode


class PolicyValidationError(ValueError):
    """Raised when a proposed IV program is not valid schema-v1 JSON."""


class Role(str, Enum):
    """Metabolic role encoded by an IV program."""

    PRODUCER = "producer"
    RECYCLER = "recycler"


class Movement(str, Enum):
    """Closed set of movement rules available to schema v1."""

    DEFAULT = "default"
    STAY_IF_FED = "stay_if_fed"
    SEEK_RESOURCE = "seek_resource"
    SEEK_OPPOSITE = "seek_opposite"


class Construction(str, Enum):
    """When the organism applies its heritable construction trait."""

    ALWAYS = "always"
    NEVER = "never"
    UNTIL_NONZERO = "until_nonzero"


_TOP_KEYS = frozenset(
    {
        "schema",
        "traits",
        "movement",
        "construction",
        "reproduce_at",
        "require_uncrowded",
    }
)
_TRAIT_KEYS = frozenset({"role", "taste", "construct"})


def _key_error(label: str, actual: set[str], expected: frozenset[str]) -> None:
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if unknown:
        details.append(f"unknown keys: {', '.join(unknown)}")
    if details:
        raise PolicyValidationError(f"{label} has " + "; ".join(details))


def _enum_value(enum_type: type[Enum], value: object, label: str) -> Enum:
    if not isinstance(value, str):
        raise PolicyValidationError(f"{label} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(repr(member.value) for member in enum_type)
        raise PolicyValidationError(f"{label} must be one of {allowed}") from exc


@dataclass(frozen=True, kw_only=True)
class IVProgram:
    """A fully validated, executable policy in the closed v1 language."""

    schema: int = 1
    role: Role
    taste: int
    construct: int
    movement: Movement
    construction: Construction
    reproduce_at: int
    require_uncrowded: bool

    def __post_init__(self) -> None:
        if type(self.schema) is not int or self.schema != 1:
            raise PolicyValidationError("schema must be the integer 1")

        role = _enum_value(Role, self.role, "traits.role")
        movement = _enum_value(Movement, self.movement, "movement")
        construction = _enum_value(Construction, self.construction, "construction")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "movement", movement)
        object.__setattr__(self, "construction", construction)

        if type(self.taste) is not int or self.taste not in (-1, 1):
            raise PolicyValidationError("traits.taste must be the integer -1 or +1")
        if type(self.construct) is not int or self.construct not in (-1, 0, 1):
            raise PolicyValidationError(
                "traits.construct must be the integer -1, 0, or +1"
            )
        if type(self.reproduce_at) is not int or not 8 <= self.reproduce_at <= 30:
            raise PolicyValidationError(
                "reproduce_at must be an integer from 8 through 30"
            )
        if type(self.require_uncrowded) is not bool:
            raise PolicyValidationError("require_uncrowded must be a boolean")

    def traits(self) -> IVTraits:
        """Compile the program's metabolic fields into simulator traits."""
        return IVTraits(
            producer=self.role is Role.PRODUCER,
            taste=self.taste,
            construct=self.construct,
        )

    def to_json(self) -> str:
        """Return the one compact, deterministic JSON representation."""
        payload = {
            "schema": self.schema,
            "traits": {
                "role": self.role.value,
                "taste": self.taste,
                "construct": self.construct,
            },
            "movement": self.movement.value,
            "construction": self.construction.value,
            "reproduce_at": self.reproduce_at,
            "require_uncrowded": self.require_uncrowded,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, candidate: str) -> "IVProgram":
        """Parse and validate one JSON policy without accepting extensions."""
        if type(candidate) is not str:
            raise PolicyValidationError("policy candidate must be a JSON string")

        def reject_constant(token: str) -> None:
            raise PolicyValidationError(f"non-finite JSON number is forbidden: {token}")

        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise PolicyValidationError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        try:
            raw = json.loads(
                candidate,
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
            )
        except PolicyValidationError:
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise PolicyValidationError(f"malformed JSON policy: {exc}") from exc

        if type(raw) is not dict:
            raise PolicyValidationError("policy must be a JSON object")
        _key_error("policy", set(raw), _TOP_KEYS)

        traits = raw["traits"]
        if type(traits) is not dict:
            raise PolicyValidationError("traits must be a JSON object")
        _key_error("traits", set(traits), _TRAIT_KEYS)

        return cls(
            schema=raw["schema"],
            role=raw["traits"]["role"],
            taste=raw["traits"]["taste"],
            construct=raw["traits"]["construct"],
            movement=raw["movement"],
            construction=raw["construction"],
            reproduce_at=raw["reproduce_at"],
            require_uncrowded=raw["require_uncrowded"],
        )


def coerce_program(candidate: IVProgram | str) -> IVProgram:
    """Return a typed program, validating JSON strings at the boundary."""
    if isinstance(candidate, IVProgram):
        return candidate
    if type(candidate) is str:
        return IVProgram.from_json(candidate)
    raise PolicyValidationError("program must be an IVProgram or JSON string")


def _resource_intent(percept: IVPercept) -> IVIntent:
    """Select the richest local cell, preferring the current cell on ties."""
    stocks = (
        (percept.position, percept.stock_here),
        (percept.left, percept.stock_left),
        (percept.right, percept.stock_right),
    )
    target, _stock = max(stocks, key=lambda item: item[1])
    if target == percept.position:
        return IVIntent(movement=MovementMode.STAY)
    return IVIntent(movement=MovementMode.TARGET, target_position=target)


def _movement_intent(program: IVProgram, percept: IVPercept) -> IVIntent:
    if program.movement is Movement.DEFAULT:
        return IVIntent()
    if program.movement is Movement.STAY_IF_FED:
        if percept.stock_here > 0:
            return IVIntent(movement=MovementMode.STAY)
        return IVIntent()
    if program.movement is Movement.SEEK_RESOURCE:
        return _resource_intent(percept)

    opposite_targets: list[tuple[int, int]] = []
    if percept.opposite_left:
        opposite_targets.append((percept.left, percept.stock_left))
    if percept.opposite_right:
        opposite_targets.append((percept.right, percept.stock_right))
    if not opposite_targets:
        return IVIntent()
    target, _stock = max(opposite_targets, key=lambda item: item[1])
    return IVIntent(movement=MovementMode.TARGET, target_position=target)


def decide_program(program: IVProgram, percept: IVPercept) -> IVIntent:
    """Purely map one validated program and percept to a typed intent."""
    if not isinstance(program, IVProgram):
        raise TypeError("program must be an IVProgram")
    if not isinstance(percept, IVPercept):
        raise TypeError("percept must be an IVPercept")

    movement = _movement_intent(program, percept)
    if program.construction is Construction.ALWAYS:
        construct = True
    elif program.construction is Construction.NEVER:
        construct = False
    else:
        construct = percept.condition_here == 0

    return IVIntent(
        movement=movement.movement,
        target_position=movement.target_position,
        construct=construct,
        reproduce=not (program.require_uncrowded and percept.crowded),
        repro_threshold=program.reproduce_at,
    )


DEFAULT_IV_PROGRAMS: tuple[IVProgram, ...] = (
    IVProgram(
        role=Role.PRODUCER,
        taste=1,
        construct=1,
        movement=Movement.SEEK_OPPOSITE,
        construction=Construction.ALWAYS,
        reproduce_at=14,
        require_uncrowded=False,
    ),
    IVProgram(
        role=Role.RECYCLER,
        taste=-1,
        construct=-1,
        movement=Movement.SEEK_OPPOSITE,
        construction=Construction.ALWAYS,
        reproduce_at=20,
        require_uncrowded=False,
    ),
    IVProgram(
        role=Role.PRODUCER,
        taste=1,
        construct=0,
        movement=Movement.DEFAULT,
        construction=Construction.NEVER,
        reproduce_at=10,
        require_uncrowded=False,
    ),
    IVProgram(
        role=Role.RECYCLER,
        taste=-1,
        construct=-1,
        movement=Movement.SEEK_RESOURCE,
        construction=Construction.ALWAYS,
        reproduce_at=20,
        require_uncrowded=False,
    ),
    IVProgram(
        role=Role.PRODUCER,
        taste=1,
        construct=1,
        movement=Movement.STAY_IF_FED,
        construction=Construction.UNTIL_NONZERO,
        reproduce_at=16,
        require_uncrowded=False,
    ),
    IVProgram(
        role=Role.RECYCLER,
        taste=-1,
        construct=0,
        movement=Movement.SEEK_OPPOSITE,
        construction=Construction.NEVER,
        reproduce_at=10,
        require_uncrowded=False,
    ),
    IVProgram(
        role=Role.PRODUCER,
        taste=-1,
        construct=-1,
        movement=Movement.DEFAULT,
        construction=Construction.ALWAYS,
        reproduce_at=14,
        require_uncrowded=True,
    ),
    IVProgram(
        role=Role.RECYCLER,
        taste=1,
        construct=1,
        movement=Movement.STAY_IF_FED,
        construction=Construction.UNTIL_NONZERO,
        reproduce_at=12,
        require_uncrowded=False,
    ),
)

# Compatibility name for policy stores that persist strings. Every entry is
# schema-valid canonical JSON; there is no English/sub-string interpreter.
DEFAULT_IV_POLICIES: tuple[str, ...] = tuple(
    program.to_json() for program in DEFAULT_IV_PROGRAMS
)


def heuristic_mutate_iv_program(
    program: IVProgram, ctx: Mapping[str, Any]
) -> IVProgram:
    """Deterministically change zero or one field of a typed program.

    ``ctx['roll']`` selects one of the seven mutable fields; the final eighth
    of the unit interval is a no-mutation outcome. This is an offline
    variation operator, not an evaluator.
    """
    if not isinstance(program, IVProgram):
        raise TypeError("program must be an IVProgram")
    try:
        roll = float(ctx.get("roll", 0.5))
    except (TypeError, ValueError) as exc:
        raise PolicyValidationError("mutation roll must be a finite number") from exc
    if not math.isfinite(roll):
        raise PolicyValidationError("mutation roll must be a finite number")
    roll = min(1.0, max(0.0, roll))
    selection = min(7, int(roll * 8))

    if selection == 0:
        next_role = Role.RECYCLER if program.role is Role.PRODUCER else Role.PRODUCER
        return replace(program, role=next_role)
    if selection == 1:
        return replace(program, taste=-program.taste)
    if selection == 2:
        constructs = (-1, 0, 1)
        index = constructs.index(program.construct)
        return replace(program, construct=constructs[(index + 1) % len(constructs)])
    if selection == 3:
        movements = tuple(Movement)
        index = movements.index(program.movement)
        return replace(program, movement=movements[(index + 1) % len(movements)])
    if selection == 4:
        constructions = tuple(Construction)
        index = constructions.index(program.construction)
        return replace(
            program,
            construction=constructions[(index + 1) % len(constructions)],
        )
    if selection == 5:
        threshold = 8 if program.reproduce_at == 30 else program.reproduce_at + 1
        return replace(program, reproduce_at=threshold)
    if selection == 6:
        return replace(program, require_uncrowded=not program.require_uncrowded)
    return program


LLMMutator: TypeAlias = Callable[[IVProgram, Mapping[str, Any]], str]


def make_llm_mutator(complete: Callable[[str], str]) -> LLMMutator:
    """Wrap one model call as a raw JSON-candidate generator.

    The output is deliberately not repaired, truncated, parsed, or replaced
    with a heuristic fallback. The caller must validate it with
    :func:`coerce_program` and may then accept or reject it atomically.
    """

    def mutate(program: IVProgram, ctx: Mapping[str, Any]) -> str:
        if not isinstance(program, IVProgram):
            raise TypeError("program must be an IVProgram")
        prompt = (
            "Propose one mutation of this EVOLVE IV policy. Return only one "
            "JSON object with exactly these top-level keys: schema, traits, "
            "movement, construction, reproduce_at, require_uncrowded. "
            "The traits object must contain exactly role, taste, construct. "
            "Keep schema=1; role is producer or recycler; taste is -1 or 1; "
            "construct is -1, 0, or 1; movement is default, stay_if_fed, "
            "seek_resource, or seek_opposite; construction is always, never, "
            "or until_nonzero; reproduce_at is an integer from 8 through 30; "
            "require_uncrowded is a JSON boolean. Change at most one field.\n"
            f"Parent: {program.to_json()}\n"
            f"Context: {dict(ctx)!r}"
        )
        return complete(prompt)

    return mutate


__all__ = [
    "Construction",
    "DEFAULT_IV_POLICIES",
    "DEFAULT_IV_PROGRAMS",
    "IVProgram",
    "LLMMutator",
    "Movement",
    "PolicyValidationError",
    "Role",
    "coerce_program",
    "decide_program",
    "heuristic_mutate_iv_program",
    "make_llm_mutator",
]
