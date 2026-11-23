# Waygraph --- Implementation Plan

**Plan date:** 17 November 2026\
**Repository:** `waygraph`\
**Internal v1 target:** 8 December 2026\
**Hackathon deadline:** 11 December 2026, 6:00 PM PST / 12 December
2026, 7:30 AM IST

## Progress note --- 17 November 2026

Gate 0 source reconnaissance and the first importer slice are complete:
the published `graph.json` has been archived with a SHA-256 manifest,
`relate-db==1.0.1` passed an isolated Python 3.13 smoke check, and the
snapshot was imported into the directory store and reopened read-only
with the expected 4,133 entity and 9,148 relationship counts. See
`SOURCE_DATA.md` and `API_COMPATIBILITY.md` for evidence. Python 3.11,
write-conflict behavior, relationship ID stability across reopen, and
the remaining Gate 1 cursor/evaluation work are still open.

The cursor now requires a recent neighbor offer before following an edge,
revalidates that offer against the live graph, caps walks at 32 hops
(default 8), and returns structured MCP responses with trace IDs and
stable error codes. The evaluation runner now inspects before following.
The deterministic cursor test matrix passes. An MCP 1.30.0 stdio smoke
test initialized the server, listed its tools, and called `start_walk`;
the fresh-clone launch check remains open. Query-timeout support is also
still unverified.

Question IDs are now derived from a deterministic source-graph snapshot
hash and ordered path. The oracle resolves each gold path through direct
edge reads before cursor replay. Shortcuts are candidates after the first
verified walk and promote after the second; versioned fingerprints cover
the documented relationship-property allowlist. The unit suite currently
passes 23 tests, including mutation, question identity, oracle, importer,
and MCP envelope cases. MCP is pinned to 1.x because the v2 API removed
the server import used by this project.

The frozen question draft is `data/questions/relate-docs-v1.jsonl` with
30 questions, a deterministic 10/20 split, graph snapshot
`d691ad319bfeb28b18d07ec5a2bc59eaeea2cf88f76ae6671294ac12beba78ae`,
and file SHA-256 `02d114654ad2268b4b528c206ef3b10bfdbdedfcf5a66844ac86d6d18ecc186e`.
Each prompt names every hop destination; an automated audit confirms all
30 routes resolve uniquely. Human language/usability review is still
pending, and the loader blocks held-out replay until the manifest is
marked `reviewed`.

The 10-question pilot split replayed at 10/10 oracle accuracy on a fresh
isolated import. It promoted no shortcut and recorded zero reuse hits,
which is expected because these paths each occurred once. This is an
engine replay, not an agent benchmark. The suite now passes 23 tests.

`waygraph mutations` runs eight isolated synthetic mutation scenarios:
disable/delete dependency, endpoint/type change, relevant/irrelevant
property change, intermediate-node deletion, and continuity break. All
eight matched their expected result with zero false-valid and zero
false-stale outcomes. The JSON report is written under the ignored
`experiments/results/` directory.

## Progress note --- 18 November 2026

The CI unit-test matrix now targets Python 3.11--3.13. Relate 1.0.1's
transaction API and sequential read-only reopen behavior are recorded
from runtime evidence; concurrent reader/writer behavior and conflict
classification remain open. An isolated repeat-pilot command ran twice
on fresh stores with 20/20 deterministic oracle replays correct.

An Anthropic tool-use runner now supports in-process cursor and bounded
read-only Cypher adapters and records JSONL tool traces, tokens, calls,
hops, latency, model, and prompt hash. Its tool loop passes mocked
tests, but a real run is blocked in this environment because the
Anthropic SDK/API key are unavailable. These adapters do not count as
the planned MCP-to-agent comparison. The human question review also
found the current routes disclose all hop information, so the frozen
question manifest remains draft and held-out replay remains blocked.

## Mission

Build an evidence-carrying, self-improving graph traversal interface for
AI agents. Agents explore only relationships returned by Relate.
Repeated successful traversals can become reusable shortcut
relationships ("desire paths"). A shortcut is reusable only while its
complete dependency path remains valid.

Success means demonstrating a workload where constrained graph traversal
improves cost, reliability, or both against agent-written Cypher,
without sacrificing answer correctness.

## Product principles

1.  Relate is the source of truth for source entities, relationships,
    and shortcut records.
2.  Cursor tools expose only real, currently traversable relationships;
    no arbitrary Cypher is accepted by the cursor.
3.  Every shortcut records ordered dependency relationships and a
    deterministic fingerprint.
4.  Missing, changed, ambiguous, or unverifiable dependencies make a
    shortcut unusable.
5.  Accuracy is a gate, not a metric to silently trade for fewer tokens.
6.  Experiments are reproducible: fixed graph snapshots, question IDs,
    model IDs, seeds, and run metadata.
7.  Deterministic engine tests and LLM agent evaluations are reported
    separately.

## Scope

### P0 --- required for v1

-   Import the published Relate documentation graph into a persistent
    directory store.
-   Inspect and document the actual source JSON schema before
    implementing the importer.
-   Implement typed cursor operations: inspect node, list neighbors,
    follow returned edge, backtrack, inspect walk, and reuse shortcut.
-   Cursor accepts stable IDs and enumerated parameters, never
    agent-authored Cypher.
-   Detect repeated successful paths and create shortcut
    records/relationships.
-   Validate shortcut dependencies before every reuse; stale shortcuts
    fail closed.
-   Test traversal, path ordering, fingerprints, invalidation, and
    write-conflict handling.
-   Generate approximately 30 multi-hop questions; derive gold answers
    independently from the cursor.
-   Compare native Relate MCP / agent-authored Cypher with Waygraph
    cursor. Add vector RAG only if time permits.
-   Record accuracy, input/output tokens, tool calls, hops, latency,
    shortcut hits, and mutation outcomes.
-   Provide one-command demo, README, inspectable persistent store, and
    1--2 minute demo video.

### P1 --- desirable

-   Vector RAG baseline.
-   Static HTML viewer with walk replay and shortcut lifecycle.
-   Second dataset (ADR log).
-   Cold/warm learning curve.
-   Small-model versus stronger-model comparison.

### P2 --- defer

-   Multi-agent concurrent writers, distributed service, generalized
    graph rewriting, complex optimization, production multi-tenant
    security, third dataset (deps.dev) unless P0 is complete.

## Architecture

``` text
Question -> LLM agent
              |                         |
              v                         v
       Native Relate MCP          Waygraph MCP
       schema + Cypher            typed cursor tools
              |                         |
              +-----------+-------------+
                          v
                    Relate graph
                          |
                 shortcut + evidence
                          |
                 validation on reuse
                          |
                 structured trace/result
                          |
                    eval harness
```

Relate remains authoritative. Evaluation logs can be JSONL/CSV, but
shortcut truth and dependencies must be represented in or verifiably
derived from Relate.

## Phases and exit gates

### Gate 0 --- API and dataset reconnaissance (Day 1)

-   Pin `relate-db==1.0.1` and Python version.
-   Install in a clean environment and run connect/create/query/close
    smoke test.
-   Record exact signatures and supported Cypher in
    `docs/API_COMPATIBILITY.md`.
-   Download and inspect source graph schema, IDs, labels, edges,
    properties, size, and license.
-   Create persistent directory store; verify reader behavior only if
    documented/supported.

**Exit:** Relate smoke test passes; importer schema is based on observed
JSON; source checksum and provenance recorded.

**Stop condition:** If installation/import fails, do not build on
assumptions. Reproduce with a tiny hand-authored graph and resolve
compatibility first.

### Gate 1 --- 48-hour pilot (Days 1--2)

-   Implement deterministic importer and graph adapter.
-   Implement cursor state machine and typed operations.
-   Generate 30 multi-hop questions.
-   Compute gold answers independently using direct graph queries /
    deterministic oracle.
-   Test deterministic traversal correctness.
-   Run initial agent comparisons on a fixed subset.

**Exit:** 30 stable question IDs, graph snapshot IDs, independent gold
answers, valid cursor transitions, parseable results, raw traces,
environment metadata, and a written go/no-go memo.

**Continue if:** no cursor-attributable correctness regression and at
least one credible benefit remains plausible (small-model accuracy,
tokens, unknown-schema robustness, or provenance). If it loses across
all metrics after one focused redesign, narrow or pivot.

### Gate 2 --- Stable cursor and baselines (by Day 10)

-   Finalize MCP schemas, errors, and invariants.
-   Run native MCP and cursor end to end.
-   Version datasets, questions, and gold answers.
-   Keep viewer to debug trace only.

### Gate 3 --- Learning and invalidation (by Day 15)

-   Promote repeated successful walks into shortcuts.
-   Store ordered dependency IDs and endpoint identity.
-   Validate before every reuse.
-   Test deleted edges, changed endpoints, changed relevant properties,
    and missing dependencies.
-   Reject stale shortcuts and audit the reason.

### Gate 4 --- Evaluation and feature freeze (by Day 19)

-   Repeat fixed workloads across models.
-   Separate cold and warm results.
-   Report mutation results and run-to-run variation.
-   Freeze features; fix only correctness, reproducibility, and demo
    blockers.

### Gate 5 --- Submission (Days 20--23)

-   README follows official template and states Relate mode and why.
-   Public repo has required `relate` topic and recommended
    `relate-neo4j-hackathon`.
-   Persistent store is committed or inspectable.
-   Fresh clone runs one-command demo.
-   Submitter records 1--2 minute video.
-   Disclose AI use and reused code; document caveats.
-   Submit v1 by Dec 8; Dec 9--11 are contingency and
    submission-verification days.

## Milestones

  -----------------------------------------------------------------------
  Date                    Milestone               Evidence
  ----------------------- ----------------------- -----------------------
  Nov 17                  Repo, API smoke test,   Commit, smoke log,
                          source graph inspection schema note

  Nov 18--19              48-hour pilot           30 questions, baseline
                                                  results, decision memo

  Nov 20--26              Cursor hardening +      Tests, repeatable eval
                          native MCP comparison   

  Nov 27--Dec 1           Shortcut learning +     Mutation tests and
                          invalidation            trace

  Dec 2--5                Full metrics + viewer + Results report and
                          docs                    screenshots

  Dec 6--8                Freeze, demo,           Release tag and Devpost
                          fresh-clone check, v1   entry

  Dec 9--11               Contingency only        Final audit
  -----------------------------------------------------------------------

## Definition of done

A reviewer can clone the public repo, install dependencies, run the
demo, inspect the persistent Relate store, replay a walk, observe
shortcut creation, mutate a dependency, and see stale shortcut
rejection.

## Engineering rules

-   One process owns writes to a store.
-   Concurrent readers only where supported by the pinned Relate
    version; otherwise use exported snapshots.
-   Retry only documented transient write conflicts with bounded
    exponential backoff and jitter.
-   Never retry validation errors or deterministic query failures.
-   Each evaluation condition uses an isolated graph snapshot.
-   Gold answers never use the cursor or LLM.
-   Never report deterministic oracle replay as an LLM agent benchmark.
-   Do not claim hallucinations are impossible; say cursor traversal
    cannot follow an edge the graph did not offer.
