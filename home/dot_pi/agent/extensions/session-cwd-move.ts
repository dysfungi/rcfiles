import { SessionManager, type ExtensionAPI, type ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";

type SessionManagerWithStorageMode = ExtensionCommandContext["sessionManager"] &
	Pick<SessionManager, "usesDefaultSessionDir">;

function hasUsesDefaultSessionDir(
	sessionManager: ExtensionCommandContext["sessionManager"],
): sessionManager is SessionManagerWithStorageMode {
	return "usesDefaultSessionDir" in sessionManager && typeof sessionManager.usesDefaultSessionDir === "function";
}

function requireIdle(ctx: ExtensionCommandContext): boolean {
	if (ctx.isIdle()) return true;
	ctx.ui.notify("/cwd requires an idle agent. Wait for the current run to finish.", "warning");
	return false;
}

function parseTarget(args: string): string | undefined {
	const target = args.trim();
	if (!target) return process.cwd();
	if (target === "~") return homedir();
	if (target.startsWith("~/")) return join(homedir(), target.slice(2));
	if (isAbsolute(target)) return target;
	return undefined;
}

function isCurrentCwd(target: string, cwd: string): boolean {
	try {
		const realTarget = realpathSync(target);
		try {
			return realTarget === realpathSync(cwd);
		} catch {
			return target === cwd;
		}
	} catch {
		return target === cwd;
	}
}

function getSessionDir(ctx: ExtensionCommandContext): string | undefined {
	// Pi 0.80.6 exposes this runtime method but omits it from ReadonlySessionManager.
	const { sessionManager } = ctx;
	if (!hasUsesDefaultSessionDir(sessionManager)) {
		throw new Error("Pi SessionManager is missing required usesDefaultSessionDir() for /cwd.");
	}
	return sessionManager.usesDefaultSessionDir() ? undefined : sessionManager.getSessionDir();
}

export default function sessionCwdMove(pi: ExtensionAPI): void {
	pi.registerCommand("cwd", {
		description:
			"Move this session to a new directory by forking history into a new session there. Usage: /cwd [path] (no path = this terminal's launch directory)",
		handler: async (args, ctx) => {
			if (!requireIdle(ctx)) return;

			const target = parseTarget(args);
			if (!target) {
				ctx.ui.notify(
					"Relative paths are ambiguous because either resolution anchor may be stale. Use an absolute path, ~/..., or omit the path to use this terminal's launch directory.",
					"warning",
				);
				return;
			}

			let targetStats: ReturnType<typeof statSync>;
			try {
				targetStats = statSync(target);
			} catch (error) {
				const detail = error instanceof Error ? error.message : String(error);
				ctx.ui.notify(`Cannot use ${target}: ${detail}`, "error");
				return;
			}
			if (!targetStats.isDirectory()) {
				ctx.ui.notify(`Target is not a directory: ${target}.`, "error");
				return;
			}

			const currentSessionFile = ctx.sessionManager.getSessionFile();
			if (!currentSessionFile) {
				ctx.ui.notify("/cwd cannot move an ephemeral session because it has no session file to fork.", "warning");
				return;
			}

			if (isCurrentCwd(target, ctx.cwd)) {
				ctx.ui.notify(`Already at ${target}.`);
				return;
			}

			let newManager: SessionManager;
			try {
				newManager = SessionManager.forkFrom(currentSessionFile, target, getSessionDir(ctx));
			} catch (error) {
				const detail = error instanceof Error ? error.message : String(error);
				ctx.ui.notify(`Could not create a session for ${target}: ${detail}`, "error");
				return;
			}

			const newSessionFile = newManager.getSessionFile();
			if (!newSessionFile) {
				ctx.ui.notify(`Internal error: the session created for ${target} has no session file.`, "error");
				return;
			}

			const result = await ctx.switchSession(newSessionFile, {
				withSession: async (newCtx) => {
					newCtx.ui.notify(`Moved this session to ${target}.`);
				},
			});
			if (result.cancelled) {
				ctx.ui.notify(
					`Created a new session at ${newSessionFile} but did not activate it. Resume it manually with pi --session "${newSessionFile}".`,
					"warning",
				);
			}
		},
	});
}
