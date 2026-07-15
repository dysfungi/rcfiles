#!/usr/bin/env -S uv run
"""Reconcile the managed ``Ignored`` field of a Perforce virtual stream.

The project registry owns only the extension exclusions for selected virtual
streams. This command retrieves stream forms through ``p4 -G`` so repeated
fields stay structured as marshalled byte-keyed records, rather than relying on
fragile text-form parsing. Existing stream forms retain every server-owned
field; only ``Ignored`` entries are replaced. A missing stream is initialized
from Perforce's virtual-stream template, while a saved form is identified by
its ``Access`` and ``Update`` fields and must match the declared virtual-stream
identity before it can be updated.

The command intentionally never changes client specifications or stream
bindings. It is safe to run repeatedly: a saved stream with matching desired
exclusions does not submit a form back to Perforce.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from io import BytesIO
import marshal
import re
import subprocess


P4Spec = dict[bytes, bytes]
_IGNORED_KEY = re.compile(rb"^Ignored(?:\d+)?$")


class P4CommandError(RuntimeError):
    """Raised when the P4 command-line client cannot complete a request."""


def child_stream_path(parent_stream: str, child_name: str) -> str:
    """Return a sibling stream path beside ``parent_stream``."""
    if not parent_stream.startswith("//"):
        raise ValueError(f"parent stream must start with '//': {parent_stream!r}")

    parent_parts = parent_stream.removeprefix("//").split("/")
    if len(parent_parts) < 2 or not all(parent_parts):
        raise ValueError(
            f"parent stream must include a depot and name: {parent_stream!r}"
        )
    if not child_name or "/" in child_name:
        raise ValueError(f"child name must be one stream-name segment: {child_name!r}")

    return f"{parent_stream.rsplit('/', 1)[0]}/{child_name}"


def normalize_ignored_extensions(extensions: Iterable[str]) -> list[bytes]:
    """Validate extensions and return their Perforce leading-dot patterns."""
    normalized: list[bytes] = []
    seen: set[bytes] = set()

    for extension in extensions:
        value = extension.strip().lstrip(".")
        if not value:
            raise ValueError("ignored extensions must not be empty or only dots")
        if "/" in value:
            raise ValueError(f"ignored extension must not contain '/': {extension!r}")

        pattern = f".{value}".encode()
        if pattern in seen:
            raise ValueError(f"ignored extensions must be unique: {extension!r}")
        seen.add(pattern)
        normalized.append(pattern)

    if not normalized:
        raise ValueError("at least one ignored extension is required")

    return normalized


def patch_ignored_extensions(
    spec: Mapping[bytes, bytes], ignored_extensions: Iterable[str]
) -> P4Spec:
    """Return ``spec`` with only its marshalled ``Ignored`` entries replaced."""
    patched = {
        key: value for key, value in spec.items() if not _IGNORED_KEY.fullmatch(key)
    }
    for index, pattern in enumerate(normalize_ignored_extensions(ignored_extensions)):
        patched[f"Ignored{index}".encode()] = pattern
    return patched


def is_saved_stream_spec(spec: Mapping[bytes, bytes]) -> bool:
    """Return whether Perforce identified this form as a saved stream spec."""
    return b"Access" in spec and b"Update" in spec


def validate_saved_stream_identity(
    spec: Mapping[bytes, bytes], parent_stream: str
) -> None:
    """Reject saved forms that do not identify the declared virtual stream."""
    stream_type = spec.get(b"Type")
    if stream_type != b"virtual":
        raise ValueError(
            "refusing to update saved stream with "
            f"Type {stream_type!r}; expected b'virtual'"
        )

    expected_parent = parent_stream.encode()
    actual_parent = spec.get(b"Parent")
    if actual_parent != expected_parent:
        raise ValueError(
            "refusing to update saved stream with "
            f"Parent {actual_parent!r}; expected {expected_parent!r}"
        )


def _p4_failure_message(error: subprocess.CalledProcessError) -> str:
    output = error.stderr or error.stdout
    return output.decode(errors="replace").strip() or f"exit status {error.returncode}"


def run_p4_stream(
    port: str, stream_args: list[str], *, input_data: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run a marshalled P4 stream command or raise an actionable error."""
    command = ["p4", "-p", port, "-G", "stream", *stream_args]
    try:
        return subprocess.run(
            command,
            check=True,
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise P4CommandError("p4 is not installed or not on PATH") from error
    except subprocess.CalledProcessError as error:
        raise P4CommandError(
            f"p4 stream command failed ({' '.join(command)}): "
            f"{_p4_failure_message(error)}"
        ) from error


def unmarshal_spec(output: bytes) -> P4Spec:
    """Decode the single marshalled stream form emitted by ``p4 -G``."""
    try:
        stream = BytesIO(output)
        spec = marshal.load(stream)
    except (EOFError, ValueError, TypeError) as error:
        raise P4CommandError("p4 did not return a marshalled stream form") from error

    if stream.read():
        raise P4CommandError(
            "p4 returned multiple marshalled records for one stream form"
        )
    if not isinstance(spec, dict) or not all(
        isinstance(key, bytes) and isinstance(value, bytes)
        for key, value in spec.items()
    ):
        raise P4CommandError("p4 returned a stream form with unexpected field types")

    return spec


def fetch_stream_spec(port: str, stream: str) -> P4Spec:
    """Fetch a saved form or Perforce's unsaved default form for ``stream``."""
    return unmarshal_spec(run_p4_stream(port, ["-o", stream]).stdout)


def virtual_stream_template(port: str, parent_stream: str, stream: str) -> P4Spec:
    """Fetch Perforce's virtual-stream template for a stream that is not saved."""
    return unmarshal_spec(
        run_p4_stream(
            port,
            ["-o", "-t", "virtual", "-P", parent_stream, stream],
        ).stdout
    )


def parse_args() -> argparse.Namespace:
    """Parse declarative virtual-stream settings supplied by chezmoi."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="P4PORT for the stream depot")
    parser.add_argument(
        "--parent-stream",
        required=True,
        help="parent stream used by a new virtual stream",
    )
    parser.add_argument(
        "--child-name",
        required=True,
        help="sibling virtual stream name within the depot",
    )
    parser.add_argument(
        "--ignored-extensions",
        required=True,
        help="comma-separated extensions, with or without leading dots",
    )
    return parser.parse_args()


def main() -> int:
    """Reconcile one virtual stream and report whether Perforce changed."""
    args = parse_args()
    try:
        child_stream = child_stream_path(args.parent_stream, args.child_name)
        ignored_extensions = args.ignored_extensions.split(",")
        current_spec = fetch_stream_spec(args.port, child_stream)
        saved_stream = is_saved_stream_spec(current_spec)
        if saved_stream:
            validate_saved_stream_identity(current_spec, args.parent_stream)
            source_spec = current_spec
        else:
            source_spec = virtual_stream_template(
                args.port, args.parent_stream, child_stream
            )
        desired_spec = patch_ignored_extensions(source_spec, ignored_extensions)

        if saved_stream and desired_spec == source_spec:
            print(f"already up to date, no changes needed: {child_stream}")
            return 0

        run_p4_stream(args.port, ["-i"], input_data=marshal.dumps(desired_spec))
    except (P4CommandError, ValueError) as error:
        raise SystemExit(f"p4-reconcile-virtual-stream: {error}") from error

    print(f"reconciled: {child_stream} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
