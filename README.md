# Waygraph

Evidence-bearing shortcuts learned from verified graph walks, with fail-closed invalidation when underlying relationships change.

## Use case
AI agents exploring unfamiliar graph schemas can waste tokens generating Cypher or accidentally invent traversals. Waygraph exposes only real outgoing edges, records verified walks, and learns reusable shortcuts that carry evidence.

## How it uses Relate
- **Mode:** directory-backed persistent Relate store (`data/relate/pilot`).
- **Why:** one writer owns the store; directory mode also permits a separate read-only opener.
- **Graph:** `DPEntity` nodes; `DPEdge` nodes representing source facts with stable application IDs; `DPShortcut` nodes storing path evidence and fingerprints. `DP_FROM`, `DP_TO`, `DP_SHORTCUT_FROM`, `DP_SHORTCUT_TO` are actual Relate relationships.
- The pilot uses edge-as-node reification to preserve stable application-level dependency IDs. This is a deliberate modeling trade-off, not a claim that Relate lacks native relationships.

## Setup and run
Requires Python 3.11–3.13 and a supported `relate-db==1.0.1` platform wheel.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
waygraph import-docs
waygraph questions --limit 30 --pilot-count 10 --output data/questions/relate-docs-v1.jsonl
waygraph pilot --questions-file data/questions/relate-docs-v1.jsonl --split pilot
waygraph repeat-pilot --questions-file data/questions/relate-docs-v1.jsonl --split pilot --repetitions 3
waygraph agent-eval --condition cursor --questions-file data/questions/relate-docs-v1.jsonl --split pilot
waygraph mutations --output experiments/results/mutations.json
pytest -q
```

For a fresh isolated walkthrough after installing dependencies, run
`waygraph demo`. It imports into `data/relate/demo`, replays the
reviewable pilot question split, and runs the deterministic mutation
matrix. Choose a new `--db` directory for each run; the command refuses
to overwrite an existing store. Results are written under
`experiments/results/demo/`. For alternate locations, pass `--db`,
`--output`, or `--source` after `demo`.

`repeat-pilot` makes one fresh isolated Relate store per repetition and
writes a combined summary under the selected output directory. The
source store must match the frozen question snapshot. Heldout runs remain
blocked while the manifest is a draft.

`agent-eval` defaults to OpenRouter and requires `OPENROUTER_API_KEY`; it selects
`nvidia/nemotron-3-ultra-550b-a55b:free`, a currently free tool-capable model.
Use `--model openrouter/free` to dynamically route across free models; the
actual model served is recorded per request, but results vary by model.
OpenRouter receives a per-question sticky session ID and the default
completion budget is 2,048 tokens. Current free availability and rate
limits can change. Pass `--provider gemini` to use
`GEMINI_API_KEY` or `--provider anthropic` to use `ANTHROPIC_API_KEY`.
It runs a function/tool
calling loop with temperature 0 and writes one JSONL tool trace per
repetition. `cursor` is the constrained cursor condition;
`native-cypher` is a bounded, read-only in-process Cypher adapter, not the
official Relate MCP baseline. Use only the pilot split until a human
approves a revised benchmark question set.

The CLI loads `.env` from the project working directory; inherited shell
variables take precedence. Install the updated dependencies with
`python -m pip install -e '.[dev]'` first. OpenRouter
uses the Python standard library; Gemini and Anthropic users can install
their provider SDK with `python -m pip install -e '.[gemini]'` or
`python -m pip install -e '.[anthropic]'`.

The generated question file is a draft until its manifest's semantic review status is changed to `reviewed` after human review. The CLI blocks `--split held_out` while the manifest remains a draft.

Run the MCP server with `python -m waygraph.mcp_server`. Set `WAYGRAPH_DB` to override the default store path. The MCP host must launch only one writer process per store.

Cursor MCP tools return `{ok, data, error, trace_id}` envelopes. A walk defaults to 8 hops and cannot exceed 32; each inspection returns at most 100 outgoing edges. The cursor only follows an edge offered by its latest inspection and checks that it is still available before advancing.

## Where the data lives
The imported documentation graph is stored in `data/relate/pilot/` (ignored by Git). **Before submission, checkpoint and commit a small judge-inspectable persistent store or reproducible store artifact.** The `seed` command writes a separate, synthetic graph for a quick API smoke test; use `waygraph --db data/relate/synthetic seed` to keep it separate from the docs snapshot.

The published Relate documentation graph snapshot is archived at `data/source/relate-docs-graph.json`; its schema, source URL, license attribution, SHA-256, and imported counts are recorded in [`docs/SOURCE_DATA.md`](docs/SOURCE_DATA.md). `waygraph import-docs` imports that snapshot while retaining source labels, properties, typed relationships, and endpoints. Relationship IDs are deterministic hashes of each source relationship record, including an occurrence number for duplicate records. Use a fresh store for a new source snapshot so each evaluation has an isolated graph state.

## Honest pilot scope
- `pilot` is a deterministic oracle replay using precomputed paths. Its accuracy and timing are **not** an LLM-vs-Cypher benchmark.
- A shortcut is a candidate after one verified walk and becomes reusable after the same ordered path is verified in a second walk. Repeated saves from one walk count once. The current property fingerprint allowlist is `anchor`, `cell`, and `role`.
- No tokens, LLM correctness, vector RAG, or agent-generated Cypher scores are reported until real model runs are integrated.
- `questions` creates graph-derived path prompts; a separate semantic validity review is needed before presenting these as realistic user questions.
- Shortcuts are revalidated on every read; mutations made outside this writer cannot cause silent reuse because validation checks the current underlying facts. A shortcut may still become stale after validation and before use if another writer changes the graph; production deployment needs an atomic read/validate/use transaction.
- The Anthropic evaluation harness remains an integration task. The synthetic seed is retained as a small API smoke test alongside the archived documentation graph.

## Prior art and attribution
The graph cursor and dynamic path-index ideas appear in Michael Hunger's `jexp/relate-ideas`. Waygraph explores evidence-bearing learning, explicit invalidation, and reproducible evaluation. Significant AI assistance was used to scaffold the project; review and verify code and outputs before submitting.
