/** The plan phase belongs to interactive root sessions, never delegated workers. */
export function isPlanPhaseActive(mode, environment = process.env) {
	return (mode === "tui" || mode === "rpc") && environment.PI_SUBAGENT !== "1";
}
