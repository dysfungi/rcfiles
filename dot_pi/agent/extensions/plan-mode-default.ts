/**
 * Default plan mode ON at session start.
 *
 * The upstream plan-mode extension (pulled via .chezmoiexternals from pi-mono)
 * defaults to OFF and requires `--plan` to activate. This companion extension
 * activates plan mode on every fresh session, mirroring Claude Code's
 * `defaultMode: "plan"` — safe by default, `/plan` to toggle off.
 *
 * Why a separate file instead of patching upstream:
 *   - .chezmoiexternals pulls are immutable (no post-download patching)
 *   - Keeps our one-line customization isolated from upstream churn
 *   - pi loads extensions alphabetically; plan-mode-default.ts sorts after
 *     plan-mode/ so the plan-mode extension is already registered
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    // Skip if user explicitly passed --no-plan, or if this is a resume
    // (the plan-mode extension persists its own state across resumes).
    if (pi.getFlag("plan") === false) return;
    if (_event.reason === "resume" || _event.reason === "fork") return;

    // Activate plan mode by simulating the /plan command.
    // The plan-mode extension's session_start handler runs first (alphabetical
    // ordering: plan-mode/ < plan-mode-default.ts) and checks its persisted
    // state + the --plan flag. On a fresh session with no flag, it leaves plan
    // mode off. We then toggle it on here.
    //
    // We use sendUserMessage with /plan rather than directly calling
    // setActiveTools because the plan-mode extension owns the state machine
    // (planModeEnabled, tool lists, status widgets). Going through /plan
    // ensures consistent state.
    pi.sendUserMessage("/plan", { deliverAs: "followUp" });
  });
}
