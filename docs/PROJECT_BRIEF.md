# Waygraph --- Project Brief

## One-line pitch

A graph cursor that learns reusable shortcuts from verified walks---and
invalidates them when the evidence beneath them changes.

## Problem

Agent-written graph queries require schema knowledge and valid query
generation. Repeated questions often retrace the same paths. Cached
answers and paths become unsafe when graph facts change.

## Solution

Waygraph exposes a constrained cursor over Relate. Agents inspect
nodes and follow relationships actually returned by the graph. Repeated
successful paths can be promoted into shortcut relationships that carry
ordered dependency evidence and a deterministic fingerprint. Every reuse
validates the underlying path; stale shortcuts are rejected.

## What connects to what

The source graph connects domain entities through typed relationships. A
shortcut connects a start node to an end node while referencing the
exact ordered source relationships that justify it. The graph stores
both original facts and learned navigation structure.

## Users

Developers building graph-aware agents and teams repeatedly querying
technical documentation, architecture, dependency, or knowledge graphs.

## Why Relate

Relate is the actual embedded graph engine and source of truth. Graph
relationships define cursor actions; the persistent store contains the
source graph and shortcut evidence.

## Differentiation

Acknowledge existing graph-walking cursor and dynamic path-index seeds
in Relate Ideas. The contribution is the integrated learning lifecycle,
evidence-carrying shortcuts, dependency-aware invalidation, mutation
evaluation, and measured comparison against native Cypher and optional
vector retrieval.

## Success criteria

A fresh clone runs the demo and exposes the persistent graph; a
multi-hop walk is replayable; repeated walks create a shortcut with
inspectable evidence; mutation makes it stale and reuse rejects it;
independent evaluation measures correctness and efficiency.
