#!/usr/bin/env node
/** Runtime coverage for subagent execution classes, preflight, and worker leases. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [extensionPath, registryPath, packageDir] = process.argv.slice(2);
if (!extensionPath || !registryPath || !packageDir) {
	throw new Error("Usage: subagent_runner_runtime_harness.mjs <extension-path> <registry-path> <pi-package-dir>");
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

function writeAgent(root, name, execution) {
	const agentsDir = join(root, ".pi", "agents");
	mkdirSync(agentsDir, { recursive: true });
	const executionLine = execution === undefined ? "" : `execution: ${execution}\n`;
	writeFileSync(
		join(agentsDir, `${name}.md`),
		`---\nname: ${name}\ndescription: ${name} test agent\ntools: read, bash\n${executionLine}---\n\nTest agent.\n`,
	);
}

function writeAgents(root) {
	writeAgent(root, "reader", "read-only");
	writeAgent(root, "reviewer", "read-only");
	writeAgent(root, "writer", "worktree-write");
	writeAgent(root, "missing", undefined);
	writeAgent(root, "invalid", "not-a-class");
}

function runner(cwd, sessionId) {
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
			sessionManager: { getSessionId: () => sessionId },
			ui: { confirm: async () => false },
		},
		tool,
	};
}

async function invoke(currentRunner, params, signal) {
	return currentRunner.tool.execute("subagent-test", params, signal, undefined, currentRunner.ctx);
}

function resultText(result) {
	const content = result.content?.[0];
	assert.equal(content?.type, "text");
	return content.text;
}

function fakePi() {
	const directory = mkdtempSync(join(tmpdir(), "pi-subagent-fake-"));
	const script = join(directory, "pi.mjs");
	const log = join(directory, "invocations.jsonl");
	writeFileSync(
		script,
		[
			'import { appendFileSync, existsSync } from "node:fs";',
			"const record = {",
			"\tcwd: process.cwd(),",
			"\targs: process.argv.slice(2),",
			"\texecution: process.env.PI_SUBAGENT_EXECUTION,",
			"\tmarker: process.env.PI_SUBAGENT,",
			"\tworktreeRoot: process.env.PI_WORKTREE_ROOT,",
			"\trepoRoot: process.env.PI_WORKTREE_REPO_ROOT,",
			"\tgeneration: process.env.PI_WORKTREE_GENERATION,",
			"};",
			'if (process.env.FAKE_PI_BEHAVIOR === "hold" || process.env.FAKE_PI_BEHAVIOR === "ignore-term") {',
			'\tif (process.env.FAKE_PI_BEHAVIOR === "ignore-term") process.on("SIGTERM", () => {});',
			"\tconst release = process.env.FAKE_PI_RELEASE;",
			"\tconst timer = setInterval(() => {",
			"\t\tif (!release || !existsSync(release)) return;",
			"\t\tclearInterval(timer);",
			"\t\tprocess.exit(0);",
			"\t}, 10);",
			"}",
			'appendFileSync(process.env.FAKE_PI_LOG, `${JSON.stringify(record)}\\n`);',
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

async function testReadOnlyExecution(fake) {
	const { root } = worktreeFixture();
	const sessionId = "read-only";
	writeAgents(root);
	const currentRunner = runner(root, sessionId);
	const original = {
		generation: process.env.PI_WORKTREE_GENERATION,
		repoRoot: process.env.PI_WORKTREE_REPO_ROOT,
		worktreeRoot: process.env.PI_WORKTREE_ROOT,
	};
	process.env.PI_WORKTREE_GENERATION = "stale";
	process.env.PI_WORKTREE_REPO_ROOT = "stale";
	process.env.PI_WORKTREE_ROOT = "stale";
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
	} finally {
		if (original.generation === undefined) delete process.env.PI_WORKTREE_GENERATION;
		else process.env.PI_WORKTREE_GENERATION = original.generation;
		if (original.repoRoot === undefined) delete process.env.PI_WORKTREE_REPO_ROOT;
		else process.env.PI_WORKTREE_REPO_ROOT = original.repoRoot;
		if (original.worktreeRoot === undefined) delete process.env.PI_WORKTREE_ROOT;
		else process.env.PI_WORKTREE_ROOT = original.worktreeRoot;
	}
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
	} finally {
		registry.revokeWorktree({ sessionId: ignoringSession, repoRoot: ignoring.root });
	}
}

const fake = fakePi();
await testReadOnlyExecution(fake);
writeFileSync(fake.log, "");
await testApprovedWorktreeRoutesReviewers(fake);
writeFileSync(fake.log, "");
await testReadOnlyRejectsUnresolvedApproval(fake);
writeFileSync(fake.log, "");
await testWritableExecution(fake);
writeFileSync(fake.log, "");
await testExecutionClassAndCwdPreflight(fake);
writeFileSync(fake.log, "");
await testParallelPreflightIsAtomic(fake);
writeFileSync(fake.log, "");
await testLeaseReleasesAfterSpawnFailure();
writeFileSync(fake.log, "");
await testConcurrentToolCallsShareOneLease(fake);
writeFileSync(fake.log, "");
await testSignalTerminationAndAbortEscalation(fake);
console.log("subagent runner runtime harness: ok");
