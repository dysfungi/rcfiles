/**
 * Worktree Enforcement Extension
 *
 * Blocks file mutations until the agent activates a worktree via
 * @rezamonangg/pi-worktree's `worktree_start` tool. Ensures every session
 * that modifies files does so in an isolated git worktree — enforced at
 * the tool_call level, not by instructions.
 *
 * Detection (on session_start, cached for session lifetime):
 *   1. `git rev-parse --show-toplevel` — fails → not a git repo → inert.
 *   2. `detectWorktreeName(ctx.cwd)` — cwd contains `/.worktree/` or
 *      `/.worktrees/` → already inside a worktree → inert.
 *   3. Otherwise → main checkout → block mutations until worktree_start
 *      succeeds.
 *
 * Guard scope: git repositories only. Non-git workspaces (Perforce, plain
 * directories, etc.) are unguarded — no worktree isolation concept applies,
 * and P4's changelist model handles concurrent access natively.
 *
 * Integration with @rezamonangg/pi-worktree:
 *   - That package registers `worktree_start` as an agent-callable tool
 *   - That package intercepts tool_call events to rewrite paths into the
 *     worktree and overrides bash cwd via spawnHook
 *   - This extension just enforces that worktree_start is called first
 *   - On tool_result for worktree_start (success) → guard disables itself
 *
 * Blocked on main (git repos only):
 *   - write, edit tools (except .pi/ session infra paths)
 *   - bash: git mutations, sed -i, rm/mv/cp, shell redirects, tee, todo.sh
 *
 * Allowed on main:
 *   - All read-only operations (read, bash read commands, grep, find, ls)
 *   - worktree_start, worktree_status, worktree_resolve_file (the workflow)
 *   - git merge --ff-only (worktree merge-back per AGENTS.md)
 *   - git branch -d (cleanup after merge-back)
 *   - git pull/fetch/push (remote sync, no file-edit race risk)
 *   - git worktree add/remove/list
 *
 * Exemption: touch .pi/worktree-exempt in repo root (human-only, agents
 * must never create this).
 *
 * Best-effort guardrail, not a sandbox — obfuscated mutations bypass it.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

// --- Session-level state ---

let guardActive = false;
let repoRoot = "";

/**
 * Detect if cwd is inside a worktree. Checks both .worktree/ (used by
 * @rezamonangg/pi-worktree) and .worktrees/ (used by pi-worktree).
 */
function detectWorktreeName(cwd: string): string | null {
  const m = cwd.match(/\/\.worktrees?\/([^/]+)/);
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
    const tokens = seg.trim().split(/\s+/).slice(1);
    const subcmd = gitSubcmd(tokens);
    if (!subcmd) return undefined;

    if (subcmd === "merge" && seg.includes("--ff-only")) return undefined;
    if (subcmd === "branch") return undefined;

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

Call worktree_start first to create an isolated worktree, then retry.

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

  // Disable guard when worktree_start succeeds
  pi.on("tool_result", async (event, ctx) => {
    if (!guardActive) return;
    if (event.toolName === "worktree_start" && !event.error) {
      guardActive = false;
      ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("success", "🌿 worktree active"));
    }
  });

  pi.on("tool_call", async (event) => {
    if (!guardActive) return;

    // Always allow worktree management tools
    if (event.toolName.startsWith("worktree_")) return;

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
