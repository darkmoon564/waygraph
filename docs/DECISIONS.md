# Waygraph --- Architecture Decision Records

## ADR-001: Relate is authoritative

**Status:** Accepted. Source graph, shortcuts, and dependency evidence
live in Relate. Exported JSON is presentation-only. This makes graph
relationships central to the use case.

## ADR-002: Directory-backed store

**Status:** Accepted, runtime verification pending. Use persistent
directory mode for inspectability and reader workflow. If concurrent
read behavior is not supported in the pinned version, readers use
exported snapshots. README must state mode and rationale.

## ADR-003: Constrained cursor MCP

**Status:** Accepted. Typed operations over stable IDs; no arbitrary
Cypher exposed in Waygraph. Native Relate MCP remains a separate
benchmark condition.

## ADR-004: Fail-closed shortcut validation

**Status:** Accepted. Every reuse validates ordered dependencies,
endpoints, continuity, type, and semantic fingerprint. Any unverifiable
dependency rejects the shortcut.

## ADR-005: Application-controlled mutation path

**Status:** Accepted for pilot. Do not assume triggers or CDC. Mutations
go through the controlled writer; reuse validation also detects
out-of-band changes.

## ADR-006: One writer process

**Status:** Accepted. Enforce one writer per store. Retry only
documented transient conflicts; restart transaction and recompute
read-dependent decisions.

## ADR-007: Independent gold answers

**Status:** Accepted. Gold answers come from direct graph queries or
independent deterministic oracle, never cursor or LLM.

## ADR-008: Acknowledge prior seeds

**Status:** Accepted. Attribute existing graph-walking cursor and
dynamic path-index ideas in Relate Ideas. Differentiation is integrated
learning lifecycle, evidence-carrying shortcuts, invalidation, mutation
evaluation, and measured comparisons.

## ADR-009: Viewer after correctness

**Status:** Accepted. Static viewer is P1. First deliver actual Relate
integration, cursor, shortcut lifecycle, and mutation tests.
