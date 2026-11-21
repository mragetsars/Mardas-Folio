"""The user's local document shelf. Source files are never stored in this index."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

from .engine_errors import EngineError

MAX_ITEMS = 1500
MAX_INDEX_BYTES = 4 * 1024 * 1024
THUMB = re.compile(r"data:image/jpeg;base64,[A-Za-z0-9+/]+={0,2}")
TYPES = {"book", "document", "note", "resume", "article"}
CHOICES = {
    "variant": {"full", "band"},
    "texture": {"smooth", "linen", "paper", "leather", "twill"},
    "pattern": {"plain", "fold", "wave", "orbit"},
    "privacy": {"hidden", "visible"},
    "mark": {"auto", "duo", "triangle", "none"},
    "fastener": {"staple", "clip", "binder"},
    "material": {"sticky", "kraft", "cotton"},
    "binding": {"strip", "wire"},
    "avatar": {"neutral", "woman", "man"},
}


def index_path() -> Path:
    override = os.environ.get("MARDAS_FOLIO_LIBRARY_DIR")
    if override:
        return Path(override).expanduser() / "library.sqlite3"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "Mardas Folio" / "library.sqlite3"


def invalid() -> EngineError:
    return EngineError("Invalid shelf metadata.", code="MARDAS-LIBRARY-INVALID")


def _bounded(value: Any, limit: int, *, required: bool = False) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= limit
        and "\0" not in value
        and (not required or bool(value.strip()))
    )


def _appearance(value: Any) -> None:
    if not isinstance(value, dict):
        raise invalid()
    for key, option in value.items():
        if not isinstance(option, str):
            raise invalid()
        if key == "color" and re.fullmatch(r"#[0-9a-fA-F]{6}", option):
            continue
        if key in {"picture", "logo"} and len(option) <= 98304 and THUMB.fullmatch(option):
            continue
        if key == "label" and _bounded(option, 180):
            continue
        if option not in CHOICES.get(key, set()):
            raise invalid()


def _payload(items: Any) -> str:
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise invalid()
    ids: set[str] = set()
    paths: set[str] = set()
    for row in items:
        required = {"id", "path", "type", "title", "appearance"}
        if (
            not isinstance(row, dict)
            or not required <= row.keys()
            or row.keys() - required - {"detail", "author"}
        ):
            raise invalid()
        if not _bounded(row["id"], 100, required=True) or row["id"] in ids:
            raise invalid()
        if not _bounded(row["path"], 8192, required=True) or not _bounded(row["title"], 240):
            raise invalid()
        if not isinstance(row["type"], str) or row["type"] not in TYPES:
            raise invalid()
        path = row["path"].strip().replace("\\", "/")
        if path.startswith("//") or re.match(r"^[A-Za-z]:/", path):
            path = path.lower()
        if path in paths:
            raise invalid()
        if any(not _bounded(row.get(field, ""), 110) for field in ("detail", "author")):
            raise invalid()
        ids.add(row["id"])
        paths.add(path)
        _appearance(row["appearance"])
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    try:
        size = len(payload.encode("utf-8"))
    except UnicodeError as exc:
        raise invalid() from exc
    if size > MAX_INDEX_BYTES:
        raise EngineError("Shelf image or item limit reached.", code="MARDAS-LIBRARY-LIMIT")
    return payload


def _index(connection: sqlite3.Connection) -> tuple[int, str]:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS shelf "
        "(slot INTEGER PRIMARY KEY CHECK(slot = 1), revision INTEGER NOT NULL, items TEXT NOT NULL)"
    )
    row = connection.execute("SELECT revision, items FROM shelf WHERE slot = 1").fetchone()
    return row or (0, "[]")


def read_index() -> dict[str, Any]:
    path = index_path()
    try:
        if not path.exists():
            return {"revision": 0, "items": []}
        with closing(sqlite3.connect(path, timeout=3)) as conn:
            revision, payload = _index(conn)
        items = json.loads(payload)
        _payload(items)
        return {"revision": revision, "items": items}
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise EngineError("The local shelf could not be read.", code="MARDAS-LIBRARY-READ") from exc


def write_index(expected_revision: Any, items: Any) -> dict[str, Any]:
    if type(expected_revision) is not int or expected_revision < 0:
        raise invalid()
    payload = _payload(items)
    path = index_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(path, timeout=3)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            revision, _ = _index(conn)
            if revision != expected_revision:
                raise EngineError(
                    "The shelf was changed by another session.", code="MARDAS-LIBRARY-CONFLICT"
                )
            conn.execute("INSERT OR REPLACE INTO shelf VALUES (1, ?, ?)", (revision + 1, payload))
        return {"revision": revision + 1}
    except (OSError, sqlite3.Error) as exc:
        raise EngineError(
            "The local shelf could not be saved.", code="MARDAS-LIBRARY-WRITE"
        ) from exc
