# Waygraph — Architecture Decision Records

**Last updated:** 25 November 2026

---

## Accepted Decisions (Implemented & Verified)

### ADR-001: Relate is authoritative
**Status:** Accepted.  
Source graph entities, source facts, learned shortcuts (`DPShortcut`), and dependency evidence live natively in Relate. Exported JSON/JSONL files are presentation and audit traces only, keeping Relate relationships central to the application.

### ADR-002: Directory-backed persistent store
**Status:** Accepted (sequential read-only reopen verified on `relate-db==1.0.1`).  
Use persistent directory mode for durability, WAL/Parquet inspectability, and clean single-writer ownership. README documents the storage mode and rationale explicitly.

### ADR-003: Constrained cursor MCP
**Status:** Accepted.  
Expose typed traversal operations over verified IDs (`start_walk`, `inspect_walk`, `follow_edge`, `backtrack`, `get_walk`, shortcut tools) rather than arbitrary agent-written Cypher. Official/native Cypher access remains an isolated baseline condition.

### ADR-004: Fail-closed shortcut validation
**Status:** Accepted.  
Every shortcut reuse re-verifies ordered dependencies, active state, endpoints, path continuity, relationship kind, and versioned SHA-256 semantic property fingerprint (`anchor`, `cell`, `role`). Any missing or mutated dependency marks the shortcut `STALE` with an explicit reason code and rejects traversal.

### ADR-005: Application-controlled mutation path + out-of-band safety
**Status:** Accepted.  
Do not depend on database triggers or CDC. Mutations run through the single writer (`Graph` methods), while read-time revalidation also catches out-of-band graph edits before any shortcut is trusted.

### ADR-006: Single writer process per store
**Status:** Accepted.  
One writer process owns a Relate store at a time; benchmark conditions and repetitions run against isolated store directories so learned shortcuts never leak across trials.

### ADR-007: Independent gold answers
**Status:** Accepted.  
Benchmark gold answers are verified via direct edge/entity resolution (`oracle_path`) independent of `Cursor` state and independent of any LLM.

### ADR-008: Explicit attribution of prior seeds
**Status:** Accepted.  
Attribute the graph-walking cursor and dynamic path-index seeds in Michael Hunger's `jexp/relate-ideas`. Waygraph's original contribution is the unified desire-path promotion lifecycle, cryptographic dependency fingerprinting, fail-closed mutation invalidation, and controlled multi-regime evaluation.

### ADR-009: Correctness before visual polish
**Status:** Accepted (Gate 0–3 core correctness complete: 32/32 unit tests and 8/8 mutation matrix passing; interactive Studio now unblocked for upcoming sprint).

---

## Strategic Decisions Taken on 25 November 2026 (Hackathon Win Plan)

### ADR-010: First-class shortcut discovery, 1-hop traversal & node search in Cursor/MCP
**Status:** Accepted for Sprint 1 implementation.  
*Context:* Audit showed `agent_runner.py` did not expose shortcut tools to the LLM, and `inspect_walk` did not surface `VALID` shortcuts departing the current node, preventing warm-start shortcut reuse in agent runs. Users also need a way to locate starting nodes without memorizing internal `Label:id` strings.  
*Decision:* Surface active `VALID` shortcuts from `current` inside `inspect_walk` (or `find_shortcuts`), add `take_shortcut(session, shortcut_id)` to validate and traverse a promoted desire path in one verified hop (falling back cleanly with `SHORTCUT_STALE` reason if invalidated so the agent immediately walks live edges), and add a bounded `search_nodes` entrypoint.

### ADR-011: Three-regime benchmark workload (Cold, Warm Desire Paths, Post-Mutation Self-Healing)
**Status:** Accepted for Sprint 2 implementation.  
*Context:* `relate-docs-v1.jsonl` spells out intermediate hops and uses 30 non-overlapping routes (`0` shortcut promotions during single-pass replay).  
*Decision:* Retain `relate-docs-v1.jsonl` for deterministic plumbing regression tests, and author a human-reviewed `relate-docs-v2.jsonl` natural task benchmark that (1) states user information goals without leaking intermediate hops, (2) includes realistic recurring documentation corridors so warm runs measure genuine desire-path hop/token compression, and (3) evaluates post-mutation self-healing against a naive path/answer cache and official native Relate MCP.

### ADR-012: Commit a judge-inspectable persistent store + zero-install Waygraph Studio
**Status:** Accepted for Sprint 2–3 implementation.  
*Context:* Devpost explicitly warns against unpersisted graphs, and top gallery contenders pair a committed persistent Relate store with an instant browser explorer.  
*Decision:* Commit a compact, reproducible persistent Relate store (`data/relate/showcase` and/or `.rl` clone) containing the imported Relate docs graph plus inspectable `CANDIDATE`, `VALID`, and `STALE` shortcuts, paired with a zero-install static HTML **Waygraph Studio** visualizer for judges.
