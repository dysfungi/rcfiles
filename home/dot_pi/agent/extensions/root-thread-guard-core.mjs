import { homedir } from "node:os";
import { isAbsolute, relative, resolve } from "node:path";

const ROOT_MODES = new Set(["tui", "rpc"]);
const EXACTLY_ALLOWED_TOOLS = new Set(["subagent", "write", "edit", "questionnaire", "plan_write", "scratchpad", "worktree_start", "worktree_status", "worktree_stop"]);
const PREFIX_ALLOWED_TOOLS = ["memory_"];

function expandHome(path, home) {
	return path === "~" || path.startsWith("~/") ? `${home}${path.slice(1)}` : path;
}

function isWithin(path, root) {
	const pathRelative = relative(root, path);
	return pathRelative === "" || (!pathRelative.startsWith("..") && !isAbsolute(pathRelative));
}

function resolveInputPath(path, cwd, home) {
	return resolve(cwd, expandHome(path, home));
}

function scratchReadAllowed(path, { cwd, home, agentDir, memoryDir }) {
	const resolvedPath = resolveInputPath(path, cwd, home);
	const plansDir = resolve(agentDir, "plans");
	const agentSkillsDir = resolve(agentDir, "skills");
	const globalSkillsDir = resolve(home, ".agents", "skills");
	const allowedTodoFiles = [resolve(cwd, "todo.txt"), resolve(cwd, "done.txt")];
	return (
		isWithin(resolvedPath, plansDir) ||
		isWithin(resolvedPath, memoryDir) ||
		isWithin(resolvedPath, agentSkillsDir) ||
		isWithin(resolvedPath, globalSkillsDir) ||
		allowedTodoFiles.includes(resolvedPath)
	);
}

/**
 * Decide whether a pi tool call is allowed under root-thread context discipline.
 * JSON workers and print-mode one-shots are exempt; interactive root sessions are
 * block-by-default, with a narrowly scoped scratch-read allowance.
 */
export function decideToolCall({ mode, toolName, input = {}, cwd, home = homedir(), agentDir, memoryDir }) {
	if (!ROOT_MODES.has(mode)) return { allowed: true };

	const resolvedAgentDir = resolve(agentDir ?? process.env.PI_CODING_AGENT_DIR ?? `${home}/.pi/agent`);
	const resolvedMemoryDir = resolve(memoryDir ?? process.env.PI_MEMORY_DIR ?? `${resolvedAgentDir}/memory`);

	if (EXACTLY_ALLOWED_TOOLS.has(toolName) || PREFIX_ALLOWED_TOOLS.some((prefix) => toolName.startsWith(prefix))) {
		return { allowed: true };
	}

	if (toolName === "read" && typeof input.path === "string") {
		if (scratchReadAllowed(input.path, { cwd, home, agentDir: resolvedAgentDir, memoryDir: resolvedMemoryDir })) {
			return { allowed: true };
		}
	}

	return {
		allowed: false,
		reason: `Blocked by root-thread context discipline: ${toolName} is not permitted in a ${mode} root session. Delegate read-heavy, exploratory, shell, or MCP work with subagent; it runs in an isolated JSON context and must return distilled file:line findings.`,
	};
}
