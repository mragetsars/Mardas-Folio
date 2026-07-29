from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ERROR_POLICIES = ("error", "warn", "ignore")
QUALITY_PROFILES = ("standard", "strict-publication")


class RenderQualityError(RuntimeError):
    """Base class for rendering failures enforced by a quality policy."""


class MathJaxRenderError(RenderQualityError):
    """Raised when MathJax cannot produce complete rendered output."""


class FontValidationError(RenderQualityError):
    """Raised when a required publication font is unavailable."""


class PdfNavigationError(RenderQualityError):
    """Raised when expected PDF navigation cannot be preserved safely."""


@dataclass(slots=True)
class RenderQualityLog:
    """Structured evidence collected across browser rendering and PDF post-processing."""

    profile: str = "standard"
    events: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        category: str,
        status: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "category": category,
            "status": status,
            "message": message,
        }
        if details:
            event["details"] = details
        self.events.append(event)

    def payload(self) -> dict[str, Any]:
        counts = {"passed": 0, "warning": 0, "ignored": 0, "error": 0, "info": 0}
        for event in self.events:
            status = str(event.get("status") or "info")
            counts[status] = counts.get(status, 0) + 1
        return {
            "schema_version": 1,
            "profile": self.profile,
            "ok": counts.get("error", 0) == 0,
            "summary": counts,
            "events": self.events,
        }

    def write(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def validate_error_policy(value: str | None, *, default: str = "warn") -> str:
    normalized = str(value or default).strip().lower()
    if normalized not in ERROR_POLICIES:
        raise ValueError(f"must be one of: {', '.join(ERROR_POLICIES)}")
    return normalized


def validate_quality_profile(value: str | None) -> str:
    normalized = str(value or "standard").strip().lower()
    if normalized not in QUALITY_PROFILES:
        raise ValueError(f"must be one of: {', '.join(QUALITY_PROFILES)}")
    return normalized


def profile_policy(profile: str, explicit: str | None) -> str:
    """Resolve an explicit policy or the selected profile's default policy."""
    profile = validate_quality_profile(profile)
    default = "error" if profile == "strict-publication" else "warn"
    return validate_error_policy(explicit, default=default)


def handle_quality_issue(
    log: RenderQualityLog,
    *,
    category: str,
    policy: str,
    message: str,
    details: dict[str, Any] | None = None,
    error_type: type[RenderQualityError] = RenderQualityError,
) -> None:
    """Record and enforce a quality issue without duplicating policy logic."""
    normalized = validate_error_policy(policy)
    if normalized == "error":
        log.record(category, "error", message, details=details)
        raise error_type(message)
    if normalized == "warn":
        log.record(category, "warning", message, details=details)
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        return
    log.record(category, "ignored", message, details=details)
