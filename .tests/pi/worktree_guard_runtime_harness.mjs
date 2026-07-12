#!/usr/bin/env node
/** Runtime tests for the managed worktree guard's supported boundary. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const [extensionPath, packageDir] = process.argv.slice(2);
const require = createRequire(pathToFileURL(join(packageDir, "package.json")));
const createJiti = require("jiti");
const nodeModules = join(packageDir, "node_modules");
const jiti = createJiti(import.meta.url, {
	alias: {
		"@earendil-works/pi-coding-agent": join(packageDir, "dist", "index.js"),
		"@earendil-works/pi-tui": join(nodeModules, "@earendil-works", "pi-tui", "dist", "index.js"),
		typebox: join(nodeModules, "typebox", "build", "index.mjs"),
	},
});
const { default: worktreeGuard } = await jiti.import(resolve(extensionPath));

function fixture() {
	const root = mkdtempSync(join(tmpdir(), "pi-worktree-guard-"));
	const worker = join(root, "worker");
	const git = (...args) => execFileSync("git", ["-C", root, ...args], { encoding: "utf8" });
	git("init", "-q");
	git("config", "user.email", "test@example.invalid");
	git("config", "user.name", "test");
	git("commit", "--allow-empty", "-qm", "initial");
	git("worktree", "add", "-qb", "worker", worker);
	return { root, worker };
}

function harness(cwd, sessionId = "session", { isGit = true } = {}) {
	const events = new Map();
	const statuses = [];
	let gitProbes = 0;
	const pi = {
		exec: async () => {
			gitProbes += 1;
			return isGit ? { code: 0, stdout: `${cwd}\n` } : { code: 1, stdout: "" };
		},
		on: (name, handler) => events.set(name, handler),
	};
	const ctx = {
		cwd,
		sessionManager: { getSessionId: () => sessionId },
		ui: { notify() {}, setStatus: (key, value) => statuses.push({ key, value }), theme: { fg: (_color, text) => text } },
	};
	worktreeGuard(pi);
	return { events, ctx, gitProbes: () => gitProbes, statuses };
}

async function call(events, ctx, toolName, input, toolCallId = toolName) {
	return events.get("tool_call")({ toolName, input, toolCallId }, ctx);
}

async function testRootBlocksBeforeApproval() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root, worker } = fixture();
		const { events, ctx } = harness(root);
		await events.get("session_start")({}, ctx);
		assert.match((await call(events, ctx, "bash", { command: "echo x > output" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "printf x | tee output" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "git -C . commit -m test" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "echo read-only\nrm -f output" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "echo \"$(rm -f output)\"" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "echo `rm -f output`" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "env SAFE=1 git commit --allow-empty -m test" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "env -i SAFE=1 git commit --allow-empty -m test" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "sudo -u root env SAFE=1 git commit --allow-empty -m test" })).reason, /require/);
		assert.match((await call(events, ctx, "bash", { command: "command env --unset SAFE git commit --allow-empty -m test" })).reason, /require/);
		assert.match((await call(events, ctx, "write", { path: ".pi/../README.md" })).reason, /require/);
		assert.equal(await call(events, ctx, "bash", { command: "printf '>'" }), undefined);
		assert.equal(await call(events, ctx, "bash", { command: "printf 'literal ` backtick'" }), undefined);

		assert.equal(await call(events, ctx, "worktree_start", {}, "start-1"), undefined);
		await events.get("tool_result")({ toolName: "worktree_start", toolCallId: "start-1", isError: false, details: { piWorktree: { mode: "active", repoRoot: root, worktreeRoot: worker } } }, ctx);
		assert.equal(await call(events, ctx, "bash", { command: "git status --short" }), undefined);
		assert.equal(await call(events, ctx, "bash", { command: "git commit --allow-empty -m ok" }), undefined);
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testLifecyclePendingRecovery() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root, worker } = fixture();
		const { events, ctx, statuses } = harness(root, "lifecycle-recovery");
		await events.get("session_start")({}, ctx);
		assert.deepEqual(statuses.at(-1), { key: "worktree-guard", value: "🔒 worktree required" });

		assert.equal(await call(events, ctx, "worktree_stop", {}, "stop-no-approval"), undefined);
		const startWhileNoApprovalStop = await call(events, ctx, "worktree_start", {}, "start-during-no-approval-stop");
		assert.match(startWhileNoApprovalStop.reason, /lifecycle operation is pending/);
		const statusesBeforeNoApprovalStopRecovery = statuses.length;
		await events.get("tool_execution_end")({ toolName: "worktree_stop", toolCallId: "stop-no-approval", result: {}, isError: true }, ctx);
		assert.equal(statuses.length, statusesBeforeNoApprovalStopRecovery + 1);
		assert.deepEqual(statuses.at(-1), { key: "worktree-guard", value: "🔒 worktree required" });

		assert.equal(await call(events, ctx, "worktree_start", {}, "start-canceled"), undefined);
		const statusesBeforeStartRecovery = statuses.length;
		await events.get("tool_execution_end")({ toolName: "worktree_start", toolCallId: "start-canceled", result: {}, isError: true }, ctx);
		assert.equal(statuses.length, statusesBeforeStartRecovery + 1);
		assert.deepEqual(statuses.at(-1), { key: "worktree-guard", value: "🔒 worktree required" });
		await events.get("tool_result")({ toolName: "worktree_start", toolCallId: "start-canceled", isError: false, details: { piWorktree: { mode: "active", repoRoot: root, worktreeRoot: worker } } }, ctx);
		assert.match((await call(events, ctx, "write", { path: "blocked", content: "blocked" })).reason, /require/);

		assert.equal(await call(events, ctx, "worktree_start", {}, "start-active"), undefined);
		await events.get("tool_result")({ toolName: "worktree_start", toolCallId: "start-active", isError: false, details: { piWorktree: { mode: "active", repoRoot: root, worktreeRoot: worker } } }, ctx);
		assert.deepEqual(statuses.at(-1), { key: "worktree-guard", value: "🌿 worktree approved" });
		await events.get("tool_execution_end")({ toolName: "worktree_start", toolCallId: "start-active", result: {}, isError: false }, ctx);

		assert.equal(await call(events, ctx, "worktree_start", {}, "start-rejected"), undefined);
		await events.get("tool_result")({ toolName: "worktree_start", toolCallId: "start-rejected", isError: true, details: {} }, ctx);
		assert.deepEqual(statuses.at(-1), { key: "worktree-guard", value: "🔒 worktree required" });
		assert.match((await call(events, ctx, "write", { path: "blocked-after-rejected-start", content: "blocked" })).reason, /require/);
		await events.get("tool_execution_end")({ toolName: "worktree_start", toolCallId: "start-rejected", result: {}, isError: true }, ctx);

		assert.equal(await call(events, ctx, "worktree_start", {}, "start-active-after-rejection"), undefined);
		await events.get("tool_result")({ toolName: "worktree_start", toolCallId: "start-active-after-rejection", isError: false, details: { piWorktree: { mode: "active", repoRoot: root, worktreeRoot: worker } } }, ctx);
		assert.deepEqual(statuses.at(-1), { key: "worktree-guard", value: "🌿 worktree approved" });
		await events.get("tool_execution_end")({ toolName: "worktree_start", toolCallId: "start-active-after-rejection", result: {}, isError: false }, ctx);

		assert.equal(await call(events, ctx, "worktree_stop", {}, "stop-no-result"), undefined);
		const startWhileStopPending = await call(events, ctx, "worktree_start", {}, "start-during-stop");
		assert.match(startWhileStopPending.reason, /lifecycle operation is pending/);
		const statusesBeforeCanceledStop = statuses.length;
		await events.get("tool_execution_end")({ toolName: "worktree_stop", toolCallId: "stop-no-result", result: {}, isError: true }, ctx);
		assert.equal(statuses.length, statusesBeforeCanceledStop + 1);
		assert.deepEqual(statuses.at(-1), { key: "worktree-guard", value: "🔒 worktree required" });
		assert.match((await call(events, ctx, "write", { path: "blocked", content: "blocked" })).reason, /require/);

		assert.equal(await call(events, ctx, "worktree_start", {}, "restart-after-canceled-stop"), undefined);
		await events.get("tool_result")({ toolName: "worktree_start", toolCallId: "restart-after-canceled-stop", isError: false, details: { piWorktree: { mode: "active", repoRoot: root, worktreeRoot: worker } } }, ctx);
		await events.get("tool_execution_end")({ toolName: "worktree_start", toolCallId: "restart-after-canceled-stop", result: {}, isError: false }, ctx);
		assert.equal(await call(events, ctx, "write", { path: "allowed", content: "allowed" }), undefined);
		await events.get("tool_result")({ toolName: "worktree_stop", toolCallId: "stop-no-result", isError: false, details: { piWorktree: { mode: "inactive" } } }, ctx);
		assert.equal(await call(events, ctx, "write", { path: "still-allowed", content: "allowed" }), undefined);

		assert.equal(await call(events, ctx, "worktree_stop", {}, "stop-completed"), undefined);
		await events.get("tool_result")({ toolName: "worktree_stop", toolCallId: "stop-completed", isError: false, details: { piWorktree: { mode: "inactive" } } }, ctx);
		assert.deepEqual(statuses.at(-1), { key: "worktree-guard", value: "🔒 worktree required" });
		await events.get("tool_execution_end")({ toolName: "worktree_stop", toolCallId: "stop-completed", result: {}, isError: false }, ctx);
		assert.match((await call(events, ctx, "write", { path: "blocked-after-stop", content: "blocked" })).reason, /require/);

		assert.equal(await call(events, ctx, "worktree_start", {}, "start-pending-shutdown"), undefined);
		await events.get("session_shutdown")({}, ctx);
		assert.equal(await call(events, ctx, "worktree_start", {}, "start-after-shutdown"), undefined);
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testChildPolicy() {
	const { root, worker } = fixture();
	const original = { ...process.env };
	try {
		process.env.PI_SUBAGENT = "1";
		process.env.PI_SUBAGENT_EXECUTION = "worktree-write";
		process.env.PI_WORKTREE_ROOT = worker;
		process.env.PI_WORKTREE_REPO_ROOT = root;
		process.env.PI_WORKTREE_GENERATION = "1";
		let current = harness(worker, "child-write");
		await current.events.get("session_start")({}, current.ctx);
		assert.equal(await call(current.events, current.ctx, "bash", { command: "git commit --allow-empty -m child" }), undefined);
		// A validated initial cwd routes a cooperative worker; it does not contain
		// its later direct Git/Bash path selection.
		assert.equal(await call(current.events, current.ctx, "bash", { command: "git -C ../ commit --allow-empty -m direct" }), undefined);
		assert.equal(await call(current.events, current.ctx, "bash", { command: "cd ../ && touch direct" }), undefined);
		assert.equal(await call(current.events, current.ctx, "write", { path: "../direct", content: "direct" }), undefined);
		assert.match((await call(current.events, current.ctx, "worktree_start", {})).reason, /root-owned/);

		process.env.PI_SUBAGENT_EXECUTION = "read-only";
		delete process.env.PI_WORKTREE_ROOT;
		delete process.env.PI_WORKTREE_REPO_ROOT;
		delete process.env.PI_WORKTREE_GENERATION;
		current = harness(root, "child-read");
		await current.events.get("session_start")({}, current.ctx);
		assert.match((await call(current.events, current.ctx, "bash", { command: "git commit --allow-empty -m denied" })).reason, /read-only/);
		assert.match((await call(current.events, current.ctx, "bash", { command: "echo harmless\nrm -f denied" })).reason, /read-only/);
		assert.match((await call(current.events, current.ctx, "bash", { command: "sudo -u root git commit --allow-empty -m denied" })).reason, /read-only/);
		assert.match((await call(current.events, current.ctx, "write", { path: "blocked" })).reason, /read-only/);
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testNonGitChildrenFailClosed() {
	const original = { ...process.env };
	const plainDirectory = mkdtempSync(join(tmpdir(), "pi-worktree-guard-plain-"));
	try {
		process.env.PI_SUBAGENT = "1";
		process.env.PI_SUBAGENT_EXECUTION = "read-only";
		for (const key of ["PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		let current = harness(plainDirectory, "child-read-non-git", { isGit: false });
		await current.events.get("session_start")({}, current.ctx);
		assert.equal(current.gitProbes(), 0, "child policy must initialize before the root Git probe");
		assert.match((await call(current.events, current.ctx, "bash", { command: "touch blocked" })).reason, /read-only/);
		assert.match((await call(current.events, current.ctx, "write", { path: "blocked" })).reason, /read-only/);

		delete process.env.PI_SUBAGENT_EXECUTION;
		current = harness(plainDirectory, "child-unmarked-non-git", { isGit: false });
		await current.events.get("session_start")({}, current.ctx);
		assert.equal(current.gitProbes(), 0, "unmarked children must not depend on a Git probe to be guarded");
		assert.match((await call(current.events, current.ctx, "bash", { command: "touch blocked" })).reason, /lacks a validated/);

		process.env.PI_SUBAGENT_EXECUTION = "worktree-write";
		process.env.PI_WORKTREE_ROOT = plainDirectory;
		process.env.PI_WORKTREE_REPO_ROOT = plainDirectory;
		process.env.PI_WORKTREE_GENERATION = "invalid";
		current = harness(plainDirectory, "child-invalid-write-non-git", { isGit: false });
		await current.events.get("session_start")({}, current.ctx);
		assert.equal(current.gitProbes(), 0, "invalid write metadata must fail closed before any root probe");
		assert.match((await call(current.events, current.ctx, "edit", { path: "blocked" })).reason, /lacks a validated/);
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

await testRootBlocksBeforeApproval();
await testLifecyclePendingRecovery();
await testChildPolicy();
await testNonGitChildrenFailClosed();
console.log("ok");
