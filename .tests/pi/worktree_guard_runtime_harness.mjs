#!/usr/bin/env node
/** Runtime tests for the managed worktree guard's supported boundary. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { appendFileSync, chmodSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const SESSION_START_CHILD_TIMEOUT_MS = 15_000;
const MAX_PARENT_SESSION_BYTES = 64 * 1024 * 1024;
const [extensionPath, registryPath, packageDir, command, encodedResume] = process.argv.slice(2);
if (!extensionPath || !registryPath || !packageDir) {
	throw new Error("Usage: worktree_guard_runtime_harness.mjs <extension-path> <registry-path> <pi-package-dir>");
}
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
const registry = await import(pathToFileURL(resolve(registryPath)).href);
const { RpcClient } = await import(pathToFileURL(join(packageDir, "dist", "modes", "rpc", "rpc-client.js")).href);

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

function harness(cwd, sessionId = "session", { isGit = true, branch = [], header = undefined, directMcpTools = [] } = {}) {
	const handlers = new Map();
	const events = {
		get(name) {
			return async (event, ctx) => {
				let result;
				for (const handler of handlers.get(name) ?? []) {
					const next = await handler(event, ctx);
					if (next !== undefined) result = next;
				}
				return result;
			};
		},
	};
	const statuses = [];
	let gitProbes = 0;
	const pi = {
		exec: async () => {
			gitProbes += 1;
			return isGit ? { code: 0, stdout: `${cwd}\n` } : { code: 1, stdout: "" };
		},
		getAllTools: () => [toolInfo("mcp", MCP_ADAPTER_SOURCE_INFO), ...directMcpTools],
		on: (name, handler) => {
			const eventHandlers = handlers.get(name) ?? [];
			eventHandlers.push(handler);
			handlers.set(name, eventHandlers);
		},
	};
	const ctx = {
		cwd,
		sessionManager: { getSessionId: () => sessionId, getBranch: () => branch, getHeader: () => header },
		ui: { notify() {}, setStatus: (key, value) => statuses.push({ key, value }), theme: { fg: (_color, text) => text } },
	};
	worktreeGuard(pi);
	return { events, ctx, gitProbes: () => gitProbes, statuses };
}

async function call(events, ctx, toolName, input, toolCallId = toolName) {
	return events.get("tool_call")({ toolName, input, toolCallId }, ctx);
}

const MUTATING_MCP_TOOLS = [
	"p4_mcp_modify_files",
	"atlassian_rovo_createJiraIssue",
	"atlassian_rovo_transitionJiraIssue",
];
const READONLY_MCP_TOOLS = ["p4_mcp_query_files", "getJiraIssue", "searchJiraIssuesUsingJql"];
const DIRECT_MUTATING_MCP_TOOLS = ["p4_mcp_modify_files", "atlassian_rovo_updateJiraIssue"];
const DIRECT_READONLY_MCP_TOOLS = ["atlassian_rovo_getProjectSettings"];
const MCP_ADAPTER_SOURCE_INFO = {
	path: "/agent/npm/node_modules/pi-mcp-adapter/index.ts",
	source: "local",
	scope: "temporary",
	origin: "top-level",
	baseDir: "/agent/npm/node_modules/pi-mcp-adapter",
};
const OTHER_EXTENSION_SOURCE_INFO = {
	path: "/agent/extensions/other.ts",
	source: "local",
	scope: "temporary",
	origin: "top-level",
	baseDir: "/agent/extensions",
};

function toolInfo(name, sourceInfo) {
	return { name, description: "", parameters: {}, promptGuidelines: undefined, sourceInfo };
}

const DIRECT_MCP_TOOL_DEFINITIONS = [
	...DIRECT_MUTATING_MCP_TOOLS.map((name) => toolInfo(name, MCP_ADAPTER_SOURCE_INFO)),
	...DIRECT_READONLY_MCP_TOOLS.map((name) => toolInfo(name, MCP_ADAPTER_SOURCE_INFO)),
];
const MCP_GATEWAY_CALLS = [
	{ connect: "p4-mcp" },
	{ describe: "p4_mcp_query_files" },
	{ search: "Jira" },
	{ server: "atlassian-rovo" },
	{ action: "ui-messages" },
	{ action: "auth-start" },
	{ action: "auth-complete" },
	{ action: "auth-start", tool: "updateJiraIssue" },
	{ connect: "p4-mcp", tool: "updateJiraIssue" },
	{ describe: "getJiraIssue", tool: "updateJiraIssue" },
	{ search: "Jira", tool: "updateJiraIssue" },
	{ server: "atlassian-rovo", tool: "updateJiraIssue" },
	{},
];

async function assertMcpPolicy(current, blockMutations = false, expectedReason) {
	for (const tool of MUTATING_MCP_TOOLS) {
		const result = await call(current.events, current.ctx, "mcp", { tool }, `mcp-mutation-${tool}`);
		if (blockMutations) {
			assert.equal(result?.block, true);
			assert.match(result?.reason ?? "", expectedReason);
		} else assert.equal(result, undefined);
	}
	for (const tool of READONLY_MCP_TOOLS) {
		assert.equal(await call(current.events, current.ctx, "mcp", { tool }, `mcp-read-${tool}`), undefined);
	}
	for (const [index, input] of MCP_GATEWAY_CALLS.entries()) {
		assert.equal(await call(current.events, current.ctx, "mcp", input, `mcp-gateway-${index}`), undefined);
	}
}

async function assertDirectMcpPolicy(current, blockMutations = false, expectedReason) {
	for (const toolName of DIRECT_MUTATING_MCP_TOOLS) {
		const result = await call(current.events, current.ctx, toolName, {}, `direct-mcp-mutation-${toolName}`);
		if (blockMutations) {
			assert.equal(result?.block, true);
			assert.match(result?.reason ?? "", expectedReason);
		} else assert.equal(result, undefined);
	}
	for (const toolName of DIRECT_READONLY_MCP_TOOLS) {
		assert.equal(await call(current.events, current.ctx, toolName, {}, `direct-mcp-read-${toolName}`), undefined);
	}
}

let nextEntryId = 0;
let nextSessionId = 0;

function sessionEntryId() {
	nextEntryId += 1;
	return nextEntryId.toString(16).padStart(8, "0");
}

function sessionId() {
	nextSessionId += 1;
	return `00000000-0000-4000-8000-${nextSessionId.toString().padStart(12, "0")}`;
}

function worktreeStateEntry(state, toolName = "worktree_start", { id = sessionEntryId(), parentId = null } = {}) {
	return {
		type: "message",
		id,
		parentId,
		timestamp: "2024-12-03T14:00:01.000Z",
		message: { role: "toolResult", toolName, details: { piWorktree: state } },
	};
}

function writeSessionFixture(root, name, { entries = [], parentSession } = {}) {
	const file = join(root, `${name}.jsonl`);
	const header = {
		type: "session",
		version: 3,
		id: sessionId(),
		timestamp: "2024-12-03T14:00:00.000Z",
		cwd: root,
		...(parentSession === undefined ? {} : { parentSession }),
	};
	writeFileSync(file, [header, ...entries].map((entry) => JSON.stringify(entry)).join("\n") + "\n");
	return file;
}

function readSessionFixture(file) {
	const [header, ...branch] = readFileSync(file, "utf8")
		.trim()
		.split("\n")
		.map((line) => JSON.parse(line));
	if (header?.type !== "session") throw new Error(`Invalid session fixture: ${file}`);
	return { header, branch };
}

function resumableWorktreeState(root, worker, mode = "active") {
	return {
		mode,
		repoRoot: root,
		worktreeRoot: worker,
		branch: execFileSync("git", ["-C", worker, "rev-parse", "--abbrev-ref", "HEAD"], { encoding: "utf8" }).trim(),
	};
}

function resetApprovalRegistry() {
	delete globalThis[Symbol.for("dfrank.pi.worktree-approval-registry")];
}

async function approveFromWorktreeStart(current, root, worker, toolCallId) {
	const state = resumableWorktreeState(root, worker);
	assert.equal(await call(current.events, current.ctx, "worktree_start", {}, toolCallId), undefined);
	await current.events.get("tool_result")({ toolName: "worktree_start", toolCallId, isError: false, details: { piWorktree: state } }, current.ctx);
	return state;
}

async function assertResumedWorktree({ root, worker, sessionId, branch, header, sessionFile, reason, shouldRestore }) {
	const before = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
	assert.equal(before.ok, false);
	assert.equal(before.noApproval, true);

	const session = sessionFile ? readSessionFixture(sessionFile) : { branch, header };
	const current = harness(root, sessionId, session);
	await current.events.get("session_start")({ reason }, current.ctx);
	const mutation = await call(current.events, current.ctx, "write", { path: "resumed", content: "resumed" }, `${sessionId}-write`);
	const resumed = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
	try {
		if (!shouldRestore) {
			assert.match(mutation?.reason ?? "", /require/);
			assert.equal(resumed.ok, false, resumed.reason);
			assert.equal(resumed.noApproval, true);
			return;
		}
		assert.equal(mutation, undefined);
		assert.equal(resumed.ok, true, resumed.reason);
		assert.equal(resumed.approval.worktreeRoot, realpathSync(worker));
		assert.equal(resumed.approval.generation, 1);
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

function resumeInFreshProcess(resume) {
	const environment = { ...process.env };
	for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete environment[key];
	const output = execFileSync(
		process.execPath,
		[
			process.argv[1],
			extensionPath,
			registryPath,
			packageDir,
			"--resume",
			Buffer.from(JSON.stringify(resume)).toString("base64url"),
		],
		{ encoding: "utf8", env: environment, timeout: SESSION_START_CHILD_TIMEOUT_MS, killSignal: "SIGKILL" },
	);
	assert.equal(output, "resumed\n");
}

async function testPiCloneEmitsForkSessionStartReason() {
	const { root } = fixture();
	const agentDir = join(root, "agent");
	const sessionDir = join(root, "sessions");
	const reasonsFile = join(root, "session-start-reasons");
	const sessionFile = writeSessionFixture(root, "clone-source", {
		entries: [
			{
				type: "message",
				id: sessionEntryId(),
				parentId: null,
				timestamp: "2024-12-03T14:00:01.000Z",
				message: { role: "user", content: "clone probe", timestamp: 1 },
			},
		],
	});
	const extension = join(root, "capture-session-start.mjs");
	writeFileSync(
		extension,
		`import { appendFileSync } from "node:fs";
export default function (pi) {
\tpi.on("session_start", async (event) => appendFileSync(process.env.PI_TEST_SESSION_START_REASONS, event.reason + "\\n"));
}
`,
	);
	const environment = { ...process.env, PI_CODING_AGENT_DIR: agentDir, PI_OFFLINE: "1", PI_TEST_SESSION_START_REASONS: reasonsFile };
	for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete environment[key];
	const rpc = new RpcClient({
		cliPath: join(packageDir, "dist", "cli.js"),
		cwd: root,
		env: environment,
		args: [
			"--session-dir",
			sessionDir,
			"--session",
			sessionFile,
			"--no-extensions",
			"--extension",
			extension,
			"--no-context-files",
			"--no-skills",
			"--no-prompt-templates",
			"--no-themes",
			"--offline",
		],
	});
	await rpc.start();
	try {
		assert.equal((await rpc.clone()).cancelled, false);
		assert.equal(readFileSync(reasonsFile, "utf8").trim().split("\n").at(-1), "fork");
	} finally {
		await rpc.stop();
	}
}

async function testResumeHydratesApprovedWorktree() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		for (const reason of ["resume", "reload"]) {
			for (const mode of ["active", "conflict"]) {
				const { root, worker } = fixture();
				const sessionId = `${reason}-${mode}`;
				const first = harness(root, sessionId);
				await first.events.get("session_start")({ reason: "startup" }, first.ctx);
				const state = await approveFromWorktreeStart(first, root, worker, `${sessionId}-start`);
				const initial = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
				assert.equal(initial.ok, true, initial.reason);

				const sessionFile = writeSessionFixture(root, `${sessionId}-${mode}`, {
					entries: [worktreeStateEntry({ ...state, mode })],
				});
				resumeInFreshProcess({
					root,
					worker,
					sessionId,
					sessionFile,
					reason,
					shouldRestore: true,
				});
				registry.revokeWorktree({ sessionId, repoRoot: root });
			}
		}

		const cases = [
			["no detail", async () => []],
			["malformed checkpoint after valid start", async ({ root, worker }) => [
				worktreeStateEntry(resumableWorktreeState(root, worker)),
				{ type: "message", id: sessionEntryId(), message: { role: "toolResult", toolName: "worktree_start", details: {} } },
			]],
			["inactive", async ({ root, worker }) => [worktreeStateEntry(resumableWorktreeState(root, worker, "inactive"))]],
			["active stop after valid start", async ({ root, worker }) => [
				worktreeStateEntry(resumableWorktreeState(root, worker)),
				worktreeStateEntry(resumableWorktreeState(root, worker), "worktree_stop"),
			]],
			["pending", async ({ root, worker }) => [worktreeStateEntry(resumableWorktreeState(root, worker, "pending"))]],
			["missing worktree root", async ({ root }) => [worktreeStateEntry({ mode: "active", repoRoot: root, branch: "worker" })]],
			["missing branch", async ({ root, worker }) => [worktreeStateEntry({ mode: "active", repoRoot: root, worktreeRoot: worker })]],
			["deleted root", async ({ root, worker }) => {
				const state = resumableWorktreeState(root, worker);
				execFileSync("git", ["-C", root, "worktree", "remove", "--force", worker]);
				return [worktreeStateEntry(state)];
			}],
			["primary root", async ({ root }) => [worktreeStateEntry(resumableWorktreeState(root, root))]],
			["foreign worktree", async ({ root }) => {
				const foreign = fixture();
				return [worktreeStateEntry(resumableWorktreeState(root, foreign.worker))];
			}],
			["foreign repository", async () => {
				const foreign = fixture();
				return [worktreeStateEntry(resumableWorktreeState(foreign.root, foreign.worker))];
			}],
			["relative worktree root", async ({ root, worker }) => [worktreeStateEntry({ ...resumableWorktreeState(root, worker), worktreeRoot: "worker" })]],
			["malformed state", async () => [{ type: "message", message: { role: "toolResult", toolName: "worktree_start", details: { piWorktree: "invalid" } } }]],
		];
		for (const [name, makeEntries] of cases) {
			const { root, worker } = fixture();
			const sessionId = `resume-rejected-${name.replaceAll(" ", "-")}`;
			const entries = await makeEntries({ root, worker });
			resetApprovalRegistry();
			const current = harness(root, sessionId, { branch: entries });
			await current.events.get("session_start")({ reason: "resume" }, current.ctx);
			const rejected = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
			assert.equal(rejected.ok, false, `${name}: ${rejected.reason}`);
			assert.equal(rejected.noApproval, true, name);
			registry.revokeWorktree({ sessionId, repoRoot: root });
		}
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testForkedOrClonedSessionsDoNotHydrateCopiedWorktreeState() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root, worker } = fixture();
		const sourceSessionId = "source-worktree-approval";
		const source = harness(root, sourceSessionId);
		await source.events.get("session_start")({ reason: "startup" }, source.ctx);
		const state = await approveFromWorktreeStart(source, root, worker, `${sourceSessionId}-start`);
		const approved = registry.resolveApprovedWorktree({ sessionId: sourceSessionId, repoRoot: root, cwd: worker });
		assert.equal(approved.ok, true, approved.reason);
		try {
			for (const [reason, sessionId] of [
				["fork", "forked-or-cloned-worktree-approval"],
				["new", "new-worktree-approval"],
				["startup", "fresh-worktree-approval"],
				[undefined, "undefined-reason-worktree-approval"],
				["future-reason", "future-reason-worktree-approval"],
			]) {
				resumeInFreshProcess({
					root,
					worker,
					sessionId,
					branch: [worktreeStateEntry(state)],
					reason,
					shouldRestore: false,
				});
			}
		} finally {
			registry.revokeWorktree({ sessionId: sourceSessionId, repoRoot: root });
		}
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testForkLineageRejectsInheritedApprovalAndAllowsNativeApproval() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		for (const reason of ["resume", "reload"]) {
			const { root, worker } = fixture();
			const state = resumableWorktreeState(root, worker);
			const inherited = worktreeStateEntry(state, "worktree_start");
			const parentSession = writeSessionFixture(root, `${reason}-parent`, { entries: [inherited] });
			const inheritedChild = writeSessionFixture(root, `${reason}-inherited-child`, {
				parentSession,
				entries: [{ ...inherited, parentId: null }],
			});
			resumeInFreshProcess({
				root,
				worker,
				sessionId: `${reason}-inherited-worktree-approval`,
				sessionFile: inheritedChild,
				reason,
				shouldRestore: false,
			});

			const ancestorSession = writeSessionFixture(root, `${reason}-ancestor`, { entries: [inherited] });
			const middleSession = writeSessionFixture(root, `${reason}-middle`, {
				parentSession: ancestorSession,
				entries: [{ ...inherited, parentId: null }],
			});
			const descendantSession = writeSessionFixture(root, `${reason}-descendant`, {
				parentSession: middleSession,
				entries: [{ ...inherited, parentId: null }],
			});
			resumeInFreshProcess({
				root,
				worker,
				sessionId: `${reason}-three-generation-inherited-worktree-approval`,
				sessionFile: descendantSession,
				reason,
				shouldRestore: false,
			});

			const native = worktreeStateEntry(state, "worktree_start", { parentId: inherited.id });
			const nativeChild = writeSessionFixture(root, `${reason}-native-child`, {
				parentSession,
				entries: [{ ...inherited, parentId: null }, native],
			});
			resumeInFreshProcess({
				root,
				worker,
				sessionId: `${reason}-native-worktree-approval`,
				sessionFile: nativeChild,
				reason,
				shouldRestore: true,
			});

			const observedAfterFork = worktreeStateEntry(state, "worktree_status", { parentId: inherited.id });
			assert.notEqual(observedAfterFork.id, inherited.id);
			assert.equal(readSessionFixture(parentSession).branch.some((entry) => entry.id === observedAfterFork.id), false);
			const observedChild = writeSessionFixture(root, `${reason}-observed-child`, {
				parentSession,
				entries: [{ ...inherited, parentId: null }, observedAfterFork],
			});
			resumeInFreshProcess({
				root,
				worker,
				sessionId: `${reason}-observed-worktree-approval`,
				sessionFile: observedChild,
				reason,
				shouldRestore: false,
			});
		}
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testForkLineageFailsClosedWhenParentCannotBeRead() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root, worker } = fixture();
		const missingParent = join(root, "missing-parent.jsonl");
		const nonRegularParent = join(root, "parent-directory");
		mkdirSync(nonRegularParent);
		const oversizedParent = writeSessionFixture(root, "oversized-parent");
		const whitespaceBlock = " ".repeat(1024 * 1024);
		for (let bytesWritten = 0; bytesWritten <= MAX_PARENT_SESSION_BYTES; bytesWritten += whitespaceBlock.length) {
			appendFileSync(oversizedParent, whitespaceBlock);
		}
		const corruptParent = join(root, "corrupt-parent.jsonl");
		writeFileSync(corruptParent, '{"type":"session"\n');
		const unreadableParent = writeSessionFixture(root, "unreadable-parent");
		chmodSync(unreadableParent, 0);
		const fifoParent = join(root, "fifo-parent.jsonl");
		execFileSync("mkfifo", [fifoParent]);
		for (const [name, parentSession] of [
			["missing", missingParent],
			["non-regular", nonRegularParent],
			["oversized", oversizedParent],
			["corrupt", corruptParent],
			["unreadable", unreadableParent],
			["fifo", fifoParent],
		]) {
			const child = writeSessionFixture(root, `${name}-parent-child`, {
				parentSession,
				entries: [worktreeStateEntry(resumableWorktreeState(root, worker), "worktree_start")],
			});
			resumeInFreshProcess({
				root,
				worker,
				sessionId: `${name}-parent-worktree-approval`,
				sessionFile: child,
				reason: "resume",
				shouldRestore: false,
			});
		}
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testResumeDoesNotRestorePastSuccessfulStop() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root, worker } = fixture();
		const sessionId = "resume-after-successful-stop";
		const first = harness(root, sessionId);
		await first.events.get("session_start")({ reason: "startup" }, first.ctx);
		const state = await approveFromWorktreeStart(first, root, worker, `${sessionId}-start`);

		resumeInFreshProcess({
			root,
			worker,
			sessionId,
			branch: [worktreeStateEntry(state), worktreeStateEntry({ mode: "inactive", repoRoot: root }, "worktree_stop")],
			reason: "resume",
			shouldRestore: false,
		});
		registry.revokeWorktree({ sessionId, repoRoot: root });
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testResumeOnlyUsesAllowlistedLifecycleCheckpoints() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root, worker } = fixture();
		const state = resumableWorktreeState(root, worker);
		const cases = [
			[
				"active status",
				[
					worktreeStateEntry(state, "worktree_start"),
					worktreeStateEntry(state, "worktree_status"),
				],
				true,
			],
			[
				"stopped status",
				[
					worktreeStateEntry(state, "worktree_start"),
					worktreeStateEntry({ mode: "inactive", repoRoot: root }, "worktree_stop"),
					worktreeStateEntry({ mode: "inactive", repoRoot: root }, "worktree_status"),
				],
				false,
			],
			["unknown tool cannot approve", [worktreeStateEntry(state, "arbitrary_unknown_tool")], false],
			[
				"unknown tool cannot supersede start",
				[
					worktreeStateEntry(state, "worktree_start"),
					worktreeStateEntry({ mode: "inactive", repoRoot: root }, "arbitrary_unknown_tool"),
				],
				true,
			],
		];
		for (const [name, branch, shouldRestore] of cases) {
			resumeInFreshProcess({
				root,
				worker,
				sessionId: `resume-lifecycle-checkpoint-${name.replaceAll(" ", "-")}`,
				branch,
				reason: "resume",
				shouldRestore,
			});
		}
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testResumeRejectsUnidentifiedWorktreeState() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root, worker } = fixture();
		const sessionId = "resume-rejects-unidentified-state";
		const first = harness(root, sessionId);
		await first.events.get("session_start")({ reason: "startup" }, first.ctx);
		const state = await approveFromWorktreeStart(first, root, worker, `${sessionId}-start`);

		resumeInFreshProcess({
			root,
			worker,
			sessionId,
			branch: [worktreeStateEntry(state), worktreeStateEntry({ mode: "inactive" }, "worktree_stop")],
			reason: "resume",
			shouldRestore: false,
		});
		registry.revokeWorktree({ sessionId, repoRoot: root });
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testResumeIgnoresLaterOtherRepositoryState() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root, worker } = fixture();
		const other = fixture();
		const sessionId = "resume-ignores-other-repository";
		const first = harness(root, sessionId);
		await first.events.get("session_start")({ reason: "startup" }, first.ctx);
		const state = await approveFromWorktreeStart(first, root, worker, `${sessionId}-start`);
		const otherInactive = resumableWorktreeState(other.root, other.worker, "inactive");
		const otherActive = resumableWorktreeState(other.root, other.worker);
		const histories = [
			[[worktreeStateEntry(state), worktreeStateEntry(otherInactive, "worktree_stop")], true],
			[
				[
					worktreeStateEntry(state),
					{ type: "message", message: { role: "toolResult", toolName: "read", details: {} } },
				],
				true,
			],
			[
				[
					worktreeStateEntry(state),
					worktreeStateEntry(otherInactive, "worktree_stop"),
					worktreeStateEntry({ ...state, mode: "inactive" }, "worktree_stop"),
					worktreeStateEntry(otherActive, "worktree_start"),
				],
				false,
			],
			[
				[
					worktreeStateEntry(state),
					worktreeStateEntry(otherInactive, "worktree_stop"),
					worktreeStateEntry(state, "worktree_start"),
					worktreeStateEntry(otherInactive, "worktree_stop"),
				],
				true,
			],
		];
		for (const [branch, shouldRestore] of histories) {
			resumeInFreshProcess({ root, worker, sessionId, branch, reason: "resume", shouldRestore });
		}
		registry.revokeWorktree({ sessionId, repoRoot: root });
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testResumeRejectsMismatchedWorktreeBranch() {
	const original = { ...process.env };
	try {
		for (const key of ["PI_SUBAGENT", "PI_SUBAGENT_EXECUTION", "PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];

		const siblingFixture = fixture();
		const sibling = join(siblingFixture.root, "sibling");
		execFileSync("git", ["-C", siblingFixture.root, "worktree", "add", "-qb", "sibling", sibling]);
		const siblingRecordedBranch = resumableWorktreeState(siblingFixture.root, siblingFixture.worker).branch;
		const siblingState = { ...resumableWorktreeState(siblingFixture.root, sibling), branch: siblingRecordedBranch };
		assert.notEqual(siblingState.branch, resumableWorktreeState(siblingFixture.root, sibling).branch);
		const validSibling = registry.validateWorktree(siblingFixture.root, sibling);
		assert.equal(validSibling.ok, true, validSibling.reason);
		resetApprovalRegistry();
		const siblingSession = "resume-wrong-sibling";
		const siblingGuard = harness(siblingFixture.root, siblingSession, { branch: [worktreeStateEntry(siblingState)] });
		await siblingGuard.events.get("session_start")({ reason: "resume" }, siblingGuard.ctx);
		assert.deepEqual(siblingGuard.statuses.at(-1), { key: "worktree-guard", value: "🔒 worktree required" });
		const siblingMutation = await call(siblingGuard.events, siblingGuard.ctx, "write", { path: "blocked", content: "blocked" });
		assert.match(siblingMutation.reason, /require/);
		const siblingRejected = registry.resolveApprovedWorktree({ sessionId: siblingSession, repoRoot: siblingFixture.root, cwd: sibling });
		assert.equal(siblingRejected.ok, false, siblingRejected.reason);
		assert.equal(siblingRejected.noApproval, true);
		registry.revokeWorktree({ sessionId: siblingSession, repoRoot: siblingFixture.root });

		const reusedFixture = fixture();
		const reusedState = resumableWorktreeState(reusedFixture.root, reusedFixture.worker);
		execFileSync("git", ["-C", reusedFixture.root, "worktree", "remove", "--force", reusedFixture.worker]);
		execFileSync("git", ["-C", reusedFixture.root, "worktree", "add", "-qb", "replacement", reusedFixture.worker]);
		assert.notEqual(reusedState.branch, resumableWorktreeState(reusedFixture.root, reusedFixture.worker).branch);
		const validReusedPath = registry.validateWorktree(reusedFixture.root, reusedFixture.worker);
		assert.equal(validReusedPath.ok, true, validReusedPath.reason);
		resetApprovalRegistry();
		const reusedSession = "resume-reused-path";
		const reusedGuard = harness(reusedFixture.root, reusedSession, { branch: [worktreeStateEntry(reusedState)] });
		await reusedGuard.events.get("session_start")({ reason: "resume" }, reusedGuard.ctx);
		assert.deepEqual(reusedGuard.statuses.at(-1), { key: "worktree-guard", value: "🔒 worktree required" });
		const reusedMutation = await call(reusedGuard.events, reusedGuard.ctx, "write", { path: "blocked", content: "blocked" });
		assert.match(reusedMutation.reason, /require/);
		const reusedRejected = registry.resolveApprovedWorktree({ sessionId: reusedSession, repoRoot: reusedFixture.root, cwd: reusedFixture.worker });
		assert.equal(reusedRejected.ok, false, reusedRejected.reason);
		assert.equal(reusedRejected.noApproval, true);
		registry.revokeWorktree({ sessionId: reusedSession, repoRoot: reusedFixture.root });
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testHydrationPreservesPendingAndLeasedState() {
	const { root, worker } = fixture();
	const sessionId = "preserve-hydration-state";
	const state = resumableWorktreeState(root, worker);
	resetApprovalRegistry();
	try {
		const started = registry.beginWorktreeStart({ sessionId, repoRoot: root, toolCallId: "start" });
		assert.equal(started.ok, true, started.reason);
		const duringPendingStart = registry.hydrateApprovedWorktree({ sessionId, repoRoot: root, ...state });
		assert.equal(duringPendingStart.ok, false);
		assert.match(duringPendingStart.reason, /lifecycle operation is pending/);
		const approved = registry.finishWorktreeStart({ sessionId, repoRoot: root, worktreeRoot: worker, toolCallId: "start", succeeded: true });
		assert.equal(approved.ok, true, approved.reason);
		assert.equal(approved.approval.generation, started.generation);

		const lease = registry.acquireWorktreeLease({ sessionId, repoRoot: root, cwd: worker });
		assert.equal(lease.ok, true, lease.reason);
		const duringLease = registry.hydrateApprovedWorktree({ sessionId, repoRoot: root, ...state });
		assert.equal(duringLease.ok, false);
		assert.match(duringLease.reason, /active worker holds the worktree lease/);
		assert.equal(registry.worktreeHasLeases({ sessionId, repoRoot: root }), true);
		const leasedApproval = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
		assert.equal(leasedApproval.ok, true, leasedApproval.reason);
		assert.equal(leasedApproval.approval.generation, lease.lease.generation);
		assert.equal(registry.releaseWorktreeLease({ sessionId, repoRoot: root, generation: lease.lease.generation, leaseId: lease.lease.leaseId }).ok, true);

		const stopping = registry.beginWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop" });
		assert.equal(stopping.ok, true, stopping.reason);
		const duringPendingStop = registry.hydrateApprovedWorktree({ sessionId, repoRoot: root, ...state });
		assert.equal(duringPendingStop.ok, false);
		assert.match(duringPendingStop.reason, /lifecycle operation is pending/);
		const failedStop = registry.finishWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop", succeeded: false });
		assert.equal(failedStop.ok, false);
		const preserved = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
		assert.equal(preserved.ok, true, preserved.reason);
		assert.equal(preserved.approval.generation, lease.lease.generation);
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
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

		assert.equal(await call(events, ctx, "worktree_start", {}, "start-active-shutdown"), undefined);
		await events.get("tool_result")({ toolName: "worktree_start", toolCallId: "start-active-shutdown", isError: false, details: { piWorktree: { mode: "active", repoRoot: root, worktreeRoot: worker } } }, ctx);
		assert.equal(await call(events, ctx, "write", { path: "allowed-before-shutdown", content: "allowed" }), undefined);
		await events.get("session_shutdown")({}, ctx);
		assert.match((await call(events, ctx, "write", { path: "blocked-after-shutdown", content: "blocked" })).reason, /require/);

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
		let current = harness(worker, "child-write", { directMcpTools: DIRECT_MCP_TOOL_DEFINITIONS });
		await current.events.get("session_start")({}, current.ctx);
		assert.equal(await call(current.events, current.ctx, "bash", { command: "git commit --allow-empty -m child" }), undefined);
		// A validated initial cwd routes a cooperative worker; it does not contain
		// its later direct Git/Bash path selection.
		assert.equal(await call(current.events, current.ctx, "bash", { command: "git -C ../ commit --allow-empty -m direct" }), undefined);
		assert.equal(await call(current.events, current.ctx, "bash", { command: "cd ../ && touch direct" }), undefined);
		assert.equal(await call(current.events, current.ctx, "write", { path: "../direct", content: "direct" }), undefined);
		await assertMcpPolicy(current);
		await assertDirectMcpPolicy(current);
		assert.match((await call(current.events, current.ctx, "worktree_start", {})).reason, /root-owned/);

		process.env.PI_SUBAGENT_EXECUTION = "read-only";
		delete process.env.PI_WORKTREE_ROOT;
		delete process.env.PI_WORKTREE_REPO_ROOT;
		delete process.env.PI_WORKTREE_GENERATION;
		current = harness(root, "child-read", { directMcpTools: DIRECT_MCP_TOOL_DEFINITIONS });
		await current.events.get("session_start")({}, current.ctx);
		assert.match((await call(current.events, current.ctx, "bash", { command: "git commit --allow-empty -m denied" })).reason, /read-only/);
		assert.match((await call(current.events, current.ctx, "bash", { command: "echo harmless\nrm -f denied" })).reason, /read-only/);
		assert.match((await call(current.events, current.ctx, "bash", { command: "sudo -u root git commit --allow-empty -m denied" })).reason, /read-only/);
		assert.match((await call(current.events, current.ctx, "write", { path: "blocked" })).reason, /read-only/);
		await assertMcpPolicy(current, true, /read-only/);
		await assertDirectMcpPolicy(current, true, /read-only/);
	} finally {
		for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
		Object.assign(process.env, original);
	}
}

async function testNoLabelToolInfoDoesNotThrowOrMisclassify() {
	const original = { ...process.env };
	try {
		process.env.PI_SUBAGENT = "1";
		process.env.PI_SUBAGENT_EXECUTION = "read-only";
		for (const key of ["PI_WORKTREE_ROOT", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION"]) delete process.env[key];
		const { root } = fixture();
		const current = harness(root, "no-label-tool-info", {
			directMcpTools: [toolInfo(DIRECT_MUTATING_MCP_TOOLS[0], OTHER_EXTENSION_SOURCE_INFO)],
		});
		await current.events.get("session_start")({}, current.ctx);
		assert.equal(
			await call(current.events, current.ctx, DIRECT_MUTATING_MCP_TOOLS[0], {}, "no-label-non-mcp-tool"),
			undefined,
		);
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

		process.env.PI_SUBAGENT_EXECUTION = "worktree-write";
		current = harness(plainDirectory, "child-degraded-write-non-git", {
			isGit: false,
			directMcpTools: DIRECT_MCP_TOOL_DEFINITIONS,
		});
		await current.events.get("session_start")({}, current.ctx);
		assert.equal(current.gitProbes(), 0, "degraded workers must not depend on a Git probe to be guarded");
		assert.match((await call(current.events, current.ctx, "write", { path: "blocked" })).reason, /without a Git worktree/);
		assert.match((await call(current.events, current.ctx, "edit", { path: "blocked" })).reason, /without a Git worktree/);
		await assertMcpPolicy(current, true, /without a Git worktree/);
		await assertDirectMcpPolicy(current, true, /without a Git worktree/);

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

if (command === "--resume") {
	if (!encodedResume) throw new Error("Missing resume payload.");
	await assertResumedWorktree(JSON.parse(Buffer.from(encodedResume, "base64url").toString("utf8")));
	console.log("resumed");
} else {
	if (command) throw new Error(`Unknown command: ${command}`);
	await testRootBlocksBeforeApproval();
	await testPiCloneEmitsForkSessionStartReason();
	await testResumeHydratesApprovedWorktree();
	await testForkedOrClonedSessionsDoNotHydrateCopiedWorktreeState();
	await testForkLineageRejectsInheritedApprovalAndAllowsNativeApproval();
	await testForkLineageFailsClosedWhenParentCannotBeRead();
	await testResumeDoesNotRestorePastSuccessfulStop();
	await testResumeOnlyUsesAllowlistedLifecycleCheckpoints();
	await testResumeRejectsUnidentifiedWorktreeState();
	await testResumeIgnoresLaterOtherRepositoryState();
	await testResumeRejectsMismatchedWorktreeBranch();
	await testHydrationPreservesPendingAndLeasedState();
	await testLifecyclePendingRecovery();
	await testChildPolicy();
	await testNoLabelToolInfoDoesNotThrowOrMisclassify();
	await testNonGitChildrenFailClosed();
	console.log("ok");
}
