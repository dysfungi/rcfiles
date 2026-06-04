"""Startup time guardrail for the Neovim config.

WHY THIS FILE EXISTS
    Plugin-heavy Neovim configs can silently degrade startup time as plugins accumulate.
    This test catches regressions by measuring real startup time with the applied config
    and asserting it stays under a configurable threshold.

    Baseline measured during test authorship on the target machine (MLF67N6G9N5W):
      ~110-115 ms warm (Lazy compile cache hot)
      ~279 ms cold (first run, compile/cache miss)
    Default threshold: 400 ms — comfortably above warm baseline, far below a real
    regression (e.g. a blocking plugin adding 300+ ms).

THRESHOLD OVERRIDE
    Set NVIM_STARTUP_MAX_MS in the environment to tighten or loosen the limit without
    editing this file. Useful for stricter local enforcement or looser CI allowance:
      NVIM_STARTUP_MAX_MS=250 mise x -- pytest .tests/nvim/test_startuptime.py

METHODOLOGY: BEST-OF-N AFTER WARMUP
    1. A warmup spawn (discarded) ensures Lazy's compiled-loader cache is hot.
    2. N=3 measured runs record the cumulative startup time from the last
       "--- NVIM STARTED ---" line of each --startuptime log.
    3. The minimum across runs is asserted — this sheds transient OS scheduling noise
       and cold-cache variance while still catching sustained slowdowns.

ON FAILURE
    A failure means startup has regressed beyond the threshold. Diagnose with:
      nvim --startuptime /tmp/nvim_startup.log +qa && sort -k2 -rn /tmp/nvim_startup.log | head -20
    The "self+sourced" column (col 2) identifies the slowest individual sources.
    Have an agent investigate and address the top offenders.

WHY SUBPROCESS (NOT UNIT TEST)
    Startup time is an emergent property of the full plugin load sequence. It cannot be
    usefully mocked or unit-tested. The test drives the real applied config as a user
    would (nvim --headless +qa) and measures wall-clock time from the log.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

NVIM_CONFIG = Path.home() / ".config" / "nvim" / "init.lua"
DEFAULT_THRESHOLD_MS = 400.0
MEASURED_RUNS = 3

# Pattern for the final startup log line: "  <ms>  <elapsed>: --- NVIM STARTED ---"
_STARTED_RE = re.compile(r"^\s*(\d+\.\d+)\s+[\d.]+:\s+---\s+NVIM STARTED\s+---")


def _measure_startup_ms(nvim: str, tmp_log: Path) -> float:
    """Spawn nvim --headless with --startuptime, return total startup ms."""
    subprocess.run(
        [nvim, "--headless", "--startuptime", str(tmp_log), "+qa"],
        capture_output=True,
        timeout=60,
    )
    for line in reversed(tmp_log.read_text().splitlines()):
        m = _STARTED_RE.match(line)
        if m:
            return float(m.group(1))
    raise RuntimeError(f"Could not parse startup time from {tmp_log}")


@pytest.fixture(scope="module")
def nvim_bin() -> str:
    nvim = shutil.which("nvim")
    if nvim is None:
        pytest.skip("nvim not on PATH")
    return nvim  # type: ignore[return-value]  # pytest.skip() is NoReturn; mypy can't see it


def test_startup_time(nvim_bin: str) -> None:
    """Neovim startup time (best-of-3 after warmup) stays under threshold."""
    if not NVIM_CONFIG.exists():
        pytest.skip(
            f"nvim config not applied: {NVIM_CONFIG} not found — "
            "run `chezmoi apply ~/.config/nvim/init.lua`"
        )

    threshold_ms = float(os.environ.get("NVIM_STARTUP_MAX_MS", DEFAULT_THRESHOLD_MS))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # Warmup: ensure Lazy's compiled-loader cache is hot (result discarded).
        _measure_startup_ms(nvim_bin, tmp_dir / "warmup.log")

        # Measured runs.
        times: list[float] = []
        for i in range(MEASURED_RUNS):
            log = tmp_dir / f"run_{i}.log"
            times.append(_measure_startup_ms(nvim_bin, log))

    best_ms = min(times)
    assert best_ms < threshold_ms, (
        f"Neovim startup regressed: best-of-{MEASURED_RUNS} = {best_ms:.1f} ms "
        f"(threshold {threshold_ms:.0f} ms, all runs: {[f'{t:.1f}' for t in times]})\n"
        "Diagnose with:\n"
        "  nvim --startuptime /tmp/nvim_startup.log +qa\n"
        "  sort -k2 -rn /tmp/nvim_startup.log | head -20\n"
        "The 'self+sourced' column identifies the slowest sources. "
        "Investigate and address the top offenders, or raise NVIM_STARTUP_MAX_MS "
        "if the increase is intentional."
    )
