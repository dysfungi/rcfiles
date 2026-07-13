#!/usr/bin/env node
/**
 * Direct runtime harness for the plan-mode extension.
 *
 * Pi exposes extension command handlers only through its runtime API. This
 * lightweight mock records that public registration surface, then invokes the
 * real handlers with controlled state so behavior can be tested without an LLM
 * turn or source-text assertions.
 */

import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [extensionPath, packageDir] = process.argv.slice(2);

if (!extensionPath || !packageDir) {
	throw new Error("Usage: plan_mode_runtime_harness.mjs <extension-path> <pi-package-dir>");
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
const { default: planModeExtension } = await jiti.import(resolve(extensionPath));
const extensionDir = dirname(resolve(extensionPath));
const { default: rootThreadGuard } = await jiti.import(resolve(extensionDir, "..", "root-thread-guard.ts"));
const bashSafety = await jiti.import(resolve(extensionDir, "bash-safety.ts"));
const mutationPolicy = await import(pathToFileURL(resolve(extensionDir, "..", "bash-mutation-policy.mjs")).href);

function createHarness({ entries = [], branchEntries = entries, idle = true, mode = "rpc", plan = true, sendFailure } = {}) {
	const commands = new Map();
	const events = new Map();
	const notifications = [];
	const statuses = [];
	const persistedEntries = [];
	const sentMessages = [];
	const initialTools = ["read", "bash", "edit", "write", "mcp", "external_tool"];
	const state = { activeTools: [...initialTools], idle };

	const pi = {
		appendEntry(customType, data) {
			persistedEntries.push({ customType, data });
		},
		getActiveTools() {
			return [...state.activeTools];
		},
		getFlag(name) {
			return name === "plan" && plan;
		},
		on(name, handler) {
			const handlers = events.get(name) ?? [];
			handlers.push(handler);
			events.set(name, handlers);
		},
		registerCommand(name, options) {
			commands.set(name, options);
		},
		registerEntryRenderer() {},
		registerFlag() {},
		registerShortcut() {},
		registerTool() {},
		sendUserMessage(message) {
			if (sendFailure) throw sendFailure;
			sentMessages.push({ message, activeTools: [...state.activeTools] });
		},
		setActiveTools(toolNames) {
			state.activeTools = [...toolNames];
		},
	};

	const ctx = {
		cwd: process.cwd(),
		isIdle: () => state.idle,
		mode,
		sessionManager: {
			getBranch: () => branchEntries,
			getEntries: () => entries,
			getSessionDir: () => join(process.cwd(), ".tmp", "pi", "sessions", "test"),
			getSessionId: () => "test",
		},
		ui: {
			custom: async () => undefined,
			notify: (message, type = "info") => notifications.push({ message, type }),
			setStatus: (key, value) => statuses.push({ key, value }),
			theme: { fg: (_color, text) => text },
		},
	};

	planModeExtension(pi);
	return { commands, ctx, events, initialTools, notifications, persistedEntries, pi, sentMessages, state, statuses };
}

async function emit(harness, eventName, event) {
	let result;
	for (const handler of harness.events.get(eventName) ?? []) {
		const nextResult = await handler(event, harness.ctx);
		if (nextResult !== undefined) result = nextResult;
	}
	return result;
}

async function startPlanMode(harness) {
	await emit(harness, "session_start", {});
}

async function runCommand(harness, name, args = "") {
	const command = harness.commands.get(name);
	assert.ok(command, `/${name} must be registered`);
	await command.handler(args, harness.ctx);
}

function contextMessage(customType, content = "[PLAN MODE ACTIVE]\ncontext") {
	return { role: "user", customType, content };
}

function testCommandRegistration() {
	const harness = createHarness();
	assert.ok(harness.commands.has("execute"), "/execute must be registered for the one-step implementation kickoff");
	assert.equal(harness.commands.has("implement"), false, "/implement must remain available to its prompt template");
}

async function testSelectorsAndToolSnapshots() {
	const harness = createHarness();
	await startPlanMode(harness);
	assert.deepEqual(harness.state.activeTools, ["read", "bash", "mcp", "external_tool", "grep", "find", "ls", "questionnaire", "plan_write"]);

	const beforeRepeatedPlan = {
		entries: harness.persistedEntries.length,
		notifications: harness.notifications.length,
		tools: [...harness.state.activeTools],
	};
	harness.state.activeTools.push("late_extension_tool");
	await runCommand(harness, "plan");
	assert.deepEqual(harness.state.activeTools, [...beforeRepeatedPlan.tools, "late_extension_tool"]);
	assert.equal(harness.persistedEntries.length, beforeRepeatedPlan.entries);
	assert.equal(harness.notifications.length, beforeRepeatedPlan.notifications);

	await runCommand(harness, "normal");
	assert.deepEqual(harness.state.activeTools, [...harness.initialTools, "late_extension_tool"]);
	assert.equal(harness.persistedEntries.at(-1).data.enabled, false);

	const toolsBeforeRepeatedNormal = [...harness.state.activeTools];
	const entriesBeforeRepeatedNormal = harness.persistedEntries.length;
	await runCommand(harness, "normal");
	assert.deepEqual(harness.state.activeTools, toolsBeforeRepeatedNormal);
	assert.equal(harness.persistedEntries.length, entriesBeforeRepeatedNormal);
}

async function testSessionStartGates() {
	for (const mode of ["tui", "rpc"]) {
		const harness = createHarness({ mode });
		await startPlanMode(harness);
		assert.notDeepEqual(harness.state.activeTools, harness.initialTools, `${mode} roots enable plan mode`);
	}

	for (const mode of ["json", "print"]) {
		const harness = createHarness({ mode });
		await startPlanMode(harness);
		assert.deepEqual(harness.state.activeTools, harness.initialTools, `${mode} workers stay writable`);
	}

	const previous = process.env.PI_SUBAGENT;
	process.env.PI_SUBAGENT = "1";
	try {
		const harness = createHarness({ mode: "tui" });
		await startPlanMode(harness);
		assert.deepEqual(harness.state.activeTools, harness.initialTools, "PI_SUBAGENT root stays writable");
	} finally {
		if (previous === undefined) delete process.env.PI_SUBAGENT;
		else process.env.PI_SUBAGENT = previous;
	}
}

async function testBranchLocalSessionRestore() {
	const branchWithPlanMode = createHarness({
		plan: false,
		entries: [{ type: "custom", customType: "plan-mode", data: { enabled: false } }],
		branchEntries: [{ type: "custom", customType: "plan-mode", data: { enabled: true } }],
	});
	await startPlanMode(branchWithPlanMode);
	assert.deepEqual(branchWithPlanMode.state.activeTools, [
		"read",
		"bash",
		"mcp",
		"external_tool",
		"grep",
		"find",
		"ls",
		"questionnaire",
		"plan_write",
	]);

	const branchWithNormalMode = createHarness({
		plan: false,
		entries: [{ type: "custom", customType: "plan-mode", data: { enabled: true } }],
		branchEntries: [{ type: "custom", customType: "plan-mode", data: { enabled: false } }],
	});
	await startPlanMode(branchWithNormalMode);
	assert.deepEqual(branchWithNormalMode.state.activeTools, branchWithNormalMode.initialTools);
}

async function testModeParsingAndIdleGuards() {
	const harness = createHarness();
	await startPlanMode(harness);
	const mode = harness.commands.get("mode");
	assert.deepEqual(mode.getArgumentCompletions(""), [
		{ value: "plan", label: "plan" },
		{ value: "normal", label: "normal" },
	]);
	assert.deepEqual(mode.getArgumentCompletions("P"), [{ value: "plan", label: "plan" }]);
	assert.equal(mode.getArgumentCompletions("plan extra"), null);

	await runCommand(harness, "mode");
	assert.deepEqual(harness.state.activeTools, harness.initialTools);
	await runCommand(harness, "mode", "PLAN");
	assert.equal(harness.persistedEntries.at(-1).data.enabled, true);

	const entriesBeforeInvalid = harness.persistedEntries.length;
	for (const args of ["p", "plan extra"]) {
		await runCommand(harness, "mode", args);
		assert.equal(harness.persistedEntries.length, entriesBeforeInvalid);
		assert.deepEqual(harness.notifications.at(-1), {
			message: "Usage: /mode [plan|normal] (use an exact full mode name).",
			type: "warning",
		});
	}

	harness.state.idle = false;
	const stateBeforeBusy = {
		entries: harness.persistedEntries.length,
		tools: [...harness.state.activeTools],
	};
	for (const command of ["plan", "normal", "mode", "execute"]) {
		await runCommand(harness, command, command === "mode" ? "normal" : "");
	}
	assert.equal(harness.persistedEntries.length, stateBeforeBusy.entries);
	assert.deepEqual(harness.state.activeTools, stateBeforeBusy.tools);
	assert.deepEqual(
		harness.notifications.slice(-4).map(({ message, type }) => ({ message, type })),
		["plan", "normal", "mode", "execute"].map((command) => ({
			message: `/${command} requires an idle agent. Wait for the current run to finish.`,
			type: "warning",
		})),
	);
}

async function testImplementationKickoffAndFailure() {
	const harness = createHarness();
	await startPlanMode(harness);
	await runCommand(harness, "execute", "  preserve the tests  ");
	assert.deepEqual(harness.state.activeTools, harness.initialTools);
	assert.deepEqual(harness.sentMessages, [
		{
			message: "Implement the approved plan now.\n\n--- Additional implementation instructions ---\npreserve the tests",
			activeTools: harness.initialTools,
		},
	]);

	const failed = createHarness({ sendFailure: new Error("offline") });
	await startPlanMode(failed);
	await runCommand(failed, "execute");
	assert.deepEqual(failed.state.activeTools, failed.initialTools);
	assert.deepEqual(failed.sentMessages, []);
	assert.deepEqual(failed.notifications.at(-1), {
		message: "Could not start implementation: offline. Normal mode remains active.",
		type: "error",
	});
}

async function testContextDeduplication() {
	const harness = createHarness();
	await startPlanMode(harness);
	const first = contextMessage("plan-mode-context", "[PLAN MODE ACTIVE]\nold structured context");
	const quotedMarker = contextMessage(undefined, "Please explain [PLAN MODE ACTIVE] to me.");
	const injected = await emit(harness, "before_agent_start", {});
	const legacy = { role: "user", ...injected.message };
	delete legacy.customType;
	const newest = contextMessage("plan-mode-context", "[PLAN MODE ACTIVE]\nnew structured context");
	const ordinary = { role: "user", content: "keep me" };
	const messages = [first, ordinary, quotedMarker, legacy, newest];
	const activeResult = await emit(harness, "context", { messages });
	assert.deepEqual(activeResult.messages, [ordinary, quotedMarker, newest]);

	await runCommand(harness, "normal");
	const normalResult = await emit(harness, "context", { messages });
	assert.deepEqual(normalResult.messages, [ordinary, quotedMarker]);
}

async function testBashPolicyParity() {
	await bashSafety.ensureParserLoaded();
	for (const subcommand of mutationPolicy.MUTATING_GIT_SUBCMDS) {
		assert.ok(
			bashSafety.checkPlanModeBash(`git ${subcommand}`),
			`plan mode must block the worktree policy's git ${subcommand}`,
		);
	}
	for (const command of ["env SAFE=1 git config --get user.name", "find . -delete", "bash -c true"]) {
		assert.ok(bashSafety.checkPlanModeBash(command), `plan mode must block ${command}`);
	}
	assert.equal(bashSafety.checkPlanModeBash("git status --short"), undefined);
	assert.equal(bashSafety.checkPlanModeBash("printf '>'"), undefined);
	assert.equal(bashSafety.checkPlanModeBash("printf 'literal ` backtick'"), undefined);
	assert.ok(bashSafety.checkPlanModeBash("echo `rm -f output`"));

	const harness = createHarness();
	await startPlanMode(harness);
	const blocked = await emit(harness, "tool_call", {
		toolName: "bash",
		input: { command: "git config --get user.name" },
	});
	assert.match(blocked.reason, /Plan mode: command blocked/);
}

async function testRootThreadPolicyComposition() {
	const harness = createHarness({ mode: "rpc" });
	rootThreadGuard(harness.pi);
	await startPlanMode(harness);
	assert.ok(harness.state.activeTools.includes("bash"), "plan mode preserves nominal Bash composition");
	assert.ok(harness.state.activeTools.includes("mcp"), "plan mode preserves nominal MCP composition");

	const bash = await emit(harness, "tool_call", {
		toolName: "bash",
		input: { command: "git status --short" },
	});
	const mcp = await emit(harness, "tool_call", { toolName: "mcp", input: {} });
	assert.match(bash.reason, /root-thread context discipline/);
	assert.match(mcp.reason, /root-thread context discipline/);

	const fixtureRoot = await mkdtemp(join(tmpdir(), "pi-global-skills-"));
	const agentDir = join(fixtureRoot, ".pi", "agent");
	const skillFile = join(agentDir, "skills", "fixture", "SKILL.md");
	const previousAgentDir = process.env.PI_CODING_AGENT_DIR;
	await mkdir(dirname(skillFile), { recursive: true });
	await writeFile(skillFile, "# fixture skill\n");
	process.env.PI_CODING_AGENT_DIR = agentDir;
	try {
		const allowed =
			(await emit(harness, "tool_call", {
				toolName: "read",
				input: { path: skillFile },
			})) === undefined;
		assert.equal(allowed, true, "root reads under the global skill root must be allowed");
	} finally {
		if (previousAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR;
		else process.env.PI_CODING_AGENT_DIR = previousAgentDir;
		await rm(fixtureRoot, { recursive: true, force: true });
	}
}

testCommandRegistration();
await testSelectorsAndToolSnapshots();
await testSessionStartGates();
await testBranchLocalSessionRestore();
await testModeParsingAndIdleGuards();
await testImplementationKickoffAndFailure();
await testContextDeduplication();
await testBashPolicyParity();
await testRootThreadPolicyComposition();
console.log("plan-mode runtime handler harness: ok");
