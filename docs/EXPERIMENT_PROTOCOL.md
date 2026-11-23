# Waygraph --- Experiment Protocol

## Research question

Does a constrained graph cursor with reusable evidence-carrying
shortcuts improve efficiency or reliability over agent-written Cypher on
Relate, while preserving answer correctness under graph mutations?

## Hypotheses

-   H1: On repeated/related questions, shortcuts reduce graph calls,
    hops, or tokens relative to cold cursor walks.
-   H2: On small models or unfamiliar schemas, typed cursor tools
    improve exact accuracy or reduce invalid query attempts versus
    agent-written Cypher.
-   H3: Dependency-aware validation rejects shortcuts whose underlying
    facts changed.
-   H4: Strong models may outperform the cursor on cold, simple
    questions; this is an expected regime, not an invalid experiment.

## Conditions

**A --- Native Relate MCP:** agent inspects schema and writes read-only
Cypher using official Relate MCP; no Waygraph tools.

**B --- Waygraph:** agent uses typed cursor and shortcut tools only;
no arbitrary Cypher exposed.

The current `agent-eval` command supplies in-process adapters for
cursor operations and bounded read-only Cypher. These are useful for
runner development, but they do not launch either MCP server and must
not be reported as the protocol's official MCP A/B comparison. The
protocol comparison remains pending until the agent is connected to the
actual MCP servers on paired snapshots.

**C --- Vector RAG (optional):** same corpus, fixed chunking/index, no
graph traversal; add only after A/B is stable.

## Dataset and questions

Primary: published Relate documentation graph.

Archive source bytes/revision, retrieval time, license/attribution,
SHA-256, size, schema, and import version.

Generate about 30 questions requiring 2--5 relationship traversals.
Cover relation types, branches, and plausible alternatives. Gold answers
are computed independently using direct graph queries or a deterministic
oracle, never by the cursor or LLM.

Each question record includes `question_id`, `graph_snapshot_id`,
question text, start node, expected answer, gold path(s), equivalence
rule, and difficulty metadata.

`graph_snapshot_id` is a deterministic SHA-256 over sorted source entities
and relationships, excluding learned shortcut records. `question_id` is
derived from that snapshot ID, origin, and ordered gold edge IDs. Gold
paths are first generated from graph neighbors and then independently
resolved through direct edge lookups before cursor replay.

Use 10 pilot questions for debugging and 20 held-out evaluation
questions. Freeze the question set and promotion threshold before
headline runs. Exclude questions requiring unstored semantic
interpretation.

The current pilot's promotion threshold is two verified occurrences of
the same ordered path. This remains fixed for the pilot unless a new
threshold is documented before any held-out run.

## Fairness controls

-   Same graph snapshot for paired A/B runs.
-   Same question, answer schema, model, temperature, max output tokens,
    timeout, and retry budget.
-   Randomize condition order where practical.
-   Run each question at least 3 times for stochastic models.
-   Record model/provider version and run date.
-   Separate cold-start and warm-start.
-   Isolate condition state to prevent shortcut leakage.
-   Define cache policy explicitly.
-   Gold oracle is independent from cursor.
-   Record failures; do not silently discard them.

## Metrics

Primary: - exact and predeclared normalized answer accuracy; - input and
output tokens; - tool calls; - end-to-end latency.

Cursor: - traversal hops; - neighbor-list calls; - shortcut candidate
hits and reuse success; - promotion count; - stale rejections; - invalid
transition attempts; - baseline invalid Cypher attempts.

Mutation: - stale shortcut rejection rate; - false-valid rate; -
false-stale rate; - post-mutation accuracy; - calls/time to recover a
fresh route.

## Mutation matrix

Test: delete dependency edge; change endpoint; change type; change
semantically relevant property; change irrelevant property; delete
intermediate node; break path continuity.

For each: create shortcut, mutate via controlled writer, attempt reuse,
assert stale rejection with reason, perform fresh traversal, compare
against new gold state.

Target zero false-valid acceptance in the deterministic mutation suite.
This does not prove correctness for all possible mutations.

## Result record schema

`run_id`, `timestamp_utc`, `condition`, `question_id`,
`graph_snapshot_id`, `model_id`, `prompt_version`, `success`, `answer`,
`gold_answer`, `is_correct`, `input_tokens`, `output_tokens`,
`tool_calls`, `traversal_hops`, `shortcut_hits`, `latency_ms`,
`error_code`, `trace_path`.

## Reporting

Report raw numerator/denominator, mean/median/std/range for latency and
tokens, paired per-question comparisons, model identifiers, prompt
hashes, run dates, failures, and sample size. Avoid claims of
significance with tiny samples.

## Decision criteria

Continue if correctness is not materially worse than native MCP on
held-out questions, at least one target segment shows a reproducible
benefit, and the mutation suite has no false-valid acceptance. Scope
conclusions to the measured workload and models.
