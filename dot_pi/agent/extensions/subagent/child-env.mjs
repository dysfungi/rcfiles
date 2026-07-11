/** Mark a child pi process as delegated without mutating the parent environment. */
export function childEnvironment(environment = process.env) {
	return { ...environment, PI_SUBAGENT: "1" };
}
