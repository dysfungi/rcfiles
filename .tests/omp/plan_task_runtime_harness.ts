import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createPlanTaskExtension, resolveOmpExecutable } from "../../home/dot_omp/agent/extensions/plan-task.ts";

type Frame = Record<string, unknown>;
type ProcessOptions = {
	cmd: string[];
	cwd?: string;
	detached?: boolean;
	stderr?: "ignore" | "pipe";
	stdin?: "ignore" | "pipe";
	stdout?: "ignore" | "pipe";
	windowsHide?: boolean;
};
type Result = { content: { text: string; type: "text" }[]; details?: Record<string, unknown>; isError?: boolean };
type RegisteredTool = {
	approval: string;
	execute: (
		toolCallId: string,
		params: { task: string },
		signal: AbortSignal | undefined,
		onUpdate: ((result: Result) => void) | undefined,
		ctx: { cwd: string },
	) => Promise<Result>;
	name: string;
	parameters: unknown;
};

type Scenario =
	| "abort"
	| "assistant-error"
	| "final-exit"
	| "malformed"
	| "missing-assistant"
	| "premature-exit"
	| "prompt-failure"
	| "prompt-result"
	| "startup-timeout"
	| "stdout-eof"
	| "success"
	| "trailing-malformed"
	| "unterminated"
	| "will-continue";

const encoder = new TextEncoder();

function createFixture(scenario: Scenario) {
	const calls: ProcessOptions[] = [];
	const updates: Result[] = [];
	let tool: RegisteredTool | undefined;
	let minimumLength: number | undefined;
	let stdoutController: ReadableStreamDefaultController<Uint8Array>;
	let stderrController: ReadableStreamDefaultController<Uint8Array>;
	const exit = Promise.withResolvers<number>();
	let stdinClosed = false;
	let workerExited = false;
	let abortReceived = false;

	const finish = (status = 0) => {
		if (workerExited) return;
		workerExited = true;
		try {
			stdoutController.close();
		} catch {
			// The malformed-JSON scenario has already cancelled the reader.
		}
		stderrController.close();
		exit.resolve(status);
	};
	const emit = (frame: Frame) => stdoutController.enqueue(encoder.encode(`${JSON.stringify(frame)}\n`));
	const emitRaw = (line: string) => stdoutController.enqueue(encoder.encode(line));
	const stderr = (text: string) => stderrController.enqueue(encoder.encode(text));
	const child = {
		exited: exit.promise,
		pid: 42_424,
		stderr: new ReadableStream<Uint8Array>({ start(controller) { stderrController = controller; } }),
		stdin: {
			async end() {
				stdinClosed = true;
				if (scenario === "success" || scenario === "trailing-malformed" || scenario === "will-continue") finish(0);
				else if (scenario !== "premature-exit" && !(scenario === "abort" && process.platform === "win32")) finish(143);
			},
			async write(raw: string) {
				const frame = JSON.parse(raw) as Frame;
				if (frame.type === "abort") {
					abortReceived = true;
					return;
				}
				if (frame.type !== "prompt") return;
				switch (scenario) {
					case "success":
						emit({ type: "tool_execution_start", toolName: "bash" });
						emit({ type: "tool_execution_update", toolName: "bash", text: "working" });
						emit({ id: frame.id, type: "response", command: "prompt", success: true, data: { agentInvoked: true } });
						emit({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "worker result" }] } });
						emit({ type: "agent_end" });
						return;
					case "final-exit":
						emit({ id: frame.id, type: "response", command: "prompt", success: true, data: { agentInvoked: true } });
						emit({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "result before process exit" }] } });
						emit({ type: "agent_end" });
						finish(0);
						return;
					case "will-continue":
						emit({ id: frame.id, type: "response", command: "prompt", success: true, data: { agentInvoked: true } });
						emit({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "transient result" }] } });
						emit({ type: "agent_end", willContinue: true });
						emit({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "final result" }] } });
						emit({ type: "agent_end" });
						return;
					case "trailing-malformed":
						emit({ id: frame.id, type: "response", command: "prompt", success: true, data: { agentInvoked: true } });
						emit({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "valid before invalid frame" }] } });
						emit({ type: "agent_end" });
						emitRaw("not-json\n");
						return;
					case "prompt-failure":
						stderr("worker diagnostics\n");
						emit({ id: frame.id, type: "response", command: "prompt", success: false, error: "model unavailable" });
						return;
					case "assistant-error":
						emit({ id: frame.id, type: "response", command: "prompt", success: true, data: { agentInvoked: true } });
						emit({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "partial result" }], errorMessage: "provider failed", stopReason: "error" } });
						emit({ type: "agent_end" });
						return;
					case "missing-assistant":
						emit({ type: "agent_end" });
						emit({ id: frame.id, type: "response", command: "prompt", success: true, data: { agentInvoked: true } });
						return;
					case "prompt-result":
						emit({ id: frame.id, type: "response", command: "prompt", success: true });
						emit({ id: frame.id, type: "prompt_result", agentInvoked: false });
						return;
					case "premature-exit":
						finish(7);
						return;
					case "malformed":
						emitRaw("not-json\n");
						return;
					case "stdout-eof":
						stdoutController.close();
						return;
					case "unterminated":
						emitRaw("x".repeat(1_048_577));
						return;
					case "abort":
					case "startup-timeout":
						return;
				}
			},
		},
		stdout: new ReadableStream<Uint8Array>({ start(controller) { stdoutController = controller; } }),
	};
	const spawn = (options: ProcessOptions) => {
		calls.push(options);
		if (options.cmd[0] === "taskkill") {
			finish(143);
			return { exited: Promise.resolve(0) };
		}
		if (scenario !== "startup-timeout") queueMicrotask(() => emit({ type: "ready" }));
		return child;
	};
	const extension = createPlanTaskExtension({
		executable: () => "/fixture/omp",
		forceKillGraceMs: 1,
		shutdownGraceMs: 1,
		spawn,
		startupTimeoutMs: 5,
	});
	extension({
		zod: {
			z: {
				object: (shape: { task: unknown }) => shape,
				string: () => ({
					min: (length: number) => {
						minimumLength = length;
						return { length };
					},
				}),
			},
		},
		registerTool(registered: RegisteredTool) {
			tool = registered;
		},
	} as never);
	assert.ok(tool, "extension must register plan_task");
	return {
		abortReceived: () => abortReceived,
		calls,
		minimumLength: () => minimumLength,
		run: (task: string, signal?: AbortSignal) => tool!.execute("call-1", { task }, signal, (update) => updates.push(update), { cwd: "/fixture/cwd" }),
		stdinClosed: () => stdinClosed,
		tool,
		updates,
	};
}

async function testSurfaceAndSuccess(): Promise<void> {
	const fixture = createFixture("success");
	assert.equal(fixture.tool.name, "plan_task");
	assert.equal(fixture.tool.approval, "exec");
	assert.equal(fixture.minimumLength(), 1);
	const result = await fixture.run('first line\n"quoted" second line');
	assert.equal(result.isError, undefined);
	assert.equal(result.content[0]?.text, "worker result");
	assert.equal(fixture.calls.length, 1);
	assert.deepEqual(fixture.calls[0], {
		cmd: [
			"/fixture/omp",
			"--mode",
			"rpc",
			"--no-session",
			"--model",
			"@task",
			"--thinking",
			"auto",
			"--approval-mode",
			"yolo",
			"--no-extensions",
			"--system-prompt",
			"Complete the user's assigned task autonomously with all available tools. Follow repository instructions, do not delegate, and return a concise result with concrete evidence.",
		],
		cwd: "/fixture/cwd",
		detached: process.platform !== "win32",
		stdin: "pipe",
		stderr: "pipe",
		stdout: "pipe",
		windowsHide: process.platform === "win32",
	});
	assert.equal(fixture.stdinClosed(), true);
	assert.equal(fixture.updates.length, 2);
	assert.match(fixture.updates[0]?.content[0]?.text ?? "", /tool_execution_start/);
	assert.match(fixture.updates[1]?.content[0]?.text ?? "", /tool_execution_update/);
}

async function testRejectsBlankTaskWithoutSpawning(): Promise<void> {
	const fixture = createFixture("success");
	const result = await fixture.run(" \n\t ");
	assert.equal(result.isError, true);
	assert.equal(fixture.calls.length, 0);
}

async function testFailureScenarios(): Promise<void> {
	for (const scenario of ["prompt-failure", "assistant-error", "missing-assistant", "prompt-result", "premature-exit", "malformed", "startup-timeout", "stdout-eof", "trailing-malformed", "unterminated"] as const) {
		const fixture = createFixture(scenario);
		const result = await fixture.run("run the worker");
		assert.equal(result.isError, true, scenario);
		assert.equal(fixture.abortReceived(), true, `${scenario} must request worker abort before reaping`);
		assert.equal(fixture.stdinClosed(), true, `${scenario} must close stdin before reaping`);
		if (scenario === "prompt-failure") assert.match(result.content[0]?.text ?? "", /worker diagnostics/);
		if (scenario === "assistant-error") assert.match(result.content[0]?.text ?? "", /provider failed/);
	}
}

async function testWaitsForFinalAgentEnd(): Promise<void> {
	const fixture = createFixture("will-continue");
	const result = await fixture.run("retry before returning");
	assert.equal(result.isError, undefined);
	assert.equal(result.content[0]?.text, "final result");
}
async function testAcceptsFinalTranscriptBeforeProcessExit(): Promise<void> {
	const fixture = createFixture("final-exit");
	const result = await fixture.run("exit after final frame");
	assert.equal(result.isError, undefined);
	assert.equal(result.content[0]?.text, "result before process exit");
}

async function testCancelsBeforeWorkerReady(): Promise<void> {
	const fixture = createFixture("startup-timeout");
	const controller = new AbortController();
	controller.abort();
	const result = await fixture.run("cancel before ready", controller.signal);
	assert.equal(result.isError, true);
	assert.equal(fixture.abortReceived(), true);
	assert.equal(fixture.stdinClosed(), true);
}

async function testCancellation(): Promise<void> {
	const fixture = createFixture("abort");
	const controller = new AbortController();
	const resultPromise = fixture.run("wait", controller.signal);
	await Bun.sleep(1);
	controller.abort();
	const result = await resultPromise;
	assert.equal(result.isError, true);
	assert.equal(fixture.abortReceived(), true);
	assert.equal(fixture.stdinClosed(), true);
}

async function testWindowsTaskkillPath(): Promise<void> {
	const descriptor = Object.getOwnPropertyDescriptor(process, "platform");
	assert.ok(descriptor?.configurable, "test runtime must permit platform simulation");
	Object.defineProperty(process, "platform", { configurable: true, value: "win32" });
	try {
		const fixture = createFixture("abort");
		const controller = new AbortController();
		const resultPromise = fixture.run("wait", controller.signal);
		await Bun.sleep(1);
		controller.abort();
		const result = await resultPromise;
		assert.equal(result.isError, true);
		assert.deepEqual(fixture.calls[1]?.cmd, ["taskkill", "/PID", "42424", "/T", "/F"]);
	} finally {
		Object.defineProperty(process, "platform", descriptor);
	}
}

async function testProcessGroupReaping(): Promise<void> {
	if (process.platform === "win32") return;
	const directory = mkdtempSync(join(tmpdir(), "plan-task-reap-"));
	const report = join(directory, "pids.json");
	const script = join(directory, "worker.ts");
	writeFileSync(
		script,
		[
			'import { writeFileSync } from "node:fs";',
			'const grandchild = Bun.spawn({ cmd: [Bun.which("bun")!, "-e", "setInterval(() => {}, 1_000)"], stdin: "ignore", stdout: "ignore", stderr: "ignore" });',
			'writeFileSync(Bun.env.PLAN_TASK_REPORT!, JSON.stringify({ child: process.pid, grandchild: grandchild.pid }));',
			'process.stdout.write("{\\\"type\\\":\\\"ready\\\"}\\n");',
			'process.stdin.on("data", data => { if (data.toString().includes("\\\"type\\\":\\\"abort\\\"")) process.exit(0); });',
			"setInterval(() => {}, 1_000);"
		].join("\n"),
	);
	try {
		let tool: RegisteredTool | undefined;
		createPlanTaskExtension({
			executable: () => "/fixture/omp",
			forceKillGraceMs: 10,
			shutdownGraceMs: 10,
			spawn: (options) =>
				Bun.spawn({
					...options,
					cmd: [Bun.which("bun")!, script],
					env: { ...process.env, PLAN_TASK_REPORT: report },
				}) as never,
		})({
			zod: { z: { object: () => ({}), string: () => ({ min: () => ({}) }) } },
			registerTool(registered: RegisteredTool) {
				tool = registered;
			},
		} as never);
		const controller = new AbortController();
		const resultPromise = tool!.execute("call-2", { task: "wait" }, controller.signal, undefined, { cwd: directory });
		for (let attempts = 0; attempts < 100 && !(await Bun.file(report).exists()); attempts += 1) await Bun.sleep(10);
		if (!(await Bun.file(report).exists())) {
			const result = await resultPromise;
			assert.fail(result.content[0]?.text ?? "worker exited before writing the process report");
		}
		assert.equal(await Bun.file(report).exists(), true, "worker must report both process IDs before cancellation");
		const processIds = await Bun.file(report).json() as { child: number; grandchild: number };
		controller.abort();
		const result = await resultPromise;
		assert.equal(result.isError, true);
		await Bun.sleep(20);
		for (const processId of [processIds.child, processIds.grandchild]) {
			let alive = true;
			try {
				process.kill(processId, 0);
			} catch {
				alive = false;
			}
			assert.equal(alive, false, `process ${processId} must be reaped`);
		}
	} finally {
		rmSync(directory, { force: true, recursive: true });
	}
}

function testExecutableResolution(): void {
	const descriptor = Object.getOwnPropertyDescriptor(process, "execPath");
	assert.ok(descriptor?.configurable, "test runtime must permit executable simulation");
	Object.defineProperty(process, "execPath", { configurable: true, value: "/fixture/not-omp" });
	try {
		assert.throws(() => resolveOmpExecutable(), /plan_task cannot resolve the current OMP executable: \/fixture\/not-omp/);
	} finally {
		Object.defineProperty(process, "execPath", descriptor);
	}
}

await testSurfaceAndSuccess();
await testRejectsBlankTaskWithoutSpawning();
await testFailureScenarios();
await testWaitsForFinalAgentEnd();
await testAcceptsFinalTranscriptBeforeProcessExit();
await testCancelsBeforeWorkerReady();
await testCancellation();
await testWindowsTaskkillPath();
await testProcessGroupReaping();
testExecutableResolution();
