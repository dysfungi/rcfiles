"""Opt-in macOS A/B harness for tmux pane-CWD behavior through ``login(1)``.

The managed tmux configuration creates a persistent ``main`` session, so this
module starts an isolated server with only the Darwin pane command and its three
CWD-preserving bindings.  The binding-subset test deliberately duplicates those
lines rather than loading production configuration.

Each experiment has an unguessable tmux socket and inherited run marker.  The
marker is only evidence that ``login -p`` preserved the test state; cleanup never
uses it to authorize process ownership or signals.  Before tmux-owned shutdown,
the context manager snapshots only descendants of its server by PID/PPID topology
with non-environment ``ps`` fields.  After shutdown it inspects only those observed
PIDs, reporting sanitized start-time and executable diagnostics for survivors.  It
asks every pane it has observed to run ``exit``, waits for normal tmux shutdown,
and then calls ``tmux kill-server`` as its only fallback.  It never signals a child
process.

``login -pfl`` is intentionally opt-in because it runs against the real macOS
account and can create account-level mail notices and utmpx records.  Run:
``TMUX_LOGIN_CWD_PROTOTYPE=1 mise x -- uv run --group test pytest
.tests/tmux/test_pane_cwd_darwin.py -v``.  The test emits normalized A/B evidence
before asserting the candidate observations, so a reproduced regression remains
inspectable.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, cast

import pytest

_TIMEOUT_SECONDS = 15
_CLEANUP_GRACE_SECONDS = 2
_POLL_SECONDS = 0.1
_ENVIRONMENT_KEYS = ("PATH", "TERM", "USER", "SHELL")
# macOS login exits its PTY session without a locale; no other inherited values pass through.
_LAUNCH_ENVIRONMENT_KEYS = (*_ENVIRONMENT_KEYS, "HOME", "LANG")
_PROTOTYPE_ENVIRONMENT_VARIABLE = "TMUX_LOGIN_CWD_PROTOTYPE"
_RUN_ID_ENVIRONMENT_VARIABLE = "TMUX_LOGIN_CWD_PROTOTYPE_RUN_ID"
_BINDINGS = (("new-window", b"c"), ("vertical-split", b'"'), ("horizontal-split", b"%"))
_BINDING_CONFIG_LINES = (
    'bind-key c new-window -c "#{pane_current_path}"',
    r'bind-key \" split-window -v -c "#{pane_current_path}"',
    'bind-key % split-window -h -c "#{pane_current_path}"',
)
TMUX = shutil.which("tmux")


def _add_note(error: BaseException, note: str) -> None:
    """Attach cleanup context; all supported Python versions provide ``add_note``."""
    getattr(error, "add_note")(note)


def _minimal_tmux_config(default_command: str) -> str:
    """Return the isolated config whose binding subset is checked below."""
    return "\n".join(
        (
            "set -g default-shell /bin/sh",
            f"set -g default-command {json.dumps(default_command)}",
            *_BINDING_CONFIG_LINES,
            "",
        )
    )


def _integration_skip_reason() -> str | None:
    """Explain why the account-affecting experiment is not being run."""
    if os.environ.get(_PROTOTYPE_ENVIRONMENT_VARIABLE) != "1":
        return (
            f"set {_PROTOTYPE_ENVIRONMENT_VARIABLE}=1 to run this real-account "
            "login -pfl experiment; it can create mail notices and utmpx records. "
            "Command: TMUX_LOGIN_CWD_PROTOTYPE=1 mise x -- uv run --group test "
            "pytest .tests/tmux/test_pane_cwd_darwin.py -v"
        )
    if platform.system() != "Darwin":
        return "tmux/login pane-CWD integration requires macOS"

    missing = [
        command
        for command in ("tmux", "xonsh", "login")
        if shutil.which(command) is None
    ]
    if missing:
        return "tmux/login pane-CWD integration requires PATH commands: " + ", ".join(
            missing
        )
    return None


_INTEGRATION_SKIP_REASON = _integration_skip_reason()


@dataclass(frozen=True)
class PaneMetadata:
    pane_id: str
    pid: int
    current_path: str


@dataclass(frozen=True)
class ProcessSnapshot:
    parent_pid: int
    started: str


@dataclass(frozen=True)
class ResidualProcess:
    pid: int
    started: str
    executable: str


@dataclass(frozen=True)
class BindingResult:
    binding: str
    destination_metadata_matches_source_cwd: bool
    destination_xonsh_cwd_matches_source_cwd: bool


@dataclass(frozen=True)
class ExperimentResult:
    source_xonsh_entered_destination: bool
    source_metadata_matches_xonsh_cwd: bool
    supported_environment_preserved: dict[str, bool]
    marker_reaches_all_xonsh: bool
    bindings: tuple[BindingResult, ...]
    startup_observations: dict[str, bool]

    def normalized(self) -> dict[str, object]:
        """Return reportable evidence without host paths, PIDs, or values."""
        return {
            "source_xonsh_entered_destination": self.source_xonsh_entered_destination,
            "source_metadata_matches_xonsh_cwd": self.source_metadata_matches_xonsh_cwd,
            "supported_environment_preserved": self.supported_environment_preserved,
            "marker_reaches_all_xonsh": self.marker_reaches_all_xonsh,
            "bindings": [result.__dict__ for result in self.bindings],
            "login_startup_observations": self.startup_observations,
        }


class TmuxServer:
    """An isolated tmux server with tmux-owned, exception-safe cleanup."""

    def __init__(
        self, tmp_path: Path, default_command: str, initial_directory: Path
    ) -> None:
        identifier = secrets.token_hex(16)
        self.socket = f"pane-cwd-{identifier}"
        self.session = f"pane-cwd-{identifier}"
        self.config = tmp_path / f"{identifier}.tmux.conf"
        self.run_id = secrets.token_urlsafe(32)
        self._known_panes: set[str] = set()
        self._clients: list[subprocess.Popen[bytes]] = []
        self._closed = False
        try:
            self._write_config(default_command)
            self._run(
                "new-session",
                "-d",
                "-x",
                "240",
                "-y",
                "80",
                "-s",
                self.session,
                "-c",
                str(initial_directory.resolve()),
            )
        except BaseException as creation_error:
            cleanup_error = self._close_after_failed_creation()
            if cleanup_error is not None:
                _add_note(
                    creation_error,
                    f"tmux cleanup after partial creation also failed: {cleanup_error}",
                )
            raise

    def __enter__(self) -> TmuxServer:
        return self

    def __exit__(
        self, exc_type: object, exc_value: BaseException | None, _: object
    ) -> Literal[False]:
        try:
            self.close()
        except Exception as cleanup_error:
            if exc_value is None:
                raise
            _add_note(exc_value, f"tmux cleanup also failed: {cleanup_error}")
        return False

    def _close_after_failed_creation(self) -> BaseException | None:
        """Attempt cleanup without replacing the startup failure."""
        try:
            self.close()
        except BaseException as cleanup_error:
            return cleanup_error
        return None

    def _write_config(self, default_command: str) -> None:
        """Write only the behavior under test, never the managed configuration."""
        self.config.write_text(_minimal_tmux_config(default_command))

    def _environment(self) -> dict[str, str]:
        """Return only the launch variables required by tmux, login, and xonsh."""
        environment = {
            key: value
            for key in _LAUNCH_ENVIRONMENT_KEYS
            if (value := os.environ.get(key)) is not None
        }
        environment[_RUN_ID_ENVIRONMENT_VARIABLE] = self.run_id
        return environment

    def _command(
        self, *args: str, timeout: float = _TIMEOUT_SECONDS
    ) -> subprocess.CompletedProcess[str]:
        tmux = TMUX
        assert tmux is not None, "tmux is required for the opt-in integration test"
        return subprocess.run(
            [tmux, "-L", self.socket, "-f", str(self.config), *args],
            capture_output=True,
            text=True,
            env=self._environment(),
            timeout=timeout,
        )

    def _run(self, *args: str, timeout: float = _TIMEOUT_SECONDS) -> str:
        process = self._command(*args, timeout=timeout)
        assert process.returncode == 0, (
            f"isolated tmux command failed: {args!r}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
        return process.stdout.rstrip("\n")

    def panes(self) -> list[PaneMetadata]:
        output = self._run(
            "list-panes",
            "-a",
            "-F",
            "#{pane_id}\x1f#{pane_pid}\x1f#{pane_current_path}",
        )
        panes = [
            PaneMetadata(pane_id, int(pid), current_path)
            for line in output.splitlines()
            for pane_id, pid, current_path in [line.split("\x1f", maxsplit=2)]
        ]
        self._known_panes.update(pane.pane_id for pane in panes)
        return panes

    def pane(self, pane_id: str) -> PaneMetadata:
        matches = [pane for pane in self.panes() if pane.pane_id == pane_id]
        assert len(matches) == 1, f"could not find isolated tmux pane {pane_id}"
        return matches[0]

    @staticmethod
    def _process_rows() -> dict[int, ProcessSnapshot]:
        """Return process topology and start times without reading environments."""
        process = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,lstart="],
            check=True,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        rows: dict[int, ProcessSnapshot] = {}
        for line in process.stdout.splitlines():
            fields = line.split(maxsplit=6)
            if len(fields) != 7:
                continue
            pid, parent_pid = fields[:2]
            rows[int(pid)] = ProcessSnapshot(int(parent_pid), " ".join(fields[2:]))
        return rows

    @staticmethod
    def _descendant_pids(root_pid: int, rows: dict[int, ProcessSnapshot]) -> set[int]:
        """Return descendants of ``root_pid`` from the supplied PID/PPID topology."""
        descendants: set[int] = set()
        pending = [root_pid]
        while pending:
            parent_pid = pending.pop()
            children = [
                pid
                for pid, snapshot in rows.items()
                if snapshot.parent_pid == parent_pid and pid not in descendants
            ]
            descendants.update(children)
            pending.extend(children)
        return descendants

    @staticmethod
    def _process_commands(pids: set[int]) -> dict[int, str]:
        """Return executable names only for already-scoped PIDs."""
        if not pids:
            return {}
        process = subprocess.run(
            [
                "ps",
                "-p",
                ",".join(str(pid) for pid in sorted(pids)),
                "-o",
                "pid=,comm=",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        commands: dict[int, str] = {}
        for line in process.stdout.splitlines():
            fields = line.split(maxsplit=1)
            if len(fields) == 2:
                pid, command = fields
                commands[int(pid)] = command
        return commands

    @staticmethod
    def _command_name(command: str) -> str:
        executable, *_ = command.split(maxsplit=1)
        return Path(executable).name.lstrip("-")

    def wait_for_xonsh(self, pane_id: str) -> None:
        """Wait until login has selected the configured interactive xonsh shell."""

        def has_xonsh() -> bool:
            pane = self.pane(pane_id)
            rows = self._process_rows()
            pane_processes = {pane.pid, *self._descendant_pids(pane.pid, rows)}
            return any(
                self._command_name(command) == "xonsh"
                for command in self._process_commands(pane_processes).values()
            )

        self._wait_for(has_xonsh, f"xonsh child for pane {pane_id}")

    def wait_for_pane_current_path(
        self, pane_id: str, expected_directory: str | Path
    ) -> tuple[PaneMetadata, bool]:
        """Poll until tmux metadata catches up, retaining a negative observation."""
        deadline = time.monotonic() + _TIMEOUT_SECONDS
        pane = self.pane(pane_id)
        while time.monotonic() < deadline:
            pane = self.pane(pane_id)
            if self._same_path(pane.current_path, expected_directory):
                return pane, True
            time.sleep(_POLL_SECONDS)
        return self.pane(pane_id), False

    def send_xonsh(self, pane_id: str, command: str) -> None:
        self._run("send-keys", "-t", pane_id, "-l", command)
        self._run("send-keys", "-t", pane_id, "Enter")

    def _probe_xonsh(self, pane_id: str, suffix: str, expression: str) -> str:
        probe = self.config.parent / f"{uuid.uuid4().hex}.{suffix}"
        self.send_xonsh(pane_id, f"open({str(probe)!r}, 'w').write({expression})")
        self._wait_for(probe.exists, f"{suffix} probe from pane {pane_id}")
        return probe.read_text()

    def xonsh_cwd(self, pane_id: str) -> str:
        return self._probe_xonsh(pane_id, "cwd", "__import__('os').getcwd()")

    def xonsh_environment(self, pane_id: str) -> dict[str, str | None]:
        encoded = self._probe_xonsh(
            pane_id,
            "json",
            "__import__('json').dumps({key: __import__('os').environ.get(key) "
            f"for key in {_ENVIRONMENT_KEYS!r}}}, sort_keys=True)",
        )
        environment = json.loads(encoded)
        assert set(environment) == set(_ENVIRONMENT_KEYS)
        return environment

    def xonsh_run_id(self, pane_id: str) -> str:
        return self._probe_xonsh(
            pane_id,
            "run-id",
            f"__import__('os').environ.get({_RUN_ID_ENVIRONMENT_VARIABLE!r}, '')",
        )

    def startup_observations(self, pane_id: str) -> dict[str, bool]:
        output = self._run("capture-pane", "-p", "-t", pane_id, "-S", "-200").lower()
        return {
            "last_login_text": "last login" in output,
            "mail_notice_text": "mail" in output,
        }

    def trigger_binding(self, source_pane: str, key: bytes) -> str:
        """Attach a ready client and press prefix+key to execute its binding."""
        import pty

        before = {pane.pane_id for pane in self.panes()}
        self._run("select-window", "-t", f"{self.session}:0")
        self._run("select-pane", "-t", source_pane)
        tmux = TMUX
        assert tmux is not None
        master, slave = pty.openpty()
        client: subprocess.Popen[bytes] | None = None
        try:
            try:
                client = subprocess.Popen(
                    [
                        tmux,
                        "-L",
                        self.socket,
                        "-f",
                        str(self.config),
                        "attach-session",
                        "-t",
                        self.session,
                    ],
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    env=self._environment(),
                    start_new_session=True,
                )
            finally:
                os.close(slave)

            assert client is not None
            self._clients.append(client)
            self._wait_for(
                lambda: self._client_is_attached(client),
                f"tmux client {client.pid} attachment",
            )
            os.write(master, b"\x02" + key)
            self._wait_for(
                lambda: len({pane.pane_id for pane in self.panes()} - before) == 1,
                key.decode(),
            )
            return next(iter({pane.pane_id for pane in self.panes()} - before))
        finally:
            os.close(master)

    def _client_is_attached(self, client: subprocess.Popen[bytes]) -> bool:
        assert client.poll() is None, "tmux client exited before attaching"
        client_pids = self._run("list-clients", "-F", "#{client_pid}").splitlines()
        return str(client.pid) in client_pids

    def _wait_for(self, predicate: Callable[[], bool], description: str) -> None:
        deadline = time.monotonic() + _TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(_POLL_SECONDS)
        raise AssertionError(f"timed out waiting for {description}")

    @staticmethod
    def _same_path(left: str | Path, right: str | Path) -> bool:
        return Path(left).resolve() == Path(right).resolve()

    def _pane_exists(self, pane_id: str) -> bool:
        return (
            self._command(
                "display-message", "-p", "-t", pane_id, "#{pane_id}"
            ).returncode
            == 0
        )

    def _request_known_pane_exit(self) -> list[str]:
        """Ask every observed pane to exit; vanished panes need no further action."""
        errors: list[str] = []
        try:
            self.panes()
        except Exception as error:
            errors.append(f"could not enumerate panes for graceful exit: {error}")

        for pane_id in sorted(self._known_panes):
            if not self._pane_exists(pane_id):
                continue
            for args in (("-l", "exit"), ("Enter",)):
                result = self._command("send-keys", "-t", pane_id, *args)
                if result.returncode == 0 or not self._pane_exists(pane_id):
                    continue
                errors.append(
                    f"could not send {args!r} to live pane {pane_id}: "
                    f"{result.stderr.strip()}"
                )
                break
        return errors

    def _session_exists(self) -> bool:
        """Return session state, surfacing unexpected tmux/socket failures."""
        result = self._command("has-session", "-t", self.session)
        if result.returncode == 0:
            return True

        stderr = result.stderr.strip()
        if stderr == f"can't find session: {self.session}" or stderr.startswith(
            "no server running on "
        ):
            return False

        raise AssertionError(
            f"tmux has-session failed for {self.session!r} (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def _wait_for_server_exit(self) -> bool:
        """Bound normal-exit wait; pane enumeration also captures late test panes."""
        deadline = time.monotonic() + _CLEANUP_GRACE_SECONDS
        while time.monotonic() < deadline:
            if not self._session_exists():
                return True
            try:
                self.panes()
            except AssertionError:
                pass
            time.sleep(_POLL_SECONDS)
        return not self._session_exists()

    def _kill_server(self) -> str | None:
        """Use tmux's own fallback teardown, tolerating an already-exited server."""
        result = self._command("kill-server")
        if result.returncode != 0 and self._session_exists():
            return result.stderr.strip() or "tmux kill-server failed"
        return None

    @staticmethod
    def _sanitized_executable(command: str) -> str:
        """Return a safe executable label without arguments or process environment."""
        executable = command.split(maxsplit=1)[0] if command else ""
        name = Path(executable).name.lstrip("-")
        return name if name in {"xonsh", "tmux", "login", "sh"} else "<redacted>"

    def _snapshot_server_descendants(self) -> dict[int, ProcessSnapshot]:
        """Capture this server's descendants before shutdown using PID/PPID topology."""
        if not self._session_exists():
            return {}
        server_pid = int(self._run("display-message", "-p", "#{pid}"))
        rows = self._process_rows()
        assert server_pid in rows, (
            f"isolated tmux server PID {server_pid} was not found"
        )
        return {
            pid: rows[pid]
            for pid in self._descendant_pids(server_pid, rows)
            if pid in rows
        }

    def _observed_residuals(
        self, observed: dict[int, ProcessSnapshot]
    ) -> list[ResidualProcess]:
        """Return surviving observed processes with sanitized fields only."""
        if not observed:
            return []
        result = subprocess.run(
            [
                "ps",
                "-p",
                ",".join(str(pid) for pid in sorted(observed)),
                "-o",
                "pid=,lstart=,comm=",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        residuals: list[ResidualProcess] = []
        for line in result.stdout.splitlines():
            fields = line.split(maxsplit=6)
            if len(fields) != 7:
                continue
            pid, weekday, month, day, clock, year, command = fields
            process_id = int(pid)
            started = f"{weekday} {month} {day} {clock} {year}"
            if (
                observed.get(process_id) is None
                or observed[process_id].started != started
            ):
                continue
            residuals.append(
                ResidualProcess(
                    pid=process_id,
                    started=started,
                    executable=self._sanitized_executable(command),
                )
            )
        return residuals

    def _wait_for_observed_residuals(
        self, observed: dict[int, ProcessSnapshot]
    ) -> list[ResidualProcess]:
        deadline = time.monotonic() + _CLEANUP_GRACE_SECONDS
        residuals = self._observed_residuals(observed)
        while residuals and time.monotonic() < deadline:
            time.sleep(_POLL_SECONDS)
            residuals = self._observed_residuals(observed)
        return residuals

    @staticmethod
    def _residual_details(residuals: list[ResidualProcess]) -> str:
        return "; ".join(
            f"PID {item.pid} (started {item.started}, executable {item.executable})"
            for item in residuals
        )

    def _reap_clients(self) -> list[str]:
        """Reap PTY clients after tmux owns their shutdown; never signal them."""
        errors: list[str] = []
        for client in self._clients:
            try:
                client.wait(timeout=_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                errors.append(
                    f"tmux client {client.pid} did not exit after server shutdown"
                )
            except Exception as error:
                errors.append(f"could not reap tmux client {client.pid}: {error}")
        return errors

    def close(self) -> None:
        """Exit known panes, wait, kill the server, then report—not kill—residuals."""
        if self._closed:
            return
        self._closed = True
        errors: list[str] = []
        observed: dict[int, ProcessSnapshot] = {}

        try:
            observed = self._snapshot_server_descendants()
        except Exception as error:
            errors.append(f"failed to snapshot isolated tmux descendants: {error}")
        try:
            errors.extend(self._request_known_pane_exit())
        except Exception as error:
            errors.append(f"pane-exit request failed: {error}")
        try:
            self._wait_for_server_exit()
        except Exception as error:
            errors.append(f"pane-exit wait failed: {error}")
        try:
            kill_error = self._kill_server()
            if kill_error is not None:
                errors.append(kill_error)
        except Exception as error:
            errors.append(f"failed to kill isolated tmux server: {error}")
        try:
            if not self._wait_for_server_exit():
                errors.append("tmux server remained after kill-server")
        except Exception as error:
            errors.append(f"post-kill server wait failed: {error}")
        try:
            errors.extend(self._reap_clients())
        except Exception as error:
            errors.append(f"failed to reap tmux clients: {error}")
        try:
            residuals = self._wait_for_observed_residuals(observed)
            if residuals:
                errors.append(
                    "observed tmux descendants survived tmux shutdown: "
                    + self._residual_details(residuals)
                )
        except Exception as error:
            errors.append(f"failed to inspect observed tmux descendants: {error}")

        if errors:
            raise AssertionError("isolated tmux cleanup failed: " + "; ".join(errors))


def _supported_environment_snapshot() -> dict[str, str | None]:
    """Capture the supported login environment before any tmux process launches."""
    return {key: os.environ.get(key) for key in _ENVIRONMENT_KEYS}


def _run_experiment(
    tmp_path: Path, default_command: str, expected_environment: dict[str, str | None]
) -> ExperimentResult:
    tmp_path.mkdir(parents=True, exist_ok=True)
    initial_directory = tmp_path / "initial"
    destination_directory = tmp_path / "destination"
    initial_directory.mkdir()
    destination_directory.mkdir()
    with TmuxServer(tmp_path, default_command, initial_directory) as server:
        source = server.panes()[0].pane_id
        server.wait_for_xonsh(source)
        startup_observations = server.startup_observations(source)
        server.send_xonsh(source, f"cd {str(destination_directory)!r}")
        source_cwd = server.xonsh_cwd(source)
        source_entered_destination = server._same_path(
            source_cwd, destination_directory
        )
        _, source_metadata_matches_xonsh_cwd = server.wait_for_pane_current_path(
            source, source_cwd
        )
        source_environment = server.xonsh_environment(source)
        supported_environment_preserved = {
            key: source_environment[key] == expected_environment[key]
            for key in _ENVIRONMENT_KEYS
        }
        marker_reaches_all_xonsh = server.xonsh_run_id(source) == server.run_id

        bindings: list[BindingResult] = []
        for binding, key in _BINDINGS:
            destination = server.trigger_binding(source, key)
            server.wait_for_xonsh(destination)
            _, metadata_matches_source_cwd = server.wait_for_pane_current_path(
                destination, source_cwd
            )
            destination_cwd = server.xonsh_cwd(destination)
            marker_reaches_all_xonsh &= (
                server.xonsh_run_id(destination) == server.run_id
            )
            bindings.append(
                BindingResult(
                    binding=binding,
                    destination_metadata_matches_source_cwd=metadata_matches_source_cwd,
                    destination_xonsh_cwd_matches_source_cwd=server._same_path(
                        destination_cwd, source_cwd
                    ),
                )
            )

        return ExperimentResult(
            source_xonsh_entered_destination=source_entered_destination,
            source_metadata_matches_xonsh_cwd=source_metadata_matches_xonsh_cwd,
            supported_environment_preserved=supported_environment_preserved,
            marker_reaches_all_xonsh=marker_reaches_all_xonsh,
            bindings=tuple(bindings),
            startup_observations=startup_observations,
        )


def test_minimal_binding_subset_matches_production_config() -> None:
    """Keep isolated bindings aligned without sourcing the persistent config."""
    production_config = Path(__file__).parents[2] / "dot_config/tmux/tmux.conf"
    production_lines = production_config.read_text().splitlines()

    assert [line for line in production_lines if line in _BINDING_CONFIG_LINES] == list(
        _BINDING_CONFIG_LINES
    )
    assert _minimal_tmux_config("exec sleep 60").splitlines()[2:] == list(
        _BINDING_CONFIG_LINES
    )


def test_environment_is_allowlisted_and_residual_labels_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep tmux environments and residual diagnostics free of inherited secrets."""
    server = object.__new__(TmuxServer)
    server.run_id = "test-marker"
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-reach-tmux")

    environment = server._environment()

    assert set(environment) == {
        _RUN_ID_ENVIRONMENT_VARIABLE,
        *(key for key in _LAUNCH_ENVIRONMENT_KEYS if os.environ.get(key) is not None),
    }
    assert "UNRELATED_SECRET" not in environment
    assert TmuxServer._sanitized_executable("/bin/xonsh SECRET=value") == "xonsh"
    assert TmuxServer._sanitized_executable("SECRET=value /bin/xonsh") == "<redacted>"


def test_constructor_preserves_startup_error_and_notes_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Partial creation cleanup augments rather than replaces the startup failure."""
    startup_error = RuntimeError("tmux startup failed")
    cleanup_error = AssertionError("tmux cleanup failed")

    def fail_startup(_: TmuxServer, _default_command: str) -> None:
        raise startup_error

    def fail_cleanup(_: TmuxServer) -> None:
        raise cleanup_error

    monkeypatch.setattr(TmuxServer, "_write_config", fail_startup)
    monkeypatch.setattr(TmuxServer, "close", fail_cleanup)

    with pytest.raises(RuntimeError, match="tmux startup failed") as raised:
        TmuxServer(tmp_path, "exec xonsh", tmp_path)

    assert raised.value is startup_error
    assert raised.value.__notes__ == [
        "tmux cleanup after partial creation also failed: tmux cleanup failed"
    ]


@pytest.mark.parametrize(
    ("command", "expected"),
    (
        ("/opt/homebrew/bin/xonsh -i", "xonsh"),
        ("-xonsh", "xonsh"),
        ("/bin/sh -c 'exec xonsh'", "sh"),
    ),
)
def test_command_name_uses_the_executable_not_arguments(
    command: str, expected: str
) -> None:
    """Readiness treats only an executable named xonsh as the interactive shell."""
    assert TmuxServer._command_name(command) == expected


@pytest.mark.parametrize(
    ("returncode", "stderr", "expected"),
    (
        (0, "", True),
        (1, "can't find session: test-session", False),
        (1, "no server running on /tmp/tmux-501/test-socket", False),
    ),
)
def test_session_exists_recognizes_only_expected_absence(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stderr: str, expected: bool
) -> None:
    """Expected tmux absence is distinct from an arbitrary failed has-session call."""
    server = object.__new__(TmuxServer)
    server.session = "test-session"

    monkeypatch.setattr(
        server,
        "_command",
        lambda *_: subprocess.CompletedProcess([], returncode, "", stderr),
    )

    assert server._session_exists() is expected


def test_session_exists_surfaces_tmux_socket_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup records has-session failures instead of treating them as absence."""
    server = object.__new__(TmuxServer)
    server.session = "test-session"
    monkeypatch.setattr(
        server,
        "_command",
        lambda *_: subprocess.CompletedProcess(
            [], 1, "", "error connecting to /tmp/tmux-501/test-socket"
        ),
    )

    with pytest.raises(AssertionError, match="tmux has-session failed"):
        server._session_exists()


def test_close_reports_has_session_failures_in_cleanup_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed session probe remains visible in aggregated cleanup diagnostics."""
    server = object.__new__(TmuxServer)
    server._closed = False
    session_error = AssertionError("tmux has-session failed for 'test-session'")

    def fail_session_wait() -> bool:
        raise session_error

    monkeypatch.setattr(server, "_snapshot_server_descendants", lambda: {})
    monkeypatch.setattr(server, "_request_known_pane_exit", lambda: [])
    monkeypatch.setattr(server, "_wait_for_server_exit", fail_session_wait)
    monkeypatch.setattr(server, "_kill_server", lambda: None)
    monkeypatch.setattr(server, "_reap_clients", lambda: [])
    monkeypatch.setattr(server, "_wait_for_observed_residuals", lambda _: [])

    with pytest.raises(
        AssertionError, match="pane-exit wait failed: tmux has-session failed"
    ):
        server.close()


def test_process_topology_uses_no_environment_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The server-descendant snapshot reads PID topology, never environments."""
    calls: list[list[str]] = []
    output = "101 100 Mon Jul 11 12:00:00 2026\n"

    def process_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(subprocess, "run", process_run)

    assert TmuxServer._process_rows() == {
        101: ProcessSnapshot(100, "Mon Jul 11 12:00:00 2026")
    }
    assert calls == [["ps", "-axo", "pid=,ppid=,lstart="]]


def test_snapshot_server_descendants_uses_pid_ppid_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the isolated server's descendants become residual candidates."""
    server = object.__new__(TmuxServer)
    snapshots = {
        10: ProcessSnapshot(1, "Mon Jul 11 12:00:00 2026"),
        11: ProcessSnapshot(10, "Mon Jul 11 12:00:01 2026"),
        12: ProcessSnapshot(11, "Mon Jul 11 12:00:02 2026"),
        13: ProcessSnapshot(1, "Mon Jul 11 12:00:03 2026"),
    }
    monkeypatch.setattr(server, "_session_exists", lambda: True)
    monkeypatch.setattr(server, "_run", lambda *_: "10")
    monkeypatch.setattr(server, "_process_rows", lambda: snapshots)

    assert server._snapshot_server_descendants() == {
        11: snapshots[11],
        12: snapshots[12],
    }


def test_observed_residuals_include_full_start_year_and_query_only_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-shutdown inspection is PID-scoped and ignores a reused PID."""
    server = object.__new__(TmuxServer)
    observed = {
        101: ProcessSnapshot(100, "Mon Jul 11 12:00:00 2026"),
        102: ProcessSnapshot(100, "Mon Jul 11 12:00:01 2026"),
    }
    calls: list[list[str]] = []
    output = (
        "101 Mon Jul 11 12:00:00 2026 /bin/xonsh\n"
        "102 Mon Jul 11 12:00:02 2026 /bin/sh\n"
    )

    def process_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(subprocess, "run", process_run)

    assert server._observed_residuals(observed) == [
        ResidualProcess(101, "Mon Jul 11 12:00:00 2026", "xonsh")
    ]
    assert calls == [["ps", "-p", "101,102", "-o", "pid=,lstart=,comm="]]


def test_close_exits_known_panes_before_tmux_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup is pane exit, bounded wait, and tmux kill-server—never PID signals."""
    server = object.__new__(TmuxServer)
    server._closed = False
    events: list[str] = []

    def snapshot_descendants() -> dict[int, ProcessSnapshot]:
        events.append("snapshot")
        return {}

    def request_exit() -> list[str]:
        events.append("exit")
        return []

    def wait_for_exit() -> bool:
        events.append("wait")
        return True

    def kill_server() -> None:
        events.append("kill")

    def reap_clients() -> list[str]:
        events.append("reap")
        return []

    monkeypatch.setattr(server, "_snapshot_server_descendants", snapshot_descendants)
    monkeypatch.setattr(server, "_request_known_pane_exit", request_exit)
    monkeypatch.setattr(server, "_wait_for_server_exit", wait_for_exit)
    monkeypatch.setattr(server, "_kill_server", kill_server)
    monkeypatch.setattr(server, "_reap_clients", reap_clients)
    monkeypatch.setattr(server, "_wait_for_observed_residuals", lambda _: [])

    server.close()

    assert events == ["snapshot", "exit", "wait", "kill", "wait", "reap"]


@pytest.mark.parametrize("exception_type", (KeyboardInterrupt, SystemExit))
def test_close_does_not_aggregate_control_flow_exceptions(
    monkeypatch: pytest.MonkeyPatch, exception_type: type[BaseException]
) -> None:
    """Keep process control flow distinct from ordinary cleanup assertion failures."""
    server = object.__new__(TmuxServer)
    server._closed = False

    def interrupt_cleanup() -> list[str]:
        raise exception_type

    monkeypatch.setattr(server, "_request_known_pane_exit", interrupt_cleanup)

    with pytest.raises(exception_type):
        server.close()


def test_reap_clients_waits_after_tmux_shutdown() -> None:
    """PTY clients stay server-owned until tmux shutdown makes them reapable."""

    class Client:
        pid = 101

        def __init__(self) -> None:
            self.wait_calls = 0

        def wait(self, timeout: float) -> int:
            assert timeout == _TIMEOUT_SECONDS
            self.wait_calls += 1
            return 0

    server = object.__new__(TmuxServer)
    client = Client()
    server._clients = [cast(subprocess.Popen[bytes], client)]

    assert server._reap_clients() == []
    assert client.wait_calls == 1


def test_close_reports_residual_details_without_signalling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A survivor is an actionable cleanup failure, never a manual-kill target."""
    server = object.__new__(TmuxServer)
    server._closed = False
    residual = ResidualProcess(101, "Mon Jul 11 12:00:00 2026", "xonsh")

    monkeypatch.setattr(
        server,
        "_snapshot_server_descendants",
        lambda: {101: ProcessSnapshot(100, "Mon Jul 11 12:00:00 2026")},
    )
    monkeypatch.setattr(server, "_request_known_pane_exit", lambda: [])
    monkeypatch.setattr(server, "_wait_for_server_exit", lambda: True)
    monkeypatch.setattr(server, "_kill_server", lambda: None)
    monkeypatch.setattr(server, "_reap_clients", lambda: [])
    monkeypatch.setattr(server, "_wait_for_observed_residuals", lambda _: [residual])

    with pytest.raises(
        AssertionError, match=r"PID 101 .*started Mon Jul 11.*executable xonsh"
    ):
        server.close()


def _emit_experiment_evidence(
    name: str,
    result: ExperimentResult,
    capsys: pytest.CaptureFixture[str],
    record_property: pytest.RecordProperty,
) -> None:
    """Publish sanitized evidence immediately so a later experiment cannot erase it."""
    evidence = json.dumps(result.normalized(), sort_keys=True)
    record_property(f"tmux_login_cwd_prototype_{name}", evidence)
    with capsys.disabled():
        print(f"tmux-login-cwd prototype {name}: {evidence}")


@pytest.mark.skipif(
    _INTEGRATION_SKIP_REASON is not None, reason=_INTEGRATION_SKIP_REASON or ""
)
def test_login_exec_ab_records_prototype_observation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    record_property: pytest.RecordProperty,
) -> None:
    """Record per-variant evidence before asserting pane-CWD behavior for both variants."""
    expected_environment = _supported_environment_snapshot()
    baseline = _run_experiment(
        tmp_path / "exec-login", 'exec login -pfl "$USER"', expected_environment
    )
    _emit_experiment_evidence("exec_login", baseline, capsys, record_property)
    candidate = _run_experiment(
        tmp_path / "no-exec-login", 'login -pfl "$USER"', expected_environment
    )
    _emit_experiment_evidence("no_exec_login", candidate, capsys, record_property)

    complete_evidence = {
        "exec_login": baseline.normalized(),
        "no_exec_login": candidate.normalized(),
    }
    record_property(
        "tmux_login_cwd_prototype", json.dumps(complete_evidence, sort_keys=True)
    )

    for name, result in (("exec_login", baseline), ("no_exec_login", candidate)):
        missing_environment = [
            key
            for key, preserved in result.supported_environment_preserved.items()
            if not preserved
        ]
        assert not missing_environment, (
            f"{name} did not preserve expected supported environment keys: "
            + ", ".join(missing_environment)
        )
        assert result.marker_reaches_all_xonsh, (
            "login -p did not preserve the diagnostic run marker in every xonsh pane"
        )
        assert result.source_xonsh_entered_destination, (
            "source xonsh did not enter its requested destination directory"
        )
        assert result.source_metadata_matches_xonsh_cwd, (
            "source pane_current_path did not catch up with xonsh's cwd"
        )
        assert [binding.binding for binding in result.bindings] == [
            name for name, _ in _BINDINGS
        ]
        assert all(
            binding.destination_metadata_matches_source_cwd
            and binding.destination_xonsh_cwd_matches_source_cwd
            for binding in result.bindings
        ), "a destination pane did not inherit the intended source cwd"
