/**
 * Shared child-process policy for managed Pi extensions.
 *
 * PI_SUBAGENT is a cooperative workflow marker set by our launcher, not an
 * authentication or sandbox boundary for independently launched processes.
 */
export function isDelegatedChild(environment = process.env) {
	return environment.PI_SUBAGENT === "1";
}

/** Only interactive parent sessions may own lifecycle/UI side effects. */
export function isInteractiveRoot(mode, environment = process.env) {
	return !isDelegatedChild(environment) && (mode === "tui" || mode === "rpc");
}
