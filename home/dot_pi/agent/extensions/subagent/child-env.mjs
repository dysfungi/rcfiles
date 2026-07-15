/** Build an explicit child policy; never inherit parent worktree-routing state. */
export function childEnvironment(environment = process.env, policy = {}) {
	// Preserve PI_MODE so nested launchers inherit the root policy; child plan-mode
	// extensions are inert under PI_SUBAGENT and only propagate this signal.
	const child = { ...environment, PI_SUBAGENT: "1" };
	for (const key of ["PI_WORKTREE_ROOT", "PI_WORKTREE_BRANCH", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION", "PI_SUBAGENT_EXECUTION"]) delete child[key];
	if (policy.execution) child.PI_SUBAGENT_EXECUTION = policy.execution;
	if (policy.execution === "worktree-write" && policy.approval) {
		child.PI_WORKTREE_ROOT = policy.approval.worktreeRoot;
		child.PI_WORKTREE_REPO_ROOT = policy.approval.repoRoot;
		child.PI_WORKTREE_GENERATION = String(policy.approval.generation);
	}
	return child;
}
