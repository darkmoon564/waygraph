# Waygraph — Winning Strategy & Gap Closure Plan

**Last updated:** 25 November 2026  
**Objective:** Finish 1st overall at the Relate by Neo4j Hackathon by scoring near-maximum across all five rubric dimensions.

---

## 1. Honest Diagnosis: Where We Stand vs. What Wins

### What Is Already Strong
- **Clean Core Engine (`32/32` tests passing):** Deterministic Relate docs importer (4,133 entities, 9,148 source facts, SHA-256 snapshot verification), bounded cursor (`Cursor` offer-check invariant + 32-hop cap), SHA-256 ordered dependency fingerprinting (`version: 2`), 2-walk promotion (`CANDIDATE` -> `VALID`), and fail-closed read-time validation (`8/8` mutation matrix cases with `0` false-valid and `0` false-stale outcomes).
- **Scientific Discipline:** Strict separation between deterministic oracle checks and stochastic LLM agent evaluations, independent gold-path oracle, structured `{ok, data, error, trace_id}` MCP envelopes, and transparent caveats.

### Six Critical Gaps We Must Close to Beat Top Entries
1. **Gap 1 — Agents Cannot Yet Discover or Reuse Shortcuts (`P0 Blocker`):**
   - `agent_runner.py` currently exposes only `start_walk`, `inspect_walk`, `follow_edge`, and `get_walk`—it never exposes `save_shortcut`, `find_shortcuts`, or `reuse_shortcut`!
   - `mcp_server.py` has `save_shortcut` and `check_shortcut(shortcut_id)`, but lacks a discovery surface (`find_shortcuts` or surfacing active `VALID` shortcuts directly inside `start_walk` / `inspect_walk`) and lacks a cursor transition (`take_shortcut(session, shortcut_id)`) that advances the cursor in 1 verified jump!
2. **Gap 2 — Entry-Point Discovery Without Knowing Internal Node IDs (`P0 Usefulness`):**
   - Real users ask natural questions without knowing `Capability:offline-and-sandboxed-use` upfront. Adding a bounded `search_nodes(query, label?, limit=10)` tool (backed by Relate full-text / substring + optional vector search) lets agents enter the graph naturally and still navigate strictly along verified edges.
3. **Gap 3 — Question Set Leaks Intermediate Hops & Has Zero Path Overlap (`P0 Evaluation`):**
   - `relate-docs-v1.jsonl` currently dictates every intermediate hop (`follow CITES to Page ..., then DOCUMENTS to Command ...`) and uses 30 disjoint paths (`reuse_count = 0`).
   - To prove Waygraph's thesis, we need a human-reviewed **natural multi-hop benchmark** with:
     - Questions stating the *information goal* without naming intermediate hops;
     - Realistic recurring hub corridors (so **Warm Run** promotes and reuses desire paths, demonstrating concrete hop, tool-call, and token savings);
     - **Post-Mutation Recovery trials** (where an underlying relationship changes mid-workload: naive path-cache returns a stale/wrong answer, while Waygraph rejects the `STALE` shortcut with exact reason code, re-walks live edges, and self-heals).
4. **Gap 4 — Committed Persistent Store & Native Relate Depth (`P0 — 30% Criterion`):**
   - `data/relate/` is currently gitignored, leaving no persistent store in the repository for judges to inspect immediately.
   - We should commit a compact, ready-to-inspect persistent Relate store (including pre-learned `VALID` and `STALE` desire paths with inspectable evidence!) **and** evaluate upgrading from `relate-db==1.0.1` to the latest stable `1.2.x` release + pairing with official `relate serve --mcp` for the true A/B MCP benchmark.
   - Also preserve native domain labels/relationships alongside `DPEdge` provenance (or provide clean Cypher views) so judges inspecting the store with `relate` CLI see rich connected graph structure immediately.
5. **Gap 5 — Zero-Install Interactive "Waygraph Studio" (`High Judge Leverage`):**
   - Top entries (`Crosswalk`, `Chokepoint Lab`, `SafeMeds`) give judges an instant browser experience.
   - Shipping a clean static web / GitHub Pages **Waygraph Studio** (replayable real benchmark traces + interactive Walk -> Promote Desire Path -> 1-Hop Reuse + SHA-256 Receipt -> Mutate Edge -> Fail-Closed `STALE` Rejection & Live Reroute) makes the core innovation visceral in 15 seconds.
6. **Gap 6 — Complete Multi-Model Benchmark + Submission Hygiene (`P0`):**
   - Replace the partial 5-question rate-limited OpenRouter log with complete, reproducible runs across at least two model tiers (e.g., small/fast model + frontier model) over real MCP stdio transport.
   - Verify GitHub `relate` topic tag, exact 5-section Devpost README headings, cold-start CI workflow (running `waygraph demo` from scratch), and a crisp <= 2:00 demo video.

---

## 2. Rubric-Aligned Scoring Targets

| Criterion | Weight | How Waygraph Wins It |
| :--- | :---: | :--- |
| **Relate & Connected Context** | **30%** | Persistent Relate store committed in repo; source facts + materialized `:DPShortcut` evidence stored natively in Relate; real stdio MCP comparison against official `relate serve --mcp`; node search + transactional fail-closed dependency checks. |
| **Functionality & Completeness** | **25%** | Full closed loop working end-to-end in CLI, MCP server, LLM agent runner, and interactive Studio: Search -> Constrained Walk -> Candidate -> Promoted Shortcut -> 1-Hop Verified Reuse -> Mutation -> Stale Rejection -> Self-Healing Walk. |
| **Usefulness** | **20%** | Solves two real failure modes in production graph agents: (1) hallucinated Cypher / schema drift on unfamiliar graphs, and (2) silent staleness when cached paths/answers outlive underlying facts. Quantified token & hop savings on warm workloads. |
| **Documentation & Reproducibility** | **15%** | Exact Devpost 5-section README, one-command `waygraph demo`, committed persistent store + raw JSONL traces, clean-clone GitHub Actions CI across Python 3.11–3.13, transparent methodology & disclosures. |
| **Creativity** | **10%** | Urban-planning **"desire paths"** brought to AI agent graph navigation: paths thicken with verified traffic in Relate and evaporate the instant a supporting relationship mutates. |

---

## 3. Execution Roadmap (Nov 25 – Dec 11, 2026)

1. **Sprint 1 — Full Desire-Path Loop in Cursor & MCP (Nov 25–27):**
   - Add `search_nodes`, `find_shortcuts`, and `take_shortcut` (advancing cursor + recording verified reuse) to `Cursor` and `mcp_server.py`; include available valid shortcuts from the current node in `inspect_walk` responses.
   - Update `agent_runner.py` to speak real MCP stdio (and in-process fast mode) with full shortcut discovery, learning, and reuse tools.
2. **Sprint 2 — Relate Store Depth & Natural 3-Regime Benchmark (Nov 28–Dec 1):**
   - Check `relate-db` 1.2.x / `relate` CLI compatibility; ensure native graph inspectability + commit a judge-ready persistent store snapshot (`data/relate/showcase`).
   - Author & human-review `relate-docs-v2.jsonl` (natural multi-hop questions without leaked intermediate hops + shared corridor workload + post-mutation recovery set) and promote manifest to `reviewed`.
   - Execute full paired benchmarks: **Native Relate MCP vs. Waygraph (Cold) vs. Waygraph (Warm Desire Paths) vs. Naive Cache under Mutation**.
3. **Sprint 3 — Interactive Waygraph Studio & Cold-Start CI (Dec 2–5):**
   - Build lightweight, zero-dependency interactive HTML/JS **Waygraph Studio** (deployable on GitHub Pages + local `docs/studio/` or `viewer/`) visualizing real Relate docs subgraphs, desire-path thickening, SHA-256 evidence cards, and live mutation invalidation.
   - Expand `.github/workflows/ci.yml` to run lint + pytest + end-to-end `waygraph demo` clean-clone verification.
4. **Sprint 4 — Freeze, README Alignment & 2-Minute Video (Dec 6–8):**
   - Align top-level `README.md` strictly to the required 5-section Devpost template while linking deep technical docs in `docs/`.
   - Verify public GitHub repo settings (`relate`, `relate-neo4j-hackathon`, `relatedb` topics), record crisp 1:45–2:00 demo video, and submit v1 by Dec 8 (keeping Dec 9–11 as verification buffer).
