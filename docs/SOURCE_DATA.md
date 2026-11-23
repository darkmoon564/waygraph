# Source graph snapshot

## Provenance

- Dataset: Relate documentation graph, format 1.
- Source: <https://relatedb.ai/docs/graph.json>.
- Schema documentation: <https://relatedb.ai/docs/reference/docs-graph/>.
- Retrieved: 2026-11-17.
- Source `verified` value: `1.0.1`.
- Archived bytes: [`data/source/relate-docs-graph.json`](../data/source/relate-docs-graph.json).
- Size: 6,854,955 bytes.
- SHA-256: `7efa0f16f8ff8d6d5b5dc021449a84a64f7f4f0902eae95c139b06ed0e714249`.
- Attribution and license: Relate Authors; the published documentation identifies the project license as Apache-2.0. Retain this attribution with redistributed snapshots.

The graph build documentation says the source is generated deterministically from the published pages, glossary, cookbook recipes, CLI facts, and capability catalog. The JSON contains all node and relationship records but omits the Section embeddings; the separate seed script and `.rl` store contain those vectors.

## Observed JSON schema

Top-level fields in the archived file are `format`, `kind`, `note`, `verified`, `seed`, `embeddings`, `nodes`, and `relationships`. `format` is `1`, `kind` is `documentation`, and `seed` points to `https://relatedb.ai/docs/graph.cypher`.

Each node has a stable `id` in `Label:id` form, a `labels` array, and a `properties` object. The snapshot has 4,133 nodes across 11 labels:

| Label | Count |
| --- | ---: |
| Page | 142 |
| Section | 1,643 |
| Example | 2,004 |
| Term | 65 |
| Surface | 16 |
| CookbookRecipe | 11 |
| Command | 12 |
| Flag | 96 |
| Index | 2 |
| Capability | 20 |
| Problem | 122 |

Each relationship has `type`, `start`, `end`, and `properties`. The archived file has 9,148 directed relationships across 15 types. The property values observed in this snapshot are strings, integers, booleans, and lists; the importer keeps a canonical JSON copy as well as queryable prefixed scalar/list properties.

The import adapter reifies each source relationship as a `DPEdge` node to retain a stable application-level ID. The ID is a SHA-256 of the canonical source relationship record plus an occurrence index for exact duplicate records. It preserves source node IDs, labels and properties, relationship type, source endpoints, and relationship properties. The downloaded file's SHA-256 is computed at import time and attached to imported records and the CLI result.

For shortcut fingerprints, the semantic relationship-property allowlist is `anchor`, `cell`, and `role`, the three keys present in this snapshot. A relationship fingerprint also covers its application ID, endpoints, type, active state, and fingerprint schema version. Other relationship metadata does not invalidate the shortcut.

## Snapshot manifest

[`data/source/manifest.json`](../data/source/manifest.json) records the source URL, retrieval date, checksum, byte count, format/version, and imported counts. Recompute and compare the checksum before using a replacement download. Keep each evaluation condition on an isolated Relate store for a fixed snapshot.
