from __future__ import annotations

from pathlib import Path
import threading
import time

import pytest

from mardas_folio import render_pool, studio_jobs
from mardas_folio.render_pool import RenderFuture, RenderPool, RenderPoolClosedError, RenderQueueFullError
from mardas_folio.renderer import RenderCancelledError
from mardas_folio.studio_jobs import StudioExportManager


@pytest.fixture
def session_probe(monkeypatch: pytest.MonkeyPatch):
    class Session:
        instances: list[Session] = []
        construction_count = 0
        constructor_failures = 0
        startup_failures = 0
        restart_failures = 0
        close_failures = 0

        def __init__(self) -> None:
            type(self).construction_count += 1
            if type(self).constructor_failures:
                type(self).constructor_failures -= 1
                raise RuntimeError("constructor failed")
            self.owner = threading.get_ident()
            self.closed = threading.Event()
            self.close_count = 0
            self.restart_count = 0
            self.instances.append(self)

        def __enter__(self):
            assert threading.get_ident() == self.owner
            if type(self).startup_failures:
                type(self).startup_failures -= 1
                raise RuntimeError("startup failed")
            return self

        def restart(self) -> None:
            assert threading.get_ident() == self.owner
            self.restart_count += 1
            if type(self).restart_failures:
                type(self).restart_failures -= 1
                raise RuntimeError("restart failed")

        def close(self) -> None:
            assert threading.get_ident() == self.owner
            self.close_count += 1
            self.closed.set()
            if type(self).close_failures:
                type(self).close_failures -= 1
                raise RuntimeError("close failed")

    monkeypatch.setattr(render_pool, "RenderSession", Session)
    return Session


@pytest.mark.parametrize("failure", ["constructor", "startup"])
def test_session_start_failure_finishes_job_and_worker_accepts_next_job(
    session_probe, failure: str
) -> None:
    setattr(session_probe, f"{failure}_failures", 1)
    with RenderPool(workers=1, queue_size=1, idle_timeout=10) as pool:
        first = pool.submit(lambda session, progress, cancelled: "unreachable")
        with pytest.raises(RuntimeError, match=f"{failure} failed"):
            first.result(timeout=3)
        second = pool.submit(lambda session, progress, cancelled: session)
        session = second.result(timeout=3)
        assert first.snapshot().status == "failed"
        assert second.snapshot().status == "succeeded"
        assert pool._threads[0].is_alive()
    assert session_probe.construction_count == 2
    assert session.closed.is_set()
    if failure == "startup":
        assert session_probe.instances[0].close_count == 1


def test_failed_restart_discards_session_and_worker_recovers(session_probe) -> None:
    session_probe.restart_failures = 1

    def fail(session, progress, cancelled):
        raise ValueError("render failed")

    with RenderPool(workers=1, queue_size=1, idle_timeout=10) as pool:
        first = pool.submit(fail)
        with pytest.raises(ValueError, match="render failed"):
            first.result(timeout=3)
        second = pool.submit(lambda session, progress, cancelled: session)
        recovered = second.result(timeout=3)
        failed = session_probe.instances[0]
        assert failed.restart_count == 1
        assert failed.close_count == 1
        assert recovered is not failed
    assert pool.shutdown_complete


def test_failed_startup_cleanup_does_not_kill_worker(session_probe) -> None:
    session_probe.startup_failures = 1
    session_probe.close_failures = 1
    with RenderPool(workers=1, queue_size=1, idle_timeout=10) as pool:
        failed = pool.submit(lambda session, progress, cancelled: "unreachable")
        with pytest.raises(RuntimeError, match="startup failed"):
            failed.result(timeout=3)
        assert pool.submit(lambda session, progress, cancelled: "recovered").result(3) == "recovered"
    assert pool.shutdown_complete


def test_failed_close_still_reports_worker_shutdown(session_probe) -> None:
    session_probe.close_failures = 1
    pool = RenderPool(workers=1, queue_size=1, idle_timeout=10)
    try:
        assert pool.submit(lambda session, progress, cancelled: "done").result(3) == "done"
    finally:
        pool.close()
    assert session_probe.instances[0].close_count == 1
    assert pool.shutdown_complete
    assert pool.wait_for_shutdown(timeout=0)
    assert not pool._threads[0].is_alive()


def test_idle_session_is_closed_and_replaced_even_when_close_fails(session_probe) -> None:
    session_probe.close_failures = 1
    with RenderPool(workers=1, queue_size=1, idle_timeout=1) as pool:
        first = pool.submit(lambda session, progress, cancelled: session).result(3)
        assert first.closed.wait(timeout=3)
        second = pool.submit(lambda session, progress, cancelled: session).result(3)
        assert second is not first
        assert first.close_count == 1
    assert second.closed.is_set()
    assert pool.shutdown_complete


def test_close_without_wait_cancels_full_queue_without_waiting_for_active_work(session_probe) -> None:
    entered = threading.Event()
    release = threading.Event()
    close_returned = threading.Event()
    ran_queued = threading.Event()

    def blocked(session, progress, cancelled):
        entered.set()
        assert release.wait(timeout=5)
        return "late result"

    def queued(session, progress, cancelled):
        ran_queued.set()

    pool = RenderPool(workers=1, queue_size=1, idle_timeout=10)
    closer = None
    try:
        active = pool.submit(blocked)
        assert entered.wait(timeout=3)
        pending = pool.submit(queued)
        with pytest.raises(RenderQueueFullError):
            pool.submit(queued)

        def close() -> None:
            pool.close(wait=False)
            close_returned.set()

        closer = threading.Thread(target=close, daemon=True)
        closer.start()
        assert close_returned.wait(timeout=1), "shutdown blocked behind the full queue"
        assert not active.done()
        assert active.snapshot().status == "cancelling"
        assert pending.done()
        with pytest.raises(RenderCancelledError):
            pending.result(timeout=0)
        assert not pool.shutdown_complete
        with pytest.raises(RenderPoolClosedError):
            pool.submit(queued)
        release.set()
        with pytest.raises(RenderCancelledError):
            active.result(timeout=3)
        assert pool.wait_for_shutdown(timeout=3)
        assert pool.shutdown_complete
        assert not ran_queued.is_set()
        assert pool._queue.unfinished_tasks == 0
    finally:
        release.set()
        if closer is not None:
            closer.join(timeout=3)
        pool.close()


def test_active_cancellation_remains_pending_until_work_releases_session(session_probe) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked(session, progress, cancelled):
        entered.set()
        assert release.wait(timeout=5)
        assert cancelled()
        return "discarded"

    with RenderPool(workers=1, queue_size=1, idle_timeout=10) as pool:
        future = pool.submit(blocked)
        try:
            assert entered.wait(timeout=3)
            assert future.cancel()
            assert future.snapshot().status == "cancelling"
            with pytest.raises(TimeoutError):
                future.result(timeout=0)
            release.set()
            with pytest.raises(RenderCancelledError):
                future.result(timeout=3)
            assert future.snapshot().status == "cancelled"
            assert not future.cancel()
        finally:
            release.set()


def test_submit_is_serialized_with_shutdown_so_accepted_work_cannot_be_orphaned(
    session_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    submitting = threading.Event()
    release_submit = threading.Event()
    closing = threading.Event()
    close_returned = threading.Event()
    release_work = threading.Event()
    futures = []
    errors: list[BaseException] = []
    pool = RenderPool(workers=1, queue_size=1, idle_timeout=10)
    original_put = pool._queue.put_nowait

    def delayed_put(item) -> None:
        submitting.set()
        assert release_submit.wait(timeout=5)
        original_put(item)

    monkeypatch.setattr(pool._queue, "put_nowait", delayed_put)

    def submit() -> None:
        try:
            futures.append(
                pool.submit(lambda session, progress, cancelled: release_work.wait(timeout=5))
            )
        except BaseException as exc:
            errors.append(exc)

    def close() -> None:
        closing.set()
        pool.close(wait=False)
        close_returned.set()

    submitter = threading.Thread(target=submit, daemon=True)
    closer = threading.Thread(target=close, daemon=True)
    try:
        submitter.start()
        assert submitting.wait(timeout=3)
        closer.start()
        assert closing.wait(timeout=3)
        assert not close_returned.wait(timeout=0.05)
        release_submit.set()
        submitter.join(timeout=3)
        assert close_returned.wait(timeout=3)
        release_work.set()
        assert not errors
        assert len(futures) == 1
        with pytest.raises(RenderCancelledError):
            futures[0].result(timeout=3)
        assert pool.wait_for_shutdown(timeout=3)
        assert pool._queue.unfinished_tasks == 0
    finally:
        release_submit.set()
        release_work.set()
        submitter.join(timeout=3)
        if closer.ident is not None:
            closer.join(timeout=3)
        pool.close()


def test_studio_close_keeps_export_files_until_worker_and_session_have_stopped(
    session_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render_pool, "RENDER_POOL_SHUTDOWN_TIMEOUT_SECONDS", 0.05)
    entered = threading.Event()
    release_work = threading.Event()
    cleanup_done = threading.Event()
    root_existed_after_close: list[bool] = []
    manager = StudioExportManager(workers=1, queue_size=1, idle_timeout=10)
    original_cleanup = manager._root.cleanup

    def cleanup() -> None:
        original_cleanup()
        cleanup_done.set()

    monkeypatch.setattr(manager._root, "cleanup", cleanup)

    def blocked(directory: Path, session, progress, cancelled) -> Path:
        output = directory / "report.pdf"
        output.write_bytes(b"%PDF-1.7\n")
        entered.set()
        assert release_work.wait(timeout=5)
        root_existed_after_close.append(output.is_file())
        return output

    try:
        job = manager.submit(label="report", filename="report.pdf", work=blocked)
        assert entered.wait(timeout=3)
        started = time.monotonic()
        manager.close()
        assert time.monotonic() - started < 1
        assert not manager.pool.shutdown_complete
        assert manager.root.is_dir()
        assert (job.directory / "report.pdf").is_file()
        assert not cleanup_done.is_set()
        manager.close()
        release_work.set()
        with pytest.raises(RenderCancelledError):
            job.future.result(timeout=3)
        assert manager.pool.wait_for_shutdown(timeout=3)
        assert cleanup_done.wait(timeout=3)
        assert root_existed_after_close == [True]
        assert session_probe.instances[0].closed.is_set()
        assert not manager.root.exists()
        assert not manager._jobs
    finally:
        release_work.set()
        manager.close()
        assert manager.pool.wait_for_shutdown(timeout=3)


def test_studio_close_after_idle_worker_cleans_root_synchronously(
    session_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = studio_jobs.StudioExportManager(workers=1, queue_size=1, idle_timeout=10)
    manager.close()
    assert manager.pool.shutdown_complete
    assert not manager.root.exists()


def test_cancellation_wins_before_success_is_published() -> None:
    future: RenderFuture[str] = RenderFuture(label="late cancellation")
    assert future._mark_running()
    assert future.cancel()
    future._mark_succeeded("discarded")
    with pytest.raises(RenderCancelledError):
        future.result(timeout=0)
    assert future.snapshot().status == "cancelled"


def test_worker_can_request_shutdown_without_joining_itself(session_probe) -> None:
    pool = RenderPool(workers=1, queue_size=1, idle_timeout=10)

    def stop(session, progress, cancelled):
        pool.close()
        return "discarded"

    try:
        future = pool.submit(stop)
        with pytest.raises(RenderCancelledError):
            future.result(timeout=3)
        assert pool.wait_for_shutdown(timeout=3)
        assert pool.shutdown_complete
    finally:
        pool.close()


@pytest.mark.parametrize(
    "options",
    [
        {"workers": True},
        {"workers": 1.5},
        {"queue_size": False},
        {"queue_size": "2"},
        {"idle_timeout": float("nan")},
        {"idle_timeout": float("inf")},
        {"idle_timeout": True},
        {"idle_timeout": "10"},
    ],
)
def test_invalid_pool_options_are_rejected_before_threads_start(options) -> None:
    with pytest.raises(ValueError):
        RenderPool(**options)
