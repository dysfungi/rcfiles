#!/usr/bin/env -S uv run --no-project
"""Synchronize a configured Perforce project without selected binary assets.

A Perforce stream client's View is server-owned, so exclusion rules cannot be
persisted locally by changing that View. Each invocation instead asks Perforce
for a dry-run of the configured stream root, removes paths whose final extension
is in the selected exclusion list, and supplies the retained bare depot paths to
``p4 -x`` for the final sync. Bare paths preserve normal head-revision behavior;
the dry-run revision is only used to identify the candidate path.

Every P4 invocation passes the configured port and runtime-derived client name
explicitly. That avoids ambient P4CONFIG/P4PORT resolution and makes the client
identity portable across machines following the ``user_hostname_suffix``
convention. The temporary ``-x`` file contains raw one-path-per-line entries:
Perforce treats shell-style quoting as literal path characters.

``--dry-run`` still performs the initial enumeration and filtering, then adds
``-n`` to the final ``p4 -x ... sync`` command. It therefore previews the exact
filtered sync without modifying the workspace.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import socket
import subprocess
import sys
import tempfile
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

CONFIG_PATH = Path.home() / ".config" / "p4-sync" / "config.json"

# Perforce escapes '#' in depot paths, so the first '#' is the revision marker.
P4_DRY_RUN_FILE_ACTION = re.compile(r"^(//[^#]*)#(\d+)(?:\s+-\s+.*)?$")


class ConfigurationError(ValueError):
    """Raised when the deployed P4 sync configuration is missing or invalid."""


class P4CommandError(RuntimeError):
    """Raised when an explicit P4 invocation fails."""


@dataclass(frozen=True)
class ProjectConfig:
    """Resolved P4 settings for one selectable sync project."""

    port: str
    depot_root: str
    client_suffix: str
    excluded_extensions: frozenset[str]


def _require_mapping(value: object, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{description} must be an object")
    return value


def _require_string(values: Mapping[str, Any], field: str, description: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{description}.{field} must be a non-empty string")
    return value


def _normalize_extension(extension: object, list_name: str) -> str:
    if (
        not isinstance(extension, str)
        or not extension
        or extension != extension.strip()
        or "." in extension
        or "*" in extension
    ):
        raise ConfigurationError(
            f"exclude list {list_name!r} must contain bare, non-empty extensions"
        )
    return extension.casefold()


def resolve_project_config(config: object, project_name: str) -> ProjectConfig:
    """Resolve one project and its named extension list from config data."""
    document = _require_mapping(config, "P4 sync configuration")
    projects = _require_mapping(document.get("projects"), "projects")
    project = _require_mapping(projects.get(project_name), f"project {project_name!r}")
    exclude_lists = _require_mapping(document.get("exclude_lists"), "exclude_lists")

    exclude_list_name = _require_string(
        project, "exclude_list", f"project {project_name!r}"
    )
    extensions = exclude_lists.get(exclude_list_name)
    if not isinstance(extensions, list) or not extensions:
        raise ConfigurationError(
            f"exclude list {exclude_list_name!r} for project {project_name!r} is missing or empty"
        )

    normalized_extensions = [
        _normalize_extension(extension, exclude_list_name) for extension in extensions
    ]
    if len(set(normalized_extensions)) != len(normalized_extensions):
        raise ConfigurationError(
            f"exclude list {exclude_list_name!r} contains duplicate extensions"
        )

    depot_root = _require_string(project, "depot_root", f"project {project_name!r}")
    if not depot_root.startswith("//"):
        raise ConfigurationError(
            f"project {project_name!r}.depot_root must start with '//': {depot_root!r}"
        )

    return ProjectConfig(
        port=_require_string(project, "port", f"project {project_name!r}"),
        depot_root=depot_root,
        client_suffix=_require_string(
            project, "client_suffix", f"project {project_name!r}"
        ),
        excluded_extensions=frozenset(normalized_extensions),
    )


def load_project_config(config_path: Path, project_name: str) -> ProjectConfig:
    """Load the deployed JSON configuration and resolve the requested project."""
    try:
        config = json.loads(config_path.read_text())
    except FileNotFoundError as error:
        raise ConfigurationError(
            f"P4 sync configuration is missing: {config_path}. Run chezmoi apply."
        ) from error
    except json.JSONDecodeError as error:
        raise ConfigurationError(
            f"P4 sync configuration is invalid JSON: {config_path}: {error}"
        ) from error
    return resolve_project_config(config, project_name)


def build_client_name(username: str, hostname: str, client_suffix: str) -> str:
    """Build the portable P4 client identity from the local machine identity."""
    return "_".join((username, hostname, client_suffix))


def build_enumeration_command(
    port: str, client_name: str, depot_root: str
) -> list[str]:
    """Build the explicit P4 dry-run used to enumerate candidate depot paths."""
    return [
        "p4",
        "-p",
        port,
        "-c",
        client_name,
        "sync",
        "-n",
        f"{depot_root.rstrip('/')}/...",
    ]


def parse_dry_run_output(output: str) -> list[str]:
    """Return bare depot paths from P4 sync dry-run file/action output lines."""
    paths: list[str] = []
    for line in output.splitlines():
        match = P4_DRY_RUN_FILE_ACTION.match(line)
        if match is None:
            if line.startswith("//"):
                print(
                    f"WARNING: skipping unparseable p4 sync -n line: {line}",
                    file=sys.stderr,
                )
            continue
        paths.append(match.group(1))
    return paths


def filter_excluded_paths(
    paths: Sequence[str], excluded_extensions: Collection[str]
) -> list[str]:
    """Keep paths whose last extension is not in the case-insensitive exclusion set."""
    normalized_extensions = {
        extension.removeprefix(".").casefold() for extension in excluded_extensions
    }
    return [
        path
        for path in paths
        if PurePosixPath(path).suffix.removeprefix(".").casefold()
        not in normalized_extensions
    ]


def build_sync_command(
    port: str, client_name: str, paths_file: Path, dry_run: bool
) -> list[str]:
    """Build the final explicit P4 sync command using a global ``-x`` argument."""
    command = [
        "p4",
        "-p",
        port,
        "-c",
        client_name,
        "-x",
        str(paths_file),
        "sync",
    ]
    if dry_run:
        command.append("-n")
    return command


def _run_p4(
    command: Sequence[str], *, capture_output: bool
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=capture_output,
            text=True,
        )
    except FileNotFoundError as error:
        raise P4CommandError("p4 is not installed or not available on PATH") from error

    if result.returncode == 0:
        return result

    detail = "\n".join(
        output.strip()
        for output in (result.stderr, result.stdout)
        if output and output.strip()
    )
    message = f"p4 exited {result.returncode}"
    raise P4CommandError(f"{message}:\n{detail}" if detail else message)


def _write_paths_file(paths: Sequence[str]) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="p4-sync-", suffix=".txt", delete=False
    ) as file:
        for path in paths:
            file.write(f"{path}\n")
        return Path(file.name)


def sync_project(project_name: str, project: ProjectConfig, dry_run: bool) -> None:
    """Enumerate, filter, and sync one project; always remove the ``-x`` file."""
    client_name = build_client_name(
        getpass.getuser(),
        socket.gethostname(),
        project.client_suffix,
    )
    enumeration = _run_p4(
        build_enumeration_command(project.port, client_name, project.depot_root),
        capture_output=True,
    )
    candidate_paths = parse_dry_run_output(enumeration.stdout)
    retained_paths = filter_excluded_paths(candidate_paths, project.excluded_extensions)
    excluded_count = len(candidate_paths) - len(retained_paths)

    print(
        f"INFO: {project_name}: candidates={len(candidate_paths)} "
        f"kept={len(retained_paths)} excluded={excluded_count}",
        file=sys.stderr,
    )
    if not retained_paths:
        print(f"INFO: {project_name}: nothing to sync after filtering", file=sys.stderr)
        return

    paths_file = _write_paths_file(retained_paths)
    try:
        _run_p4(
            build_sync_command(project.port, client_name, paths_file, dry_run),
            capture_output=False,
        )
    finally:
        paths_file.unlink(missing_ok=True)

    action = "preview" if dry_run else "sync"
    print(
        f"INFO: {project_name}: {action} completed for {len(retained_paths)} paths "
        f"({excluded_count} excluded)",
        file=sys.stderr,
    )


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="configured project name")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the filtered final P4 sync without modifying the workspace",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        project = load_project_config(CONFIG_PATH, args.project)
        sync_project(args.project, project, args.dry_run)
    except (ConfigurationError, OSError, P4CommandError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
