# Relate 1.2.0 — API Compatibility Record

**Status:** Runtime-verified on Windows / Python 3.13 (`cp39-abi3` universal wheel) across `:memory:`, directory stores, portable single-file `.rl` stores, native full-text indexing, and concurrent `read_only=True` readers alongside an active directory writer.
**Pinned dependency:** `relate-db==1.2.0` (upgraded from `1.0.1` on 25 November 2026)
**Tested Python:** 3.13 locally; CI matrix covers 3.11–3.13.

## Documented and runtime-verified usage

Installed `1.2.0` signatures:

```text
relate.connect(database: str = ':memory:', namespace: str = 'neo4j', read_only: bool = False) -> relate.connection.Connection
Connection.execute(query: str, params: Optional[Dict[str, Any]] = None)
```

`Connection` exposes `autocommit` (default `True`), `closed`, `commit()`, `cursor()`, `execute()`, `executemany()`, `flush()`, `namespace`, `rollback()`, `set_namespace()`, and `close()`. `relate.Database` additionally exposes `execute_arrow()`, `labels`, `relationship_types`, `node_count`, and `relationship_count`.

With `autocommit=False`, the first statement opens a transaction; `commit()` and `rollback()` end it. Closing with an open transaction rolls it back. No per-query timeout parameter is exposed on `Connection.execute`; Waygraph enforces server-side hop (`max_hops <= 32`) and result (`LIMIT <= 100`) bounds.

## Verified 1.2.0 capabilities leveraged by Waygraph

| Capability | Status | Runtime Evidence |
|---|---|---|
| Universal `cp39-abi3` wheel on Python 3.13 | Pass | Installed `relate-db==1.2.0`; 32/32 test suite passed in 3.57s |
| Directory store import & reopen | Pass | 4,133 entities and 9,148 source facts imported and verified |
| Portable single-file `.rl` store | Pass | Created, closed, and reopened `.rl` file `read_only=True` |
| Concurrent reader alongside directory writer | Pass | `relate.connect(dir_path, read_only=True)` reads committed rows while writer connection remains open |
| Native Full-Text Index (`FULLTEXT INDEX`) | Pass | `CREATE FULLTEXT INDEX ... FOR (n:DPEntity) ON EACH [...]` + `CALL db.index.fulltext.queryNodes(...)` |
| Parameterized Cypher, list properties, transactions | Pass | Verified in unit and mutation suites |
| Per-query timeout parameter | Not exposed | Enforced via hop/row bounds instead |

## MCP SDK compatibility

The MCP server uses `mcp.server.fastmcp.FastMCP`. The `mcp` dependency remains pinned to `>=1.0,<2` (verified against `mcp==1.30.0`), as `mcp` 2.x reorganized the `fastmcp` server module path.
