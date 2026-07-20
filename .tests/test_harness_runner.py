"""Regression coverage for shared runtime-harness process-group cleanup."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

import _test_env
from _test_env import _clean_env, _run_process_group


@pytest.mark.skipif(
    os.name == "nt", reason="runtime-harness cleanup requires POSIX process groups"
)
def test_runner_reaps_sigterm_ignoring_descendants_after_timeout(
    tmp_path: Path,
) -> None:
    """Timeouts kill descendants that retain the harness output pipes."""
    child = "\n".join(
        [
            "import os, signal, subprocess, sys, time",
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
            "print(f'process-group:{os.getpgrp()}', flush=True)",
            "print('parent stderr', file=sys.stderr, flush=True)",
            "subprocess.Popen([sys.executable, '-c', \"import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)\"])",
            "time.sleep(60)",
        ]
    )

    with pytest.raises(AssertionError) as error:
        _run_process_group(
            [sys.executable, "-c", child],
            cwd=tmp_path,
            environment=_clean_env(),
            timeout_seconds=0.1,
            phase="SIGTERM-resistant child regression",
            termination_grace_seconds=0.2,
        )

    message = str(error.value)
    assert "SIGTERM-resistant child regression" in message
    assert "process-group:" in message
    assert "parent stderr" in message
    process_group_match = re.search(r"process-group:(\d+)", message)
    assert process_group_match is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(int(process_group_match.group(1)), 0)


class _WindowsFallbackProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.wait_timeouts: list[float] = []

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, *, timeout: float) -> int:
        self.wait_timeouts.append(timeout)
        if not self.killed:
            raise subprocess.TimeoutExpired("test process", timeout)
        return 0

    def kill(self) -> None:
        self.killed = True


def test_terminate_process_group_uses_process_cleanup_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows cleanup reaps the leader without POSIX process-group APIs."""
    process = _WindowsFallbackProcess()

    def fail_killpg(*_: object) -> None:
        raise AssertionError("Windows fallback must not use os.killpg")

    monkeypatch.setattr(_test_env.os, "name", "nt")
    monkeypatch.setattr(_test_env.os, "killpg", fail_killpg)

    _test_env.terminate_process_group(cast(subprocess.Popen[Any], process), grace=0.2)

    assert process.terminated
    assert process.killed
    assert process.wait_timeouts == [0.2, 0.2]


def test_mise_runtime_resolution_skips_with_missing_mise_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Optional Pi coverage skips when the host lacks mise."""
    monkeypatch.setattr(_test_env.shutil, "which", lambda _: None)

    with pytest.raises(pytest.skip.Exception) as error:
        _test_env._mise_pi_runtime_paths(tmp_path, _clean_env())

    message = str(error.value)
    assert "mise executable lookup" in message
    assert "command: ['mise']" in message
    assert "stdout:\n<empty>" in message
    assert "stderr:\nmise is not on PATH" in message
