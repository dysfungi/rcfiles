"""Behavioral tests for Pi's session-scoped approved-worktree registry."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import _clean_env

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
REGISTRY = (
    MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "worktree-approval-registry.mjs"
)
CHILD_ENV = (
    MANAGED_ROOT / "dot_pi" / "agent" / "extensions" / "subagent" / "child-env.mjs"
)

RUNNER = r"""
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [registryPath, childEnvPath] = process.argv.slice(1);
const registry = await import(pathToFileURL(registryPath).href);
const child = await import(pathToFileURL(childEnvPath).href);
const root = mkdtempSync(join(tmpdir(), "pi-worktree-registry-"));
const worktree = join(root, "worker");
const prunableWorktree = join(root, "prunable");
const git = (...args) => execFileSync("git", ["-C", root, ...args], { encoding: "utf8" });
git("init", "-q");
git("config", "user.email", "test@example.invalid");
git("config", "user.name", "test");
execFileSync("git", ["-C", root, "commit", "--allow-empty", "-qm", "initial"]);
execFileSync("git", ["-C", root, "worktree", "add", "-qb", "worker", worktree]);
execFileSync("git", ["-C", root, "worktree", "add", "-qb", "prunable", prunableWorktree]);
rmSync(prunableWorktree, { recursive: true, force: true });
const validWithUnrelatedPrunable = registry.validateWorktree(root, worktree);
const requestedPrunableRejected = registry.validateWorktree(root, prunableWorktree);
const sessionId = "session";
const started = registry.beginWorktreeStart({ sessionId, repoRoot: root, toolCallId: "start-1" });
const startWhileStartPending = registry.beginWorktreeStart({ sessionId, repoRoot: root, toolCallId: "start-conflict" });
const stopWhileStartPending = registry.beginWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop-conflict" });
const stale = registry.finishWorktreeStart({ sessionId, repoRoot: root, worktreeRoot: worktree, toolCallId: "stale", succeeded: true });
const approved = registry.finishWorktreeStart({ sessionId, repoRoot: root, worktreeRoot: worktree, toolCallId: "start-1", succeeded: true });
const lease = registry.acquireWorktreeLease({ sessionId, repoRoot: root, cwd: worktree });
const competingLease = registry.acquireWorktreeLease({ sessionId, repoRoot: root, cwd: worktree });
const stopWhileLeased = registry.beginWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop-1" });
git("worktree", "remove", "--force", worktree);
const invalidated = registry.resolveApprovedWorktree({ sessionId, repoRoot: root });
const leasesSurviveInvalidation = registry.worktreeHasLeases({ sessionId, repoRoot: root });
const startWhileInvalidLeased = registry.beginWorktreeStart({ sessionId, repoRoot: root, toolCallId: "start-invalid" });
const stopWhileInvalidLeased = registry.beginWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop-invalid" });
registry.releaseWorktreeLease({ sessionId, repoRoot: root, generation: lease.lease.generation, leaseId: lease.lease.leaseId });
git("worktree", "add", worktree, "worker");
const resolvedAfterTopologyRestored = registry.resolveApprovedWorktree({ sessionId, repoRoot: root });
const stopStarted = registry.beginWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop-2" });
const startWhileStopPending = registry.beginWorktreeStart({ sessionId, repoRoot: root, toolCallId: "start-during-stop" });
const stopWhileStopPending = registry.beginWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop-conflict-2" });
const failedStop = registry.finishWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop-2", succeeded: false });
const preservedAfterFailedStop = registry.resolveApprovedWorktree({ sessionId, repoRoot: root });
const startedAgain = registry.beginWorktreeStart({ sessionId, repoRoot: root, toolCallId: "start-2" });
const staleOldResult = registry.finishWorktreeStart({ sessionId, repoRoot: root, worktreeRoot: worktree, toolCallId: "start-1", succeeded: true });
const reapproved = registry.finishWorktreeStart({ sessionId, repoRoot: root, worktreeRoot: worktree, toolCallId: "start-2", succeeded: true });
const noApprovalSession = "no-approval";
const noApprovalStop = registry.beginWorktreeStop({ sessionId: noApprovalSession, repoRoot: root, toolCallId: "stop-no-approval" });
const startWhileNoApprovalStop = registry.beginWorktreeStart({ sessionId: noApprovalSession, repoRoot: root, toolCallId: "start-no-approval" });
const canceledNoApprovalStop = registry.cancelWorktreeLifecycle({ sessionId: noApprovalSession, repoRoot: root, toolCallId: "stop-no-approval" });
const startAfterNoApprovalCancel = registry.beginWorktreeStart({ sessionId: noApprovalSession, repoRoot: root, toolCallId: "start-after-cancel" });
const canceledPendingStart = registry.cancelWorktreeLifecycle({ sessionId: noApprovalSession, repoRoot: root, toolCallId: "start-after-cancel" });
const primary = registry.validateWorktree(root, root);
const environment = child.childEnvironment({ KEEP: "value", PI_WORKTREE_ROOT: root }, { execution: "worktree-write", approval: reapproved.approval });
console.log(JSON.stringify({ validWithUnrelatedPrunable: validWithUnrelatedPrunable.ok, requestedPrunableRejected: requestedPrunableRejected.ok, started: started.ok, startWhileStartPending: startWhileStartPending.ok, stopWhileStartPending: stopWhileStartPending.ok, stale: stale.ok, approved: approved.ok, lease: lease.ok, competingLease: competingLease.ok, stopWhileLeased: stopWhileLeased.ok, invalidated: invalidated.ok, leasesSurviveInvalidation, startWhileInvalidLeased: startWhileInvalidLeased.ok, stopWhileInvalidLeased: stopWhileInvalidLeased.ok, resolvedAfterTopologyRestored: resolvedAfterTopologyRestored.ok, stopStarted: stopStarted.ok, startWhileStopPending: startWhileStopPending.ok, stopWhileStopPending: stopWhileStopPending.ok, failedStop: failedStop.ok, preservedAfterFailedStop: preservedAfterFailedStop.ok, startedAgain: startedAgain.ok, staleOldResult: staleOldResult.ok, reapproved: reapproved.ok, noApprovalStop: noApprovalStop.ok, startWhileNoApprovalStop: startWhileNoApprovalStop.ok, canceledNoApprovalStop: canceledNoApprovalStop.ok, startAfterNoApprovalCancel: startAfterNoApprovalCancel.ok, canceledPendingStart: canceledPendingStart.ok, primary: primary.ok, environment }));
"""


def test_registry_rejects_stale_results_and_preserves_on_failed_stop() -> None:
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            RUNNER,
            str(REGISTRY),
            str(CHILD_ENV),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    outcome = json.loads(result.stdout)
    assert outcome == {
        "validWithUnrelatedPrunable": True,
        "requestedPrunableRejected": False,
        "started": True,
        "startWhileStartPending": False,
        "stopWhileStartPending": False,
        "stale": False,
        "approved": True,
        "lease": True,
        "competingLease": False,
        "stopWhileLeased": False,
        "invalidated": False,
        "leasesSurviveInvalidation": True,
        "startWhileInvalidLeased": False,
        "stopWhileInvalidLeased": False,
        "resolvedAfterTopologyRestored": True,
        "stopStarted": True,
        "startWhileStopPending": False,
        "stopWhileStopPending": False,
        "failedStop": False,
        "preservedAfterFailedStop": True,
        "startedAgain": True,
        "staleOldResult": False,
        "reapproved": True,
        "noApprovalStop": True,
        "startWhileNoApprovalStop": False,
        "canceledNoApprovalStop": True,
        "startAfterNoApprovalCancel": True,
        "canceledPendingStart": True,
        "primary": False,
        "environment": {
            "KEEP": "value",
            "PI_SUBAGENT": "1",
            "PI_SUBAGENT_EXECUTION": "worktree-write",
            "PI_WORKTREE_ROOT": outcome["environment"]["PI_WORKTREE_ROOT"],
            "PI_WORKTREE_REPO_ROOT": outcome["environment"]["PI_WORKTREE_REPO_ROOT"],
            "PI_WORKTREE_GENERATION": "2",
        },
    }
    assert Path(outcome["environment"]["PI_WORKTREE_ROOT"]).name == "worker"
