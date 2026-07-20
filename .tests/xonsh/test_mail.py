"""PTY-level behavioral tests for xonsh's managed mail-spool notices.

The mail module is sourced into a real interactive xonsh process, not imported
as ordinary Python.  That matters because its startup path and pre-prompt hook
are registered through xonsh's runtime event system.  A tiny generated RC file
loads only the managed module, supplies a controlled mail spool, replaces the
module-local clock before the first prompt, and emits a post-hook marker.

The tests therefore cover both simulated Darwin and non-Darwin values without
sleeping for the 60-second throttle.  They also pin the deliberate definition
of an unreadable spool: ``os.path.getsize()`` must fail.  A mode-000 spool whose
metadata remains stat-able is still a populated spool and must announce mail.
"""

from __future__ import annotations

import os
import pty
import select
import shutil
import subprocess
import time
from pathlib import Path
from typing import Literal

import pytest

from _test_env import terminate_process_group

REPO_ROOT = Path(__file__).resolve().parents[2]
MANAGED_ROOT = REPO_ROOT / "home"
MAIL_MODULE = MANAGED_ROOT / "dot_config" / "xonsh" / "exact_rc.d" / "85-mail.xsh"
RC_DIRECTORY = MAIL_MODULE.parent
PROMPT_MARKER = "__MAIL_TEST_PROMPT_COMPLETE__"
_TIMEOUT_SECONDS = 15

pytestmark = pytest.mark.slow


class InteractiveXonsh:
    """A real xonsh process attached to an owned PTY with marker-based reads."""

    def __init__(self, xonsh: str, rc_file: Path, environment: dict[str, str]) -> None:
        master_fd, slave_fd = pty.openpty()
        try:
            self.process = subprocess.Popen(
                [xonsh, "--rc", str(rc_file), "--interactive"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=environment,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)
        self.master_fd = master_fd
        self.buffer = bytearray()
        self.closed = False

    def __enter__(self) -> InteractiveXonsh:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: BaseException | None,
        traceback: object,
    ) -> Literal[False]:
        self.close()
        return False

    def send_line(self, line: str) -> None:
        """Submit one line to the interactive xonsh process."""
        os.write(self.master_fd, line.encode() + b"\n")

    def read_until(self, marker: str) -> str:
        """Read through an event marker, retaining later PTY bytes for the next call."""
        marker_bytes = marker.encode()
        deadline = time.monotonic() + _TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            marker_index = self.buffer.find(marker_bytes)
            if marker_index >= 0:
                end = marker_index + len(marker_bytes)
                output = bytes(self.buffer[:end])
                del self.buffer[:end]
                return output.decode(errors="replace")
            if self.process.poll() is not None:
                raise AssertionError(
                    "xonsh exited before the expected prompt marker\n"
                    + bytes(self.buffer).decode(errors="replace")
                )
            readable, _, _ = select.select(
                [self.master_fd], [], [], max(0.0, deadline - time.monotonic())
            )
            if readable:
                self.buffer.extend(os.read(self.master_fd, 4096))
        raise AssertionError(
            f"timed out waiting for xonsh marker {marker!r}\n"
            + bytes(self.buffer).decode(errors="replace")
        )

    def run_until_prompt(self, line: str) -> str:
        """Run one command and collect output after all pre-prompt hooks run."""
        self.send_line(line)
        return self.read_until(PROMPT_MARKER)

    def close(self) -> None:
        """Reap the test-owned interactive process group and its PTY."""
        if self.closed:
            return
        self.closed = True
        terminate_process_group(self.process)
        os.close(self.master_fd)


def _xonsh_binary() -> str:
    """Require xonsh explicitly; supported CI jobs must not silently skip it."""
    xonsh = shutil.which("xonsh")
    if xonsh is None:
        raise AssertionError("xonsh is required for the managed-mail regression")
    return xonsh


def _environment(home: Path, spool: Path) -> dict[str, str]:
    """Build a clean-enough interactive environment with a controlled mail spool."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"XONSHRC", "TMUX", "TMUX_PANE"}
    }
    environment.update(
        {
            "HOME": str(home),
            "MAIL": str(spool),
            "TERM": "xterm-256color",
        }
    )
    return environment


def _write_rc(
    tmp_path: Path,
    platform_name: str,
    *,
    mock_getsize_failure: bool = False,
    mock_second_spool_stat_failure: bool = False,
    prompt_marker: bool = True,
) -> Path:
    """Create a minimal RC file that sources the actual managed mail module."""
    mock_getsize = ""
    if mock_getsize_failure:
        mock_getsize = """
def _mail_test_getsize_failure(_path):
    raise OSError("forced unreadable mail spool")

os.path.getsize = _mail_test_getsize_failure
"""
    mock_second_spool_stat = ""
    if mock_second_spool_stat_failure:
        mock_second_spool_stat = """
_mail_test_original_stat = os.stat
_mail_test_spool_stat_calls = [0]

def _mail_test_second_spool_stat_failure(path, *args, **kwargs):
    if path == os.environ["MAIL"]:
        _mail_test_spool_stat_calls[0] += 1
        if _mail_test_spool_stat_calls[0] == 2:
            raise OSError("forced unreadable mail spool")
    return _mail_test_original_stat(path, *args, **kwargs)

os.stat = _mail_test_second_spool_stat_failure
"""
    marker = ""
    if prompt_marker:
        marker = f"""
_mail_test_clock = [60.0]
_mail_clock = lambda: _mail_test_clock[0]

@events.on_pre_prompt
def _mail_test_prompt_marker(**kwargs):
    print({PROMPT_MARKER!r})
"""
    rc = tmp_path / f"mail-{platform_name}.xsh"
    rc.write_text(
        f"""import os
import sys

sys.path.insert(0, {str(RC_DIRECTORY)!r})
sys.platform = {platform_name!r}
{mock_getsize}
exec(compile(open({str(MAIL_MODULE)!r}).read(), {str(MAIL_MODULE)!r}, "exec"), globals(), globals())
{mock_second_spool_stat}
{marker}
"""
    )
    return rc


def _start_interactive_xonsh(
    tmp_path: Path,
    spool: Path,
    platform_name: str,
    *,
    mock_getsize_failure: bool = False,
    mock_second_spool_stat_failure: bool = False,
) -> tuple[InteractiveXonsh, str]:
    """Start real interactive xonsh and return its startup/pre-prompt output."""
    home = tmp_path / "home"
    home.mkdir()
    rc_file = _write_rc(
        tmp_path,
        platform_name,
        mock_getsize_failure=mock_getsize_failure,
        mock_second_spool_stat_failure=mock_second_spool_stat_failure,
    )
    shell = InteractiveXonsh(_xonsh_binary(), rc_file, _environment(home, spool))
    return shell, shell.read_until(PROMPT_MARKER)


@pytest.mark.parametrize("platform_name", ("darwin", "linux"))
def test_populated_spool_emits_one_startup_notice_on_every_platform(
    tmp_path: Path, platform_name: str
) -> None:
    """Existing mail is announced once whether xonsh thinks it is Darwin or Linux."""
    spool = tmp_path / "spool"
    spool.write_text("existing mail\n")

    shell, startup = _start_interactive_xonsh(tmp_path, spool, platform_name)
    with shell:
        assert startup.count("You have mail.") == 1
        assert "You have new mail." not in startup


@pytest.mark.parametrize("platform_name", ("darwin", "linux"))
def test_empty_and_noninteractive_shells_are_mail_silent(
    tmp_path: Path, platform_name: str
) -> None:
    """Empty spools and noninteractive commands never emit managed mail notices."""
    spool = tmp_path / "spool"
    spool.touch()

    shell, startup = _start_interactive_xonsh(tmp_path, spool, platform_name)
    with shell:
        assert "You have mail." not in startup
        assert "You have new mail." not in startup

    home = tmp_path / "noninteractive-home"
    home.mkdir()
    rc_file = _write_rc(tmp_path, platform_name, prompt_marker=False)
    result = subprocess.run(
        [_xonsh_binary(), "--rc", str(rc_file), "-c", "print('noninteractive-ok')"],
        capture_output=True,
        env=_environment(home, spool),
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr
    assert "You have mail." not in result.stdout + result.stderr
    assert "You have new mail." not in result.stdout + result.stderr


def test_spool_growth_is_throttled_without_real_time_sleep(tmp_path: Path) -> None:
    """Only one post-baseline growth notification appears after the virtual minute."""
    spool = tmp_path / "spool"
    spool.write_text("existing mail\n")

    shell, startup = _start_interactive_xonsh(tmp_path, spool, "darwin")
    with shell:
        assert startup.count("You have mail.") == 1
        spool.write_text("existing mail\nnew mail\n")

        throttled = shell.run_until_prompt("_mail_test_clock[0] = 90.0")
        assert "You have new mail." not in throttled

        announced = shell.run_until_prompt("_mail_test_clock[0] = 120.0")
        assert announced.count("You have new mail.") == 1

        repeated = shell.run_until_prompt("_mail_test_clock[0] = 120.0")
        assert "You have new mail." not in repeated


@pytest.mark.parametrize("platform_name", ("darwin", "linux"))
def test_missing_spool_then_created_emits_one_new_mail_notice(
    tmp_path: Path, platform_name: str
) -> None:
    """A spool created after an observed absence is new mail, not a baseline."""
    spool = tmp_path / "spool"

    shell, startup = _start_interactive_xonsh(tmp_path, spool, platform_name)
    with shell:
        assert "You have mail." not in startup
        assert "You have new mail." not in startup

        spool.write_text("delivered after shell startup\n")
        announced = shell.run_until_prompt("_mail_test_clock[0] = 120.0")
        assert announced.count("You have new mail.") == 1

        repeated = shell.run_until_prompt("_mail_test_clock[0] = 180.0")
        assert "You have new mail." not in repeated


def test_unreadable_probe_after_missing_spool_does_not_infer_new_mail(
    tmp_path: Path,
) -> None:
    """A transient metadata failure clears an old missing-spool observation."""
    spool = tmp_path / "spool"

    shell, startup = _start_interactive_xonsh(
        tmp_path,
        spool,
        "darwin",
        mock_second_spool_stat_failure=True,
    )
    with shell:
        assert "You have mail." not in startup
        assert "You have new mail." not in startup

        unreadable = shell.run_until_prompt("_mail_test_clock[0] = 120.0")
        assert "You have new mail." not in unreadable

        spool.write_text("mail delivered after an unreadable probe\n")
        recovered = shell.run_until_prompt("_mail_test_clock[0] = 180.0")
        assert "You have new mail." not in recovered


def test_spool_shrink_rebaselines_without_a_false_new_mail_notice(
    tmp_path: Path,
) -> None:
    """A smaller spool is ambiguous user compaction, so it resets the baseline."""
    spool = tmp_path / "spool"
    spool.write_text("existing mail\n" * 8)

    shell, startup = _start_interactive_xonsh(tmp_path, spool, "darwin")
    with shell:
        assert startup.count("You have mail.") == 1
        spool.write_text("remaining mail\n")
        rebaselined = shell.run_until_prompt("_mail_test_clock[0] = 120.0")
        assert "You have new mail." not in rebaselined


def test_mocked_getsize_failure_is_silent(tmp_path: Path) -> None:
    """An actual getsize failure is the sole unreadable-spool definition."""
    spool = tmp_path / "spool"
    spool.write_text("mail that must not be announced\n")

    shell, startup = _start_interactive_xonsh(
        tmp_path, spool, "darwin", mock_getsize_failure=True
    )
    with shell:
        assert "You have mail." not in startup
        assert "You have new mail." not in startup


def test_mode_zero_spool_remains_a_populated_spool_when_statable(
    tmp_path: Path,
) -> None:
    """Mode bits alone do not make metadata-readable mail spools unreadable."""
    spool = tmp_path / "spool"
    spool.write_text("existing mail\n")
    spool.chmod(0)
    try:
        assert os.path.getsize(spool) > 0
        shell, startup = _start_interactive_xonsh(tmp_path, spool, "linux")
        with shell:
            assert startup.count("You have mail.") == 1
    finally:
        spool.chmod(0o600)
