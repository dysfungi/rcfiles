/**
 * Plan Mode Extension (owned)
 *
 * Read-only exploration mode, ON BY DEFAULT for every new session.
 *
 * See DESIGN.md (same directory) for the full requirements, the options
 * evaluated, and why each decision was made. Summary of the load-bearing ones:
 *
 *   - Default-on, clean: the `plan` flag defaults to `true` and `session_start`
 *     enables plan mode whenever the flag is true with NO `reason` gate, so both
 *     fresh processes (`reason:"startup"`) and in-session `/new` (`reason:"new"`)
 *     start in plan mode. No injected `/plan` message, no startup turn, no
 *     session rename (those were the problems with the previous approach).
 *     `--no-plan` opts out; `/plan` toggles.
 *
 *   - Tool preservation: plan mode = (currently active tools) MINUS `edit`/
 *     `write`, PLUS read-only plan tools and `plan_write`. The pre-plan tool set
 *     is captured and restored on exit, so `worktree_*`/`memory_*`/`mcp`/
 *     `scratchpad` stay available throughout (no per-session reconfiguration).
 *
 *   - Hard read-only: `edit`/`write` are physically removed from the tool set,
 *     and `bash` is gated to read-only commands (see bash-safety.ts). This is a
 *     guarantee, not advice.
 *
 *   - Plans synced to disk: `edit`/`write` are gone, but the model can persist
 *     its plan via the `plan_write` tool, which can ONLY write the session's
 *     plan file at `~/.pi/agent/plans/<sessionId>.md` (one flat, browsable
 *     location; the path is derived from the session manager, not hardcoded).
 *     Memory persistence is unaffected — `memory_*` tools are preserved.
 *
 *   - Plan shown in the TUI, for free: `plan_write` has a `renderResult` slot
 *     that renders the plan as Markdown inline, so I see it automatically
 *     instead of having to `cat`/open the file. This is DISPLAY-ONLY and costs
 *     ZERO extra LLM context — it renders `context.args.content`, which the
 *     model already generated (it's in context exactly once regardless), while
 *     the model-facing tool result stays the short `Plan saved to <path>`.
 *
 *   - Re-view on demand: `/plan-show` (and Ctrl+Alt+V) opens a full-screen,
 *     scrollable Markdown pager for the current session's plan. The pager is
 *     TUI-only and never enters LLM context. Non-TUI modes retain a custom
 *     transcript entry (`pi.appendEntry` + `registerEntryRenderer`), which also
 *     does NOT participate in LLM context.
 */

import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { TextContent } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { defineTool, getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import { Box, Key, Markdown, Text, matchesKey, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { checkPlanModeBash, ensureParserLoaded, maybeWarnParserUnavailable } from "./bash-safety.ts";

const PLAN_WRITE_TOOL = "plan_write";
// Read-only tools ensured active in plan mode, plus the scoped plan writer.
const PLAN_MODE_TOOLS = ["read", "bash", "grep", "find", "ls", "questionnaire", PLAN_WRITE_TOOL];
const NORMAL_MODE_TOOLS = ["read", "bash", "edit", "write"];
const PLAN_MODE_DISABLED_TOOLS = new Set<string>(["edit", "write"]);
const PLAN_MANAGED_TOOLS = new Set<string>([...PLAN_MODE_TOOLS, ...NORMAL_MODE_TOOLS]);

const PLAN_CONTEXT = `[PLAN MODE ACTIVE]
You are in plan mode - a read-only exploration mode for safe analysis.

Restrictions:
- The edit and write tools are disabled.
- Bash is restricted to read-only commands (mutating commands are blocked).
- All other currently active tools remain available (including memory_* and worktree_*).

Investigate, then produce a clear, concise plan. Ask clarifying questions with
the questionnaire tool. Persist or update your plan to disk with the ${PLAN_WRITE_TOOL}
tool (it writes this session's plan file). Do NOT attempt to make changes or run
mutating commands; run /plan to exit plan mode when ready to execute.`;

interface PlanModeState {
	enabled: boolean;
	toolsBeforePlanMode?: string[];
}

/** Resolve this session's plan file: ~/.pi/agent/plans/<sessionId>.md.
 * Derived from the session dir (~/.pi/agent/sessions/<encoded-cwd>) so it honors
 * any pi config-dir override instead of hardcoding ~/.pi. Flat/global on purpose
 * (all plans in one browsable place), not project-namespaced. */
function resolvePlanFile(ctx: ExtensionContext): string {
	const sessionId = ctx.sessionManager.getSessionId();
	const agentDir = resolve(ctx.sessionManager.getSessionDir(), "..", "..");
	return join(agentDir, "plans", `${sessionId}.md`);
}

export default function planModeExtension(pi: ExtensionAPI): void {
	let planModeEnabled = false;
	let toolsBeforePlanMode: string[] | undefined;

	pi.registerFlag("plan", {
		description: "Start in plan mode (read-only exploration). Default: on; use --no-plan to opt out.",
		type: "boolean",
		default: true,
	});

	// Scoped plan writer: the ONLY write capability in plan mode. It can write
	// nothing but the current session's plan file, so general write stays gone.
	pi.registerTool(
		defineTool({
			name: PLAN_WRITE_TOOL,
			label: "Plan Write",
			description:
				"Persist or update the current session's plan to disk (~/.pi/agent/plans/<sessionId>.md). " +
				"Overwrites the file with the provided content. Use this in plan mode to keep the plan synced to disk.",
			promptSnippet: "plan_write(content): save/update this session's plan file",
			parameters: Type.Object({
				content: Type.String({ description: "Full Markdown content of the plan (overwrites the file)." }),
			}),
			async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
				const planFile = resolvePlanFile(ctx);
				mkdirSync(join(planFile, ".."), { recursive: true });
				writeFileSync(planFile, params.content, "utf8");
				return {
					content: [{ type: "text", text: `Plan saved to ${planFile}` }],
					details: { path: planFile },
				};
			},
			// Show the plan inline as Markdown (display-only, no LLM-context cost).
			// Rendered from context.args.content — already in context, never re-sent.
			renderResult(_result, { isPartial }, theme, context) {
				const content = (context.args as { content?: string } | undefined)?.content;
				if (isPartial || !content) return new Text(theme.fg("muted", "Saving plan…"), 0, 0);
				return new Markdown(content, 0, 0, getMarkdownTheme());
			},
		}),
	);

	// Renders a `/plan-show` snapshot into the transcript. Custom entries do NOT
	// participate in LLM context, so re-viewing the plan is also context-free.
	pi.registerEntryRenderer("plan-view", (entry, _opts, theme) => {
		const data = entry.data as { content?: string; path?: string } | undefined;
		const box = new Box(0, 0);
		box.addChild(new Text(theme.fg("muted", `📋 plan: ${data?.path ?? "(unknown)"}`)));
		box.addChild(new Markdown(data?.content ?? "(empty)", 0, 0, getMarkdownTheme()));
		return box;
	});

	// Show the current session's plan file on demand, out of LLM context.
	async function showPlan(ctx: ExtensionContext): Promise<void> {
		const planFile = resolvePlanFile(ctx);
		let content: string;
		try {
			content = readFileSync(planFile, "utf8");
		} catch {
			ctx.ui.notify("No plan saved yet for this session (use plan_write first).", "warning");
			return;
		}
		if (!content.trim()) {
			ctx.ui.notify("Plan file is empty.", "warning");
			return;
		}

		// Custom UI is only available in the interactive TUI. Preserve the prior
		// context-free transcript entry as a useful fallback for other modes.
		if (ctx.mode !== "tui") {
			pi.appendEntry("plan-view", { content, path: planFile });
			return;
		}

		await ctx.ui.custom<void>(
			(tui, theme, _keybindings, done) => {
				const markdown = new Markdown(content, 0, 0, getMarkdownTheme());
				let offset = 0;
				let width = tui.terminal.columns;

				function pageHeight(): number {
					return Math.max(1, tui.terminal.rows - 2); // Header + footer.
				}

				function lines(): string[] {
					return markdown.render(width);
				}

				function clampOffset(renderedLines = lines()): void {
					offset = Math.max(0, Math.min(offset, renderedLines.length - pageHeight()));
				}

				function surface(line: string): string {
					const truncated = truncateToWidth(line, width);
					return theme.bg("customMessageBg", `${truncated}${" ".repeat(Math.max(0, width - visibleWidth(truncated)))}`);
				}

				return {
					render(nextWidth: number): string[] {
						width = nextWidth;
						const renderedLines = lines();
						const visibleLines = pageHeight();
						clampOffset(renderedLines);
						const end = Math.min(offset + visibleLines, renderedLines.length);
						const progress = `${offset + 1}-${end} / ${renderedLines.length}`;
						const header = `${theme.bold(theme.fg("accent", "📋 Plan"))} ${theme.fg("muted", planFile)} ${theme.fg("dim", progress)}`;
						const footer = theme.fg("dim", "↑↓/j/k scroll • PgUp/PgDn page • Home/End jump • Esc/q close");
						const body = renderedLines.slice(offset, end);
						while (body.length < visibleLines) body.push("");
						return [surface(header), ...body.map(surface), surface(footer)];
					},
					invalidate(): void {
						markdown.invalidate();
					},
					handleInput(data: string): void {
						const renderedLines = lines();
						const previousOffset = offset;
						const page = pageHeight();
						if (matchesKey(data, Key.escape) || matchesKey(data, "q")) {
							done(undefined);
							return;
						}
						if (matchesKey(data, Key.up) || matchesKey(data, "k")) offset -= 1;
						else if (matchesKey(data, Key.down) || matchesKey(data, "j")) offset += 1;
						else if (matchesKey(data, Key.pageUp)) offset -= page;
						else if (matchesKey(data, Key.pageDown)) offset += page;
						else if (matchesKey(data, Key.home)) offset = 0;
						else if (matchesKey(data, Key.end)) offset = renderedLines.length;
						else return;
						clampOffset(renderedLines);
						if (offset !== previousOffset) tui.requestRender();
					},
				};
			},
			{ overlay: true, overlayOptions: { width: "100%", maxHeight: "100%", margin: 0 } },
		);
	}

	function updateStatus(ctx: ExtensionContext): void {
		ctx.ui.setStatus("plan-mode", planModeEnabled ? ctx.ui.theme.fg("warning", "⏸ plan") : undefined);
	}

	function uniqueToolNames(toolNames: string[]): string[] {
		return [...new Set(toolNames)];
	}

	function getPlanModeTools(activeToolNames: string[]): string[] {
		return uniqueToolNames([...activeToolNames.filter((name) => !PLAN_MODE_DISABLED_TOOLS.has(name)), ...PLAN_MODE_TOOLS]);
	}

	function getNormalModeTools(activeToolNames: string[]): string[] {
		return uniqueToolNames([...NORMAL_MODE_TOOLS, ...activeToolNames.filter((name) => !PLAN_MANAGED_TOOLS.has(name))]);
	}

	function enablePlanModeTools(): void {
		if (toolsBeforePlanMode === undefined) toolsBeforePlanMode = pi.getActiveTools();
		pi.setActiveTools(getPlanModeTools(toolsBeforePlanMode));
	}

	function restoreNormalModeTools(): void {
		pi.setActiveTools(toolsBeforePlanMode ?? getNormalModeTools(pi.getActiveTools()));
		toolsBeforePlanMode = undefined;
	}

	function persistState(): void {
		pi.appendEntry("plan-mode", { enabled: planModeEnabled, toolsBeforePlanMode } satisfies PlanModeState);
	}

	function togglePlanMode(ctx: ExtensionContext): void {
		planModeEnabled = !planModeEnabled;
		if (planModeEnabled) {
			enablePlanModeTools();
			ctx.ui.notify("Plan mode enabled. Write tools disabled; bash restricted to read-only.");
		} else {
			restoreNormalModeTools();
			ctx.ui.notify("Plan mode disabled. Full access restored.");
		}
		updateStatus(ctx);
		persistState();
	}

	pi.registerCommand("plan", {
		description: "Toggle plan mode (read-only exploration)",
		handler: async (_args, ctx) => togglePlanMode(ctx),
	});

	pi.registerCommand("plan-show", {
		description: "Open this session's saved plan in a full-screen pager (out of context)",
		handler: async (_args, ctx) => showPlan(ctx),
	});

	pi.registerShortcut(Key.ctrlAlt("p"), {
		description: "Toggle plan mode",
		handler: async (ctx) => togglePlanMode(ctx),
	});

	pi.registerShortcut(Key.ctrlAlt("v"), {
		description: "Open this session's saved plan in a full-screen pager",
		handler: async (ctx) => showPlan(ctx),
	});

	// Block mutating bash commands while plan mode is active.
	pi.on("tool_call", async (event, ctx) => {
		if (!planModeEnabled || event.toolName !== "bash") return;
		const command = event.input?.command as string | undefined;
		if (!command) return;
		await ensureParserLoaded();
		maybeWarnParserUnavailable(ctx);
		const reason = checkPlanModeBash(command);
		if (reason) {
			return {
				block: true,
				reason: `Plan mode: command blocked (${reason}). Run /plan to exit plan mode first.\nCommand: ${command}`,
			};
		}
	});

	// Drop stale plan-mode context from history when plan mode is off.
	pi.on("context", async (event) => {
		if (planModeEnabled) return;
		return {
			messages: event.messages.filter((m) => {
				const msg = m as AgentMessage & { customType?: string };
				if (msg.customType === "plan-mode-context") return false;
				if (msg.role !== "user") return true;
				const content = msg.content;
				if (typeof content === "string") return !content.includes("[PLAN MODE ACTIVE]");
				if (Array.isArray(content)) {
					return !content.some((c) => c.type === "text" && (c as TextContent).text?.includes("[PLAN MODE ACTIVE]"));
				}
				return true;
			}),
		};
	});

	// Inject plan-mode instructions before each turn while active.
	pi.on("before_agent_start", async () => {
		if (!planModeEnabled) return;
		return { message: { customType: "plan-mode-context", content: PLAN_CONTEXT, display: false } };
	});

	// Default-on (startup + /new) and restore persisted state (resume/fork).
	pi.on("session_start", async (_event, ctx) => {
		void ensureParserLoaded(); // warm the parser; don't block startup
		if (pi.getFlag("plan") === true) planModeEnabled = true;

		const planModeEntry = ctx.sessionManager
			.getEntries()
			.filter((e: { type: string; customType?: string }) => e.type === "custom" && e.customType === "plan-mode")
			.pop() as { data?: PlanModeState } | undefined;
		if (planModeEntry?.data) {
			planModeEnabled = planModeEntry.data.enabled ?? planModeEnabled;
			toolsBeforePlanMode = planModeEntry.data.toolsBeforePlanMode ?? toolsBeforePlanMode;
		}

		if (planModeEnabled) enablePlanModeTools();
		updateStatus(ctx);
	});
}
