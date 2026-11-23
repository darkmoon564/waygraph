# Waygraph --- 2-Minute Demo Script

**Target:** 1:45--2:00. Record actual application behavior; never
fabricate results.

### 0:00--0:15 --- Problem

"Agents can query graphs with Cypher, but must understand schema and
generate valid queries. Waygraph gives agents a constrained way to
explore real relationships---and lets useful paths become reusable
shortcuts."

Show title, graph, and a real question.

### 0:15--0:40 --- First walk

"The cursor offers only relationships that exist in Relate. The agent
follows this sequence."

Highlight actual edges, relationship IDs, and hop count.

### 0:40--1:00 --- Shortcut forms

"After this path is used \[actual count\] times, Waygraph records a
shortcut with ordered dependency evidence and a fingerprint---not just a
cached answer."

Show actual shortcut record and promotion threshold.

### 1:00--1:25 --- Reuse and invalidation

"On a related request, the agent can reuse the shortcut. We now mutate
an underlying relationship. The next reuse validates dependencies,
detects the change, and rejects the stale shortcut."

Show mutation, stale status, reason, and fresh traversal if available.

### 1:25--1:45 --- Results

"On \[dataset\] and \[question count\], we compare native Cypher MCP and
the cursor on accuracy, tokens, calls, and latency."

Show actual chart/table, sample size, and model IDs.

### 1:45--2:00 --- Close

"Waygraph makes graph exploration reusable without treating old
paths as unquestionable truth. The graph teaches the agent where to
walk, and the evidence tells it when a shortcut is no longer safe."

## Recording checklist

-   [ ] Actual pinned Relate version and committed graph.
-   [ ] Real cursor calls and shortcut metadata.
-   [ ] Real mutation and stale rejection.
-   [ ] Real measured results with denominators.
-   [ ] 1--2 minutes total.
-   [ ] Original/authorized visuals and audio.
-   [ ] Do not edit out failures misleadingly.
