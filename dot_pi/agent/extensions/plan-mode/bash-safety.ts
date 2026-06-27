/**
 * Read-only bash command analysis for plan mode.
 *
 * Intent
 * ------
 * In plan mode the `edit`/`write` tools are removed, but `bash` stays available
 * for inspection. This module decides whether a bash command is read-only and
 * therefore safe to run while plan mode is active. A blocked command returns a
 * human-readable reason string; a safe command returns `undefined`.
 *
 * Design — shell-quote tokenizer first, regex fallback
 * ----------------------------------------------------
 * Primary path parses the command with `shell-quote` (vendored as a single
 * self-contained file via a chezmoi external + TTL; see ../.chezmoiexternal.toml
 * and DESIGN.md). Tokenizing first means quoting/escaping and redirect operators
 * are handled correctly — e.g. `echo ">"` is NOT a redirect, and `echo "rm -rf"`
 * is NOT an `rm` invocation — which a pure-regex scan gets wrong.
 *
 * The token analysis applies the same mutation denylist that `../worktree-guard.ts`
 * enforces (one mental model for "what mutates" across the repo), but stricter,
 * because plan mode is read-only exploration rather than race-avoidance:
 *   - all `git merge` blocked (no `--ff-only` carve-out); `git push`/`pull` blocked
 *   - extra file-mutating builtins blocked (mkdir/touch/chmod/chown/ln/dd/...)
 *   - `git branch` (list-dominant) and `git stash list|show` stay allowed
 *
 * Fallback: if the parser file is absent (e.g. offline first `chezmoi apply`) or
 * a command fails to parse, we fall back to the same regex denylist worktree-guard
 * uses. This is the ONLY place regex is used, and only as a degraded backstop —
 * the design does not rely solely on regex.
 *
 * Why not just-bash (full AST)? See DESIGN.md: 19 MB + 15 deps incl. WASM, and
 * not self-contained, so there is no script-free way to ship it.
 *
 * Best-effort guardrail, not a sandbox. The hard guarantee is the removed
 * `edit`/`write` tools; this is defense in depth.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

// --- Shared mutation denylist (used by both the token and regex paths) ---

// Mutating git subcommands. Superset of worktree-guard's list: adds push/pull
// because plan mode forbids remote/working-tree mutation entirely.
const MUTATING_GIT_SUBCMDS = new Set([
	"add", "am", "apply", "checkout", "cherry-pick", "clean", "commit",
	"fast-import", "merge", "mv", "rebase", "reset", "restore", "revert",
	"rm", "update-index", "update-ref", "push", "pull",
]);

const GIT_FLAGS_WITH_VALUE = new Set(["-C", "-c", "--work-tree", "--git-dir", "--namespace"]);

const READONLY_TODO_SUBCMDS = new Set([
	"help", "shorthelp", "list", "listall", "listaddons", "listcon",
	"listfile", "listpri", "listproj", "lf", "ls", "lsa", "lsc", "lsp", "lsprj",
]);

// File/system mutating builtins blocked in read-only plan mode.
const MUTATING_FILE_CMDS = new Set([
	"rm", "rmdir", "mv", "cp", "mkdir", "touch", "chmod", "chown", "chgrp",
	"ln", "dd", "truncate", "shred", "install",
]);

function gitSubcmd(tokens: string[]): string | undefined {
	let i = 0;
	while (i < tokens.length) {
		const tok = tokens[i];
		if (GIT_FLAGS_WITH_VALUE.has(tok)) { i += 2; continue; }
		if (tok.startsWith("-")) { i += 1; continue; }
		return tok;
	}
	return undefined;
}

/** Apply the denylist to one parsed command (command name + its args). */
function checkCommandWords(words: string[]): string | undefined {
	// Skip leading env-assignments (FOO=bar cmd ...).
	let start = 0;
	while (start < words.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(words[start])) start += 1;
	const cmd = words[start];
	if (!cmd) return undefined;
	const args = words.slice(start + 1);

	if (MUTATING_FILE_CMDS.has(cmd)) return `${cmd} (file mutation)`;
	if (cmd === "tee") return "tee";
	if (cmd === "sed" && args.some((a) => /^-[a-zA-Z]*i/.test(a))) return "sed -i (in-place edit)";

	if (cmd === "git") {
		const subcmd = gitSubcmd(args);
		if (!subcmd) return undefined;
		if (subcmd === "branch") return undefined; // list-dominant; parity with worktree-guard
		if (subcmd === "stash") {
			const next = (args[args.indexOf("stash") + 1] ?? "").toLowerCase();
			if (next === "list" || next === "show") return undefined;
			return "git stash (mutating)";
		}
		if (MUTATING_GIT_SUBCMDS.has(subcmd)) return `git ${subcmd} (mutating)`;
	}

	if (cmd === "todo" || cmd === "todo.sh") {
		const sub = args[0];
		if (sub && !READONLY_TODO_SUBCMDS.has(sub)) return `todo.sh ${sub} (mutating)`;
	}

	return undefined;
}

// --- Primary path: shell-quote tokenizer ---

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
		"plan-mode: shell-quote parser unavailable; using best-effort regex bash checks (run `chezmoi apply` to fetch it)",
		"warning",
	);
}

const CONTROL_OPS = new Set(["|", "||", "&&", ";", ";;", "&", "|&", "(", ")"]);
const WRITE_REDIRECT_OPS = new Set([">", ">>"]);

function isOp(t: ShellToken): t is ShellOp {
	return typeof t === "object" && t !== null && "op" in t;
}

/** Token-based read-only check. Returns a reason if blocked, else undefined. */
function checkTokens(tokens: ShellToken[]): string | undefined {
	// Pass 1: write redirects. Allow fd redirects like `2>` (preceding bare int),
	// mirroring worktree-guard's `(?<![2&])` carve-out; `>&`/`<&` are not in the
	// write set so fd-dups pass.
	for (let i = 0; i < tokens.length; i += 1) {
		const t = tokens[i];
		if (isOp(t) && WRITE_REDIRECT_OPS.has(t.op)) {
			const prev = tokens[i - 1];
			if (typeof prev === "string" && /^\d+$/.test(prev)) continue; // fd redirect (e.g. 2>)
			return "output redirect (>, >>)";
		}
	}

	// Pass 2: split into commands at control operators, dropping redirect targets,
	// then denylist-check each command's leading word.
	let cur: string[] = [];
	let skipRedirectTarget = false;
	const commit = (): string | undefined => {
		if (cur.length) {
			const reason = checkCommandWords(cur);
			cur = [];
			if (reason) return reason;
		}
		return undefined;
	};
	for (const t of tokens) {
		if (isOp(t)) {
			if (CONTROL_OPS.has(t.op)) {
				const reason = commit();
				if (reason) return reason;
				skipRedirectTarget = false;
			} else {
				// redirect / other op: the next string token is its target, not an arg
				skipRedirectTarget = true;
			}
			continue;
		}
		if (typeof t !== "string") continue; // comment / glob
		if (skipRedirectTarget) { skipRedirectTarget = false; continue; }
		cur.push(t);
	}
	return commit();
}

// --- Fallback path: regex (worktree-guard-style), used only without a parser ---

function checkSegmentRegex(segment: string): string | undefined {
	const seg = segment.trim();
	if (!seg) return undefined;
	if (/(?<![2&])>{1,2}(?!&)/.test(seg)) return "output redirect (>, >>)";
	if (/(?:^|\|)\s*tee(?:\s|$)/.test(seg)) return "tee";
	if (/^\s*sed\s/.test(seg) && /\s-[a-zA-Z]*i/.test(seg)) return "sed -i (in-place edit)";
	const fileOp = seg.match(/^\s*([a-z]+)\b/);
	if (fileOp && MUTATING_FILE_CMDS.has(fileOp[1])) return `${fileOp[1]} (file mutation)`;
	if (/^\s*git(?:\s|$)/.test(seg)) {
		const subcmd = gitSubcmd(seg.trim().split(/\s+/).slice(1));
		if (!subcmd) return undefined;
		if (subcmd === "branch") return undefined;
		if (subcmd === "stash") {
			if (/git\s+stash\s+(list|show)(?:\s|$)/.test(seg)) return undefined;
			return "git stash (mutating)";
		}
		if (MUTATING_GIT_SUBCMDS.has(subcmd)) return `git ${subcmd} (mutating)`;
	}
	const todoMatch = seg.match(/^\s*(?:todo\.sh|todo)\s+(\S+)/);
	if (todoMatch && !READONLY_TODO_SUBCMDS.has(todoMatch[1])) return `todo.sh ${todoMatch[1]} (mutating)`;
	return undefined;
}

function checkRegex(command: string): string | undefined {
	const lines = command.replace(/&&/g, "\n").replace(/\|\|/g, "\n").replace(/;/g, "\n");
	for (const line of lines.split("\n")) {
		if (!line.trim()) continue;
		for (const part of line.split("|")) {
			const reason = checkSegmentRegex(part);
			if (reason) return reason;
		}
	}
	return undefined;
}

/**
 * Returns a reason string if the command is NOT read-only (should be blocked),
 * or undefined if it is safe to run in plan mode. Uses the shell-quote tokenizer
 * when available (call `ensureParserLoaded()` first); otherwise the regex
 * fallback. On parse failure for a specific command, falls back to regex.
 */
export function checkPlanModeBash(command: string): string | undefined {
	if (parseShell) {
		try {
			return checkTokens(parseShell(command, {}));
		} catch {
			// fall through to regex for this command
		}
	}
	return checkRegex(command);
}
