from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from queue import Empty, Full, Queue
import threading
import time
from typing import Callable, Generic, TypeVar
from uuid import uuid4

from .renderer import ProgressCallback, RenderCancelledError, RenderSession

T = TypeVar("T")
RenderWork = Callable[[RenderSession, ProgressCallback, Callable[[], bool]], T]
LOGGER = logging.getLogger(__name__)
RENDER_POOL_SHUTDOWN_TIMEOUT_SECONDS = 5.0


class RenderQueueFullError(RuntimeError):
    """Raised when the bounded render queue cannot accept another export."""


class RenderPoolClosedError(RuntimeError):
    """Raised when work is submitted after pool shutdown."""


@dataclass(frozen=True, slots=True)
class RenderJobSnapshot:
    job_id: str
    label: str
    status: str
    message: str
    progress: float
    created_at: float
    started_at: float | None
    finished_at: float | None
    queue_wait_ms: int | None
    render_ms: int | None
    cancel_requested: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "queue_wait_ms": self.queue_wait_ms,
            "render_ms": self.render_ms,
            "cancel_requested": self.cancel_requested,
        }


class RenderFuture(Generic[T]):
    """Small future with progress and cooperative cancellation state."""

    def __init__(self, *, label: str) -> None:
        self.job_id = uuid4().hex
        self.label = label
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._cancel = threading.Event()
        self._status = "queued"
        self._message = "Queued"
        self._progress = 0.0
        self._created_at = time.time()
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._result: T | None = None
        self._exception: BaseException | None = None

    def cancel(self) -> bool:
        with self._lock:
            if self._status in {"succeeded", "failed", "cancelled"}:
                return False
            self._cancel.set()
            if self._status == "queued":
                self._status = "cancelled"
                self._message = "Cancelled before rendering started"
                self._progress = 0.0
                self._finished_at = time.time()
                self._done.set()
            else:
                self._status = "cancelling"
                self._message = "Cancellation requested"
            return True

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def update_progress(self, message: str, fraction: float) -> None:
        with self._lock:
            if self._status in {"cancelled", "failed", "succeeded"}:
                return
            self._message = str(message)
            self._progress = max(0.0, min(1.0, float(fraction)))

    def _mark_running(self) -> bool:
        with self._lock:
            if self._status == "cancelled" or self._cancel.is_set():
                if self._finished_at is None:
                    self._status = "cancelled"
                    self._message = "Cancelled before rendering started"
                    self._finished_at = time.time()
                    self._done.set()
                return False
            self._status = "running"
            self._message = "Starting renderer"
            self._started_at = time.time()
            return True

    def _mark_succeeded(self, result: T) -> None:
        with self._lock:
            # Cancellation may arrive after the worker's last callback check.
            # Publish completion while holding the same lock as cancel().
            if self._cancel.is_set():
                self._status = "cancelled"
                self._message = "Rendering cancelled"
                self._finished_at = time.time()
                self._done.set()
                return
            self._result = result
            self._status = "succeeded"
            self._message = "PDF ready"
            self._progress = 1.0
            self._finished_at = time.time()
            self._done.set()

    def _mark_cancelled(self) -> None:
        with self._lock:
            self._status = "cancelled"
            self._message = "Rendering cancelled"
            self._finished_at = time.time()
            self._done.set()

    def _mark_failed(self, exc: BaseException) -> None:
        with self._lock:
            self._exception = exc
            self._status = "failed"
            self._message = "Rendering failed"
            self._finished_at = time.time()
            self._done.set()

    def snapshot(self) -> RenderJobSnapshot:
        with self._lock:
            queue_wait = None
            render_ms = None
            if self._started_at is not None:
                queue_wait = round((self._started_at - self._created_at) * 1000)
            if self._started_at is not None and self._finished_at is not None:
                render_ms = round((self._finished_at - self._started_at) * 1000)
            return RenderJobSnapshot(
                job_id=self.job_id,
                label=self.label,
                status=self._status,
                message=self._message,
                progress=self._progress,
                created_at=self._created_at,
                started_at=self._started_at,
                finished_at=self._finished_at,
                queue_wait_ms=queue_wait,
                render_ms=render_ms,
                cancel_requested=self._cancel.is_set(),
            )

    def result(self, timeout: float | None = None) -> T:
        if not self._done.wait(timeout):
            raise TimeoutError("Timed out waiting for the render job.")
        with self._lock:
            if self._status == "cancelled":
                raise RenderCancelledError("PDF rendering was cancelled.")
            if self._exception is not None:
                raise self._exception
            if self._status != "succeeded":
                raise RuntimeError(f"Render job ended in unexpected state: {self._status}")
            return self._result  # type: ignore[return-value]

    def done(self) -> bool:
        return self._done.is_set()

    def exception(self) -> BaseException | None:
        if not self._done.is_set():
            return None
        with self._lock:
            return self._exception


@dataclass(slots=True)
class _QueuedWork(Generic[T]):
    future: RenderFuture[T]
    work: RenderWork[T]


class RenderPool:
    """Bounded worker pool whose workers reuse isolated Chromium sessions."""

    def __init__(
        self,
        *,
        workers: int = 2,
        queue_size: int = 6,
        idle_timeout: float = 60.0,
    ) -> None:
        if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 8:
            raise ValueError("workers must be between 1 and 8")
        if isinstance(queue_size, bool) or not isinstance(queue_size, int) or not 1 <= queue_size <= 64:
            raise ValueError("queue_size must be between 1 and 64")
        if (
            isinstance(idle_timeout, bool)
            or not isinstance(idle_timeout, (int, float))
            or not math.isfinite(idle_timeout)
            or idle_timeout < 1
        ):
            raise ValueError("idle_timeout must be at least one second")
        self.workers = workers
        self.queue_size = queue_size
        self.idle_timeout = float(idle_timeout)
        self._queue: Queue[_QueuedWork[object]] = Queue(maxsize=queue_size)
        self._closed = threading.Event()
        self._stopped = threading.Event()
        self._workers_remaining = workers
        self._state_lock = threading.Lock()
        self._active: set[RenderFuture[object]] = set()
        self._threads = [
            threading.Thread(
                target=self._worker,
                name=f"mardas-render-{index + 1}",
                daemon=True,
            )
            for index in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, work: RenderWork[T], *, label: str = "PDF export") -> RenderFuture[T]:
        future: RenderFuture[T] = RenderFuture(label=label)
        with self._state_lock:
            if self._closed.is_set():
                raise RenderPoolClosedError("Render pool is closed.")
            try:
                self._queue.put_nowait(_QueuedWork(future=future, work=work))
            except Full as exc:
                raise RenderQueueFullError("Render queue is full.") from exc
        return future

    @staticmethod
    def _close_session(session: RenderSession | None) -> None:
        if session is not None:
            try:
                session.close()
            except BaseException:
                LOGGER.warning("Could not close a render worker session", exc_info=True)

    def _worker(self) -> None:
        session: RenderSession | None = None
        last_work = time.monotonic()
        try:
            while not self._closed.is_set():
                try:
                    item = self._queue.get(timeout=min(1.0, self.idle_timeout))
                except Empty:
                    if session is not None and time.monotonic() - last_work >= self.idle_timeout:
                        self._close_session(session)
                        session = None
                    if self._closed.is_set():
                        return
                    continue
                future = item.future
                try:
                    with self._state_lock:
                        if self._closed.is_set():
                            future.cancel()
                            continue
                        if not future._mark_running():
                            continue
                        self._active.add(future)
                    if session is None:
                        created = RenderSession()
                        try:
                            created.__enter__()
                        except BaseException:
                            self._close_session(created)
                            raise
                        session = created
                    result = item.work(session, future.update_progress, future.cancelled)
                    if future.cancelled():
                        future._mark_cancelled()
                    else:
                        future._mark_succeeded(result)
                except RenderCancelledError:
                    future._mark_cancelled()
                except BaseException as exc:
                    future._mark_failed(exc)
                    if session is not None:
                        try:
                            session.restart()
                        except BaseException:
                            LOGGER.warning("Could not restart a render worker session", exc_info=True)
                            self._close_session(session)
                            session = None
                finally:
                    with self._state_lock:
                        self._active.discard(future)
                    last_work = time.monotonic()
                    self._queue.task_done()
        finally:
            self._close_session(session)
            with self._state_lock:
                self._workers_remaining -= 1
                if self._workers_remaining == 0:
                    self._stopped.set()

    def close(self, *, wait: bool = True) -> None:
        with self._state_lock:
            self._closed.set()
            for future in self._active:
                future.cancel()
            # Drain queued work directly; shutdown never waits for room to put
            # sentinels behind a full queue or an unavailable worker.
            while True:
                try:
                    item = self._queue.get_nowait()
                except Empty:
                    break
                item.future.cancel()
                self._queue.task_done()
        if wait:
            deadline = time.monotonic() + RENDER_POOL_SHUTDOWN_TIMEOUT_SECONDS
            for thread in self._threads:
                if thread is threading.current_thread():
                    continue
                thread.join(timeout=max(0.0, deadline - time.monotonic()))

    @property
    def shutdown_complete(self) -> bool:
        return self._closed.is_set() and self._stopped.is_set()

    def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """Wait until every worker has released its thread-affine resources."""
        return self._stopped.wait(timeout)

    def __enter__(self) -> "RenderPool":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
