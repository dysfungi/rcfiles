"""Unit tests for the filtered P4 sync executable.

The command's safety depends on its transformation boundary: P4's full dry-run
output is parsed into bare depot paths, only configured binary extensions are
removed, and those retained paths become global ``p4 -x`` input. These tests
exercise that boundary with synthetic P4 output and load the real chezmoi data
for Flyingfox without contacting a P4 server.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dot_local" / "bin" / "executable_p4-sync-excluding-assets.py"
PROJECTS_DATA = REPO_ROOT / ".chezmoidata" / "projects.yaml"
EXCLUDES_DATA = REPO_ROOT / ".chezmoidata" / "p4-sync-excludes.yaml"
EXPECTED_UNREAL_BINARY_ASSET_EXTENSIONS = frozenset(
    {
        "psd",
        "uasset",
        "ztl",
        "wem",
        "wav",
        "spp",
        "tga",
        "fbx",
        "png",
        "mp4",
        "pur",
        "mov",
        "hdr",
        "dll",
        "fla",
        "exe",
        "umap",
        "exr",
        "ai",
        "pyd",
        "mb",
    }
)


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("p4_sync_excluding_assets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT_MODULE = _load_script()


def _source_config() -> dict[str, Any]:
    projects = yaml.safe_load(PROJECTS_DATA.read_text())
    excludes = yaml.safe_load(EXCLUDES_DATA.read_text())
    assert isinstance(projects, dict)
    assert isinstance(excludes, dict)
    return {
        "projects": projects["riot"]["p4_sync_projects"],
        "exclude_lists": excludes,
    }


def test_parse_dry_run_output_requires_numeric_revision(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = "\n".join(
        (
            "//flyingfox/dev-main/source/tool.py#9 - updating /workspace/tool.py",
            "must resolve #573,#579 before submitting",
            "//flyingfox/dev-main/Assets/Texture.PNG#17 - updating /workspace/Texture.PNG",
            "//flyingfox/dev-main/Source/no-revision.py - updating /workspace/no-revision.py",
            "//flyingfox/dev-main/S3M2/01 - Bearcubs - Breathin'.wav#1 - updating /workspace/S3M2/01 - Bearcubs - Breathin'.wav",
            "//flyingfox/dev-main/Source/revision-only.py#5",
            "//flyingfox/dev-main/Deleted/Asset.uasset#42 - deleted as /local/path#123/file.ext",
            "//flyingfox/dev-main/Deleted/Asset.uasset#none - deleted as /workspace/Asset.uasset",
        )
    )

    assert SCRIPT_MODULE.parse_dry_run_output(output) == [
        "//flyingfox/dev-main/source/tool.py",
        "//flyingfox/dev-main/Assets/Texture.PNG",
        "//flyingfox/dev-main/S3M2/01 - Bearcubs - Breathin'.wav",
        "//flyingfox/dev-main/Source/revision-only.py",
        "//flyingfox/dev-main/Deleted/Asset.uasset",
    ]
    warnings = capsys.readouterr().err
    assert (
        "WARNING: skipping unparseable p4 sync -n line: //flyingfox/dev-main/Source/no-revision.py"
        in warnings
    )
    assert (
        "WARNING: skipping unparseable p4 sync -n line: //flyingfox/dev-main/Deleted/Asset.uasset#none"
        in warnings
    )


def test_filter_excluded_paths_is_case_insensitive_and_uses_final_extension() -> None:
    paths = [
        "//flyingfox/dev-main/Assets/Texture.PNG",
        "//flyingfox/dev-main/Assets/Character.uasset",
        "//flyingfox/dev-main/Source/tool.py",
        "//flyingfox/dev-main/Scenes/model.ma",
        "//flyingfox/dev-main/Docs/asset.png.txt",
        "//flyingfox/dev-main/README",
    ]

    assert SCRIPT_MODULE.filter_excluded_paths(paths, {"png", "UASSET"}) == [
        "//flyingfox/dev-main/Source/tool.py",
        "//flyingfox/dev-main/Scenes/model.ma",
        "//flyingfox/dev-main/Docs/asset.png.txt",
        "//flyingfox/dev-main/README",
    ]


def test_build_enumeration_command_uses_explicit_port_and_client() -> None:
    assert SCRIPT_MODULE.build_enumeration_command(
        "uegames.p4.riotgames.io:1666",
        "test_user_test_host_flyingfox_dev-main",
        "//flyingfox/dev-main",
    ) == [
        "p4",
        "-p",
        "uegames.p4.riotgames.io:1666",
        "-c",
        "test_user_test_host_flyingfox_dev-main",
        "sync",
        "-n",
        "//flyingfox/dev-main/...",
    ]


@pytest.mark.parametrize(
    ("dry_run", "expected_suffix"),
    [
        pytest.param(False, [], id="real-sync"),
        pytest.param(True, ["-n"], id="dry-run"),
    ],
)
def test_build_sync_command_uses_global_x_before_sync(
    dry_run: bool, expected_suffix: list[str]
) -> None:
    command = SCRIPT_MODULE.build_sync_command(
        "uegames.p4.riotgames.io:1666",
        "test_user_test_host_flyingfox_dev-main",
        Path("/tmp/p4-filtered-paths"),
        dry_run=dry_run,
    )

    assert command == [
        "p4",
        "-p",
        "uegames.p4.riotgames.io:1666",
        "-c",
        "test_user_test_host_flyingfox_dev-main",
        "-x",
        "/tmp/p4-filtered-paths",
        "sync",
        *expected_suffix,
    ]


def test_build_client_name_uses_runtime_identity_and_configured_suffix() -> None:
    assert (
        SCRIPT_MODULE.build_client_name(
            "other_user", "other-host", "flyingfox_dev-main"
        )
        == "other_user_other-host_flyingfox_dev-main"
    )


def test_load_project_config_resolves_flyingfox_from_chezmoi_data(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_source_config()))

    project = SCRIPT_MODULE.load_project_config(config_path, "flyingfox")

    assert project.port == "uegames.p4.riotgames.io:1666"
    assert project.depot_root == "//flyingfox/dev-main"
    assert project.client_suffix == "flyingfox_dev-main"
    assert project.excluded_extensions == EXPECTED_UNREAL_BINARY_ASSET_EXTENSIONS
    assert "ma" not in project.excluded_extensions
    assert "py" not in project.excluded_extensions


@pytest.mark.parametrize(
    "extension",
    [".png", "asset*", "", " png "],
    ids=["leading-dot", "wildcard", "empty", "surrounding-space"],
)
def test_project_config_rejects_non_bare_extensions(extension: str) -> None:
    config = _source_config()
    config["exclude_lists"]["unreal_binary_assets"] = [extension]

    with pytest.raises(SCRIPT_MODULE.ConfigurationError, match="bare"):
        SCRIPT_MODULE.resolve_project_config(config, "flyingfox")


@pytest.mark.parametrize(
    ("dry_run", "expected_sync_suffix"),
    [
        pytest.param(False, [], id="real-sync"),
        pytest.param(True, ["-n"], id="dry-run"),
    ],
)
def test_sync_project_writes_filtered_paths_to_p4_x_file_and_cleans_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
    expected_sync_suffix: list[str],
) -> None:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    log_path = tmp_path / "p4-invocations.jsonl"
    p4_stub = stub_bin / "p4"
    p4_stub.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            arguments = sys.argv[1:]
            record = {"arguments": arguments}
            if "-x" in arguments:
                paths_file = Path(arguments[arguments.index("-x") + 1])
                record["paths_file"] = str(paths_file)
                record["paths_contents"] = paths_file.read_text()
                record["exists_during_sync"] = paths_file.exists()
            else:
                print("//flyingfox/dev-main/Source/keep.py#9 - updating /workspace/keep.py")
                print("//flyingfox/dev-main/Plugins/tool.PYD#8 - updating /workspace/tool.PYD")
                print("//flyingfox/dev-main/Binaries/library.DLL#7 - updating /workspace/library.DLL")
                print("//flyingfox/dev-main/Scenes/model.ma#6 - updating /workspace/model.ma")
                print("//flyingfox/dev-main/README#5 - updating /workspace/README")

            with Path(os.environ["P4_STUB_LOG"]).open("a") as log_file:
                print(json.dumps(record), file=log_file)
            """
        )
    )
    p4_stub.chmod(0o755)
    monkeypatch.setenv("P4_STUB_LOG", str(log_path))
    monkeypatch.setenv("P4PORT", "ambient-p4.example:1666")
    monkeypatch.setenv("P4CLIENT", "ambient-client")
    monkeypatch.setenv("PATH", f"{stub_bin}:{os.environ['PATH']}")
    monkeypatch.setattr(SCRIPT_MODULE.getpass, "getuser", lambda: "test-user")
    monkeypatch.setattr(SCRIPT_MODULE.socket, "gethostname", lambda: "test-host")

    project = SCRIPT_MODULE.resolve_project_config(_source_config(), "flyingfox")
    SCRIPT_MODULE.sync_project("flyingfox", project, dry_run=dry_run)

    enumeration, sync = [json.loads(line) for line in log_path.read_text().splitlines()]
    client_name = "test-user_test-host_flyingfox_dev-main"
    assert enumeration["arguments"] == [
        "-p",
        "uegames.p4.riotgames.io:1666",
        "-c",
        client_name,
        "sync",
        "-n",
        "//flyingfox/dev-main/...",
    ]
    assert sync["arguments"] == [
        "-p",
        "uegames.p4.riotgames.io:1666",
        "-c",
        client_name,
        "-x",
        sync["paths_file"],
        "sync",
        *expected_sync_suffix,
    ]
    assert sync["paths_contents"] == (
        "//flyingfox/dev-main/Source/keep.py\n"
        "//flyingfox/dev-main/Scenes/model.ma\n"
        "//flyingfox/dev-main/README\n"
    )
    assert sync["exists_during_sync"]
    assert not Path(sync["paths_file"]).exists()


def test_sync_project_removes_paths_file_after_final_sync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    log_path = tmp_path / "failed-sync.json"
    p4_stub = stub_bin / "p4"
    p4_stub.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            arguments = sys.argv[1:]
            if "-x" not in arguments:
                print("//flyingfox/dev-main/Source/keep.py#9 - updating /workspace/keep.py")
                raise SystemExit(0)

            paths_file = Path(arguments[arguments.index("-x") + 1])
            Path(os.environ["P4_STUB_LOG"]).write_text(
                json.dumps(
                    {
                        "paths_file": str(paths_file),
                        "exists_during_sync": paths_file.exists(),
                    }
                )
            )
            print("intentional final-sync failure", file=sys.stderr)
            raise SystemExit(17)
            """
        )
    )
    p4_stub.chmod(0o755)
    monkeypatch.setenv("P4_STUB_LOG", str(log_path))
    monkeypatch.setenv("PATH", f"{stub_bin}:{os.environ['PATH']}")
    monkeypatch.setattr(SCRIPT_MODULE.getpass, "getuser", lambda: "test-user")
    monkeypatch.setattr(SCRIPT_MODULE.socket, "gethostname", lambda: "test-host")

    project = SCRIPT_MODULE.resolve_project_config(_source_config(), "flyingfox")
    with pytest.raises(SCRIPT_MODULE.P4CommandError, match="p4 exited 17"):
        SCRIPT_MODULE.sync_project("flyingfox", project, dry_run=False)

    failed_sync = json.loads(log_path.read_text())
    assert failed_sync["exists_during_sync"]
    assert not Path(failed_sync["paths_file"]).exists()
