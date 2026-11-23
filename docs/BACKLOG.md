# Waygraph --- Engineering Backlog

Priority: **P0** pilot/v1 blocker; **P1** useful; **P2** deferred.

## Repository and reproducibility

-   [ ] P0 Publish the Waygraph repository.
-   [ ] P0 Add topics `relate` and `relate-neo4j-hackathon`.
-   [ ] P0 Add license and official README template.
-   [ ] P0 Pin Python and `relate-db==1.0.1`.
-   [ ] P0 Add lock file / reproducible dependency export (still open; installed environment freeze is platform-specific and not promoted as a portable lock).
-   [ ] P0 Add `.env.example`; ignore secrets.
-   [x] P0 Add CI unit-test matrix for Python 3.11--3.13; lint, type-check, and integration jobs remain open.
-   [ ] P1 Add release workflow and benchmark artifact upload.

## Relate integration

-   [x] P0 Clean-environment connect/query/close smoke test (Windows, Python 3.13).
-   [x] P0 Record exact 1.0.1 API behavior in `docs/API_COMPATIBILITY.md` (runtime verified on Python 3.13; concurrency/exception classification remain open).
-   [x] P0 Inspect published graph JSON schema.
-   [x] P0 Implement deterministic importer with stable node/edge IDs.
-   [x] P0 Preserve source references and semantic properties.
-   [x] P0 Validate imported counts and graph checksum.
-   [x] P0 Create persistent directory store.
-   [x] P0 Record snapshot manifest.
-   [x] P1 Verify sequential read-only reopen after closing writer (concurrent readers/writer still unverified).
-   [ ] P1 Add deterministic export for viewer.

## Cursor

-   [x] P0 Define state and invariants.
-   [x] P0 Inspect node.
-   [x] P0 List bounded neighbors (maximum 100).
-   [x] P0 Follow only recently offered edge IDs; revalidate before moving.
-   [x] P0 Backtrack and retrieve walk trace.
-   [x] P0 Enforce hop/result limits (query result is capped at 100); query timeout remains open because Relate 1.0.1 exposes no timeout parameter on `Connection.execute`.
-   [x] P0 Define stable error codes and structured MCP errors.
-   [x] P0 Test disconnected IDs, wrong direction, stale offers, missing
    nodes, hop limit.
-   [x] P0 Expose MCP tools with official Python MCP SDK.
-   [ ] P0 Verify stdio launch from fresh clone (local checkout smoke test passed; fresh clone pending).
-   [ ] P1 Add session expiry and request correlation.

## Desire paths

-   [x] P0 Define logical shortcut schema.
-   [x] P0 Define semantic property allowlist (`anchor`, `cell`, `role`).
-   [x] P0 Implement versioned ordered SHA-256 dependency fingerprint.
-   [x] P0 Validate continuity and endpoints.
-   [x] P0 Count repeated successful paths.
-   [x] P0 Implement deterministic promotion threshold (2 verified walks).
-   [x] P0 Persist shortcut evidence.
-   [x] P0 Validate immediately before reuse.
-   [x] P0 Fail closed on missing/changed dependencies.
-   [x] P0 Record stale reason on the shortcut.
-   [x] P0 Test delete, endpoint, type, relevant property, node deletion, and continuity mutations.
-   [x] P0 Test irrelevant property mutation.
-   [ ] P1 Verify transaction snapshot semantics for validate+reuse.

## Evaluation

-   [x] P0 Generate stable graph-derived multi-hop questions.
-   [x] P0 Compute gold independently of cursor.
-   [x] P0 Freeze deterministic 10/20 pilot/held-out split and manifest (draft; semantic review pending).
-   [ ] P0 Review question semantics and mark the frozen manifest reviewed.
-   [ ] P0 Implement official native Relate MCP condition (local bounded native-Cypher adapter exists; official MCP server not configured).
-   [x] P0 Implement cursor agent condition with provider adapters for OpenRouter, Gemini, and Anthropic (in-process, not MCP).
-   [x] P0 Store JSONL traces and environment metadata (including prompt hash, model, temperature, tokens, errors).
-   [x] P0 Calculate exact accuracy, tokens, calls, hops, latency.
-   [x] P0 Isolate each agent condition/repetition in its own store and support repeated trials; paired/native-MCP runs still require setup.
-   [x] P0 Add deterministic mutation evaluation matrix (synthetic graph; no false-valid or false-stale results).
-   [x] P0 Add isolated deterministic repeats and latency spread summary (2 pilot repetitions verified; no LLM metrics).
-   [x] P1 Add provider selection, OpenRouter free-model default, and env-only API keys.
-   [ ] P1 Add vector RAG condition.
-   [ ] P1 Add paired summaries / confidence intervals.

## Viewer and demo

-   [ ] P1 Export graph and traces to JSON.
-   [ ] P1 Build static HTML viewer.
-   [ ] P1 Show source edges, walked edges, shortcuts.
-   [ ] P1 Animate promotion and stale rejection.
-   [ ] P1 Add replay controls.
-   [ ] P0 Record 1--2 minute demo.
-   [ ] P0 Fresh-clone one-command demo test (the `demo` CLI workflow passes in this checkout; clean clone still pending).

## Submission

-   [ ] P0 README states use case, relationships, Relate mode, why,
    setup, store path.
-   [ ] P0 Document data source/license/attribution.
-   [ ] P0 Acknowledge prior idea seeds and reused code.
-   [ ] P0 Include limitations and evaluation protocol.
-   [ ] P0 Disclose significant AI use.
-   [ ] P0 Verify public repo and `relate` topic.
-   [ ] P0 Submit by Dec 8 internal target.
-   [ ] P0 Final Devpost check before deadline.
