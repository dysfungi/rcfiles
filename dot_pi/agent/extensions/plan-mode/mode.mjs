/** Plan mode belongs to interactive root sessions, never delegated workers. */
export function isPlanModeEnabled(mode, environment = process.env) {
	return (mode === "tui" || mode === "rpc") && environment.PI_SUBAGENT !== "1";
}
