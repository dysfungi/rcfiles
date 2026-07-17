"""Regression guardrail for OMP's deterministic headless RPC lifecycle.

OMP is measured only after all ambient agent state is removed: each spawn receives
an empty working directory, HOME/XDG roots, and an overlay that disables OMP's
background update, marketplace, QA, and remote-compaction paths. A self-contained
fake model definition is required for OMP to initialize, but points at an unused
loopback address; RPC mode has no request to execute and ``--no-tools`` prevents a
model call. The test therefore measures the real session startup/shutdown lifecycle
without reading live credentials, touching ``~/.omp/agent``, or using the network.

Baseline measured on Darwin arm64 with omp 17.0.0 on 2026-07-16:
  startup: 2653 ms best-of-3 after warmup (2653-2769 ms measured range)
  shutdown: 43 ms best-of-3 after warmup (43-47 ms measured range)

The 3,000 ms startup default is intentionally a tight guardrail: about 1.08x the
slowest 2,769 ms baseline sample. Its thin scheduling margin detects modest
lifecycle regressions. The 200 ms shutdown limit is about 4.3x the slowest 47 ms
baseline sample: modestly above 3.5x while still detecting material lifecycle
regressions. Set OMP_STARTUP_MAX_MS or
OMP_SHUTDOWN_MAX_MS to tighten or relax either limit without editing this file.
OMP_STARTUP_INJECT_DELAY_SECONDS is a test-harness-only fault injection used to
prove the startup limit fails when measured latency is deliberately increased.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

import pytest
from pathlib import Path
from typing import TextIO


DEFAULT_STARTUP_THRESHOLD_MS = 3_000.0
DEFAULT_SHUTDOWN_THRESHOLD_MS = 200.0
MEASURED_RUNS = 3
READY_TIMEOUT_SECONDS = 30
CLEAN_SHUTDOWN_TIMEOUT_SECONDS = 10
FORCED_TERMINATION_TIMEOUT_SECONDS = 5
STARTUP_DELAY_ENV = "OMP_STARTUP_INJECT_DELAY_SECONDS"

_OVERLAY_CONFIG = """\
startup:
  checkUpdate: false
marketplace:
  autoUpdate: off
dev:
  autoqa: false
compaction:
  remoteEnabled: false
modelRoles:
  default: fixture/fixture
"""

# OMP needs one selectable model before it emits RPC readiness. This never receives a
# request: the test disables tools and closes stdin immediately after readiness.
_FIXTURE_MODELS = """\
providers:
  fixture:
    baseUrl: "http://127.0.0.1:9"
    apiKey: "fixture-token"
    api: "openai-completions"
    models:
      - id: "fixture"
        name: "Fixture"
        reasoning: false
        contextWindow: 1024
        maxTokens: 256
        cost:
          input: 0
          output: 0
          cacheRead: 0
          cacheWrite: 0
"""


def _diagnostic_output(output: str | bytes | None) -> str:
    """Render partial subprocess output consistently in failures."""
    if isinstance(output, bytes):
        output = output.decode(errors="replace")
    return output or "<empty>"


def _read_stderr(stderr: TextIO) -> str:
    """Read diagnostics from the file that avoids a competing stderr pipe."""
    stderr.seek(0)
    return stderr.read()


def _omp_binary() -> Path:
    """Resolve OMP through mise's active tool configuration."""
    mise = shutil.which("mise")
    assert mise is not None, "OMP lifecycle regression requires mise"
    result = subprocess.run(
        [mise, "which", "omp"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "Could not resolve omp through mise's active tool configuration.\n"
        f"stdout:\n{_diagnostic_output(result.stdout)}\n"
        f"stderr:\n{_diagnostic_output(result.stderr)}"
    )
    omp = Path(result.stdout.strip())
    assert omp.is_file(), f"OMP executable is missing: {omp}"
    return omp


def _isolated_environment(home: Path) -> dict[str, str]:
    """Provide OMP only isolated state roots and no inherited credentials."""
    temporary_directory = home / "tmp"
    temporary_directory.mkdir()
    return {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "TMPDIR": str(temporary_directory),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"),
    }


def _start_response_reader(
    process: subprocess.Popen[str],
) -> tuple[queue.Queue[str | None], threading.Thread]:
    """Read JSON Lines asynchronously so readiness has a strict timeout."""
    stdout = process.stdout
    assert stdout is not None
    responses: queue.Queue[str | None] = queue.Queue()

    def read_responses() -> None:
        try:
            for line in stdout:
                responses.put(line)
        finally:
            responses.put(None)

    reader = threading.Thread(
        target=read_responses,
        name="omp-rpc-response-reader",
        daemon=True,
    )
    reader.start()
    return responses, reader


def _close_stdin(process: subprocess.Popen[str]) -> None:
    """Close the RPC input stream without masking an already-exited child."""
    stdin = process.stdin
    if stdin is None or stdin.closed:
        return
    try:
        stdin.close()
    except BrokenPipeError:
        pass
    except OSError:
        if process.poll() is None:
            raise


def _terminate_and_reap(process: subprocess.Popen[str]) -> None:
    """Terminate a failed lifecycle measurement without leaking a child process."""
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=FORCED_TERMINATION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=FORCED_TERMINATION_TIMEOUT_SECONDS)


def _wait_for_ready(
    process: subprocess.Popen[str],
    responses: queue.Queue[str | None],
) -> float:
    """Return the wall-clock instant OMP emits its RPC ready response."""
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    output: list[str] = []

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            line = responses.get(timeout=remaining)
        except queue.Empty:
            break
        if line is None:
            raise RuntimeError(
                "OMP closed stdout before its ready response "
                f"(returncode={process.poll()}; output={output!r})"
            )
        output.append(line)
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if response == {"type": "ready"}:
            return time.monotonic()

    raise TimeoutError(
        f'OMP did not emit {{"type":"ready"}} within {READY_TIMEOUT_SECONDS} '
        f"seconds (returncode={process.poll()}; output={output!r})"
    )


def _startup_delay_seconds() -> float:
    """Read optional test-only latency injection used to validate the guardrail."""
    value = os.environ.get(STARTUP_DELAY_ENV)
    if value is None:
        return 0.0
    try:
        delay = float(value)
    except ValueError as error:
        raise AssertionError(
            f"{STARTUP_DELAY_ENV} must be a number, got {value!r}"
        ) from error
    assert delay >= 0, f"{STARTUP_DELAY_ENV} must be non-negative, got {delay}"
    return delay


def _command_with_optional_delay(command: list[str], delay_seconds: float) -> list[str]:
    """Prefix OMP with an exec wrapper only when proving the threshold is real."""
    if delay_seconds == 0:
        return command
    return [
        sys.executable,
        "-c",
        (
            "import os, sys, time; "
            "time.sleep(float(sys.argv[1])); "
            "os.execvpe(sys.argv[2], sys.argv[2:], os.environ)"
        ),
        str(delay_seconds),
        *command,
    ]


def _measure_lifecycle(omp: Path, run_root: Path) -> tuple[float, float]:
    """Measure spawn-to-ready and stdin-close-to-exit for one isolated OMP session."""
    cwd = run_root / "cwd"
    home = run_root / "home"
    agent_directory = home / ".omp" / "agent"
    run_root.mkdir()
    cwd.mkdir()
    agent_directory.mkdir(parents=True)
    (agent_directory / "models.yml").write_text(_FIXTURE_MODELS, encoding="utf-8")
    overlay = run_root / "overlay.yml"
    overlay.write_text(_OVERLAY_CONFIG, encoding="utf-8")

    command = [
        str(omp),
        "--cwd",
        str(cwd),
        "--config",
        str(overlay),
        "--mode",
        "rpc",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-rules",
        "--no-tools",
    ]
    environment = _isolated_environment(home)
    command = _command_with_optional_delay(command, _startup_delay_seconds())

    with (run_root / "omp.stderr").open(
        "w+", encoding="utf-8", errors="replace"
    ) as stderr:
        started_at = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        responses, response_reader = _start_response_reader(process)
        try:
            ready_at = _wait_for_ready(process, responses)
            shutdown_started_at = time.monotonic()
            _close_stdin(process)
            try:
                process.wait(timeout=CLEAN_SHUTDOWN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as error:
                _terminate_and_reap(process)
                raise AssertionError(
                    "OMP did not exit after clean RPC stdin closure within "
                    f"{CLEAN_SHUTDOWN_TIMEOUT_SECONDS} seconds.\n"
                    f"stderr:\n{_read_stderr(stderr)}"
                ) from error
        except (RuntimeError, TimeoutError) as error:
            _terminate_and_reap(process)
            raise AssertionError(f"{error}\nstderr:\n{_read_stderr(stderr)}") from error
        finally:
            if process.poll() is None:
                _terminate_and_reap(process)
            response_reader.join(timeout=FORCED_TERMINATION_TIMEOUT_SECONDS)
            assert not response_reader.is_alive(), (
                "OMP response reader did not exit after child cleanup.\n"
                f"stderr:\n{_read_stderr(stderr)}"
            )

        assert process.returncode == 0, _read_stderr(stderr)
    return (ready_at - started_at) * 1_000, (
        time.monotonic() - shutdown_started_at
    ) * 1_000


@pytest.mark.slow
def test_startup_and_shutdown_time(tmp_path: Path) -> None:
    """OMP RPC lifecycle stays within best-of-N startup and teardown limits."""
    omp = _omp_binary()
    startup_threshold_ms = float(
        os.environ.get("OMP_STARTUP_MAX_MS", DEFAULT_STARTUP_THRESHOLD_MS)
    )
    shutdown_threshold_ms = float(
        os.environ.get("OMP_SHUTDOWN_MAX_MS", DEFAULT_SHUTDOWN_THRESHOLD_MS)
    )

    # The discarded spawn allows one-time runtime initialization to settle first.
    _measure_lifecycle(omp, tmp_path / "warmup")
    measurements = [
        _measure_lifecycle(omp, tmp_path / f"run-{index}")
        for index in range(MEASURED_RUNS)
    ]
    startup_times = [startup for startup, _ in measurements]
    shutdown_times = [shutdown for _, shutdown in measurements]
    best_startup_ms = min(startup_times)
    best_shutdown_ms = min(shutdown_times)

    assert best_startup_ms < startup_threshold_ms, (
        f"OMP startup regressed: best-of-{MEASURED_RUNS} = {best_startup_ms:.1f} ms "
        f"(threshold {startup_threshold_ms:.0f} ms, "
        f"all runs: {[f'{value:.1f}' for value in startup_times]}).\n"
        "Inspect the isolated RPC lifecycle before raising OMP_STARTUP_MAX_MS."
    )
    assert best_shutdown_ms < shutdown_threshold_ms, (
        f"OMP shutdown regressed: best-of-{MEASURED_RUNS} = {best_shutdown_ms:.1f} ms "
        f"(threshold {shutdown_threshold_ms:.0f} ms, "
        f"all runs: {[f'{value:.1f}' for value in shutdown_times]}).\n"
        "Inspect clean RPC stdin-close handling before raising OMP_SHUTDOWN_MAX_MS."
    )
