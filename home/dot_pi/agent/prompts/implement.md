---
description: Full implementation workflow - scout gathers context, planner creates plan, worker implements
---

The interactive root must call `worktree_start` with `prompt: "$@"` and wait for a
successful root-approved result before launching this workflow. Do not launch a
worker if activation fails. The root owns that lifecycle call; do not ask a
subagent to call it or supply a worker cwd.

Then use the subagent tool with the chain parameter:

1. Use the "scout" agent to find all code relevant to: $@
2. Use the "planner" agent to create an implementation plan for "$@" using the context from the previous step (use {previous} placeholder)
3. Use the "worker" agent to implement the plan from the previous step (use {previous} placeholder)

Execute this as a chain, passing output between steps via {previous}. Every
chain step receives the topology-validated worktree as its initial cwd
automatically.
