# Plan Mode — Design & Rationale

Owned pi extension providing a **read-only exploration mode that is ON BY DEFAULT
for interactive root sessions** (`tui`/`rpc`). JSON subagents and print one-shots
are deliberately inert. This document records the requirements, the options
evaluated, and why each decision was made, so the context lives next to the code.

## Requirements

1. **Default-on, interactive-root-only.** Plan mode is active for all new `tui`
   and `rpc` root sessions — fresh process **and** in-session `/new` — with
   **no startup turn, no injected
   `/plan` message, no token waste, no session renamed `/plan`**. (The previous
   approach injected `pi.sendUserMessage("/plan")` at `session_start`; that was
   the root cause of all four problems and is gone.)
2. **First message is the user's task.** The user types their own first message,
   which becomes the session name — not a synthetic `/plan`.
3. **Overrides still work.** `--no-plan` opts out; `--plan` is redundant but
   harmless; `/plan` toggles in-session.
4. **Delegated workers stay writable.** `json` subagents and `print` one-shots
   never enable plan mode, so a worker can read and edit without a parent-side
   `--no-plan` escape hatch.
5. **Resume must not deceive.** No fake `/plan` prompt injected on resume; we
   simply restore persisted state.
6. **Hard read-only.** `edit`/`write` are _physically removed_ from the tool set
   (a guarantee, not advice), and `bash` is gated to read-only commands.
7. **Auto tool-preservation.** Plan mode must keep `worktree_*`/`memory_*`/`mcp`/
   `scratchpad` available **without per-session reconfiguration** (the worktree
   workflow is mandatory). Tools are preserved by _subtracting_ `edit`/`write`,
   never by replacing the set with a hardcoded list.
8. **Plans synced to disk.** The model can persist its plan even though
   `edit`/`write` are gone — via a scoped `plan_write` tool. Memory persistence
   is unaffected (`memory_*` tools are preserved).
9. **Portable & low-maintenance** across machines (chezmoi-managed dotfiles).
10. **Surface the plan in the TUI.** The plan must be shown to me automatically
    when written (no manual `cat`/open), and it must cost **no extra LLM
    context** to do so. I must also be able to **re-view it on demand** later,
    likewise context-free.

## Decisions

### Default-on mechanism — interactive-root mode gate

The `plan` flag is registered with `default: true`. `session_start` enables plan
mode only when `ctx.mode` is `tui` or `rpc`; `json` workers and `print` one-shots
return before parser loading, state restoration, or tool-set mutation. In root
modes, both `reason:"startup"` (fresh) and `reason:"new"` (`/new`) start in
plan mode. CLI argv is applied after registration, so `--no-plan` wins. No
message is sent, no turn is taken, and the session name is whatever the user
types first.

> Surveyed published packages: none met requirements 6–8 simultaneously.
> Tool-strippers (`@juanibiapina/pi-plan`, qmx, openplan, …) replace the tool set
> with a constant list → break tool-preservation. `@narumitw/pi-plan-mode`
> defaults to a curated allowlist needing per-session re-selection. `pi-plan-modus`
> gates its flag on `reason:"startup"` only → misses `/new`. So this is an owned
> extension rather than a dependency.

### Tool model — subtract, don't replace

`planTools = (active tools) − {edit, write} + {read, bash, grep, find, ls,
questionnaire, plan_write}`. The pre-plan set is captured and restored on exit.
This preserves `worktree_*`/`memory_*`/`mcp`/`scratchpad` automatically.

### Plan persistence — scoped `plan_write` tool

`edit`/`write` removal is non-negotiable, so plans can't use them. A dedicated
`plan_write` tool is registered that can write **only** the current session's
plan file. General write stays impossible; the plan file is reachable.

**Path: `~/.pi/agent/plans/<sessionId>.md`** (flat/global, derived from
`sessionManager.getSessionDir()` → `../..` so it honors any pi config-dir
override instead of hardcoding `~/.pi`).

Why home dir and not the project root:

- These files are **session-scoped, auto-named, auto-overwritten** — ephemeral
  working artifacts, not curated docs. You would gitignore `<session-id>.md`
  clutter anyway, so the "git-committable" benefit of project-root storage is
  illusory _for these files_.
- A plan you actually want in git is a **deliberate promotion** to a named
  `DESIGN.md`/`docs/…` — a separate, intentional act, not an auto-sync dump.
- Home dir gives the real want: **all plans in one browsable place**,
  predictable, and it handles being launched outside any project root (where a
  cwd-relative path would scatter files or break).

The path is a one-line constant (`resolvePlanFile`), trivial to change.

### Plan display — `renderResult` renders Markdown, zero context cost

Writing the plan to disk isn't enough; the default `plan_write` result only
printed `Plan saved to <path>`, so the plan was never actually shown (Req 9).
The tool now defines a `renderResult` slot that renders the plan as Markdown
inline via pi-tui's `Markdown` component + `getMarkdownTheme()` (the pattern in
`docs/tui.md`).

**Why this adds no LLM context** — the load-bearing point:

- The plan `content` is a tool-call **argument the model generated**, so it is
  already in context exactly once, unavoidably.
- `renderResult` is **display-only**; it is never sent to the model. It renders
  `context.args.content` (already in context), so there is **no** second copy in
  the transcript and no added tokens.
- `execute()` still returns the short `Plan saved to <path>` as the model-facing
  result — unchanged.

Rendered from `context.args` (not copied into `details`) per pi's documented
best practice, which also avoids duplicating the plan into the session file.
Full render is intentional (not gated behind `expanded`): the whole point is to
see the plan without a manual step; `plan_write` is called deliberately, so
inline full render is not noisy. A partial/empty-args guard shows `Saving plan…`.

**Re-view on demand — `/plan-show` (Ctrl+Alt+V).** In the interactive TUI, opens
a full-screen, focused `ctx.ui.custom()` overlay: Markdown is rendered at the
current terminal width, sliced by scroll offset, and painted over an opaque
`customMessageBg` surface. Controls are ↑/↓ or j/k (line), PgUp/PgDn (page),
Home/End (jump), and Esc/q (close). It adapts to terminal resizing by rerendering
Markdown at the new width and clamping the offset. This is UI-only and therefore
adds **zero** LLM context.

Non-TUI modes retain the previous custom transcript entry (`pi.appendEntry("plan-view")`
with `registerEntryRenderer`), which also never participates in LLM context.
Missing/empty plan → a `notify` warning rather than an empty view. The pager
uses pi's `ctx.ui.custom()` overlay rather than an external `less` process: it
preserves the pi session, works across supported terminals, uses the active
theme, and requires no subprocess or terminal-state cleanup.

### Bash read-only enforcement — shell-quote tokenizer, regex fallback

Bash stays available for inspection but is gated. The check **tokenizes with
`shell-quote` first** (handles quoting/escaping/redirects correctly — e.g.
`echo ">"` is not a redirect, `echo "rm -rf"` is not an `rm`), applying the same
mutation denylist `worktree-guard.ts` uses (one mental model across the repo),
but stricter for read-only exploration (all `git merge` blocked; `push`/`pull`
blocked; extra file-mutating builtins blocked). Regex is the **fallback only**,
when the parser file is absent or a command fails to parse.

#### Dependency delivery — chezmoi external + TTL (no scripts, no node_modules)

`shell-quote`'s `parse.js` is a **single self-contained file** (zero deps,
6.3 KB). It's fetched + auto-refreshed by a chezmoi external
(`../.chezmoiexternal.toml`, `refreshPeriod`, pinned to major `@1`) to
`vendor/shell-quote-parse.cjs`. So: **no `package.json`, no `npm install`, no
`node_modules`, nothing to maintain.** The extension imports it relatively and
degrades to regex if it's missing.

##### Why not `just-bash` (full bash AST)

Initially considered for maximal accuracy, but **rejected**: it is 19 MB unpacked
with 15 transitive runtime deps (incl. WASM: `quickjs-emscripten`, `sql.js`) —
"a simulated bash environment," not a parser — and its own "bundle" is _not_
self-contained (chunks statically import `quickjs-emscripten`/`sql.js`/`diff`/
`minimatch`). pi only runs `npm install` for `npm:`/`git:` packages, never for
loose/local-path extensions, so there is **no script-free way to ship it**.
Publishing it as a package was declined. shell-quote delivers the meaningful win
(tokenization) at ~0.03% of the weight, with a maintenance-free delivery.

## Files

| File                           | Role                                                                                                                                               |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `index.ts`                     | Extension entry: flag, tool preservation, `plan_write`, `/plan` toggle + shortcut, status widget, context injection, bash gating, session restore. |
| `bash-safety.ts`               | Read-only bash analysis: shell-quote token check + regex fallback.                                                                                 |
| `vendor/shell-quote-parse.cjs` | Vendored parser, fetched by chezmoi external (not committed).                                                                                      |
| `../.chezmoiexternal.toml`     | Declares the shell-quote external (TTL refresh).                                                                                                   |

## Verification matrix

- Fresh `tui`/`rpc` start, `/new` → plan mode on; first user message becomes session name.
- `json` subagent and `print` one-shot → plan mode inert; write/edit stay available.
- `/resume` → state restored, no injected `/plan`.
- `--no-plan` → starts off; `/plan` → toggles.
- In plan mode: `edit`/`write` absent; `worktree_*`/`memory_*`/`mcp` present;
  mutating bash blocked, read-only bash allowed; `plan_write` writes
  `~/.pi/agent/plans/<sessionId>.md` **and** renders the plan as Markdown inline
  (model-facing result stays `Plan saved to <path>`).
- `/plan-show` (Ctrl+Alt+V) opens the saved plan in a full-screen, scrollable
  Markdown pager (out of context); missing/empty plan → a warning notification.
