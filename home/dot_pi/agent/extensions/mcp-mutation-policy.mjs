/**
 * Best-effort MCP mutation classifier for worktree-guard.
 *
 * Gateway management fields take precedence over `tool` in this policy. They
 * are intentionally allowed by product policy even though `connect` and
 * OAuth actions can have authentication or connection side effects.
 */

const MUTATING_MCP_VERBS = new Set([
	"create",
	"add",
	"edit",
	"update",
	"modify",
	"delete",
	"remove",
	"submit",
	"revert",
	"shelve",
	"unshelve",
	"transition",
	"set",
	"write",
	"post",
	"put",
	"patch",
	"merge",
	"resolve",
	"mute",
	"archive",
	"restore",
	"publish",
	"close",
	"assign",
	"attach",
	"upload",
	"schedule",
	"cancel",
	"trigger",
	"invite",
	"grant",
	"revoke",
	"install",
	"enable",
	"disable",
]);

function toolWords(tool) {
	return tool
		.split(/[_-]+/)
		.flatMap((part) => part.split(/(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/))
		.map((word) => word.toLowerCase())
		.filter(Boolean);
}

function checkMcpToolName(tool) {
	const verb = toolWords(tool).find((word) => MUTATING_MCP_VERBS.has(word));
	return verb ? `MCP tool ${tool} contains mutating verb ${verb}` : null;
}

/** Return a reason for a recognized mutating MCP gateway service-tool call. */
export function checkMcpCall(input) {
	if (["action", "connect", "describe", "search", "server"].some((key) => input?.[key])) return null;
	const tool = input?.tool;
	return typeof tool === "string" && tool ? checkMcpToolName(tool) : null;
}

/** Return a reason for a recognized mutating direct MCP tool call. */
export function checkMcpDirectToolCall(toolName) {
	return checkMcpToolName(toolName);
}
