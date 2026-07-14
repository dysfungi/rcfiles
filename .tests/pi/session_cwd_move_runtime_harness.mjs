#!/usr/bin/env node
/** Runtime tests for the managed /cwd session-fork command. */

import assert from "node:assert/strict";
import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	readdirSync,
	realpathSync,
	rmSync,
	symlinkSync,
	writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [extensionPath, packageDir] = process.argv.slice(2);

if (!extensionPath || !packageDir) {
	throw new Error("Usage: session_cwd_move_runtime_harness.mjs <extension-path> <pi-package-dir>");
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
const {
	SessionManager,
	SettingsManager,
	createAgentSessionFromServices,
	createAgentSessionRuntime,
	createAgentSessionServices,
} = await import(pathToFileURL(join(packageDir, "dist", "index.js")).href);
const { default: sessionCwdMove } = await jiti.import(resolve(extensionPath));

function createFixture({ usesDefaultSessionDir = false } = {}) {
	const root = mkdtempSync(join(tmpdir(), "pi-cwd-move-"));
	const sourceCwd = join(root, "source");
	const sessionDir = join(root, "sessions");
	mkdirSync(sourceCwd);
	const sessionManager = usesDefaultSessionDir
		? SessionManager.create(sourceCwd)
		: SessionManager.create(sourceCwd, sessionDir);
	sessionManager.appendCustomEntry("fixture-history", { copied: true });
	sessionManager.appendMessage({
		role: "assistant",
		content: [{ type: "text", text: "fixture history" }],
		api: "fixture",
		provider: "fixture",
		model: "fixture",
		usage: {
			input: 0,
			output: 0,
			cacheRead: 0,
			cacheWrite: 0,
			totalTokens: 0,
			cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
		},
		stopReason: "stop",
		timestamp: Date.now(),
	});
	const sessionFile = sessionManager.getSessionFile();
	assert.ok(sessionFile, "fixture source session must be persisted");
	return { root, sourceCwd, sessionDir: sessionManager.getSessionDir(), sessionFile, sessionManager };
}

function readSession(sessionFile) {
	return readFileSync(sessionFile, "utf8")
		.trim()
		.split("\n")
		.map((line) => JSON.parse(line));
}

function sessionFiles(sessionDir) {
	return readdirSync(sessionDir)
		.filter((entry) => entry.endsWith(".jsonl"))
		.sort();
}

function spyOnForkFrom() {
	const originalForkFrom = SessionManager.forkFrom;
	const calls = [];
	SessionManager.forkFrom = (...args) => {
		calls.push(args);
		return Reflect.apply(originalForkFrom, SessionManager, args);
	};
	return {
		calls,
		restore: () => {
			SessionManager.forkFrom = originalForkFrom;
		},
	};
}

// Controlled contexts cover command-owned decisions; the real runtime replacement path is tested below.
function createHarness({ cwd, sessionManager, idle = true, cancelled = false }) {
	const commands = new Map();
	const notifications = [];
	const newSessionNotifications = [];
	const switches = [];
	const pi = {
		registerCommand(name, options) {
			commands.set(name, options);
		},
	};
	const ctx = {
		cwd,
		isIdle: () => idle,
		sessionManager,
		switchSession: async (sessionPath, options) => {
			switches.push(sessionPath);
			if (cancelled) return { cancelled: true };
			await options?.withSession?.({
				ui: {
					notify: (message, type = "info") => newSessionNotifications.push({ message, type }),
				},
			});
			return { cancelled: false };
		},
		ui: {
			notify: (message, type = "info") => notifications.push({ message, type }),
		},
	};

	sessionCwdMove(pi);
	return { commands, ctx, newSessionNotifications, notifications, switches };
}

async function runCommand(harness, args = "") {
	const command = harness.commands.get("cwd");
	assert.ok(command, "/cwd must be registered");
	await command.handler(args, harness.ctx);
}

// AgentSessionRuntime is the session-replacement layer shared by Pi's TUI and RPC modes.
async function createRuntimeHarness({ cwd, agentDir, sessionManager, extensionErrors }) {
	const createRuntime = async ({
		cwd: runtimeCwd,
		agentDir: runtimeAgentDir,
		sessionManager: runtimeSessionManager,
		sessionStartEvent,
	}) => {
		const services = await createAgentSessionServices({
			cwd: runtimeCwd,
			agentDir: runtimeAgentDir,
			settingsManager: SettingsManager.inMemory({ compaction: { enabled: false } }),
			resourceLoaderOptions: {
				extensionFactories: [sessionCwdMove],
				noContextFiles: true,
				noExtensions: true,
				noPromptTemplates: true,
				noSkills: true,
				noThemes: true,
			},
		});
		return {
			...(await createAgentSessionFromServices({
				services,
				sessionManager: runtimeSessionManager,
				sessionStartEvent,
				noTools: "all",
			})),
			services,
			diagnostics: services.diagnostics,
		};
	};

	const runtime = await createAgentSessionRuntime(createRuntime, { cwd, agentDir, sessionManager });
	const rebindSession = async () => {
		const session = runtime.session;
		await session.bindExtensions({
			mode: "print",
			commandContextActions: {
				waitForIdle: () => session.waitForIdle(),
				newSession: async (options) => runtime.newSession(options),
				fork: async (entryId, options) => {
					const result = await runtime.fork(entryId, options);
					return { cancelled: result.cancelled };
				},
				navigateTree: async (targetId, options) => {
					const result = await session.navigateTree(targetId, options);
					return { cancelled: result.cancelled };
				},
				switchSession: async (sessionPath, options) => runtime.switchSession(sessionPath, options),
				reload: async () => {
					await session.reload();
				},
			},
			onError: (error) => extensionErrors.push(error),
		});
	};

	runtime.setRebindSession(rebindSession);
	await rebindSession();
	return runtime;
}

function cleanup(root) {
	rmSync(root, { recursive: true, force: true });
}

function testCommandRegistration() {
	const harness = createHarness({
		cwd: process.cwd(),
		sessionManager: {
			getSessionFile: () => undefined,
			getSessionDir: () => "",
			usesDefaultSessionDir: () => true,
		},
	});
	const command = harness.commands.get("cwd");
	assert.ok(command, "/cwd must be registered");
	assert.match(command.description, /Move this session to a new directory/);
	assert.match(command.description, /Usage: \/cwd \[path\]/);
}

async function testArgumentClassification() {
	const fixture = createFixture();
	try {
		const absoluteTarget = join(fixture.root, "absolute-target");
		const spacedTarget = join(fixture.root, "target with spaces");
		mkdirSync(absoluteTarget);
		mkdirSync(spacedTarget);
		const sourceBefore = readFileSync(fixture.sessionFile, "utf8");
		const cases = [
			{ args: "", expected: process.cwd(), label: "empty argument uses process cwd" },
			{ args: absoluteTarget, expected: absoluteTarget, label: "absolute path remains absolute" },
			{ args: "~", expected: homedir(), label: "bare tilde expands home" },
			{ args: "~/", expected: homedir(), label: "tilde slash expands home" },
			{ args: spacedTarget, expected: spacedTarget, label: "spaces stay in one path argument" },
		];

		for (const { args, expected, label } of cases) {
			const harness = createHarness({ cwd: fixture.sourceCwd, sessionManager: fixture.sessionManager });
			await runCommand(harness, args);
			assert.equal(harness.switches.length, 1, label);
			assert.equal(readSession(harness.switches[0])[0].cwd, resolve(expected), label);
		}
		assert.equal(readFileSync(fixture.sessionFile, "utf8"), sourceBefore, "forking never mutates the source session");
	} finally {
		cleanup(fixture.root);
	}
}

async function testRelativePathRejection() {
	const fixture = createFixture();
	try {
		const before = sessionFiles(fixture.sessionDir);
		for (const args of ["relative path", "~otheruser/project"]) {
			const harness = createHarness({ cwd: fixture.sourceCwd, sessionManager: fixture.sessionManager });
			await runCommand(harness, args);
			assert.deepEqual(harness.switches, [], `${args} must not switch sessions`);
			assert.match(harness.notifications.at(-1).message, /Relative paths are ambiguous/);
			assert.equal(harness.notifications.at(-1).type, "warning");
		}
		assert.deepEqual(sessionFiles(fixture.sessionDir), before, "rejected arguments create no sessions");
	} finally {
		cleanup(fixture.root);
	}
}

async function testNoOpUsesPhysicalPathIdentity() {
	const fixture = createFixture();
	const forkFromSpy = spyOnForkFrom();
	try {
		const alias = join(fixture.root, "source-alias");
		symlinkSync(fixture.sourceCwd, alias, "dir");
		const before = sessionFiles(fixture.sessionDir);
		const harness = createHarness({ cwd: fixture.sourceCwd, sessionManager: fixture.sessionManager });
		await runCommand(harness, alias);
		assert.deepEqual(harness.switches, [], "symlink alias must not switch sessions");
		assert.equal(forkFromSpy.calls.length, 0, "symlink alias must not call SessionManager.forkFrom");
		assert.deepEqual(sessionFiles(fixture.sessionDir), before, "symlink alias must not fork a session");
		assert.deepEqual(harness.notifications, [{ message: `Already at ${alias}.`, type: "info" }]);
	} finally {
		forkFromSpy.restore();
		cleanup(fixture.root);
	}
}

async function testEphemeralSessionRejectsBeforeNoOp() {
	const root = mkdtempSync(join(tmpdir(), "pi-cwd-ephemeral-"));
	try {
		const cwd = join(root, "cwd");
		mkdirSync(cwd);
		const harness = createHarness({
			cwd,
			sessionManager: {
				getSessionFile: () => undefined,
				getSessionDir: () => {
					throw new Error("ephemeral sessions must not request a session directory");
				},
				usesDefaultSessionDir: () => {
					throw new Error("ephemeral sessions must not inspect storage mode");
				},
			},
		});
		await runCommand(harness, cwd);
		assert.deepEqual(harness.switches, []);
		assert.match(harness.notifications.at(-1).message, /ephemeral session/);
		assert.equal(harness.notifications.at(-1).type, "warning");
	} finally {
		cleanup(root);
	}
}

async function testMissingStorageModeMethodFailsClearly() {
	const fixture = createFixture();
	try {
		const target = join(fixture.root, "target");
		mkdirSync(target);
		const harness = createHarness({
			cwd: fixture.sourceCwd,
			sessionManager: {
				getSessionFile: () => fixture.sessionFile,
				getSessionDir: () => fixture.sessionDir,
			},
		});
		await runCommand(harness, target);
		assert.deepEqual(harness.switches, []);
		assert.match(harness.notifications.at(-1).message, /missing required usesDefaultSessionDir/);
		assert.equal(harness.notifications.at(-1).type, "error");
	} finally {
		cleanup(fixture.root);
	}
}

async function testInvalidTargetsDoNotMutateSessions() {
	const fixture = createFixture();
	try {
		const missing = join(fixture.root, "missing");
		const notDirectory = join(fixture.root, "not-a-directory");
		writeFileSync(notDirectory, "fixture");
		const filesBefore = sessionFiles(fixture.sessionDir);
		const sourceBefore = readFileSync(fixture.sessionFile, "utf8");

		const notifications = [];
		for (const target of [missing, notDirectory]) {
			const harness = createHarness({ cwd: fixture.sourceCwd, sessionManager: fixture.sessionManager });
			await runCommand(harness, target);
			assert.deepEqual(harness.switches, [], `${target} must not switch sessions`);
			notifications.push(harness.notifications.at(-1));
		}

		assert.match(notifications[0].message, /Cannot use/);
		assert.match(notifications[1].message, /Target is not a directory/);
		assert.equal(existsSync(missing), false, "missing target stays absent");
		assert.equal(readFileSync(notDirectory, "utf8"), "fixture", "non-directory target stays untouched");
		assert.deepEqual(sessionFiles(fixture.sessionDir), filesBefore, "invalid targets create no session files");
		assert.equal(readFileSync(fixture.sessionFile, "utf8"), sourceBefore, "invalid targets leave source untouched");
	} finally {
		cleanup(fixture.root);
	}
}

async function testIdleGuardRunsFirst() {
	let sessionFileCalls = 0;
	const harness = createHarness({
		cwd: process.cwd(),
		idle: false,
		sessionManager: {
			getSessionFile: () => {
				sessionFileCalls += 1;
				return undefined;
			},
			getSessionDir: () => "",
			usesDefaultSessionDir: () => true,
		},
	});
	await runCommand(harness, "relative path");
	assert.equal(sessionFileCalls, 0, "idle guard must run before argument parsing or session access");
	assert.deepEqual(harness.switches, []);
	assert.deepEqual(harness.notifications, [
		{ message: "/cwd requires an idle agent. Wait for the current run to finish.", type: "warning" },
	]);
}

async function testForkCopiesHistoryAndPreservesCustomSessionDir() {
	const fixture = createFixture();
	try {
		const target = join(fixture.root, "target with spaces");
		mkdirSync(target);
		const sourceBefore = readFileSync(fixture.sessionFile, "utf8");
		const harness = createHarness({ cwd: fixture.sourceCwd, sessionManager: fixture.sessionManager });
		await runCommand(harness, target);

		assert.equal(harness.switches.length, 1);
		const newSessionFile = harness.switches[0];
		assert.equal(dirname(newSessionFile), resolve(fixture.sessionDir), "custom session directory is preserved");
		const [newHeader, ...newHistory] = readSession(newSessionFile);
		const [_sourceHeader, ...sourceHistory] = readSession(fixture.sessionFile);
		assert.equal(newHeader.cwd, resolve(target));
		assert.equal(newHeader.parentSession, resolve(fixture.sessionFile));
		assert.deepEqual(newHistory, sourceHistory, "forked session copies complete history");
		assert.equal(readFileSync(fixture.sessionFile, "utf8"), sourceBefore, "source session stays untouched");
		assert.deepEqual(harness.notifications, []);
		assert.deepEqual(harness.newSessionNotifications, [{ message: `Moved this session to ${target}.`, type: "info" }]);
	} finally {
		cleanup(fixture.root);
	}
}

async function testForkUsesDefaultSessionDir() {
	const agentDir = mkdtempSync(join(tmpdir(), "pi-cwd-default-session-dir-"));
	const previousAgentDir = process.env.PI_CODING_AGENT_DIR;
	process.env.PI_CODING_AGENT_DIR = agentDir;
	let fixture;
	let forkFromSpy;
	try {
		fixture = createFixture({ usesDefaultSessionDir: true });
		assert.equal(fixture.sessionManager.usesDefaultSessionDir(), true);
		const target = join(fixture.root, "target");
		mkdirSync(target);
		forkFromSpy = spyOnForkFrom();
		const harness = createHarness({ cwd: fixture.sourceCwd, sessionManager: fixture.sessionManager });
		await runCommand(harness, target);
		assert.equal(harness.switches.length, 1);
		assert.equal(forkFromSpy.calls.length, 1);
		assert.equal(forkFromSpy.calls[0][2], undefined, "default session storage must be selected by forkFrom");
		assert.equal(readSession(harness.switches[0])[0].cwd, resolve(target));
	} finally {
		forkFromSpy?.restore();
		if (previousAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR;
		else process.env.PI_CODING_AGENT_DIR = previousAgentDir;
		if (fixture) cleanup(fixture.root);
		cleanup(agentDir);
	}
}

async function testForkFailureAndSwitchCancellation() {
	const failureRoot = mkdtempSync(join(tmpdir(), "pi-cwd-failure-"));
	try {
		const target = join(failureRoot, "target");
		mkdirSync(target);
		const invalidSession = join(failureRoot, "invalid.jsonl");
		writeFileSync(invalidSession, '{"type":"not-session"}\n');
		const harness = createHarness({
			cwd: join(failureRoot, "source"),
			sessionManager: {
				getSessionFile: () => invalidSession,
				getSessionDir: () => join(failureRoot, "sessions"),
				usesDefaultSessionDir: () => false,
			},
		});
		await runCommand(harness, target);
		assert.deepEqual(harness.switches, []);
		assert.match(harness.notifications.at(-1).message, /Could not create a session/);
		assert.ok(harness.notifications.at(-1).message.includes(target), "fork failure identifies the target path");
		assert.equal(existsSync(join(failureRoot, "sessions")), false, "failed fork creates no session directory");
	} finally {
		cleanup(failureRoot);
	}

	const fixture = createFixture();
	try {
		const target = join(fixture.root, "target");
		mkdirSync(target);
		const harness = createHarness({ cwd: fixture.sourceCwd, sessionManager: fixture.sessionManager, cancelled: true });
		await runCommand(harness, target);
		assert.equal(harness.switches.length, 1);
		const newSessionFile = harness.switches[0];
		assert.equal(existsSync(newSessionFile), true, "cancelled switch leaves the forked session resumable");
		assert.deepEqual(harness.newSessionNotifications, []);
		assert.deepEqual(harness.notifications, [
			{
				message: `Created a new session at ${newSessionFile} but did not activate it. Resume it manually with pi --session "${newSessionFile}".`,
				type: "warning",
			},
		]);
	} finally {
		cleanup(fixture.root);
	}
}

async function testRuntimeRebindsStaleCwd() {
	const fixture = createFixture();
	const target = join(fixture.root, "terminal launch directory");
	const agentDir = join(fixture.root, "agent");
	const originalCwd = process.cwd();
	const extensionErrors = [];
	let runtime;
	try {
		mkdirSync(target);
		const physicalTarget = realpathSync(target);
		assert.notEqual(readSession(fixture.sessionFile)[0].cwd, physicalTarget);
		process.chdir(target);
		runtime = await createRuntimeHarness({
			cwd: fixture.sourceCwd,
			agentDir,
			sessionManager: SessionManager.open(fixture.sessionFile, fixture.sessionDir),
			extensionErrors,
		});
		const staleSession = runtime.session;
		await staleSession.prompt("/cwd");

		assert.deepEqual(extensionErrors, []);
		assert.notStrictEqual(runtime.session, staleSession, "/cwd must replace the active session runtime");
		assert.equal(runtime.cwd, physicalTarget);
		const newSessionFile = runtime.session.sessionFile;
		assert.ok(newSessionFile, "replacement runtime must retain a persisted session");
		assert.notEqual(resolve(newSessionFile), resolve(fixture.sessionFile));
		assert.equal(readSession(newSessionFile)[0].cwd, physicalTarget);

		const bashResult = await runtime.session.executeBash("pwd");
		assert.equal(bashResult.exitCode, 0);
		assert.equal(bashResult.output.trim(), physicalTarget, "subsequent session actions use the replacement cwd");
	} finally {
		try {
			if (runtime) await runtime.dispose();
		} finally {
			process.chdir(originalCwd);
			cleanup(fixture.root);
		}
	}
}

testCommandRegistration();
await testArgumentClassification();
await testRelativePathRejection();
await testNoOpUsesPhysicalPathIdentity();
await testEphemeralSessionRejectsBeforeNoOp();
await testMissingStorageModeMethodFailsClearly();
await testInvalidTargetsDoNotMutateSessions();
await testIdleGuardRunsFirst();
await testForkCopiesHistoryAndPreservesCustomSessionDir();
await testForkUsesDefaultSessionDir();
await testForkFailureAndSwitchCancellation();
await testRuntimeRebindsStaleCwd();
console.log("session-cwd-move runtime handler harness: ok");
