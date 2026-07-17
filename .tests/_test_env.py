"""Git-safe environment and subprocess helpers for repository tests.

Tests run nested Git commands while pre-commit may export Git's internal variables.
They must be removed so subprocesses operate on their intended temporary repositories
rather than the repository running pytest. Runtime harnesses also need a session-wide
cleanup boundary because their intentionally held descendants can retain output pipes.
"""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import time
from pathlib import Path

_PROCESS_GROUP_TERMINATION_TIMEOUT_SECONDS = 5
_PI_MISE_TOOL = "npm:@earendil-works/pi-coding-agent"


def _clean_env() -> dict[str, str]:
    """Return the environment without Git's repository-routing variables."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }


def _process_group_exists(process_group: int) -> bool:
    """Return whether a POSIX process group still contains a process."""
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    return True


def _terminate_and_reap_process_group(process: subprocess.Popen[str]) -> None:
    """End every harness descendant, including one retaining a captured pipe."""
    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + _PROCESS_GROUP_TERMINATION_TIMEOUT_SECONDS
    while _process_group_exists(process_group):
        if time.monotonic() >= deadline:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                return
            break
        time.sleep(0.05)

    try:
        process.wait(timeout=_PROCESS_GROUP_TERMINATION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=_PROCESS_GROUP_TERMINATION_TIMEOUT_SECONDS)


def _diagnostic_output(output: str | bytes | None) -> str:
    """Normalize subprocess output captured before a timeout."""
    if isinstance(output, bytes):
        output = output.decode(errors="replace")
    return output or "<empty>"


def _run_process_group(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: float,
    phase: str,
) -> subprocess.CompletedProcess[str]:
    """Run a harness in its own process group and retain timeout diagnostics."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate_and_reap_process_group(process)
        stdout, stderr = process.communicate()
        raise AssertionError(
            f"Timed out after {timeout_seconds} seconds during {phase}.\n"
            f"command: {command!r}\n"
            f"stdout:\n{stdout or _diagnostic_output(error.stdout)}\n"
            f"stderr:\n{stderr or _diagnostic_output(error.stderr)}"
        ) from error
    finally:
        _terminate_and_reap_process_group(process)

    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _mise_pi_runtime_paths(cwd: Path, environment: dict[str, str]) -> tuple[Path, Path]:
    """Resolve Pi and Node from the versions pinned by this repository's mise file."""
    mise = shutil.which("mise")
    assert mise is not None, "Pi runtime coverage requires mise"
    package_result = _run_process_group(
        [mise, "where", _PI_MISE_TOOL],
        cwd=cwd,
        environment=environment,
        timeout_seconds=30,
        phase="Pi package resolution",
    )
    assert package_result.returncode == 0, package_result.stderr
    package_dir = (
        Path(package_result.stdout.strip())
        / "lib"
        / "node_modules"
        / "@earendil-works"
        / "pi-coding-agent"
    )
    assert package_dir.is_dir(), f"missing installed Pi package: {package_dir}"
    node_result = _run_process_group(
        [mise, "which", "node"],
        cwd=cwd,
        environment=environment,
        timeout_seconds=30,
        phase="Node executable resolution",
    )
    assert node_result.returncode == 0, node_result.stderr
    node = Path(node_result.stdout.strip())
    assert node.is_file(), f"missing mise-managed Node executable: {node}"
    return package_dir, node
