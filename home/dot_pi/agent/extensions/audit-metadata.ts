/**
 * Agents cannot reliably introspect their live model, provider, or session identity.
 * This is the single runtime-owned source for audit metadata, and it fails loud rather
 * than emitting "unknown" so durable records never contain fabricated provenance.
 */

import { VERSION, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readFileSync } from "node:fs";
import * as os from "node:os";
import { join } from "node:path";
import { Type } from "typebox";

type AuditField = {
	label: string;
	value: unknown;
};

type GatewayProviders = Record<string, string>;

type RootIdentity = {
	model: string;
	provider: string;
	sessionId: string;
};

type AuditContext = {
	model?: { id?: unknown; provider?: unknown };
	sessionManager?: { getSessionId?: () => unknown };
};

type AuditRuntime = {
	hostname(): unknown;
	version(): unknown;
	gatewayProviders(): unknown;
};

const ROOT_IDENTITY_ENV = "PI_ROOT_IDENTITY";
const GATEWAY_PROVIDERS_FILE = "gateway-providers.json";

function configuredAgentDirectory(): string {
	return process.env.PI_CODING_AGENT_DIR ?? join(os.homedir(), ".pi", "agent");
}

const runtime: AuditRuntime = {
	hostname: () => os.hostname(),
	version: () => VERSION,
	gatewayProviders: () => {
		const filePath = join(configuredAgentDirectory(), GATEWAY_PROVIDERS_FILE);
		try {
			return JSON.parse(readFileSync(filePath, "utf8"));
		} catch (error) {
			const detail = error instanceof Error ? error.message : String(error);
			throw new Error(`Unable to load gateway provider catalog ${filePath}: ${detail}`);
		}
	},
};

function validationProblems(value: unknown): string[] {
	if (typeof value !== "string") return ["is missing"];

	const problems: string[] = [];
	const trimmedValue = value.trim();
	if (!trimmedValue) problems.push("must be a non-empty string");
	if (trimmedValue.toLowerCase().startsWith("unknown")) problems.push('must not use "unknown"');
	if (/\r|\n/.test(value)) problems.push("must not contain carriage returns or newlines");
	return problems;
}

function rootIdentityFromEnvironment(): RootIdentity | undefined {
	const encodedIdentity = process.env[ROOT_IDENTITY_ENV];
	if (encodedIdentity === undefined) return undefined;

	let envelope: unknown;
	try {
		envelope = JSON.parse(encodedIdentity);
	} catch (error) {
		const detail = error instanceof Error ? error.message : String(error);
		throw new Error(`${ROOT_IDENTITY_ENV} envelope contains invalid JSON: ${detail}`);
	}
	if (typeof envelope !== "object" || envelope === null || Array.isArray(envelope)) {
		throw new Error(`${ROOT_IDENTITY_ENV} envelope must be a JSON object`);
	}

	const identity = envelope as Record<string, unknown>;
	const requiredFields = ["model", "provider", "sessionId"] as const;
	for (const field of requiredFields) {
		if (!Object.prototype.hasOwnProperty.call(identity, field)) {
			throw new Error(`${ROOT_IDENTITY_ENV} envelope is missing field '${field}'`);
		}
		if (typeof identity[field] !== "string") {
			throw new Error(`${ROOT_IDENTITY_ENV} envelope field '${field}' must be a string`);
		}
		if (!identity[field].trim()) {
			throw new Error(`${ROOT_IDENTITY_ENV} envelope field '${field}' must be a non-empty string`);
		}
	}
	return identity as RootIdentity;
}

function parseGatewayProviders(value: unknown): GatewayProviders {
	if (typeof value !== "object" || value === null || Array.isArray(value)) {
		throw new Error("Invalid gateway provider catalog: root must be a JSON object");
	}

	const providers: GatewayProviders = {};
	for (const [provider, displayName] of Object.entries(value)) {
		const providerFailures = validationProblems(provider);
		const displayNameFailures = validationProblems(displayName);
		if (providerFailures.length > 0 || displayNameFailures.length > 0) {
			const failures = [
				...providerFailures.map((problem) => `provider ${JSON.stringify(provider)} ${problem}`),
				...displayNameFailures.map((problem) => `display name for provider ${JSON.stringify(provider)} ${problem}`),
			];
			throw new Error(`Invalid gateway provider catalog: ${failures.join("; ")}`);
		}
		providers[provider] = displayName as string;
	}
	return providers;
}

function auditValues(ctx: AuditContext, auditRuntime: AuditRuntime) {
	// PI_ROOT_IDENTITY is a JSON envelope set by the managed child launcher:
	// {"model":"<id>","provider":"<provider-id>","sessionId":"<root-session-id>"}.
	// Its presence is authoritative; malformed envelopes expose launcher defects instead of falling back.
	const rootIdentity = rootIdentityFromEnvironment();
	const model = rootIdentity?.model ?? ctx.model?.id;
	const provider = rootIdentity?.provider ?? ctx.model?.provider;
	const sessionId = rootIdentity?.sessionId ?? ctx.sessionManager?.getSessionId?.();
	const gatewayProviders = parseGatewayProviders(auditRuntime.gatewayProviders());
	const modelGateway =
		typeof provider === "string" && Object.prototype.hasOwnProperty.call(gatewayProviders, provider)
			? gatewayProviders[provider]
			: undefined;
	const fields: AuditField[] = [
		{ label: "Model", value: model },
		{ label: "Model-Provider", value: provider },
		...(modelGateway === undefined ? [] : [{ label: "Model-Gateway", value: modelGateway }]),
		{ label: "Session-ID", value: sessionId },
		{ label: "Hostname", value: auditRuntime.hostname() },
	];
	const piVersion = auditRuntime.version();
	const failures = [...fields, { label: "Pi-Version", value: piVersion }].flatMap(({ label, value }) =>
		validationProblems(value).map((problem) => `${label} ${problem}`),
	);
	if (failures.length > 0) throw new Error(`Invalid audit metadata: ${failures.join("; ")}`);

	return {
		values: Object.fromEntries(fields.map(({ label, value }) => [label, value])) as Record<string, string>,
		piVersion: piVersion as string,
	};
}

export default function auditMetadata(pi: ExtensionAPI, auditRuntime: AuditRuntime = runtime): void {
	pi.registerTool({
		name: "audit_metadata",
		label: "Audit Metadata",
		description: "Return verified root Pi identity and executing-host metadata for durable audit records.",
		parameters: Type.Object({}),
		async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
			const { values, piVersion } = auditValues(ctx, auditRuntime);
			const details = {
				model: values.Model,
				modelProvider: values["Model-Provider"],
				...(values["Model-Gateway"] === undefined ? {} : { modelGateway: values["Model-Gateway"] }),
				sessionId: values["Session-ID"],
				hostname: values.Hostname,
			};
			// The audit-trail skill owns durable-record formatting; this tool emits only provable runtime facts.
			const text = [
				`Authored-By: Pi ${piVersion}`,
				`Model: ${details.model}`,
				`Model-Provider: ${details.modelProvider}`,
				...(details.modelGateway === undefined ? [] : [`Model-Gateway: ${details.modelGateway}`]),
				`Session-ID: ${details.sessionId}`,
				`Hostname: ${details.hostname}`,
			].join("\n");

			return { content: [{ type: "text", text }], details };
		},
	});
}
