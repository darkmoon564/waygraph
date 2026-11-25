# Relate by Neo4j Hackathon — Intelligence & Landscape Report

**Last updated:** 25 November 2026  
**Hackathon URL:** https://relate.devpost.com/  
**Current status:** Active building & submission period (17 days remaining)

---

## 1. Key Dates & Deadlines

| Milestone | Official Rules (PST) | Local Time (IST / GMT+5:30) |
| :--- | :--- | :--- |
| **Contest Start** | Nov 11, 2026 @ 6:00 PM PST | Nov 12, 2026 @ 7:30 AM IST |
| **Internal Freeze Target** | Dec 8, 2026 | Dec 8, 2026 |
| **Submission Deadline** | **Dec 11, 2026 @ 6:00 PM PST** | **Dec 12, 2026 @ 7:30 AM IST** |
| **Judging Window** | Dec 12 – Dec 16, 2026 | Dec 12 – Dec 17, 2026 |
| **Winners Announced** | Dec 17, 2026 | Dec 18, 2026 @ 7:30 AM IST |

---

## 2. Prizes, Judges & Scoring Rubric

### Hardware Prizes (1 per winning entry, single open track)
1. **1st Place:** Mac Studio (M5 Max, 64GB / 1TB) — \$3,799 ARV
2. **2nd Place:** Mac mini (M6, 32GB / 512GB) — \$1,499 ARV
3. **3rd Place:** Mac mini (M6, 16GB / 256GB) — \$899 ARV
*(Public voting is also open in the gallery for Popular Choice visibility, while the three main prizes are determined by the judging panel.)*

### Judging Panel (Neo4j Product, Engineering & DevRel Leadership)
- **Michael Hunger** — VP Product Innovation *(author of `jexp/relate-ideas`, where the graph-walking cursor & desire-paths seed concepts originate)*
- **Andreas ("ABK") Kollegger** — Director, Developer Advocacy
- **William Lyon** — Senior Product Manager, AI Innovation
- **Oskar Hane** — Senior Software Engineer
- **Yaru Lin** — Lead Product Manager
- **Kate Smith** — Developer Marketing Manager, AI Capabilities
- **Jennifer Reif** — Senior Developer Advocate
- **Stephen Chin** — VP, Developer Relations

### Judging Criteria (Overview 100-Point Rubric)
1. **Relate and Connected Context (30 pts):** Meaningful use of Relate's graph relationships, storage model, retrieval/MCP surfaces, and ease for judges to run and inspect the persistent store.
2. **Functionality and Completeness (25 pts):** End-to-end working implementation of the core use case.
3. **Usefulness (20 pts):** Solves a clear, genuine problem for a well-defined user where relationships matter.
4. **Documentation and Reproducibility (15 pts):** Clear README following the official 5-section template, deterministic setup, and inspectable store.
5. **Creativity (10 pts):** Originality of the concept or inventive use of Relate capabilities.
*(Note: Official Rules Section 5 lists the same five dimensions weighted equally; optimizing all five protects our score under either weighting.)*

---

## 3. Mandatory Submission Checklist & Rules Nuances

- **New Contest Work:** Must be started on or after Nov 11, 2026 (`waygraph` and its initial pilot started Nov 16–17, 2026, fully within the contest window). Any external data snapshots, prior idea seeds, and AI assistance must be explicitly disclosed.
- **Public GitHub Repo + Mandatory Topic:** Repository (`https://github.com/darkmoon564/waygraph`) must be public through winner announcement and **must carry the `relate` GitHub topic tag** (plus recommended `relate-neo4j-hackathon` and `relatedb`).
- **Persistent Store:** Must commit a persistent Relate store (directory or `.rl` single-file) or make it directly inspectable in the repo/demo—pure `:memory:` apps where data vanishes on exit are explicitly discouraged.
- **Official 5-Section README Structure:**
  1. `# Project name` + one-line pitch
  2. `## Use case` (problem solved & which relationships matter)
  3. `## How it uses Relate` (`Mode: in memory | directory | single file`, `Why this mode:`, `What the graph models:`)
  4. `## Setup and run` (prerequisites, install commands, steps to first result)
  5. `## Where the data lives` (path to the persistent store in the repo)
- **Demo Video:** 1–2 minutes (strictly <= 2:00), accessible without login or paywall.

---

## 4. Relate Engine Capabilities Snapshot (v1.0 – v1.2.1)

Beyond the `relate-db==1.0.1` Python wheel currently pinned in `pyproject.toml`, the upstream `relatedb/relate` release (v1.2.x) highlights capabilities emphasized by the organizers and in `jexp/relate-ideas`:
- **Storage formats:** Directory mode (WAL + Parquet shards, JSON, or Markdown vault), portable single-file `.rl` (`relate clone`), and `:memory:`.
- **Surfaces:** Embedded Python (`relate-db`, including Arrow IPC), Node.js, Rust, **Browser WASM (`@relate/relate-wasm`)**, CLI (`relate`), and single-process server (`relate serve --bolt --http --mcp`, supporting `--read-only=live` WAL tailing).
- **Query & Search:** Cypher 25 (quantified path patterns, label expressions), native vector search + full-text hybrid `SEARCH`, and 2D/3D spatial point indexes.

---

## 5. Landscape Analysis — What the Competition Is Building (77 Gallery Entries)

As of Nov 25, 2026, **797 participants** are registered and **77 submissions** are already visible in the public gallery:
- **Storage mode split:** 51 single-file (`.rl`, 66%), 22 directory (29%), 4 in-memory (5%).

### Five Dominant Submission Archetypes
1. **Generic AI Agent Episodic Memory & Guardrails (~22 entries):** e.g., `GraphMemory`, `ContextMesh`, `memory-pr`, `Recall`, `Supersede`, `WAKE`, `GraphSentinel`, `WorkGraph`, `Thread Compass`. *Crowded category; many store conversational facts or task DAGs.*
2. **Industrial, Safety & Infrastructure Failure Tracing (~14 entries):** e.g., `Blind Flange` (process-plant permit-to-work isolation path checker; returns `COMPLETE/INCOMPLETE` + `BLOCK/HOLD/CLEAR` over 12-hop piping paths), `Chokepoint Lab` (maritime blockade rerouting with WASM + `.rl` + MCP + Cypher 25), `Interlock Tracer`.
3. **Compliance, Audit & Evidence Verification (~11 entries):** e.g., `Crosswalk` (NIST 800-53/171/CSF audit prep in directory mode with `--read-only=live` MCP, hybrid vector/FTS search, claim-checker re-verifying cited paths, WASM browser explorer, 19/20 vs 9/20 baseline eval, and 274 tests), `Claim Rings`, `Forebear`, `Precedent`.
4. **Codebase, Data Lineage & Supply Chain (~9 entries):** e.g., `CodeContext Graph`, `Data Impact Graph`, `Patient Zero`, `Ripple`, `Relating`.
5. **Healthcare, Science & Domain Knowledge Graphs (~21 entries):** e.g., `SafeMeds 3D Graph Studio` (176 KB `.rl` drug collision explorer), `KidneyLoop`, `Prometheus`, `Retraction Reach`.

### Common Patterns Among Top Contenders
- **Path-as-Proof & Fail-Closed Honesty:** Returning exact multi-hop relationship receipts and refusing to guess when underlying state is incomplete or stale (`Blind Flange`, `Crosswalk`).
- **Zero-Friction Judge Inspection:** Shipping both a committed persistent Relate store in Git and a zero-install browser UI / WASM explorer so judges can test in seconds without paid LLM keys (`Crosswalk`, `Chokepoint Lab`, `SafeMeds`).
- **Rigorous Quantitative Baselines + Cold-Start CI:** Measuring head-to-head accuracy/efficiency against a realistic baseline and verifying README commands in CI (`Crosswalk`, `WAKE`).

### Why Waygraph Has Clear Whitespace
1. **Uncrowded Core Mechanism:** None of the 77 visible entries implement **adaptive graph desire paths**—constrained cursor exploration that promotes repeated verified walks into evidence-carrying shortcuts and invalidates them fail-closed under graph mutation.
2. **Direct Judge Resonance:** Evolves two foundational seeds from Judge Michael Hunger's `jexp/relate-ideas` (constrained graph-walking cursor + dynamic path index) into a unified, cryptographically fingerprinted, empirically benchmarked system.
3. **Meta-Relate Dogfooding:** Uses Relate's own official published documentation graph (4,133 nodes, 9,148 edges) as a primary benchmark corpus—every judge immediately understands the domain entities (`Capability`, `Page`, `Command`, `Flag`, `CookbookRecipe`, `Example`).
