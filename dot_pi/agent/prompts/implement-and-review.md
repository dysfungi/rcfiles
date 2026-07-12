---
description: Worker implements, reviewer reviews, worker applies feedback
---

The interactive root must call `worktree_start` with `prompt: "$@"` and wait for a
successful root-approved result before launching this workflow. Do not launch a
worker if activation fails. The root owns that lifecycle call; do not ask a
subagent to call it or supply a worker cwd.

Then use the subagent tool with the chain parameter:

1. Use the "worker" agent to implement: $@
2. Use the "reviewer" agent to review the implementation from the previous step (use {previous} placeholder)
3. Use the "worker" agent to apply the feedback from the review (use {previous} placeholder)

Execute this as a chain, passing output between steps via {previous}. Every
chain step receives the topology-validated worktree as its initial cwd
automatically, so the reviewer sees the worker's uncommitted diff.
