import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { basename } from "node:path";

type JsonObject = Record<string, unknown>;
type Stream = AsyncIterable<Uint8Array | string>;
type Stdin = {
	end?: () => unknown;
	write: (chunk: string) => unknown;
};
type ChildProcess = {
	exited: Promise<number>;
	pid?: number;
	stderr?: Stream;
	stdin?: Stdin;
	stdout?: Stream;
};
type SpawnOptions = {
	cmd: string[];
	cwd?: string;
	detached?: boolean;
	stderr?: "ignore" | "pipe";
	stdin?: "ignore" | "pipe";
	stdout?: "ignore" | "pipe";
	windowsHide?: boolean;
};
type ProcessSpawner = (options: SpawnOptions) => ChildProcess;
type Update = (result: { content: { text: string; type: "text" }[]; details?: JsonObject }) => void;
type ToolContext = { cwd: string };
type ToolResult = {
	content: { text: string; type: "text" }[];
	details?: JsonObject;
	isError?: boolean;
};

type PlanTaskOptions = {
	executable?: () => string;
	forceKillGraceMs?: number;
	shutdownGraceMs?: number;
	spawn?: ProcessSpawner;
	startupTimeoutMs?: number;
};


const MAX_STDERR_LENGTH = 65_536;
const MAX_UPDATE_LENGTH = 4_096;
const MAX_RPC_FRAME_LENGTH = 1_048_576;
const WORKER_PROMPT =
	"Complete the user's assigned task autonomously with all available tools. Follow repository instructions, do not delegate, and return a concise result with concrete evidence.";

async function withTimeout<T>(promise: Promise<T>, milliseconds: number, message: string): Promise<T> {
	const timeout = Promise.withResolvers<T>();
	const timer = setTimeout(() => timeout.reject(new Error(message)), milliseconds);
	try {
		return await Promise.race([promise, timeout.promise]);
	} finally {
		clearTimeout(timer);
	}
}

function asError(error: unknown): Error {
	return error instanceof Error ? error : new Error(String(error));
}

function readText(content: unknown): string | undefined {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return undefined;
	const text = content
		.flatMap((part) => {
			if (typeof part === "string") return [part];
			if (part && typeof part === "object" && typeof (part as JsonObject).text === "string") {
				return [(part as JsonObject).text as string];
			}
			return [];
		})
		.join("");
	return text || undefined;
}



function appendStderr(current: string, chunk: string): string {
	const combined = current + chunk;
	return combined.length <= MAX_STDERR_LENGTH ? combined : combined.slice(-MAX_STDERR_LENGTH);
}

async function consumeLines(stream: Stream, onFrame: (frame: JsonObject) => void): Promise<void> {
	const decoder = new TextDecoder();
	let buffered = "";
	for await (const chunk of stream) {
		buffered += typeof chunk === "string" ? chunk : decoder.decode(chunk, { stream: true });
		let newlineIndex = buffered.indexOf("\n");
		if (newlineIndex < 0 && buffered.length > MAX_RPC_FRAME_LENGTH) {
			throw new Error("worker emitted an unterminated oversized JSONL frame");
		}
		while (newlineIndex >= 0) {
			if (newlineIndex > MAX_RPC_FRAME_LENGTH) {
				throw new Error("worker emitted an oversized JSONL frame");
			}
			const line = buffered.slice(0, newlineIndex).trim();
			buffered = buffered.slice(newlineIndex + 1);
			if (line) {
				const frame = JSON.parse(line);
				if (!frame || typeof frame !== "object" || Array.isArray(frame)) {
					throw new Error("worker emitted a non-object JSONL frame");
				}
				onFrame(frame as JsonObject);
			}
			newlineIndex = buffered.indexOf("\n");
		}
	}
	buffered += decoder.decode();
	if (buffered.trim()) {
		const frame = JSON.parse(buffered.trim());
		if (!frame || typeof frame !== "object" || Array.isArray(frame)) {
			throw new Error("worker emitted a non-object JSONL frame");
		}
		onFrame(frame as JsonObject);
	}
}

async function consumeStderr(stream: Stream | undefined, setStderr: (stderr: string) => void): Promise<void> {
	if (!stream) return;
	const decoder = new TextDecoder();
	let stderr = "";
	for await (const chunk of stream) {
		stderr = appendStderr(stderr, typeof chunk === "string" ? chunk : decoder.decode(chunk, { stream: true }));
		setStderr(stderr);
	}
	setStderr(appendStderr(stderr, decoder.decode()));
}

async function writeFrame(child: ChildProcess, frame: JsonObject): Promise<void> {
	if (!child.stdin) throw new Error("worker stdin is unavailable");
	await child.stdin.write(`${JSON.stringify(frame)}\n`);
}

async function closeStdin(child: ChildProcess): Promise<void> {
	if (!child.stdin?.end) return;
	await child.stdin.end();
}

async function waitForExit(child: ChildProcess, milliseconds: number): Promise<number | undefined> {
	const timeout = Promise.withResolvers<number | undefined>();
	const timer = setTimeout(() => timeout.resolve(undefined), milliseconds);
	try {
		return await Promise.race([child.exited, timeout.promise]);
	} finally {
		clearTimeout(timer);
	}
}

async function terminateWindowsProcess(
	spawn: ProcessSpawner,
	pid: number,
): Promise<void> {
	const taskkill = spawn({
		cmd: ["taskkill", "/PID", String(pid), "/T", "/F"],
		stderr: "pipe",
		stdin: "ignore",
		stdout: "ignore",
		windowsHide: true,
	});
	const status = await taskkill.exited;
	if (status !== 0) throw new Error(`taskkill failed with exit status ${status}`);
}
function signalProcessGroup(pid: number, signal: NodeJS.Signals | 0): boolean {
	try {
		process.kill(-pid, signal);
		return true;
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ESRCH") return false;
		throw error;
	}
}


async function stopWorker(
	child: ChildProcess,
	spawn: ProcessSpawner,
	shutdownGraceMs: number,
	forceKillGraceMs: number,
): Promise<void> {
	try {
		await writeFrame(child, { type: "abort" });
	} catch {
		// A broken stdin cannot prevent process-tree cleanup.
	}
	try {
		await closeStdin(child);
	} catch {
		// The process group remains the cleanup authority after stdin failure.
	}

	const directExit = await waitForExit(child, shutdownGraceMs);
	if (process.platform === "win32") {
		if (directExit === undefined) {
			if (!child.pid) throw new Error("worker exited neither cleanly nor with a usable PID");
			await terminateWindowsProcess(spawn, child.pid);
		}
		await child.exited;
		return;
	}
	if (!child.pid) {
		if (directExit === undefined) throw new Error("worker exited neither cleanly nor with a usable PID");
		return;
	}
	if (signalProcessGroup(child.pid, "SIGTERM")) {
		await Bun.sleep(forceKillGraceMs);
		if (signalProcessGroup(child.pid, 0)) signalProcessGroup(child.pid, "SIGKILL");
	}
	await child.exited;
}

export function resolveOmpExecutable(): string {
	const executable = process.execPath;
	const name = basename(executable).toLowerCase();
	if (name === "omp" || name === "omp.exe") return executable;
	throw new Error(`plan_task cannot resolve the current OMP executable: ${executable}`);
}

export function createPlanTaskExtension({
	spawn = Bun.spawn as unknown as ProcessSpawner,
	executable = resolveOmpExecutable,
	startupTimeoutMs = 30_000,
	shutdownGraceMs = 5_000,
	forceKillGraceMs = 1_000,
}: PlanTaskOptions = {}) {
	return function planTaskExtension(pi: ExtensionAPI): void {
		const { z } = pi.zod;
		pi.registerTool({
			name: "plan_task",
			label: "Plan Task",
			description: "Delegate execution-only work from native plan mode to a full-capability OMP worker.",
			approval: "exec",
			parameters: z.object({ task: z.string().min(1) }),
			async execute(
				_toolCallId: string,
				params: { task: string },
				signal: AbortSignal | undefined,
				onUpdate: Update | undefined,
				ctx: ToolContext,
			): Promise<ToolResult> {
				if (!params.task.trim()) {
					return {
						content: [{ type: "text", text: "plan_task requires a non-empty task." }],
						isError: true,
					};
				}

				let child: ChildProcess | undefined;
				let stderr = "";
				let stdoutReader: Promise<void> | undefined;
				let stderrReader: Promise<void> | undefined;
				let stopping = false;
				let cleanExitExpected = false;
				try {
					const worker = executable();
					child = spawn({
						cmd: [
							worker,
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
							WORKER_PROMPT,
						],
						cwd: ctx.cwd,
						detached: process.platform !== "win32",
						stdin: "pipe",
						stderr: "pipe",
						stdout: "pipe",
						windowsHide: process.platform === "win32",
					});
					if (!child.stdout) throw new Error("worker stdout is unavailable");

					const ready = Promise.withResolvers<void>();
					const completed = Promise.withResolvers<string>();
					void ready.promise.catch(() => undefined);
					void completed.promise.catch(() => undefined);
					const promptId = `plan_task_${crypto.randomUUID()}`;
					let agentEnded = false;
					let workerCompleted = false;
					let latestAssistantText: string | undefined;
					let promptAcknowledged = false;
					let terminalError: Error | undefined;

					const fail = (error: unknown): void => {
						if (terminalError) return;
						terminalError = asError(error);
						ready.reject(terminalError);
						completed.reject(terminalError);
					};
					const finish = (): void => {
						if (!promptAcknowledged || !agentEnded || terminalError) return;
						if (!latestAssistantText?.trim()) {
							fail(new Error("worker completed without an assistant message_end text"));
							return;
						}
						workerCompleted = true;
						completed.resolve(latestAssistantText);
					};
					const onFrame = (frame: JsonObject): void => {
						if (frame.type === "ready") {
							ready.resolve();
							return;
						}
						if (frame.type === "tool_execution_start" || frame.type === "tool_execution_update") {
							const serialized = JSON.stringify(frame);
							onUpdate?.({
								content: [
									{
										type: "text",
										text:
											serialized.length <= MAX_UPDATE_LENGTH
												? serialized
												: `${serialized.slice(0, MAX_UPDATE_LENGTH)}…`,
									},
								],
								details: { rpcEvent: frame.type },
							});
							return;
						}
						if (frame.type === "message_end") {
							const message = frame.message as JsonObject | undefined;
							if (message?.role !== "assistant") return;
							if (message.errorMessage || message.stopReason === "aborted" || message.stopReason === "error") {
								fail(new Error(`worker assistant failed: ${String(message.errorMessage ?? message.stopReason)}`));
								return;
							}
							latestAssistantText = readText(message.content);
							return;
						}
						if (frame.type === "prompt_result" && frame.id === promptId && frame.agentInvoked === false) {
							fail(new Error("worker prompt completed without invoking an agent"));
							return;
						}
						if (frame.type === "response" && frame.id === promptId) {
							if (frame.success !== true) {
								fail(new Error(`worker prompt failed: ${String(frame.error ?? "unknown error")}`));
								return;
							}
							const data = frame.data as JsonObject | undefined;
							if (data?.agentInvoked === false) {
								fail(new Error("worker prompt completed without invoking an agent"));
								return;
							}
							promptAcknowledged = true;
							finish();
							return;
						}
						if (frame.type === "agent_end") {
							if (frame.willContinue === true) return;
							agentEnded = true;
							finish();
						}
					};

					stdoutReader = consumeLines(child.stdout, onFrame)
						.then(() => {
							if (!workerCompleted && !terminalError) fail(new Error("worker RPC stdout closed before completion"));
						})
						.catch((error) => {
							fail(new Error(`worker RPC stream failed: ${asError(error).message}`));
						});
					stderrReader = consumeStderr(child.stderr, (value) => {
						stderr = value;
					});
					const abort = (): void => fail(new Error("plan_task aborted"));
					signal?.addEventListener("abort", abort, { once: true });
					if (signal?.aborted) abort();
					try {
						await withTimeout(ready.promise, startupTimeoutMs, "worker did not emit ready before timeout");
						if (signal?.aborted) abort();
						if (terminalError) throw terminalError;
						await writeFrame(child, { id: promptId, message: params.task, type: "prompt" });
						const result = await completed.promise;
						cleanExitExpected = true;
						await closeStdin(child);
						const status = await waitForExit(child, shutdownGraceMs);
						if (status === undefined) throw new Error("worker did not exit after stdin closed");
						if (status !== 0) throw new Error(`worker exited with status ${status}`);
						await Promise.all([stdoutReader, stderrReader]);
						if (terminalError) throw terminalError;
						return { content: [{ type: "text", text: result }] };
					} finally {
						signal?.removeEventListener("abort", abort);
					}
				} catch (error) {
					if (child && !stopping) {
						stopping = true;
						try {
							await stopWorker(child, spawn, shutdownGraceMs, forceKillGraceMs);
						} catch (cleanupError) {
							error = new Error(`${asError(error).message}; cleanup failed: ${asError(cleanupError).message}`);
						}
					}
					if (stdoutReader) await stdoutReader;
					if (stderrReader) await stderrReader;
					const message = asError(error).message;
					return {
						content: [
							{
								type: "text",
								text: stderr.trim() ? `plan_task failed: ${message}\nstderr:\n${stderr.trim()}` : `plan_task failed: ${message}`,
							},
						],
						isError: true,
					};
				}
			},
		});
	};
}

export default createPlanTaskExtension();
