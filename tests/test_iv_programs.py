"""Contracts for the typed EVOLVE IV program language."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
import math
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve4.control import IVIntent, IVPercept, MovementMode
from evolve_modern.iv_policies import (
    Construction,
    DEFAULT_IV_POLICIES,
    DEFAULT_IV_PROGRAMS,
    IVProgram,
    Movement,
    PolicyValidationError,
    Role,
    decide_program,
    heuristic_mutate_iv_program,
)


CANONICAL_PROGRAM = (
    '{"construction":"always","movement":"seek_opposite",'
    '"reproduce_at":14,"require_uncrowded":false,"schema":1,'
    '"traits":{"construct":1,"role":"producer","taste":1}}'
)


def base_percept(**changes: object) -> IVPercept:
    values: dict[str, object] = {
        "bug_id": 7,
        "step": 3,
        "position": 5,
        "left": 4,
        "right": 6,
        "stock_here": 2,
        "stock_left": 7,
        "stock_right": 5,
        "condition_here": 0,
        "stored": 12,
        "repro_threshold": 14,
        "crowded": False,
        "opposite_left": False,
        "opposite_right": True,
        "n_opposite": 1,
    }
    values.update(changes)
    return IVPercept(**values)  # type: ignore[arg-type]


class IVProgramValidationTests(unittest.TestCase):
    def test_canonical_json_round_trips_and_compatibility_aliases_match(self) -> None:
        self.assertEqual(DEFAULT_IV_PROGRAMS[0].to_json(), CANONICAL_PROGRAM)
        self.assertEqual(IVProgram.from_json(CANONICAL_PROGRAM), DEFAULT_IV_PROGRAMS[0])
        self.assertEqual(IVProgram.from_json(CANONICAL_PROGRAM).to_json(), CANONICAL_PROGRAM)

        self.assertEqual(len(DEFAULT_IV_POLICIES), len(DEFAULT_IV_PROGRAMS))
        for encoded, program in zip(
            DEFAULT_IV_POLICIES,
            DEFAULT_IV_PROGRAMS,
            strict=True,
        ):
            with self.subTest(program=encoded):
                self.assertEqual(IVProgram.from_json(encoded), program)
                self.assertEqual(program.to_json(), encoded)

    def test_parser_rejects_non_product_schema_values(self) -> None:
        valid = json.loads(CANONICAL_PROGRAM)
        candidates: dict[str, str] = {}

        for key in tuple(valid):
            payload = copy.deepcopy(valid)
            del payload[key]
            candidates[f"missing top-level {key}"] = json.dumps(payload)

        payload = copy.deepcopy(valid)
        payload["comment"] = "not in v1"
        candidates["unknown top-level key"] = json.dumps(payload)

        payload = copy.deepcopy(valid)
        payload["traits"]["comment"] = "not in v1"
        candidates["unknown trait key"] = json.dumps(payload)

        replacements = {
            "wrong schema": ("schema", 2),
            "unknown movement": ("movement", "teleport"),
            "unknown construction": ("construction", "sometimes"),
            "threshold below domain": ("reproduce_at", 7),
            "threshold above domain": ("reproduce_at", 31),
            "float threshold": ("reproduce_at", 12.0),
            "boolean threshold": ("reproduce_at", True),
            "integer crowded flag": ("require_uncrowded", 0),
        }
        for label, (key, value) in replacements.items():
            payload = copy.deepcopy(valid)
            payload[key] = value
            candidates[label] = json.dumps(payload)

        trait_replacements = {
            "unknown role": ("role", "omnivore"),
            "zero taste": ("taste", 0),
            "out-of-domain construct": ("construct", 2),
            "boolean taste": ("taste", True),
        }
        for label, (key, value) in trait_replacements.items():
            payload = copy.deepcopy(valid)
            payload["traits"][key] = value
            candidates[label] = json.dumps(payload)

        candidates["duplicate key"] = CANONICAL_PROGRAM.replace(
            '"schema":1',
            '"schema":1,"schema":1',
            1,
        )
        candidates["non-finite number"] = CANONICAL_PROGRAM.replace(
            '"reproduce_at":14',
            '"reproduce_at":NaN',
            1,
        )
        candidates["array root"] = "[]"
        candidates["malformed JSON"] = "{"

        for label, candidate in candidates.items():
            with self.subTest(label=label):
                with self.assertRaises(PolicyValidationError):
                    IVProgram.from_json(candidate)

        for candidate in (None, b"{}", {}, 1):
            with self.subTest(non_string=type(candidate).__name__):
                with self.assertRaises(PolicyValidationError):
                    IVProgram.from_json(candidate)  # type: ignore[arg-type]

    def test_direct_constructor_rejects_boolean_integer_impersonation(self) -> None:
        common = {
            "role": Role.PRODUCER,
            "taste": 1,
            "construct": 1,
            "movement": Movement.DEFAULT,
            "construction": Construction.ALWAYS,
            "reproduce_at": 14,
            "require_uncrowded": False,
        }
        for field, value in (
            ("schema", True),
            ("taste", True),
            ("construct", False),
            ("reproduce_at", True),
            ("require_uncrowded", 0),
        ):
            with self.subTest(field=field):
                values = dict(common)
                values[field] = value
                with self.assertRaises(PolicyValidationError):
                    IVProgram(**values)  # type: ignore[arg-type]


class IVProgramDecisionTests(unittest.TestCase):
    def test_movement_rules_compile_to_explicit_typed_intents(self) -> None:
        program = DEFAULT_IV_PROGRAMS[0]
        percept = base_percept()

        expected = IVIntent(
            movement=MovementMode.DEFAULT,
            construct=True,
            repro_threshold=14,
        )
        self.assertEqual(
            decide_program(replace(program, movement=Movement.DEFAULT), percept),
            expected,
        )

        stay_program = replace(program, movement=Movement.STAY_IF_FED)
        self.assertEqual(
            decide_program(stay_program, percept).movement,
            MovementMode.STAY,
        )
        self.assertEqual(
            decide_program(stay_program, base_percept(stock_here=0)).movement,
            MovementMode.DEFAULT,
        )

        resource_program = replace(program, movement=Movement.SEEK_RESOURCE)
        resource_intent = decide_program(resource_program, percept)
        self.assertEqual(resource_intent.movement, MovementMode.TARGET)
        self.assertEqual(resource_intent.target_position, percept.left)
        self.assertEqual(
            decide_program(
                resource_program,
                base_percept(stock_here=7, stock_left=7, stock_right=7),
            ).movement,
            MovementMode.STAY,
        )

        opposite_program = replace(program, movement=Movement.SEEK_OPPOSITE)
        opposite_intent = decide_program(opposite_program, percept)
        self.assertEqual(opposite_intent.movement, MovementMode.TARGET)
        self.assertEqual(opposite_intent.target_position, percept.right)
        self.assertEqual(
            decide_program(
                opposite_program,
                base_percept(
                    opposite_left=True,
                    opposite_right=True,
                    stock_left=8,
                    stock_right=5,
                    n_opposite=2,
                ),
            ).target_position,
            percept.left,
        )
        self.assertEqual(
            decide_program(
                opposite_program,
                base_percept(
                    opposite_left=False,
                    opposite_right=False,
                    n_opposite=0,
                ),
            ).movement,
            MovementMode.DEFAULT,
        )

    def test_construction_and_uncrowded_rules_only_change_their_seams(self) -> None:
        program = replace(DEFAULT_IV_PROGRAMS[0], movement=Movement.DEFAULT)

        self.assertTrue(
            decide_program(
                replace(program, construction=Construction.ALWAYS),
                base_percept(condition_here=1),
            ).construct
        )
        self.assertFalse(
            decide_program(
                replace(program, construction=Construction.NEVER),
                base_percept(condition_here=0),
            ).construct
        )
        until_nonzero = replace(program, construction=Construction.UNTIL_NONZERO)
        self.assertTrue(decide_program(until_nonzero, base_percept(condition_here=0)).construct)
        self.assertFalse(decide_program(until_nonzero, base_percept(condition_here=-1)).construct)

        uncrowded = replace(program, require_uncrowded=True, reproduce_at=14)
        self.assertEqual(
            decide_program(uncrowded, base_percept(crowded=False, stored=20)).repro_threshold,
            14,
        )
        self.assertTrue(
            decide_program(uncrowded, base_percept(crowded=False, stored=20)).reproduce
        )
        self.assertFalse(
            decide_program(uncrowded, base_percept(crowded=True, stored=20)).reproduce
        )

    def test_decision_boundary_rejects_untyped_inputs(self) -> None:
        with self.assertRaises(TypeError):
            decide_program("{}", base_percept())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            decide_program(DEFAULT_IV_PROGRAMS[0], {})  # type: ignore[arg-type]

    def test_heuristic_mutation_is_valid_deterministic_and_one_field_at_most(self) -> None:
        parent = DEFAULT_IV_PROGRAMS[0]
        parent_values = parent.__dict__

        for selection in range(8):
            roll = (selection + 0.25) / 8.0
            with self.subTest(selection=selection):
                first = heuristic_mutate_iv_program(parent, {"roll": roll})
                second = heuristic_mutate_iv_program(parent, {"roll": roll})
                changed = sum(
                    first.__dict__[field] != parent_values[field]
                    for field in parent_values
                )
                self.assertEqual(first, second)
                self.assertLessEqual(changed, 1)
                self.assertEqual(IVProgram.from_json(first.to_json()), first)

        for invalid_roll in (math.nan, math.inf, -math.inf, "not-a-number"):
            with self.subTest(invalid_roll=invalid_roll):
                with self.assertRaises(PolicyValidationError):
                    heuristic_mutate_iv_program(parent, {"roll": invalid_roll})


if __name__ == "__main__":
    unittest.main()
