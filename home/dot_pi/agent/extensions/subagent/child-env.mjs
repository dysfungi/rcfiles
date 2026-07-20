/** Build an explicit child policy; never inherit parent worktree-routing state. */
const ROOT_IDENTITY_ENV = "PI_ROOT_IDENTITY";
const ROOT_IDENTITY_FIELDS = ["model", "provider", "sessionId"];

function validateRootIdentity(identity, source) {
	if (typeof identity !== "object" || identity === null || Array.isArray(identity)) {
		throw new Error(`${ROOT_IDENTITY_ENV} ${source} must be a JSON object`);
	}
	for (const field of ROOT_IDENTITY_FIELDS) {
		if (!Object.hasOwn(identity, field)) {
			throw new Error(`${ROOT_IDENTITY_ENV} ${source} is missing field '${field}'`);
		}
		if (typeof identity[field] !== "string" || !identity[field].trim()) {
			throw new Error(`${ROOT_IDENTITY_ENV} ${source} field '${field}' must be a non-empty string`);
		}
	}
}

function validateRootIdentityEnvelope(envelope) {
	if (typeof envelope !== "string") {
		throw new Error(`${ROOT_IDENTITY_ENV} envelope must be a string`);
	}
	let identity;
	try {
		identity = JSON.parse(envelope);
	} catch (error) {
		const detail = error instanceof Error ? error.message : String(error);
		throw new Error(`${ROOT_IDENTITY_ENV} envelope contains invalid JSON: ${detail}`);
	}
	validateRootIdentity(identity, "envelope");
}

export function rootIdentityEnvelope(environment = process.env, ctx) {
	const inherited = environment[ROOT_IDENTITY_ENV];
	if (inherited !== undefined) {
		validateRootIdentityEnvelope(inherited);
		return inherited;
	}

	const identity = {
		model: ctx.model?.id,
		provider: ctx.model?.provider,
		sessionId: ctx.sessionManager?.getSessionId?.(),
	};
	validateRootIdentity(identity, "context");
	const envelope = JSON.stringify(identity);
	validateRootIdentityEnvelope(envelope);
	return envelope;
}

export function childEnvironment(environment = process.env, policy = {}) {
	// Preserve PI_ROOT_PHASE so nested launchers inherit the root-phase policy; child
	// plan-mode extensions are inert under PI_SUBAGENT and only propagate this signal.
	const child = { ...environment, PI_SUBAGENT: "1" };
	if (policy.rootIdentity !== undefined) {
		validateRootIdentityEnvelope(policy.rootIdentity);
		child[ROOT_IDENTITY_ENV] = policy.rootIdentity;
	}
	for (const key of ["PI_WORKTREE_ROOT", "PI_WORKTREE_BRANCH", "PI_WORKTREE_REPO_ROOT", "PI_WORKTREE_GENERATION", "PI_SUBAGENT_EXECUTION"]) delete child[key];
	if (policy.execution) child.PI_SUBAGENT_EXECUTION = policy.execution;
	if (policy.execution === "worktree-write" && policy.approval) {
		child.PI_WORKTREE_ROOT = policy.approval.worktreeRoot;
		child.PI_WORKTREE_REPO_ROOT = policy.approval.repoRoot;
		child.PI_WORKTREE_GENERATION = String(policy.approval.generation);
	}
	return child;
}
