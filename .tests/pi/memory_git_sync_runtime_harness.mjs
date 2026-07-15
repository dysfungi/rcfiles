#!/usr/bin/env node
/** Runtime coverage for Pi memory synchronization helpers against disposable Git repositories. */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
	chmodSync,
	existsSync,
	lstatSync,
	mkdtempSync,
	mkdirSync,
	readFileSync,
	rmSync,
	symlinkSync,
	writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [extensionPath, packageDir] = process.argv.slice(2);
if (!extensionPath || !packageDir) {
	throw new Error("Usage: memory_git_sync_runtime_harness.mjs <extension-path> <pi-package-dir>");
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
	default: memoryGitSync,
	MEMORY_ATTRIBUTES_BLOCK,
	MEMORY_REMOTE_URL,
	ensureMemoryAttributes,
	managedAttributesContent,
	probeRepository,
} = await jiti.import(resolve(extensionPath));

function cleanEnvironment() {
	const environment = { ...process.env };
	for (const key of Object.keys(environment)) {
		if (
			key === "GIT_DIR" ||
			key === "GIT_WORK_TREE" ||
			key === "GIT_INDEX_FILE" ||
			key === "GIT_COMMON_DIR" ||
			key === "GIT_OBJECT_DIRECTORY" ||
			key === "GIT_ALTERNATE_OBJECT_DIRECTORIES" ||
			key === "GIT_NAMESPACE" ||
			key === "GIT_CONFIG_COUNT" ||
			key.startsWith("GIT_CONFIG_")
		) {
			delete environment[key];
		}
	}
	return environment;
}

function run(command, args, { cwd, input, allowFailure = false } = {}) {
	const result = spawnSync(command, args, {
		cwd,
		encoding: "utf8",
		env: cleanEnvironment(),
		input,
	});
	if (!allowFailure) {
		assert.equal(
			result.status,
			0,
			`${command} ${args.join(" ")} failed:\n${result.stderr || "<empty>"}`,
		);
	}
	return result;
}

function git(directory, args, options = {}) {
	return run("git", ["-C", directory, ...args], options);
}

function gitOutput(directory, args, options = {}) {
	return git(directory, args, options).stdout.trim();
}

function configureUser(directory) {
	git(directory, ["config", "user.email", "test@example.invalid"]);
	git(directory, ["config", "user.name", "Pi Memory Test"]);
}

function repository(root, name, remote = MEMORY_REMOTE_URL) {
	const directory = join(root, name);
	run("git", ["init", "-q", "-b", "main", directory]);
	configureUser(directory);
	git(directory, ["remote", "add", "origin", remote]);
	git(directory, ["commit", "--allow-empty", "-qm", "initial"]);
	return directory;
}

function commonDirectory(directory) {
	const gitCommonDir = gitOutput(directory, ["rev-parse", "--git-common-dir"]);
	return isAbsolute(gitCommonDir) ? gitCommonDir : resolve(directory, gitCommonDir);
}

function gitDirectory(directory) {
	const gitDir = gitOutput(directory, ["rev-parse", "--git-dir"]);
	return isAbsolute(gitDir) ? gitDir : resolve(directory, gitDir);
}

function attributesPath(directory) {
	const path = gitOutput(directory, ["rev-parse", "--git-path", "info/attributes"]);
	return isAbsolute(path) ? path : resolve(directory, path);
}

async function assertHealthy(directory, remote) {
	const health = await probeRepository(directory, remote);
	assert.equal(health.healthy, true, health.reason);
	return health;
}

async function assertUnhealthy(directory, expectedReason, remote) {
	const health = await probeRepository(directory, remote);
	assert.equal(health.healthy, false, `expected unhealthy repository, got ${health.reason}`);
	assert.equal(health.reason, expectedReason);
}

function setFile(directory, relativePath, content) {
	const path = join(directory, relativePath);
	mkdirSync(resolve(path, ".."), { recursive: true });
	writeFileSync(path, content, "utf8");
}

function commitAll(directory, message) {
	git(directory, ["add", "-A"]);
	git(directory, ["commit", "-qm", message]);
}

async function withEnvironment(overrides, callback) {
	const previous = Object.fromEntries(Object.keys(overrides).map((key) => [key, process.env[key]]));
	try {
		for (const [key, value] of Object.entries(overrides)) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
		return await callback();
	} finally {
		for (const [key, value] of Object.entries(previous)) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
	}
}

function writeExecutable(path, content) {
	writeFileSync(path, content, "utf8");
	chmodSync(path, 0o700);
}

function installSshShim(root, name, remote, { fail = false } = {}) {
	const directory = join(root, `${name}-bin`);
	const log = join(root, `${name}-ssh.log`);
	mkdirSync(directory);
	const body = fail
		? `#!/bin/sh\nprintf '%s\\n' "$*" >> ${JSON.stringify(log)}\nexit 1\n`
		: `#!/bin/sh\nprintf '%s\\n' "$*" >> ${JSON.stringify(log)}\ncase "$*" in\n  *git-upload-pack*) exec git-upload-pack ${JSON.stringify(remote)} ;;\n  *git-receive-pack*) exec git-receive-pack ${JSON.stringify(remote)} ;;\nesac\nexit 1\n`;
	writeExecutable(join(directory, "ssh"), body);
	return { directory, log };
}

function installAbortFailingGitShim(directory, root, name) {
	const log = join(root, `${name}-git.log`);
	const realGit = spawnSync("which", ["git"], { encoding: "utf8" }).stdout.trim();
	assert.ok(realGit, "git executable must be discoverable");
	writeExecutable(
		join(directory, "git"),
		`#!/bin/sh\nprintf '%s\\n' "$*" >> ${JSON.stringify(log)}\ncase " $* " in\n  *" merge --abort "*) exit 1 ;;\nesac\nexec ${JSON.stringify(realGit)} "$@"\n`,
	);
	return log;
}

function session() {
	const events = new Map();
	const notifications = [];
	const ctx = { ui: { notify: (message) => notifications.push(message) } };
	const previousSubagent = process.env.PI_SUBAGENT;
	try {
		delete process.env.PI_SUBAGENT;
		memoryGitSync({ on: (name, handler) => events.set(name, handler) });
	} finally {
		if (previousSubagent === undefined) delete process.env.PI_SUBAGENT;
		else process.env.PI_SUBAGENT = previousSubagent;
	}
	return { events, notifications, ctx };
}

async function invokeSessionEvent(currentSession, name) {
	const handler = currentSession.events.get(name);
	assert.ok(handler, `missing ${name} handler`);
	await handler({}, currentSession.ctx);
}

async function withSessionEnvironment(directory, shimDirectory, callback, overrides = {}) {
	await withEnvironment(
		{
			GIT_ASKPASS: "/definitely/not/inherited-askpass",
			GIT_SSH_COMMAND: "/definitely/not/inherited-ssh",
			PATH: `${shimDirectory}:${process.env.PATH ?? ""}`,
			PI_MEMORY_DIR: directory,
			PI_SUBAGENT: undefined,
			...overrides,
		},
		callback,
	);
}

async function testHealthProbe(root) {
	const healthy = repository(root, "healthy");
	await assertHealthy(healthy);

	const detached = repository(root, "detached");
	git(detached, ["checkout", "--detach", "-q"]);
	await assertUnhealthy(detached, "detached HEAD");

	const wrongBranch = repository(root, "wrong-branch");
	git(wrongBranch, ["checkout", "-qb", "other"]);
	await assertUnhealthy(wrongBranch, "branch is not main");

	const wrongOrigin = repository(root, "wrong-origin");
	git(wrongOrigin, ["remote", "set-url", "origin", "git@example.invalid:wrong.git"]);
	await assertUnhealthy(wrongOrigin, "unexpected origin fetch URL");

	const wrongPushOrigin = repository(root, "wrong-push-origin");
	git(wrongPushOrigin, ["remote", "set-url", "--push", "origin", "git@example.invalid:wrong.git"]);
	await assertUnhealthy(wrongPushOrigin, "unexpected origin push URL");

	const extraPushOrigin = repository(root, "extra-push-origin");
	git(extraPushOrigin, ["remote", "set-url", "--add", "--push", "origin", MEMORY_REMOTE_URL]);
	git(
		extraPushOrigin,
		["remote", "set-url", "--add", "--push", "origin", "git@example.invalid:extra.git"],
	);
	await assertUnhealthy(extraPushOrigin, "unexpected origin push URL");

	const unmerged = repository(root, "unmerged");
	const blob = gitOutput(unmerged, ["hash-object", "-w", "--stdin"], {
		input: "conflicting content\n",
	});
	git(unmerged, ["update-index", "--index-info"], {
		input: [
			`100644 ${blob} 1\tconflict.md`,
			`100644 ${blob} 2\tconflict.md`,
			`100644 ${blob} 3\tconflict.md`,
		].join("\n"),
	});
	await assertUnhealthy(unmerged, "unmerged index");

	for (const [name, marker, reason, isDirectory] of [
		["merge", "MERGE_HEAD", "active operation (merge)", false],
		["rebase-apply", "rebase-apply", "active operation (rebase)", true],
		["rebase-merge", "rebase-merge", "active operation (rebase)", true],
		["cherry-pick", "CHERRY_PICK_HEAD", "active operation (cherry-pick)", false],
		["revert", "REVERT_HEAD", "active operation (revert)", false],
		["sequencer", "sequencer", "active operation (sequencer)", true],
		["bisect", "BISECT_START", "active operation (bisect)", false],
	]) {
		const active = repository(root, name);
		const markerPath = join(commonDirectory(active), marker);
		if (isDirectory) mkdirSync(markerPath);
		else writeFileSync(markerPath, "operation\n", "utf8");
		await assertUnhealthy(active, reason);
	}

	const stale = repository(root, "stale-markers");
	const staleCommonDir = commonDirectory(stale);
	writeFileSync(join(staleCommonDir, "REBASE_HEAD"), "stale\n", "utf8");
	writeFileSync(join(staleCommonDir, "AUTO_MERGE"), "stale\n", "utf8");
	await assertHealthy(stale);

	const linkedWorktreeMain = repository(root, "linked-worktree-main");
	git(linkedWorktreeMain, ["checkout", "--detach", "-q"]);
	const linkedWorktree = join(root, "linked-worktree-active-merge");
	git(linkedWorktreeMain, ["worktree", "add", "-q", linkedWorktree, "main"]);
	setFile(linkedWorktree, "conflict.md", "base\n");
	commitAll(linkedWorktree, "base conflict file");
	git(linkedWorktree, ["branch", "incoming"]);
	setFile(linkedWorktree, "conflict.md", "local change\n");
	commitAll(linkedWorktree, "local conflict change");
	git(linkedWorktree, ["checkout", "-q", "incoming"]);
	setFile(linkedWorktree, "conflict.md", "incoming change\n");
	commitAll(linkedWorktree, "incoming conflict change");
	git(linkedWorktree, ["checkout", "-q", "main"]);
	const linkedMerge = git(linkedWorktree, ["merge", "--no-edit", "incoming"], {
		allowFailure: true,
	});
	assert.notEqual(linkedMerge.status, 0, "linked worktree merge must remain active");
	assert.notEqual(gitDirectory(linkedWorktree), commonDirectory(linkedWorktree));
	assert.equal(existsSync(join(gitDirectory(linkedWorktree), "MERGE_HEAD")), true);
	assert.equal(existsSync(join(commonDirectory(linkedWorktree), "MERGE_HEAD")), false);
	await assertUnhealthy(linkedWorktree, "linked worktrees are unsupported");

	const target = repository(root, "hostile-env-target");
	const attacker = repository(root, "hostile-env-attacker", "git@example.invalid:attacker.git");
	await withEnvironment(
		{
			GIT_ALTERNATE_OBJECT_DIRECTORIES: join(attacker, ".git", "objects"),
			GIT_COMMON_DIR: commonDirectory(attacker),
			GIT_CONFIG_COUNT: "1",
			GIT_CONFIG_KEY_0: "remote.origin.url",
			GIT_CONFIG_VALUE_0: "git@example.invalid:config-injection.git",
			GIT_DIR: join(attacker, ".git"),
			GIT_INDEX_FILE: join(attacker, "hostile.index"),
			GIT_NAMESPACE: "hostile",
			GIT_OBJECT_DIRECTORY: join(attacker, ".git", "objects"),
			GIT_WORK_TREE: attacker,
		},
		async () => assertHealthy(target),
	);
}

async function testAttributes(root) {
	const directory = repository(root, "attributes");
	const resolvedAttributesPath = attributesPath(directory);
	const first = await ensureMemoryAttributes(directory);
	assert.equal(first.ok, true);
	assert.equal(first.changed, true);
	assert.equal(readFileSync(resolvedAttributesPath, "utf8"), `${MEMORY_ATTRIBUTES_BLOCK}\n`);

	const second = await ensureMemoryAttributes(directory);
	assert.equal(second.ok, true);
	assert.equal(second.changed, false);

	writeFileSync(resolvedAttributesPath, "custom/** -merge\n", "utf8");
	const third = await ensureMemoryAttributes(directory);
	assert.equal(third.ok, true);
	assert.equal(third.changed, true);
	const expected = `custom/** -merge\n\n${MEMORY_ATTRIBUTES_BLOCK}\n`;
	assert.equal(readFileSync(resolvedAttributesPath, "utf8"), expected);
	assert.equal(managedAttributesContent(expected), expected);

	writeFileSync(resolvedAttributesPath, MEMORY_ATTRIBUTES_BLOCK, "utf8");
	const noTrailingNewline = await ensureMemoryAttributes(directory);
	assert.equal(noTrailingNewline.ok, true);
	assert.equal(noTrailingNewline.changed, true);
	assert.equal(readFileSync(resolvedAttributesPath, "utf8"), `${MEMORY_ATTRIBUTES_BLOCK}\n`);

	const attributes = gitOutput(directory, [
		"check-attr",
		"merge",
		"--",
		"daily/2026-01-01.md",
		"MEMORY.md",
		"SCRATCHPAD.md",
	]);
	assert.match(attributes, /daily\/2026-01-01\.md: merge: union/);
	assert.match(attributes, /MEMORY\.md: merge: unset/);
	assert.match(attributes, /SCRATCHPAD\.md: merge: unset/);

	const symlinkDirectory = repository(root, "attributes-symlink");
	const symlinkAttributesPath = attributesPath(symlinkDirectory);
	const target = join(root, "attributes-symlink-target");
	writeFileSync(target, "deliberate local symlink target\n", "utf8");
	symlinkSync(target, symlinkAttributesPath);
	const symlinkResult = await ensureMemoryAttributes(symlinkDirectory);
	assert.equal(symlinkResult.ok, false);
	assert.equal(symlinkResult.reason, "attributes file is a symbolic link");
	assert.equal(lstatSync(symlinkAttributesPath).isSymbolicLink(), true);
	assert.equal(readFileSync(target, "utf8"), "deliberate local symlink target\n");
}

function initializeBareRemote(root, name) {
	const remote = join(root, `${name}.git`);
	run("git", ["init", "--bare", "-q", "--initial-branch=main", remote]);
	return remote;
}

function clone(remote, directory) {
	run("git", ["clone", "-q", remote, directory]);
	configureUser(directory);
}

function seededRemote(root, name) {
	const remote = initializeBareRemote(root, name);
	const seed = join(root, `${name}-seed`);
	clone(remote, seed);
	setFile(seed, "MEMORY.md", "base\n");
	commitAll(seed, "seed memory");
	git(seed, ["push", "-qu", "origin", "main"]);
	return remote;
}

function setCanonicalOrigin(directory) {
	git(directory, ["remote", "set-url", "origin", MEMORY_REMOTE_URL]);
}

async function testDailyUnionMerge(root) {
	const remote = initializeBareRemote(root, "daily-remote");
	const first = join(root, "daily-first");
	clone(remote, first);
	setFile(first, "daily/2026-01-01.md", "base\n");
	commitAll(first, "seed daily log");
	git(first, ["push", "-qu", "origin", "main"]);

	const second = join(root, "daily-second");
	clone(remote, second);
	assert.equal((await ensureMemoryAttributes(first)).ok, true);
	assert.equal((await ensureMemoryAttributes(second)).ok, true);

	setFile(first, "daily/2026-01-01.md", "base\nfirst writer\n");
	commitAll(first, "first daily entry");
	git(first, ["push", "-q"]);

	setFile(second, "daily/2026-01-01.md", "base\nsecond writer\n");
	commitAll(second, "second daily entry");
	git(second, ["fetch", "origin", "main"]);
	git(second, ["merge", "--no-edit", "origin/main"]);
	git(second, ["push", "origin", "HEAD:refs/heads/main"]);

	const finalClone = join(root, "daily-final");
	clone(remote, finalClone);
	const finalContent = readFileSync(join(finalClone, "daily/2026-01-01.md"), "utf8");
	assert.match(finalContent, /first writer/);
	assert.match(finalContent, /second writer/);
}

async function testSuccessfulSessionPush(root) {
	const remote = seededRemote(root, "successful-session-remote");
	const writer = join(root, "successful-session-writer");
	clone(remote, writer);
	setCanonicalOrigin(writer);
	setFile(writer, "MEMORY.md", "runtime writer\n");
	const ssh = installSshShim(root, "successful-session", remote);
	const currentSession = session();

	await withSessionEnvironment(writer, ssh.directory, async () => {
		await invokeSessionEvent(currentSession, "session_start");
		await invokeSessionEvent(currentSession, "session_shutdown");
	});

	assert.deepEqual(currentSession.notifications, []);
	const finalClone = join(root, "successful-session-final");
	clone(remote, finalClone);
	assert.equal(readFileSync(join(finalClone, "MEMORY.md"), "utf8"), "runtime writer\n");
	assert.equal(gitOutput(finalClone, ["log", "--oneline", "-1"]).includes("sync"), true);
	const sshCommands = readFileSync(ssh.log, "utf8");
	assert.match(sshCommands, /-o BatchMode=yes/);
	assert.match(sshCommands, /-o StrictHostKeyChecking=accept-new/);
	assert.match(sshCommands, /git-upload-pack/);
	assert.match(sshCommands, /git-receive-pack/);
}

async function testRejectedPushDisablesSession(root) {
	const remote = seededRemote(root, "rejected-push-remote");
	const writer = join(root, "rejected-push-writer");
	clone(remote, writer);
	setCanonicalOrigin(writer);
	setFile(writer, "MEMORY.md", "local writer\n");
	const ssh = installSshShim(root, "rejected-push", remote);
	const currentSession = session();
	let localHead;

	await withSessionEnvironment(writer, ssh.directory, async () => {
		await invokeSessionEvent(currentSession, "session_start");
		localHead = gitOutput(writer, ["rev-parse", "HEAD"]);

		const concurrent = join(root, "rejected-push-concurrent");
		clone(remote, concurrent);
		setFile(concurrent, "MEMORY.md", "concurrent writer\n");
		commitAll(concurrent, "concurrent writer");
		git(concurrent, ["push", "-q"]);

		await invokeSessionEvent(currentSession, "session_shutdown");
		assert.equal(gitOutput(writer, ["rev-parse", "HEAD"]), localHead);
		setFile(writer, "after-rejected-push.md", "must remain untracked\n");
		await invokeSessionEvent(currentSession, "session_shutdown");
	});

	assert.match(currentSession.notifications.at(-1), /push failed .*local commit retained/);
	assert.equal(gitOutput(writer, ["rev-parse", "HEAD"]), localHead);
	assert.equal(gitOutput(writer, ["status", "--porcelain"]), "?? after-rejected-push.md");
	const finalClone = join(root, "rejected-push-final");
	clone(remote, finalClone);
	assert.equal(readFileSync(join(finalClone, "MEMORY.md"), "utf8"), "concurrent writer\n");
}

async function testFetchFailureDoesNotWrite(root) {
	const remote = seededRemote(root, "fetch-failure-remote");
	const writer = join(root, "fetch-failure-writer");
	clone(remote, writer);
	setCanonicalOrigin(writer);
	setFile(writer, "pending.md", "must remain untracked\n");
	const ssh = installSshShim(root, "fetch-failure", remote, { fail: true });
	const currentSession = session();
	const initialHead = gitOutput(writer, ["rev-parse", "HEAD"]);
	const localAttributesPath = attributesPath(writer);
	assert.equal(existsSync(localAttributesPath), false);

	await withSessionEnvironment(writer, ssh.directory, async () => {
		await invokeSessionEvent(currentSession, "session_start");
		assert.equal(gitOutput(writer, ["rev-parse", "HEAD"]), initialHead);
		assert.equal(gitOutput(writer, ["status", "--porcelain"]), "?? pending.md");
		assert.equal(existsSync(localAttributesPath), false);
		await invokeSessionEvent(currentSession, "session_shutdown");
	});

	assert.match(currentSession.notifications.at(-1), /fetch failed .*repository recovered/);
	assert.equal(gitOutput(writer, ["rev-parse", "HEAD"]), initialHead);
	assert.equal(gitOutput(writer, ["status", "--porcelain"]), "?? pending.md");
	assert.equal(existsSync(localAttributesPath), false);
}

async function testHostileAttributesRefuseMerge(root) {
	const remote = seededRemote(root, "hostile-attributes-remote");
	const writer = join(root, "hostile-attributes-writer");
	clone(remote, writer);
	setCanonicalOrigin(writer);
	assert.equal((await ensureMemoryAttributes(writer)).ok, true);
	writeFileSync(attributesPath(writer), `${MEMORY_ATTRIBUTES_BLOCK}\nMEMORY.md merge=union\n`, "utf8");
	const initialHead = gitOutput(writer, ["rev-parse", "HEAD"]);

	const concurrent = join(root, "hostile-attributes-concurrent");
	clone(remote, concurrent);
	setFile(concurrent, "MEMORY.md", "remote writer\n");
	commitAll(concurrent, "remote writer");
	git(concurrent, ["push", "-q"]);

	const ssh = installSshShim(root, "hostile-attributes", remote);
	const currentSession = session();
	await withSessionEnvironment(writer, ssh.directory, async () => {
		await invokeSessionEvent(currentSession, "session_start");
		assert.equal(gitOutput(writer, ["rev-parse", "HEAD"]), initialHead);
		setFile(writer, "after-hostile-attributes.md", "must remain untracked\n");
		await invokeSessionEvent(currentSession, "session_shutdown");
	});

	assert.match(currentSession.notifications.at(-1), /managed attributes are ineffective/);
	assert.equal(gitOutput(writer, ["rev-parse", "HEAD"]), initialHead);
	assert.equal(readFileSync(join(writer, "MEMORY.md"), "utf8"), "base\n");
	assert.equal(gitOutput(writer, ["status", "--porcelain"]), "?? after-hostile-attributes.md");
}

async function testAbortFailureStopsSessionGit(root) {
	const remote = seededRemote(root, "abort-failure-remote");
	const writer = join(root, "abort-failure-writer");
	clone(remote, writer);
	setCanonicalOrigin(writer);
	setFile(writer, "MEMORY.md", "local writer\n");

	const concurrent = join(root, "abort-failure-concurrent");
	clone(remote, concurrent);
	setFile(concurrent, "MEMORY.md", "remote writer\n");
	commitAll(concurrent, "remote writer");
	git(concurrent, ["push", "-q"]);

	const ssh = installSshShim(root, "abort-failure", remote);
	const gitLog = installAbortFailingGitShim(ssh.directory, root, "abort-failure");
	const currentSession = session();
	await withSessionEnvironment(writer, ssh.directory, async () => {
		await invokeSessionEvent(currentSession, "session_start");
		const callsAfterStart = readFileSync(gitLog, "utf8");
		assert.match(callsAfterStart, /merge --abort/);
		await invokeSessionEvent(currentSession, "session_shutdown");
		assert.equal(readFileSync(gitLog, "utf8"), callsAfterStart);
	});

	assert.match(currentSession.notifications.at(-1), /merge abort failed .*recovery-required/);
	assert.equal(existsSync(join(commonDirectory(writer), "MERGE_HEAD")), true);
}

async function testCuratedConflict(root, fileName) {
	const remote = initializeBareRemote(root, `curated-${fileName}`);
	const first = join(root, `curated-${fileName}-first`);
	clone(remote, first);
	setFile(first, fileName, "base\n");
	commitAll(first, `seed ${fileName}`);
	git(first, ["push", "-qu", "origin", "main"]);

	const second = join(root, `curated-${fileName}-second`);
	clone(remote, second);
	assert.equal((await ensureMemoryAttributes(first)).ok, true);
	assert.equal((await ensureMemoryAttributes(second)).ok, true);

	setFile(first, fileName, "remote writer\n");
	commitAll(first, `remote ${fileName} edit`);
	git(first, ["push", "-q"]);

	setFile(second, fileName, "local writer\n");
	commitAll(second, `local ${fileName} edit`);
	git(second, ["fetch", "origin", "main"]);
	const merge = git(second, ["merge", "--no-edit", "origin/main"], { allowFailure: true });
	assert.notEqual(merge.status, 0, `curated ${fileName} merge must conflict`);
	assert.notEqual(gitOutput(second, ["ls-files", "-u"]), "");

	git(second, ["merge", "--abort"]);
	await assertHealthy(second, remote);
	assert.equal(readFileSync(join(second, fileName), "utf8"), "local writer\n");
	assert.equal(gitOutput(second, ["status", "--porcelain"]), "");
}

const root = mkdtempSync(join(tmpdir(), "pi-memory-git-sync-"));
try {
	await testHealthProbe(root);
	await testAttributes(root);
	await testDailyUnionMerge(root);
	await testSuccessfulSessionPush(root);
	await testRejectedPushDisablesSession(root);
	await testFetchFailureDoesNotWrite(root);
	await testHostileAttributesRefuseMerge(root);
	await testAbortFailureStopsSessionGit(root);
	await testCuratedConflict(root, "MEMORY.md");
	await testCuratedConflict(root, "SCRATCHPAD.md");
} finally {
	rmSync(root, { recursive: true, force: true });
}

console.log("memory git sync runtime harness: ok");
