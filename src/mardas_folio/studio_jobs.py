from __future__ import annotations

from dataclasses import dataclass
import secrets
import shutil
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .render_pool import RenderFuture, RenderPool, RenderQueueFullError
from .renderer import ProgressCallback, RenderSession

StudioExportWork = Callable[
    [Path, RenderSession, ProgressCallback, Callable[[], bool]], Path
]


class StudioExportJobError(RuntimeError):
    """Stable export-job manager error."""


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    path: Path
    filename: str
    content_type: str = "application/pdf"


@dataclass(slots=True)
class StudioExportJob:
    job_id: str
    directory: Path
    filename: str
    future: RenderFuture[ExportArtifact]
    downloaded_at: float | None = None


class StudioExportManager:
    """Own bounded Studio export jobs and their temporary result files."""

    def __init__(
        self,
        *,
        workers: int = 2,
        queue_size: int = 6,
        idle_timeout: float = 60.0,
        max_jobs: int = 64,
        ttl_seconds: float = 900.0,
    ) -> None:
        if max_jobs < workers + queue_size:
            raise ValueError("max_jobs must cover active workers and the render queue")
        self.max_jobs = max_jobs
        self.ttl_seconds = float(ttl_seconds)
        self._root = tempfile.TemporaryDirectory(prefix="mardas-studio-exports-")
        self.root = Path(self._root.name).resolve(strict=True)
        self.pool = RenderPool(
            workers=workers,
            queue_size=queue_size,
            idle_timeout=idle_timeout,
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, StudioExportJob] = {}

    def _cleanup_locked(self) -> None:
        now = time.time()
        removable: list[str] = []
        for job_id, job in self._jobs.items():
            snapshot = job.future.snapshot()
            terminal = snapshot.status in {"succeeded", "failed", "cancelled"}
            reference = snapshot.finished_at or snapshot.created_at
            if terminal and (now - reference >= self.ttl_seconds or job.downloaded_at is not None):
                removable.append(job_id)
        if len(self._jobs) - len(removable) >= self.max_jobs:
            terminal_jobs = sorted(
                (
                    (job.future.snapshot().finished_at or 0.0, job_id)
                    for job_id, job in self._jobs.items()
                    if job.future.snapshot().status in {"succeeded", "failed", "cancelled"}
                    and job_id not in removable
                ),
                key=lambda item: item[0],
            )
            needed = len(self._jobs) - len(removable) - self.max_jobs + 1
            removable.extend(job_id for _finished, job_id in terminal_jobs[:needed])
        for job_id in removable:
            job = self._jobs.pop(job_id, None)
            if job is not None:
                shutil.rmtree(job.directory, ignore_errors=True)

    def submit(
        self,
        *,
        label: str,
        filename: str,
        work: StudioExportWork,
    ) -> StudioExportJob:
        with self._lock:
            self._cleanup_locked()
            if len(self._jobs) >= self.max_jobs:
                raise RenderQueueFullError("Studio export history is full.")
            job_id = secrets.token_urlsafe(18).replace("-", "a").replace("_", "b")
            directory = self.root / job_id
            directory.mkdir(mode=0o700)

            def run(
                session: RenderSession,
                progress: ProgressCallback,
                cancelled: Callable[[], bool],
            ) -> ExportArtifact:
                output = work(directory, session, progress, cancelled)
                try:
                    resolved = output.resolve(strict=True)
                    resolved.relative_to(directory.resolve())
                    mode = resolved.stat().st_mode
                except (FileNotFoundError, OSError, ValueError) as exc:
                    raise StudioExportJobError(
                        "Studio export did not produce a valid result file."
                    ) from exc
                if output.is_symlink() or not stat.S_ISREG(mode):
                    raise StudioExportJobError(
                        "Studio export did not produce a regular result file."
                    )
                return ExportArtifact(path=resolved, filename=filename)

            try:
                future = self.pool.submit(run, label=label)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            job = StudioExportJob(
                job_id=job_id,
                directory=directory,
                filename=filename,
                future=future,
            )
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> StudioExportJob | None:
        with self._lock:
            self._cleanup_locked()
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool | None:
        job = self.get(job_id)
        if job is None:
            return None
        return job.future.cancel()

    def mark_downloaded(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.downloaded_at = time.time()

    def close(self) -> None:
        self.pool.close()
        with self._lock:
            self._jobs.clear()
        self._root.cleanup()

    def __enter__(self) -> "StudioExportManager":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
