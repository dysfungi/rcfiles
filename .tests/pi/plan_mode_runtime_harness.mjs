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
import { rmSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [planModeExtensionPath, questionnaireExtensionPath, packageDir] = process.argv.slice(2);

if (!planModeExtensionPath || !questionnaireExtensionPath || !packageDir) {
	throw new Error(
		"Usage: plan_mode_runtime_harness.mjs <plan-mode-extension-path> <questionnaire-extension-path> <pi-package-dir>",
	);
}

const require = createRequire(pathToFileURL(join(packageDir, "package.json")));
const createJiti = require("jiti");
const nodeModules = join(packageDir, "node_modules");
const realIndexFile = join(packageDir, "dist", "index.js");
const clipboardStubDir = await mkdtemp(join(tmpdir(), "pi-plan-clipboard-stub-"));
const clipboardStubFile = join(clipboardStubDir, "index.mjs");
await writeFile(
	clipboardStubFile,
	[
		`export * from ${JSON.stringify(pathToFileURL(realIndexFile).href)};`,
		"export const copyToClipboardCalls = [];",
		"let clipboardMode = 'immediate';",
		"let nextFailure = null;",
		"const pendingClipboardResolvers = [];",
		"export function setClipboardFailure(error) { nextFailure = error; }",
		"export function setClipboardPending() { clipboardMode = 'pending'; }",
		"export function resolvePendingClipboardCopies() {",
		"\tfor (const resolve of pendingClipboardResolvers.splice(0)) resolve();",
		"}",
		"export function resetClipboardStub() {",
		"\tcopyToClipboardCalls.length = 0;",
		"\tclipboardMode = 'immediate';",
		"\tnextFailure = null;",
		"\tpendingClipboardResolvers.length = 0;",
		"}",
		"export function copyToClipboard(text) {",
		"\tcopyToClipboardCalls.push(text);",
		"\tif (nextFailure) {",
		"\t\tconst error = nextFailure;",
		"\t\tnextFailure = null;",
		"\t\treturn Promise.reject(error);",
		"\t}",
		"\tif (clipboardMode === 'pending') {",
		"\t\treturn new Promise((resolve) => pendingClipboardResolvers.push(resolve));",
		"\t}",
		"\treturn Promise.resolve();",
		"}",
		"",
	].join("\n"),
);

function cleanupClipboardStub() {
	try {
		rmSync(clipboardStubDir, { recursive: true, force: true });
	} catch {}
}

process.once("exit", cleanupClipboardStub);

const {
	copyToClipboardCalls,
	resetClipboardStub,
	resolvePendingClipboardCopies,
	setClipboardFailure,
	setClipboardPending,
} = await import(pathToFileURL(clipboardStubFile).href);
const jiti = createJiti(import.meta.url, {
	alias: {
		"@earendil-works/pi-coding-agent": clipboardStubFile,
		"@earendil-works/pi-tui": join(nodeModules, "@earendil-works", "pi-tui", "dist", "index.js"),
		typebox: join(nodeModules, "typebox", "build", "index.mjs"),
	},
});
const themeModule = await import(
	pathToFileURL(join(packageDir, "dist", "modes", "interactive", "theme", "theme.js")).href,
);
const tuiModule = await import(
	pathToFileURL(join(nodeModules, "@earendil-works", "pi-tui", "dist", "index.js")).href,
);
const { KeybindingsManager } = await import(
	pathToFileURL(join(packageDir, "dist", "core", "keybindings.js")).href,
);
const { TUI } = tuiModule;
const { initTheme, theme: globalTheme } = themeModule;
const { default: planModeExtension } = await jiti.import(resolve(planModeExtensionPath));
const { default: questionnaireExtension } = await jiti.import(resolve(questionnaireExtensionPath));
const extensionDir = dirname(resolve(planModeExtensionPath));
const { default: rootThreadGuard } = await jiti.import(resolve(extensionDir, "..", "root-thread-guard.ts"));
const bashSafety = await jiti.import(resolve(extensionDir, "bash-safety.ts"));
const mutationPolicy = await import(pathToFileURL(resolve(extensionDir, "..", "bash-mutation-policy.mjs")).href);

function createPlanPagerFixture(cancelKeys) {
	initTheme("dark");
	const terminal = {
		columns: 80,
		rows: 24,
		kittyProtocolActive: true,
		start() {},
		stop() {},
		async drainInput() {},
		write() {},
		moveBy() {},
		hideCursor() {},
		showCursor() {},
		clearLine() {},
		clearFromCursor() {},
		clearScreen() {},
		setTitle() {},
		setProgress() {},
	};
	const tui = new TUI(terminal);
	let renderRequests = 0;
	tui.requestRender = () => {
		renderRequests += 1;
	};
	return {
		keybindings: new KeybindingsManager({ "tui.select.cancel": cancelKeys }),
		theme: globalTheme,
		tui,
		getRenderRequests: () => renderRequests,
	};
}

function stripAnsi(value) {
	return value.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
}

function getPlanPagerProgress(component) {
	const header = stripAnsi(component.render(160).at(0));
	component.render(80);
	const match = header.match(/(\d+)-(\d+) \/ (\d+)\s*$/);
	assert.ok(match, `plan pager header must contain progress: ${header}`);
	return {
		start: Number(match[1]),
		end: Number(match[2]),
		total: Number(match[3]),
	};
}

function createHarness({
	entries = [],
	branchEntries = entries,
	idle = true,
	mode = "rpc",
	plan = true,
	sendFailure,
	sessionDir = join(process.cwd(), ".tmp", "pi", "sessions", "test"),
	planPagerFixture,
} = {}) {
	const commands = new Map();
	const events = new Map();
	const notifications = [];
	const statuses = [];
	const persistedEntries = [];
	const sentMessages = [];
	const customRequests = [];
	let customCallCount = 0;
	const nativeToolNames = ["read", "bash", "edit", "write", "grep", "find", "ls"];
	const registeredTools = new Map(
		[...nativeToolNames, "mcp", "external_tool"].map((name) => [name, { name }]),
	);
	let resolveCustomRequest;
	const customRequestReady = new Promise((resolveRequest) => {
		resolveCustomRequest = resolveRequest;
	});
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
		registerTool(tool) {
			registeredTools.set(tool.name, tool);
		},
		sendUserMessage(message) {
			if (sendFailure) throw sendFailure;
			sentMessages.push({ message, activeTools: [...state.activeTools] });
		},
		setActiveTools(toolNames) {
			state.activeTools = toolNames.filter((name) => registeredTools.has(name));
		},
	};

	const ctx = {
		cwd: process.cwd(),
		isIdle: () => state.idle,
		mode,
		sessionManager: {
			getBranch: () => branchEntries,
			getEntries: () => entries,
			getSessionDir: () => sessionDir,
			getSessionId: () => "test",
		},
		ui: {
			custom: async (factory, options) => {
				customCallCount += 1;
				if (!planPagerFixture) return undefined;
				let resolveResult;
				const result = new Promise((resolveResultValue) => {
					resolveResult = resolveResultValue;
				});
				const request = { component: undefined, done: undefined, doneCalls: 0, options };
				const done = (value) => {
					request.doneCalls += 1;
					resolveResult(value);
				};
				request.done = done;
				request.component = await factory(
					planPagerFixture.tui,
					planPagerFixture.theme,
					planPagerFixture.keybindings,
					done,
				);
				customRequests.push(request);
				resolveCustomRequest(request);
				return result;
			},
			notify: (message, type = "info") => notifications.push({ message, type }),
			setStatus: (key, value) => statuses.push({ key, value }),
			theme: { fg: (_color, text) => text },
		},
	};

	planModeExtension(pi);
	questionnaireExtension(pi);
	return {
		commands,
		ctx,
		customRequestReady,
		customRequests,
		events,
		getCustomCallCount: () => customCallCount,
		initialTools,
		notifications,
		persistedEntries,
		pi,
		registeredTools,
		sentMessages,
		state,
		statuses,
	};
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

function testUnregisteredToolsAreSilentlyDropped() {
	const harness = createHarness();
	harness.pi.setActiveTools(["read", "synthetic_bogus_name"]);
	assert.deepEqual(harness.state.activeTools, ["read"]);
}

function testCommandRegistration() {
	const harness = createHarness();
	assert.ok(harness.commands.has("execute"), "/execute must be registered for the one-step implementation kickoff");
	assert.equal(harness.commands.has("implement"), false, "/implement must remain available to its prompt template");
}

async function testQuestionnaireNonUiErrorPaths() {
	const nonInteractiveHarness = createHarness({ mode: "rpc" });
	const questionnaire = nonInteractiveHarness.registeredTools.get("questionnaire");
	assert.ok(questionnaire, "questionnaire must register with Pi");

	const nonInteractiveResult = await questionnaire.execute(
		"non-interactive-questionnaire",
		{
			questions: [
				{
					id: "scope",
					label: "Scope",
					prompt: "What should change?",
					options: [{ value: "small", label: "Small" }],
				},
			],
		},
		undefined,
		undefined,
		nonInteractiveHarness.ctx,
	);
	assert.deepEqual(nonInteractiveResult, {
		content: [{ type: "text", text: "Error: UI not available (running in non-interactive mode)" }],
		details: { questions: [], answers: [], cancelled: true },
	});
	assert.equal(nonInteractiveHarness.getCustomCallCount(), 0, "non-interactive execution must not open a custom UI");

	const emptyQuestionsHarness = createHarness({ mode: "tui" });
	const emptyQuestionsQuestionnaire = emptyQuestionsHarness.registeredTools.get("questionnaire");
	assert.ok(emptyQuestionsQuestionnaire, "questionnaire must register with Pi");
	const emptyQuestionsResult = await emptyQuestionsQuestionnaire.execute(
		"empty-questionnaire",
		{ questions: [] },
		undefined,
		undefined,
		emptyQuestionsHarness.ctx,
	);
	assert.deepEqual(emptyQuestionsResult, {
		content: [{ type: "text", text: "Error: No questions provided" }],
		details: { questions: [], answers: [], cancelled: true },
	});
	assert.equal(emptyQuestionsHarness.getCustomCallCount(), 0, "empty questionnaires must not open a custom UI");
}

async function testSelectorsAndToolSnapshots() {
	const harness = createHarness();
	const baselineTools = [...harness.initialTools];
	assert.equal(baselineTools.includes("questionnaire"), false, "questionnaire is absent before plan mode");
	assert.equal(baselineTools.includes("plan_write"), false, "plan_write is absent before plan mode");

	await startPlanMode(harness);
	assert.deepEqual(harness.state.activeTools, [
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
	assert.ok(harness.state.activeTools.includes("questionnaire"), "questionnaire is active in plan mode");
	assert.ok(harness.state.activeTools.includes("plan_write"), "plan_write is active in plan mode");

	await runCommand(harness, "normal");
	assert.deepEqual(harness.state.activeTools, baselineTools, "normal mode restores the exact baseline tool set");
	assert.equal(harness.persistedEntries.at(-1).data.enabled, false);

	await runCommand(harness, "plan");
	const beforeRepeatedPlan = {
		entries: harness.persistedEntries.length,
		notifications: harness.notifications.length,
		tools: [...harness.state.activeTools],
	};
	harness.pi.registerTool({ name: "late_extension_tool" });
	harness.state.activeTools.push("late_extension_tool");
	await runCommand(harness, "plan");
	assert.deepEqual(harness.state.activeTools, [...beforeRepeatedPlan.tools, "late_extension_tool"]);
	assert.equal(harness.persistedEntries.length, beforeRepeatedPlan.entries);
	assert.equal(harness.notifications.length, beforeRepeatedPlan.notifications);

	await runCommand(harness, "normal");
	assert.deepEqual(harness.state.activeTools, [...baselineTools, "late_extension_tool"]);
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
		assert.deepEqual(harness.state.activeTools, harness.initialTools, `${mode} sessions keep the plan-mode extension inert`);
	}

	const previous = process.env.PI_SUBAGENT;
	process.env.PI_SUBAGENT = "1";
	try {
		const harness = createHarness({ mode: "tui" });
		await startPlanMode(harness);
		assert.deepEqual(harness.state.activeTools, harness.initialTools, "PI_SUBAGENT sessions keep the plan-mode extension inert");
	} finally {
		if (previous === undefined) delete process.env.PI_SUBAGENT;
		else process.env.PI_SUBAGENT = previous;
	}
}

async function testModeEnvironmentPropagation() {
	const previous = process.env.PI_MODE;
	const previousSubagent = process.env.PI_SUBAGENT;
	try {
		delete process.env.PI_MODE;
		const planned = createHarness();
		await startPlanMode(planned);
		assert.equal(process.env.PI_MODE, "plan", "session start records the default plan mode");
		await runCommand(planned, "execute");
		assert.equal(process.env.PI_MODE, "normal", "/execute records normal mode before launching work");
		await runCommand(planned, "plan");
		assert.equal(process.env.PI_MODE, "plan", "/plan records plan mode");
		await runCommand(planned, "normal");
		assert.equal(process.env.PI_MODE, "normal", "/normal records normal mode");
		await runCommand(planned, "plan");
		assert.equal(process.env.PI_MODE, "plan", "plan-normal-plan cycles update the inherited mode");

		const normal = createHarness({ plan: false });
		await startPlanMode(normal);
		assert.equal(process.env.PI_MODE, "normal", "session start records normal mode when plan is disabled");

		process.env.PI_MODE = "plan";
		process.env.PI_SUBAGENT = "1";
		const child = createHarness({ mode: "tui" });
		await startPlanMode(child);
		assert.equal(process.env.PI_MODE, "plan", "inert child plan-mode extensions preserve the inherited root mode");
	} finally {
		if (previous === undefined) delete process.env.PI_MODE;
		else process.env.PI_MODE = previous;
		if (previousSubagent === undefined) delete process.env.PI_SUBAGENT;
		else process.env.PI_SUBAGENT = previousSubagent;
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

async function openPlanPager(cancelKeys) {
	const fixtureRoot = await mkdtemp(join(tmpdir(), "pi-plan-pager-"));
	const agentDir = join(fixtureRoot, "agent");
	const sessionDir = join(agentDir, "sessions", "test");
	await mkdir(join(agentDir, "plans"), { recursive: true });
	const planContent = ["# Plan", ...Array.from({ length: 48 }, (_, index) => `Step ${index + 1}`)].join("\n");
	await writeFile(join(agentDir, "plans", "test.md"), planContent);

	const planPagerFixture = createPlanPagerFixture(cancelKeys);
	assert.equal(planPagerFixture.tui.terminal.columns, 80, "pager TUI has a concrete width");
	assert.equal(planPagerFixture.tui.terminal.rows, 24, "pager TUI has a concrete height");
	const harness = createHarness({ mode: "tui", planPagerFixture, sessionDir });
	const command = runCommand(harness, "plan-show");
	const request = await harness.customRequestReady;
	assert.ok(request.component, "plan pager custom factory returned a component");

	return {
		command,
		fixtureRoot,
		planContent,
		planPagerFixture,
		request,
		async close() {
			try {
				if (request.doneCalls === 0) request.component.handleInput("q");
				if (request.doneCalls === 0) request.done(undefined);
				await command;
			} finally {
				await rm(fixtureRoot, { recursive: true, force: true });
			}
		},
	};
}

async function testPlanPagerCancellationBindings() {
	const defaultCancelKeys = ["escape", "ctrl+c", "ctrl+["];

	const escape = await openPlanPager(defaultCancelKeys);
	try {
		escape.request.component.handleInput("\x1b");
		escape.request.component.handleInput("\x1b");
		assert.equal(escape.request.doneCalls, 1, "raw Escape completes the pager once through tui.select.cancel");
		await escape.command;
	} finally {
		await escape.close();
	}

	const ctrlC = await openPlanPager(defaultCancelKeys);
	try {
		ctrlC.request.component.handleInput("\x03");
		ctrlC.request.component.handleInput("\x03");
		assert.equal(ctrlC.request.doneCalls, 1, "Ctrl+C completes the pager once through tui.select.cancel");
		await ctrlC.command;
	} finally {
		await ctrlC.close();
	}

	const csi = await openPlanPager(defaultCancelKeys);
	try {
		const footer = stripAnsi(csi.request.component.render(80).at(-1));
		assert.match(footer, /escape\/ctrl\+c\/ctrl\+\[\/q close/);
		csi.request.component.handleInput("\x1b[91;5u");
		csi.request.component.handleInput("\x1b[91;5u");
		assert.equal(csi.request.doneCalls, 1, "CSI-u Ctrl+[ completes the pager once");
		await csi.command;
	} finally {
		await csi.close();
	}

	const q = await openPlanPager(defaultCancelKeys);
	try {
		q.request.component.handleInput("q");
		assert.equal(q.request.doneCalls, 1, "q remains a pager close fallback");
		await q.command;
	} finally {
		await q.close();
	}

	const navigation = await openPlanPager(defaultCancelKeys);
	try {
		navigation.request.component.handleInput("\x1b[B");
		assert.equal(navigation.request.doneCalls, 0, "navigation does not close the pager");
		assert.equal(navigation.planPagerFixture.getRenderRequests(), 1, "navigation requests a render");
	} finally {
		await navigation.close();
	}

	const halfPage = await openPlanPager(defaultCancelKeys);
	try {
		const page = Math.max(1, halfPage.planPagerFixture.tui.terminal.rows - 2);
		const halfPageDelta = Math.max(1, Math.ceil(page / 2));
		assert.equal(halfPageDelta, 11, "fixed pager terminal has an 11-line half page");
		assert.match(
			stripAnsi(halfPage.request.component.render(160).at(-1)),
			/Ctrl\+d\/Ctrl\+u half-page/,
			"footer documents half-page controls",
		);

		const before = getPlanPagerProgress(halfPage.request.component);
		const rendersBefore = halfPage.planPagerFixture.getRenderRequests();
		halfPage.request.component.handleInput("\x04");
		const afterDown = getPlanPagerProgress(halfPage.request.component);
		assert.equal(afterDown.start - before.start, halfPageDelta, "Ctrl+D advances by exactly half a page");
		assert.equal(afterDown.end - before.end, halfPageDelta, "Ctrl+D advances the viewport by exactly half a page");
		assert.equal(afterDown.total, before.total, "Ctrl+D preserves the rendered document length");
		assert.equal(halfPage.request.doneCalls, 0, "Ctrl+D does not close the pager");
		assert.equal(
			halfPage.planPagerFixture.getRenderRequests(),
			rendersBefore + 1,
			"Ctrl+D requests a render after moving",
		);

		halfPage.request.component.handleInput("\x15");
		const afterUp = getPlanPagerProgress(halfPage.request.component);
		assert.equal(afterDown.start - afterUp.start, halfPageDelta, "Ctrl+U reverses exactly half a page");
		assert.equal(afterDown.end - afterUp.end, halfPageDelta, "Ctrl+U restores the viewport by exactly half a page");
		assert.equal(halfPage.request.doneCalls, 0, "Ctrl+U does not close the pager");
		assert.equal(
			halfPage.planPagerFixture.getRenderRequests(),
			rendersBefore + 2,
			"Ctrl+U requests a render after moving",
		);

		const rendersAtTop = halfPage.planPagerFixture.getRenderRequests();
		halfPage.request.component.handleInput("\x15");
		assert.deepEqual(getPlanPagerProgress(halfPage.request.component), before, "Ctrl+U at the top stays clamped");
		assert.equal(
			halfPage.planPagerFixture.getRenderRequests(),
			rendersAtTop,
			"a clamped Ctrl+U does not request a render",
		);
	} finally {
		await halfPage.close();
	}

	const emptyCancel = await openPlanPager([]);
	try {
		const footer = stripAnsi(emptyCancel.request.component.render(80).at(-1));
		assert.match(footer, /q close/);
		assert.doesNotMatch(footer, /escape|ctrl\+c|ctrl\+\[/);
		emptyCancel.request.component.handleInput("\x1b");
		assert.equal(emptyCancel.request.doneCalls, 0, "empty cancel bindings leave Escape unclaimed");
		emptyCancel.request.component.handleInput("q");
		assert.equal(emptyCancel.request.doneCalls, 1, "q closes with empty cancel bindings");
		await emptyCancel.command;
	} finally {
		await emptyCancel.close();
	}

	const deduplicatedQ = await openPlanPager(["q"]);
	try {
		const footer = stripAnsi(deduplicatedQ.request.component.render(80).at(-1));
		assert.match(footer, /q close/);
		assert.doesNotMatch(footer, /q\/q close/);
	} finally {
		await deduplicatedQ.close();
	}
}

async function flushClipboard() {
	await new Promise((resolveFlush) => setImmediate(resolveFlush));
}

async function testPlanPagerClipboardCopy() {
	const defaultCancelKeys = ["escape", "ctrl+c", "ctrl+["];

	resetClipboardStub();
	const success = await openPlanPager(defaultCancelKeys);
	try {
		assert.match(stripAnsi(success.request.component.render(80).at(-1)), /c copy/);
		success.request.component.handleInput("c");
		assert.match(stripAnsi(success.request.component.render(80).at(-1)), /Copying…/);
		await flushClipboard();
		assert.deepEqual(copyToClipboardCalls, [success.planContent], "copying uses the full raw plan content");
		assert.match(stripAnsi(success.request.component.render(80).at(-1)), /✓ Copied/);
	} finally {
		await success.close();
	}

	resetClipboardStub();
	setClipboardPending();
	const reentry = await openPlanPager(defaultCancelKeys);
	try {
		reentry.request.component.handleInput("c");
		reentry.request.component.handleInput("c");
		assert.equal(copyToClipboardCalls.length, 1, "copying ignores repeated c input while a copy is pending");
		resolvePendingClipboardCopies();
		await flushClipboard();
	} finally {
		await reentry.close();
	}

	resetClipboardStub();
	setClipboardFailure(new Error("boom"));
	const failure = await openPlanPager(defaultCancelKeys);
	try {
		failure.request.component.handleInput("c");
		await flushClipboard();
		assert.match(stripAnsi(failure.request.component.render(80).at(-1)), /✗ Copy failed: boom/);
		assert.equal(failure.request.doneCalls, 0, "a failed copy leaves the pager open");
	} finally {
		await failure.close();
	}

	resetClipboardStub();
	const conflict = await openPlanPager(["c"]);
	try {
		assert.doesNotMatch(stripAnsi(conflict.request.component.render(80).at(-1)), /copy/i);
		conflict.request.component.handleInput("c");
		assert.equal(conflict.request.doneCalls, 1, "c keeps its configured cancel behavior");
		assert.deepEqual(copyToClipboardCalls, [], "configured cancellation does not invoke the clipboard");
		await conflict.command;
	} finally {
		await conflict.close();
	}

	resetClipboardStub();
	setClipboardPending();
	const copyThenClose = await openPlanPager(defaultCancelKeys);
	try {
		copyThenClose.request.component.handleInput("c");
		assert.match(stripAnsi(copyThenClose.request.component.render(80).at(-1)), /Copying…/);
		copyThenClose.request.component.handleInput("q");
		assert.equal(copyThenClose.request.doneCalls, 1, "q closes an in-flight copy once");
		const renderRequestsAfterClose = copyThenClose.planPagerFixture.getRenderRequests();
		resolvePendingClipboardCopies();
		await flushClipboard();
		assert.deepEqual(copyToClipboardCalls, [copyThenClose.planContent]);
		assert.equal(
			copyThenClose.planPagerFixture.getRenderRequests(),
			renderRequestsAfterClose,
			"settled clipboard work does not render after the pager closes",
		);
		await copyThenClose.command;
	} finally {
		await copyThenClose.close();
	}
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

try {
	testUnregisteredToolsAreSilentlyDropped();
	testCommandRegistration();
	await testQuestionnaireNonUiErrorPaths();
	await testSelectorsAndToolSnapshots();
	await testSessionStartGates();
	await testModeEnvironmentPropagation();
	await testBranchLocalSessionRestore();
	await testModeParsingAndIdleGuards();
	await testImplementationKickoffAndFailure();
	await testContextDeduplication();
	await testBashPolicyParity();
	await testPlanPagerCancellationBindings();
	await testPlanPagerClipboardCopy();
	await testRootThreadPolicyComposition();
	console.log("plan-mode runtime handler harness: ok");
} finally {
	cleanupClipboardStub();
}
