#!/usr/bin/env python3
"""Normalize sdist archive metadata for reproducible release artifacts."""

from __future__ import annotations

import argparse
import gzip
import os
import stat
import tarfile
import tempfile
from pathlib import Path


def normalize_sdist(path: Path, *, epoch: int) -> None:
    """Rewrite ``path`` with stable ordering, ownership, modes, and timestamps."""
    path = path.resolve()
    original_mode = stat.S_IMODE(path.stat().st_mode)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with tarfile.open(path, "r:gz") as source:
            members = sorted(source.getmembers(), key=lambda item: item.name)
            with temporary_path.open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
                    with tarfile.open(
                        fileobj=compressed,
                        mode="w|",
                        format=tarfile.PAX_FORMAT,
                    ) as target:
                        for member in members:
                            member.uid = 0
                            member.gid = 0
                            member.uname = ""
                            member.gname = ""
                            member.mtime = epoch
                            member.pax_headers = {}
                            content = source.extractfile(member) if member.isfile() else None
                            target.addfile(member, content)
        # Replace only after the archive being read is closed. POSIX allows a
        # rename over a file that still has an open handle; Windows does not,
        # and fails the whole normalization with a sharing violation.
        os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Path to a .tar.gz source distribution")
    parser.add_argument(
        "--epoch",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", "946684800")),
        help="Unix timestamp used for all archive metadata",
    )
    args = parser.parse_args(argv)
    if args.epoch < 0:
        parser.error("--epoch must be non-negative")
    normalize_sdist(args.archive, epoch=args.epoch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
