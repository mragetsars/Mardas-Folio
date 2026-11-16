"""projects — models implementation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from ..book import BookManifest, BookRenderBundle
from ..config import LoadedProjectConfig
from ..diagnostics import Diagnostic


class WorkspaceError(ValueError):
    """Stable project-workspace error for Studio API responses."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "project_error",
        status: int = 400,
        diagnostics: Iterable[Diagnostic] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.diagnostics = tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class WorkspaceFile:
    path: str
    size: int
    kind: str
    chapter_index: int | None = None
    chapter_title: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "path": self.path,
            "size": self.size,
            "kind": self.kind,
        }
        if self.chapter_index is not None:
            data["chapter_index"] = self.chapter_index
        if self.chapter_title:
            data["chapter_title"] = self.chapter_title
        return data


@dataclass(slots=True)
class ProjectWorkspace:
    config: LoadedProjectConfig
    manifest: BookManifest | None
    bundle: BookRenderBundle | None
    diagnostics: tuple[Diagnostic, ...]
    files: tuple[WorkspaceFile, ...]

    @property
    def root(self) -> Path:
        return self.config.root

    @property
    def enabled(self) -> bool:
        return self.config.path is not None
