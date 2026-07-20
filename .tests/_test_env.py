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
from typing import Any, NoReturn

import pytest

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
    except PermissionError:
        # Darwin can reject signal 0 for a process group containing only a
        # just-terminated zombie; reaping its leader completes cleanup.
        return False
    return True


def terminate_process_group(
    process: subprocess.Popen[Any],
    *,
    grace: float = _PROCESS_GROUP_TERMINATION_TIMEOUT_SECONDS,
) -> None:
    """Terminate and reap a harness process and, on POSIX, its session descendants."""
    if os.name == "nt":
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=grace)
        return

    process_group = process.pid
    if process.poll() is not None and not _process_group_exists(process_group):
        return

    killed = False
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass
    else:
        deadline = time.monotonic() + grace
        while True:
            # Reap the session leader during the grace period. On Darwin, a
            # terminated-but-unreaped leader can keep its process group visible.
            process.poll()
            if not _process_group_exists(process_group):
                break
            if time.monotonic() >= deadline:
                try:
                    os.killpg(process_group, signal.SIGKILL)
                    killed = True
                except ProcessLookupError:
                    pass
                break
            time.sleep(0.05)

    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        if not killed:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=grace)


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
    # Runtime harnesses keep five seconds for graceful shutdown; regression tests
    # shorten it so SIGKILL escalation is covered without slowing the fast gate.
    termination_grace_seconds: float = _PROCESS_GROUP_TERMINATION_TIMEOUT_SECONDS,
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
        terminate_process_group(process, grace=termination_grace_seconds)
        stdout, stderr = process.communicate()
        raise AssertionError(
            f"Timed out after {timeout_seconds} seconds during {phase}.\n"
            f"command: {command!r}\n"
            f"stdout:\n{stdout or _diagnostic_output(error.stdout)}\n"
            f"stderr:\n{stderr or _diagnostic_output(error.stderr)}"
        ) from error
    finally:
        terminate_process_group(process, grace=termination_grace_seconds)

    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _skip_mise_resolution(
    phase: str,
    command: list[str],
    *,
    returncode: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    detail: str | None = None,
) -> NoReturn:
    """Skip optional Pi runtime coverage when its pinned mise tools are unavailable."""
    lines = [
        f"Pi runtime coverage unavailable during {phase}.",
        f"command: {command!r}",
        f"returncode: {returncode if returncode is not None else '<unavailable>'}",
        f"stdout:\n{_diagnostic_output(stdout)}",
        f"stderr:\n{_diagnostic_output(stderr)}",
    ]
    if detail:
        lines.append(detail)
    raise pytest.skip("\n".join(lines))


def _mise_resolution_result(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    phase: str,
) -> subprocess.CompletedProcess[str]:
    """Run one mise lookup or skip with its diagnostics when it cannot run."""
    try:
        result = _run_process_group(
            command,
            cwd=cwd,
            environment=environment,
            timeout_seconds=30,
            phase=phase,
        )
    except AssertionError as error:
        _skip_mise_resolution(phase, command, detail=str(error))

    if result.returncode != 0:
        _skip_mise_resolution(
            phase,
            command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


def _mise_pi_runtime_paths(cwd: Path, environment: dict[str, str]) -> tuple[Path, Path]:
    """Resolve Pi and Node from the versions pinned by this repository's mise file."""
    mise = shutil.which("mise")
    if mise is None:
        _skip_mise_resolution(
            "mise executable lookup",
            ["mise"],
            stderr="mise is not on PATH",
        )
    assert mise is not None

    package_command = [mise, "where", _PI_MISE_TOOL]
    package_result = _mise_resolution_result(
        package_command,
        cwd=cwd,
        environment=environment,
        phase="Pi package resolution",
    )
    package_dir = (
        Path(package_result.stdout.strip())
        / "lib"
        / "node_modules"
        / "@earendil-works"
        / "pi-coding-agent"
    )
    if not package_dir.is_dir():
        _skip_mise_resolution(
            "Pi package resolution",
            package_command,
            returncode=package_result.returncode,
            stdout=package_result.stdout,
            stderr=package_result.stderr,
            detail=f"missing installed Pi package: {package_dir}",
        )

    node_command = [mise, "which", "node"]
    node_result = _mise_resolution_result(
        node_command,
        cwd=cwd,
        environment=environment,
        phase="Node executable resolution",
    )
    node = Path(node_result.stdout.strip())
    if not node.is_file():
        _skip_mise_resolution(
            "Node executable resolution",
            node_command,
            returncode=node_result.returncode,
            stdout=node_result.stdout,
            stderr=node_result.stderr,
            detail=f"missing mise-managed Node executable: {node}",
        )
    return package_dir, node
