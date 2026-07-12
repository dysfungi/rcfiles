"""End-to-end regressions for managed direct-shell tmux startup.

The old Darwin-only ``login(1)`` wrapper made tmux observe ``login`` rather
than the shell whose working directory changes.  This test starts a dedicated
socket, seeds its server with that stale command, then sources the *managed*
tmux configuration.  It deliberately does not recreate a binding fixture: the
source file itself must clear the stale option and provide the bindings that
users receive.

A real PTY client exercises prefix bindings after a detach/reattach.  The
runtime portion is marked slow because it requires a POSIX tmux implementation
and an interactive shell; CI runs it explicitly on macOS, Linux, and MSYS2.
The Windows WSL launcher check is deliberately structural: it renders and
inspects its commands but does not launch a WSL distribution. The native Linux
job validates the shared tmux configuration, not WSL process, PTY, environment,
or cwd behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
import json
import os
import pty
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TMUX_CONFIG = REPO_ROOT / "dot_config" / "tmux" / "tmux.conf"
WEZTERM_TEMPLATE = REPO_ROOT / "dot_wezterm.lua.tmpl"
_TIMEOUT_SECONDS = 15
_POLL_SECONDS = 0.05
_SESSION = "main"
_TEST_MAILCHECK_SECONDS = str(24 * 60 * 60)
_EXPECTED_TMUX_DEFAULT_COMMAND_SURFACES = (
    'set-option -g default-shell "$SHELL"',
    "set-option -gu default-command",
)
_UNIX_DEFAULT_PROGRAM = (
    'config.default_prog = tmux and { tmux, "new-session", "-A", "-s", "main" } '
    "or { shell }"
)
_WINDOWS_DEFAULT_PROGRAM = (
    r"""config.default_prog = { gitBin .. "/bash.exe", "-c", "wsl.exe --cd '~' """
    r"""-- bash -lc 'if command -v tmux >/dev/null 2>&1 && infocmp \"$TERM\""""
    r""" >/dev/null 2>&1; then exec tmux new-session -A -s main; else exec xonsh -l; """
    r"""fi' || exec tmux new-session -A -s main", }"""
)
_EXPECTED_DEFAULT_PROGRAMS = (
    _UNIX_DEFAULT_PROGRAM,
    _UNIX_DEFAULT_PROGRAM,
    _WINDOWS_DEFAULT_PROGRAM,
)
_UNIX_SHELL_LOGIN_LAUNCH_ARGUMENTS = (
    'args = { homebrewBin .. "/zsh", "-l" },',
    'args = { homebrewBin .. "/bash", "-l" },',
)
_WINDOWS_SHELL_LOGIN_LAUNCH_ARGUMENTS = (
    'args = { "wsl.exe", "-d", "Ubuntu", "--cd", "~", "--", "xonsh", "--login" },',
    'args = { "wsl.exe", "-d", "Ubuntu", "--cd", "~", "--", "bash", "--login" },',
)
_EXPECTED_LAUNCH_MENU_ARGUMENTS = (
    "args = { shell },",
    *_UNIX_SHELL_LOGIN_LAUNCH_ARGUMENTS,
    'args = { "wsl.exe", "-d", "Ubuntu", "--cd", "~" },',
    *_WINDOWS_SHELL_LOGIN_LAUNCH_ARGUMENTS,
    'args = { gitBin .. "/bash.exe" },',
    'args = { xonshBin .. "/xbin-xonsh" },',
    'args = { "powershell.exe", "-NoLogo" },',
    'args = { "powershell.exe", "-NoLogo", "-Command", \'"Start-Process Wezterm -Verb RunAs"\' },',
)
_EXPECTED_RENDERED_COMMAND_SURFACES = (
    *_EXPECTED_DEFAULT_PROGRAMS,
    *_EXPECTED_LAUNCH_MENU_ARGUMENTS,
)
_SHELL_LOGIN_COMMAND_SURFACES = (
    _WINDOWS_DEFAULT_PROGRAM,
    *_UNIX_SHELL_LOGIN_LAUNCH_ARGUMENTS,
    *_WINDOWS_SHELL_LOGIN_LAUNCH_ARGUMENTS,
)
_FORBIDDEN_ACCOUNT_LOGIN_COMMAND_SURFACES = (
    'config.default_prog = { "login" }',
    'config.default_prog = { "exec login" }',
    'config.default_prog = { "/usr/bin/login" }',
    'config.default_prog = { "exec /usr/bin/login" }',
    'args = { "login" },',
    'args = { "exec login" },',
    'args = { "/usr/bin/login" },',
    'args = { "exec /usr/bin/login" },',
)
_BINDINGS = (
    ("new-window", b"c"),
    ("vertical-split", b'"'),
    ("horizontal-split", b"%"),
)


@dataclass(frozen=True)
class PaneProbe:
    """Observable shell state written by a command issued to one tmux pane."""

    argv0: str
    cwd: str
    login: str
    mail: str
    mailcheck: str
    mailpath: str
    path: str
    shell: str
    term: str


@dataclass
class AttachedTmuxClient:
    """An owned PTY tmux client used only for real key-binding input."""

    master_fd: int
    process: subprocess.Popen[bytes]


class IsolatedTmuxServer:
    """Small, independently-addressed tmux server with deterministic cleanup."""

    def __init__(self, tmp_path: Path) -> None:
        tmux = shutil.which("tmux")
        bash = shutil.which("bash")
        if tmux is None:
            raise AssertionError("tmux is required for the direct-shell regression")
        if bash is None:
            raise AssertionError("bash is required for the direct-shell regression")

        self.tmux = tmux
        self.shell = Path(bash).resolve()
        self.socket = f"direct-shell-{secrets.token_hex(12)}"
        self.home = tmp_path / "home"
        self.home.mkdir(exist_ok=True)
        # The managed config creates a chezmoi window there; make its declared
        # start directory real so source-file is fully hermetic on every CI OS.
        (self.home / ".local" / "share" / "chezmoi").mkdir(parents=True)
        self.path_sentinel = tmp_path / "inherited-path"
        self.path_sentinel.mkdir()
        self.mailbox = tmp_path / "empty-mailbox"
        self.mailbox.touch()
        self.clients: list[AttachedTmuxClient] = []
        self.closed = False
        inherited_path = os.environ.get("PATH", "")
        excluded_environment = {
            "MAIL",
            "MAILCHECK",
            "MAILPATH",
            "TMUX",
            "TMUX_PANE",
        }
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_") and key not in excluded_environment
        }
        self.environment.update(
            {
                "HOME": str(self.home),
                "MAIL": str(self.mailbox),
                "MAILCHECK": _TEST_MAILCHECK_SECONDS,
                "MAILPATH": "",
                "PATH": os.pathsep.join((str(self.path_sentinel), inherited_path)),
                "SHELL": str(self.shell),
                # A known POSIX terminal keeps detached-server startup independent of
                # the caller's terminal emulator while tmux still supplies a terminal
                # type to every direct child shell.
                "TERM": "screen-256color",
            }
        )

    def __enter__(self) -> IsolatedTmuxServer:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: BaseException | None,
        traceback: object,
    ) -> Literal[False]:
        self.close()
        return False

    def command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run one command against only this isolated tmux socket."""
        return subprocess.run(
            [self.tmux, "-L", self.socket, "-f", os.devnull, *arguments],
            capture_output=True,
            env=self.environment,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )

    def run(self, *arguments: str) -> str:
        """Run a successful isolated tmux command and return its stdout."""
        result = self.command(*arguments)
        assert result.returncode == 0, (
            f"tmux command failed: {arguments!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        return result.stdout.rstrip("\n")

    def start(self) -> None:
        """Seed a stale server option, then source the managed configuration."""
        self.run("new-session", "-d", "-s", "bootstrap", "-c", str(self.home))
        self.run(
            "set-option",
            "-g",
            "default-command",
            'exec login -pfl "stale-user"',
        )
        assert self.run("show-options", "-gv", "default-command") == (
            'exec login -pfl "stale-user"'
        )

        self.run("source-file", str(TMUX_CONFIG))
        self._assert_stale_default_command_was_cleared()
        assert (
            Path(self.run("show-options", "-gv", "default-shell")).resolve()
            == self.shell
        )
        self.run("kill-session", "-t", "bootstrap")

    def _assert_stale_default_command_was_cleared(self) -> None:
        """Accept tmux's empty and absent representations of an unset option."""
        result = self.command("show-options", "-gv", "default-command")
        assert result.returncode in {0, 1}, result.stderr
        assert result.stdout.strip() == "", (
            "sourcing the managed tmux configuration retained a stale "
            f"default-command: {result.stdout!r} {result.stderr!r}"
        )

    def source_pane(self) -> str:
        """Return the initial pane created by the actual managed configuration."""
        panes = self.panes()
        assert panes, "managed configuration did not create the main tmux session"
        return panes[0]

    def panes(self) -> list[str]:
        """Return pane IDs that belong to the managed test session."""
        output = self.run("list-panes", "-a", "-F", "#{session_name}\t#{pane_id}")
        return [
            pane_id
            for line in output.splitlines()
            for session, pane_id in [line.split("\t", maxsplit=1)]
            if session == _SESSION
        ]

    def pane_pid(self, pane_id: str) -> int:
        """Return the direct child PID that tmux associates with one pane."""
        return int(self.run("display-message", "-p", "-t", pane_id, "#{pane_pid}"))

    def pane_path(self, pane_id: str) -> Path:
        """Return tmux's current-directory metadata for one pane."""
        return Path(
            self.run("display-message", "-p", "-t", pane_id, "#{pane_current_path}")
        ).resolve()

    def pane_output(self, pane_id: str) -> str:
        """Return recent pane text for direct-shell startup assertions."""
        return self.run("capture-pane", "-p", "-t", pane_id, "-S", "-100")

    def send_line(self, pane_id: str, line: str) -> None:
        """Queue one shell command in a pane, independent of client key bindings."""
        self.run("send-keys", "-t", pane_id, "-l", line)
        self.run("send-keys", "-t", pane_id, "Enter")

    def probe(self, pane_id: str, tmp_path: Path) -> PaneProbe:
        """Ask bash in a pane to write cwd, environment, and login-shell state."""
        destination = tmp_path / f"probe-{secrets.token_hex(8)}.json"
        program = """
import json
import os
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "argv0": os.environ.get("TMUX_DIRECT_ARGV0", ""),
            "cwd": os.getcwd(),
            "login": os.environ.get("TMUX_DIRECT_LOGIN", ""),
            "mail": os.environ.get("MAIL", ""),
            "mailcheck": os.environ.get("MAILCHECK", ""),
            "mailpath": os.environ.get("MAILPATH", ""),
            "path": os.environ.get("PATH", ""),
            "shell": os.environ.get("SHELL", ""),
            "term": os.environ.get("TERM", ""),
        }
    )
)
"""
        command = " ".join(
            (
                'TMUX_DIRECT_LOGIN="$(shopt -q login_shell && printf true || printf false)"',
                'TMUX_DIRECT_ARGV0="$0"',
                shlex.quote(sys.executable),
                "-c",
                shlex.quote(program),
                shlex.quote(str(destination)),
            )
        )
        self.send_line(pane_id, command)
        self.wait_for(destination.exists, f"probe from pane {pane_id}")
        return PaneProbe(**json.loads(destination.read_text()))

    def wait_for_pane_path(self, pane_id: str, expected: Path) -> None:
        """Wait for tmux's cwd metadata to observe a shell-side ``cd``."""
        resolved_expected = expected.resolve()
        self.wait_for(
            lambda: self.pane_path(pane_id) == resolved_expected,
            f"pane {pane_id} cwd {resolved_expected}",
        )

    def wait_for(self, predicate: Callable[[], bool], description: str) -> None:
        """Poll a side effect while retaining a useful timeout message."""
        deadline = time.monotonic() + _TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(_POLL_SECONDS)
        raise AssertionError(f"timed out waiting for {description}")

    def process_name(self, pane_id: str) -> str:
        """Return the pane process executable without reading process environments."""
        result = subprocess.run(
            ["ps", "-p", str(self.pane_pid(pane_id)), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def assert_direct_bash(
        self, pane_id: str, expected_cwd: Path, tmp_path: Path
    ) -> None:
        """Validate a direct configured login shell and its inherited environment."""
        actual_name = _executable_name(self.process_name(pane_id))
        expected_name = _executable_name(str(self.shell))
        assert actual_name == expected_name, (
            f"pane {pane_id} runs {actual_name!r}, expected configured shell "
            f"{expected_name!r}; account-level login must not own panes"
        )
        probe = self.probe(pane_id, tmp_path)
        assert probe.login == "true", f"{pane_id} is not a login shell: {probe!r}"
        assert probe.argv0.lstrip("-").startswith(expected_name), probe.argv0
        assert Path(probe.cwd).resolve() == expected_cwd.resolve()
        assert Path(probe.mail).resolve() == self.mailbox.resolve()
        assert probe.mailcheck == _TEST_MAILCHECK_SECONDS
        assert probe.mailpath == ""
        assert self.path_sentinel.as_posix() in probe.path.replace("\\", "/").split(
            os.pathsep
        )
        assert Path(probe.shell).resolve() == self.shell
        assert probe.term, "tmux child shell lost TERM"
        assert probe.term.startswith(("screen", "tmux")), probe.term

    def attach(self) -> AttachedTmuxClient:
        """Attach an owned PTY client so actual prefix bindings can receive input."""
        master_fd, slave_fd = pty.openpty()
        try:
            process = subprocess.Popen(
                [
                    self.tmux,
                    "-L",
                    self.socket,
                    "-f",
                    os.devnull,
                    "attach-session",
                    "-t",
                    _SESSION,
                ],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=self.environment,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)
        client = AttachedTmuxClient(master_fd, process)
        self.clients.append(client)
        self.wait_for(
            lambda: self._client_is_attached(client),
            f"tmux client {process.pid} attachment",
        )
        return client

    def _client_is_attached(self, client: AttachedTmuxClient) -> bool:
        if client.process.poll() is not None:
            raise AssertionError(
                f"tmux client exited before attaching: {client.process.pid}"
            )
        return (
            str(client.process.pid)
            in self.run("list-clients", "-F", "#{client_pid}").splitlines()
        )

    def detach(self, client: AttachedTmuxClient) -> None:
        """Detach the owned client through tmux, then reap its PTY process."""
        target = next(
            (
                tty
                for line in self.run(
                    "list-clients", "-F", "#{client_pid}\t#{client_tty}"
                ).splitlines()
                for pid, tty in [line.split("\t", maxsplit=1)]
                if pid == str(client.process.pid)
            ),
            None,
        )
        assert target is not None, f"tmux client is not attached: {client.process.pid}"
        try:
            self.run("detach-client", "-t", target)
            self.wait_for(
                lambda: str(client.process.pid)
                not in self.run("list-clients", "-F", "#{client_pid}").splitlines(),
                f"tmux client {client.process.pid} detachment",
            )
            # Detached tmux clients need not exit while their owning PTY remains
            # open. Reap this test-owned process after tmux has detached it.
            if client.process.poll() is None:
                client.process.kill()
            client.process.wait(timeout=_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            raise AssertionError(
                f"tmux client did not detach: {client.process.pid}"
            ) from error
        finally:
            with suppress(OSError):
                os.close(client.master_fd)
            if client in self.clients:
                self.clients.remove(client)

    def trigger_binding(
        self, client: AttachedTmuxClient, source_pane: str, key: bytes
    ) -> str:
        """Press prefix+key and return the exactly one pane it creates."""
        before = set(self.panes())
        self.run("select-window", "-t", f"{_SESSION}:0")
        self.run("select-pane", "-t", source_pane)
        os.write(client.master_fd, b"\x02" + key)
        self.wait_for(
            lambda: len(set(self.panes()) - before) == 1,
            f"binding {key.decode()} destination pane",
        )
        destinations = set(self.panes()) - before
        assert len(destinations) == 1
        return destinations.pop()

    def close(self) -> None:
        """Stop the owned server and reap any owned PTY clients on every path."""
        if self.closed:
            return
        self.closed = True
        self.command("kill-server")
        for client in self.clients:
            try:
                if client.process.poll() is None:
                    client.process.kill()
                client.process.wait(timeout=_TIMEOUT_SECONDS)
            finally:
                with suppress(OSError):
                    os.close(client.master_fd)
        self.clients.clear()


def _executable_name(command: str) -> str:
    """Normalize POSIX and MSYS executable spellings for comparison."""
    executable = command.split(maxsplit=1)[0].replace("\\", "/")
    return executable.rsplit("/", maxsplit=1)[-1].lstrip("-").removesuffix(".exe")


def _tmux_default_command_surfaces() -> tuple[str, ...]:
    """Return every live tmux default-shell/default-command configuration line."""
    return tuple(
        stripped
        for line in TMUX_CONFIG.read_text().splitlines()
        if not (stripped := line.strip()).startswith("#")
        and ("default-shell" in stripped or "default-command" in stripped)
    )


def _render_wezterm(tmp_path: Path) -> str:
    """Render the real template with minimal non-secret ChezMoi data."""
    chezmoi = shutil.which("chezmoi")
    if chezmoi is None:
        raise AssertionError("chezmoi is required to render the WezTerm regression")
    config = tmp_path / "chezmoi.toml"
    config.write_text('[data]\ndefault_shell = "xonsh"\nwsl_distro = "Ubuntu"\n')
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [
            chezmoi,
            "--config",
            str(config),
            "--source",
            str(REPO_ROOT),
            "--destination",
            str(home),
            "execute-template",
            "--file",
            str(WEZTERM_TEMPLATE),
        ],
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"could not render {WEZTERM_TEMPLATE}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout


def _rendered_default_programs(rendered_wezterm: str) -> tuple[str, ...]:
    """Collect every rendered WezTerm ``default_prog`` expression."""
    programs: list[str] = []
    lines = iter(rendered_wezterm.splitlines())
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("--") or not stripped.startswith(
            "config.default_prog ="
        ):
            continue
        if stripped.endswith("}"):
            programs.append(stripped)
            continue

        expression = [stripped]
        for continuation in lines:
            continuation = continuation.strip()
            expression.append(continuation)
            if continuation == "}":
                break
        else:
            raise AssertionError("unterminated rendered WezTerm default_prog")
        programs.append(" ".join(expression))
    return tuple(programs)


def _rendered_launch_menu_arguments(rendered_wezterm: str) -> tuple[str, ...]:
    """Collect every single-line ``args`` expression in rendered launch menus."""
    arguments: list[str] = []
    in_launch_menu = False
    for line in rendered_wezterm.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if stripped == "config.launch_menu = {":
            assert not in_launch_menu, "nested rendered WezTerm launch menu"
            in_launch_menu = True
            continue
        if not in_launch_menu:
            continue
        if stripped == "}":
            in_launch_menu = False
            continue
        if stripped.startswith("args ="):
            assert stripped.startswith("args = {") and stripped.endswith("},"), (
                "rendered WezTerm launch-menu args must remain one command surface: "
                f"{stripped!r}"
            )
            arguments.append(stripped)
    assert not in_launch_menu, "unterminated rendered WezTerm launch menu"
    return tuple(arguments)


def test_tmux_and_rendered_wezterm_commands_match_explicit_allowlist(
    tmp_path: Path,
) -> None:
    """Only approved direct-shell command surfaces can reach new panes/tabs."""
    assert _tmux_default_command_surfaces() == _EXPECTED_TMUX_DEFAULT_COMMAND_SURFACES

    rendered = _render_wezterm(tmp_path)
    assert 'local shell = firstFoundPathFor("xonsh", myPaths)' in rendered
    assert 'or firstFoundPathFor("zsh", myPaths)' in rendered
    assert 'or firstFoundPathFor("bash", myPaths)' in rendered
    rendered_command_surfaces = (
        *_rendered_default_programs(rendered),
        *_rendered_launch_menu_arguments(rendered),
    )
    assert rendered_command_surfaces == _EXPECTED_RENDERED_COMMAND_SURFACES
    assert set(rendered_command_surfaces).isdisjoint(
        _FORBIDDEN_ACCOUNT_LOGIN_COMMAND_SURFACES
    )
    assert set(_SHELL_LOGIN_COMMAND_SURFACES).issubset(rendered_command_surfaces)


@pytest.mark.slow
def test_managed_tmux_config_resets_stale_login_and_preserves_pane_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source the actual config, then exercise all standard bindings after reattach."""
    monkeypatch.setenv("MAIL", str(tmp_path / "inherited-mailbox"))
    monkeypatch.setenv("MAILCHECK", "0")
    monkeypatch.setenv("MAILPATH", str(tmp_path / "inherited-mailpath"))

    nested_directory = tmp_path / "home" / "nested" / "directory"
    nested_directory.mkdir(parents=True)

    with IsolatedTmuxServer(tmp_path) as server:
        source_pane = server.source_pane()
        server.assert_direct_bash(source_pane, server.pane_path(source_pane), tmp_path)
        startup_output = server.pane_output(source_pane).lower()
        assert "last login" not in startup_output
        assert "you have mail" not in startup_output

        server.send_line(source_pane, f"cd -- {shlex.quote(str(nested_directory))}")
        server.wait_for_pane_path(source_pane, nested_directory)
        server.assert_direct_bash(source_pane, nested_directory, tmp_path)

        # A detached client cannot exercise bindings.  Reattach before opening each
        # destination to prove tmux retains the shell's current directory across it.
        first_client = server.attach()
        server.detach(first_client)
        client = server.attach()
        try:
            for binding_name, key in _BINDINGS:
                destination = server.trigger_binding(client, source_pane, key)
                server.wait_for_pane_path(destination, nested_directory)
                server.assert_direct_bash(destination, nested_directory, tmp_path)
                assert server.pane_path(destination) == nested_directory.resolve(), (
                    f"{binding_name} did not inherit {source_pane}'s current directory"
                )
        finally:
            server.detach(client)
