# Frozen question set review — 18 November 2026

## Scope and procedure

Reviewed all 30 records in `data/questions/relate-docs-v1.jsonl` for route uniqueness, graph reachability under the cursor offer cap, coherent start/end identifiers, ambiguity, naturalness, and whether the prompt tests the intended agent task rather than only route execution.

## Findings

- All 30 gold routes resolve to the frozen graph snapshot, and each hop is uniquely identified by relationship type and destination caption.
- All gold edges are present within the cursor's 100-edge neighbor offer cap.
- Every prompt has an explicit origin and a deterministic endpoint ID target.
- The wording supplies the complete gold route, including every relationship type and intermediate destination. Prompts repeat the same template and often use graph-internal labels such as `Capability` and `CookbookRecipe`.
- Therefore the set is useful for cursor/oracle plumbing and exact route replay, but it does not test whether an agent can discover an appropriate route from a natural user question. It risks overstating results if used as a user-facing agent benchmark.

## Disposition

This is an automated engineering review, not the required human semantic approval. The manifest remains `draft_for_semantic_review`, and the loader continues to block heldout replay. Before promoting the set, a human reviewer should rewrite or explicitly accept the prompts, verify that their wording matches the intended task, check answer equivalence rules, and approve the manifest. For a meaningful native-MCP versus cursor agent comparison, author questions that state the information need without disclosing the complete route.
