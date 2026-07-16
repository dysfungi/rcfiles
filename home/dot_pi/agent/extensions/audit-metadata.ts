/**
 * Agents cannot reliably introspect their live model, provider, or session identity.
 * This is the single runtime-owned source for audit metadata, and it fails loud rather
 * than emitting "unknown" so durable records never contain fabricated provenance.
 */

import { VERSION, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as os from "node:os";
import { Type } from "typebox";

type AuditField = {
	label: string;
	value: unknown;
};

type AuditRuntime = {
	hostname(): unknown;
	version(): unknown;
};

const runtime: AuditRuntime = {
	hostname: () => os.hostname(),
	version: () => VERSION,
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

function auditValues(ctx: {
	model?: { id?: unknown; provider?: unknown };
	sessionManager?: { getSessionId?: () => unknown };
}, auditRuntime: AuditRuntime) {
	const fields: AuditField[] = [
		{ label: "Model", value: ctx.model?.id },
		{ label: "Model-Provider", value: ctx.model?.provider },
		{ label: "Session-ID", value: ctx.sessionManager?.getSessionId?.() },
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
		description: "Return verified live Pi runtime metadata for durable audit records.",
		parameters: Type.Object({}),
		async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
			const { values, piVersion } = auditValues(ctx, auditRuntime);
			const details = {
				model: values.Model,
				modelProvider: values["Model-Provider"],
				sessionId: values["Session-ID"],
				hostname: values.Hostname,
			};
			// The Pi audit-trail skill owns the static co-author identity trailer by design; this tool emits only provable runtime facts.
			const text = [
				`Model: ${details.model} (source: Pi ${piVersion})`,
				`Model-Provider: ${details.modelProvider} (source: Pi ${piVersion})`,
				`Session-ID: ${details.sessionId} (source: Pi ${piVersion})`,
				`Hostname: ${details.hostname} (source: Pi ${piVersion})`,
			].join("\n");

			return { content: [{ type: "text", text }], details };
		},
	});
}
