#!/usr/bin/env node
/** Runtime coverage for subagent execution classes, preflight, and worker leases. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [extensionPath, guardPath, registryPath, packageDir] = process.argv.slice(2);
if (!extensionPath || !guardPath || !registryPath || !packageDir) {
	throw new Error("Usage: subagent_runner_runtime_harness.mjs <extension-path> <guard-path> <registry-path> <pi-package-dir>");
}

const require = createRequire(pathToFileURL(join(packageDir, "package.json")));
const createJiti = require("jiti");
const nodeModules = join(packageDir, "node_modules");
const jiti = createJiti(import.meta.url, {
	alias: {
		"@earendil-works/pi-ai": join(nodeModules, "@earendil-works", "pi-ai", "dist", "index.js"),
		"@earendil-works/pi-coding-agent": join(packageDir, "dist", "index.js"),
		"@earendil-works/pi-tui": join(nodeModules, "@earendil-works", "pi-tui", "dist", "index.js"),
		typebox: join(nodeModules, "typebox", "build", "index.mjs"),
	},
});
const { default: subagentExtension } = await jiti.import(resolve(extensionPath));
const { default: worktreeGuard } = await jiti.import(resolve(guardPath));
const { default: planModeExtension } = await jiti.import(resolve(extensionPath, "..", "..", "plan-mode", "index.ts"));
const registry = await import(pathToFileURL(resolve(registryPath)).href);

function git(root, ...args) {
	return execFileSync("git", ["-C", root, ...args], { encoding: "utf8" });
}

function worktreeFixture() {
	const root = mkdtempSync(join(tmpdir(), "pi-subagent-runner-"));
	const worker = join(root, "worker");
	git(root, "init", "-q");
	git(root, "config", "user.email", "test@example.invalid");
	git(root, "config", "user.name", "test");
	git(root, "commit", "--allow-empty", "-qm", "initial");
	git(root, "worktree", "add", "-qb", "worker", worker);
	return { root, worker };
}

function writeAgent(root, name, execution, tools = "read, bash", model = undefined) {
	const agentsDir = join(root, ".pi", "agents");
	mkdirSync(agentsDir, { recursive: true });
	const executionLine = execution === undefined ? "" : `execution: ${execution}\n`;
	const modelLine = model === undefined ? "" : `model: ${model}\n`;
	writeFileSync(
		join(agentsDir, `${name}.md`),
		`---\nname: ${name}\ndescription: ${name} test agent\ntools: ${tools}\n${executionLine}${modelLine}---\n\nTest agent.\n`,
	);
}

function writeAgents(root) {
	writeAgent(root, "reader", "read-only");
	writeAgent(root, "reviewer", "read-only");
	writeAgent(root, "writer", "worktree-write");
	writeAgent(root, "missing", undefined);
	writeAgent(root, "invalid", "not-a-class");
}

function runner(cwd, sessionId, model = { id: "root-model", provider: "root-provider" }) {
	let tool;
	subagentExtension({
		registerTool(definition) {
			tool = definition;
		},
	});
	assert.ok(tool, "subagent extension must register its tool");
	return {
		ctx: {
			cwd,
			hasUI: false,
			model,
			sessionManager: { getSessionId: () => sessionId },
			ui: { confirm: async () => false },
		},
		tool,
	};
}

async function startNestedChildPlanMode() {
	const handlers = [];
	planModeExtension({
		appendEntry() {},
		getActiveTools: () => [],
		getFlag: () => true,
		on(name, handler) {
			if (name === "session_start") handlers.push(handler);
		},
		registerCommand() {},
		registerEntryRenderer() {},
		registerFlag() {},
		registerShortcut() {},
		registerTool() {},
		setActiveTools() {},
	});
	const ctx = {
		mode: "json",
		sessionManager: { getBranch: () => [] },
		ui: { notify() {}, setStatus() {}, theme: { fg: (_color, text) => text } },
	};
	for (const handler of handlers) await handler({ reason: "startup" }, ctx);
}

function rootGuard(cwd, sessionId, branch, header = undefined) {
	const handlers = new Map();
	const ctx = {
		cwd,
		sessionManager: { getSessionId: () => sessionId, getBranch: () => branch, getHeader: () => header },
		ui: { notify() {}, setStatus() {}, theme: { fg: (_color, text) => text } },
	};
	worktreeGuard({
		exec: async () => ({ code: 0, killed: false, stdout: `${cwd}\n`, stderr: "" }),
		getAllTools: () => [],
		on(name, handler) {
			const eventHandlers = handlers.get(name) ?? [];
			eventHandlers.push(handler);
			handlers.set(name, eventHandlers);
		},
	});
	return {
		async emit(name, event = {}) {
			let result;
			for (const handler of handlers.get(name) ?? []) {
				const next = await handler(event, ctx);
				if (next !== undefined) result = next;
			}
			return result;
		},
	};
}

let nextSessionEntryId = 0;

function worktreeStateEntry(state, toolName = "worktree_start") {
	nextSessionEntryId += 1;
	return {
		type: "message",
		id: nextSessionEntryId.toString(16).padStart(8, "0"),
		parentId: null,
		timestamp: "2024-12-03T14:00:01.000Z",
		message: { role: "toolResult", toolName, details: { piWorktree: state } },
	};
}

function resumableWorktreeState(root, worker) {
	return {
		mode: "active",
		repoRoot: root,
		worktreeRoot: worker,
		branch: git(worker, "rev-parse", "--abbrev-ref", "HEAD").trim(),
	};
}

function resetApprovalRegistry() {
	delete globalThis[Symbol.for("dfrank.pi.worktree-approval-registry")];
}

async function approveFromWorktreeStart(guard, root, worker, toolCallId) {
	const state = resumableWorktreeState(root, worker);
	assert.equal(await guard.emit("tool_call", { toolName: "worktree_start", toolCallId }), undefined);
	await guard.emit("tool_result", { toolName: "worktree_start", toolCallId, isError: false, details: { piWorktree: state } });
	return state;
}

async function invoke(currentRunner, params, signal) {
	return currentRunner.tool.execute("subagent-test", params, signal, undefined, currentRunner.ctx);
}

function resultText(result) {
	const content = result.content?.[0];
	assert.equal(content?.type, "text");
	return content.text;
}

function fakePi({ extensionPath, packageDir }) {
	const directory = mkdtempSync(join(tmpdir(), "pi-subagent-fake-"));
	const script = join(directory, "pi.mjs");
	const log = join(directory, "invocations.jsonl");
	writeFileSync(
		script,
		[
			'import { appendFileSync, existsSync } from "node:fs";',
			'import { createRequire } from "node:module";',
			'import { join, resolve } from "node:path";',
			'import { pathToFileURL } from "node:url";',
			"const record = {",
			"\tcwd: process.cwd(),",
			"\targs: process.argv.slice(2),",
			"\texecution: process.env.PI_SUBAGENT_EXECUTION,",
			"\tphase: process.env.PI_ROOT_PHASE,",
			"\tmarker: process.env.PI_SUBAGENT,",
			"\tworktreeRoot: process.env.PI_WORKTREE_ROOT,",
			"\trepoRoot: process.env.PI_WORKTREE_REPO_ROOT,",
			"\tgeneration: process.env.PI_WORKTREE_GENERATION,",
			"\tbranch: process.env.PI_WORKTREE_BRANCH,",
			"\trootIdentity: process.env.PI_ROOT_IDENTITY,",
			"\tlevel: process.env.FAKE_PI_NESTED_LEVEL,",
			"\tprocessId: process.pid,",
			"\tparentProcessId: process.ppid,",
			"};",
			"let recorded = false;",
			'const recordInvocation = () => { if (!recorded) { appendFileSync(process.env.FAKE_PI_LOG, `${JSON.stringify(record)}\\n`); recorded = true; } };',
			'if (process.env.FAKE_PI_BEHAVIOR === "nested-launcher" && process.env.FAKE_PI_NESTED_LEVEL === "first") {',
			"\trecordInvocation();",
			"\tconst packageDir = process.env.FAKE_PI_PACKAGE_DIR;",
			"\tconst require = createRequire(pathToFileURL(join(packageDir, \"package.json\")));",
			"\tconst nodeModules = join(packageDir, \"node_modules\");",
			"\tconst jiti = require(\"jiti\")(import.meta.url, { alias: {",
			"\t\t\"@earendil-works/pi-ai\": join(nodeModules, \"@earendil-works\", \"pi-ai\", \"dist\", \"index.js\"),",
			"\t\t\"@earendil-works/pi-coding-agent\": join(packageDir, \"dist\", \"index.js\"),",
			"\t\t\"@earendil-works/pi-tui\": join(nodeModules, \"@earendil-works\", \"pi-tui\", \"dist\", \"index.js\"),",
			"\t\ttypebox: join(nodeModules, \"typebox\", \"build\", \"index.mjs\"),",
			"\t} });",
			"\tconst { default: subagentExtension } = await jiti.import(resolve(process.env.FAKE_PI_SUBAGENT_EXTENSION));",
			"\tlet tool;",
			"\tsubagentExtension({ registerTool(definition) { tool = definition; } });",
			"\tprocess.env.FAKE_PI_NESTED_LEVEL = \"grandchild\";",
			"\tconst result = await tool.execute(\"nested-subagent-test\", { agent: \"reader\", task: \"launch the grandchild\", agentScope: \"project\", confirmProjectAgents: false }, undefined, undefined, { cwd: process.cwd(), hasUI: false, model: { id: \"model-B\", provider: \"provider-B\" }, sessionManager: { getSessionId: () => \"session-B\" }, ui: { confirm: async () => false } });",
			'\tif (result.isError) throw new Error(result.content?.[0]?.text ?? "nested launcher failed");',
			"}",
			'if (process.env.FAKE_PI_BEHAVIOR === "hold" || process.env.FAKE_PI_BEHAVIOR === "ignore-term") {',
			'\tif (process.env.FAKE_PI_BEHAVIOR === "ignore-term") process.on("SIGTERM", () => {});',
			"\tconst release = process.env.FAKE_PI_RELEASE;",
			"\tconst timer = setInterval(() => {",
			"\t\tif (!release || !existsSync(release)) return;",
			"\t\tclearInterval(timer);",
			"\t\tprocess.exit(0);",
			"\t}, 10);",
			"}",
			"recordInvocation();",
			'if (process.env.FAKE_PI_BEHAVIOR === "signal") process.kill(process.pid, "SIGTERM");',
		].join("\n"),
	);
	return { log, script };
}

function invocations(log) {
	try {
		return readFileSync(log, "utf8")
			.trim()
			.split("\n")
			.filter(Boolean)
			.map((line) => JSON.parse(line));
	} catch {
		return [];
	}
}

function rootIdentity(model, provider, sessionId) {
	return JSON.stringify({ model, provider, sessionId });
}

function assertRootIdentity(record, expected) {
	assert.equal(record.rootIdentity, expected, "child must receive the exact root identity envelope");
	assert.deepEqual(JSON.parse(record.rootIdentity), JSON.parse(expected));
}

function assertChildLaunchArgs(log) {
	const records = invocations(log);
	assert.ok(records.length > 0, "scenario must spawn at least one child");
	for (const [index, record] of records.entries()) {
		const child = `child launch ${index + 1}`;
		assert.ok(record.args.includes("--no-session"), `${child} must isolate session history`);
		assert.equal(record.args.includes("--no-context-files"), false, `${child} must retain context-file discovery`);
		assert.equal(record.args.includes("-nc"), false, `${child} must retain context-file discovery`);
		assert.equal(record.args.includes("--thinking"), false, `${child} must inherit Pi's configured thinking level`);
		assert.equal("branch" in record, false, `${child} must not inherit PI_WORKTREE_BRANCH`);
	}
}

async function withFakePi(fake, callback, environment = {}) {
	const originalScript = process.argv[1];
	const originals = new Map(
		Object.keys(environment).map((key) => [key, process.env[key]]),
	);
	const originalLog = process.env.FAKE_PI_LOG;
	process.argv[1] = fake.script;
	process.env.FAKE_PI_LOG = fake.log;
	for (const [key, value] of Object.entries(environment)) {
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
	try {
		return await callback();
	} finally {
		process.argv[1] = originalScript;
		if (originalLog === undefined) delete process.env.FAKE_PI_LOG;
		else process.env.FAKE_PI_LOG = originalLog;
		for (const [key, value] of originals) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
	}
}

async function waitFor(predicate, description) {
	const deadline = Date.now() + 2_000;
	while (!predicate()) {
		if (Date.now() >= deadline) throw new Error(`Timed out waiting for ${description}`);
		await new Promise((resolve) => setTimeout(resolve, 10));
	}
}

function approve(root, worker, sessionId) {
	const approval = registry.approveWorktree({
		sessionId,
		repoRoot: root,
		worktreeRoot: worker,
		toolCallId: `${sessionId}-start`,
	});
	assert.equal(approval.ok, true, approval.reason);
	return approval.approval;
}

async function testRootIdentityPropagatesAcrossLaunchModes(fake) {
	const { root } = worktreeFixture();
	writeAgents(root);
	const cases = [
		["single", { agent: "reader", task: "inspect", agentScope: "project", confirmProjectAgents: false }, 1],
		[
			"parallel",
			{
				tasks: [
					{ agent: "reader", task: "inspect the first concern" },
					{ agent: "reviewer", task: "inspect the second concern" },
				],
				agentScope: "project",
				confirmProjectAgents: false,
			},
			2,
		],
		[
			"chain",
			{
				chain: [
					{ agent: "reader", task: "inspect first" },
					{ agent: "reviewer", task: "review {previous}" },
				],
				agentScope: "project",
				confirmProjectAgents: false,
			},
			2,
		],
	];
	for (const [mode, params, expectedLaunches] of cases) {
		writeFileSync(fake.log, "");
		const model = { id: `root-${mode}-model`, provider: `root-${mode}-provider` };
		const sessionId = `root-${mode}-session`;
		const result = await withFakePi(fake, () => invoke(runner(root, sessionId, model), params));
		assert.equal(result.isError, undefined, resultText(result));
		const records = invocations(fake.log);
		assert.equal(records.length, expectedLaunches, `${mode} launch count`);
		const expected = rootIdentity(model.id, model.provider, sessionId);
		for (const record of records) assertRootIdentity(record, expected);
		assertChildLaunchArgs(fake.log);
	}
}

async function testNestedRootIdentityIsForwardedUnchanged(fake, packageDir) {
	assert.equal(process.env.PI_ROOT_IDENTITY, undefined, "nested forwarding must begin at the root");
	const { root } = worktreeFixture();
	writeAgents(root);
	const rootModel = { id: "model-A", provider: "provider-A" };
	const rootSessionId = "session-A";
	const envelope = rootIdentity(rootModel.id, rootModel.provider, rootSessionId);
	const result = await withFakePi(
		fake,
		() =>
			invoke(runner(root, rootSessionId, rootModel), {
				agent: "reader",
				task: "launch the nested child",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		{
			FAKE_PI_BEHAVIOR: "nested-launcher",
			FAKE_PI_NESTED_LEVEL: "first",
			FAKE_PI_PACKAGE_DIR: packageDir,
			FAKE_PI_SUBAGENT_EXTENSION: extensionPath,
		},
	);
	assert.equal(result.isError, undefined, resultText(result));
	const records = invocations(fake.log);
	assert.equal(records.length, 2, "the first-level child must spawn one real grandchild");
	const [firstLevelRecord, grandchildRecord] = records;
	assert.equal(firstLevelRecord.level, "first");
	assert.equal(grandchildRecord.level, "grandchild");
	assert.notEqual(firstLevelRecord.processId, grandchildRecord.processId, "nested forwarding must cross a real process boundary");
	assert.equal(grandchildRecord.parentProcessId, firstLevelRecord.processId, "the grandchild must be spawned by the first-level child");
	assertRootIdentity(firstLevelRecord, envelope);
	assertRootIdentity(grandchildRecord, envelope);
	assert.deepEqual(JSON.parse(grandchildRecord.rootIdentity), {
		model: "model-A",
		provider: "provider-A",
		sessionId: "session-A",
	});
	assert.notDeepEqual(JSON.parse(grandchildRecord.rootIdentity), {
		model: "model-B",
		provider: "provider-B",
		sessionId: "session-B",
	});
	assertChildLaunchArgs(fake.log);
}

async function testRootIdentityValidationFailsLoud(fake) {
	const { root } = worktreeFixture();
	writeAgents(root);
	const params = { agent: "reader", task: "reject invalid root identity", agentScope: "project", confirmProjectAgents: false };
	await assert.rejects(
		() => withFakePi(fake, () => invoke(runner(root, "invalid-root", { id: "", provider: "root-provider" }), params)),
		/PI_ROOT_IDENTITY context field 'model' must be a non-empty string/,
	);
	assert.deepEqual(invocations(fake.log), []);

	await assert.rejects(
		() => withFakePi(fake, () => invoke(runner(root, "nested-invalid-root"), params), { PI_ROOT_IDENTITY: "not-json" }),
		/PI_ROOT_IDENTITY envelope contains invalid JSON/,
	);
	assert.deepEqual(invocations(fake.log), []);

	for (const [caseName, inherited, pattern] of [
		["missing-provider", { model: "root-model", sessionId: "root-session" }, /missing field 'provider'/],
		["blank-provider", { model: "root-model", provider: " ", sessionId: "root-session" }, /field 'provider' must be a non-empty string/],
		["non-string-provider", { model: "root-model", provider: 42, sessionId: "root-session" }, /field 'provider' must be a non-empty string/],
		["missing-session-id", { model: "root-model", provider: "root-provider" }, /missing field 'sessionId'/],
		["blank-session-id", { model: "root-model", provider: "root-provider", sessionId: " \t" }, /field 'sessionId' must be a non-empty string/],
		["non-string-session-id", { model: "root-model", provider: "root-provider", sessionId: 42 }, /field 'sessionId' must be a non-empty string/],
	]) {
		await assert.rejects(
			() => withFakePi(fake, () => invoke(runner(root, `invalid-${caseName}`), params), { PI_ROOT_IDENTITY: JSON.stringify(inherited) }),
			pattern,
		);
		assert.deepEqual(invocations(fake.log), [], `${caseName} must reject before spawning a child`);
	}
}

async function testReadOnlyExecution(fake) {
	const { root } = worktreeFixture();
	const sessionId = "read-only";
	writeAgents(root);
	const currentRunner = runner(root, sessionId);
	const original = {
		generation: process.env.PI_WORKTREE_GENERATION,
		repoRoot: process.env.PI_WORKTREE_REPO_ROOT,
		worktreeRoot: process.env.PI_WORKTREE_ROOT,
		branch: process.env.PI_WORKTREE_BRANCH,
	};
	process.env.PI_WORKTREE_GENERATION = "stale";
	process.env.PI_WORKTREE_REPO_ROOT = "stale";
	process.env.PI_WORKTREE_ROOT = "stale";
	process.env.PI_WORKTREE_BRANCH = "stale";
	try {
		const result = await withFakePi(fake, () =>
			invoke(currentRunner, {
				agent: "reader",
				task: "inspect only",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		);
		assert.equal(result.isError, undefined, resultText(result));
		const [record] = invocations(fake.log);
		assert.equal(record.cwd, realpathSync(root));
		assert.equal(record.execution, "read-only");
		assert.equal(record.marker, "1");
		assert.equal("worktreeRoot" in record, false);
		assert.equal("repoRoot" in record, false);
		assert.equal("generation" in record, false);
		assertChildLaunchArgs(fake.log);
	} finally {
		if (original.generation === undefined) delete process.env.PI_WORKTREE_GENERATION;
		else process.env.PI_WORKTREE_GENERATION = original.generation;
		if (original.repoRoot === undefined) delete process.env.PI_WORKTREE_REPO_ROOT;
		else process.env.PI_WORKTREE_REPO_ROOT = original.repoRoot;
		if (original.worktreeRoot === undefined) delete process.env.PI_WORKTREE_ROOT;
		else process.env.PI_WORKTREE_ROOT = original.worktreeRoot;
		if (original.branch === undefined) delete process.env.PI_WORKTREE_BRANCH;
		else process.env.PI_WORKTREE_BRANCH = original.branch;
	}
}

async function testModelScopePassThrough(fake) {
	const { root } = worktreeFixture();
	const sessionId = "model-scopes";
	writeAgent(root, "canonical", "read-only", "read", "openai/openai/gpt-5.6-terra");
	writeAgent(root, "raw", "read-only", "read", "openai/gpt-5.6-terra");

	await withFakePi(fake, async () => {
		for (const [agent, model] of [
			["canonical", "openai/openai/gpt-5.6-terra"],
			["raw", "openai/gpt-5.6-terra"],
		]) {
			const result = await invoke(runner(root, sessionId), {
				agent,
				task: "inspect model forwarding",
				agentScope: "project",
				confirmProjectAgents: false,
			});
			assert.equal(result.isError, undefined, resultText(result));
			const record = invocations(fake.log).at(-1);
			const modelIndex = record.args.indexOf("--model");
			assert.equal(record.args[modelIndex + 1], model);
		}
	});
	assertChildLaunchArgs(fake.log);
}

async function testApprovedWorktreeRoutesReviewers(fake) {
	const { root, worker } = worktreeFixture();
	const sessionId = "approved-reviewer";
	writeAgents(root);
	approve(root, worker, sessionId);
	try {
		await withFakePi(fake, async () => {
			const review = await invoke(runner(root, sessionId), {
				agent: "reviewer",
				task: "review the active implementation",
				cwd: root,
				agentScope: "project",
				confirmProjectAgents: false,
			});
			assert.equal(review.isError, undefined, resultText(review));

			const chain = await invoke(runner(root, sessionId), {
				chain: [
					{ agent: "writer", task: "implement" },
					{ agent: "reviewer", task: "review {previous}" },
				],
				agentScope: "project",
				confirmProjectAgents: false,
			});
			assert.equal(chain.isError, undefined, resultText(chain));
		});
		const records = invocations(fake.log);
		assert.equal(records.length, 3);
		assert.deepEqual(records.map((record) => record.cwd), [realpathSync(worker), realpathSync(worker), realpathSync(worker)]);
		assert.deepEqual(records.map((record) => record.execution), ["read-only", "worktree-write", "read-only"]);
		assertChildLaunchArgs(fake.log);
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

async function testReadOnlyRejectsUnresolvedApproval(fake) {
	const pending = worktreeFixture();
	const pendingSession = "pending-read-only";
	writeAgents(pending.root);
	approve(pending.root, pending.worker, pendingSession);
	try {
		const stop = registry.beginWorktreeStop({ sessionId: pendingSession, repoRoot: pending.root, toolCallId: "pending-stop" });
		assert.equal(stop.ok, true, stop.reason);
		const result = await withFakePi(fake, () =>
			invoke(runner(pending.root, pendingSession), {
				agent: "reviewer",
				task: "do not review a stale checkout",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		);
		assert.equal(result.isError, true);
		assert.match(resultText(result), /worktree stop is pending/);
		assert.deepEqual(invocations(fake.log), []);
	} finally {
		registry.revokeWorktree({ sessionId: pendingSession, repoRoot: pending.root });
	}

	writeFileSync(fake.log, "");
	const invalid = worktreeFixture();
	const invalidSession = "invalid-read-only";
	writeAgents(invalid.root);
	approve(invalid.root, invalid.worker, invalidSession);
	git(invalid.root, "worktree", "remove", "--force", invalid.worker);
	try {
		const result = await withFakePi(fake, () =>
			invoke(runner(invalid.root, invalidSession), {
				agent: "reviewer",
				task: "do not review an invalid checkout",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		);
		assert.equal(result.isError, true);
		assert.match(resultText(result), /path is not an existing Git worktree/);
		assert.deepEqual(invocations(fake.log), []);
	} finally {
		registry.revokeWorktree({ sessionId: invalidSession, repoRoot: invalid.root });
	}
}

async function testWritableExecution(fake) {
	const { root, worker } = worktreeFixture();
	const sessionId = "writable";
	writeAgents(root);
	const approval = approve(root, worker, sessionId);
	try {
		const result = await withFakePi(fake, () =>
			invoke(runner(root, sessionId), {
				agent: "writer",
				task: "make a change",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		);
		assert.equal(result.isError, undefined, resultText(result));
		const record = invocations(fake.log).at(-1);
		assert.equal(record.cwd, realpathSync(worker));
		assert.equal(record.execution, "worktree-write");
		assert.equal(record.marker, "1");
		assert.equal(record.worktreeRoot, realpathSync(worker));
		assert.equal(record.repoRoot, realpathSync(root));
		assert.equal(record.generation, String(approval.generation));
		assert.equal(registry.worktreeHasLeases({ sessionId, repoRoot: root }), false);
		assertChildLaunchArgs(fake.log);
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

async function testMarkerlessWritableExecutionOutsideGit(fake) {
	const directory = mkdtempSync(join(tmpdir(), "pi-subagent-non-git-"));
	const parent = worktreeFixture();
	const sessionId = "markerless-writable";
	const parentApproval = approve(parent.root, parent.worker, "parent-worktree");
	writeAgents(directory);
	try {
		await withFakePi(
			fake,
			async () => {
				const single = await invoke(runner(directory, sessionId), {
					agent: "writer",
					task: "make permitted mutations in a confirmed non-Git directory",
					agentScope: "project",
					confirmProjectAgents: false,
				});
				assert.equal(single.isError, undefined, resultText(single));

				const relative = await invoke(runner(directory, sessionId), {
					agent: "writer",
					task: "reject a relative cwd",
					cwd: "relative",
					agentScope: "project",
					confirmProjectAgents: false,
				});
				assert.equal(relative.isError, true);
				assert.match(resultText(relative), /cwd must be an absolute path/);
			},
			{
				PI_WORKTREE_ROOT: parent.worker,
				PI_WORKTREE_REPO_ROOT: parent.root,
				PI_WORKTREE_GENERATION: String(parentApproval.generation),
			},
		);
		const [single] = invocations(fake.log);
		assert.equal(single.cwd, realpathSync(directory));
		assert.equal(single.execution, "worktree-write");
		assert.equal("worktreeRoot" in single, false);
		assert.equal("repoRoot" in single, false);
		assert.equal("generation" in single, false);
		assertChildLaunchArgs(fake.log);

		writeFileSync(fake.log, "");
		const parallel = await withFakePi(fake, () =>
			invoke(runner(directory, sessionId), {
				tasks: [
					{ agent: "writer", task: "inspect the first concern" },
					{ agent: "writer", task: "inspect the second concern" },
				],
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		);
		assert.equal(parallel.isError, undefined, resultText(parallel));
		const records = invocations(fake.log);
		assert.equal(records.length, 2);
		assert.deepEqual(records.map((record) => record.execution), ["worktree-write", "worktree-write"]);
		for (const record of records) {
			assert.equal(record.cwd, realpathSync(directory));
			assert.equal("worktreeRoot" in record, false);
			assert.equal("repoRoot" in record, false);
			assert.equal("generation" in record, false);
		}
		assertChildLaunchArgs(fake.log);
	} finally {
		registry.revokeWorktree({ sessionId: "parent-worktree", repoRoot: parent.root });
	}
}

async function testReadOnlyMcpAgentsLaunchOutsideGit(fake) {
	const directory = mkdtempSync(join(tmpdir(), "pi-subagent-mcp-non-git-"));
	const sessionId = "read-only-mcp-non-git";
	const agents = [
		["scout", "read, grep, find, ls, bash, mcp"],
		["planner", "read, grep, find, ls, mcp"],
		["reviewer", "read, grep, find, ls, bash, mcp"],
	];
	for (const [agent, tools] of agents) writeAgent(directory, agent, "read-only", tools);

	await withFakePi(fake, async () => {
		for (const [agent, tools] of agents) {
			const result = await invoke(runner(directory, sessionId), {
				agent,
				task: "use MCP for read-only reconnaissance",
				agentScope: "project",
				confirmProjectAgents: false,
			});
			assert.equal(result.isError, undefined, resultText(result));
			const record = invocations(fake.log).at(-1);
			assert.equal(record.cwd, realpathSync(directory));
			assert.equal(record.execution, "read-only");
			const toolsIndex = record.args.indexOf("--tools");
			assert.equal(record.args[toolsIndex + 1], tools.replaceAll(" ", ""));
		}
	});
	assertChildLaunchArgs(fake.log);
}

async function testResumeHydrationRoutesWritableAgent(fake) {
	const { root, worker } = worktreeFixture();
	const sessionId = "resumed-writable";
	writeAgents(root);
	const first = rootGuard(root, sessionId, []);
	await first.emit("session_start", { reason: "startup" });
	const state = await approveFromWorktreeStart(first, root, worker, `${sessionId}-start`);
	const initial = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
	assert.equal(initial.ok, true, initial.reason);

	resetApprovalRegistry();
	const before = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
	assert.equal(before.ok, false);
	assert.equal(before.noApproval, true);

	const guard = rootGuard(root, sessionId, [worktreeStateEntry(state)]);
	await guard.emit("session_start", { reason: "resume" });
	assert.equal(await guard.emit("tool_call", { toolName: "write", input: { path: "resumed", content: "resumed" }, toolCallId: `${sessionId}-write` }), undefined);
	const hydrated = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
	assert.equal(hydrated.ok, true, hydrated.reason);
	try {
		const result = await withFakePi(fake, () =>
			invoke(runner(root, sessionId), {
				agent: "writer",
				task: "write after resuming",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		);
		assert.equal(result.isError, undefined, resultText(result));
		const records = invocations(fake.log);
		assert.equal(records.length, 1);
		const [record] = records;
		assert.equal(record.cwd, realpathSync(worker));
		assert.equal(record.execution, "worktree-write");
		assert.equal(record.marker, "1");
		assert.equal(record.worktreeRoot, realpathSync(worker));
		assert.equal(record.repoRoot, realpathSync(root));
		assert.equal(record.generation, String(hydrated.approval.generation));
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

async function testDeletedResumedWorktreeRejectsWritableAgent(fake) {
	const { root, worker } = worktreeFixture();
	const sessionId = "resumed-deleted";
	writeAgents(root);
	const first = rootGuard(root, sessionId, []);
	await first.emit("session_start", { reason: "startup" });
	const state = await approveFromWorktreeStart(first, root, worker, `${sessionId}-start`);
	const initial = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
	assert.equal(initial.ok, true, initial.reason);

	resetApprovalRegistry();
	const before = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
	assert.equal(before.ok, false);
	assert.equal(before.noApproval, true);

	const guard = rootGuard(root, sessionId, [worktreeStateEntry(state)]);
	await guard.emit("session_start", { reason: "resume" });
	assert.equal(await guard.emit("tool_call", { toolName: "write", input: { path: "resumed", content: "resumed" }, toolCallId: `${sessionId}-write` }), undefined);
	const hydrated = registry.resolveApprovedWorktree({ sessionId, repoRoot: root, cwd: worker });
	assert.equal(hydrated.ok, true, hydrated.reason);
	git(root, "worktree", "remove", "--force", worker);
	try {
		const result = await withFakePi(fake, () =>
			invoke(runner(root, sessionId), {
				agent: "writer",
				task: "reject a deleted worktree",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		);
		assert.equal(result.isError, true);
		assert.match(resultText(result), /path is not an existing Git worktree/);
		assert.deepEqual(invocations(fake.log), []);
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

async function testExecutionClassAndCwdPreflight(fake) {
	const { root, worker } = worktreeFixture();
	const sessionId = "preflight";
	writeAgents(root);
	approve(root, worker, sessionId);
	try {
		await withFakePi(fake, async () => {
			for (const [agent, expected] of [
				["missing", /must declare execution/],
				["invalid", /must declare execution/],
			]) {
				const result = await invoke(runner(root, sessionId), {
					agent,
					task: "reject me",
					agentScope: "project",
					confirmProjectAgents: false,
				});
				assert.equal(result.isError, true);
				assert.match(resultText(result), expected);
			}

			const relative = await invoke(runner(root, sessionId), {
				agent: "writer",
				task: "relative cwd",
				cwd: "worker",
				agentScope: "project",
				confirmProjectAgents: false,
			});
			assert.equal(relative.isError, true);
			assert.match(resultText(relative), /cwd must be an absolute path/);

			const primary = await invoke(runner(root, sessionId), {
				agent: "writer",
				task: "primary cwd",
				cwd: root,
				agentScope: "project",
				confirmProjectAgents: false,
			});
			assert.equal(primary.isError, true);
			assert.match(resultText(primary), /cwd is not the root-approved worktree/);
		});
		assert.deepEqual(invocations(fake.log), []);
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

async function testParallelPreflightIsAtomic(fake) {
	const { root, worker } = worktreeFixture();
	const sessionId = "parallel";
	writeAgents(root);
	approve(root, worker, sessionId);
	try {
		const result = await withFakePi(fake, () =>
			invoke(runner(root, sessionId), {
				tasks: [
					{ agent: "writer", task: "first" },
					{ agent: "writer", task: "second" },
				],
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		);
		assert.equal(result.isError, true);
		assert.match(resultText(result), /Parallel writable workers require distinct root-owned worktrees/);
		assert.deepEqual(invocations(fake.log), []);
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

async function testParallelReadOnlyExecution(fake) {
	const { root } = worktreeFixture();
	const sessionId = "parallel-read-only";
	writeAgents(root);
	const result = await withFakePi(fake, () =>
		invoke(runner(root, sessionId), {
			tasks: [
				{ agent: "reader", task: "inspect the first concern" },
				{ agent: "reviewer", task: "inspect the second concern" },
			],
			agentScope: "project",
			confirmProjectAgents: false,
		}),
	);
	assert.equal(result.isError, undefined, resultText(result));
	const records = invocations(fake.log);
	assert.equal(records.length, 2);
	assert.deepEqual(records.map((record) => record.execution), ["read-only", "read-only"]);
	assertChildLaunchArgs(fake.log);
}

async function testPlanPhaseDowngradesWorkers(fake) {
	const { root } = worktreeFixture();
	const sessionId = "plan-phase-downgrade";
	writeAgents(root);
	const cases = [
		["single", { agent: "writer", task: "inspect", agentScope: "project", confirmProjectAgents: false }, 1],
		[
			"chain",
			{
				chain: [
					{ agent: "writer", task: "inspect first" },
					{ agent: "writer", task: "inspect second" },
				],
				agentScope: "project",
				confirmProjectAgents: false,
			},
			2,
		],
		[
			"parallel",
			{
				tasks: [
					{ agent: "writer", task: "inspect first" },
					{ agent: "writer", task: "inspect second" },
				],
				agentScope: "project",
				confirmProjectAgents: false,
			},
			2,
		],
	];
	for (const [id, params, expectedLaunches] of cases) {
		writeFileSync(fake.log, "");
		const result = await withFakePi(fake, () => invoke(runner(root, `${sessionId}-${id}`), params), { PI_ROOT_PHASE: "plan" });
		assert.equal(result.isError, undefined, resultText(result));
		const records = invocations(fake.log);
		assert.equal(records.length, expectedLaunches, `${id} launch count`);
		for (const record of records) {
			assert.equal(record.execution, "read-only", `${id} worker execution`);
			assert.equal(record.phase, "plan", `${id} worker phase propagation`);
		}
		assertChildLaunchArgs(fake.log);
	}

	writeFileSync(fake.log, "");
	const missingPhase = await withFakePi(
		fake,
		() =>
			invoke(runner(root, `${sessionId}-missing-phase`), {
				agent: "writer",
				task: "fail closed without a root phase",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		{ PI_ROOT_PHASE: undefined },
	);
	assert.equal(missingPhase.isError, undefined, resultText(missingPhase));
	const [missingPhaseRecord] = invocations(fake.log);
	assert.equal(missingPhaseRecord.execution, "read-only");
	assert.equal("phase" in missingPhaseRecord, false);

	writeFileSync(fake.log, "");
	const unrecognizedPhase = await withFakePi(
		fake,
		() =>
			invoke(runner(root, `${sessionId}-unrecognized-phase`), {
				agent: "writer",
				task: "fail closed for an unrecognized root phase",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		{ PI_ROOT_PHASE: "bogus" },
	);
	assert.equal(unrecognizedPhase.isError, undefined, resultText(unrecognizedPhase));
	const [unrecognizedPhaseRecord] = invocations(fake.log);
	assert.equal(unrecognizedPhaseRecord.execution, "read-only");
	assert.equal(unrecognizedPhaseRecord.phase, "bogus");

	writeFileSync(fake.log, "");
	const legacyNormal = await withFakePi(
		fake,
		() =>
			invoke(runner(root, `${sessionId}-legacy-normal`), {
				agent: "writer",
				task: "fail closed for the legacy phase value",
				agentScope: "project",
				confirmProjectAgents: false,
			}),
		{ PI_ROOT_PHASE: "normal" },
	);
	assert.equal(legacyNormal.isError, undefined, resultText(legacyNormal));
	const [legacyNormalRecord] = invocations(fake.log);
	assert.equal(legacyNormalRecord.execution, "read-only");
	assert.equal(legacyNormalRecord.phase, "normal");

	writeFileSync(fake.log, "");
	const nested = await withFakePi(
		fake,
		async () => {
			await startNestedChildPlanMode();
			assert.equal(process.env.PI_ROOT_PHASE, "plan", "child plan-mode startup must preserve the inherited root phase");
			return invoke(runner(root, `${sessionId}-nested`), {
				agent: "writer",
				task: "nested worker",
				agentScope: "project",
				confirmProjectAgents: false,
			});
		},
		{ PI_ROOT_PHASE: "plan", PI_SUBAGENT: "1" },
	);
	assert.equal(nested.isError, undefined, resultText(nested));
	const [nestedRecord] = invocations(fake.log);
	assert.equal(nestedRecord.execution, "read-only");
	assert.equal(nestedRecord.phase, "plan");
	assert.equal(nestedRecord.marker, "1");
}

async function testNonGitParentRejectsGitCwdOverride(fake) {
	const directory = mkdtempSync(join(tmpdir(), "pi-subagent-non-git-parent-"));
	const { root } = worktreeFixture();
	writeAgents(directory);
	const result = await withFakePi(fake, () =>
		invoke(runner(directory, "non-git-parent-git-cwd"), {
			agent: "writer",
			task: "must not enter Git",
			cwd: root,
			agentScope: "project",
			confirmProjectAgents: false,
		}),
	);
	assert.equal(result.isError, true);
	assert.match(resultText(result), /cwd override must not be inside a Git repository/);
	assert.deepEqual(invocations(fake.log), []);
}

async function testLeaseReleasesAfterSpawnFailure() {
	const { root, worker } = worktreeFixture();
	const sessionId = "spawn-failure";
	writeAgents(root);
	approve(root, worker, sessionId);
	const missingPiDirectory = mkdtempSync(join(tmpdir(), "pi-subagent-missing-"));
	const originalPath = process.env.PATH;
	const originalScript = process.argv[1];
	process.env.PATH = missingPiDirectory;
	process.argv[1] = join(missingPiDirectory, "missing-pi");
	try {
		const result = await invoke(runner(root, sessionId), {
			agent: "writer",
			task: "fail to spawn",
			agentScope: "project",
			confirmProjectAgents: false,
		});
		assert.equal(result.isError, true);
		assert.equal(registry.worktreeHasLeases({ sessionId, repoRoot: root }), false);
		const stop = registry.beginWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop-after-failure" });
		assert.equal(stop.ok, true, stop.reason);
		registry.finishWorktreeStop({ sessionId, repoRoot: root, toolCallId: "stop-after-failure", succeeded: false });
	} finally {
		process.argv[1] = originalScript;
		if (originalPath === undefined) delete process.env.PATH;
		else process.env.PATH = originalPath;
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

async function testConcurrentToolCallsShareOneLease(fake) {
	const { root, worker } = worktreeFixture();
	const sessionId = "concurrent";
	writeAgents(root);
	approve(root, worker, sessionId);
	const release = join(mkdtempSync(join(tmpdir(), "pi-subagent-release-")), "release");
	try {
		await withFakePi(
			fake,
			async () => {
				const first = invoke(runner(root, sessionId), {
					agent: "writer",
					task: "hold the sole lease",
					agentScope: "project",
					confirmProjectAgents: false,
				});
				await waitFor(() => invocations(fake.log).length === 1, "the first writable child");

				const second = await invoke(runner(root, sessionId), {
					agent: "writer",
					task: "race the first worker",
					agentScope: "project",
					confirmProjectAgents: false,
				});
				assert.equal(second.isError, true);
				assert.match(resultText(second), /active worker holds the worktree lease/);
				assert.equal(invocations(fake.log).length, 1);

				writeFileSync(release, "release");
				const completed = await first;
				assert.equal(completed.isError, undefined, resultText(completed));

				const afterRelease = await invoke(runner(root, sessionId), {
					agent: "writer",
					task: "acquire after release",
					agentScope: "project",
					confirmProjectAgents: false,
				});
				assert.equal(afterRelease.isError, undefined, resultText(afterRelease));
				assert.equal(invocations(fake.log).length, 2);
				assertChildLaunchArgs(fake.log);
			},
			{ FAKE_PI_BEHAVIOR: "hold", FAKE_PI_RELEASE: release },
		);
	} finally {
		registry.revokeWorktree({ sessionId, repoRoot: root });
	}
}

async function testSignalTerminationAndAbortEscalation(fake) {
	const signaled = worktreeFixture();
	const signaledSession = "signaled";
	writeAgents(signaled.root);
	approve(signaled.root, signaled.worker, signaledSession);
	try {
		const result = await withFakePi(
			fake,
			() =>
				invoke(runner(signaled.root, signaledSession), {
					agent: "writer",
					task: "exit by signal",
					agentScope: "project",
					confirmProjectAgents: false,
				}),
			{ FAKE_PI_BEHAVIOR: "signal" },
		);
		assert.equal(result.isError, true);
		assert.match(resultText(result), /terminated by SIGTERM/);
		assert.equal(registry.worktreeHasLeases({ sessionId: signaledSession, repoRoot: signaled.root }), false);
		assertChildLaunchArgs(fake.log);
	} finally {
		registry.revokeWorktree({ sessionId: signaledSession, repoRoot: signaled.root });
	}

	writeFileSync(fake.log, "");
	const ignoring = worktreeFixture();
	const ignoringSession = "ignore-term";
	writeAgents(ignoring.root);
	approve(ignoring.root, ignoring.worker, ignoringSession);
	const controller = new AbortController();
	try {
		const result = await withFakePi(
			fake,
			async () => {
				const pending = invoke(
					runner(ignoring.root, ignoringSession),
					{
						agent: "writer",
						task: "ignore SIGTERM",
						agentScope: "project",
						confirmProjectAgents: false,
					},
					controller.signal,
				);
				await waitFor(() => invocations(fake.log).length === 1, "the SIGTERM-ignoring child");
				controller.abort();
				return pending;
			},
			{ FAKE_PI_BEHAVIOR: "ignore-term" },
		);
		assert.equal(result.isError, true);
		assert.match(resultText(result), /terminated by SIGKILL after an abort request/);
		assert.equal(registry.worktreeHasLeases({ sessionId: ignoringSession, repoRoot: ignoring.root }), false);
		assertChildLaunchArgs(fake.log);
	} finally {
		registry.revokeWorktree({ sessionId: ignoringSession, repoRoot: ignoring.root });
	}
}

const previousPhase = process.env.PI_ROOT_PHASE;
process.env.PI_ROOT_PHASE = "execute";
try {
	const fake = fakePi({ extensionPath, packageDir });
	await testRootIdentityPropagatesAcrossLaunchModes(fake);
	writeFileSync(fake.log, "");
	await testNestedRootIdentityIsForwardedUnchanged(fake, packageDir);
	writeFileSync(fake.log, "");
	await testRootIdentityValidationFailsLoud(fake);
	writeFileSync(fake.log, "");
	await testReadOnlyExecution(fake);
	writeFileSync(fake.log, "");
	await testModelScopePassThrough(fake);
	writeFileSync(fake.log, "");
	await testApprovedWorktreeRoutesReviewers(fake);
	writeFileSync(fake.log, "");
	await testReadOnlyRejectsUnresolvedApproval(fake);
	writeFileSync(fake.log, "");
	await testWritableExecution(fake);
	writeFileSync(fake.log, "");
	await testMarkerlessWritableExecutionOutsideGit(fake);
	writeFileSync(fake.log, "");
	await testReadOnlyMcpAgentsLaunchOutsideGit(fake);
	writeFileSync(fake.log, "");
	await testResumeHydrationRoutesWritableAgent(fake);
	writeFileSync(fake.log, "");
	await testDeletedResumedWorktreeRejectsWritableAgent(fake);
	writeFileSync(fake.log, "");
	await testExecutionClassAndCwdPreflight(fake);
	writeFileSync(fake.log, "");
	await testParallelPreflightIsAtomic(fake);
	writeFileSync(fake.log, "");
	await testParallelReadOnlyExecution(fake);
	writeFileSync(fake.log, "");
	await testPlanPhaseDowngradesWorkers(fake);
	writeFileSync(fake.log, "");
	await testNonGitParentRejectsGitCwdOverride(fake);
	writeFileSync(fake.log, "");
	await testLeaseReleasesAfterSpawnFailure();
	writeFileSync(fake.log, "");
	await testConcurrentToolCallsShareOneLease(fake);
	writeFileSync(fake.log, "");
	await testSignalTerminationAndAbortEscalation(fake);
	console.log("subagent runner runtime harness: ok");
} finally {
	if (previousPhase === undefined) delete process.env.PI_ROOT_PHASE;
	else process.env.PI_ROOT_PHASE = previousPhase;
}
