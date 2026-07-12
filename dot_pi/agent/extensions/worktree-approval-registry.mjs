import { execFileSync } from "node:child_process";
import { realpathSync } from "node:fs";

const REGISTRY = Symbol.for("dfrank.pi.worktree-approval-registry");
const NO_APPROVED_WORKTREE_REASON = "no active root-approved worktree for this session";
const registry = globalThis[REGISTRY] ??= new Map();

function git(cwd, args) {
	return execFileSync("git", ["-C", cwd, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

function canonicalRepoRoot(repoRoot) {
	return realpathSync(repoRoot);
}

function registryKey(sessionId, repoRoot) {
	return `${sessionId}\0${repoRoot}`;
}

function recordFor(sessionId, repoRoot, create = false) {
	const realRepoRoot = canonicalRepoRoot(repoRoot);
	const key = registryKey(sessionId, realRepoRoot);
	let record = registry.get(key);
	if (!record && create) {
		record = {
			repoRoot: realRepoRoot,
			generation: 0,
			nextLeaseId: 0,
			active: undefined,
			pendingStart: undefined,
			pendingStop: undefined,
		};
		registry.set(key, record);
	}
	if (record && !Number.isSafeInteger(record.nextLeaseId)) record.nextLeaseId = 0;
	return record;
}

function hasLease(active) {
	// Keep a hot-reloaded registry fail-closed while an older extension instance
	// still holds its count-based lease.
	return active?.leaseId !== undefined || active?.leases > 0;
}

function noApprovedWorktree() {
	return { ok: false, noApproval: true, reason: NO_APPROVED_WORKTREE_REASON };
}

function existingWorktreePath(worktreeRoot) {
	try {
		return realpathSync(worktreeRoot);
	} catch (error) {
		// Git retains missing worktrees as prunable records until explicit cleanup.
		if (error?.code === "ENOENT" || error?.code === "ENOTDIR") return undefined;
		throw error;
	}
}

function worktreePaths(repoRoot) {
	const paths = [];
	for (const line of git(repoRoot, ["worktree", "list", "--porcelain"]).split("\n")) {
		if (!line.startsWith("worktree ")) continue;
		const path = existingWorktreePath(line.slice("worktree ".length));
		if (path) paths.push(path);
	}
	return paths;
}

/** Verify a linked worktree against live Git topology before authorization. */
export function validateWorktree(repoRoot, worktreeRoot) {
	try {
		const realRepoRoot = canonicalRepoRoot(repoRoot);
		const realWorktreeRoot = existingWorktreePath(worktreeRoot);
		if (!realWorktreeRoot) return { ok: false, reason: "path is not an existing Git worktree" };
		const paths = worktreePaths(realRepoRoot);
		const primaryRoot = paths[0];
		if (!primaryRoot || realWorktreeRoot === primaryRoot) return { ok: false, reason: "worktree must not be the primary checkout" };
		if (!paths.includes(realWorktreeRoot)) return { ok: false, reason: "path is not a registered Git worktree" };
		const primaryCommonDir = git(primaryRoot, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
		const worktreeCommonDir = git(realWorktreeRoot, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
		if (realpathSync(primaryCommonDir) !== realpathSync(worktreeCommonDir)) {
			return { ok: false, reason: "worktree belongs to a different Git repository" };
		}
		return { ok: true, repoRoot: realRepoRoot, worktreeRoot: realWorktreeRoot };
	} catch (error) {
		return { ok: false, reason: `could not validate Git worktree: ${error.message}` };
	}
}

/** Start calls invalidate prior approval; only their matching result may reapprove. */
export function beginWorktreeStart({ sessionId, repoRoot, toolCallId }) {
	try {
		const record = recordFor(sessionId, repoRoot, true);
		if (record.pendingStart || record.pendingStop) return { ok: false, reason: "another worktree lifecycle operation is pending" };
		if (hasLease(record.active)) return { ok: false, reason: "an active worker holds the worktree lease" };
		record.generation += 1;
		record.active = undefined;
		record.pendingStart = { toolCallId, generation: record.generation };
		return { ok: true, generation: record.generation };
	} catch (error) {
		return { ok: false, reason: `could not begin worktree activation: ${error.message}` };
	}
}

export function finishWorktreeStart({ sessionId, repoRoot, worktreeRoot, toolCallId, succeeded }) {
	try {
		const record = recordFor(sessionId, repoRoot);
		if (!record?.pendingStart || record.pendingStart.toolCallId !== toolCallId) {
			return { ok: false, reason: "stale or unknown worktree_start result" };
		}
		const { generation } = record.pendingStart;
		record.pendingStart = undefined;
		if (!succeeded) return { ok: false, matched: true, reason: "worktree_start did not succeed" };
		const validated = validateWorktree(record.repoRoot, worktreeRoot);
		if (!validated.ok) return { ...validated, matched: true };
		record.active = { ...validated, generation, toolCallId, leaseId: undefined };
		return { ok: true, approval: record.active };
	} catch (error) {
		return { ok: false, reason: `could not finish worktree activation: ${error.message}` };
	}
}

/** Compatibility helper for direct unit callers; production uses begin/finish. */
export function approveWorktree({ sessionId, repoRoot, worktreeRoot, toolCallId }) {
	const started = beginWorktreeStart({ sessionId, repoRoot, toolCallId });
	if (!started.ok) return started;
	return finishWorktreeStart({ sessionId, repoRoot, worktreeRoot, toolCallId, succeeded: true });
}

export function beginWorktreeStop({ sessionId, repoRoot, toolCallId }) {
	try {
		// A no-op stop still calls an external lifecycle tool. Reserve the slot so
		// a concurrent start cannot race it before its result is known.
		const record = recordFor(sessionId, repoRoot, true);
		if (record.pendingStart || record.pendingStop) return { ok: false, reason: "another worktree lifecycle operation is pending" };
		if (hasLease(record.active)) return { ok: false, reason: "an active worker holds the worktree lease" };
		record.pendingStop = {
			toolCallId,
			generation: record.active?.generation ?? record.generation,
			hadActive: Boolean(record.active),
		};
		return { ok: true, generation: record.pendingStop.generation };
	} catch (error) {
		return { ok: false, reason: `could not begin worktree stop: ${error.message}` };
	}
}

/** Revoke only after the matching external stop reported an inactive state. */
export function finishWorktreeStop({ sessionId, repoRoot, toolCallId, succeeded }) {
	try {
		const record = recordFor(sessionId, repoRoot);
		if (!record?.pendingStop || record.pendingStop.toolCallId !== toolCallId) {
			return { ok: false, reason: "stale or unknown worktree_stop result" };
		}
		const { generation, hadActive } = record.pendingStop;
		record.pendingStop = undefined;
		if (!hadActive) {
			return succeeded ? { ok: true } : { ok: false, reason: "worktree_stop did not complete" };
		}
		if (!succeeded || !record.active || record.active.generation !== generation) {
			return { ok: false, reason: "worktree_stop did not deactivate the approved worktree" };
		}
		record.active = undefined;
		return { ok: true };
	} catch (error) {
		return { ok: false, reason: `could not finish worktree stop: ${error.message}` };
	}
}

/** Recover from a blocked, aborted, or otherwise result-less lifecycle call. */
export function cancelWorktreeLifecycle({ sessionId, repoRoot, toolCallId }) {
	try {
		const record = recordFor(sessionId, repoRoot);
		if (!record) return { ok: false, reason: "unknown worktree lifecycle operation" };
		if (record.pendingStart?.toolCallId === toolCallId) {
			record.pendingStart = undefined;
			return { ok: true, operation: "start" };
		}
		if (record.pendingStop?.toolCallId === toolCallId) {
			const { generation, hadActive } = record.pendingStop;
			record.pendingStop = undefined;
			// An unobserved stop may have deactivated package routing. Remove the
			// approval rather than risking a root mutation in the primary checkout.
			if (hadActive && record.active?.generation === generation) record.active = undefined;
			return { ok: true, operation: "stop" };
		}
		return { ok: false, reason: "stale or unknown worktree lifecycle operation" };
	} catch (error) {
		return { ok: false, reason: `could not cancel worktree lifecycle operation: ${error.message}` };
	}
}

export function revokeWorktree({ sessionId, repoRoot }) {
	try {
		registry.delete(registryKey(sessionId, canonicalRepoRoot(repoRoot)));
	} catch {
		// If the repository vanished, it remains unauthorized.
	}
}

export function resolveApprovedWorktree({ sessionId, repoRoot, cwd }) {
	try {
		const record = recordFor(sessionId, repoRoot);
		if (!record) return noApprovedWorktree();
		if (record.pendingStart) return { ok: false, reason: "worktree activation is pending" };
		if (record.pendingStop) return { ok: false, reason: "worktree stop is pending" };
		if (!record.active) return noApprovedWorktree();
		const validated = validateWorktree(record.repoRoot, record.active.worktreeRoot);
		// Keep the generation and lease intact when topology is transiently or
		// permanently invalid. Callers fail closed, while a running worker can
		// still release its lease and unblock a later recovery attempt.
		if (!validated.ok) return validated;
		if (cwd !== undefined && realpathSync(cwd) !== validated.worktreeRoot) {
			return { ok: false, reason: "child cwd is not the root-approved worktree" };
		}
		Object.assign(record.active, validated);
		return { ok: true, approval: record.active };
	} catch (error) {
		return { ok: false, reason: `could not resolve approved worktree: ${error.message}` };
	}
}

/** One generation-bound lease serializes all writable workers for a worktree. */
export function acquireWorktreeLease(request) {
	const resolved = resolveApprovedWorktree(request);
	if (!resolved.ok) return resolved;
	const record = recordFor(request.sessionId, request.repoRoot);
	if (!record?.active || record.active !== resolved.approval) {
		return { ok: false, reason: "approved worktree changed while acquiring its lease" };
	}
	if (hasLease(record.active)) return { ok: false, reason: "an active worker holds the worktree lease" };
	const leaseId = ++record.nextLeaseId;
	record.active.leaseId = leaseId;
	return {
		ok: true,
		lease: {
			repoRoot: record.active.repoRoot,
			worktreeRoot: record.active.worktreeRoot,
			generation: record.active.generation,
			leaseId,
		},
	};
}

export function releaseWorktreeLease({ sessionId, repoRoot, generation, leaseId }) {
	try {
		const record = recordFor(sessionId, repoRoot);
		if (record?.active && record.active.generation === generation && record.active.leaseId === leaseId) {
			record.active.leaseId = undefined;
			return { ok: true };
		}
		return { ok: false, reason: "stale or unknown worktree lease" };
	} catch {
		// A removed registry never regains authorization through a late release.
		return { ok: false, reason: "worktree registry is unavailable" };
	}
}

export function worktreeHasLeases({ sessionId, repoRoot }) {
	try {
		return hasLease(recordFor(sessionId, repoRoot)?.active);
	} catch {
		return false;
	}
}
