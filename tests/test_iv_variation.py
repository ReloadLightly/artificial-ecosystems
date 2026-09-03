"""Contracts for matched EVOLVE IV variation and offline replay."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evolve_modern.iv_policies import (
    Construction,
    DEFAULT_IV_PROGRAMS,
    IVProgram,
    Movement,
    Role,
)
from evolve_modern.iv_variation import (
    CacheIntegrityError,
    CacheProvenance,
    CacheResponseStatus,
    CachedProposalOperator,
    CachedProposalProfile,
    CachedProposalStore,
    Donor,
    OperatorContractError,
    PROGRAM_PATHS,
    ProgramPath,
    ProposalFailure,
    ProposalProvenance,
    ProposalRequest,
    ProposalStatus,
    RandomAtomicEditOperator,
    RawProposal,
    TypedHomologousRecombinationOperator,
    TypedPointOperator,
    adjudicate_proposal,
    atomic_neighbors,
    make_cache_record,
    program_delta,
)


def request_for(
    parent: IVProgram | None = None,
    *,
    seed: int = 17,
    donors: tuple[Donor, ...] = (),
) -> ProposalRequest:
    return ProposalRequest(
        experiment_id="iv-matched-v1",
        replicate_id="seed-1998",
        opportunity_id=3,
        birth_step=11,
        parent_bug_id=7,
        child_bug_id=12,
        parent=parent or DEFAULT_IV_PROGRAMS[0],
        operator_event_seed=seed,
        living_donors=donors,
    )


def fixture_profile() -> CachedProposalProfile:
    return CachedProposalProfile(
        provenance=CacheProvenance.FIXTURE,
        prompt_revision="one-atomic-edit-v1",
        prompt="Return exactly one atomic edit as canonical schema-v1 JSON.",
        model_provider="fixture",
        model_name="deterministic-test-double",
        model_revision="1",
        decoding={"temperature": 0.0, "max_output_tokens": 300},
    )


def model_profile() -> CachedProposalProfile:
    return CachedProposalProfile(
        provenance=CacheProvenance.MODEL,
        prompt_revision="one-atomic-edit-model-v1",
        prompt="Return exactly one atomic schema-v1 edit.",
        model_provider="recorded-provider",
        model_name="recorded-model",
        model_revision="immutable-revision",
        decoding={"temperature": 0.0},
    )


class ProgramDistanceTests(unittest.TestCase):
    def test_seven_paths_and_exact_atomic_distance(self) -> None:
        self.assertEqual(
            tuple(path.value for path in PROGRAM_PATHS),
            (
                "traits.role",
                "traits.taste",
                "traits.construct",
                "movement",
                "construction",
                "reproduce_at",
                "require_uncrowded",
            ),
        )
        parent = replace(
            DEFAULT_IV_PROGRAMS[0],
            construct=-1,
            reproduce_at=8,
        )
        cases = (
            (replace(parent, role=Role.RECYCLER), ProgramPath.ROLE),
            (replace(parent, taste=-1), ProgramPath.TASTE),
            (replace(parent, construct=0), ProgramPath.CONSTRUCT),
            (replace(parent, movement=Movement.DEFAULT), ProgramPath.MOVEMENT),
            (
                replace(parent, construction=Construction.NEVER),
                ProgramPath.CONSTRUCTION,
            ),
            (replace(parent, reproduce_at=9), ProgramPath.REPRODUCE_AT),
            (
                replace(parent, require_uncrowded=True),
                ProgramPath.REQUIRE_UNCROWDED,
            ),
        )
        for candidate, path in cases:
            with self.subTest(path=path.value):
                self.assertEqual(
                    program_delta(parent, candidate),
                    program_delta(candidate, parent),
                )
                delta = program_delta(parent, candidate)
                self.assertEqual(delta.changed_paths, (path,))
                self.assertEqual(delta.field_hamming, 1)
                self.assertEqual(delta.atomic_distance, 1)

    def test_large_ordinal_and_multi_field_edits_are_distinct(self) -> None:
        parent = replace(DEFAULT_IV_PROGRAMS[0], construct=-1, reproduce_at=8)
        construct_jump = program_delta(parent, replace(parent, construct=1))
        threshold_jump = program_delta(parent, replace(parent, reproduce_at=30))
        multi = program_delta(
            parent,
            replace(parent, taste=-parent.taste, require_uncrowded=True),
        )

        self.assertEqual((construct_jump.field_hamming, construct_jump.atomic_distance), (1, 2))
        self.assertEqual((threshold_jump.field_hamming, threshold_jump.atomic_distance), (1, 22))
        self.assertEqual((multi.field_hamming, multi.atomic_distance), (2, 2))

    def test_atomic_neighbor_enumeration_is_complete_stable_and_exact(self) -> None:
        parent = replace(DEFAULT_IV_PROGRAMS[0], construct=0, reproduce_at=14)
        first = atomic_neighbors(parent)
        second = atomic_neighbors(parent)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        self.assertEqual(
            [path for path, _candidate in first].count(ProgramPath.MOVEMENT),
            3,
        )
        for path, candidate in first:
            with self.subTest(path=path.value, candidate=candidate.to_json()):
                delta = program_delta(parent, candidate)
                self.assertEqual(delta.changed_paths, (path,))
                self.assertEqual((delta.field_hamming, delta.atomic_distance), (1, 1))


class OperatorTests(unittest.TestCase):
    @staticmethod
    def _seed_for_path(
        operator: TypedPointOperator,
        parent: IVProgram,
        target: ProgramPath,
    ) -> int:
        for seed in range(10_000):
            proposal = operator.propose(request_for(parent, seed=seed))
            if proposal.selected_path is target:
                return seed
        raise AssertionError(f"could not find deterministic seed for {target}")

    def test_typed_point_is_deterministic_atomic_and_has_safe_boundaries(self) -> None:
        parent = replace(DEFAULT_IV_PROGRAMS[0], construct=1, reproduce_at=30)
        operator = TypedPointOperator()

        for path in PROGRAM_PATHS:
            with self.subTest(path=path.value):
                seed = self._seed_for_path(operator, parent, path)
                first = operator.propose(request_for(parent, seed=seed))
                second = operator.propose(request_for(parent, seed=seed))
                self.assertEqual(first, second)
                decision = adjudicate_proposal(parent, first)
                self.assertTrue(decision.accepted)
                self.assertEqual(decision.delta.changed_paths, (path,))
                if path is ProgramPath.CONSTRUCT:
                    self.assertEqual(decision.program.construct, 0)
                if path is ProgramPath.REPRODUCE_AT:
                    self.assertEqual(decision.program.reproduce_at, 29)

    def test_random_edit_is_deterministic_and_always_an_atomic_neighbor(self) -> None:
        parent = replace(DEFAULT_IV_PROGRAMS[0], construct=0, reproduce_at=14)
        operator = RandomAtomicEditOperator()
        possible = {candidate.to_json() for _path, candidate in atomic_neighbors(parent)}

        observed: set[str] = set()
        for seed in range(100):
            proposal = operator.propose(request_for(parent, seed=seed))
            self.assertEqual(proposal, operator.propose(request_for(parent, seed=seed)))
            self.assertIn(proposal.raw_candidate, possible)
            self.assertTrue(adjudicate_proposal(parent, proposal).accepted)
            observed.add(proposal.raw_candidate)
        self.assertGreater(len(observed), 1)

    def test_homologous_recombination_copies_one_eligible_living_leaf(self) -> None:
        parent = replace(DEFAULT_IV_PROGRAMS[0], construct=-1, reproduce_at=8)
        donor_a = Donor(
            bug_id=9,
            program=replace(
                parent,
                taste=-parent.taste,
                construct=1,  # distance two and therefore never copied directly
                reproduce_at=20,
            ),
        )
        donor_b = Donor(
            bug_id=8,
            program=replace(
                parent,
                role=Role.RECYCLER,
                construct=0,
                reproduce_at=9,
            ),
        )
        operator = TypedHomologousRecombinationOperator()
        proposal = operator.propose(
            request_for(parent, seed=33, donors=(donor_a, donor_b))
        )
        reordered = operator.propose(
            request_for(parent, seed=33, donors=(donor_b, donor_a))
        )

        self.assertEqual(proposal, reordered)
        self.assertIn(proposal.donor_bug_id, {8, 9})
        decision = adjudicate_proposal(parent, proposal)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.delta.field_hamming, 1)
        self.assertEqual(decision.delta.atomic_distance, 1)
        donor = donor_a if proposal.donor_bug_id == 9 else donor_b
        selected = proposal.selected_path
        self.assertIsNotNone(selected)
        self.assertEqual(
            program_delta(parent, decision.program).changed_paths,
            (selected,),
        )
        self.assertNotEqual(decision.program.construct, 1)
        if selected is ProgramPath.REPRODUCE_AT:
            self.assertEqual(decision.program.reproduce_at, donor.program.reproduce_at)

    def test_recombination_reports_no_eligible_donor_without_fallback(self) -> None:
        parent = replace(DEFAULT_IV_PROGRAMS[0], construct=-1, reproduce_at=8)
        far_only = Donor(
            bug_id=8,
            program=replace(parent, construct=1, reproduce_at=30),
        )
        proposal = TypedHomologousRecombinationOperator().propose(
            request_for(parent, donors=(far_only,))
        )
        decision = adjudicate_proposal(parent, proposal)

        self.assertEqual(proposal.source_failure, ProposalFailure.NO_ELIGIBLE_DONOR)
        self.assertEqual(decision.status, ProposalStatus.SOURCE_FAILURE)
        self.assertFalse(decision.accepted)
        self.assertIs(decision.program, parent)

    def test_trusted_contract_violations_abort_but_cached_violations_reject(self) -> None:
        parent = DEFAULT_IV_PROGRAMS[0]
        for provenance, raises in (
            (ProposalProvenance.TRUSTED, True),
            (ProposalProvenance.FIXTURE_CACHE, False),
        ):
            proposal = RawProposal(
                operator_id="test",
                operator_revision="1",
                provenance=provenance,
                raw_candidate=parent.to_json(),
            )
            with self.subTest(provenance=provenance.value):
                if raises:
                    with self.assertRaises(OperatorContractError):
                        adjudicate_proposal(parent, proposal)
                else:
                    decision = adjudicate_proposal(parent, proposal)
                    self.assertEqual(decision.status, ProposalStatus.NO_CHANGE)
                    self.assertIs(decision.program, parent)

        non_atomic = RawProposal(
            operator_id="cached",
            operator_revision="1",
            provenance=ProposalProvenance.MODEL_CACHE,
            raw_candidate=replace(parent, reproduce_at=30).to_json(),
        )
        decision = adjudicate_proposal(parent, non_atomic)
        self.assertEqual(decision.status, ProposalStatus.NON_ATOMIC_EDIT)
        self.assertIs(decision.program, parent)


class OfflineCacheTests(unittest.TestCase):
    def test_fixture_replay_is_explicit_and_returns_raw_text_unchanged(self) -> None:
        request = request_for()
        candidate = replace(request.parent, taste=-request.parent.taste).to_json()
        record = make_cache_record(
            fixture_profile(),
            request,
            raw_text=candidate,
            usage={"input_tokens": 0, "output_tokens": 0},
        )
        operator = CachedProposalOperator(
            profile=fixture_profile(),
            store=CachedProposalStore([record]),
        )

        proposal = operator.propose(request)
        decision = adjudicate_proposal(request.parent, proposal)

        self.assertEqual(proposal.provenance, ProposalProvenance.FIXTURE_CACHE)
        self.assertEqual(proposal.raw_candidate, candidate)
        self.assertTrue(proposal.cache_key.startswith("sha256:"))
        self.assertTrue(decision.accepted)

    def test_recorded_provider_failure_consumes_a_proposal_without_candidate(self) -> None:
        request = request_for()
        record = make_cache_record(
            fixture_profile(),
            request,
            raw_text=None,
            status=CacheResponseStatus.PROVIDER_ERROR,
            failure_detail="recorded timeout",
        )
        operator = CachedProposalOperator(
            profile=fixture_profile(),
            store=CachedProposalStore([record]),
        )

        proposal = operator.propose(request)
        decision = adjudicate_proposal(request.parent, proposal)

        self.assertEqual(proposal.source_failure, ProposalFailure.PROVIDER_FAILURE)
        self.assertEqual(decision.status, ProposalStatus.SOURCE_FAILURE)
        self.assertIs(decision.program, request.parent)

    def test_authentic_cache_profile_is_distinct_from_fixture_provenance(self) -> None:
        request = request_for()
        candidate = replace(request.parent, taste=-request.parent.taste).to_json()
        profile = model_profile()
        record = make_cache_record(profile, request, raw_text=candidate)
        operator = CachedProposalOperator(
            profile=profile,
            store=CachedProposalStore([record]),
        )

        proposal = operator.propose(request)

        self.assertEqual(record["provenance"], "model")
        self.assertEqual(proposal.provenance, ProposalProvenance.MODEL_CACHE)
        self.assertTrue(adjudicate_proposal(request.parent, proposal).accepted)

    def test_cache_miss_duplicate_key_and_checksums_fail_closed(self) -> None:
        request = request_for()
        record = make_cache_record(
            fixture_profile(),
            request,
            raw_text=replace(request.parent, taste=-request.parent.taste).to_json(),
        )

        with self.assertRaisesRegex(CacheIntegrityError, "duplicate cache key"):
            CachedProposalStore([record, copy.deepcopy(record)])

        bad_key = copy.deepcopy(record)
        bad_key["cache_key"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(CacheIntegrityError, "request key mismatch"):
            CachedProposalStore([bad_key])

        bad_response = copy.deepcopy(record)
        bad_response["response"]["raw_text"] += " "
        with self.assertRaisesRegex(CacheIntegrityError, "checksum mismatch"):
            CachedProposalStore([bad_response])

        operator = CachedProposalOperator(
            profile=fixture_profile(),
            store=CachedProposalStore([record]),
        )
        different_request = replace(request, child_bug_id=13)
        with self.assertRaisesRegex(CacheIntegrityError, "cache miss"):
            operator.propose(different_request)

    def test_cache_lookup_cannot_mutate_validated_store_state(self) -> None:
        request = request_for()
        candidate = replace(request.parent, taste=-request.parent.taste).to_json()
        profile = fixture_profile()
        store = CachedProposalStore(
            [make_cache_record(profile, request, raw_text=candidate)]
        )

        _key, exposed = store.lookup(profile, request)
        exposed["raw_text"] = request.parent.to_json()

        proposal = CachedProposalOperator(profile=profile, store=store).propose(request)
        self.assertEqual(proposal.raw_candidate, candidate)
        self.assertTrue(adjudicate_proposal(request.parent, proposal).accepted)

    def test_jsonl_loader_rejects_duplicate_json_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.jsonl"
            path.write_text(
                '{"cache_schema":1,"cache_schema":1}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CacheIntegrityError, "duplicate JSON key"):
                CachedProposalStore.from_jsonl(path)

    def test_fixture_and_model_provenance_cannot_be_mislabeled(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider 'fixture'"):
            CachedProposalProfile(
                provenance=CacheProvenance.FIXTURE,
                prompt_revision="v1",
                prompt="prompt",
                model_provider="openai",
                model_name="model",
                model_revision="revision",
                decoding={},
            )
        with self.assertRaisesRegex(ValueError, "cannot use provider 'fixture'"):
            CachedProposalProfile(
                provenance=CacheProvenance.MODEL,
                prompt_revision="v1",
                prompt="prompt",
                model_provider="fixture",
                model_name="model",
                model_revision="revision",
                decoding={},
            )


if __name__ == "__main__":
    unittest.main()
