# Frozen Question Sets Review — `v1` and `v2`

**Updated:** 25 November 2026

---

## 1. `data/questions/relate-docs-v1.jsonl` (Status: `draft_for_semantic_review`)

- **Purpose:** Deterministic route-following and cursor/oracle plumbing regression suite (30 questions, 10 pilot / 20 held-out).
- **Finding:** Every prompt explicitly names intermediate relationship types and destination captions. Useful for cursor-plumbing tests, but does not measure autonomous multi-hop discovery and has zero recurring path overlap (`reuse_count = 0`).
- **Disposition:** Retained as `draft_for_semantic_review` for plumbing verification only; held-out split remains intentionally blocked.

---

## 2. `data/questions/relate-docs-v2.jsonl` (Status: `reviewed`)

- **Scope & Procedure:** Curated and verified 24 natural, goal-oriented 3-hop questions (`10` pilot / `14` held-out) across 6 real Relate documentation corridors (`mcp_serve_flags`, `sandbox_serve_flags`, `neo4j_push_flags`, `sandbox_extension_flags`, `shared_store_serve_flags`, `agent_memory_serve_flags`).
- **Key Improvements over `v1`:**
  1. **Zero Intermediate Route Disclosure (`route_disclosed: false`):** Prompts state the starting `Capability` and the exact technical goal (e.g., the `push` CLI flag controlling relationship updates), without revealing the intermediate `Page` or relationship types.
  2. **Recurring Hub Corridors:** Each 3-hop corridor shares a 2-hop prefix (`Capability -> Page -> Command`) across 4 distinct flag targets, allowing independent walks #1 and #2 to promote a `VALID` desire path and walks #3+ to jump across the verified 2-hop corridor in 1 step (`take_shortcut`).
  3. **Independent Oracle & Offer-Cap Verification:** Every gold path resolves through `oracle_path()` against canonical snapshot `d691ad319bfeb28b18d07ec5a2bc59eaeea2cf88f76ae6671294ac12beba78ae`, and every hop lies within the cursor's 100-edge neighbor offer cap.
- **Disposition:** Marked `reviewed` in `data/questions/relate-docs-v2.manifest.json`, enabling both `pilot` and `held_out` replay and 3-regime lifecycle benchmarking (`waygraph lifecycle-bench`).
