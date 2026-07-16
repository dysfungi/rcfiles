# Pi memory performance and removal

## Problem

Pi startup and exit were slow in every directory and worsened as the memory store grew. The combined nearest-rank p95 was 5.9 s.

## Diagnosis

`home/dot_pi/agent/extensions/memory-git-sync.ts` (removed in this change) synchronously ran Git at both session boundaries:

- `session_start`: probe, fetch, commit local changes, and merge `origin/main`.
- `session_shutdown`: probe, commit local changes, and push.

The extension could launch about 29 Git subprocesses at startup and 19 at exit, each with a 20 s timeout. `pi-memory` added startup `qmd` detection and collection checks, plus an LLM-generated exit summary when quitting with populated memory.

## What was measured

A detached post-quit helper backgrounded the Git sync. In a real-launcher PTY benchmark with 20 warm samples and nearest-rank p95:

| Measurement             | Synchronous | Background Git |  Change |
| ----------------------- | ----------: | -------------: | ------: |
| Combined startup + exit |       5.9 s |          3.6 s |  -2.3 s |
| Exit                    |       1.5 s |         0.13 s | -1.37 s |
| Startup                 |       4.2 s |          3.5 s |  -0.7 s |

Background Git removed the exit cost, but startup remained about 3.5 s. The remaining startup cost is not Git; the leading suspects are pi-memory's `qmd` startup probes and Pi initialization.

## Decision

Pi memory is disabled until it can meet the performance target and its behavior is revisited. The shared cross-tool memory setup remains unchanged for Claude, Codex, and Gemini.

Removed from Pi only:

- the `memory-git-sync` extension and its helper;
- the Pi memory Git external;
- the `npm:pi-memory` package and `qmd` package declaration;
- root-guard memory tool and path allowances;
- worker memory and scratchpad tool declarations;
- Pi-only plan-mode, subagent, README, SSH-script, and root instruction references;
- memory synchronization tests and benchmark harness.

`my-agent-memory` remains available in Pi because it captures durable learnings as skills; it does not require Pi's `memory_*` tools.

## Benchmark methodology

The benchmark used a real interactive zsh through a PTY and invoked the production `pi` alias. Readiness was the unique widget marker rendered after `session_start`. Exit started with Ctrl-D and ended at a new zsh precmd marker; a second shell command prevented keypress races with terminal restoration.

Each run isolated `HOME`, `PI_CODING_AGENT_DIR`, `PI_CODING_AGENT_SESSION_DIR`, `PI_MEMORY_DIR`, TUI logs, `MISE_DATA_DIR`, `TMPDIR`, and `XDG_*`. A local bare Git remote and SSH shim prevented network access and real-memory access. The launcher used Pi 0.80.6 and Node 24.18.0. It used two warmups and 20 measured samples. Nearest-rank p95 was `ceil(n * 0.95) - 1`, or index 18 (the 19th ordered sample) for 20 samples.

When loading Pi bundled modules, resolve and pass the installed Pi package root explicitly. Do not rely on `PI_PACKAGE_DIR` discovery: an empty `PI_PACKAGE_DIR` made `pi --version` report `0.0.0`.

## Gotchas

The shared `my-agent-memory` skill may still reference `memory_*` tools that Pi no longer provides. That wording is intentionally retained because the skill is shared with tools that still use the cross-tool memory setup.

## Revisit plan

Target: combined startup + exit p95 <= 2 s.

1. Re-enable memory with eventual/background Git sync; the detached post-quit helper design worked.
2. Use a pi-memory fast mode or fork that skips startup `qmd` and index work, defers or disables automatic exit summaries, and indexes on demand.
3. Test an offline launcher (`PI_OFFLINE=1`) and disabled install telemetry.
4. Rebuild the PTY benchmark and measure before enabling each layer.
