"""Adapt the pinned MathJax browser component to Tauri's frozen Object prototype.

Only the desktop copy is changed. The publishing engine keeps its original
vendored asset. Upgrading that asset requires reviewing and repinning this patch.
"""
from __future__ import annotations

import hashlib
import re

MATHJAX_SHA256 = "87d82f5c3b1fe8c1e0c95379a881204a4c7077fee45602414a11850266728e12"
_METHOD = re.compile(r"\b([A-Za-z_$][\w$]*\.prototype)\.toString=")
_EXPECTED_METHODS = 10


def prepare_preview_mathjax(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != MATHJAX_SHA256:
        raise ValueError("Pinned MathJax asset changed; review the desktop compatibility patch")

    def own_method(match: re.Match[str]) -> str:
        # ES5 class output assigns toString onto a new prototype. An inherited
        # nonwritable Object.prototype.toString rejects that assignment in strict
        # mode. Explicitly create the same writable, enumerable own property
        # first; Object.prototype itself remains frozen and untouched.
        return (
            f'Object.defineProperty({match.group(1)},"toString",'
            '{value:void 0,writable:!0,configurable:!0,enumerable:!0}).toString='
        )

    patched, count = _METHOD.subn(own_method, source.decode("utf-8"))
    if count != _EXPECTED_METHODS:
        raise ValueError(f"Expected {_EXPECTED_METHODS} MathJax prototype methods, found {count}")
    notice = "/* Mardas Folio desktop: frozen-prototype compatibility patch; see scripts/prepare_preview_mathjax.py. */\n"
    return (notice + patched).encode("utf-8")
