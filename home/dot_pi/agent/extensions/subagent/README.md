# Subagent Extension

Delegate tasks to specialized subagents with isolated context windows.

## Features

- **Isolated context**: Each subagent runs in a separate `pi` process
- **Streaming output**: See tool calls and progress as they happen
- **Parallel streaming**: All parallel tasks stream updates simultaneously
- **Markdown rendering**: Final output rendered with proper formatting (expanded view)
- **Usage tracking**: Shows turns, tokens, cost, and context usage per agent
- **Abort support**: Ctrl+C sends SIGTERM, then SIGKILL after a grace period if needed

## Structure

```
subagent/
├── README.md            # This file
├── index.ts             # The extension (entry point)
└── agents.ts            # Agent discovery logic
```

## Installation

This is a ChezMoi-managed extension. Edit its runtime source under
`home/dot_pi/agent/extensions/subagent/`; ChezMoi renders the extension files to
`~/.pi/agent/extensions/subagent/` with the managed agent definitions under
`~/.pi/agent/agents/`. This README is deployed with the extension. The canonical
and only managed role definitions are `home/dot_pi/agent/agents/*.md.tmpl`, rendered to
`~/.pi/agent/agents/`. Workflow prompt templates are canonical only under
`home/dot_pi/agent/prompts/` (rendered to `~/.pi/agent/prompts/`), not inside this
extension. Legacy extension-local prompt and sample-role targets are listed in
`home/.chezmoiremove`, so a future normal apply removes only obsolete
files rather than exact-syncing any broader `.pi` directory. Do not copy these
files from Pi's upstream examples or manually symlink them.

## Child launch contract

Children retain normal context-file discovery: never pass `--no-context-files`
or `-nc`, so each child reloads global and project `AGENTS.md` from its own
working directory. `--no-session` remains an explicit child CLI flag because
Pi resolves `parsed.noSession` before extensions bind; core provides no
environment-variable hook through which `PI_SUBAGENT` could replace it.

## Worktree ownership

The interactive root owns only `worktree_start`, `worktree_status`, and
`worktree_stop`. A matching successful start result is validated against live
Git topology and recorded with a generation. When `/resume` loads a
replacement session or `/reload` rebuilds the current runtime, hydration
requires the `"resume"`/`"reload"` reason gate, the same live validation, and
a fork-lineage cross-check: when `parentSession` is set, the candidate entry
must not appear in its parent JSONL file. Only `worktree_start` and
`worktree_stop` entries are hydration checkpoints; `worktree_status` output is
purely observational and can never authorize hydration on its own. Pi emits
`reason: "fork"` for both `/fork` and `/clone`; fork/clone sessions with
copied history, sessions with an unreadable or malformed parent, and all
`"startup"`/`"new"` sessions begin unapproved and must call `worktree_start`
themselves. While that approval is active,
every managed child—including `execution: read-only` reviewers—receives the
approved worktree as its **initial cwd** so chain review sees uncommitted worker
changes; this routing intentionally overrides a supplied `cwd`. If the session
has no approval, read-only agents use the supplied cwd or caller cwd; a pending
or invalid approval rejects launch rather than silently reviewing a different
checkout. `execution: worktree-write` agents use direct Git/Bash there; every child
lifecycle tool is blocked. The initial-cwd check is launch routing, not path
containment: an approved worker can later use `cd`, absolute paths, or `git -C`
outside it. Read-only agents' direct `write`/`edit` calls fail closed even when
their cwd is not a Git repository, while Bash rejects only the shared
classifier's known commands and syntax. That Bash policy is deliberately best-effort and
cooperative, not a complete shell parser or sandbox. Missing, unknown, or
invalid writable metadata fails closed before a worker receives direct tools. Outside
plan mode, a markerless `worktree-write` worker in a confirmed non-Git cwd may
mutate; Git cwd and ambiguous Git-probe results fail closed. Launch preflight rejects
a non-Git parent that overrides a writable child cwd into a Git repository. Launch
preflight validates every single, chain, or parallel request before any
child is spawned. A generation-bound lease is exclusive across all subagent
tool calls, so only one writable child may run in an approved worktree at once;
other writable launches fail until its process actually exits and releases the
lease. Topology validation retains a held lease but rejects new work fail
closed. Start and stop reserve the lifecycle slot even when no worktree is
approved. A blocked, aborted, or result-less lifecycle call is canceled at
`tool_execution_end`; an unobserved stop revokes approval rather than risking a
root mutation after package routing changed. Session shutdown revokes all
approval for its session.

`PI_SUBAGENT=1` is a cooperative child-mode marker, not an authentication or
sandbox boundary. `PI_ROOT_PHASE` is intentionally preserved in child environments so
nested launchers inherit the root session's plan-phase read-only policy; only
`PI_ROOT_PHASE=execute` retains declared execution, so `plan`, missing, legacy
`normal`, or unrecognized values fail closed to read-only. The child's plan-mode extension stays inert. Root-only
local extensions use
`PI_SUBAGENT=1` only to disable their root lifecycle behavior; the local worktree
guard remains active in children. A
process launched outside this extension can forge its environment, so execution
classes and worktree metadata must not be relied on to contain an adversarial
child. The policy instead protects the managed workflow: pre-approval roots and
declared read-only children block direct writes/edits and recognized Bash
mutations, while a root-approved worker intentionally has unrestricted direct
Git/Bash. That worker can deliberately use absolute paths or `git -C` outside
its assigned worktree; this cooperative policy is not path containment. The managed fork of
[`rezamonangg/pi-worktree`](https://github.com/frank-machine/pi-worktree)
contains an early `PI_SUBAGENT` return before registration or side effects. The
managed settings pin that fork at an immutable commit; do not edit its installed
clone. Update the pin only after a reviewed fork commit is published.

## Linked-worktree package boundary

The pinned fork's early child return prevents managed subagents from
initializing `pi-worktree` state, so a delegated worker in a linked worktree does
not try to create its `.git` file as a directory. That resolves the observed
subagent `EEXIST` startup noise.

A direct interactive Pi root launched inside a linked worktree remains an
unfixed `pi-worktree` package defect: its state writer uses
`<repoRoot>/.git/pi-worktree-state.json`, but linked worktrees expose `.git` as
a file. The fork must resolve the Git metadata path (for example with
`git rev-parse --git-path pi-worktree-state.json`) before writing state. Do not
work around that package bug in the subagent launcher or mutate the installed
clone; update the immutable package pin only after the fork publishes the fix.

## Child extension policy

| Extension                                               | Child behavior                                                                                                                                                                                      |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `root-thread-guard`                                     | Inert: JSON children use their declared tools without root-thread restrictions.                                                                                                                     |
| `plan-mode`                                             | Inert locally; `PI_ROOT_PHASE` is inherited so the launcher downgrades children to read-only while the root is in plan phase.                                                                       |
| `memory-git-sync`                                       | Inert: child sessions never pull, commit, or push memory.                                                                                                                                           |
| `worktree-guard`                                        | Active: lifecycle is root-owned; read-only/unmarked direct writes/edits fail closed, and known Bash mutations use a best-effort classifier. A validated worker initial cwd is not path containment. |
| `@rezamonangg/pi-worktree` fork                         | Inert before registration (`PI_SUBAGENT=1`).                                                                                                                                                        |
| Third-party `pi-mcp-adapter`, `pi-memory`, `pi-vimmode` | No lifecycle routing or Git side effects are configured; their normal tool behavior remains available only if declared by the agent.                                                                |

## Security Model

This tool executes a separate `pi` subprocess with a delegated system prompt and tool/model configuration.

**Project-local agents** (`.pi/agents/*.md`) are repo-controlled prompts that can instruct the model to read files, run bash commands, etc.

**Default behavior:** Only loads **user-level agents** from `~/.pi/agent/agents`.

To enable project-local agents, pass `agentScope: "both"` (or `"project"`). Only do this for repositories you trust.

When running interactively, the tool prompts for confirmation before running project-local agents. Set `confirmProjectAgents: false` to disable.

## Usage

### Single agent

```
Use scout to find all authentication code
```

### Parallel execution

```
Run 2 scouts in parallel: one to find models, one to find providers
```

### Chained workflow

```
Use a chain: first have scout find the read tool, then have planner suggest improvements
```

### Workflow prompts

```
/implement add Redis caching to the session store
/scout-and-plan refactor auth to support OAuth
/implement-and-review add input validation to API endpoints
```

## Tool Modes

| Mode     | Parameter          | Description                                            |
| -------- | ------------------ | ------------------------------------------------------ |
| Single   | `{ agent, task }`  | One agent, one task                                    |
| Parallel | `{ tasks: [...] }` | Multiple agents run concurrently (max 8, 4 concurrent) |
| Chain    | `{ chain: [...] }` | Sequential with `{previous}` placeholder               |

## Output Display

**Collapsed view** (default):

- Status icon (✓/✗/⏳) and agent name
- Last 5-10 items (tool calls and text)
- Usage stats: `3 turns ↑input ↓output RcacheRead WcacheWrite $cost ctx:contextTokens model`

**Expanded view** (Ctrl+O):

- Full task text
- All tool calls with formatted arguments
- Final output rendered as Markdown
- Per-task usage (for chain/parallel)

**Parallel mode streaming**:

- Shows all tasks with live status (⏳ running, ✓ done, ✗ failed)
- Updates as each task makes progress
- Shows "2/3 done, 1 running" status
- Returns each completed task's final output to the parent model, capped at 50 KB per task
- Returns failure diagnostics from stderr/error messages when a child exits before producing output

**Tool call formatting** (mimics built-in tools):

- `$ command` for bash
- `read ~/path:1-10` for read
- `grep /pattern/ in ~/path` for grep
- etc.

## Agent Definitions

Agents are markdown files with YAML frontmatter. The managed roles currently have:

| Role       | Tools                                                                                                                      | Execution        |
| ---------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| `scout`    | `read`, `grep`, `find`, `ls`, `bash`, `mcp`                                                                                | `read-only`      |
| `planner`  | `read`, `grep`, `find`, `ls`, `mcp`                                                                                        | `read-only`      |
| `reviewer` | `read`, `grep`, `find`, `ls`, `bash`, `mcp`                                                                                | `read-only`      |
| `worker`   | `read`, `grep`, `find`, `ls`, `bash`, `write`, `edit`, `mcp`, `memory_read`, `memory_write`, `memory_search`, `scratchpad` | `worktree-write` |

```markdown
---
name: my-agent
description: What this agent does
tools: read, grep, find, ls
execution: read-only
model: claude-haiku-4-5
---

System prompt for the agent goes here.
```

**Locations:**

- `~/.pi/agent/agents/*.md` - User-level canonical managed role definitions (always loaded)
- `.pi/agents/*.md` - Project-level (only with `agentScope: "project"` or `"both"`)

Project agents override user agents with the same name when `agentScope: "both"`.

## Workflow Prompts

| Prompt                          | Flow                                               |
| ------------------------------- | -------------------------------------------------- |
| `/implement <query>`            | root `worktree_start` → scout → planner → worker   |
| `/scout-and-plan <query>`       | scout → planner                                    |
| `/implement-and-review <query>` | root `worktree_start` → worker → reviewer → worker |

## Error Handling

- **Exit code != 0 or signal exit**: Tool returns failure with stderr/output
- **stopReason "error"**: LLM error propagated with error message
- **stopReason "aborted"**: Ctrl+C requests SIGTERM, escalates to SIGKILL only
  after the child has not exited during the grace period, and reports failure
- **Chain mode**: Stops at first failing step, reports which step failed

## Limitations

- Output truncated to last 10 items in collapsed view (expand to see all)
- Parallel model-visible output is capped at 50 KB per task; full results remain in tool details
- Agents discovered fresh on each invocation (allows editing mid-session)
- Parallel mode limited to 8 tasks, 4 concurrent
