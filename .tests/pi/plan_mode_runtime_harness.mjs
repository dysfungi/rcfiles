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
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
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

function createHarness({ entries = [], idle = true, sendFailure } = {}) {
	const commands = new Map();
	const events = new Map();
	const notifications = [];
	const statuses = [];
	const persistedEntries = [];
	const sentMessages = [];
	const initialTools = ["read", "bash", "edit", "write", "external_tool"];
	const state = { activeTools: [...initialTools], idle };

	const pi = {
		appendEntry(customType, data) {
			persistedEntries.push({ customType, data });
		},
		getActiveTools() {
			return [...state.activeTools];
		},
		getFlag(name) {
			return name === "plan";
		},
		on(name, handler) {
			events.set(name, handler);
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
		mode: "rpc",
		sessionManager: {
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
	return { commands, ctx, events, initialTools, notifications, persistedEntries, sentMessages, state, statuses };
}

async function startPlanMode(harness) {
	await harness.events.get("session_start")({}, harness.ctx);
}

async function runCommand(harness, name, args = "") {
	const command = harness.commands.get(name);
	assert.ok(command, `/${name} must be registered`);
	await command.handler(args, harness.ctx);
}

function contextMessage(customType, content = "[PLAN MODE ACTIVE]\ncontext") {
	return { role: "user", customType, content };
}

async function testSelectorsAndToolSnapshots() {
	const harness = createHarness();
	await startPlanMode(harness);
	assert.deepEqual(harness.state.activeTools, ["read", "bash", "external_tool", "grep", "find", "ls", "questionnaire", "plan_write"]);

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

async function testSubagentGate() {
	const previous = process.env.PI_SUBAGENT;
	process.env.PI_SUBAGENT = "1";
	try {
		const harness = createHarness();
		await startPlanMode(harness);
		assert.deepEqual(harness.state.activeTools, harness.initialTools);
	} finally {
		if (previous === undefined) delete process.env.PI_SUBAGENT;
		else process.env.PI_SUBAGENT = previous;
	}
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
	await runCommand(harness, "mode", "p");
	assert.equal(harness.persistedEntries.length, entriesBeforeInvalid);
	assert.equal(harness.notifications.at(-1).type, "warning");

	harness.state.idle = false;
	const stateBeforeBusy = {
		entries: harness.persistedEntries.length,
		tools: [...harness.state.activeTools],
	};
	for (const command of ["plan", "normal", "mode", "execute", "implement"]) {
		await runCommand(harness, command, command === "mode" ? "normal" : "");
	}
	assert.equal(harness.persistedEntries.length, stateBeforeBusy.entries);
	assert.deepEqual(harness.state.activeTools, stateBeforeBusy.tools);
	assert.deepEqual(
		harness.notifications.slice(-5).map(({ message, type }) => ({ message, type })),
		["plan", "normal", "mode", "execute", "implement"].map((command) => ({
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
	await runCommand(failed, "implement");
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
	const legacy = contextMessage(undefined, "[PLAN MODE ACTIVE]\nold user-text context");
	const newest = contextMessage("plan-mode-context", "[PLAN MODE ACTIVE]\nnew structured context");
	const ordinary = { role: "user", content: "keep me" };
	const activeResult = await harness.events.get("context")({ messages: [first, ordinary, legacy, newest] }, harness.ctx);
	assert.deepEqual(activeResult.messages, [ordinary, newest]);

	await runCommand(harness, "normal");
	const normalResult = await harness.events.get("context")({ messages: [first, ordinary, legacy, newest] }, harness.ctx);
	assert.deepEqual(normalResult.messages, [ordinary]);
}

await testSelectorsAndToolSnapshots();
await testSubagentGate();
await testModeParsingAndIdleGuards();
await testImplementationKickoffAndFailure();
await testContextDeduplication();
console.log("plan-mode runtime handler harness: ok");
