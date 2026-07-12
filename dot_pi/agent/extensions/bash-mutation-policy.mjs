/**
 * Best-effort shell mutation classifier shared by worktree and plan-mode guards.
 *
 * This cooperative workflow policy recognizes only the command families and shell
 * syntax below; it is not a complete shell parser or process sandbox. It
 * intentionally classifies whole command families such as `git branch`,
 * `git config`, and `git stash` as mutating rather than inferring intent from
 * arguments.
 */

export const MUTATING_GIT_SUBCMDS = new Set([
	"add",
	"am",
	"apply",
	"bisect",
	"branch",
	"checkout",
	"cherry-pick",
	"clean",
	"commit",
	"config",
	"fast-import",
	"fetch",
	"gc",
	"init",
	"merge",
	"mv",
	"notes",
	"pull",
	"push",
	"rebase",
	"reset",
	"restore",
	"revert",
	"rm",
	"sparse-checkout",
	"stash",
	"submodule",
	"switch",
	"tag",
	"update-index",
	"update-ref",
	"worktree",
]);

const GIT_FLAGS_WITH_VALUE = new Set(["-C", "-c", "--work-tree", "--git-dir", "--namespace", "--config-env"]);
const FILE_MUTATION_COMMANDS = new Set([
	"chmod",
	"chgrp",
	"chown",
	"cp",
	"dd",
	"install",
	"ln",
	"mkdir",
	"mkfifo",
	"mknod",
	"mv",
	"rm",
	"rmdir",
	"shred",
	"tee",
	"touch",
	"truncate",
]);
const SHELL_EVALUATORS = new Set([".", "bash", "command", "env", "eval", "sh", "source", "sudo", "xargs", "zsh"]);
const ENV_OPTIONS_WITH_VALUE = new Set(["-C", "-u", "--chdir", "--unset"]);
const SUDO_OPTIONS_WITH_VALUE = new Set([
	"-C",
	"-g",
	"-h",
	"-p",
	"-r",
	"-t",
	"-u",
	"--chdir",
	"--close-from",
	"--group",
	"--host",
	"--prompt",
	"--role",
	"--type",
	"--user",
]);
const READONLY_TODO_SUBCMDS = new Set([
	"help",
	"shorthelp",
	"list",
	"listall",
	"listaddons",
	"listcon",
	"listfile",
	"listpri",
	"listproj",
	"lf",
	"ls",
	"lsa",
	"lsc",
	"lsp",
	"lsprj",
]);

function skipOptions(words, index, optionsWithValue) {
	while (index < words.length) {
		const word = words[index];
		if (word === "--") return index + 1;
		if (!word.startsWith("-")) return index;
		if (optionsWithValue.has(word)) {
			index += 2;
			continue;
		}
		index += 1;
	}
	return index;
}

function skipEnvArguments(words, index) {
	index = skipOptions(words, index, ENV_OPTIONS_WITH_VALUE);
	while (index < words.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(words[index])) index += 1;
	return index;
}

function firstCommand(words) {
	let index = 0;
	while (index < words.length) {
		while (index < words.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(words[index])) index += 1;
		const wrapper = words[index];
		if (wrapper === "command") {
			index = skipOptions(words, index + 1, new Set());
			continue;
		}
		if (wrapper === "env") {
			index = skipEnvArguments(words, index + 1);
			continue;
		}
		if (wrapper === "sudo") {
			index = skipOptions(words, index + 1, SUDO_OPTIONS_WITH_VALUE);
			continue;
		}
		return { command: wrapper, args: words.slice(index + 1) };
	}
	return { args: [] };
}

function gitSubcmd(tokens) {
	for (let index = 0; index < tokens.length; index += 1) {
		if (GIT_FLAGS_WITH_VALUE.has(tokens[index])) {
			index += 1;
			continue;
		}
		if (!tokens[index].startsWith("-")) return tokens[index];
	}
}

/** Return the first mutation reason for one shell command's words. */
export function mutationInWords(words) {
	if (words.length === 0) return;
	const { command, args } = firstCommand(words);
	if (!command) return;
	if (SHELL_EVALUATORS.has(command) && command !== "command" && command !== "env" && command !== "sudo") {
		return `shell evaluator ${command}`;
	}
	if (FILE_MUTATION_COMMANDS.has(command)) return `file mutation command ${command}`;
	if (command === "sed" && args.some((arg) => arg === "-i" || /^-.*i/.test(arg))) return "sed in-place edit";
	if (command === "find" && args.some((arg) => arg === "-delete" || arg === "-exec" || arg === "-execdir")) {
		return "find mutation action";
	}
	if (command === "git") {
		const subcmd = gitSubcmd(args);
		if (subcmd && MUTATING_GIT_SUBCMDS.has(subcmd)) return `git ${subcmd} (mutating)`;
	}
	const todo = command === "todo" || command === "todo.sh" ? args[0] : undefined;
	if (todo && !READONLY_TODO_SUBCMDS.has(todo)) return `todo.sh ${todo} (mutating)`;
}

/** Best-effort quote-aware tokenizer; it does not implement full shell grammar. */
export function tokenizeShell(command) {
	const tokens = [];
	let word = "";
	let quote = "";
	let escaped = false;
	const flush = () => {
		if (word) tokens.push({ type: "word", value: word });
		word = "";
	};
	for (let index = 0; index < command.length; index += 1) {
		const char = command[index];
		if (escaped) {
			word += char;
			escaped = false;
			continue;
		}
		if (char === "\\" && quote !== "'") {
			escaped = true;
			continue;
		}
		const isCommandSubstitution = char === "`" || (char === "$" && command[index + 1] === "(");
		if (quote) {
			if (char === quote) quote = "";
			else if (quote !== "'" && isCommandSubstitution) return { tokens, unsafe: true };
			else word += char;
			continue;
		}
		if (isCommandSubstitution) return { tokens, unsafe: true };
		if (char === "'" || char === '"') {
			quote = char;
			continue;
		}
		if (char === "\n") {
			flush();
			tokens.push({ type: "operator", value: ";" });
			continue;
		}
		if (/\s/.test(char)) {
			flush();
			continue;
		}
		if (";&|<>".includes(char)) {
			flush();
			const next = command[index + 1];
			if (
				(char === "&" && (next === "&" || next === ">")) ||
				(char === "|" && next === "|") ||
				(char === ">" && next === ">") ||
				(char === "<" && next === "<")
			) {
				tokens.push({ type: "operator", value: char + next });
				index += 1;
			} else tokens.push({ type: "operator", value: char });
			continue;
		}
		word += char;
	}
	flush();
	return { tokens, unsafe: Boolean(quote || escaped) };
}

/**
 * Return a reason for a mutation this classifier recognizes.
 *
 * An undefined result is not proof that an arbitrary shell command is read-only.
 */
export function checkBashCommand(command) {
	const parsed = tokenizeShell(command);
	if (parsed.unsafe) return "shell substitution or malformed quoting";
	if (parsed.tokens.some((token) => token.type === "operator" && [">", ">>", "&>"].includes(token.value))) {
		return "shell redirection";
	}
	let words = [];
	for (const token of parsed.tokens) {
		if (token.type === "word") {
			words.push(token.value);
			continue;
		}
		const reason = mutationInWords(words);
		if (reason) return reason;
		words = [];
	}
	return mutationInWords(words);
}
