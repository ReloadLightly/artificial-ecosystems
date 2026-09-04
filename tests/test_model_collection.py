"""Offline safety and integrity contracts for authentic model collection."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location(
    "plan_model_collection",
    ROOT / "experiments" / "plan_model_collection.py",
)
assert SPEC is not None and SPEC.loader is not None
PLANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLANNER)

from evolve_modern.model_collection import (
    canonical_json,
    CollectionIntegrityError,
    CollectionPlan,
    CollectionProfile,
    ModelResponse,
    RenderedRequest,
    inspect_resume,
    inspect_spool,
    make_collection_record,
    render_messages,
    validate_collection_record,
)
from evolve4.randomness import IVSeedPlan


PARENT_PROGRAM = (
    '{"construction":"always","movement":"seek_opposite",'
    '"reproduce_at":14,"require_uncrowded":false,"schema":1,'
    '"traits":{"construct":1,"role":"producer","taste":1}}'
)
TEST_RESERVATION_ROOT = 20260906
TEST_QUALIFICATION_ROOT = 20260905
TEST_EVIDENCE_SEEDS = tuple(
    int(child.generate_state(1, dtype=np.uint64)[0])
    for child in np.random.SeedSequence(TEST_RESERVATION_ROOT).spawn(4)
)
COLLECTION_SOURCE_PATHS = (
    "experiments/plan_model_collection.py",
    "experiments/run_iv_variation.py",
    "src/evolve4/control.py",
    "src/evolve4/randomness.py",
    "src/evolve4/simulation.py",
    "src/evolve_modern/iv.py",
    "src/evolve_modern/iv_policies.py",
    "src/evolve_modern/iv_variation.py",
    "src/evolve_modern/model_collection.py",
)


def reservation(root: int) -> dict[str, object]:
    seeds = tuple(
        int(child.generate_state(1, dtype=np.uint64)[0])
        for child in np.random.SeedSequence(root).spawn(4)
    )
    seed_plans = [
        IVSeedPlan.from_master(seed).to_dict() for seed in seeds
    ]
    return {
        "derivation": "numpy-seedsequence-spawn-uint64",
        "derivation_version": 1,
        "root": root,
        "count": len(seeds),
        "master_seeds": list(seeds),
        "master_seeds_sha256": sha256_text(
            canonical_json(list(seeds))
        ),
        "seed_plans": seed_plans,
        "seed_plans_sha256": sha256_text(canonical_json(seed_plans)),
    }


def world_mapping() -> dict[str, object]:
    source = json.loads(
        (ROOT / "experiments/configs/iv-variation-pilot-v1.json").read_text(
            encoding="utf-8"
        )
    )
    physics = dict(source["physics"])
    physics["max_organisms"] = 176
    policy = {
        "trigger": "birth_event",
        "per_replicate_upper_cap": 8,
        "terminal_shortfall": "preserved_as_outcome",
        "authentic_evidence_requires_full_budget": False,
    }
    return {
        "schema": 1,
        "world_id": "iv-variation-world-v1",
        "calibration_id": "iv-world-calibration-v1",
        "claim_status": (
            "model_blind_selected_before_authentic_model_evidence"
        ),
        "design_timing": dict(PLANNER.DESIGN_TIMING),
        "selected_max_organisms": 176,
        "physics": physics,
        "proposal_budget_policy": policy,
        "initial_programs": source["initial_programs"],
        "qualification_seeds": reservation(TEST_QUALIFICATION_ROOT),
        "evidence_seeds": reservation(TEST_RESERVATION_ROOT),
        "bindings": {
            "calibration_config_sha256": PLANNER.EXPECTED_CALIBRATION_CONFIG_SHA256,
            "source_config_sha256": PLANNER.EXPECTED_SOURCE_CONFIG_SHA256,
            "calibration_decision_sha256": "sha256:" + "3" * 64,
            "physics_sha256": sha256_text(canonical_json(physics)),
            "initial_programs_sha256": sha256_text(
                canonical_json(source["initial_programs"])
            ),
            "proposal_budget_policy_sha256": sha256_text(
                canonical_json(policy)
            ),
        },
    }


def world_text() -> str:
    return json.dumps(
        world_mapping(),
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


def install_contract_tree(
    root: Path,
    frozen_world: str,
    *,
    copy_collection_sources: bool = True,
) -> Path:
    paths = [
        "experiments/configs/iv-world-calibration-v1.json",
        "experiments/configs/iv-variation-pilot-v1.json",
    ]
    if copy_collection_sources:
        paths.extend(COLLECTION_SOURCE_PATHS)
    for name in paths:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    world_path = root / PLANNER.CANONICAL_WORLD_PATH
    world_path.parent.mkdir(parents=True, exist_ok=True)
    world_path.write_text(frozen_world, encoding="utf-8")
    pricing = root / "tests/fixtures/scripted-pricing-v1.txt"
    pricing.parent.mkdir(parents=True, exist_ok=True)
    pricing.write_text("scripted pricing v1\n", encoding="utf-8")
    return world_path


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def implementation_mapping(*, operator_selected: bool) -> dict[str, object]:
    source_files = {
        path: "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in COLLECTION_SOURCE_PATHS
    }
    operator = (
        {
            "id": "schema-v2-scripted-test-bridge",
            "revision": "scripted-test-v1",
            "source_path": "src/evolve_modern/model_collection.py",
        }
        if operator_selected
        else {
            "id": "UNSELECTED",
            "revision": "UNSELECTED",
            "source_path": "UNSELECTED",
        }
    )
    selected_component = {
        "id": "scripted-test-component",
        "revision": "scripted-test-v1",
        "source_path": "src/evolve_modern/model_collection.py",
    }
    pending_component = {
        "id": "UNSELECTED",
        "revision": "UNSELECTED",
        "source_path": "UNSELECTED",
    }
    return {
        "operator": operator,
        "adapter": dict(
            selected_component if operator_selected else pending_component
        ),
        "collector": dict(
            selected_component if operator_selected else pending_component
        ),
        "token_counter": dict(
            selected_component if operator_selected else pending_component
        ),
        "terminal_manifest": dict(
            selected_component if operator_selected else pending_component
        ),
        "adjudicator": {
            "id": "evolve_modern.iv_variation.adjudicate_proposal",
            "revision": "one-atomic-edit-v1",
            "source_path": "src/evolve_modern/iv_variation.py",
        },
        "parser": {
            "id": "evolve_modern.iv_policies.IVProgram.from_json",
            "revision": "iv-program-schema-v1",
            "source_path": "src/evolve_modern/iv_policies.py",
        },
        "verifier": {
            "id": "experiments.plan_model_collection.verify_cache",
            "revision": "schema-v2-offline-test-v1",
            "source_path": "experiments/plan_model_collection.py",
        },
        "source_files_sha256": source_files,
        "source_bundle_sha256": sha256_text(canonical_json(source_files)),
    }


def profile_mapping() -> dict[str, object]:
    template = (
        "Return exactly one canonical EVOLVE IV schema-v1 JSON program that "
        "differs from the supplied parent by one atomic typed edit.\n"
        "{{parent_program}}"
    )
    return {
        "collection_profile_schema": 2,
        "profile_id": "iv-authentic-model-cache-v1",
        "experiment_id": "iv-variation-model-study-v1",
        "frozen_world_path": (
            "results/reference/iv-world-calibration-v1/frozen-world.json"
        ),
        "frozen_world_sha256": "sha256:" + "1" * 64,
        "status": "blocked_pending_provider_selection",
        "prompt": {
            "revision": "one-atomic-edit-v2",
            "template": template,
            "template_sha256": sha256_text(template),
            "render_revision": "messages-v1",
        },
        "provider": {
            "name": "UNSELECTED",
            "model": "UNSELECTED",
            "model_revision": "UNSELECTED",
            "adapter_revision": "UNSELECTED",
            "credential_env_var": "UNSELECTED",
            "endpoint": "UNSELECTED",
            "http_method": "UNSELECTED",
            "wire_protocol_revision": "UNSELECTED",
        },
        "tokenizer": {
            "identity": "UNSELECTED",
            "revision": "UNSELECTED",
            "definition_sha256": "UNSELECTED",
            "counter_revision": "UNSELECTED",
        },
        "transport": {
            "automatic_retries": 0,
            "max_attempts_per_request": 1,
            "timeout": {
                "kind": "total_wall_clock",
                "seconds": None,
            },
            "idempotency": {
                "mode": "UNSELECTED",
                "key_derivation": "request_sha256",
                "ambiguous_outcome": "stop_collection_no_retry",
            },
        },
        "implementation": implementation_mapping(operator_selected=False),
        "decoding": {
            "temperature": 0.0,
            "max_output_tokens": 192,
        },
        "budget": {
            "replicates": 4,
            "proposals_per_replicate": 8,
            "max_calls": 32,
            "max_input_tokens_per_call": 1024,
            "input_token_cap_status": "provisional_pending_provider_tokenizer",
            "max_output_tokens_per_call": 192,
            "max_input_tokens_total": 32768,
            "max_output_tokens_total": 6144,
            "max_cost_usd": 1.0,
        },
        "pricing": {
            "status": "pending_provider_selection",
            "input_usd_per_million_tokens": None,
            "output_usd_per_million_tokens": None,
            "request_usd": None,
            "effective_date": None,
            "currency": "USD",
            "snapshot_path": None,
            "snapshot_sha256": None,
            "snapshot_source_url": None,
        },
        "trajectory_dependency": {
            "schedule": "sequential",
            "future_requests_precomputable": False,
            "offline_replay_required": True,
            "disclosure": (
                "Each later request depends on prior model-produced programs; "
                "collect in frozen trajectory order, then compare by offline replay."
            ),
        },
    }


def ready_profile_mapping() -> dict[str, object]:
    mapping = profile_mapping()
    mapping["status"] = "ready_for_explicit_authorization"
    mapping["provider"] = {
        "name": "scripted-test-provider",
        "model": "scripted-test-model",
        "model_revision": "recorded-revision",
        "adapter_revision": "scripted-local-v1",
        "credential_env_var": "SCRIPTED_TEST_PROVIDER_API_KEY",
        "endpoint": "https://api.example.test/v1/generate",
        "http_method": "POST",
        "wire_protocol_revision": "canonical-json-utf8-v1",
    }
    mapping["tokenizer"] = {
        "identity": "scripted-test-tokenizer",
        "revision": "scripted-tokenizer-v1",
        "definition_sha256": "sha256:" + "2" * 64,
        "counter_revision": "scripted-counter-v1",
    }
    mapping["transport"] = {
        "automatic_retries": 0,
        "max_attempts_per_request": 1,
        "timeout": {
            "kind": "total_wall_clock",
            "seconds": 30,
        },
        "idempotency": {
            "mode": "provider_guaranteed",
            "key_derivation": "request_sha256",
            "ambiguous_outcome": "stop_collection_no_retry",
        },
    }
    mapping["implementation"] = implementation_mapping(
        operator_selected=True
    )
    budget = dict(mapping["budget"])
    budget["input_token_cap_status"] = "exact_provider_tokenizer_frozen"
    mapping["budget"] = budget
    mapping["pricing"] = {
        "status": "frozen",
        "input_usd_per_million_tokens": 1.0,
        "output_usd_per_million_tokens": 2.0,
        "request_usd": 0.0,
        "effective_date": "2026-09-04",
        "currency": "USD",
        "snapshot_path": "tests/fixtures/scripted-pricing-v1.txt",
        "snapshot_sha256": sha256_text("scripted pricing v1\n"),
        "snapshot_source_url": "https://example.test/pricing",
    }
    return mapping


def rendered_request(
    profile: CollectionProfile,
    sequence_index: int,
    *,
    suffix: str = "",
) -> RenderedRequest:
    profile_values = profile.to_mapping()
    provider = profile_values["provider"]
    decoding = profile_values["decoding"]
    assert isinstance(provider, dict) and isinstance(decoding, dict)
    parent_program = (
        PARENT_PROGRAM.replace('"reproduce_at":14', '"reproduce_at":15')
        if suffix
        else PARENT_PROGRAM
    )
    messages = list(render_messages(profile, parent_program))
    return RenderedRequest.create(
        profile,
        sequence_index=sequence_index,
        replicate_id=f"seed-{TEST_EVIDENCE_SEEDS[sequence_index // 8]}",
        opportunity_id=sequence_index % 8,
        birth_step=sequence_index + 3,
        parent_bug_id=sequence_index + 1,
        child_bug_id=sequence_index + 101,
        operator_event_seed=10_000 + sequence_index,
        parent_program=parent_program,
        messages=messages,
        normalized_adapter_payload={
            "model": provider["model"],
            "messages": messages,
            **decoding,
        },
    )


def ok_response(sequence_index: int) -> ModelResponse:
    return ModelResponse(
        status="ok",
        raw_text=PARENT_PROGRAM,
        definitive_error=None,
        provider_request_id=f"provider-request-{sequence_index}",
        returned_model_revision="recorded-revision",
        finish_reason="stop",
        usage={"input_tokens": 128, "output_tokens": 48},
    )


def record(
    profile: CollectionProfile,
    sequence_index: int,
    *,
    suffix: str = "",
) -> dict[str, object]:
    request = rendered_request(profile, sequence_index, suffix=suffix)
    return make_collection_record(profile, request, ok_response(sequence_index))


class NoCredentialEnvironment(dict[str, str]):
    """Environment that permits locale reads but explodes on credential reads."""

    @staticmethod
    def _guard(key: object) -> None:
        name = str(key).upper()
        sensitive = ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN", "SECRET")
        if name == "UNSELECTED" or any(marker in name for marker in sensitive):
            raise AssertionError(f"planning read credential variable {key!r}")

    def __getitem__(self, key: str) -> str:
        self._guard(key)
        return super().__getitem__(key)

    def get(self, key: str, default: object = None) -> object:
        self._guard(key)
        return super().get(key, default)

    def __contains__(self, key: object) -> bool:
        self._guard(key)
        return super().__contains__(key)


class ModelCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = CollectionProfile.from_mapping(ready_profile_mapping())
        self.blocked_profile = CollectionProfile.from_mapping(profile_mapping())

    def test_profile_and_rendered_request_hashes_bind_exact_inputs(self) -> None:
        reordered = dict(reversed(list(ready_profile_mapping().items())))
        same_profile = CollectionProfile.from_mapping(reordered)
        self.assertEqual(self.profile.profile_sha256, same_profile.profile_sha256)

        changed_mapping = ready_profile_mapping()
        changed_mapping["decoding"] = {
            "temperature": 0.1,
            "max_output_tokens": 192,
        }
        changed_profile = CollectionProfile.from_mapping(changed_mapping)
        self.assertNotEqual(
            self.profile.profile_sha256,
            changed_profile.profile_sha256,
        )

        request = rendered_request(self.profile, 0)
        changed = rendered_request(self.profile, 0, suffix=" ")
        request_mapping = request.to_mapping()
        changed_mapping = changed.to_mapping()
        self.assertNotEqual(
            request_mapping["messages_sha256"],
            changed_mapping["messages_sha256"],
        )
        self.assertNotEqual(
            request_mapping["normalized_adapter_payload_sha256"],
            changed_mapping["normalized_adapter_payload_sha256"],
        )
        self.assertNotEqual(request.request_sha256, changed.request_sha256)
        self.assertNotEqual(request.cache_key, changed.cache_key)

        mapping = request.to_mapping()
        self.assertEqual(mapping["profile_sha256"], self.profile.profile_sha256)
        self.assertEqual(
            mapping["frozen_world_sha256"],
            self.profile.to_mapping()["frozen_world_sha256"],
        )
        self.assertEqual(mapping["messages"], list(request.messages))
        self.assertEqual(
            canonical_json(mapping["normalized_adapter_payload"]),
            canonical_json(request.normalized_adapter_payload),
        )

    def test_new_profile_contracts_bind_transitively_into_cache_records(self) -> None:
        baseline_profile = CollectionProfile.from_mapping(ready_profile_mapping())
        baseline_request = rendered_request(baseline_profile, 0)
        baseline_record = make_collection_record(
            baseline_profile,
            baseline_request,
            ok_response(0),
        )

        alternatives: list[dict[str, object]] = []
        tokenizer_changed = ready_profile_mapping()
        tokenizer_changed["tokenizer"]["revision"] = "scripted-tokenizer-v2"
        alternatives.append(tokenizer_changed)

        transport_changed = ready_profile_mapping()
        transport_changed["transport"]["timeout"]["seconds"] = 31
        alternatives.append(transport_changed)

        implementation_changed = ready_profile_mapping()
        implementation_changed["implementation"]["adjudicator"][
            "revision"
        ] = "one-atomic-edit-v1-audit-label"
        alternatives.append(implementation_changed)

        for candidate in alternatives:
            with self.subTest(changed=set(candidate)):
                profile = CollectionProfile.from_mapping(candidate)
                request = rendered_request(profile, 0)
                cached = make_collection_record(
                    profile,
                    request,
                    ok_response(0),
                )
                self.assertNotEqual(
                    profile.profile_sha256,
                    baseline_profile.profile_sha256,
                )
                self.assertNotEqual(
                    request.request_sha256,
                    baseline_request.request_sha256,
                )
                self.assertNotEqual(
                    cached["record_sha256"],
                    baseline_record["record_sha256"],
                )
                with self.assertRaisesRegex(
                    CollectionIntegrityError,
                    "profile|checksum|provenance",
                ):
                    validate_collection_record(
                        baseline_record,
                        profile=profile,
                    )

    def test_ready_and_blocked_profiles_fail_closed_on_transport_identity(self) -> None:
        invalid_ready: list[tuple[dict[str, object], str]] = []

        unresolved_tokenizer = ready_profile_mapping()
        unresolved_tokenizer["tokenizer"]["counter_revision"] = "UNSELECTED"
        invalid_ready.append((unresolved_tokenizer, "ready profile"))

        unresolved_operator = ready_profile_mapping()
        unresolved_operator["implementation"]["operator"][
            "revision"
        ] = "UNSELECTED"
        invalid_ready.append((unresolved_operator, "ready profile"))

        unresolved_parser = ready_profile_mapping()
        unresolved_parser["implementation"]["parser"]["id"] = "UNSELECTED"
        invalid_ready.append((unresolved_parser, "parser.*selected"))

        no_timeout = ready_profile_mapping()
        no_timeout["transport"]["timeout"]["seconds"] = None
        invalid_ready.append((no_timeout, "ready profile"))

        zero_timeout = ready_profile_mapping()
        zero_timeout["transport"]["timeout"]["seconds"] = 0
        invalid_ready.append((zero_timeout, "timeout.*positive"))

        unknown_idempotency = ready_profile_mapping()
        unknown_idempotency["transport"]["idempotency"]["mode"] = "maybe"
        invalid_ready.append((unknown_idempotency, "ready profile"))

        automatic_retry = ready_profile_mapping()
        automatic_retry["transport"]["automatic_retries"] = 1
        invalid_ready.append((automatic_retry, "automatic_retries"))

        boolean_retry = ready_profile_mapping()
        boolean_retry["transport"]["automatic_retries"] = False
        invalid_ready.append((boolean_retry, "automatic_retries"))

        second_attempt = ready_profile_mapping()
        second_attempt["transport"]["max_attempts_per_request"] = 2
        invalid_ready.append((second_attempt, "max_attempts"))

        boolean_attempt = ready_profile_mapping()
        boolean_attempt["transport"]["max_attempts_per_request"] = True
        invalid_ready.append((boolean_attempt, "max_attempts"))

        for candidate, pattern in invalid_ready:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(CollectionIntegrityError, pattern):
                    CollectionProfile.from_mapping(candidate)

        selected_while_blocked = profile_mapping()
        selected_while_blocked["transport"]["timeout"]["seconds"] = 30
        with self.assertRaisesRegex(CollectionIntegrityError, "blocked profile"):
            CollectionProfile.from_mapping(selected_while_blocked)

        selected_tokenizer_while_blocked = profile_mapping()
        selected_tokenizer_while_blocked["tokenizer"][
            "identity"
        ] = "partial-selection"
        with self.assertRaisesRegex(CollectionIntegrityError, "blocked profile"):
            CollectionProfile.from_mapping(selected_tokenizer_while_blocked)

    def test_profile_rejects_unselected_core_identity_and_secret_values(self) -> None:
        for path in (
            ("profile_id",),
            ("experiment_id",),
            ("frozen_world_path",),
            ("prompt", "revision"),
            ("prompt", "template"),
            ("prompt", "render_revision"),
        ):
            for factory in (profile_mapping, ready_profile_mapping):
                candidate = factory()
                target = candidate
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = "UNSELECTED"
                if path == ("prompt", "template"):
                    candidate["prompt"]["template_sha256"] = sha256_text(
                        "UNSELECTED"
                    )
                with self.subTest(path=path, status=candidate["status"]):
                    with self.assertRaises(CollectionIntegrityError):
                        CollectionProfile.from_mapping(candidate)

        for credential_name in (
            "PATH", "HOME", "sk-live-secret", "actual_secret_value",
            "OPENAI API KEY",
        ):
            candidate = ready_profile_mapping()
            candidate["provider"]["credential_env_var"] = credential_name
            with self.subTest(credential_name=credential_name):
                with self.assertRaisesRegex(
                    CollectionIntegrityError,
                    "credential-like.*environment-variable",
                ):
                    CollectionProfile.from_mapping(candidate)

        for secret_key in (
            "authorization", "headers", "cookie", "api_key", "access_token"
        ):
            candidate = ready_profile_mapping()
            candidate["decoding"][secret_key] = "secret-value"
            with self.subTest(secret_key=secret_key):
                with self.assertRaisesRegex(
                    CollectionIntegrityError,
                    "unsupported|secret-bearing",
                ):
                    CollectionProfile.from_mapping(candidate)

        request = rendered_request(self.profile, 0)
        payload = dict(request.normalized_adapter_payload)
        payload["authorization"] = "Bearer secret-value"
        with self.assertRaisesRegex(CollectionIntegrityError, "secret-bearing"):
            RenderedRequest.create(
                self.profile,
                sequence_index=request.sequence_index,
                replicate_id=request.replicate_id,
                opportunity_id=request.opportunity_id,
                birth_step=request.birth_step,
                parent_bug_id=request.parent_bug_id,
                child_bug_id=request.child_bug_id,
                operator_event_seed=request.operator_event_seed,
                parent_program=request.parent_program,
                messages=request.messages,
                normalized_adapter_payload=payload,
            )

    def test_ready_profile_rejects_unsafe_endpoint_and_unbound_pricing(self) -> None:
        for endpoint in (
            "http://api.example.test/v1",
            "file:///tmp/provider",
            "https://localhost/v1",
            "https://127.0.0.1/v1",
            "https://user:secret@api.example.test/v1",
            "https://api.example.test/v1?api_key=secret",
            "https://api.example.test/v1#fragment",
        ):
            candidate = ready_profile_mapping()
            candidate["provider"]["endpoint"] = endpoint
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(
                    CollectionIntegrityError, "endpoint|HTTPS|public"
                ):
                    CollectionProfile.from_mapping(candidate)

        invalid_pricing: list[tuple[dict[str, object], str]] = []
        zero_input = ready_profile_mapping()
        zero_input["pricing"]["input_usd_per_million_tokens"] = 0
        invalid_pricing.append((zero_input, "positive"))
        negative_output = ready_profile_mapping()
        negative_output["pricing"]["output_usd_per_million_tokens"] = -1
        invalid_pricing.append((negative_output, "positive"))
        invalid_date = ready_profile_mapping()
        invalid_date["pricing"]["effective_date"] = "2026-99-99"
        invalid_pricing.append((invalid_date, "calendar date"))
        escaping_snapshot = ready_profile_mapping()
        escaping_snapshot["pricing"]["snapshot_path"] = "../secret.txt"
        invalid_pricing.append((escaping_snapshot, "repository-relative"))
        missing_snapshot_digest = ready_profile_mapping()
        missing_snapshot_digest["pricing"]["snapshot_sha256"] = "UNSELECTED"
        invalid_pricing.append((missing_snapshot_digest, "sha256"))
        for candidate, pattern in invalid_pricing:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(CollectionIntegrityError, pattern):
                    CollectionProfile.from_mapping(candidate)

    def test_profile_request_response_and_plan_are_deeply_immutable(self) -> None:
        source = ready_profile_mapping()
        profile = CollectionProfile.from_mapping(source)
        profile_sha256 = profile.profile_sha256
        source_budget = source["budget"]
        assert isinstance(source_budget, dict)
        source_budget["max_calls"] = 1
        self.assertEqual(profile.profile_sha256, profile_sha256)
        self.assertEqual(profile.to_mapping()["budget"]["max_calls"], 32)

        exported = profile.to_mapping()
        exported["provider"]["model"] = "mutated-after-export"
        self.assertEqual(profile.profile_sha256, profile_sha256)
        with self.assertRaises(TypeError):
            profile._mapping["status"] = "mutated"  # type: ignore[index]

        profile_values = profile.to_mapping()
        provider = profile_values["provider"]
        decoding = profile_values["decoding"]
        assert isinstance(provider, dict) and isinstance(decoding, dict)
        messages = list(render_messages(profile, PARENT_PROGRAM))
        payload = {
            "model": provider["model"],
            "messages": messages,
            **decoding,
        }
        request = RenderedRequest.create(
            profile,
            sequence_index=0,
            replicate_id=f"seed-{TEST_EVIDENCE_SEEDS[0]}",
            opportunity_id=0,
            birth_step=3,
            parent_bug_id=1,
            child_bug_id=101,
            operator_event_seed=10_000,
            parent_program=PARENT_PROGRAM,
            messages=messages,
            normalized_adapter_payload=payload,
        )
        request_sha256 = request.request_sha256
        messages[0]["content"] = "mutated caller message"
        payload["temperature"] = 0.75
        self.assertEqual(request.request_sha256, request_sha256)
        with self.assertRaises(TypeError):
            request.normalized_adapter_payload["temperature"] = 0.75  # type: ignore[index]

        usage = {"input_tokens": 128, "output_tokens": 48}
        response = ModelResponse(
            status="ok",
            raw_text=PARENT_PROGRAM,
            definitive_error=None,
            provider_request_id="provider-request-immutable",
            returned_model_revision="recorded-revision",
            finish_reason="stop",
            usage=usage,
        )
        usage["input_tokens"] = 999
        self.assertEqual(response.to_mapping()["usage"]["input_tokens"], 128)
        with self.assertRaises(TypeError):
            response.usage["input_tokens"] = 999  # type: ignore[index]

        plan = CollectionPlan.from_profile(profile)
        with self.assertRaises(TypeError):
            plan.pricing["status"] = "mutated"  # type: ignore[index]

    def test_record_integrity_binds_profile_request_payload_and_response(self) -> None:
        request = rendered_request(self.profile, 0)
        cached = make_collection_record(self.profile, request, ok_response(0))
        validated = validate_collection_record(cached, profile=self.profile)
        self.assertEqual(validated, cached)
        self.assertEqual(cached["profile_sha256"], self.profile.profile_sha256)
        self.assertEqual(cached["request"]["request_sha256"], request.request_sha256)

        for path, replacement, error_pattern in (
            (
                ("profile_sha256",),
                "sha256:" + "0" * 64,
                "profile|provenance",
            ),
            (
                ("request", "messages", 0, "content"),
                "tampered message",
                "messages|request",
            ),
            (
                ("request", "normalized_adapter_payload", "temperature"),
                0.5,
                "adapter payload|request",
            ),
            (("response", "raw_text"), "tampered", "raw|response"),
        ):
            tampered = copy.deepcopy(cached)
            target: object = tampered
            for key in path[:-1]:
                target = target[key]  # type: ignore[index]
            target[path[-1]] = replacement  # type: ignore[index]
            with self.assertRaisesRegex(CollectionIntegrityError, error_pattern):
                validate_collection_record(tampered, profile=self.profile)

    def test_definitive_provider_error_is_a_valid_record(self) -> None:
        request = rendered_request(self.profile, 0)
        response = ModelResponse(
            status="definitive_error",
            raw_text=None,
            definitive_error="recorded terminal provider error",
            provider_request_id="provider-request-error-0",
            returned_model_revision="recorded-revision",
            finish_reason=None,
            usage={"input_tokens": 128, "output_tokens": 0},
        )
        cached = make_collection_record(self.profile, request, response)

        self.assertEqual(
            validate_collection_record(cached, profile=self.profile),
            cached,
        )
        self.assertEqual(cached["response"]["status"], "definitive_error")
        self.assertIsNone(cached["response"]["raw_text"])
        self.assertEqual(
            cached["response"]["definitive_error"],
            "recorded terminal provider error",
        )

    def test_resume_requires_unique_contiguous_exact_prefix(self) -> None:
        requests = [rendered_request(self.profile, index) for index in range(3)]
        records = [
            make_collection_record(self.profile, request, ok_response(index))
            for index, request in enumerate(requests)
        ]
        inspection = inspect_resume(
            records[:2],
            self.profile,
            expected_rendered_prefix=requests,
        )
        self.assertEqual(inspection.completed_count, 2)
        self.assertEqual(inspection.next_sequence_index, 2)
        self.assertIsNone(inspection.pending_request_sha256)
        self.assertFalse(inspection.at_call_ceiling)

        invalid_cases = (
            (records[:1] + records[:1], None, "duplicate|sequence"),
            ([records[0], records[2]], None, "gap|sequence|contiguous"),
            (records, requests[:2], "extra|prefix"),
            (
                records[:2],
                [requests[0], rendered_request(self.profile, 1, suffix=" ")],
                "prefix|request",
            ),
        )
        for candidate_records, prefix, pattern in invalid_cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(CollectionIntegrityError, pattern):
                    inspect_resume(
                        candidate_records,
                        self.profile,
                        expected_rendered_prefix=prefix,
                    )

        schedule = tuple(
            (f"seed-{seed}", opportunity)
            for seed in TEST_EVIDENCE_SEEDS
            for opportunity in range(8)
        )
        base = requests[0]
        foreign_request = RenderedRequest.create(
            self.profile,
            sequence_index=base.sequence_index,
            replicate_id="seed-foreign",
            opportunity_id=base.opportunity_id,
            birth_step=base.birth_step,
            parent_bug_id=base.parent_bug_id,
            child_bug_id=base.child_bug_id,
            operator_event_seed=base.operator_event_seed,
            parent_program=base.parent_program,
            messages=base.messages,
            normalized_adapter_payload=base.normalized_adapter_payload,
        )
        foreign = make_collection_record(
            self.profile,
            foreign_request,
            ok_response(0),
        )
        with self.assertRaisesRegex(CollectionIntegrityError, "frozen.*slot"):
            inspect_resume(
                [foreign],
                self.profile,
                expected_schedule=schedule,
            )

    def test_pending_request_is_exposed_and_never_silently_retried(self) -> None:
        first = rendered_request(self.profile, 0)
        second = rendered_request(self.profile, 1)
        first_record = make_collection_record(self.profile, first, ok_response(0))

        inspection = inspect_resume(
            [first_record],
            self.profile,
            pending={"request": second.to_mapping()},
            expected_rendered_prefix=[first, second],
        )
        self.assertEqual(inspection.completed_count, 1)
        self.assertEqual(inspection.next_sequence_index, 1)
        self.assertEqual(inspection.pending_request_sha256, second.request_sha256)
        self.assertFalse(inspection.at_call_ceiling)

        with self.assertRaisesRegex(CollectionIntegrityError, "pending|sequence"):
            inspect_resume(
                [first_record],
                self.profile,
                pending={
                    "request": rendered_request(self.profile, 2).to_mapping()
                },
                expected_rendered_prefix=[first, second],
            )

    def test_plan_is_blocked_bounded_and_discloses_trajectory_dependency(self) -> None:
        plan = CollectionPlan.from_profile(self.blocked_profile)

        self.assertEqual(plan.status, "blocked_pending_provider_selection")
        self.assertEqual(plan.max_calls, 32)
        self.assertEqual(plan.max_input_tokens_per_call, 1024)
        self.assertEqual(plan.max_input_tokens_total, 32768)
        self.assertEqual(plan.max_output_tokens_per_call, 192)
        self.assertEqual(plan.max_output_tokens_total, 32 * 192)
        self.assertEqual(plan.max_cost_usd, 1.0)
        self.assertIn("1000000", plan.cost_formula.replace(",", ""))
        self.assertEqual(
            plan.profile_sha256,
            self.blocked_profile.profile_sha256,
        )
        self.assertEqual(plan.trajectory_dependency["schedule"], "sequential")
        self.assertEqual(
            tuple(plan.blockers),
            (
                "provider_selection",
                "tokenizer_identity",
                "input_counter_revision",
                "timeout_policy",
                "idempotency_policy",
                "wire_protocol",
                "provider_adapter",
                "sequential_collector",
                "schema_v2_replay_operator",
                "pricing",
                "terminal_manifest_support",
            ),
        )
        self.assertFalse(
            plan.trajectory_dependency["future_requests_precomputable"]
        )
        self.assertTrue(plan.trajectory_dependency["offline_replay_required"])
        disclosure = plan.trajectory_dependency["disclosure"].lower()
        self.assertIn("later request", disclosure)
        self.assertIn("offline replay", disclosure)

    def test_profile_rejects_any_expansion_of_the_frozen_hard_caps(self) -> None:
        oversized_calls = profile_mapping()
        call_budget = dict(oversized_calls["budget"])
        call_budget.update(
            {
                "replicates": 4,
                "proposals_per_replicate": 9,
                "max_calls": 36,
                "max_input_tokens_total": 36 * 1024,
                "max_output_tokens_total": 36 * 192,
            }
        )
        oversized_calls["budget"] = call_budget

        oversized_output = profile_mapping()
        output_budget = dict(oversized_output["budget"])
        output_budget.update(
            {
                "max_output_tokens_per_call": 193,
                "max_output_tokens_total": 32 * 193,
            }
        )
        oversized_output["budget"] = output_budget
        output_decoding = dict(oversized_output["decoding"])
        output_decoding["max_output_tokens"] = 193
        oversized_output["decoding"] = output_decoding

        oversized_input = profile_mapping()
        input_budget = dict(oversized_input["budget"])
        input_budget.update(
            {
                "max_input_tokens_per_call": 1025,
                "max_input_tokens_total": 32 * 1025,
            }
        )
        oversized_input["budget"] = input_budget

        oversized_cost = profile_mapping()
        cost_budget = dict(oversized_cost["budget"])
        cost_budget["max_cost_usd"] = 1.01
        oversized_cost["budget"] = cost_budget

        for mapping, pattern in (
            (oversized_calls, "max_calls.*hard cap"),
            (oversized_input, "input.*hard cap"),
            (oversized_output, "output.*hard cap"),
            (oversized_cost, "max_cost_usd.*at most"),
        ):
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(CollectionIntegrityError, pattern):
                    CollectionProfile.from_mapping(mapping)

    def test_source_bundle_and_paths_are_fail_closed(self) -> None:
        bad_bundle = profile_mapping()
        bad_bundle["implementation"]["source_bundle_sha256"] = (
            "sha256:" + "0" * 64
        )
        with self.assertRaisesRegex(CollectionIntegrityError, "bundle checksum"):
            CollectionProfile.from_mapping(bad_bundle)

        path_alias = profile_mapping()
        sources = path_alias["implementation"]["source_files_sha256"]
        sources["./src/evolve_modern/model_collection.py"] = sources[
            "src/evolve_modern/model_collection.py"
        ]
        path_alias["implementation"]["source_bundle_sha256"] = sha256_text(
            canonical_json(sources)
        )
        with self.assertRaisesRegex(CollectionIntegrityError, "repository-relative"):
            CollectionProfile.from_mapping(path_alias)

    def test_plan_and_verify_hash_implementation_source_as_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_files: dict[str, str] = {}
            for index, source_path in enumerate(COLLECTION_SOURCE_PATHS):
                path = root / source_path
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = bytes((0xFF, index, 0x0D, 0x0A))
                path.write_bytes(payload)
                source_files[source_path] = (
                    "sha256:" + hashlib.sha256(payload).hexdigest()
                )

            frozen_world = world_text()
            world_path = install_contract_tree(
                root,
                frozen_world,
                copy_collection_sources=False,
            )
            mapping = ready_profile_mapping()
            mapping["frozen_world_sha256"] = sha256_text(frozen_world)
            mapping["implementation"]["source_files_sha256"] = source_files
            mapping["implementation"]["source_bundle_sha256"] = sha256_text(
                canonical_json(source_files)
            )
            profile_path = root / "profile.json"
            profile_path.write_text(
                json.dumps(mapping, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            cache_path = root / "empty.jsonl"
            cache_path.write_text("", encoding="utf-8")

            with (
                mock.patch.object(PLANNER, "ROOT", root),
                mock.patch.object(PLANNER, "_validate_calibration_bundle"),
            ):
                plan = PLANNER.build_plan(profile_path)
                verification = PLANNER.verify_cache(profile_path, cache_path)
                self.assertEqual(
                    plan["implementation_sources_verification"],
                    "verified",
                )
                self.assertTrue(
                    verification["implementation_sources_verified"]
                )

                changed = root / COLLECTION_SOURCE_PATHS[0]
                changed.write_bytes(changed.read_bytes() + b"changed")
                with self.assertRaisesRegex(
                    CollectionIntegrityError,
                    "source checksum mismatch",
                ):
                    PLANNER.build_plan(profile_path)
                with self.assertRaisesRegex(
                    CollectionIntegrityError,
                    "source checksum mismatch",
                ):
                    PLANNER.verify_cache(profile_path, cache_path)

    def test_maximum_slot_order_allows_terminal_replicate_shortfall(self) -> None:
        maximum_slots = tuple(
            (f"seed-{seed}", opportunity)
            for seed in TEST_EVIDENCE_SEEDS
            for opportunity in range(8)
        )

        def request_for_slot(
            sequence_index: int,
            replicate_id: str,
            opportunity_id: int,
        ) -> RenderedRequest:
            base = rendered_request(self.profile, 0)
            return RenderedRequest.create(
                self.profile,
                sequence_index=sequence_index,
                replicate_id=replicate_id,
                opportunity_id=opportunity_id,
                birth_step=base.birth_step + sequence_index,
                parent_bug_id=base.parent_bug_id + sequence_index,
                child_bug_id=base.child_bug_id + sequence_index,
                operator_event_seed=base.operator_event_seed + sequence_index,
                parent_program=base.parent_program,
                messages=base.messages,
                normalized_adapter_payload=base.normalized_adapter_payload,
            )

        first = request_for_slot(0, f"seed-{TEST_EVIDENCE_SEEDS[0]}", 0)
        after_shortfall = request_for_slot(
            1,
            f"seed-{TEST_EVIDENCE_SEEDS[1]}",
            0,
        )
        records = [
            make_collection_record(self.profile, first, ok_response(0)),
            make_collection_record(
                self.profile,
                after_shortfall,
                ok_response(1),
            ),
        ]
        inspection = inspect_resume(
            records,
            self.profile,
            expected_schedule=maximum_slots,
        )
        self.assertEqual(inspection.completed_count, 2)
        self.assertFalse(inspection.at_call_ceiling)

        gap = request_for_slot(1, f"seed-{TEST_EVIDENCE_SEEDS[0]}", 2)
        with self.assertRaisesRegex(CollectionIntegrityError, "opportunity gap"):
            inspect_resume(
                [
                    records[0],
                    make_collection_record(
                        self.profile,
                        gap,
                        ok_response(1),
                    ),
                ],
                self.profile,
                expected_schedule=maximum_slots,
            )

    def test_world_verifier_rejects_rehashed_semantic_tampering(self) -> None:
        mutations = []

        selected = world_mapping()
        selected["selected_max_organisms"] = 160
        mutations.append((selected, "selected capacity"))

        physics = world_mapping()
        physics["physics"]["harvest"] += 1
        physics["bindings"]["physics_sha256"] = sha256_text(
            canonical_json(physics["physics"])
        )
        mutations.append((physics, "physics"))

        programs = world_mapping()
        programs["initial_programs"] = list(programs["initial_programs"])
        programs["initial_programs"][0] = programs["initial_programs"][1]
        programs["bindings"]["initial_programs_sha256"] = sha256_text(
            canonical_json(programs["initial_programs"])
        )
        mutations.append((programs, "initial programs"))

        policy = world_mapping()
        policy["proposal_budget_policy"]["per_replicate_upper_cap"] = 9
        policy["bindings"]["proposal_budget_policy_sha256"] = sha256_text(
            canonical_json(policy["proposal_budget_policy"])
        )
        mutations.append((policy, "proposal-budget"))

        reservation_overlap = world_mapping()
        reservation_overlap["qualification_seeds"] = copy.deepcopy(
            reservation_overlap["evidence_seeds"]
        )
        mutations.append((reservation_overlap, "qualification.*reservation"))

        missing_field = world_mapping()
        del missing_field["bindings"]
        mutations.append((missing_field, "keys differ"))

        for world, pattern in mutations:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(CollectionIntegrityError, pattern):
                    PLANNER._validate_frozen_world(world)

    def test_profile_rejects_noncanonical_or_escaping_world_paths(self) -> None:
        for path in (
            "/tmp/frozen-world.json",
            "../frozen-world.json",
            "results/reference/other/frozen-world.json",
            "results//reference/iv-world-calibration-v1/frozen-world.json",
        ):
            candidate = profile_mapping()
            candidate["frozen_world_path"] = path
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    CollectionIntegrityError, "canonical.*v1 path"
                ):
                    CollectionProfile.from_mapping(candidate)

    def test_spool_rejects_unknown_nonregular_and_unreadable_entries(self) -> None:
        cached = record(self.profile, 0)
        name = f"000000-{cached['cache_key'][7:]}.json"

        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory) / "records"
            records.mkdir()
            (records / name).write_text(
                json.dumps(cached, sort_keys=True) + "\n", encoding="utf-8"
            )
            inspection = inspect_spool(directory, self.profile)
            self.assertEqual(inspection.completed_count, 1)
            (records / "notes.txt").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(
                CollectionIntegrityError, "unrecognized|non-regular"
            ):
                inspect_spool(directory, self.profile)

        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory) / "records"
            records.mkdir()
            (records / "000000-directory.json").mkdir()
            with self.assertRaisesRegex(
                CollectionIntegrityError, "unrecognized|non-regular"
            ):
                inspect_spool(directory, self.profile)

        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory) / "records"
            records.mkdir()
            (records / "000000-invalid.json").write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(CollectionIntegrityError, "UTF-8"):
                inspect_spool(directory, self.profile)

        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory) / "records"
            records.mkdir()
            (records / name).write_text("{}", encoding="utf-8")
            with mock.patch.object(
                Path, "read_bytes", side_effect=OSError("denied")
            ):
                with self.assertRaisesRegex(
                    CollectionIntegrityError, "cannot read spool record"
                ):
                    inspect_spool(directory, self.profile)

    def test_plan_cli_reads_no_environment_and_opens_no_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen_world = world_text()
            install_contract_tree(root, frozen_world)
            mapping = profile_mapping()
            mapping["frozen_world_sha256"] = sha256_text(frozen_world)
            profile_path = root / "profile.json"
            profile_path.write_text(
                json.dumps(mapping, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                mock.patch.object(
                    os,
                    "environ",
                    NoCredentialEnvironment(os.environ),
                ),
                mock.patch.object(
                    socket,
                    "socket",
                    side_effect=AssertionError("planning opened a socket"),
                ),
                mock.patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("planning opened a connection"),
                ),
                mock.patch.object(PLANNER, "ROOT", root),
                mock.patch.object(PLANNER, "_validate_calibration_bundle"),
                redirect_stdout(output),
            ):
                result = PLANNER.main(["plan", "--profile", str(profile_path)])

            self.assertIn(result, (None, 0))
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "blocked_pending_provider_selection")
            self.assertEqual(payload["limits"]["max_calls"], 32)
            self.assertEqual(
                payload["limits"]["max_input_tokens_per_call"],
                1024,
            )
            self.assertEqual(payload["limits"]["max_output_tokens_total"], 6144)
            self.assertEqual(payload["limits"]["max_cost_usd"], 1.0)
            self.assertEqual(payload["maximum_request_slots"], 32)
            self.assertEqual(
                payload["blockers"][-1],
                "terminal_manifest_support",
            )
            self.assertEqual(
                payload["implementation_sources_verification"],
                "verified",
            )
            self.assertEqual(payload["network_calls_made"], 0)
            self.assertFalse(payload["credentials_read"])

    def test_verify_cli_accepts_valid_prefix_and_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen_world = world_text()
            install_contract_tree(root, frozen_world)
            mapping = ready_profile_mapping()
            mapping["frozen_world_sha256"] = sha256_text(frozen_world)
            profile = CollectionProfile.from_mapping(mapping)
            profile_path = root / "profile.json"
            profile_path.write_text(
                json.dumps(mapping, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            cached = record(profile, 0)
            cache_path = root / "cache.jsonl"
            cache_path.write_text(
                json.dumps(cached, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                mock.patch.object(PLANNER, "ROOT", root),
                mock.patch.object(PLANNER, "_validate_calibration_bundle"),
                redirect_stdout(output),
            ):
                result = PLANNER.main(
                    [
                        "verify",
                        "--profile",
                        str(profile_path),
                        "--input",
                        str(cache_path),
                    ]
                )
            self.assertEqual(result, 0)
            verification = json.loads(output.getvalue())
            self.assertEqual(
                verification["status"],
                "structurally_valid_ordered_sequence",
            )
            self.assertEqual(verification["completed_count"], 1)
            self.assertEqual(verification["next_sequence_index"], 1)
            self.assertFalse(verification["at_call_ceiling"])
            self.assertTrue(verification["maximum_slot_order_verified"])
            self.assertFalse(
                verification["trajectory_verified"]
            )
            self.assertFalse(verification["replay_ready"])
            self.assertTrue(verification["replay_validation_required"])
            self.assertEqual(verification["network_calls_made"], 0)
            self.assertFalse(verification["credentials_read"])

            tampered = copy.deepcopy(cached)
            tampered["response"]["raw_text"] = "tampered"
            cache_path.write_text(
                json.dumps(tampered, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            error = io.StringIO()
            with (
                mock.patch.object(PLANNER, "ROOT", root),
                mock.patch.object(PLANNER, "_validate_calibration_bundle"),
                redirect_stderr(error),
            ):
                result = PLANNER.main(
                    [
                        "verify",
                        "--profile",
                        str(profile_path),
                        "--input",
                        str(cache_path),
                    ]
                )
            self.assertEqual(result, 2)
            self.assertIn("integrity error", error.getvalue())

            blocked_mapping = profile_mapping()
            blocked_mapping["frozen_world_sha256"] = sha256_text(frozen_world)
            blocked_profile_path = root / "blocked-profile.json"
            blocked_profile_path.write_text(
                json.dumps(blocked_mapping, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            empty_cache = root / "empty-cache.jsonl"
            empty_cache.write_text("", encoding="utf-8")
            error = io.StringIO()
            with (
                mock.patch.object(PLANNER, "ROOT", root),
                mock.patch.object(PLANNER, "_validate_calibration_bundle"),
                redirect_stderr(error),
            ):
                result = PLANNER.main(
                    [
                        "verify",
                        "--profile",
                        str(blocked_profile_path),
                        "--input",
                        str(empty_cache),
                    ]
                )
            self.assertEqual(result, 2)
            self.assertRegex(error.getvalue(), "provider|ready|authorization")


if __name__ == "__main__":
    unittest.main()
