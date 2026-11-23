# Waygraph --- Architecture

## Components and trust boundaries

-   **Relate:** authoritative store for source graph and shortcut
    evidence.
-   **Cursor MCP:** typed, bounded traversal interface; no arbitrary
    Cypher tool.
-   **Learning subsystem:** counts successful walks and promotes
    eligible paths.
-   **Validator:** checks every dependency immediately before shortcut
    reuse; fail-closed.
-   **Evaluation harness:** controlled baseline runs, raw traces,
    metrics.
-   **Viewer:** static HTML consuming exported traces/snapshots;
    presentation only.

## Logical data model

**Source node:** `node_id`, labels, properties, source reference.

**Source relationship:** `relationship_id`, start/end node IDs, type,
properties, source reference.

**Shortcut:** `shortcut_id`, start/end node IDs, ordered dependency IDs,
canonical dependency fingerprint, traversal count, status (`VALID`,
`STALE`, `DISABLED`), timestamps, validation reason, algorithm version.

Physical representation (shortcut relationship properties versus
dedicated shortcut node) must be selected only after verifying Relate
1.0.1 property/query support. The logical contract is mandatory.

## Cursor state

-   `current_node_id`, `start_node_id`
-   `visited_node_ids`
-   `walked_relationship_ids`
-   backtrack history
-   `max_hops`, cursor status

Operations: 1. `inspect_node(node_id)` 2.
`list_neighbors(node_id, direction, relationship_types?, limit?)` 3.
`follow_relationship(relationship_id)` 4. `backtrack()` 5. `get_walk()`
6. `find_shortcuts(start_node_id, goal_node_id)` 7.
`reuse_shortcut(shortcut_id)`

**Invariant:** follow succeeds only if the relationship was offered by a
fresh neighbor listing for the current node and its endpoint matches the
selected direction. Knowing an ID alone is not authorization.

**Invariant:** shortcut is traversable only after dependency validation
succeeds.

**Invariant:** hop, result, and timeout limits are enforced server-side.
The current implementation caps walks at 32 hops (default 8) and each
neighbor listing at 100 edges. A query timeout remains open because the
pinned Python API does not yet have a verified per-query timeout path.

## Shortcut lifecycle

``` text
walk observed
  -> promotion threshold reached?
  -> validate source path
  -> persist shortcut + ordered dependencies + fingerprint
  -> candidate shortcut
  -> validate on every reuse
       valid   -> return shortcut with evidence
       invalid -> mark stale, reject, require fresh walk
```

The current pilot threshold is 2 identical successful walks. The first
verified walk creates a `CANDIDATE`; the second promotes it to `VALID`.
The cursor assigns a walk ID and duplicate saves from that same walk do
not count twice. The threshold is a code constant and must be frozen
before final evaluation. Do not tune it on held-out test questions.

## Fingerprinting and invalidation

Canonical fingerprint includes: - ordered dependency relationship IDs; -
each dependency's start/end node IDs and type; - only semantically
relevant properties; - fingerprint schema/version.

Serialize deterministically and hash with SHA-256.

Validation: 1. Resolve every dependency. 2. Confirm existence,
endpoints, and type. 3. Recompute semantic fingerprint. 4. Compare with
stored fingerprint. 5. Check path continuity. 6. Check shortcut
endpoints match first/last path nodes. 7. Return valid only if all
checks pass.

The current relationship-property allowlist is `anchor`, `cell`, and
`role`, the relationship property keys in the imported docs snapshot.
Only these properties are included alongside edge identity, endpoints,
type, active state, and fingerprint schema version 2. Other source
relationship properties do not invalidate a shortcut. Revisit the
allowlist if another source dataset is added.

**Race condition:** validation and use can race with a mutation. Prefer
validation and use in one transaction/snapshot if supported. Otherwise
describe result as validated against a snapshot and do not claim
linearizable safety.

## Write model

-   One writer process per store.
-   Add process-level writer lock.
-   Bounded retry only for documented transient conflicts.
-   On retry, restart transaction and recompute read-dependent
    decisions.
-   Never blindly replay a partially applied sequence.
-   Readers use documented read-only mode or exported snapshots.
-   Conditions use isolated snapshots.

## MCP contract

Return structured results:
`{ "ok": bool, "data": ..., "error": { "code": ..., "message": ... } | null, "trace_id": ... }`

Current tools: `start_walk(session, origin, max_hops=8)`,
`inspect_walk(session)`, `follow_edge(session, edge_id)`,
`backtrack(session)`, `get_walk(session)`, `save_shortcut(session)`,
and `check_shortcut(shortcut_id)`. Every response carries a trace ID;
failures use the stable codes below. `follow_edge` requires an edge from
the latest inspection and rechecks that it is still an active outgoing
edge before moving the cursor.

Do not expose `execute_cypher` in Waygraph MCP. Native Relate MCP is
a separate benchmark condition.

## Error codes

`NODE_NOT_FOUND`, `RELATIONSHIP_NOT_AVAILABLE`,
`RELATIONSHIP_NOT_CONNECTED`, `HOP_LIMIT_REACHED`, `CURSOR_NOT_STARTED`,
`SHORTCUT_NOT_FOUND`, `SHORTCUT_STALE`, `SHORTCUT_DISABLED`,
`DEPENDENCY_MISSING`, `DEPENDENCY_CHANGED`, `PATH_DISCONTINUITY`,
`WRITE_CONFLICT`, `DATABASE_UNAVAILABLE`, `INVALID_ARGUMENT`.

## Security

-   Bound all reads and tool outputs.
-   Accept IDs/enums, not arbitrary query strings.
-   Treat graph content and tool output as untrusted data, not
    instructions.
-   Never commit secrets or sensitive personal data.
-   Escape graph labels/properties in the viewer.
