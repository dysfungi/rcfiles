#!/usr/bin/env node
/** Runtime coverage for the managed read-only Pi audit metadata extension. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import * as os from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [extensionPath, packageDir, scenario, field, encodedValue] = process.argv.slice(2);
if (!extensionPath || !packageDir || !scenario) {
	throw new Error("Usage: audit_metadata_runtime_harness.mjs <extension-path> <pi-package-dir> <scenario>");
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
const auditMetadataModule = await jiti.import(resolve(extensionPath));
const { default: auditMetadata } = auditMetadataModule;

function context({ model = { id: "model-alpha", provider: "provider-alpha" }, sessionId = "session-alpha" } = {}) {
	return {
		model,
		sessionManager: { getSessionId: () => sessionId },
	};
}

function runtime({ username = "user-alpha", hostname = "host-alpha" } = {}) {
	return {
		userInfo: () => ({ username }),
		hostname: () => hostname,
	};
}

function load(auditRuntime) {
	const registrations = { commands: [], events: [], executions: [], tools: [] };
	const pi = {
		exec: (...args) => {
			registrations.executions.push(args);
			throw new Error("audit_metadata must not execute commands");
		},
		on: (...args) => registrations.events.push(args),
		registerCommand: (...args) => registrations.commands.push(args),
		registerTool: (tool) => registrations.tools.push(tool),
	};
	if (auditRuntime === undefined) auditMetadata(pi);
	else auditMetadata(pi, auditRuntime);
	assert.equal(registrations.tools.length, 1, "extension must register one tool");
	return { registrations, tool: registrations.tools[0] };
}

async function invoke(tool, ctx) {
	return tool.execute("audit-metadata", {}, undefined, undefined, ctx);
}

async function testExtraction() {
	const { tool } = load(runtime({ username: "known-user", hostname: "known-host" }));
	const result = await invoke(
		tool,
		context({ model: { id: "known-model", provider: "known-provider" }, sessionId: "known-session" }),
	);

	assert.deepEqual(result.details, {
		model: "known-model",
		modelProvider: "known-provider",
		sessionId: "known-session",
		username: "known-user",
		hostname: "known-host",
	});
}

async function testOutputFormat() {
	const { tool } = load(runtime({ username: "format-user", hostname: "format-host" }));
	const result = await invoke(
		tool,
		context({ model: { id: "format-model", provider: "format-provider" }, sessionId: "format-session" }),
	);
	assert.equal(
		result.content[0]?.text,
		[
			"Model: format-model (source: Pi runtime)",
			"Model-Provider: format-provider (source: Pi runtime)",
			"Session-ID: format-session (source: Pi runtime)",
			"Username: format-user (source: Pi runtime)",
			"Hostname: format-host (source: Pi runtime)",
		].join("\n"),
	);
}

async function testDefaultRuntime() {
	const expectedUsername = os.userInfo().username;
	const expectedHostname = os.hostname();
	const { tool } = load();
	const result = await invoke(tool, context());

	assert.equal(result.details.username, expectedUsername);
	assert.equal(result.details.hostname, expectedHostname);
}

async function testInvalidValue() {
	if (!field || encodedValue === undefined) throw new Error("Invalid-value coverage requires a field and JSON value.");
	const value = JSON.parse(encodedValue);
	const auditRuntime = runtime();
	const ctx = context();
	const labels = {
		model: "Model",
		modelProvider: "Model-Provider",
		sessionId: "Session-ID",
		username: "Username",
		hostname: "Hostname",
	};
	const label = labels[field];
	if (!label) throw new Error(`Unknown audit field: ${field}`);

	if (field === "model") ctx.model.id = value;
	else if (field === "modelProvider") ctx.model.provider = value;
	else if (field === "sessionId") ctx.sessionManager = { getSessionId: () => value };
	else if (field === "username") auditRuntime.userInfo = () => ({ username: value });
	else auditRuntime.hostname = () => value;

	const { tool } = load(auditRuntime);
	let result;
	await assert.rejects(
		async () => {
			result = await invoke(tool, ctx);
		},
		(error) => {
			assert.equal(error instanceof TypeError, false, "invalid metadata must not cause a raw TypeError");
			assert.match(String(error.message), new RegExp(`${label} .+`));
			return true;
		},
	);
	assert.equal(result, undefined, "invalid metadata must not produce an audit result");
}

async function testMissingModel() {
	const { tool } = load();
	let result;
	await assert.rejects(
		async () => {
			const ctx = context();
			ctx.model = undefined;
			result = await invoke(tool, ctx);
		},
		(error) => {
			assert.equal(error instanceof TypeError, false, "missing model must not cause a raw TypeError");
			assert.match(String(error.message), /Model is missing/);
			assert.match(String(error.message), /Model-Provider is missing/);
			return true;
		},
	);
	assert.equal(result, undefined, "missing metadata must not produce an audit result");
}

async function testFreshSnapshot() {
	let username = "first-user";
	let hostname = "first-host";
	const { tool } = load({
		userInfo: () => ({ username }),
		hostname: () => hostname,
	});
	const first = await invoke(
		tool,
		context({ model: { id: "first-model", provider: "first-provider" }, sessionId: "first-session" }),
	);
	username = "second-user";
	hostname = "second-host";
	const second = await invoke(
		tool,
		context({ model: { id: "second-model", provider: "second-provider" }, sessionId: "second-session" }),
	);

	assert.deepEqual(first.details, {
		model: "first-model",
		modelProvider: "first-provider",
		sessionId: "first-session",
		username: "first-user",
		hostname: "first-host",
	});
	assert.deepEqual(second.details, {
		model: "second-model",
		modelProvider: "second-provider",
		sessionId: "second-session",
		username: "second-user",
		hostname: "second-host",
	});
	assert.notDeepEqual(first.details, second.details, "tool must read a fresh runtime snapshot for every call");
}

function testExtensionSurface() {
	const { registrations, tool } = load();
	assert.deepEqual(Object.keys(auditMetadataModule).sort(), ["default"]);
	assert.deepEqual(registrations.tools.map((registered) => registered.name), ["audit_metadata"]);
	assert.notEqual(tool.name, "bash", "audit_metadata must not override bash");
	assert.deepEqual(registrations.events, [], "audit_metadata must not register event handlers");
	assert.deepEqual(registrations.commands, [], "audit_metadata must not register commands");
	assert.deepEqual(registrations.executions, [], "audit_metadata must not execute commands");
}

const scenarios = {
	extraction: testExtraction,
	"output-format": testOutputFormat,
	"default-runtime": testDefaultRuntime,
	"invalid-value": testInvalidValue,
	"missing-model": testMissingModel,
	"fresh-snapshot": testFreshSnapshot,
	"extension-surface": testExtensionSurface,
};
const test = scenarios[scenario];
if (!test) throw new Error(`Unknown scenario: ${scenario}`);
await test();
console.log("audit metadata runtime harness: ok");
