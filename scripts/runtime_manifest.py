#!/usr/bin/env python3
"""Shared validation for standalone-runtime manifests and symbolic links."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Mapping

RUNTIME_MANIFEST_SCHEMA = 2
LEGACY_RUNTIME_MANIFEST_SCHEMA = 1
RUNTIME_FILE_TYPE = "file"
RUNTIME_SYMLINK_TYPE = "symlink"
MAX_SYMLINK_TARGET_BYTES = 4096
MAX_SYMLINK_HOPS = 64
_BROWSER_INVENTORY_ROOTS = (
    PurePosixPath("runtime/chromium"),
    PurePosixPath("_internal/runtime/chromium"),
)


def safe_runtime_path(value: object) -> PurePosixPath:
    """Return a canonical, relative POSIX inventory path."""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("Runtime inventory path is invalid")
    pure = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        pure.is_absolute()
        or windows.drive
        or windows.root
        or ".." in pure.parts
        or not pure.parts
        or pure.as_posix() != value
    ):
        raise ValueError(f"Runtime inventory path is unsafe: {value!r}")
    return pure


def has_bundled_browser_file(paths: Iterable[str]) -> bool:
    """Return whether regular-file inventory proves a packaged Chromium tree."""

    for value in paths:
        pure = safe_runtime_path(value)
        for root in _BROWSER_INVENTORY_ROOTS:
            if (
                len(pure.parts) > len(root.parts)
                and pure.parts[: len(root.parts)] == root.parts
            ):
                return True
    return False


def normalize_symlink_target(value: str | bytes) -> str:
    """Normalize a native link target into the portable manifest representation."""

    try:
        target = os.fsdecode(value)
    except (TypeError, UnicodeDecodeError) as exc:
        raise ValueError("Runtime symlink target is not valid filesystem text") from exc
    if not target or "\x00" in target:
        raise ValueError("Runtime symlink target is invalid")
    if os.sep == "\\":
        target = target.replace("\\", "/")
    normalized = PurePosixPath(target).as_posix()
    validate_symlink_target(normalized)
    return normalized


def validate_symlink_target(value: object) -> str:
    """Validate the canonical text stored as a manifest/ZIP symlink target."""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("Runtime symlink target is invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Runtime symlink target is not valid UTF-8 text") from exc
    if len(encoded) > MAX_SYMLINK_TARGET_BYTES:
        raise ValueError("Runtime symlink target is unreasonably long")
    pure = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if pure.is_absolute() or windows.drive or windows.root:
        raise ValueError(f"Runtime symlink target must be relative: {value!r}")
    if pure.as_posix() != value:
        raise ValueError(f"Runtime symlink target is not canonical: {value!r}")
    return value


def resolve_symlink_target(link_path: str, target: str) -> PurePosixPath:
    """Resolve ``target`` lexically and reject traversal outside the runtime root."""

    link = safe_runtime_path(link_path)
    validate_symlink_target(target)
    parts = list(link.parent.parts)
    for part in PurePosixPath(target).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ValueError(
                    f"Runtime symlink target escapes the runtime root: {link_path!r} -> {target!r}"
                )
            parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts) if parts else PurePosixPath(".")


def validate_symlink_graph(
    entry_paths: Iterable[str],
    symlinks: Mapping[str, str],
    *,
    directories: Iterable[str] = (),
) -> None:
    """Reject escaping, dangling, cyclic, or structurally ambiguous runtime links."""

    paths = {safe_runtime_path(value).as_posix() for value in entry_paths}
    links = {
        safe_runtime_path(path).as_posix(): validate_symlink_target(target)
        for path, target in symlinks.items()
    }
    if not set(links).issubset(paths):
        raise ValueError("Runtime symlink inventory is inconsistent")

    directory_paths = {"."}
    for value in directories:
        pure = safe_runtime_path(value)
        directory_paths.add(pure.as_posix())
    for value in paths | directory_paths:
        pure = PurePosixPath(value)
        for parent in pure.parents:
            directory_paths.add(parent.as_posix())

    for path in paths:
        for parent in PurePosixPath(path).parents:
            parent_name = parent.as_posix()
            if parent_name in links:
                raise ValueError(
                    f"Runtime inventory descends through a symlink: {parent_name}"
                )

    regular_files = paths - set(links)
    conflicting_files = regular_files & directory_paths
    if conflicting_files:
        raise ValueError(
            "Runtime inventory descends through a regular file: "
            + ", ".join(sorted(conflicting_files))
        )

    def resolve_virtual(link: str) -> PurePosixPath:
        resolved = list(PurePosixPath(link).parent.parts)
        pending = list(PurePosixPath(links[link]).parts)
        visited: list[str] = []
        while pending:
            part = pending.pop(0)
            if part in ("", "."):
                continue
            if part == "..":
                if not resolved:
                    raise ValueError(
                        f"Runtime symlink target escapes the runtime root: "
                        f"{link!r} -> {links[link]!r}"
                    )
                resolved.pop()
                continue

            resolved.append(part)
            candidate = PurePosixPath(*resolved).as_posix()
            if candidate in links:
                if candidate in visited:
                    chain = " -> ".join((*visited, candidate))
                    raise ValueError(f"Runtime symlink cycle detected: {chain}")
                visited.append(candidate)
                if len(visited) > MAX_SYMLINK_HOPS:
                    raise ValueError(
                        f"Runtime symlink chain exceeds {MAX_SYMLINK_HOPS} hops: {link}"
                    )
                resolved.pop()
                pending[0:0] = list(PurePosixPath(links[candidate]).parts)
                continue
            if candidate not in regular_files and candidate not in directory_paths:
                raise ValueError(
                    f"Runtime symlink target is dangling: {link!r} -> {links[link]!r}"
                )
            if candidate in regular_files and pending:
                raise ValueError(
                    f"Runtime symlink target traverses a regular file: "
                    f"{link!r} -> {links[link]!r}"
                )
        return PurePosixPath(*resolved) if resolved else PurePosixPath(".")

    resolved_targets: dict[str, str] = {}
    for link in links:
        resolved = resolve_virtual(link).as_posix()
        if resolved not in regular_files and resolved not in directory_paths:
            raise ValueError(
                f"Runtime symlink target is dangling: {link!r} -> {links[link]!r}"
            )
        resolved_targets[link] = resolved

    # A directory link can be individually resolvable yet still create an
    # infinite walk together with another directory link (for example
    # ``a/to-b -> ../b`` and ``b/to-a -> ../a``). Archive creation does not
    # follow those links, but downstream resource bundlers might. Model which
    # directory links become reachable through each alias and reject cycles.
    directory_links = {
        link: target
        for link, target in resolved_targets.items()
        if target in directory_paths
    }

    def lies_within(path: str, directory: str) -> bool:
        if directory == ".":
            return True
        path_parts = PurePosixPath(path).parts
        directory_parts = PurePosixPath(directory).parts
        return path_parts[: len(directory_parts)] == directory_parts

    dependencies = {
        link: {
            other
            for other in directory_links
            if lies_within(other, target)
        }
        for link, target in directory_links.items()
    }
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(link: str) -> None:
        if link in visiting:
            cycle = " -> ".join((*visiting[visiting.index(link) :], link))
            raise ValueError(f"Runtime directory symlink cycle detected: {cycle}")
        if link in visited:
            return
        visiting.append(link)
        for dependency in sorted(dependencies[link]):
            visit(dependency)
        visiting.pop()
        visited.add(link)

    for link in sorted(directory_links):
        visit(link)


def validate_local_symlink(root: Path, path: Path) -> str:
    """Inspect a link without dereferencing it first, then prove its target is safe."""

    root = root.resolve(strict=True)
    metadata = path.lstat()
    if not stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"Runtime path is not a symlink: {path}")
    raw_target = os.readlink(path)
    target = normalize_symlink_target(raw_target)
    # Perform lexical containment before asking the filesystem to follow the link.
    resolve_symlink_target(path.relative_to(root).as_posix(), target)
    try:
        resolved = (path.parent / raw_target).resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"Runtime symlink is dangling, cyclic, or escapes its root: {path}") from exc
    if not resolved.is_file() and not resolved.is_dir():
        raise ValueError(f"Runtime symlink target is not a file or directory: {path}")
    return target
