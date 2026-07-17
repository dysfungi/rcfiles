"""Git-safe environment helpers for repository tests.

Tests run nested Git commands while pre-commit may export Git's internal variables.
They must be removed so subprocesses operate on their intended temporary repositories
rather than the repository running pytest.
"""

from __future__ import annotations

import os


def _clean_env() -> dict[str, str]:
    """Return the environment without Git's repository-routing variables."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
