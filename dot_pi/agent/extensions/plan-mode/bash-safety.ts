/**
 * Read-only bash classification for plan mode.
 *
 * Managed interactive roots are also protected by root-thread-guard, which
 * blocks all root Bash calls and sends exploration to read-only subagents.
 * This remains a defense-in-depth gate for plan mode itself: it shares the
 * worktree guard's best-effort mutation classifier, so either guard applies the
 * same supported classifications to commands it recognizes. It is not a
 * complete shell parser or sandbox.
 *
 * `shell-quote` is used when its chezmoi-delivered parser is present. The
 * built-in quote-aware tokenizer from `../bash-mutation-policy.mjs` is always
 * applied afterward, so a missing parser or parser edge case preserves those
 * supported classifications rather than falling back to a weaker regex
 * approximation.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { checkBashCommand, mutationInWords } from "../bash-mutation-policy.mjs";

type ShellOp = { op: string };
type ShellComment = { comment: string };
type ShellToken = string | ShellOp | ShellComment;
type ParseFn = (input: string, env?: unknown) => ShellToken[];

let parseShell: ParseFn | null = null;
let loadPromise: Promise<void> | null = null;
let loadDone = false;

/** Lazily load the vendored shell-quote parser. Safe to call repeatedly. */
export async function ensureParserLoaded(): Promise<void> {
	if (loadDone) return;
	if (!loadPromise) {
		loadPromise = import("./vendor/shell-quote-parse.cjs")
			.then((mod: { default?: unknown } | unknown) => {
				const fn = (mod as { default?: unknown })?.default ?? mod;
				parseShell = typeof fn === "function" ? (fn as ParseFn) : null;
			})
			.catch(() => {
				parseShell = null;
			})
			.finally(() => {
				loadDone = true;
			});
	}
	await loadPromise;
}

let warnedUnavailable = false;
export function maybeWarnParserUnavailable(ctx: ExtensionContext): void {
	if (warnedUnavailable || parseShell || !ctx.hasUI) return;
	warnedUnavailable = true;
	ctx.ui.notify(
		"plan-mode: shell-quote parser unavailable; using the built-in conservative bash guard (run `chezmoi apply` to fetch it)",
		"warning",
	);
}

const CONTROL_OPS = new Set(["|", "||", "&&", ";", ";;", "&", "|&", "(", ")"]);
const WRITE_REDIRECT_OPS = new Set([">", ">>", "&>"]);

function isOp(token: ShellToken): token is ShellOp {
	return typeof token === "object" && token !== null && "op" in token;
}

/** Apply the shared command classifier to shell-quote's parsed token stream. */
function checkTokens(tokens: ShellToken[]): string | undefined {
	for (const token of tokens) {
		if (isOp(token) && WRITE_REDIRECT_OPS.has(token.op)) return "shell redirection";
	}

	let words: string[] = [];
	let skipRedirectTarget = false;
	const commit = (): string | undefined => {
		const reason = mutationInWords(words);
		words = [];
		return reason;
	};
	for (const token of tokens) {
		if (isOp(token)) {
			if (CONTROL_OPS.has(token.op)) {
				const reason = commit();
				if (reason) return reason;
				skipRedirectTarget = false;
			} else {
				skipRedirectTarget = true;
			}
			continue;
		}
		if (typeof token !== "string") continue;
		if (skipRedirectTarget) {
			skipRedirectTarget = false;
			continue;
		}
		words.push(token);
	}
	return commit();
}

/**
 * Return a reason when a command is not read-only, otherwise undefined.
 *
 * The shared fallback always runs, preserving the worktree guard's supported
 * classifications even when shell-quote is absent or does not represent a shell
 * construct we reject. An undefined result is not a general shell-safety proof.
 */
export function checkPlanModeBash(command: string): string | undefined {
	if (parseShell) {
		try {
			const reason = checkTokens(parseShell(command, {}));
			if (reason) return reason;
		} catch {
			// The canonical fallback below handles parser failures.
		}
	}
	return checkBashCommand(command);
}
