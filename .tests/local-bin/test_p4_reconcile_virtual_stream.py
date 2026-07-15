"""Regression tests for P4 virtual-stream reconciliation.

A stubbed ``p4 -G stream`` process keeps the tests independent of a P4 server
while exercising the same marshalled forms and command paths used in production.
"""

from __future__ import annotations

import importlib.util
import marshal
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dot_local" / "bin" / "executable_p4-reconcile-virtual-stream.py"
P4_PORT = "uegames.p4.riotgames.io:1666"
PARENT_STREAM = "//flyingfox/dev-main"
CHILD_NAME = "dfrank-dev-main-mac"
CHILD_STREAM = "//flyingfox/dfrank-dev-main-mac"

_spec = importlib.util.spec_from_file_location("p4_reconcile_virtual_stream", SCRIPT)
assert _spec and _spec.loader
_module = importlib.util.module_from_spec(_spec)
sys.modules["p4_reconcile_virtual_stream"] = _module
_spec.loader.exec_module(_module)

child_stream_path = _module.child_stream_path
main = _module.main
patch_ignored_extensions = _module.patch_ignored_extensions


_SAVED_STREAM_SPEC = {
    b"code": b"stat",
    b"Stream": CHILD_STREAM.encode(),
    b"Update": b"2026/07/14 18:49:29",
    b"Access": b"2026/07/14 18:49:29",
    b"Owner": b"dfrank",
    b"Name": CHILD_NAME.encode(),
    b"Parent": PARENT_STREAM.encode(),
    b"Type": b"virtual",
    b"Description": b"Created by dfrank.\n",
    b"Options": b"allsubmit unlocked notoparent nofromparent mergedown",
    b"ParentView": b"inherit",
    b"Paths0": b"share ...",
    b"Ignored0": b".stale",
    b"Ignored1": b".obsolete",
    b"Ignored2": b".orphaned",
    b"baseParent": PARENT_STREAM.encode(),
    b"streamSpecDigest": b"D946BC575993355DE2D05CB751DF2FB8",
}


def _install_fake_p4(
    monkeypatch: pytest.MonkeyPatch,
    read_responses: list[tuple[list[str], dict[bytes, bytes]]],
) -> tuple[
    list[tuple[list[str], dict[str, object]]],
    list[tuple[list[str], dict[bytes, bytes]]],
]:
    calls: list[tuple[list[str], dict[str, object]]] = []
    remaining_responses = list(read_responses)

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        assert command[:5] == ["p4", "-p", P4_PORT, "-G", "stream"]
        stream_args = command[5:]
        if stream_args == ["-i"]:
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        if not remaining_responses:
            raise AssertionError(f"unexpected p4 stream command: {stream_args!r}")
        expected_args, response = remaining_responses.pop(0)
        assert stream_args == expected_args
        return subprocess.CompletedProcess(
            command, 0, stdout=marshal.dumps(response), stderr=b""
        )

    monkeypatch.setattr(_module.subprocess, "run", fake_run)
    return calls, remaining_responses


def _run_main(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--port",
            P4_PORT,
            "--parent-stream",
            PARENT_STREAM,
            "--child-name",
            CHILD_NAME,
            "--ignored-extensions",
            "psd,uasset",
        ],
    )
    return main()


def test_patch_replaces_only_ignored_entries() -> None:
    """A changed exclusion list preserves every server-owned stream field."""
    expected = {
        **{
            key: value
            for key, value in _SAVED_STREAM_SPEC.items()
            if not key.startswith(b"Ignored")
        },
        b"Ignored0": b".psd",
        b"Ignored1": b".uasset",
    }

    assert patch_ignored_extensions(_SAVED_STREAM_SPEC, ["psd", ".uasset"]) == expected


def test_patch_is_identical_when_ignored_entries_match() -> None:
    """A matching exclusion list retains the existing marshalled form exactly."""
    spec = {
        **{
            key: value
            for key, value in _SAVED_STREAM_SPEC.items()
            if key != b"Ignored2"
        },
        b"Ignored0": b".psd",
        b"Ignored1": b".uasset",
    }

    assert patch_ignored_extensions(spec, ["psd", "uasset"]) == spec


def test_saved_matching_stream_skips_p4_stream_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A saved matching stream avoids an unnecessary server-side write."""
    matching_spec = {
        **{
            key: value
            for key, value in _SAVED_STREAM_SPEC.items()
            if key != b"Ignored2"
        },
        b"Ignored0": b".psd",
        b"Ignored1": b".uasset",
    }
    calls, remaining_responses = _install_fake_p4(
        monkeypatch, [(["-o", CHILD_STREAM], matching_spec)]
    )

    assert _run_main(monkeypatch) == 0

    assert not remaining_responses
    assert [command[5:] for command, _ in calls] == [["-o", CHILD_STREAM]]
    assert capsys.readouterr().out == (
        f"already up to date, no changes needed: {CHILD_STREAM}\n"
    )


def test_saved_changed_stream_submits_patched_marshalled_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A saved changed stream submits only the desired ignored-extension patch."""
    calls, remaining_responses = _install_fake_p4(
        monkeypatch, [(["-o", CHILD_STREAM], _SAVED_STREAM_SPEC)]
    )

    assert _run_main(monkeypatch) == 0

    assert not remaining_responses
    assert [command[5:] for command, _ in calls] == [
        ["-o", CHILD_STREAM],
        ["-i"],
    ]
    submitted_form = calls[-1][1]["input"]
    assert isinstance(submitted_form, bytes)
    assert marshal.loads(submitted_form) == {
        **{
            key: value
            for key, value in _SAVED_STREAM_SPEC.items()
            if not key.startswith(b"Ignored")
        },
        b"Ignored0": b".psd",
        b"Ignored1": b".uasset",
    }


def test_missing_stream_submits_virtual_stream_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsaved stream is created even when its template already matches."""
    unsaved_form = {b"Stream": CHILD_STREAM.encode()}
    virtual_template = {
        b"Stream": CHILD_STREAM.encode(),
        b"Parent": PARENT_STREAM.encode(),
        b"Type": b"virtual",
        b"Paths0": b"share ...",
        b"Ignored0": b".psd",
        b"Ignored1": b".uasset",
    }
    calls, remaining_responses = _install_fake_p4(
        monkeypatch,
        [
            (["-o", CHILD_STREAM], unsaved_form),
            (
                ["-o", "-t", "virtual", "-P", PARENT_STREAM, CHILD_STREAM],
                virtual_template,
            ),
        ],
    )

    assert _run_main(monkeypatch) == 0

    assert not remaining_responses
    assert [command[5:] for command, _ in calls] == [
        ["-o", CHILD_STREAM],
        ["-o", "-t", "virtual", "-P", PARENT_STREAM, CHILD_STREAM],
        ["-i"],
    ]
    submitted_form = calls[-1][1]["input"]
    assert isinstance(submitted_form, bytes)
    assert marshal.loads(submitted_form) == virtual_template


@pytest.mark.parametrize(
    ("field", "unexpected_value", "expected_error"),
    [
        (b"Type", b"development", "Type b'development'; expected b'virtual'"),
        (
            b"Parent",
            b"//flyingfox/other-dev-main",
            "Parent b'//flyingfox/other-dev-main'; expected b'//flyingfox/dev-main'",
        ),
    ],
    ids=["saved-non-virtual-type", "saved-wrong-parent"],
)
def test_saved_stream_with_wrong_identity_fails_without_submit(
    monkeypatch: pytest.MonkeyPatch,
    field: bytes,
    unexpected_value: bytes,
    expected_error: str,
) -> None:
    """A saved form with a different identity must never be rewritten."""
    invalid_spec = {**_SAVED_STREAM_SPEC, field: unexpected_value}
    calls, remaining_responses = _install_fake_p4(
        monkeypatch, [(["-o", CHILD_STREAM], invalid_spec)]
    )

    with pytest.raises(SystemExit) as error:
        _run_main(monkeypatch)

    assert (
        error.value.code
        == f"p4-reconcile-virtual-stream: refusing to update saved stream with {expected_error}"
    )
    assert not remaining_responses
    assert [command[5:] for command, _ in calls] == [["-o", CHILD_STREAM]]


@pytest.mark.parametrize(
    ("parent_stream", "child_name", "expected_stream"),
    [
        (
            "//flyingfox/dev-main",
            "dfrank-dev-main-mac",
            "//flyingfox/dfrank-dev-main-mac",
        ),
        (
            "//flyingfox/team/dev-main",
            "dfrank-dev-main-mac",
            "//flyingfox/team/dfrank-dev-main-mac",
        ),
    ],
    ids=["top-level-parent", "nested-parent"],
)
def test_child_stream_path_preserves_parent_depot_path(
    parent_stream: str, child_name: str, expected_stream: str
) -> None:
    """Virtual children remain siblings of their parent at any nesting depth."""
    assert child_stream_path(parent_stream, child_name) == expected_stream
