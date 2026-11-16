"""Stable errors shared by application services and process adapters."""

from __future__ import annotations

from typing import Any

from .diagnostics import Diagnostic


class EngineError(RuntimeError):
    """Stable application-layer error safe to expose through the sidecar."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "MARDAS-ENGINE-ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class EngineValidationError(EngineError):
    def __init__(
        self,
        message: str,
        diagnostics: tuple[Diagnostic, ...] | list[Diagnostic],
        *,
        code: str = "MARDAS-VALIDATION-FAILED",
    ) -> None:
        items = tuple(diagnostics)
        super().__init__(
            message,
            code=code,
            details={"diagnostics": [item.to_dict() for item in items]},
        )
        self.diagnostics = items
