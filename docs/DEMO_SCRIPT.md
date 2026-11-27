# Waygraph — 1:55 Live Demo Script

**Target:** `1:45–1:55` (strictly `<= 2:00`). Show live, real outputs—no slides-only walkthrough.

---

### 0:00–0:15 — The Problem & Pitch
- **Visual:** Open `viewer/index.html` (**Waygraph Studio**) showing the 4,133-entity / 9,148-relationship Relate documentation graph.
- **Narration:** *"AI agents exploring unfamiliar graphs either burn tokens rewriting Cypher from scratch or rely on stale caches that silently lie when facts change. Waygraph brings urban-planning desire paths to Relate 1.2.0: bounded cursor walks that promote repeated verified routes into SHA-256-fingerprinted shortcuts—and fail closed the instant an underlying edge mutates."*

### 0:15–0:45 — Walk 1 (`CANDIDATE`) → Walk 2 (`VALID` Promotion) → Walk 3 (`1-Step Jump`)
- **Visual:** Click through **Scenario 1** (`Walk 1: Bounded Exploration -> CANDIDATE`), **Scenario 2** (`VALID` golden arc appears at `walk_count = 2`), and **Scenario 3** (`1-Step Shortcut Jump + SHA-256 Receipt` — `3` hops compressed into `1` cursor step, `-67%` steps).
- **Narration:** *"First, the cursor can only follow active outgoing edges offered by Relate. After two independent verified walks across `Agent memory -> --read-only`, Waygraph promotes a `DPShortcut` node storing ordered dependency edge IDs and a canonical SHA-256 fingerprint. On walk three, the agent jumps all three hops in one verified step."*

### 0:45–1:20 — Live Mutation → Fail-Closed `SHORTCUT_STALE` → Automatic Reroute
- **Visual:** In **Waygraph Studio**, **click a gold dependency edge** directly on the graph canvas (or play **Scenario 4**). Watch the toast alert, the golden arc flash crimson **`STALE (DEPENDENCY_INACTIVE)`**, the Inspector's live SHA-256 diverge, and the purple **live reroute** path light up via `Page:guides/agents/model-agent-memory -> Flag:read-only`.
- **Narration:** *"Now watch what happens when we disable an underlying relationship. A naive cache keeps returning the stale path. Waygraph recomputes the SHA-256 proof at read time, rejects the shortcut fail-closed as `DEPENDENCY_INACTIVE`, marks it `STALE` in Relate, and reroutes over live edges."*

### 1:20–1:45 — Real Relate Store & One-Command Reproducible Proof
- **Visual:** Terminal split:
  1. Inspect committed `data/relate/showcase.rl` (`MATCH (s:DPShortcut) RETURN s.status, s.walk_count, s.reuse_count, s.validation_reason`).
  2. Run `waygraph lifecycle-bench` showing `Cold 72 steps -> Warm 48 steps (-33.3%)`, **`Naive Cache 5/5 false-valid` vs. `Waygraph 0 false-valid, 4/4 live reroutes`**, and `pytest -q` (`50+ passed`).
- **Narration:** *"Everything lives natively in Relate 1.2.0—dual domain labels, full-text search, and a committed single-file `showcase.rl` store. On our 24-question multi-hop benchmark, desire paths cut steady-state steps by 33% with zero stale acceptances versus 5-for-5 staleness on a naive cache."*

### 1:45–1:55 — Close
- **Visual:** GitHub repo (`github.com/darkmoon564/waygraph`) with green Python 3.11–3.13 CI badges.
- **Narration:** *"Waygraph lets the graph teach the agent where to walk—and lets cryptographic evidence tell it when a shortcut is no longer safe. Clone it, open `viewer/index.html`, or query `showcase.rl` in seconds."*
