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
import { realpathSync } from "node:fs";
import {
	beginWorktreeStart,
	beginWorktreeStop,
	cancelWorktreeLifecycle,
	finishWorktreeStart,
	finishWorktreeStop,
	resolveApprovedWorktree,
	revokeWorktree,
	validateWorktree,
} from "./worktree-approval-registry.mjs";
import { isDelegatedChild } from "./child-policy.mjs";
import { checkBashCommand } from "./bash-mutation-policy.mjs";

const ROOT_LIFECYCLE_TOOLS = new Set(["worktree_start", "worktree_status", "worktree_stop"]);
const WORKTREE_REQUIRED_STATUS = "🔒 worktree required";
let repoRoot = "";
let sessionId = "";
let guarded = false;
let childExecution: "read-only" | "worktree-write" | "unmarked" | undefined;

function isMutation(event: { toolName: string; input?: Record<string, unknown> }): boolean {
	if (event.toolName === "write" || event.toolName === "edit") return true;
	return event.toolName === "bash" && Boolean(checkBashCommand(String(event.input?.command ?? "")));
}

const BLOCK_MSG = "Blocked: mutations require a root-approved active worktree. Call worktree_start and retry.";

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
	pi.on("session_start", async (_event, ctx) => {
		sessionId = ctx.sessionManager.getSessionId();
		// A delegated reader may start outside Git; classify it before the root
		// probe so a failed discovery cannot leave its mutation boundary inactive.
		if (isDelegatedChild()) {
			// This validates only the startup cwd; approved workers remain cooperative
			// after launch and can otherwise select direct Git/Bash paths themselves.
			childExecution = process.env.PI_SUBAGENT_EXECUTION === "worktree-write" && childInitialCwdIsApprovedWorktree(ctx.cwd)
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
	});

	pi.on("tool_call", async (event, ctx) => {
		if (!guarded) return;
		if (childExecution) {
			if (event.toolName.startsWith("worktree_")) return { block: true, reason: "Blocked: worktree lifecycle tools are root-owned." };
			if (isMutation(event) && childExecution !== "worktree-write") return { block: true, reason: "Blocked: this delegated child is read-only or lacks a validated worktree marker." };
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
