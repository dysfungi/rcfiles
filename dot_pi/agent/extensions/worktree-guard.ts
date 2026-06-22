/**
 * Worktree Enforcement Extension
 *
 * Blocks file mutations when pi is launched from a git repo's main checkout,
 * enforcing isolated worktree usage for all agent sessions. Complements the
 * `pi-worktree` package (lifecycle management via `/worktree create`).
 *
 * Detection (on session_start, cached for session lifetime):
 *   1. `git rev-parse --show-toplevel` — if it fails, not a git repo → inert.
 *   2. `detectWorktreeName(ctx.cwd)` — checks if cwd contains `/.worktrees/`.
 *      If present → inside a worktree → allow everything.
 *      If absent → main checkout → block mutations.
 *
 * Guard scope: git repositories only. Non-git workspaces (Perforce, plain
 * directories, etc.) are unguarded — no worktree isolation concept applies,
 * and P4's changelist model handles concurrent access natively.
 *
 * Blocked on main (git repos only):
 *   - write, edit tools (except .pi/ session infra paths)
 *   - bash: git mutations, sed -i, rm/mv/cp, shell redirects, tee, todo.sh
 *
 * Allowed on main:
 *   - All read-only operations
 *   - git merge --ff-only (worktree merge-back per AGENTS.md)
 *   - git branch -d (cleanup after merge-back)
 *   - git pull/fetch/push (remote sync, no file-edit race risk)
 *   - git worktree add/remove/list (the workflow itself)
 *
 * Exemption: touch .pi/worktree-exempt in repo root (human-only, agents
 * must never create this).
 *
 * Best-effort guardrail, not a sandbox — obfuscated mutations bypass it.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

// --- Session-level state (set once on session_start, never changes) ---

let guardActive = false;
let repoRoot = "";

function detectWorktreeName(cwd: string): string | null {
  const m = cwd.match(/\/\.worktrees\/([^/]+)/);
  return m ? m[1] : null;
}

// --- Bash command analysis ---
// Aligned with Claude Code's bash_worktree_guard.py MUTATING_GIT_SUBCMDS.

const MUTATING_GIT_SUBCMDS = new Set([
  "add", "am", "apply", "checkout", "cherry-pick", "clean", "commit",
  "fast-import", "merge", "mv", "rebase", "reset", "restore", "revert",
  "rm", "update-index", "update-ref",
]);

const GIT_FLAGS_WITH_VALUE = new Set(["-C", "-c", "--work-tree", "--git-dir", "--namespace"]);

const READONLY_TODO_SUBCMDS = new Set([
  "help", "shorthelp", "list", "listall", "listaddons", "listcon",
  "listfile", "listpri", "listproj", "lf", "ls", "lsa", "lsc", "lsp", "lsprj",
]);

function gitSubcmd(tokens: string[]): string | undefined {
  let i = 0;
  while (i < tokens.length) {
    const tok = tokens[i];
    if (GIT_FLAGS_WITH_VALUE.has(tok)) { i += 2; continue; }
    if (tok.startsWith("-")) { i += 1; continue; }
    return tok;
  }
  return undefined;
}

function checkSegment(segment: string): string | undefined {
  const seg = segment.trim();
  if (!seg) return undefined;

  // Output redirects (>, >>) excluding stderr (2>, &>)
  if (/(?<![2&])>{1,2}(?!&)/.test(seg)) return "output redirect (>, >>)";

  // tee — only at start of segment or after pipe
  if (/(?:^|\|)\s*tee(?:\s|$)/.test(seg)) return "tee";

  // sed -i
  if (/^\s*sed\s/.test(seg) && /\s-[a-zA-Z]*i/.test(seg)) return "sed -i (in-place edit)";

  // File operations
  const fileOp = seg.match(/^\s*(rm|mv|cp)\s/);
  if (fileOp) return `${fileOp[1]} (file operation)`;

  // Git mutations
  if (/^\s*git(?:\s|$)/.test(seg)) {
    const tokens = seg.trim().split(/\s+/).slice(1); // skip "git"
    const subcmd = gitSubcmd(tokens);
    if (!subcmd) return undefined;

    // Allow git merge --ff-only (worktree merge-back)
    if (subcmd === "merge" && seg.includes("--ff-only")) return undefined;

    // Allow git branch -d/-D (cleanup after merge-back)
    if (subcmd === "branch") return undefined;

    // Allow stash list/show
    if (subcmd === "stash") {
      if (/git\s+stash\s+(list|show)(?:\s|$)/.test(seg)) return undefined;
      return "git stash (mutating)";
    }

    if (MUTATING_GIT_SUBCMDS.has(subcmd)) return `git ${subcmd} (mutating)`;
  }

  // todo.sh mutations
  const todoMatch = seg.match(/^\s*(?:todo\.sh|todo)\s+(\S+)/);
  if (todoMatch && !READONLY_TODO_SUBCMDS.has(todoMatch[1])) {
    return `todo.sh ${todoMatch[1]} (mutating)`;
  }

  return undefined;
}

function checkBashCommand(command: string): string | undefined {
  const lines = command.replace(/&&/g, "\n").replace(/\|\|/g, "\n").replace(/;/g, "\n");
  for (const line of lines.split("\n")) {
    if (!line.trim()) continue;
    for (const part of line.split("|")) {
      const reason = checkSegment(part);
      if (reason) return reason;
    }
  }
  return undefined;
}

function isSessionInfraPath(filePath: string): boolean {
  const resolved = resolve(repoRoot, filePath);
  return resolved.startsWith(join(repoRoot, ".pi") + "/") ||
         resolved.startsWith(join(repoRoot, ".claude") + "/");
}

// --- Extension ---

const BLOCK_MSG = `\
Blocked: file mutations are not allowed on the main checkout.

Create an isolated worktree first:
  /worktree create <task-slug>    (or: pi --worktree <task-slug>)

See AGENTS.md "Multi-instance worktrees" for the full workflow.
Human bypass: touch .pi/worktree-exempt`;

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    const { code, stdout } = await pi.exec("git", ["rev-parse", "--show-toplevel"], { timeout: 3_000 });
    const isGitRepo = code === 0 && stdout.trim().length > 0;

    if (!isGitRepo) {
      guardActive = false;
      return;
    }

    repoRoot = stdout.trim();
    const worktreeName = detectWorktreeName(ctx.cwd);
    const exempt = existsSync(join(repoRoot, ".pi", "worktree-exempt"));

    guardActive = !worktreeName && !exempt;

    if (guardActive) {
      ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("warning", "🔒 main (read-only)"));
    } else if (worktreeName) {
      ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("success", `🌿 ${worktreeName}`));
    }
  });

  pi.on("tool_call", async (event) => {
    if (!guardActive) return;

    if (event.toolName === "write" || event.toolName === "edit") {
      const path = event.input?.path as string | undefined;
      if (path && isSessionInfraPath(path)) return;
      return { block: true, reason: `${BLOCK_MSG}\n\nAttempted: ${event.toolName} ${path ?? "(unknown)"}` };
    }

    if (event.toolName === "bash") {
      const command = event.input?.command as string | undefined;
      if (!command) return;
      const reason = checkBashCommand(command);
      if (reason) {
        return { block: true, reason: `${BLOCK_MSG}\n\nBlocked: ${reason}\nCommand: ${command}` };
      }
    }
  });
}
