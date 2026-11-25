# Waygraph — Release Checklist

**Updated:** 25 November 2026

## GitHub & Submission Hygiene

- [x] Repository created at `https://github.com/darkmoon564/waygraph`.
- [ ] Push latest commits + `data/relate/showcase.rl` + `viewer/index.html` to `origin`.
- [ ] Verify required GitHub topic `relate` (and recommended `relate-neo4j-hackathon`, `relatedb`).
- [x] License (`MIT`) and exact 5-section Devpost `README.md` template.
- [x] README states Relate storage modes (`.rl` single file + directory) and rationale.
- [x] Persistent Relate store committed (`data/relate/showcase.rl`, `35.32 MB`) and judge-inspectable.
- [x] Zero-install interactive explorer built (`viewer/index.html`, Waygraph Studio).
- [ ] Fresh-clone smoke test (`git clone` -> `pip install -e '.[dev]'` -> `pytest -q` -> `waygraph lifecycle-bench`).
- [x] No secrets or sensitive data committed (`.env` gitignored).
- [x] AI-use, contest-period, and prior-art (`jexp/relate-ideas`) disclosures included.

## Technical Verification

- [x] `relate-db==1.2.0` pinned and verified on Python 3.13 (`cp39-abi3`).
- [x] Dual native domain labels/relationships + `FULLTEXT INDEX dp_entity_ft` + `DPEdge` provenance in sync.
- [x] Importer deterministic; source SHA-256 and canonical snapshot checksum verified.
- [x] 10-tool MCP cursor server verified over real `mcp-stdio` subprocess transport.
- [x] Cursor enforces offer-checks, live re-verification, hop/neighbor caps, and fail-closed `take_shortcut`.
- [x] Shortcut evidence inspectable across `VALID`, `CANDIDATE`, and `STALE` states in `data/relate/showcase.rl`.
- [x] Synthetic 8-case mutation matrix (`0` false-valid, `0` false-stale) and real docs-graph 6-case post-mutation comparison (`0` false-valid vs. `5/5` naive cache) passing.
- [x] Reviewed natural 3-hop benchmark (`data/questions/relate-docs-v2.jsonl`, `24` questions, `status: reviewed`) with independent `oracle_path` verification.
- [ ] Complete live free-tier LLM agent traces (`waygraph` vs. `native-cypher` on `relate-docs-v2.jsonl` pilot with `--resume`).

## Demo & Devpost

- [ ] Record 1:45–2:00 demo video (no login required) walking through `viewer/index.html`, `data/relate/showcase.rl`, and `waygraph lifecycle-bench`.
- [ ] Optionally enable GitHub Pages on `viewer/` for a 1-click live demo URL on Devpost.
- [ ] Submit v1 on Devpost by internal target **Dec 8, 2026** (final deadline: **Dec 12, 2026, 7:30 AM IST**).
- [ ] Keep public repo and `relate` topic active through winner announcement (Dec 18, 2026 IST).
