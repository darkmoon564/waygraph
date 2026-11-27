# Waygraph — Reproducible Benchmark & Verification Results

**Updated:** 28 November 2026  
**Engine:** `relate-db==1.2.0` · **Corpus:** Relate Documentation Graph (`4,133` entities, `9,148` relationships, snapshot `d691ad319bfeb28b18d07ec5a2bc59eaeea2cf88f76ae6671294ac12beba78ae`)

---

## 1. Three-Regime Desire-Path Lifecycle (`waygraph lifecycle-bench`)

Evaluated deterministically on `data/questions/relate-docs-v2.jsonl` (`24` natural 3-hop goal-oriented questions across 6 recurring documentation corridors, `status: reviewed`, zero intermediate route disclosure):

| Regime | Exact Accuracy | Total Cursor Steps | Steps / Question | Shortcut Hits | Step Reduction vs. Cold |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Cold Cursor** *(no shortcuts)* | `24/24` (`100%`) | `72` | `3.00` | `0` | baseline |
| **Warm Waygraph — Pass 1** *(learns live, threshold = 2)* | `24/24` (`100%`) | `60` | `2.50` | `12` (`6` corridors promoted) | **`-16.7%`** |
| **Warm Waygraph — Steady State** | `24/24` (`100%`) | `48` | `2.00` | `24` | **`-33.3%`** *(`-67%` on full 3-hop shortcuts)* |

---

## 2. Post-Mutation Safety vs. Naive Path Cache (Real Docs Graph)

After promoting the 3-hop shortcut `Capability:agent-memory -> Page:get-started/agent-memory -> Page:guides/agents/connect-over-mcp -> Flag:read-only`, six realistic documentation-evolution mutations were applied on isolated copies of the Relate documentation graph:

| Mutation Case | Expected Valid | Naive Path Cache | Waygraph Validator | Reason Code | Live Reroute Recovery |
| :--- | :---: | :---: | :---: | :--- | :---: |
| `disable_mid_edge` | `False` | Accepted (**FALSE VALID**) | Rejected (`STALE`) | `DEPENDENCY_INACTIVE` | Recovered (`2` hops via `model-agent-memory`) |
| `delete_mid_edge` | `False` | Accepted (**FALSE VALID**) | Rejected (`STALE`) | `DEPENDENCY_MISSING` | Recovered (`2` hops via `model-agent-memory`) |
| `retarget_final_edge` | `False` | Accepted (**FALSE VALID**) | Rejected (`STALE`) | `ENDPOINT_MISMATCH` | N/A (target removed) |
| `change_edge_kind` | `False` | Accepted (**FALSE VALID**) | Rejected (`STALE`) | `DEPENDENCY_CHANGED` | Recovered (`2` hops via `model-agent-memory`) |
| `mutate_semantic_role` | `False` | Accepted (**FALSE VALID**) | Rejected (`STALE`) | `DEPENDENCY_CHANGED` | Recovered (`2` hops via `model-agent-memory`) |
| `mutate_non_semantic_note` | `True` | Accepted | Accepted (`VALID`) | `null` | Retained (no false stale) |

- **Naive Path Cache:** **`5/5` false-valid** (`100%` silent staleness failure)
- **Waygraph:** **`0` false-valid, `0` false-stale, `4/4` live reroute recoveries**

---

## 3. Synthetic 8-Scenario Invalidation Matrix (`waygraph mutations`)

All 8 isolated synthetic mutation scenarios (`disable_dependency`, `delete_dependency`, `change_endpoint`, `change_type`, `change_relevant_property`, `change_irrelevant_property`, `delete_intermediate_node`, `break_continuity`) pass with **`0` false-valid** and **`0` false-stale** outcomes.

---

## 4. Reproducing Paired LLM Agent Benchmarks (BYO API Key)

Per organizer guidelines, no API keys are committed in this repository. Judges or contributors can run a complete, checkpoint-resumable paired comparison over real **MCP stdio** (`waygraph`) vs. bounded native Cypher (`native-cypher`) on the curated 2-corridor subset (`data/questions/relate-docs-v2-paired6.jsonl`, 6 questions — fits inside free daily quotas) or the full 24-question `relate-docs-v2.jsonl`:

```bash
# 1. Waygraph over real MCP stdio subprocess (learns & reuses desire paths)
waygraph agent-eval \
  --provider openrouter \
  --model google/gemma-4-31b-it:free \
  --condition waygraph \
  --transport mcp-stdio \
  --questions-file data/questions/relate-docs-v2-paired6.jsonl \
  --split pilot \
  --output experiments/results/paired6-waygraph \
  --resume

# 2. Native Cypher baseline over the exact same native labels/relationships
waygraph agent-eval \
  --provider openrouter \
  --model google/gemma-4-31b-it:free \
  --condition native-cypher \
  --questions-file data/questions/relate-docs-v2-paired6.jsonl \
  --split pilot \
  --output experiments/results/paired6-cypher \
  --resume
```

Supported providers: `openrouter` (`OPENROUTER_API_KEY`), `gemini` (`GEMINI_API_KEY`), `groq` (`GROQ_API_KEY`), `cerebras` (`CEREBRAS_API_KEY`), `anthropic` (`ANTHROPIC_API_KEY`), or local `ollama` (no key required).

*(Historical note: An earlier Nov 19 pilot on `v1` using OpenRouter's free router answered `3/4` completed questions exact before hitting the free daily limit; deterministic lifecycle and mutation results above are always reported separately from stochastic LLM runs.)*

---

## 5. Continuous Integration Verification

GitHub Actions (`.github/workflows/ci.yml`) verifies clean-clone installation, full `pytest` suite (`50+` tests including live `mcp-stdio` subprocess, `showcase.rl`, `viewer/index.html`, and `benchmark_v2`), `waygraph mutations`, and `waygraph lifecycle-bench` across **Python 3.11, 3.12, and 3.13**.
