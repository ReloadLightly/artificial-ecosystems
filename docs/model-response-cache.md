# Authentic model-response collection and offline replay

> **Status: preflight only; collection is blocked.** The repository can plan
> and verify a schema-v2 collection, but no provider or model has been selected,
> no credential has been read, no API call has been made, and no authentic
> response cache exists. Fixture records remain fixtures and support no model
> claim.

## What “authentic” means

An authentic record contains the exact response text exposed by the named
provider's adapter for the exact rendered request recorded with it. It is not a
locally generated example, a test double, a reconstructed answer, or a fixture
relabelled as model output.

Each record must bind, by canonical bytes and SHA-256 digest:

- the frozen collection profile and world artifact;
- the exact rendered messages and normalized adapter payload for that
  opportunity, plus the digest of its canonical UTF-8 JSON wire body;
- prompt/template bytes and renderer revision;
- experiment, replicate, opportunity, birth, parent, and child identities;
- the canonical parent program and its checksum;
- provider, model, returned model revision, and every decoding setting;
- declared tokenizer identity, revision, definition digest, and input-counter
  revision;
- zero-retry/single-attempt transport, timeout, idempotency, and ambiguity
  policy;
- parser, adjudicator, verifier, adapter, collector, token-counter, replay, and
  terminal-manifest identities plus the hash-bound implementation source
  bundle, including every trajectory-critical controller and simulator file;
- raw response text and its SHA-256 digest over UTF-8, or a definitive
  provider error;
- finish reason, provider request ID, usage, and response checksum; and
- the collection-adapter revision.

This binding makes a cache record an immutable observation of one concrete
request, not a fungible answer that can be moved to another prompt, world, or
model profile.

The provider-neutral preflight can verify these declared values transitively,
but it cannot yet recompute a provider tokenizer's definition digest or audit a
provider-specific adapter that has not been selected. A concrete collection
profile must therefore add the tokenizer artifact and adapter implementation to
the verified source bundle before collection can be authorized.

Schema v2 calls the stored object a **normalized adapter payload** rather than
pretending it is a provider's opaque transport. Its wire contract is narrow:
the selected adapter must send the recorded canonical JSON UTF-8 body unchanged
by `POST` to the exact profile-bound public HTTPS endpoint. The profile also
binds the adapter and wire-protocol revisions. Authorization headers are never
part of either payload or cache. A provider that needs a different wire shape
requires a new versioned contract, not an unrecorded adapter transformation.

The frozen prompt exposes only the closed schema, atomic-edit rule, and
canonical parent program. It does not expose ecological state, treatment
outcomes, scores, donor programs, or later requests. The in-repository renderer
reconstructs the sole user message from those frozen template bytes and rejects
any record whose messages differ.

## Why collection must be sequential

There can be at most 32 requests, but neither the realized count nor their exact
identities can be safely generated in advance. A model response can change a
child's program; that child can affect later births, parents, population state,
and therefore later proposal requests. Request 12 may depend on the response
recorded for request 11.

Collection must consequently advance the frozen model-treatment trajectory in
sequence, recording each response before deriving the next request. This is a
trajectory dependency, not permission to adapt the protocol. Seeds, physics,
prompt rendering, adjudication, budgets, and endpoints remain frozen throughout
the run. After collection, reported comparisons must come from a fresh run that
uses only the completed offline cache.

## Offline-by-default architecture

| Phase | Network | Purpose | Current status |
|---|---|---|---|
| `plan` | Forbidden | Validate the frozen profile, calculate hard bounds, and expose unresolved choices | Implemented; deliberately blocked pending provider selection |
| collection | Explicitly authorized only | Drive the frozen trajectory sequentially and atomically record actual provider results | Not enabled; no concrete adapter or credentials |
| `verify` | Forbidden | Check schema, hashes, profile/world binding, contiguous record indices, and maximum-slot ordering; terminal completeness remains pending | Implemented for JSONL or spool input |
| replay | Forbidden | Consume the verified cache in a fresh frozen ecosystem run | Architectural boundary; no authentic cache or evidence run yet |

The simulator is not a provider client. Network collection belongs in a
separate adapter, while verification and ecological replay stay fail-closed and
offline.

## Run the offline preflight

The versioned collection profile is
[`experiments/configs/iv-model-response-collection-profile-v1.json`](../experiments/configs/iv-model-response-collection-profile-v1.json).
Planning does not read credentials or contact a provider:

```bash
python3 experiments/plan_model_collection.py plan \
  --profile experiments/configs/iv-model-response-collection-profile-v1.json
```

To retain the canonical plan in a new file:

```bash
python3 experiments/plan_model_collection.py plan \
  --profile experiments/configs/iv-model-response-collection-profile-v1.json \
  --output /path/to/new-plan.json
```

The expected status is `blocked_pending_provider_selection`. That is a safety
result, not a failure: an authentic profile cannot honestly claim a model,
revision, tokenizer, or price before those values are chosen and frozen.
The plan also lists every unresolved blocker, including the wire protocol,
provider adapter, sequential collector, schema-v2 replay operator, and
per-replicate terminal-manifest support; none is silently treated as complete.

Verification is also offline. A later concrete, ready profile can check either
a schema-v2 JSONL cache or a spool directory:

```bash
python3 experiments/plan_model_collection.py verify \
  --profile /path/to/ready-concrete-profile.json \
  --input /path/to/cache-or-spool
```

Using the currently committed unselected profile with `verify` is expected to
fail: a cache cannot be authenticated against an unnamed provider/model.

This command treats the 32 replicate/opportunity positions as upper-bound
slots, not guaranteed requests. It reports
`structurally_valid_ordered_sequence` or
`structurally_valid_ordered_sequence_at_call_ceiling`, not a literal slot
prefix and not an ecological replay. It verifies monotone frozen upper-bound
slot order while explicitly reporting
`trajectory_verified: false` and `replay_ready: false`: parent/child identities
must still be matched request-by-request as the frozen world is replayed.
Record `sequence_index` values must be contiguous, but valid terminal shortfall
can skip unused maximum slots. A structurally valid ordered sequence is not a
completed cache. A transition to a later replicate provisionally represents
shortfall in the earlier one; only replay plus a terminal manifest can
authenticate it.

There is intentionally no executable authentic replay command yet. Adding one
before a concrete provider profile and complete verified cache exist would make
the interface look more complete than the experiment is. The future evidence
runner must accept only a successful verification result and must make no
network call.

## Budget envelope

The proposed smallest collection is four reserved evidence seeds with at most
eight birth-triggered opportunities each:

| Limit | Proposed hard cap |
|---|---:|
| Provider calls | 32 |
| Input tokens per call | 1,024 |
| Total input tokens | 32,768 |
| Output tokens per call | 192 |
| Total output tokens | 6,144 |
| Total provider spend | USD 1.00 |

Even after authentic collection and exact offline replay, four evidence seeds
constitute an engineering/descriptive pilot. They cannot support operator
ranking, population-level inference, or claims of generalization to other
models, prompts, worlds, or random seeds.

Eight is a treatment cap, not a guaranteed realized count. A model-produced
program can alter later reproduction, so a replicate that reaches the frozen
horizon with fewer than eight opportunities must retain that shortfall as an
outcome. Collection must not extend the horizon, replace the replicate, or make
calls outside births merely to reach 32. Before provider access is enabled, the
sequential collector/replayer still needs a versioned terminal manifest that
distinguishes a valid horizon-complete shortfall from an interrupted prefix.
Consequently, reaching 32 calls is only `at_call_ceiling`; it is not by itself
proof that the experiment is complete or replay-ready.

The dollar cap is not yet executable. Final input-token and price bounds depend
on the selected provider/model, the provider's tokenizer, effective input and
output prices, and any per-request fees. The final frozen profile must record
the effective date, authoritative HTTPS source URL, repository-relative
snapshot path, and raw-byte SHA-256 digest. Planning must fail if that artifact
is missing or changed, or if the worst-case bound exceeds USD 1.00. Actual
usage must also be accumulated after every response,
and collection must stop before another call could exceed any call, token, or
dollar limit.

## Atomic spool and resume

A live collector must never append blindly to one fragile JSONL file. It should
use a spool directory with one atomically written record per sequence/cache key
and, when necessary, a `pending.json` marker written before the provider call.
Structural verification requires records to have contiguous sequence numbers
and follow the frozen maximum-slot order:

- no duplicate sequence or cache key;
- no gap, reordering, foreign record, or unused extra record;
- exact profile, world, request-message, and payload digests;
- either one authentic response or one definitive provider error per completed
  opportunity; and
- no unresolved pending request.

Every entry inside `records/` must be a recognized regular `.json` file with
the exact sequence/cache-key filename. Directories, symlinks, sidecar files,
invalid UTF-8, malformed JSON, unreadable entries, and unknown spool-root
entries all fail verification.

If a process fails after sending a request but before durably recording the
response, the outcome is ambiguous. Resume must stop. It must not silently send
the request again, because that would spend another budget unit and could
produce a different observation. Collection v1 fixes one attempt and zero SDK
retries even when a provider offers idempotency; any future recovery protocol
requires a new versioned contract.

After successful verification, a planned deterministic step will canonicalize
the spool into JSONL and checksum it. That canonicalizer is not implemented in
this revision. The spool itself remains provenance and should be retained with
collection logs.

## Failure semantics

A definitive provider refusal or error is an authentic observation when its
request identity and provider metadata are recorded. It spends one opportunity,
and offline adjudication gives the child the exact parent program. Malformed,
unchanged, multi-field, and non-atomic text is likewise recorded verbatim and
rejected once, without repair or replacement.

Infrastructure uncertainty is different. A hash mismatch, missing record,
duplicate, sequence gap, profile mismatch, corrupted bytes, or ambiguous
provider outcome stops verification and replay. It must not be converted into
biological inheritance or hidden in a rejection-rate statistic.

## Credentials and sensitive data

The profile may name the credential-like uppercase environment variable from
which a future adapter will read a credential (for example,
`PROVIDER_API_KEY`). Generic names such as `PATH` or `HOME`, non-name strings,
and secret values are rejected. The profile must never contain or record:

- the credential value;
- authorization headers, cookies, or session material;
- unrelated environment variables; or
- provider telemetry that has not been reviewed for sensitive content.

Planning and verification do not need the credential and must not read its
environment variable. Only an explicitly authorized collection command may do
so, immediately before bounded provider access.

## What remains before collection

Collection remains blocked until all of the following are deliberately chosen
and frozen:

1. a provider and concrete model identifier;
2. an immutable or returned model revision policy;
3. the exact normalized-payload renderer, public HTTPS endpoint, canonical
   wire protocol, and tokenizer revision;
4. decoding parameters and output format;
5. an effective-dated input/output/request price snapshot with authoritative
   source URL, repository-relative path, and exact raw-byte checksum;
6. a credential **environment-variable name**, never its value;
7. hash-bound adapter, sequential collector, token counter, verifier, and all
   trajectory-critical simulator/controller sources, with retries disabled and
   idempotency behavior stated;
8. a selected, hash-bound schema-v2 replay operator and terminal-manifest
   implementation;
9. the frozen-world artifact digest and final prompt/profile digests; and
10. explicit authorization for at most 32 calls and USD 1.00 total spend.

Until then, the honest claim is limited: the repository defines an auditable,
offline-first collection envelope. It contains no authentic model observations
and no result about model-assisted variation.
