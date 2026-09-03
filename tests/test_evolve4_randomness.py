"""Random-stream compatibility and replay tests for EVOLVE IV physics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.randomness import EcologyRandomStreams, IVSeedPlan
from evolve4.simulation import MetabolicConfig, MetabolicSim


def golden_config() -> MetabolicConfig:
    return MetabolicConfig(
        n_places=8,
        total_units=160,
        n_organisms=6,
        max_organisms=20,
        steps=8,
        seed=1998,
        harvest=4,
        convert_yield=3,
        excrete=2,
        repro_threshold=10,
        mut_prob=0.35,
        construction=True,
        condition_decay=0.18,
        verbose_every=0,
    )


def simulation_state(simulation: MetabolicSim) -> tuple[object, ...]:
    return (
        simulation.history,
        simulation.bugs,
        simulation.places,
        simulation._next,
        simulation.random_streams.state_dict(),
    )


class IVSeedPlanTests(unittest.TestCase):
    def test_version_one_derivation_and_serialization_are_frozen(self) -> None:
        plan = IVSeedPlan.from_master(2026)

        self.assertEqual(
            tuple(getattr(plan, name) for name in IVSeedPlan.STREAM_NAMES),
            (
                3339473683144027492,
                12896123018795801922,
                3415805307851894836,
                10590585997771611084,
                803937220440712645,
                893553057947440943,
                6345843214794302795,
            ),
        )
        self.assertEqual(IVSeedPlan.from_dict(plan.to_dict()), plan)
        self.assertEqual(IVSeedPlan.from_json(plan.to_json()), plan)
        with self.assertRaises(FrozenInstanceError):
            plan.master_seed = 7  # type: ignore[misc]


class EcologyRandomStreamTests(unittest.TestCase):
    def test_default_streams_alias_legacy_rng_and_preserve_golden(self) -> None:
        simulation = MetabolicSim(golden_config())
        streams = simulation.random_streams

        self.assertTrue(
            all(
                getattr(streams, name) is simulation.rng
                for name in IVSeedPlan.ECOLOGY_STREAM_NAMES
            )
        )

        history = simulation.run()
        last = history[-1]
        self.assertEqual(
            (
                last.n_alive,
                last.n_producers,
                last.n_recyclers,
                last.nutrient,
                last.waste,
                last.stored,
                last.births,
                last.deaths,
                last.condition_mean,
                last.condition_var,
            ),
            (20, 11, 9, 6, 21, 133, 2, 0, -2.375, 0.734375),
        )
        state = json.dumps(
            simulation.rng.bit_generator.state,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(state).hexdigest(),
            "856372359d4b333e7bf6e05240628e0ed7f0afd61766c7f5a1ba1fcdcd1712b7",
        )

    def test_plan_constructs_five_distinct_explicit_streams(self) -> None:
        streams = EcologyRandomStreams.from_plan(IVSeedPlan.from_master(2026))
        generators = [
            getattr(streams, name) for name in IVSeedPlan.ECOLOGY_STREAM_NAMES
        ]

        self.assertEqual(len({id(generator) for generator in generators}), 5)
        self.assertTrue(
            all(
                generator.bit_generator.__class__.__name__ == "PCG64"
                for generator in generators
            )
        )

    def test_same_explicit_plan_replays_every_stream_and_physical_state(self) -> None:
        plan = IVSeedPlan.from_master(7301)
        first = MetabolicSim(
            golden_config(),
            random_streams=EcologyRandomStreams.from_plan(plan),
        )
        second = MetabolicSim(
            golden_config(),
            random_streams=EcologyRandomStreams.from_plan(plan),
        )

        first.run()
        second.run()

        self.assertEqual(simulation_state(first), simulation_state(second))
        self.assertEqual(first.conserved(), golden_config().total_units)


if __name__ == "__main__":
    unittest.main()
