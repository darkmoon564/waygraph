# Relate 1.0.1 --- API Compatibility Record

**Status:** Runtime-verified on Windows/Python 3.13 for in-memory transactions, directory-store import/reopen, sequential read-only reopen, and the project's graph queries. Cross-version Python checks and concurrent reader/writer behavior remain open.
**Pinned dependency:** `relate-db==1.0.1`
**Tested Python:** 3.13. The project's 3.11--3.13 range still needs a matrix check before final release.

## Documented and runtime-verified usage

The official Python reference documents `relate.connect(...)`, `conn.execute(...)`, result retrieval with `fetchall()`, and explicit `conn.close()`.

Installed 1.0.1 signatures:

```text
relate.connect(database=':memory:', namespace='neo4j', read_only=False)
Connection.execute(query: str, params: Optional[Dict[str, Any]] = None)
```

`Connection` exposes `autocommit` (default `True`), `commit()`, `rollback()`, `cursor()`, `execute()`, and `close()`. With `autocommit=False`, the first statement opens a transaction; commit and rollback end it. Closing with an open transaction rolls it back. No timeout option is present on `Connection.execute`; the cursor enforces hop and result caps but does not claim a query deadline.

The project smoke test round-tripped a list property, performed an explicit rollback, and closed the connection. The importer wrote 4,133 entities and 9,148 relationships to a directory store. After closing its writer, a read-only connection reopened the store and returned matching counts. This verifies sequential read-only reopen, not concurrent reader/writer safety.

## Runtime behavior still to verify

- Concurrent directory-store readers and writer behavior.
- Map property support (list property values were verified).
- Exception classes and retryable conflict classification.
- Relationship ID stability across reopen.
- Import/export/backup behavior.
- Python 3.11 and 3.12 compatibility.

## Evidence table

| Test | Status | Evidence |
|---|---|---|
| Install 1.0.1 on Python 3.13 | Pass | Project isolated `.venv` |
| Create/open directory store | Pass | `import-docs`; reopened read-only |
| Create nodes and relationships | Pass | 4,133 entities and 9,148 source edges |
| Parameterized reads and list property | Pass | In-memory smoke test |
| Transaction commit/rollback | Pass | `autocommit=False`, commit, rollback |
| Close/reopen persistence | Pass | Reopened directory; counts matched |
| Sequential read-only reopen | Pass | Writer closed before reader opened |
| Query timeout | Unsupported in inspected API | No timeout parameter on `Connection.execute` |
| Write conflict classification | Pending | No supported transient classification established |
| Relationship ID stability | Pending | Application IDs are importer-generated; native IDs not assessed |

## Compatibility policy

Do not infer unsupported APIs from another Relate release, Rust/JS API, or Neo4j driver. Update this record from installed 1.0.1 behavior and exact official documentation.

The MCP server uses `mcp.server.fastmcp.FastMCP`. The `mcp` dependency is therefore pinned to `>=1.0,<2`; MCP 2.3.0 removed that import, while project MCP 1.x tool tests pass with 1.30.0.

An MCP 1.30.0 stdio client smoke test initialized the server, listed all seven tools, and called `start_walk` against the imported docs store. The result was a valid response envelope with a trace ID. A fresh-clone launch check remains pending.
