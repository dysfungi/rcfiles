/**
 * Worktree Guard Extension
 *
 * Blocks file mutations when on the main git worktree, enforcing isolated
 * worktree usage for all agent sessions. Mirrors the Claude Code PreToolUse
 * worktree guard (worktree_check.py + bash_worktree_guard.py).
 *
 * Detection: compares `git rev-parse --git-dir` vs `--git-common-dir`.
 * When they resolve to the same real path → main worktree → mutations blocked.
 * When they differ → linked worktree → all tools allowed.
 *
 * Blocked tools:
 *   - write, edit: always blocked on main worktree
 *   - bash: blocked when the command matches known mutation patterns
 *     (git mutations, sed -i, rm/mv/cp, shell redirects, tee, todo.sh writes)
 *
 * Allowed on main worktree:
 *   - All read-only operations (read, bash read commands, grep, find, ls)
 *   - git merge --ff-only (worktree merge-back pattern per AGENTS.md)
 *   - git branch -d (cleanup after merge-back)
 *   - git stash list/show (read-only stash inspection)
 *
 * Exemptions:
 *   - Not in a git repo (no worktree concept applies)
 *   - .pi/worktree-exempt exists in repo root (human-only bypass)
 *   - Paths inside .pi/ or .claude/ (gitignored session infra)
 *
 * Best-effort, not a sandbox — obfuscated mutations (eval, python -c, etc.)
 * bypass it. The goal is preventing accidental file-edit races between
 * concurrent sessions, not sandboxing untrusted code.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";
import { execSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { join, resolve } from "node:path";

// --- Worktree detection (cached per cwd) ---

interface WorktreeState {
  isMain: boolean;
  isGitRepo: boolean;
  repoRoot: string;
  exempt: boolean;
}

let cachedCwd: string | undefined;
let cachedState: WorktreeState | undefined;

function getWorktreeState(cwd: string): WorktreeState {
  if (cachedCwd === cwd && cachedState) return cachedState;

  const state: WorktreeState = { isMain: false, isGitRepo: false, repoRoot: "", exempt: false };

  try {
    const gitDir = execSync("git rev-parse --git-dir", { cwd, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] }).trim();
    const gitCommon = execSync("git rev-parse --git-common-dir", { cwd, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] }).trim();
    const repoRoot = execSync("git rev-parse --show-toplevel", { cwd, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] }).trim();

    state.isGitRepo = true;
    state.repoRoot = repoRoot;

    // Compare resolved paths — same = main worktree
    const resolvedGitDir = realpathSync(resolve(cwd, gitDir));
    const resolvedCommon = realpathSync(resolve(cwd, gitCommon));
    state.isMain = resolvedGitDir === resolvedCommon;

    // Check exemption file
    state.exempt = existsSync(join(repoRoot, ".pi", "worktree-exempt"));
  } catch {
    // Not a git repo or git not available
    state.isGitRepo = false;
  }

  cachedCwd = cwd;
  cachedState = state;
  return state;
}

// --- Bash command analysis ---

// Git subcommands that mutate state
const MUTATING_GIT_SUBCMDS = new Set([
  "add", "checkout", "restore", "reset", "rm", "mv", "clean",       // working-tree
  "commit", "merge", "rebase", "cherry-pick", "am", "apply",         // history
  "stash", "push", "pull", "fetch", "clone", "init", "tag",          // stash + remote + init
]);

// Git subcommands that are always read-only
const READONLY_GIT_SUBCMDS = new Set([
  "status", "log", "diff", "show", "branch", "remote", "config",
  "ls-files", "ls-tree", "ls-remote", "describe", "rev-parse",
  "name-rev", "shortlog", "blame", "grep", "reflog", "bisect",
  "worktree",  // worktree add/remove/list — needed for the workflow itself
]);

// Git global flags that take a value argument (must be skipped to find subcommand)
const GIT_FLAGS_WITH_VALUE = new Set(["-C", "-c", "--work-tree", "--git-dir", "--namespace"]);

// todo.sh read-only subcommands
const READONLY_TODO_SUBCMDS = new Set([
  "help", "shorthelp", "list", "listall", "listaddons", "listcon",
  "listfile", "listpri", "listproj", "lf", "ls", "lsa", "lsc", "lsp", "lsprj",
]);

/**
 * Extract the git subcommand from a command string, skipping global flags.
 */
function gitSubcmd(tokens: string[]): string | undefined {
  let i = 0;
  while (i < tokens.length) {
    const tok = tokens[i];
    if (GIT_FLAGS_WITH_VALUE.has(tok)) {
      i += 2; // skip flag + value
    } else if (tok.startsWith("-")) {
      i += 1; // skip other flags
    } else {
      return tok;
    }
  }
  return undefined;
}

/**
 * Check if a single command segment contains a blocked mutation.
 * Returns a reason string if blocked, undefined if allowed.
 */
function checkSegment(segment: string): string | undefined {
  const trimmed = segment.trim();
  if (!trimmed) return undefined;

  // Output redirects: > and >> but not 2>, &>, >&
  if (/(?<![2&\d])>(?!&)/.test(trimmed)) {
    return "shell output redirect (>, >>)";
  }

  // tee
  if (/\btee\b/.test(trimmed)) return "tee";

  // sed -i (in-place edit, any flag order)
  if (/\bsed\b/.test(trimmed) && /\s-[^\s]*i/.test(trimmed)) return "sed -i (in-place edit)";

  // File operations
  if (/\brm\b/.test(trimmed)) return "rm";
  if (/\bmv\b/.test(trimmed)) return "mv";
  if (/\bcp\b/.test(trimmed)) return "cp";
  if (/\bmkdir\b/.test(trimmed)) return "mkdir";
  if (/\btouch\b/.test(trimmed)) return "touch";
  if (/\bchmod\b/.test(trimmed)) return "chmod";

  // Git commands
  const gitMatch = trimmed.match(/\bgit\s+(.*)/);
  if (gitMatch) {
    const tokens = gitMatch[1].split(/\s+/);
    const subcmd = gitSubcmd(tokens);
    if (!subcmd) return undefined;

    // Allow git merge --ff-only (worktree merge-back pattern)
    if (subcmd === "merge" && /--ff-only/.test(trimmed)) return undefined;

    // Allow git branch -d/-D (cleanup after merge-back)
    if (subcmd === "branch" && /\s-[dD]\b/.test(trimmed)) return undefined;

    // Allow stash list/show
    if (subcmd === "stash") {
      const stashSub = tokens[tokens.indexOf("stash") + 1];
      if (stashSub === "list" || stashSub === "show") return undefined;
      return "git stash (use a worktree)";
    }

    // Allow all read-only subcommands
    if (READONLY_GIT_SUBCMDS.has(subcmd)) return undefined;

    // Block known mutating subcommands
    if (MUTATING_GIT_SUBCMDS.has(subcmd)) return `git ${subcmd}`;
  }

  // todo.sh / todo mutations
  const todoMatch = trimmed.match(/\btodo\.sh\s+(\S+)/);
  if (todoMatch) {
    const subcmd = todoMatch[1].toLowerCase();
    if (!READONLY_TODO_SUBCMDS.has(subcmd)) return `todo.sh ${subcmd}`;
  }

  return undefined;
}

/**
 * Check if a bash command contains blocked mutations.
 * Splits on &&, ||, ; then on | to check each segment.
 */
function checkBashCommand(command: string): string | undefined {
  // Split compound commands
  const compounds = command.split(/\s*(?:&&|\|\||;)\s*/);
  for (const compound of compounds) {
    // Split pipeline segments
    const segments = compound.split(/\s*\|\s*/);
    for (const segment of segments) {
      const reason = checkSegment(segment);
      if (reason) return reason;
    }
  }
  return undefined;
}

/**
 * Check if a file path is inside a session-infra directory (allowed on main).
 */
function isSessionInfraPath(filePath: string, repoRoot: string): boolean {
  const resolved = resolve(repoRoot, filePath);
  const piDir = join(repoRoot, ".pi");
  const claudeDir = join(repoRoot, ".claude");
  return resolved.startsWith(piDir) || resolved.startsWith(claudeDir);
}

// --- Extension ---

const BLOCK_MSG = `\
Blocked: file mutations are not allowed on the main worktree.

Create an isolated worktree first:
  git worktree add .worktrees/<task-slug> -b task/<task-slug>
Then cd into it before making changes.

See AGENTS.md "Multi-instance worktrees" for the full workflow.
To bypass (human-only): touch .pi/worktree-exempt`;

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    const state = getWorktreeState(ctx.cwd);

    // Not a git repo or already in a linked worktree — allow everything
    if (!state.isGitRepo || !state.isMain || state.exempt) return;

    // Block write/edit on main worktree
    if (isToolCallEventType("write", event)) {
      if (isSessionInfraPath(event.input.path, state.repoRoot)) return;
      return { block: true, reason: `${BLOCK_MSG}\n\nAttempted: write ${event.input.path}` };
    }

    if (isToolCallEventType("edit", event)) {
      if (isSessionInfraPath(event.input.path, state.repoRoot)) return;
      return { block: true, reason: `${BLOCK_MSG}\n\nAttempted: edit ${event.input.path}` };
    }

    // Block mutating bash commands on main worktree
    if (isToolCallEventType("bash", event)) {
      const reason = checkBashCommand(event.input.command);
      if (reason) {
        return { block: true, reason: `${BLOCK_MSG}\n\nBlocked: ${reason}\nCommand: ${event.input.command}` };
      }
    }
  });

  // Invalidate cache on cwd change
  pi.on("session_start", () => {
    cachedCwd = undefined;
    cachedState = undefined;
  });

  // Show guard status in footer
  pi.on("session_start", async (_event, ctx) => {
    updateStatus(ctx);
  });

  // Update status when model changes (proxy for general activity)
  pi.on("turn_start", async (_event, ctx) => {
    // Re-check in case cwd changed (e.g., after cd in bash)
    cachedCwd = undefined;
    cachedState = undefined;
    updateStatus(ctx);
  });

  function updateStatus(ctx: ExtensionContext) {
    const state = getWorktreeState(ctx.cwd);
    if (!state.isGitRepo) {
      ctx.ui.setStatus("worktree-guard", undefined);
    } else if (state.isMain && !state.exempt) {
      ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("warning", "🔒 main (read-only)"));
    } else if (state.exempt) {
      ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("muted", "🔓 exempt"));
    } else {
      ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("success", "🌿 worktree"));
    }
  }
}
