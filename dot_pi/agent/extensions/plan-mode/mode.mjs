/** Plan mode belongs to interactive root sessions, never delegated workers. */
export function isInteractiveRootMode(mode) {
	return mode === "tui" || mode === "rpc";
}
