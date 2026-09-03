"""Versioned random-stream plans for EVOLVE IV experiments.

Ordinary :class:`~evolve4.simulation.MetabolicSim` runs retain the historical
single-generator behavior.  Matched experiments can instead derive explicit,
named streams from one master seed and record the resulting plan verbatim.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from typing import ClassVar, Mapping, cast

import numpy as np


_UINT64_MAX = int(np.iinfo(np.uint64).max)


def _require_uint64(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _UINT64_MAX:
        raise ValueError(f"{label} must be an integer from 0 through {_UINT64_MAX}")
    return value


@dataclass(frozen=True, slots=True)
class IVSeedPlan:
    """Serializable seeds for every stochastic mechanism in a matched run.

    Derivation version 1 uses ``SeedSequence(master_seed).spawn(7)`` in the
    exact order stored in :attr:`STREAM_NAMES`.  Each child sequence emits one
    unsigned 64-bit integer, which seeds an explicit NumPy ``PCG64`` generator.
    The fixed names and version make adding or reordering streams an explicit
    protocol change rather than a silent change to every experiment.
    """

    master_seed: int
    initialization: int
    scheduling: int
    reproduction: int
    mortality: int
    condition_decay: int
    variation_gate: int
    operator: int
    derivation_version: int = 1

    DERIVATION_VERSION: ClassVar[int] = 1
    STREAM_NAMES: ClassVar[tuple[str, ...]] = (
        "initialization",
        "scheduling",
        "reproduction",
        "mortality",
        "condition_decay",
        "variation_gate",
        "operator",
    )
    ECOLOGY_STREAM_NAMES: ClassVar[tuple[str, ...]] = STREAM_NAMES[:5]

    def __post_init__(self) -> None:
        _require_uint64(self.master_seed, "master_seed")
        if (
            type(self.derivation_version) is not int
            or self.derivation_version != self.DERIVATION_VERSION
        ):
            raise ValueError(
                f"derivation_version must be {self.DERIVATION_VERSION}"
            )
        for name in self.STREAM_NAMES:
            _require_uint64(getattr(self, name), name)

    @classmethod
    def from_master(cls, master_seed: int) -> "IVSeedPlan":
        """Derive the version-1 named seeds from ``master_seed``."""
        master_seed = _require_uint64(master_seed, "master_seed")
        children = np.random.SeedSequence(master_seed).spawn(len(cls.STREAM_NAMES))
        seeds = {
            name: int(child.generate_state(1, dtype=np.uint64)[0])
            for name, child in zip(cls.STREAM_NAMES, children, strict=True)
        }
        return cls(master_seed=master_seed, **seeds)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable, explicitly versioned representation."""
        return {
            "derivation_version": self.derivation_version,
            "master_seed": self.master_seed,
            "streams": {name: getattr(self, name) for name in self.STREAM_NAMES},
        }

    def to_json(self) -> str:
        """Return canonical compact JSON for manifests and checksums."""
        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "IVSeedPlan":
        """Restore a plan while rejecting missing and unknown manifest keys."""
        if not isinstance(payload, Mapping):
            raise TypeError("seed plan payload must be a mapping")
        expected = {"derivation_version", "master_seed", "streams"}
        actual = set(payload)
        if actual != expected:
            raise ValueError(
                "seed plan keys must be exactly derivation_version, "
                "master_seed, streams"
            )
        streams = payload["streams"]
        if not isinstance(streams, Mapping):
            raise TypeError("seed plan streams must be a mapping")
        if set(streams) != set(cls.STREAM_NAMES):
            raise ValueError(
                "seed plan stream keys must be exactly "
                + ", ".join(cls.STREAM_NAMES)
            )
        return cls(
            master_seed=cast(int, payload["master_seed"]),
            derivation_version=cast(int, payload["derivation_version"]),
            **{
                name: cast(int, streams[name]) for name in cls.STREAM_NAMES
            },
        )

    @classmethod
    def from_json(cls, payload: str) -> "IVSeedPlan":
        """Restore a plan from its JSON representation."""
        if type(payload) is not str:
            raise TypeError("seed plan JSON must be a string")
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed seed plan JSON: {exc}") from exc
        return cls.from_dict(decoded)


@dataclass(frozen=True, slots=True)
class EcologyRandomStreams:
    """Generators used by the five stochastic ecological mechanisms."""

    initialization: np.random.Generator
    scheduling: np.random.Generator
    reproduction: np.random.Generator
    mortality: np.random.Generator
    condition_decay: np.random.Generator

    @classmethod
    def legacy(cls, generator: np.random.Generator) -> "EcologyRandomStreams":
        """Alias every mechanism to one generator for exact legacy behavior."""
        if not isinstance(generator, np.random.Generator):
            raise TypeError("legacy generator must be a numpy.random.Generator")
        return cls(
            initialization=generator,
            scheduling=generator,
            reproduction=generator,
            mortality=generator,
            condition_decay=generator,
        )

    @classmethod
    def from_plan(cls, plan: IVSeedPlan) -> "EcologyRandomStreams":
        """Construct independent PCG64 ecology generators from ``plan``."""
        if not isinstance(plan, IVSeedPlan):
            raise TypeError("plan must be an IVSeedPlan")

        def generator(name: str) -> np.random.Generator:
            return np.random.Generator(np.random.PCG64(getattr(plan, name)))

        return cls(
            initialization=generator("initialization"),
            scheduling=generator("scheduling"),
            reproduction=generator("reproduction"),
            mortality=generator("mortality"),
            condition_decay=generator("condition_decay"),
        )

    def state_dict(self) -> dict[str, object]:
        """Snapshot all named bit-generator states for replay evidence."""
        return {
            name: copy.deepcopy(getattr(self, name).bit_generator.state)
            for name in IVSeedPlan.ECOLOGY_STREAM_NAMES
        }


__all__ = ["EcologyRandomStreams", "IVSeedPlan"]
