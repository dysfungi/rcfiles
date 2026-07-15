/**
 * Synchronize Pi's runtime-owned memory checkout without letting chezmoi mutate it.
 *
 * Chezmoi clones the external once; this extension is the sole routine Git actor.
 * Runtime synchronization merges origin/main instead of rebasing so local daily-log
 * additions can use the local union attribute while curated-memory conflicts stop safely.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { promisify } from "node:util";
import { isDelegatedChild } from "./child-policy.mjs";

const execFileAsync = promisify(execFile);

const GIT_TIMEOUT_MS = 20_000;
export const MEMORY_REMOTE_URL = "git@github.com:dysfungi/ai.memory.git";

const ATTRIBUTES_BEGIN = "# BEGIN pi-memory-managed";
const ATTRIBUTES_END = "# END pi-memory-managed";
export const MEMORY_ATTRIBUTES_BLOCK = [
  ATTRIBUTES_BEGIN,
  "daily/**/*.md merge=union",
  "MEMORY.md -merge",
  "SCRATCHPAD.md -merge",
  ATTRIBUTES_END,
].join("\n");

type GitCommandResult = {
  exitCode: number;
  stdout: string;
};

type SyncState = "disabled" | "healthy" | "disabled-for-session";

type NotificationUi = {
  notify(message: string, level: "warning"): void;
};

type MutationResult =
  | { ok: true; committed: boolean }
  | {
      ok: false;
      phase: string;
      exitCode?: number;
      health?: RepositoryHealth;
    };

export type RepositoryHealth = {
  healthy: boolean;
  reason: string;
  worktreeRoot?: string;
  gitCommonDir?: string;
};

export type AttributesResult =
  | { ok: true; changed: boolean; path: string }
  | { ok: false; reason: string; exitCode?: number };

/** Mirror pi-memory's resolveMemoryDir: $PI_MEMORY_DIR or ~/.pi/agent/memory. */
function memoryDir(): string {
  return process.env.PI_MEMORY_DIR ?? join(homedir(), ".pi", "agent", "memory");
}

function gitEnvironment(): NodeJS.ProcessEnv {
  // An allowlist prevents Git's current and future environment-based repository
  // redirection and config-injection controls from reaching any subprocess.
  // Batch SSH and a failing askpass command keep lifecycle handlers from hanging
  // on a terminal, inherited SSH wrapper, or graphical credential prompt.
  return {
    HOME: process.env.HOME,
    PATH: process.env.PATH,
    SSH_AUTH_SOCK: process.env.SSH_AUTH_SOCK,
    GIT_TERMINAL_PROMPT: "0",
    GIT_EDITOR: "true",
    GIT_SSH_COMMAND: "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
    GIT_ASKPASS: "/bin/false",
    SSH_ASKPASS: "/bin/false",
    SSH_ASKPASS_REQUIRE: "force",
  };
}

function exitCode(error: unknown): number {
  if (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof error.code === "number"
  ) {
    return error.code;
  }
  return 1;
}

async function git(directory: string, args: string[]): Promise<GitCommandResult> {
  try {
    const { stdout } = await execFileAsync("git", ["-C", directory, ...args], {
      cwd: directory,
      env: gitEnvironment(),
      timeout: GIT_TIMEOUT_MS,
    });
    return { exitCode: 0, stdout: stdout.trim() };
  } catch (error) {
    return { exitCode: exitCode(error), stdout: "" };
  }
}

function failure(reason: string, details: Partial<RepositoryHealth> = {}): RepositoryHealth {
  return { healthy: false, reason, ...details };
}

function resolveGitPath(worktreeRoot: string, gitPath: string): string {
  return isAbsolute(gitPath) ? gitPath : resolve(worktreeRoot, gitPath);
}

function allRemoteUrlsMatch(result: GitCommandResult, expectedRemoteUrl: string): boolean {
  const urls = result.stdout.split("\n").filter(Boolean);
  return result.exitCode === 0 && urls.length > 0 && urls.every((url) => url === expectedRemoteUrl);
}

function activeOperation(gitCommonDir: string): string | undefined {
  const markers = [
    ["MERGE_HEAD", "merge"],
    ["CHERRY_PICK_HEAD", "cherry-pick"],
    ["REVERT_HEAD", "revert"],
    ["rebase-apply", "rebase"],
    ["rebase-merge", "rebase"],
    ["sequencer", "sequencer"],
    ["BISECT_START", "bisect"],
  ] as const;

  return markers.find(([path]) => existsSync(join(gitCommonDir, path)))?.[1];
}

/**
 * Inspect the expected checkout without changing its index, refs, or working tree.
 *
 * The explicit root and remote checks reject redirected Git environment variables,
 * detached checkouts, and lookalike repositories before the extension writes anything.
 */
export async function probeRepository(
  directory: string,
  expectedRemoteUrl = MEMORY_REMOTE_URL,
): Promise<RepositoryHealth> {
  if (!existsSync(directory)) return failure("memory directory is missing");

  let expectedRoot: string;
  try {
    expectedRoot = realpathSync(directory);
  } catch {
    return failure("memory directory cannot be resolved");
  }

  const insideWorkTree = await git(directory, ["rev-parse", "--is-inside-work-tree"]);
  if (insideWorkTree.exitCode !== 0 || insideWorkTree.stdout !== "true") {
    return failure(`not a Git worktree (exit ${insideWorkTree.exitCode})`);
  }

  const topLevel = await git(directory, ["rev-parse", "--show-toplevel"]);
  if (topLevel.exitCode !== 0 || !topLevel.stdout) {
    return failure(`worktree root lookup failed (exit ${topLevel.exitCode})`);
  }

  let worktreeRoot: string;
  try {
    worktreeRoot = realpathSync(topLevel.stdout);
  } catch {
    return failure("worktree root cannot be resolved");
  }
  if (worktreeRoot !== expectedRoot) {
    return failure("worktree root does not match memory directory", { worktreeRoot });
  }

  const branch = await git(directory, ["symbolic-ref", "--short", "HEAD"]);
  if (branch.exitCode !== 0) {
    return failure("detached HEAD", { worktreeRoot });
  }
  if (branch.stdout !== "main") {
    return failure("branch is not main", { worktreeRoot });
  }

  const fetchRemote = await git(directory, ["remote", "get-url", "--all", "origin"]);
  if (!allRemoteUrlsMatch(fetchRemote, expectedRemoteUrl)) {
    return failure("unexpected origin fetch URL", { worktreeRoot });
  }

  const pushRemote = await git(directory, ["remote", "get-url", "--all", "--push", "origin"]);
  if (!allRemoteUrlsMatch(pushRemote, expectedRemoteUrl)) {
    return failure("unexpected origin push URL", { worktreeRoot });
  }

  const commonDir = await git(directory, ["rev-parse", "--git-common-dir"]);
  if (commonDir.exitCode !== 0 || !commonDir.stdout) {
    return failure(`git common directory lookup failed (exit ${commonDir.exitCode})`, {
      worktreeRoot,
    });
  }
  const gitCommonDir = resolveGitPath(worktreeRoot, commonDir.stdout);
  const gitDir = await git(directory, ["rev-parse", "--git-dir"]);
  if (gitDir.exitCode !== 0 || !gitDir.stdout) {
    return failure(`git directory lookup failed (exit ${gitDir.exitCode})`, {
      worktreeRoot,
      gitCommonDir,
    });
  }

  // The memory external is a standalone checkout, so this extension can own its lifecycle.
  // Linked worktrees keep operation state outside the common Git directory; reject them
  // rather than risk committing an unfinished operation.
  if (resolveGitPath(worktreeRoot, gitDir.stdout) !== gitCommonDir) {
    return failure("linked worktrees are unsupported", { worktreeRoot, gitCommonDir });
  }

  const unmerged = await git(directory, ["ls-files", "-u"]);
  if (unmerged.exitCode !== 0) {
    return failure(`unmerged-index lookup failed (exit ${unmerged.exitCode})`, {
      worktreeRoot,
      gitCommonDir,
    });
  }
  if (unmerged.stdout) {
    return failure("unmerged index", { worktreeRoot, gitCommonDir });
  }

  const operation = activeOperation(gitCommonDir);
  if (operation) {
    return failure(`active operation (${operation})`, { worktreeRoot, gitCommonDir });
  }

  return { healthy: true, reason: "healthy", worktreeRoot, gitCommonDir };
}

const MEMORY_ATTRIBUTE_PATHS = [
  "MEMORY.md",
  "SCRATCHPAD.md",
  "daily/.pi-memory-attribute-probe.md",
] as const;
const EXPECTED_MEMORY_ATTRIBUTES = [
  "MEMORY.md: merge: unset",
  "SCRATCHPAD.md: merge: unset",
  "daily/.pi-memory-attribute-probe.md: merge: union",
].join("\n");

async function verifyMemoryAttributes(
  directory: string,
  health: RepositoryHealth,
): Promise<RepositoryHealth> {
  const attributes = await git(directory, ["check-attr", "merge", "--", ...MEMORY_ATTRIBUTE_PATHS]);
  if (attributes.exitCode !== 0 || attributes.stdout !== EXPECTED_MEMORY_ATTRIBUTES) {
    return failure("managed attributes are ineffective", {
      worktreeRoot: health.worktreeRoot,
      gitCommonDir: health.gitCommonDir,
    });
  }
  return health;
}

/**
 * Replace exactly one managed attributes region, keeping user-owned local rules intact.
 *
 * Refusing malformed or duplicate markers avoids silently deleting hand-maintained rules.
 */
export function managedAttributesContent(
  existingContent: string,
  managedBlock = MEMORY_ATTRIBUTES_BLOCK,
): string {
  const beginMatches = existingContent.match(
    new RegExp(`^${ATTRIBUTES_BEGIN.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`, "gm"),
  );
  const endMatches = existingContent.match(
    new RegExp(`^${ATTRIBUTES_END.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`, "gm"),
  );
  const beginCount = beginMatches?.length ?? 0;
  const endCount = endMatches?.length ?? 0;

  if (beginCount !== endCount || beginCount > 1) {
    throw new Error("malformed pi-memory-managed attributes markers");
  }

  const normalizedBlock = managedBlock.replace(/\n+$/, "");
  if (beginCount === 0) {
    if (!existingContent) return `${normalizedBlock}\n`;
    const separator = existingContent.endsWith("\n") ? "\n" : "\n\n";
    return `${existingContent}${separator}${normalizedBlock}\n`;
  }

  const managedRegion = new RegExp(
    `(^|\\n)${ATTRIBUTES_BEGIN.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\n[\\s\\S]*?\\n${ATTRIBUTES_END.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=\\n|$)`,
  );
  const updatedContent = existingContent.replace(
    managedRegion,
    (_match, prefix: string) => `${prefix}${normalizedBlock}`,
  );
  return updatedContent.endsWith("\n") ? updatedContent : `${updatedContent}\n`;
}

/** Install the managed local attributes block through Git's path resolver. */
export async function ensureMemoryAttributes(directory: string): Promise<AttributesResult> {
  const attributesPath = await git(directory, [
    "rev-parse",
    "--git-path",
    "info/attributes",
  ]);
  if (attributesPath.exitCode !== 0 || !attributesPath.stdout) {
    return {
      ok: false,
      reason: "attributes path lookup failed",
      exitCode: attributesPath.exitCode,
    };
  }

  const path = resolveGitPath(directory, attributesPath.stdout);
  let existingContent = "";
  try {
    if (lstatSync(path).isSymbolicLink()) {
      return { ok: false, reason: "attributes file is a symbolic link" };
    }
    existingContent = readFileSync(path, "utf8");
  } catch (error) {
    if (!(typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT")) {
      return { ok: false, reason: "attributes file cannot be read" };
    }
  }

  let nextContent: string;
  try {
    nextContent = managedAttributesContent(existingContent);
  } catch {
    return { ok: false, reason: "attributes markers are malformed" };
  }
  if (nextContent === existingContent) return { ok: true, changed: false, path };

  const temporaryPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(temporaryPath, nextContent, "utf8");
    renameSync(temporaryPath, path);
  } catch {
    try {
      unlinkSync(temporaryPath);
    } catch {
      // The write failed before a temporary file existed, or the rename consumed it.
    }
    return { ok: false, reason: "attributes file cannot be updated" };
  }

  return { ok: true, changed: true, path };
}

async function commitWorkingTree(directory: string): Promise<MutationResult> {
  const status = await git(directory, ["status", "--porcelain"]);
  if (status.exitCode !== 0) {
    return { ok: false, phase: "status", exitCode: status.exitCode };
  }
  if (!status.stdout) return { ok: true, committed: false };

  const beforeAdd = await probeRepository(directory);
  if (!beforeAdd.healthy) {
    return { ok: false, phase: "before add", health: beforeAdd };
  }

  const add = await git(directory, ["add", "-A"]);
  if (add.exitCode !== 0) return { ok: false, phase: "add", exitCode: add.exitCode };

  const staged = await git(directory, ["diff", "--cached", "--quiet"]);
  if (staged.exitCode === 0) return { ok: true, committed: false };
  if (staged.exitCode !== 1) {
    return { ok: false, phase: "staged-change check", exitCode: staged.exitCode };
  }

  const beforeCommit = await probeRepository(directory);
  if (!beforeCommit.healthy) {
    return { ok: false, phase: "before commit", health: beforeCommit };
  }

  const commit = await git(directory, [
    "commit",
    "-m",
    `chore(memory): sync ${new Date().toISOString()}`,
  ]);
  if (commit.exitCode !== 0) {
    return { ok: false, phase: "commit", exitCode: commit.exitCode };
  }

  return { ok: true, committed: true };
}

function notify(ui: NotificationUi, message: string): void {
  ui.notify(`memory-git-sync: ${message}`, "warning");
}

function notifyHealthFailure(ui: NotificationUi, health: RepositoryHealth): void {
  notify(ui, `memory sync disabled: unhealthy repository (${health.reason})`);
}

function notifyMutationFailure(ui: NotificationUi, result: Exclude<MutationResult, { ok: true }>): void {
  if (result.health) {
    notifyHealthFailure(ui, result.health);
    return;
  }
  notify(ui, `memory sync disabled: ${result.phase} failed (exit ${result.exitCode ?? 1})`);
}

async function recoverFromFailedFetchOrMerge(
  directory: string,
  ui: NotificationUi,
  phase: "fetch" | "merge",
  failureExitCode: number,
  knownGitCommonDir: string,
): Promise<void> {
  const afterFailure = await probeRepository(directory);
  const gitCommonDir = afterFailure.gitCommonDir ?? knownGitCommonDir;
  if (existsSync(join(gitCommonDir, "MERGE_HEAD"))) {
    const abort = await git(directory, ["merge", "--abort"]);
    if (abort.exitCode !== 0) {
      notify(
        ui,
        `memory sync disabled: ${phase} failed (exit ${failureExitCode}); merge abort failed (exit ${abort.exitCode}); recovery-required`,
      );
      return;
    }
  }

  const afterRecovery = await probeRepository(directory);
  const recovery = afterRecovery.healthy
    ? "repository recovered; local commit retained"
    : `recovery-required (${afterRecovery.reason})`;
  notify(
    ui,
    `memory sync disabled: ${phase} failed (exit ${failureExitCode}); ${recovery}`,
  );
}

async function startupSync(directory: string, ui: NotificationUi): Promise<boolean> {
  const initialHealth = await probeRepository(directory);
  if (!initialHealth.healthy) {
    notifyHealthFailure(ui, initialHealth);
    return false;
  }

  const fetch = await git(directory, ["fetch", "origin", "main"]);
  if (fetch.exitCode !== 0) {
    await recoverFromFailedFetchOrMerge(
      directory,
      ui,
      "fetch",
      fetch.exitCode,
      initialHealth.gitCommonDir!,
    );
    return false;
  }

  const attributes = await ensureMemoryAttributes(directory);
  if (!attributes.ok) {
    notify(
      ui,
      `memory sync disabled: ${attributes.reason}${attributes.exitCode === undefined ? "" : ` (exit ${attributes.exitCode})`}`,
    );
    return false;
  }

  const localCommit = await commitWorkingTree(directory);
  if (!localCommit.ok) {
    notifyMutationFailure(ui, localCommit);
    return false;
  }

  const beforeMerge = await probeRepository(directory);
  if (!beforeMerge.healthy) {
    notifyHealthFailure(ui, beforeMerge);
    return false;
  }

  const effectiveAttributes = await verifyMemoryAttributes(directory, beforeMerge);
  if (!effectiveAttributes.healthy) {
    notifyHealthFailure(ui, effectiveAttributes);
    return false;
  }

  const merge = await git(directory, ["merge", "--no-edit", "origin/main"]);
  if (merge.exitCode !== 0) {
    await recoverFromFailedFetchOrMerge(
      directory,
      ui,
      "merge",
      merge.exitCode,
      beforeMerge.gitCommonDir!,
    );
    return false;
  }

  const afterMerge = await probeRepository(directory);
  if (!afterMerge.healthy) {
    notifyHealthFailure(ui, afterMerge);
    return false;
  }

  return true;
}

async function shutdownSync(directory: string, ui: NotificationUi): Promise<boolean> {
  const initialHealth = await probeRepository(directory);
  if (!initialHealth.healthy) {
    notifyHealthFailure(ui, initialHealth);
    return false;
  }

  const attributes = await ensureMemoryAttributes(directory);
  if (!attributes.ok) {
    notify(
      ui,
      `memory sync disabled: ${attributes.reason}${attributes.exitCode === undefined ? "" : ` (exit ${attributes.exitCode})`}`,
    );
    return false;
  }

  const localCommit = await commitWorkingTree(directory);
  if (!localCommit.ok) {
    notifyMutationFailure(ui, localCommit);
    return false;
  }

  const beforePush = await probeRepository(directory);
  if (!beforePush.healthy) {
    notifyHealthFailure(ui, beforePush);
    return false;
  }

  const push = await git(directory, ["push", "origin", "HEAD:refs/heads/main"]);
  if (push.exitCode !== 0) {
    notify(
      ui,
      `memory sync disabled: push failed (exit ${push.exitCode}); local commit retained for next startup`,
    );
    return false;
  }

  return true;
}

export default function (pi: ExtensionAPI) {
  if (isDelegatedChild()) return;

  let state: SyncState = "disabled";

  pi.on("session_start", async (_event, ctx) => {
    if (state === "disabled-for-session") return;
    state = (await startupSync(memoryDir(), ctx.ui)) ? "healthy" : "disabled-for-session";
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (state !== "healthy") return;
    if (!(await shutdownSync(memoryDir(), ctx.ui))) state = "disabled-for-session";
  });
}
