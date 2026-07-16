/**
 * Plan Mode Extension (owned)
 *
 * Read-only exploration phase, ON BY DEFAULT for interactive root sessions.
 *
 * See DESIGN.md (same directory) for the full requirements, the options
 * evaluated, and why each decision was made. Summary of the load-bearing ones:
 *
 *   - Interactive-root-only, clean: the `plan` flag defaults to `true` and
 *     `session_start` enables the plan phase only in `tui`/`rpc` root sessions. Both
 *     fresh processes (`reason:"startup"`) and in-session `/new` (`reason:"new"`)
 *     start in the plan phase there. Spawned `json` workers, one-shot `print`
 *     invocations, and processes marked `PI_SUBAGENT=1` keep this extension inert,
 *     while the subagent launcher inherits `PI_ROOT_PHASE` and downgrades them to
 *     read-only when their root remains in the plan phase. No injected `/plan` message, startup
 *     turn, or session rename; the internal default starts eligible sessions in
 *     the plan phase. `/plan` selects the plan phase,
 *     `/normal` selects the execute phase, and `/phase [plan|execute]` selects or cycles
 *     phases. `/execute` selects the execute phase and sends one implementation kickoff.
 *     `/implement` is intentionally unregistered here: its prompt template owns
 *     the scout → planner → worker implementation workflow.
 *
 *   - Tool preservation: plan phase = (currently active tools) MINUS `edit`/
 *     `write`, PLUS read-only plan tools and `plan_write`. The pre-plan tool set
 *     is captured and restored on exit, so root worktree lifecycle tools stay
 *     available throughout. The separate
 *     root-thread guard still blocks root Bash and MCP exploration.
 *
 *   - Hard read-only: `edit`/`write` are physically removed from the tool set.
 *     `bash` also has an independent best-effort mutation gate (see
 *     bash-safety.ts), while root-thread-guard blocks root Bash entirely in the
 *     managed configuration.
 *
 *   - Plans synced to disk: `edit`/`write` are gone, but the model can persist
 *     its plan via the `plan_write` tool, which can ONLY write the session's
 *     plan file at `~/.pi/agent/plans/<sessionId>.md` (one flat, browsable
 *     location; the path is derived from the session manager, not hardcoded).
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

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { copyToClipboard, defineTool, getMarkdownTheme, rawKeyHint } from "@earendil-works/pi-coding-agent";
import { Box, Key, Markdown, Text, matchesKey, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { checkPlanModeBash, ensureParserLoaded, maybeWarnParserUnavailable } from "./bash-safety.ts";
import { isPlanPhaseActive } from "./mode.mjs";

const PLAN_WRITE_TOOL = "plan_write";
const PLAN_COPY_KEY = "c";
const COPY_STATUS_DURATION_MS = 1500;
// Nominal plan tools plus the scoped plan writer; root-thread-guard separately
// controls which interactive-root calls remain invocable.
const PLAN_MODE_TOOLS = ["read", "bash", "grep", "find", "ls", "questionnaire", PLAN_WRITE_TOOL];
const NORMAL_MODE_TOOLS = ["read", "bash", "edit", "write"];
const PLAN_MODE_DISABLED_TOOLS = new Set<string>(["edit", "write"]);
const PLAN_MANAGED_TOOLS = new Set<string>([...PLAN_MODE_TOOLS, ...NORMAL_MODE_TOOLS]);

const PLAN_CONTEXT = `[PLAN MODE ACTIVE]
You are in the plan phase - a read-only exploration phase for safe analysis.

Restrictions:
- The edit and write tools are disabled.
- The root-thread guard blocks Bash, MCP, and exploratory root calls; delegate them to a read-only subagent.
- Root orchestration, task, and worktree lifecycle tools remain available.

Investigate through delegated agents, then produce a clear, concise plan. Ask
clarifying questions with the questionnaire tool. Persist or update your plan
to disk with the ${PLAN_WRITE_TOOL} tool (it writes this session's plan file).
Do NOT attempt to make changes or run mutating commands; run /normal to select the
execute phase or /execute to begin implementation.`;

interface PlanModeState {
	enabled: boolean;
	toolsBeforePlanMode?: string[];
}

type PhaseName = "plan" | "execute";

const PHASE_NAMES: readonly PhaseName[] = ["plan", "execute"];
const IMPLEMENTATION_KICKOFF = "Implement the approved plan now.";

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
	let planPhaseActive = false;
	let toolsBeforePlanMode: string[] | undefined;

	pi.registerFlag("plan", {
		description: "Internal default: eligible interactive root sessions start in the read-only plan phase.",
		type: "boolean",
		default: true,
	});

	// Scoped plan writer: the ONLY write capability in the plan phase. It can write
	// nothing but the current session's plan file, so general write stays gone.
	pi.registerTool(
		defineTool({
			name: PLAN_WRITE_TOOL,
			label: "Plan Write",
			description:
				"Persist or update the current session's plan to disk (~/.pi/agent/plans/<sessionId>.md). " +
				"Overwrites the file with the provided content. Use this in the plan phase to keep the plan synced to disk.",
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
			(tui, theme, keybindings, done) => {
				const markdown = new Markdown(content, 0, 0, getMarkdownTheme());
				let offset = 0;
				let width = tui.terminal.columns;
				let closed = false;
				let copyStatus: "idle" | "copying" | "copied" | "error" = "idle";
				let copyGeneration = 0;
				let copyRevertTimer: ReturnType<typeof setTimeout> | undefined;
				let copyErrorMessage: string | undefined;

				function clearCopyRevertTimer(): void {
					if (copyRevertTimer === undefined) return;
					clearTimeout(copyRevertTimer);
					copyRevertTimer = undefined;
				}

				function close(): void {
					if (closed) return;
					closed = true;
					clearCopyRevertTimer();
					done(undefined);
				}

				function triggerCopy(): void {
					if (copyStatus === "copying") return;
					clearCopyRevertTimer();
					const generation = ++copyGeneration;
					copyStatus = "copying";
					tui.requestRender();
					// Each callback carries the generation guard because it, not timer cleanup,
					// prevents an earlier copy from overwriting newer feedback. Clearing timers
					// merely avoids harmless dangling work.
					void copyToClipboard(content)
						.then(() => {
							if (closed || generation !== copyGeneration) return;
							copyStatus = "copied";
						})
						.catch((error) => {
							if (closed || generation !== copyGeneration) return;
							copyStatus = "error";
							copyErrorMessage = error instanceof Error ? error.message : String(error);
						})
						.finally(() => {
							if (closed || generation !== copyGeneration) return;
							tui.requestRender();
							copyRevertTimer = setTimeout(() => {
								copyRevertTimer = undefined;
								if (closed || generation !== copyGeneration) return;
								copyStatus = "idle";
								tui.requestRender();
							}, COPY_STATUS_DURATION_MS);
						});
				}

				function closeHint(cancelKeys: string[]): string {
					const closeKeys = [...new Set([...cancelKeys, "q"])];
					return rawKeyHint(closeKeys.join("/"), "close");
				}

				function copyFooterSegment(cancelKeys: string[]): string {
					switch (copyStatus) {
						case "copying":
							return theme.fg("dim", "Copying…");
						case "copied":
							return theme.fg("success", "✓ Copied");
						case "error":
							return theme.fg("error", `✗ Copy failed: ${copyErrorMessage}`);
						case "idle":
							return cancelKeys.includes(PLAN_COPY_KEY) ? "" : rawKeyHint(PLAN_COPY_KEY, "copy");
					}
				}

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
						const cancelKeys = keybindings.getKeys("tui.select.cancel");
						const copySegment = copyFooterSegment(cancelKeys);
						const footer = `${closeHint(cancelKeys)}${copySegment ? ` • ${copySegment}` : ""}${theme.fg(
							"dim",
							" • ↑↓/j/k scroll • PgUp/PgDn page • Ctrl+d/Ctrl+u half-page • Home/End jump",
						)}`;
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
						if (keybindings.matches(data, "tui.select.cancel") || matchesKey(data, "q")) {
							close();
							return;
						}
						if (matchesKey(data, PLAN_COPY_KEY)) {
							triggerCopy();
							return;
						}
						const halfPage = Math.max(1, Math.ceil(page / 2));
						if (matchesKey(data, Key.ctrl("d"))) offset += halfPage;
						else if (matchesKey(data, Key.ctrl("u"))) offset -= halfPage;
						else if (matchesKey(data, Key.up) || matchesKey(data, "k")) offset -= 1;
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
		ctx.ui.setStatus("plan-mode", planPhaseActive ? ctx.ui.theme.fg("warning", "⏸ plan") : undefined);
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
		const activeTools = pi.getActiveTools();
		const restoredTools = toolsBeforePlanMode ?? getNormalModeTools(activeTools);
		const toolsAddedDuringPlanMode = activeTools.filter((name) => !PLAN_MANAGED_TOOLS.has(name));
		pi.setActiveTools(uniqueToolNames([...restoredTools, ...toolsAddedDuringPlanMode]));
		toolsBeforePlanMode = undefined;
	}

	function persistState(): void {
		pi.appendEntry("plan-mode", { enabled: planPhaseActive, toolsBeforePlanMode } satisfies PlanModeState);
	}

	/** Select a phase without ever treating an explicit selection as a toggle. */
	function selectPhase(phase: PhaseName, ctx: ExtensionContext): void {
		const planPhaseSelected = phase === "plan";
		process.env.PI_ROOT_PHASE = phase;
		// Do not rewrite another extension's tool state or append duplicate context
		// when an explicit selector repeats the already active phase.
		if (planPhaseActive === planPhaseSelected) return;

		planPhaseActive = planPhaseSelected;
		if (planPhaseActive) {
			enablePlanModeTools();
			ctx.ui.notify("Plan phase enabled. Write tools disabled; delegate Bash/MCP exploration.");
		} else {
			restoreNormalModeTools();
			ctx.ui.notify("Execute phase enabled. Full access restored.");
		}
		updateStatus(ctx);
		persistState();
	}

	function requireIdle(ctx: ExtensionContext, command: string): boolean {
		if (ctx.isIdle()) return true;
		ctx.ui.notify(`/${command} requires an idle agent. Wait for the current run to finish.`, "warning");
		return false;
	}

	function parsePhaseArgument(args: string): PhaseName | "cycle" | undefined {
		const tokens = args.trim().split(/\s+/).filter(Boolean);
		if (tokens.length === 0) return "cycle";
		if (tokens.length !== 1) return undefined;
		const phase = tokens[0].toLowerCase();
		return PHASE_NAMES.find((name) => name === phase);
	}

	function cyclePhase(ctx: ExtensionContext): void {
		selectPhase(planPhaseActive ? "execute" : "plan", ctx);
	}

	function buildImplementationKickoff(args: string): string {
		const additionalInstructions = args.trim();
		return additionalInstructions
			? `${IMPLEMENTATION_KICKOFF}\n\n--- Additional implementation instructions ---\n${additionalInstructions}`
			: IMPLEMENTATION_KICKOFF;
	}

	function startImplementation(args: string, ctx: ExtensionContext): void {
		if (!requireIdle(ctx, "execute")) return;

		// Transition first and never roll it back: even a failed kickoff must leave
		// full tools visible and plan-phase context disabled for the next attempt.
		selectPhase("execute", ctx);
		try {
			pi.sendUserMessage(buildImplementationKickoff(args));
		} catch (error) {
			const detail = error instanceof Error ? `: ${error.message}` : "";
			ctx.ui.notify(`Could not start implementation${detail}. Execute phase remains active.`, "error");
		}
	}

	pi.registerCommand("plan", {
		description: "Select plan phase (read-only exploration)",
		handler: async (_args, ctx) => {
			if (requireIdle(ctx, "plan")) selectPhase("plan", ctx);
		},
	});

	pi.registerCommand("normal", {
		description: "Alias for execute phase (full tool access)",
		handler: async (_args, ctx) => {
			if (requireIdle(ctx, "normal")) selectPhase("execute", ctx);
		},
	});

	pi.registerCommand("phase", {
		description: "Select plan or execute phase; omit the argument to cycle",
		getArgumentCompletions: (argumentPrefix) => {
			const prefix = argumentPrefix.trim().toLowerCase();
			if (/\s/.test(argumentPrefix.trim())) return null;
			const matches = PHASE_NAMES.filter((name) => name.startsWith(prefix));
			return matches.length > 0 ? matches.map((value) => ({ value, label: value })) : null;
		},
		handler: async (args, ctx) => {
			const requestedPhase = parsePhaseArgument(args);
			if (!requestedPhase) {
				ctx.ui.notify("Usage: /phase [plan|execute] (use an exact full phase name).", "warning");
				return;
			}
			if (!requireIdle(ctx, "phase")) return;
			if (requestedPhase === "cycle") cyclePhase(ctx);
			else selectPhase(requestedPhase, ctx);
		},
	});

	pi.registerCommand("execute", {
		description: "Select execute phase and start implementing the approved plan",
		handler: async (args, ctx) => startImplementation(args, ctx),
	});

	pi.registerCommand("plan-show", {
		description: "Open this session's saved plan in a full-screen pager (out of context)",
		handler: async (_args, ctx) => showPlan(ctx),
	});

	pi.registerShortcut(Key.ctrlAlt("p"), {
		description: "Cycle plan and execute phases",
		handler: async (ctx) => {
			if (requireIdle(ctx, "phase")) cyclePhase(ctx);
		},
	});

	pi.registerShortcut(Key.ctrlAlt("v"), {
		description: "Open this session's saved plan in a full-screen pager",
		handler: async (ctx) => showPlan(ctx),
	});

	// Block mutating bash commands while the plan phase is active.
	pi.on("tool_call", async (event, ctx) => {
		if (!planPhaseActive || event.toolName !== "bash") return;
		const command = event.input?.command as string | undefined;
		if (!command) return;
		await ensureParserLoaded();
		maybeWarnParserUnavailable(ctx);
		const reason = checkPlanModeBash(command);
		if (reason) {
			return {
				block: true,
				reason: `Plan phase: command blocked (${reason}). Run /normal to select the execute phase first.\nCommand: ${command}`,
			};
		}
	});

	// Structured context is extension-owned. Older sessions may contain the
	// exact unstructured injection that preceded customType; preserve its cleanup
	// without treating an ordinary user quote of the marker as extension context.
	pi.on("context", async (event) => {
		const isPlanModeContext = (message: {
			customType?: unknown;
			role?: unknown;
			content?: unknown;
			display?: unknown;
		}): boolean =>
			message.customType === "plan-mode-context" ||
			(message.customType === undefined &&
				message.role === "user" &&
				message.content === PLAN_CONTEXT &&
				message.display === false);

		if (planPhaseActive) {
			const newestPlanContext = event.messages.findLastIndex(isPlanModeContext);
			if (newestPlanContext === -1) return;
			return {
				messages: event.messages.filter((message, index) => !isPlanModeContext(message) || index === newestPlanContext),
			};
		}

		return { messages: event.messages.filter((message) => !isPlanModeContext(message)) };
	});

	// Inject plan-phase instructions before each turn while active.
	pi.on("before_agent_start", async () => {
		if (!planPhaseActive) return;
		return { message: { customType: "plan-mode-context", content: PLAN_CONTEXT, display: false } };
	});

	// Default-on (startup + /new) and restore persisted state (resume/fork).
	// Child plan-mode extensions stay inert, but their launchers inherit PI_ROOT_PHASE so
	// nested delegation cannot escape the root session's plan-phase read-only policy.
	pi.on("session_start", async (_event, ctx) => {
		if (!isPlanPhaseActive(ctx.mode)) {
			planPhaseActive = false;
			if (process.env.PI_SUBAGENT !== "1") process.env.PI_ROOT_PHASE = "execute";
			toolsBeforePlanMode = undefined;
			updateStatus(ctx);
			return;
		}

		void ensureParserLoaded(); // warm the parser; don't block startup
		if (pi.getFlag("plan") === true) planPhaseActive = true;

		const planModeEntry = ctx.sessionManager
			.getBranch()
			.filter((e: { type: string; customType?: string }) => e.type === "custom" && e.customType === "plan-mode")
			.pop() as { data?: PlanModeState } | undefined;
		if (planModeEntry?.data) {
			planPhaseActive = planModeEntry.data.enabled ?? planPhaseActive;
			toolsBeforePlanMode = planModeEntry.data.toolsBeforePlanMode ?? toolsBeforePlanMode;
		}

		process.env.PI_ROOT_PHASE = planPhaseActive ? "plan" : "execute";
		if (planPhaseActive) enablePlanModeTools();
		updateStatus(ctx);
	});
}
