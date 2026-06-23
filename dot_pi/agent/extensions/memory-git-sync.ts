/**
 * Memory Git Sync Extension
 *
 * Syncs the pi-memory store (~/.pi/agent/memory, or $PI_MEMORY_DIR) across
 * machines via a git remote. Pairs with the `pi-memory` npm extension, which
 * writes plain-markdown memory (MEMORY.md, SCRATCHPAD.md, daily/) at runtime.
 *
 * Why an extension and not a chezmoi script / cron:
 *   - Memory is runtime-mutable data written home-side, which fights chezmoi's
 *     one-way source→home apply model. chezmoi (via a git-repo external) owns
 *     the initial clone + periodic pull; this extension owns push of runtime
 *     writes. Session lifecycle is the natural, daemon-free event source.
 *
 * Behavior (best-effort — git failures NEVER block or crash a pi session):
 *   - session_start  → `git pull --rebase --autostash` (fast-forward newest
 *                       memory from other machines before the session reads it).
 *   - session_shutdown → stage all, commit if dirty, then `git push`.
 *
 * Self-gating: inert unless the memory dir is a git work tree with an `origin`
 * remote. On machines where the chezmoi git-repo external did not clone the
 * repo (e.g. work machines), every operation is a silent no-op — so this file
 * can deploy everywhere without machine-specific templating.
 *
 * Design choices:
 *   - `--autostash` + `--rebase` on pull so an interrupted prior session that
 *     left uncommitted writes does not wedge the sync.
 *   - Commits are skipped when the tree is clean (no empty commits).
 *   - Each git invocation has a hard timeout so a hung remote cannot stall
 *     session startup/teardown.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const GIT_TIMEOUT_MS = 20_000;

/** Mirror pi-memory's resolveMemoryDir: $PI_MEMORY_DIR or ~/.pi/agent/memory. */
function memoryDir(): string {
  return process.env.PI_MEMORY_DIR ?? join(homedir(), ".pi", "agent", "memory");
}

async function git(dir: string, args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", ["-C", dir, ...args], {
    timeout: GIT_TIMEOUT_MS,
  });
  return stdout.trim();
}

/** True only when `dir` is a git work tree with an `origin` remote. */
async function isSyncableRepo(dir: string): Promise<boolean> {
  if (!existsSync(dir)) return false;
  try {
    const inside = await git(dir, ["rev-parse", "--is-inside-work-tree"]);
    if (inside !== "true") return false;
    const remotes = await git(dir, ["remote"]);
    return remotes.split(/\s+/).includes("origin");
  } catch {
    return false;
  }
}

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    const dir = memoryDir();
    if (!(await isSyncableRepo(dir))) return;
    try {
      await git(dir, ["pull", "--rebase", "--autostash"]);
    } catch (err) {
      ctx.ui.notify(`memory-git-sync: pull failed (${(err as Error).message})`, "warning");
    }
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    const dir = memoryDir();
    if (!(await isSyncableRepo(dir))) return;
    try {
      await git(dir, ["add", "-A"]);
      const status = await git(dir, ["status", "--porcelain"]);
      if (status) {
        const stamp = new Date().toISOString();
        await git(dir, ["commit", "-m", `chore(memory): sync ${stamp}`]);
      }
      await git(dir, ["push"]);
    } catch (err) {
      ctx.ui.notify(`memory-git-sync: push failed (${(err as Error).message})`, "warning");
    }
  });
}
