# Waygraph

Evidence-bearing "desire path" shortcuts learned from verified graph walks on Relate, with fail-closed SHA-256 invalidation when underlying relationships change.

> **Instant Zero-Install Preview:** Open [`viewer/index.html`](viewer/index.html) in any browser to step through Cold Walk → Desire-Path Promotion → 1-Step Verified Jump → Live Edge Mutation (`SHORTCUT_STALE`) & Automatic Reroute over the real Relate documentation graph—or inspect the committed single-file store at [`data/relate/showcase.rl`](data/relate/showcase.rl).

---

## Use case

AI agents navigating unfamiliar knowledge, architecture, or documentation graphs hit two recurring failure modes:
1. **Hallucinated traversals & repeated multi-hop retracing:** Agents generating free-form queries can invent relationships or repeatedly pay multi-hop tool/token costs along the same hub corridors.
2. **Silent staleness in naive caches:** Caching answers or routes without tracking underlying graph facts silently returns wrong answers the moment a supporting relationship is edited, retargeted, or removed.

Waygraph gives agents a **bounded graph cursor over Relate**:
- Agents discover starting entities via native Relate full-text search (`search_nodes`) and can only traverse active outgoing edges offered by the latest inspection (`follow_edge`).
- Repeated verified walks (`>= 2` independent walks) promote into persistent **desire-path shortcuts** (`DPShortcut`) carrying ordered dependency edge IDs and a versioned SHA-256 semantic fingerprint.
- Subsequent walks jump across promoted corridors in **1 verified step** (`take_shortcut`). If any underlying edge is disabled, deleted, retargeted, retyped, or semantically mutated, Waygraph **fails closed** (`SHORTCUT_STALE` with exact reason code) and the agent reroutes over live edges.

---

## How it uses Relate

- **Mode:** single file (`data/relate/showcase.rl`, committed in this repo for instant judge inspection) and directory mode (`data/relate/pilot`, used for local single-writer / concurrent-reader workflows).
- **Why this mode:** Portable single-file `.rl` stores let judges clone and query the exact pre-populated 4,133-node Relate 1.2.0 graph immediately with zero setup or lockfile clutter; directory mode supports isolated local writes with verified concurrent `read_only=True` inspection (`relate-db==1.2.0`).
- **What the graph models:**
  - **Dual Native + Provenance Entities:** All 4,133 Relate documentation entities carry both `:DPEntity` and their native domain labels (`:Page`, `:Capability`, `:Command`, `:Flag`, `:Example`, `:Section`, `:Term`, `:Surface`, `:CookbookRecipe`, `:Problem`, `:Index`), indexed by Relate's native `FULLTEXT INDEX dp_entity_ft`.
  - **Synced Native & Reified Facts:** All 9,148 documentation relationships are materialized both as native typed relationships (`:CITES`, `:DOCUMENTS`, `:HAS_EXAMPLE`, `:HAS_FLAG`, `:LINKS_TO`, etc.) for idiomatic Cypher inspection and as `:DPEdge` nodes (`DP_FROM` / `DP_TO`) for stable SHA-256 dependency identity. Controlled mutations keep both views in lockstep.
  - **Materialized Desire Paths (`:DPShortcut`):** Connected via `(:DPEntity)-[:DP_SHORTCUT_FROM]->(:DPShortcut)-[:DP_SHORTCUT_TO]->(:DPEntity)` storing `status` (`CANDIDATE` | `VALID` | `STALE` | `DISABLED`), `walk_count`, `reuse_count`, ordered `evidence` edge IDs, `fingerprint` (SHA-256), and `validation_reason`.

---

## Setup and run

Requires **Python 3.11–3.13** (`relate-db==1.2.0` universal `cp39-abi3` wheel).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'

# 1. Verify the entire test suite (cursor, shortcuts, MCP stdio, showcase store, v2 benchmark)
pytest -q

# 2. Run the 3-regime Cold -> Warm Desire Paths -> Post-Mutation lifecycle benchmark
waygraph lifecycle-bench

# 3. Run the 8-scenario deterministic shortcut invalidation matrix (0 false-valid / 0 false-stale)
waygraph mutations

# 4. Run the full isolated one-command demo on a fresh store
waygraph demo --db data/relate/demo-run
```

### Run the Waygraph MCP Server (10 Typed Tools)

```bash
WAYGRAPH_DB=data/relate/showcase.rl python -m waygraph.mcp_server
```

Exposed tools return `{ok, data, error, trace_id}` envelopes: `search_nodes`, `start_walk`, `inspect_walk`, `follow_edge`, `take_shortcut`, `backtrack`, `get_walk`, `save_shortcut`, `find_shortcuts`, and `check_shortcut`.

### Run LLM Agent Benchmarks (Free-Tier Ready + Resumable)

Copy `.env.example` to `.env` and set any free-tier key (`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`) or run locally via `--provider ollama` with no key:

```bash
waygraph agent-eval \
  --provider openrouter \
  --condition waygraph \
  --transport mcp-stdio \
  --questions-file data/questions/relate-docs-v2.jsonl \
  --split pilot \
  --resume
```

Conditions: `waygraph` (adaptive desire paths), `cursor` (cold constrained cursor), and `native-cypher` (bounded read-only Cypher over native domain labels/relationships + `dp_entity_ft`).

---

## Where the data lives

- **Committed persistent Relate store:** [`data/relate/showcase.rl`](data/relate/showcase.rl) (`35.32 MB`, Relate `1.2.0` single-file store) — contains all `4,133` entities, `9,148` relationships, native `FULLTEXT INDEX dp_entity_ft`, and `6` inspectable `:DPShortcut` nodes across `VALID` (3), `CANDIDATE` (2), and `STALE` (1) states.
  - Inspect directly with Relate CLI:
    ```cypher
    MATCH (s:DPShortcut)
    RETURN s.id, s.status, s.origin, s.target, s.walk_count, s.reuse_count, s.validation_reason;
    ```
- **Interactive Studio viewer:** [`viewer/index.html`](viewer/index.html) (self-contained, zero-CORS, computes live browser SHA-256 fingerprints identical to `waygraph.shortcuts.fingerprint()`).
- **Archived source corpus:** [`data/source/relate-docs-graph.json`](data/source/relate-docs-graph.json) (Apache-2.0, Relate Authors; provenance & SHA-256 in [`docs/SOURCE_DATA.md`](docs/SOURCE_DATA.md)).
- **Reviewed benchmark sets:** [`data/questions/relate-docs-v2.jsonl`](data/questions/relate-docs-v2.jsonl) (24 natural 3-hop corridor questions, `status: reviewed`) and [`data/questions/relate-docs-v1.jsonl`](data/questions/relate-docs-v1.jsonl) (30 route-plumbing questions).

---

## Measured Results (Reproducible via `waygraph lifecycle-bench` & `waygraph mutations`)

| Regime / Check | Result | Key Metric |
| :--- | :--- | :--- |
| **Cold Cursor (`relate-docs-v2`, 24 × 3-hop)** | `24/24` exact (`100%`) | `72` cursor steps (`3.0` / question), `0` shortcuts |
| **Warm Waygraph — Pass 1 (live learning)** | `24/24` exact (`100%`) | `60` cursor steps (`-16.7%`), `6` corridors promoted, `12` shortcut jumps |
| **Warm Waygraph — Steady State** | `24/24` exact (`100%`) | `48` cursor steps (`-33.3%` on 3-hop; `-67%` on full 3-hop shortcuts), `24` verified jumps |
| **Post-Mutation Safety vs. Naive Cache (real docs graph)** | **Waygraph `6/6` pass** | **Naive Cache: `5/5` false-valid** · **Waygraph: `0` false-valid, `0` false-stale, `4/4` live reroutes** |
| **Deterministic Mutation Matrix (synthetic, 8 failure modes)** | `8/8` pass | `0` false-valid, `0` false-stale |

*(Deterministic lifecycle replays and mutation checks are reported separately from stochastic LLM agent runs—see [`docs/BENCHMARK_RESULTS.md`](docs/BENCHMARK_RESULTS.md), [`docs/EXPERIMENT_PROTOCOL.md`](docs/EXPERIMENT_PROTOCOL.md), and [`docs/README.md`](docs/README.md).)*

---

## Prior Art, Disclosures & Documentation

- **Prior art:** The constrained graph-walking cursor and dynamic path-index seeds originate in Michael Hunger's `jexp/relate-ideas`. Waygraph extends those seeds with dual native+reified Relate persistence, 2-walk promotion, SHA-256 semantic dependency fingerprinting, fail-closed read-time invalidation, MCP stdio integration, and reproducible 3-regime evaluation.
- **Contest timeline & AI disclosure:** Built entirely during the Relate by Neo4j Hackathon contest period (started Nov 16–17, 2026). Significant AI coding assistance was used to author, test, and document this repository; all runtime outputs, store checksums, and test suites were verified directly against `relate-db==1.2.0`.
- **Full engineering & hackathon docs:** See [`docs/README.md`](docs/README.md).
