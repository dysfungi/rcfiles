/**
 * Root-Thread Context-Discipline Guard
 *
 * Enforces AGENTS.md's root-thread rule at pi's tool-call boundary: interactive
 * TUI/RPC roots orchestrate, while subagents perform reads, shell work, MCP, and
 * exploration in isolated JSON contexts. This is deliberately block-by-default
 * so future tools cannot quietly reintroduce context pollution.
 *
 * JSON subagents and print-mode one-shots are exempt. Root permits only
 * orchestration tools plus read access to plans, memory, global skill roots,
 * and repo task files. There is intentionally no bypass sentinel: disabling this guard means
 * explicitly removing the managed extension and reloading pi.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isInteractiveRoot } from "./child-policy.mjs";
import { decideToolCall } from "./root-thread-guard-core.mjs";

export default function rootThreadGuard(pi: ExtensionAPI): void {
	let active = false;

	pi.on("session_start", async (_event, ctx) => {
		active = isInteractiveRoot(ctx.mode);
		ctx.ui.setStatus("root-thread-guard", active ? ctx.ui.theme.fg("warning", "🧭 root") : undefined);
	});

	pi.on("tool_call", async (event, ctx) => {
		if (!active) return;
		const decision = decideToolCall({
			mode: ctx.mode,
			toolName: event.toolName,
			input: event.input,
			cwd: ctx.cwd,
		});
		if (!decision.allowed) return { block: true, reason: decision.reason };
	});
}
