"""Regression coverage for Pi's interactive startup-plus-exit latency."""

from __future__ import annotations

import errno
import os
import pty
import select
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_SOURCE = REPO_ROOT / "home" / "dot_pi" / "agent"
WARMUP_RUNS = 2
MEASURED_RUNS = 5
READINESS_MARKER = b"__PI_STARTUP_PERFORMANCE_READY__"
SHELL_PROMPT_MARKER = b"__PI_STARTUP_PERFORMANCE_SHELL_PROMPT__"
RUN_TIMEOUT_SECONDS = 30

pytestmark = pytest.mark.slow


class PtyProcess:
    """Minimal PTY driver for Pi's interactive terminal UI."""

    def __init__(
        self, command: list[str], environment: dict[str, str], cwd: Path
    ) -> None:
        self.master_fd, slave_fd = pty.openpty()
        try:
            self.process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=environment,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)
        self.output = bytearray()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        os.close(self.master_fd)

    def send(self, content: bytes) -> None:
        os.write(self.master_fd, content)

    def wait_for(self, marker: bytes, start: int = 0) -> int:
        deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            index = self.output.find(marker, start)
            if index >= 0:
                return index + len(marker)
            readable, _, _ = select.select(
                [self.master_fd], [], [], max(0, deadline - time.monotonic())
            )
            if not readable:
                continue
            try:
                self.output.extend(os.read(self.master_fd, 65_536))
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
        decoded = bytes(self.output).decode(errors="replace")
        raise AssertionError(
            f"timed out waiting for {marker!r}; PTY output:\n{decoded}"
        )


def _clean_environment() -> dict[str, str]:
    """Keep project tool resolution while isolating Git routing from the parent process."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }


def _write_benchmark_extension(agent_dir: Path) -> None:
    extensions = agent_dir / "extensions"
    extensions.mkdir(exist_ok=True)
    (extensions / "startup-performance-ready.ts").write_text(
        """export default function startupPerformanceReady(pi) {
\tpi.on(\"session_start\", async (_event, ctx) => {
\t\tctx.ui.setStatus(\"startup-performance-ready\", \"__PI_STARTUP_PERFORMANCE_READY__\");
\t});
}
""",
        encoding="utf-8",
    )


def _benchmark_environment(tmp_path: Path) -> dict[str, str]:
    """Build an isolated Pi config without overriding PI_PACKAGE_DIR.

    Pi 0.80.6 treats an empty ``PI_PACKAGE_DIR`` as its installation and reports
    version 0.0.0. The real ``mise x -- pi`` launcher must therefore discover the
    pinned installed package itself.
    """
    agent_dir = tmp_path / "agent"
    zdotdir = tmp_path / "zsh"
    zdotdir.mkdir(parents=True)
    shutil.copytree(AGENT_SOURCE / "extensions", agent_dir / "extensions")
    _write_benchmark_extension(agent_dir)
    environment = _clean_environment()
    environment.update(
        {
            # The immutable mise installation is only used to resolve the pinned launcher;
            # every Pi-owned state path below remains disposable.
            "MISE_DATA_DIR": str(Path.home() / ".local" / "share" / "mise"),
            "PI_CODING_AGENT_DIR": str(agent_dir),
            "PI_CODING_AGENT_SESSION_DIR": str(tmp_path / "sessions"),
            "PI_MEMORY_DIR": str(tmp_path / "memory"),
            "PI_TUI_LOG_DIR": str(tmp_path / "tui-logs"),
            "TMPDIR": str(tmp_path / "tmp"),
            "ZDOTDIR": str(zdotdir),
        }
    )
    return environment


def _run_once(tmp_path: Path) -> float:
    environment = _benchmark_environment(tmp_path)
    terminal = PtyProcess(["zsh", "-fi"], environment, REPO_ROOT)
    try:
        terminal.send(
            b"PS1='pi-benchmark%# '; precmd() { print -rn -- '__PI_STARTUP_PERFORMANCE_SHELL_PROMPT__' }\r"
        )
        shell_output_end = terminal.wait_for(SHELL_PROMPT_MARKER)
        started = time.monotonic()
        terminal.send(b"mise x -- pi\r")
        terminal.wait_for(READINESS_MARKER, shell_output_end)
        terminal.send(b"\x04")
        terminal.wait_for(SHELL_PROMPT_MARKER, shell_output_end)
        return time.monotonic() - started
    finally:
        terminal.close()


def test_pi_combined_startup_and_exit_stays_within_budget(tmp_path: Path) -> None:
    """Launch the real Pi CLI in a PTY and bound the combined interactive latency."""
    assert shutil.which("mise") is not None, (
        "Pi startup performance coverage requires mise"
    )
    assert shutil.which("zsh") is not None, (
        "Pi startup performance coverage requires zsh"
    )

    for iteration in range(WARMUP_RUNS):
        _run_once(tmp_path / f"warmup-{iteration}")
    samples = [
        _run_once(tmp_path / f"sample-{iteration}")
        for iteration in range(MEASURED_RUNS)
    ]

    # Five samples cannot estimate a tail percentile reliably; the maximum bounds every
    # observed run and catches the sustained regression this test protects against.
    # Baseline on 2026-07-16: max 3.35 s across five post-memory-removal samples.
    measured_maximum = max(samples)
    assert measured_maximum <= 5, f"startup+exit samples: {samples!r}"
