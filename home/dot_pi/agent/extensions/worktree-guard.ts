/**
 * Enforce root-owned worktree activation and managed child boundaries.
 *
 * Direct write/edit calls are denied to read-only or unmarked children. Bash uses
 * the shared best-effort classifier and blocks only recognized mutations, so this
 * is a cooperative workflow policy rather than a shell sandbox. A writable
 * child's initial cwd is independently validated against live Git topology; that
 * launch-routing check is not path containment after the worker starts.
 * PI_SUBAGENT remains a cooperative workflow marker, not authentication for an
 * independently launched process.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { closeSync, constants, fstatSync, openSync, readSync, realpathSync } from "node:fs";
import { isAbsolute } from "node:path";
import {
	beginWorktreeStart,
	beginWorktreeStop,
	cancelWorktreeLifecycle,
	finishWorktreeStart,
	finishWorktreeStop,
	hydrateApprovedWorktree,
	resolveApprovedWorktree,
	revokeWorktree,
	validateWorktree,
} from "./worktree-approval-registry.mjs";
import { isDelegatedChild } from "./child-policy.mjs";
import { checkBashCommand } from "./bash-mutation-policy.mjs";

const ROOT_LIFECYCLE_TOOLS = new Set(["worktree_start", "worktree_status", "worktree_stop"]);
// pi-worktree's state contract keeps a conflict-mode worktree available for resolution, so it remains resumable.
const RESUMABLE_WORKTREE_MODES = new Set(["active", "conflict"]);
const RESUME_WORKTREE_CHECKPOINT_TOOLS = new Set(["worktree_start", "worktree_stop"]);
const WORKTREE_REQUIRED_STATUS = "🔒 worktree required";
// A 64 MiB JSONL parent is generous for a long transcript; larger ancestry proofs are anomalous and must not consume unbounded startup memory.
const MAX_PARENT_SESSION_BYTES = 64 * 1024 * 1024;
let repoRoot = "";
let sessionId = "";
let guarded = false;
let childExecution: "read-only" | "worktree-write" | "unmarked" | undefined;
let childWithoutWorktreeLease = false;

function isMutation(event: { toolName: string; input?: Record<string, unknown> }): boolean {
	if (event.toolName === "write" || event.toolName === "edit") return true;
	return event.toolName === "bash" && Boolean(checkBashCommand(String(event.input?.command ?? "")));
}

const BLOCK_MSG = "Blocked: mutations require a root-approved active worktree. Call worktree_start and retry.";

function asRecord(value: unknown): Record<string, unknown> | undefined {
	return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
}

function parentSessionEntryIds(parentSession: string): Set<string> | undefined {
	let parentFd: number | undefined;
	try {
		if (!isAbsolute(parentSession)) return undefined;
		// Opening nonblocking lets fstat reject a FIFO instead of waiting for a writer.
		parentFd = openSync(parentSession, constants.O_RDONLY | constants.O_NONBLOCK);
		const parentStats = fstatSync(parentFd);
		if (!parentStats.isFile() || parentStats.size > MAX_PARENT_SESSION_BYTES) return undefined;
		const contents = Buffer.allocUnsafe(parentStats.size);
		let bytesRead = 0;
		while (bytesRead < contents.length) {
			const read = readSync(parentFd, contents, bytesRead, contents.length - bytesRead, bytesRead);
			if (read === 0) return undefined;
			bytesRead += read;
		}
		if (fstatSync(parentFd).size !== parentStats.size) return undefined;
		const entries = contents
			.toString("utf8")
			.trim()
			.split("\n")
			.map((line) => asRecord(JSON.parse(line)));
		if (entries[0]?.type !== "session") return undefined;
		const entryIds = new Set<string>();
		for (const entry of entries) {
			if (!entry || typeof entry.type !== "string" || typeof entry.id !== "string" || !entry.id) return undefined;
			entryIds.add(entry.id);
		}
		return entryIds;
	} catch {
		return undefined;
	} finally {
		if (parentFd !== undefined) closeSync(parentFd);
	}
}

function restoredWorktreeState(entries: unknown, expectedRepoRoot: string): { entryId: string; worktreeRoot: string; branch: string } | undefined {
	if (!Array.isArray(entries)) return undefined;
	for (const entry of [...entries].reverse()) {
		const entryRecord = asRecord(entry);
		const message = asRecord(entryRecord?.message);
		if (typeof message?.toolName !== "string" || !RESUME_WORKTREE_CHECKPOINT_TOOLS.has(message.toolName)) continue;
		const details = asRecord(message?.details ?? entryRecord?.details);
		if (!details || !Object.hasOwn(details, "piWorktree")) return undefined;
		const candidate = asRecord(details.piWorktree);
		if (!candidate || typeof candidate.repoRoot !== "string" || !isAbsolute(candidate.repoRoot)) return undefined;
		if (candidate.repoRoot !== expectedRepoRoot) continue;
		if (message.toolName === "worktree_stop") return undefined;
		if (
			typeof entryRecord?.id !== "string" ||
			!entryRecord.id ||
			typeof candidate.mode !== "string" ||
			!RESUMABLE_WORKTREE_MODES.has(candidate.mode) ||
			typeof candidate.worktreeRoot !== "string" ||
			typeof candidate.branch !== "string"
		) {
			return undefined;
		}
		return { entryId: entryRecord.id, worktreeRoot: candidate.worktreeRoot, branch: candidate.branch };
	}
	return undefined;
}

function childInitialCwdIsApprovedWorktree(cwd: string): boolean {
	try {
		const expectedRepoRoot = process.env.PI_WORKTREE_REPO_ROOT;
		const expectedWorktreeRoot = process.env.PI_WORKTREE_ROOT;
		const generation = Number(process.env.PI_WORKTREE_GENERATION);
		if (
			!expectedRepoRoot ||
			!expectedWorktreeRoot ||
			!Number.isSafeInteger(generation) ||
			generation < 1 ||
			realpathSync(cwd) !== realpathSync(expectedWorktreeRoot)
		) {
			return false;
		}
		const validated = validateWorktree(expectedRepoRoot, expectedWorktreeRoot);
		return validated.ok && validated.worktreeRoot === realpathSync(cwd);
	} catch {
		return false;
	}
}

export default function worktreeGuard(pi: ExtensionAPI) {
	pi.on("session_start", async (event, ctx) => {
		sessionId = ctx.sessionManager.getSessionId();
		// A delegated reader may start outside Git; classify it before the root
		// probe so a failed discovery cannot leave its mutation boundary inactive.
		childWithoutWorktreeLease = false;
		if (isDelegatedChild()) {
			// This validates only the startup cwd; approved workers remain cooperative
			// after launch and can otherwise select direct Git/Bash paths themselves.
			const isWorktreeWrite = process.env.PI_SUBAGENT_EXECUTION === "worktree-write";
			childWithoutWorktreeLease =
				isWorktreeWrite &&
				!process.env.PI_WORKTREE_ROOT &&
				!process.env.PI_WORKTREE_REPO_ROOT &&
				!process.env.PI_WORKTREE_GENERATION;
			childExecution = isWorktreeWrite && childInitialCwdIsApprovedWorktree(ctx.cwd)
				? "worktree-write"
				: process.env.PI_SUBAGENT_EXECUTION === "read-only"
					? "read-only"
					: "unmarked";
			guarded = true;
			return;
		}

		const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], { timeout: 3_000 });
		if (result.code !== 0 || !result.stdout.trim()) return;
		repoRoot = result.stdout.trim();
		guarded = true;
		ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("warning", WORKTREE_REQUIRED_STATUS));
		if (event.reason !== "resume" && event.reason !== "reload") return;
		const restored = restoredWorktreeState(ctx.sessionManager.getBranch(), repoRoot);
		if (!restored) return;
		const parentSession = ctx.sessionManager.getHeader()?.parentSession;
		// The reason gate limits restoration paths; parentSession rejects a candidate copied from fork/clone history.
		// A parent that cannot be read as JSONL is not evidence of native approval.
		if (parentSession !== undefined) {
			const parentEntryIds = typeof parentSession === "string" ? parentSessionEntryIds(parentSession) : undefined;
			if (!parentEntryIds || parentEntryIds.has(restored.entryId)) return;
		}
		// Session history records routing, not permission; live Git must reject stale or forged state before writes are allowed.
		const hydrated = hydrateApprovedWorktree({ sessionId, repoRoot, worktreeRoot: restored.worktreeRoot, branch: restored.branch });
		if (hydrated.ok) ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("success", "🌿 worktree approved"));
	});

	pi.on("tool_call", async (event, ctx) => {
		if (!guarded) return;
		if (childExecution) {
			if (event.toolName.startsWith("worktree_")) return { block: true, reason: "Blocked: worktree lifecycle tools are root-owned." };
			if (isMutation(event) && childExecution !== "worktree-write") {
				const reason = childWithoutWorktreeLease
					? "Blocked: this delegated worker launched without a Git worktree; local mutations are unavailable in a non-Git directory."
					: "Blocked: this delegated child is read-only or lacks a validated worktree marker.";
				return { block: true, reason };
			}
			return;
		}
		if (event.toolName === "worktree_start") {
			const started = beginWorktreeStart({ sessionId, repoRoot, toolCallId: event.toolCallId });
			if (!started.ok) return { block: true, reason: `Blocked: ${started.reason}.` };
			return;
		}
		if (event.toolName === "worktree_stop") {
			const stopping = beginWorktreeStop({ sessionId, repoRoot, toolCallId: event.toolCallId });
			if (!stopping.ok) return { block: true, reason: `Blocked: ${stopping.reason}.` };
			return;
		}
		if (ROOT_LIFECYCLE_TOOLS.has(event.toolName)) return;
		if (event.toolName.startsWith("worktree_")) return { block: true, reason: "Blocked: only root lifecycle tools worktree_start, worktree_status, and worktree_stop are permitted." };
		if (!isMutation(event)) return;
		const approved = resolveApprovedWorktree({ sessionId, repoRoot });
		if (!approved.ok) return { block: true, reason: `${BLOCK_MSG}\n\n${approved.reason}` };
	});

	pi.on("tool_result", async (event, ctx) => {
		if (!guarded || childExecution) return;
		if (event.toolName === "worktree_start") {
			const state = event.details?.piWorktree;
			const approved = finishWorktreeStart({
				sessionId,
				repoRoot,
				worktreeRoot: state?.worktreeRoot,
				toolCallId: event.toolCallId,
				succeeded: !event.isError && state?.mode === "active" && state?.repoRoot === repoRoot,
			});
			if (!approved.ok && !event.isError) ctx.ui.notify(`worktree activation rejected: ${approved.reason}`, "error");
			if (approved.ok) ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("success", "🌿 worktree approved"));
			else if (approved.matched) ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("warning", WORKTREE_REQUIRED_STATUS));
			return;
		}
		if (event.toolName === "worktree_stop") {
			const state = event.details?.piWorktree;
			const stopped = finishWorktreeStop({
				sessionId,
				repoRoot,
				toolCallId: event.toolCallId,
				succeeded: !event.isError && state?.mode === "inactive",
			});
			if (stopped.ok) ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("warning", WORKTREE_REQUIRED_STATUS));
		}
	});

	pi.on("tool_execution_end", async (event, ctx) => {
		if (!guarded || childExecution || !ROOT_LIFECYCLE_TOOLS.has(event.toolName)) return;
		// A blocked preflight call has no tool_result hook. Ending the lifecycle
		// slot here prevents it from trapping the session in a pending state.
		const canceled = cancelWorktreeLifecycle({ sessionId, repoRoot, toolCallId: event.toolCallId });
		if (canceled.ok) ctx.ui.setStatus("worktree-guard", ctx.ui.theme.fg("warning", WORKTREE_REQUIRED_STATUS));
	});

	pi.on("session_shutdown", async () => {
		if (!childExecution && repoRoot && sessionId) revokeWorktree({ sessionId, repoRoot });
	});
}
