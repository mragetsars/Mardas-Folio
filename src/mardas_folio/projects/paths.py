"""Directory exclusions shared by workspace and asset discovery."""
from __future__ import annotations

WORKSPACE_IGNORED_PARTS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        "venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "patches",
    }
)
