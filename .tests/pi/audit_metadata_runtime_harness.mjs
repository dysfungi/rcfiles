#!/usr/bin/env node
/** Runtime coverage for the managed read-only Pi audit metadata extension. */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import * as os from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [extensionPath, packageDir, scenario, expectedError] = process.argv.slice(2);
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

function runtime({ hostname = "host-alpha", version = "0.80.6-test", gatewayProviders = {} } = {}) {
	return {
		hostname: () => hostname,
		version: () => version,
		gatewayProviders: () => gatewayProviders,
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
	const { tool } = load(runtime({ hostname: "known-host" }));
	const result = await invoke(
		tool,
		context({ model: { id: "known-model", provider: "known-provider" }, sessionId: "known-session" }),
	);

	assert.deepEqual(result.details, {
		model: "known-model",
		modelProvider: "known-provider",
		sessionId: "known-session",
		hostname: "known-host",
	});
}

async function testOutputFormat() {
	const { tool } = load(runtime({ hostname: "format-host", version: "1.2.3" }));
	const result = await invoke(
		tool,
		context({ model: { id: "format-model", provider: "format-provider" }, sessionId: "format-session" }),
	);
	assert.equal(
		result.content[0]?.text,
		[
			"Authored-By: Pi 1.2.3",
			"Model: format-model",
			"Model-Provider: format-provider",
			"Session-ID: format-session",
			"Hostname: format-host",
		].join("\n"),
	);
}

async function testDefaultRuntime() {
	const expectedHostname = os.hostname();
	const { VERSION } = require(join(packageDir, "dist", "index.js"));
	const agentDir = mkdtempSync(join(os.tmpdir(), "pi-audit-metadata-"));
	const previousAgentDir = process.env.PI_CODING_AGENT_DIR;
	writeFileSync(join(agentDir, "gateway-providers.json"), "{}");
	process.env.PI_CODING_AGENT_DIR = agentDir;
	try {
		const { tool } = load();
		const result = await invoke(tool, context());

		assert.equal(result.details.hostname, expectedHostname);
		assert.equal(result.content[0]?.text.split("\n")[0], `Authored-By: Pi ${VERSION}`);
	} finally {
		if (previousAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR;
		else process.env.PI_CODING_AGENT_DIR = previousAgentDir;
		rmSync(agentDir, { recursive: true, force: true });
	}
}

async function testRootEnvelope() {
	assert.ok(process.env.PI_ROOT_IDENTITY, "root-envelope coverage requires PI_ROOT_IDENTITY");
	const { tool } = load(runtime({ gatewayProviders: { "root-provider": "Catalog Gateway" }, hostname: "child-host" }));
	const result = await invoke(
		tool,
		context({
			model: { id: "child-model", provider: "child-provider" },
			sessionId: "child-session",
		}),
	);

	assert.deepEqual(result.details, {
		model: "root-model",
		modelProvider: "root-provider",
		modelGateway: "Catalog Gateway",
		sessionId: "root-session",
		hostname: "child-host",
	});
	assert.match(result.content[0]?.text ?? "", /^Model: root-model$/m);
	assert.match(result.content[0]?.text ?? "", /^Model-Provider: root-provider$/m);
	assert.match(result.content[0]?.text ?? "", /^Model-Gateway: Catalog Gateway$/m);
	assert.match(result.content[0]?.text ?? "", /^Session-ID: root-session$/m);
	assert.doesNotMatch(result.content[0]?.text ?? "", /child-(?:model|provider|session)/);
}

async function testNestedRootEnvelope() {
	assert.equal(process.env.PI_ROOT_IDENTITY, undefined, "nested-root-envelope must begin at the root");
	const directory = mkdtempSync(join(os.tmpdir(), "pi-audit-metadata-nested-"));
	const script = join(directory, "nested-audit.mjs");
	const reportPath = join(directory, "report.json");
	const childEnvironmentPath = resolve(extensionPath, "..", "subagent", "child-env.mjs");
	writeFileSync(
		script,
		[
			'import { spawnSync } from "node:child_process";',
			'import { writeFileSync } from "node:fs";',
			'import { createRequire } from "node:module";',
			'import { join, resolve } from "node:path";',
			'import { pathToFileURL } from "node:url";',
			"const [role, childEnvironmentPath, auditExtensionPath, packageDir, reportPath] = process.argv.slice(2);",
			'if (role === "first") {',
			"\tconst { childEnvironment, rootIdentityEnvelope } = await import(pathToFileURL(childEnvironmentPath).href);",
			"\tconst rootIdentity = rootIdentityEnvelope(process.env, { model: { id: \"model-B\", provider: \"provider-B\" }, sessionManager: { getSessionId: () => \"session-B\" } });",
			"\tconst nested = spawnSync(process.execPath, [process.argv[1], \"grandchild\", childEnvironmentPath, auditExtensionPath, packageDir, reportPath], { encoding: \"utf8\", env: childEnvironment(process.env, { rootIdentity }) });",
			'\tif (nested.status !== 0) throw new Error(nested.stderr || "grandchild audit process failed");',
			"} else if (role === \"grandchild\") {",
			"\tconst require = createRequire(pathToFileURL(join(packageDir, \"package.json\")));",
			"\tconst nodeModules = join(packageDir, \"node_modules\");",
			"\tconst jiti = require(\"jiti\")(import.meta.url, { alias: {",
			"\t\t\"@earendil-works/pi-coding-agent\": join(packageDir, \"dist\", \"index.js\"),",
			"\t\t\"@earendil-works/pi-tui\": join(nodeModules, \"@earendil-works\", \"pi-tui\", \"dist\", \"index.js\"),",
			"\t\ttypebox: join(nodeModules, \"typebox\", \"build\", \"index.mjs\"),",
			"\t} });",
			"\tconst { default: auditMetadata } = await jiti.import(resolve(auditExtensionPath));",
			"\tlet tool;",
			"\tauditMetadata({ registerTool(definition) { tool = definition; } }, { hostname: () => \"grandchild-host\", version: () => \"nested-version\", gatewayProviders: () => ({}) });",
			"\tconst result = await tool.execute(\"nested-audit\", {}, undefined, undefined, { model: { id: \"model-C\", provider: \"provider-C\" }, sessionManager: { getSessionId: () => \"session-C\" } });",
			"\twriteFileSync(reportPath, JSON.stringify({ rootIdentity: process.env.PI_ROOT_IDENTITY, text: result.content[0]?.text, details: result.details, processId: process.pid, parentProcessId: process.ppid }));",
			"} else {",
			'\tthrow new Error(`Unknown nested audit role: ${role}`);',
			"}",
		].join("\n"),
	);
	try {
		const { childEnvironment, rootIdentityEnvelope } = await import(pathToFileURL(childEnvironmentPath).href);
		const expectedIdentity = { model: "model-A", provider: "provider-A", sessionId: "session-A" };
		const rootIdentity = rootIdentityEnvelope(process.env, {
			model: { id: expectedIdentity.model, provider: expectedIdentity.provider },
			sessionManager: { getSessionId: () => expectedIdentity.sessionId },
		});
		const first = spawnSync(
			process.execPath,
			[script, "first", childEnvironmentPath, extensionPath, packageDir, reportPath],
			{ encoding: "utf8", env: childEnvironment(process.env, { rootIdentity }) },
		);
		assert.equal(first.status, 0, first.stderr);
		const report = JSON.parse(readFileSync(reportPath, "utf8"));
		assert.notEqual(report.processId, first.pid, "the audit handler must run in a real grandchild process");
		assert.equal(report.parentProcessId, first.pid, "the audit handler's process must be spawned by the first-level child");
		assert.deepEqual(JSON.parse(report.rootIdentity), expectedIdentity);
		assert.match(report.text, /^Model: model-A$/m);
		assert.match(report.text, /^Model-Provider: provider-A$/m);
		assert.match(report.text, /^Session-ID: session-A$/m);
		assert.doesNotMatch(report.text, /(?:model|provider|session)-[BC]/);
	} finally {
		rmSync(directory, { recursive: true, force: true });
	}
}

async function testInvalidRootEnvelope() {
	assert.ok(process.env.PI_ROOT_IDENTITY !== undefined, "invalid-root-envelope coverage requires PI_ROOT_IDENTITY");
	if (!expectedError) throw new Error("invalid-root-envelope coverage requires an expected error pattern");
	const { tool } = load(runtime());
	let result;
	await assert.rejects(
		async () => {
			result = await invoke(tool, context());
		},
		(error) => {
			assert.equal(error instanceof TypeError, false, "invalid root identity must not cause a raw TypeError");
			assert.match(String(error.message), new RegExp(expectedError));
			return true;
		},
	);
	assert.equal(result, undefined, "invalid root identity must not produce an audit result");
}

async function testGatewayProvider() {
	const { tool } = load(
		runtime({ gatewayProviders: { "gateway-provider": "Catalog Gateway" }, hostname: "gateway-host" }),
	);
	const result = await invoke(
		tool,
		context({
			model: { id: "gateway-model", provider: "gateway-provider" },
			sessionId: "gateway-session",
		}),
	);

	assert.equal(
		result.content[0]?.text,
		[
			"Authored-By: Pi 0.80.6-test",
			"Model: gateway-model",
			"Model-Provider: gateway-provider",
			"Model-Gateway: Catalog Gateway",
			"Session-ID: gateway-session",
			"Hostname: gateway-host",
		].join("\n"),
	);
	assert.equal(result.details.modelGateway, "Catalog Gateway");
}

async function testDirectProvider() {
	const { tool } = load(runtime());
	const result = await invoke(
		tool,
		context({
			model: { id: "direct-model", provider: "direct-provider" },
			sessionId: "direct-session",
		}),
	);

	assert.doesNotMatch(result.content[0]?.text ?? "", /^Model-Gateway:/m);
	assert.equal("modelGateway" in result.details, false);
}

async function testInvalidValue() {
	const field = process.argv[5];
	const encodedValue = process.argv[6];
	if (!field || encodedValue === undefined) throw new Error("Invalid-value coverage requires a field and JSON value.");
	const value = JSON.parse(encodedValue);
	const auditRuntime = runtime();
	const ctx = context();
	const labels = {
		model: "Model",
		modelProvider: "Model-Provider",
		sessionId: "Session-ID",
		hostname: "Hostname",
		piVersion: "Pi-Version",
	};
	const label = labels[field];
	if (!label) throw new Error(`Unknown audit field: ${field}`);

	if (field === "model") ctx.model.id = value;
	else if (field === "modelProvider") ctx.model.provider = value;
	else if (field === "sessionId") ctx.sessionManager = { getSessionId: () => value };
	else if (field === "hostname") auditRuntime.hostname = () => value;
	else auditRuntime.version = () => value;

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

async function testMissingVersion() {
	const auditRuntime = runtime();
	auditRuntime.version = () => undefined;
	const { tool } = load(auditRuntime);
	let result;
	await assert.rejects(
		async () => {
			result = await invoke(tool, context());
		},
		(error) => {
			assert.equal(error instanceof TypeError, false, "missing version must not cause a raw TypeError");
			assert.match(String(error.message), /Pi-Version is missing/);
			return true;
		},
	);
	assert.equal(result, undefined, "missing version must not produce an audit result");
}

async function testMissingModel() {
	const { tool } = load(runtime());
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
	let hostname = "first-host";
	let version = "1.0.0";
	const { tool } = load({
		hostname: () => hostname,
		version: () => version,
		gatewayProviders: () => ({}),
	});
	const first = await invoke(
		tool,
		context({ model: { id: "first-model", provider: "first-provider" }, sessionId: "first-session" }),
	);
	hostname = "second-host";
	version = "2.0.0";
	const second = await invoke(
		tool,
		context({ model: { id: "second-model", provider: "second-provider" }, sessionId: "second-session" }),
	);

	assert.deepEqual(first.details, {
		model: "first-model",
		modelProvider: "first-provider",
		sessionId: "first-session",
		hostname: "first-host",
	});
	assert.deepEqual(second.details, {
		model: "second-model",
		modelProvider: "second-provider",
		sessionId: "second-session",
		hostname: "second-host",
	});
	assert.notDeepEqual(first.details, second.details, "tool must read a fresh runtime snapshot for every call");
	assert.match(first.content[0]?.text ?? "", /^Authored-By: Pi 1\.0\.0$/m);
	assert.match(second.content[0]?.text ?? "", /^Authored-By: Pi 2\.0\.0$/m);
}

function testExtensionSurface() {
	const { registrations, tool } = load(runtime());
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
	"root-envelope": testRootEnvelope,
	"nested-root-envelope": testNestedRootEnvelope,
	"invalid-root-envelope": testInvalidRootEnvelope,
	"gateway-provider": testGatewayProvider,
	"direct-provider": testDirectProvider,
	"invalid-value": testInvalidValue,
	"missing-model": testMissingModel,
	"missing-version": testMissingVersion,
	"fresh-snapshot": testFreshSnapshot,
	"extension-surface": testExtensionSurface,
};
const test = scenarios[scenario];
if (!test) throw new Error(`Unknown scenario: ${scenario}`);
await test();
console.log("audit metadata runtime harness: ok");
