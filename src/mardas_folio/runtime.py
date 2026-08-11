from __future__ import annotations

import asyncio
import os
import platform
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_CHROMIUM_ENV = "MARDAS_CHROMIUM_PATH"
_RUNTIME_ROOT_ENV = "MARDAS_RUNTIME_ROOT"
_UNRESOLVED_CHROMIUM = object()
_chromium_resolution_lock = threading.Lock()
_resolved_chromium_cache: Path | None | object = _UNRESOLVED_CHROMIUM


@dataclass(frozen=True, slots=True)
class RuntimeInfo:
    """Resolved process/runtime information exposed to desktop clients."""

    frozen: bool
    executable: Path
    bundle_root: Path
    runtime_root: Path
    chromium_path: Path | None
    platform: str
    architecture: str
    python_version: str

    def to_dict(self) -> dict[str, object]:
        return {
            "frozen": self.frozen,
            "executable": str(self.executable),
            "bundle_root": str(self.bundle_root),
            "runtime_root": str(self.runtime_root),
            "chromium_path": str(self.chromium_path) if self.chromium_path else None,
            "platform": self.platform,
            "architecture": self.architecture,
            "python_version": self.python_version,
        }


def is_frozen() -> bool:
    """Return whether the process is running from a frozen application bundle."""

    return bool(getattr(sys, "frozen", False))


def executable_path() -> Path:
    return Path(sys.executable).expanduser().resolve(strict=False)


def bundle_root() -> Path:
    """Return the immutable application-bundle root.

    PyInstaller exposes ``sys._MEIPASS`` for collected files. In onedir mode the
    executable directory remains a useful fallback and in source/wheel mode the
    package root is used.
    """

    temporary_root = getattr(sys, "_MEIPASS", None)
    if temporary_root:
        return Path(str(temporary_root)).expanduser().resolve(strict=False)
    if is_frozen():
        return executable_path().parent
    return Path(__file__).resolve().parent


def runtime_root() -> Path:
    """Return the root containing optional frozen-runtime resources."""

    explicit = os.environ.get(_RUNTIME_ROOT_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve(strict=False)
    root = bundle_root()
    candidates = (
        root / "runtime",
        executable_path().parent / "runtime",
        root,
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve(strict=False)
    return root


def _candidate_chromium_names() -> tuple[str, ...]:
    if os.name == "nt":
        return (
            "chrome-headless-shell.exe",
            "headless_shell.exe",
            "chrome.exe",
            "chromium.exe",
        )
    if sys.platform == "darwin":
        return (
            "Chromium.app/Contents/MacOS/Chromium",
            "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            "chrome-headless-shell",
            "headless_shell",
            "chrome",
        )
    return (
        "chrome-headless-shell",
        "headless_shell",
        "chrome",
        "chromium",
    )


def _chromium_roots(root: Path) -> Iterable[Path]:
    yield root / "chromium"
    yield root / "browser" / "chromium"
    yield root


def bundled_chromium_path() -> Path | None:
    """Resolve a packaged Chromium executable without consulting the system PATH."""

    explicit = os.environ.get(_CHROMIUM_ENV)
    if explicit:
        candidate = Path(explicit).expanduser().resolve(strict=False)
        return candidate if candidate.is_file() else None

    roots = tuple(dict.fromkeys(_chromium_roots(runtime_root())))
    names = _candidate_chromium_names()
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return candidate.resolve(strict=False)

    # Playwright browser archives add revision/platform directories. Keep the
    # search bounded to the packaged runtime instead of scanning user storage.
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file():
                continue
            normalized = candidate.name.casefold()
            if normalized in {Path(name).name.casefold() for name in names}:
                return candidate.resolve(strict=False)
    return None


def playwright_chromium_path() -> Path | None:
    """Return Playwright's installed Chromium path when available.

    This probes Playwright metadata without launching a browser. It is kept
    separate from ``bundled_chromium_path`` so frozen builds remain explicit
    about which runtime resource they ship.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return None

    async def probe() -> str:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            return playwright.chromium.executable_path

    try:
        candidate = Path(asyncio.run(probe())).resolve(strict=False)
    except Exception:
        return None
    return candidate if candidate.is_file() else None


def resolved_chromium_path() -> Path | None:
    """Resolve Chromium once, serializing the probe across rendering threads."""

    global _resolved_chromium_cache
    with _chromium_resolution_lock:
        if _resolved_chromium_cache is _UNRESOLVED_CHROMIUM:
            try:
                resolved = bundled_chromium_path() or playwright_chromium_path()
            except Exception:
                resolved = None
            _resolved_chromium_cache = resolved
        cached = _resolved_chromium_cache
    return cached if isinstance(cached, Path) else None


def cached_chromium_path() -> Path | None:
    """Return an already resolved browser without triggering discovery."""

    with _chromium_resolution_lock:
        cached = _resolved_chromium_cache
    return cached if isinstance(cached, Path) else None


def _clear_chromium_resolution_cache() -> None:
    """Reset browser discovery state for isolated tests."""

    global _resolved_chromium_cache
    with _chromium_resolution_lock:
        _resolved_chromium_cache = _UNRESOLVED_CHROMIUM


def runtime_info() -> RuntimeInfo:
    return RuntimeInfo(
        frozen=is_frozen(),
        executable=executable_path(),
        bundle_root=bundle_root(),
        runtime_root=runtime_root(),
        chromium_path=cached_chromium_path(),
        platform=platform.system().lower() or sys.platform,
        architecture=platform.machine().lower() or "unknown",
        python_version=platform.python_version(),
    )
