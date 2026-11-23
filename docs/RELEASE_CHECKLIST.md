# Waygraph --- Release Checklist

## GitHub

-   [x] Repository published at `https://github.com/darkmoon564/waygraph`.
-   [ ] Required topic `relate`; recommended `relate-neo4j-hackathon`.
-   [ ] License and official README template.
-   [ ] README states directory store mode and rationale.
-   [ ] Persistent store committed or judge-inspectable.
-   [ ] One-command demo works from fresh clone.
-   [ ] No secrets or sensitive data.
-   [ ] AI-use and reused-code disclosure.
-   [ ] Prior idea seeds attributed.

## Technical

-   [ ] `relate-db==1.0.1` pinned.
-   [ ] Clean-environment smoke test passes.
-   [ ] Importer deterministic; source checksum recorded.
-   [ ] MCP cursor starts from documented command.
-   [ ] Cursor cannot follow unoffered edges.
-   [ ] Hop and result limits enforced.
-   [ ] Shortcut evidence inspectable.
-   [ ] Mutation suite has zero false-valid acceptances.
-   [ ] Baselines use equivalent graph snapshots.
-   [ ] Gold answers independent.
-   [ ] Raw JSONL benchmark traces saved.
-   [ ] Accuracy, tokens, calls, hops, latency reported.
-   [ ] Caveats and failures documented.

## Demo and Devpost

-   [ ] 1--2 minute video recorded by submitter.
-   [ ] Demonstrates walk → shortcut → reuse → invalidation.
-   [ ] Results real and reproducible.
-   [ ] Description explains use case and graph relationships.
-   [ ] GitHub URL public and correct.
-   [ ] Submit by internal target Dec 8.
-   [ ] Verify final deadline: Dec 12, 2026, 7:30 AM IST.
-   [ ] Keep public repo and `relate` topic through Dec 17.
