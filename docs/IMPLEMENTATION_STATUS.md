# Waygraph --- Progress and next work

**Updated:** 19 November 2026

## Verified implementation

- Relate docs source importer: 4,133 entities and 9,148 relationships.
- Bounded cursor MCP, stable error envelopes, recent-offer checks, hop cap, and shortcut evidence lifecycle.
- Eight deterministic shortcut invalidation scenarios pass.
- Frozen 30-question draft, independent graph oracle, deterministic 10/20 split, snapshot/checksum validation, and heldout review gate.
- One-command `waygraph demo` workflow passed in the working checkout.
- Isolated `repeat-pilot` workflow passed for two repetitions (20/20 oracle replay results).
- OpenRouter `.env` loading is verified. The free router returned a correct two-hop smoke answer. The corrected 10-question pilot was stopped by OpenRouter's free daily request limit after four model responses and one rejected request; three of four answers were exact, while one hit the 1,024-token output cap. Five questions were attempted overall (3/5 exact, including the rejected request); five questions were not attempted. The router varied models across turns.
- The runner now records successful-answer accuracy separately from attempted-question accuracy, provider failures, and questions not attempted. The default is a fixed free tool-capable model, `nvidia/nemotron-3-ultra-550b-a55b:free`; `openrouter/free` remains available explicitly for dynamic routing. Default completion budget is 2,048 tokens. OpenRouter `session_id` is sent per question, though dynamic routing can still vary.
- The pilot's partial result is not a complete benchmark; rerun the full set with the fixed model after the free quota resets. The heldout set is still gated on human semantic review. This is not yet an MCP process-to-agent evaluation.
- Full suite: 31 tests pass on Windows/Python 3.13.

## Next implementation and evaluation work

1. Human author/review of natural task prompts, then explicit manifest promotion.
2. MCP process-to-agent wiring for Waygraph and an official native Relate MCP baseline on paired snapshots (the in-process adapters are available but are not an MCP comparison).
3. Rerun with the fixed model and 2,048-token default after the OpenRouter free quota resets; the recorded pilot used dynamic routing and a 1,024-token cap.
4. Fresh clone setup and stdio server smoke test; CI matrix covers Python 3.11--3.13 but has not run remotely.
5. Relate concurrency/write-conflict semantics, relationship ID stability, and supported query timeout or documented lack of one.
6. Optional viewer/export, vector retrieval, and release artifacts after P0 evidence exists.

Deterministic oracle replay and mutation tests are engineering checks, not agent benchmark results.
