from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading

import pytest

from mardas_folio import renderer, studio_jobs
from mardas_folio.book import load_book_manifest, render_book
from mardas_folio.config import load_project_config
from mardas_folio.render_pool import RenderPool, RenderQueueFullError
from mardas_folio.renderer import PdfOptions, RenderCancelledError, RenderSession
from mardas_folio.studio_jobs import StudioExportJobError, StudioExportManager


def test_render_pool_reuses_one_thread_affine_session() -> None:
    with RenderPool(workers=1, queue_size=2, idle_timeout=10) as pool:
        first = pool.submit(lambda session, progress, cancelled: id(session))
        second = pool.submit(lambda session, progress, cancelled: id(session))
        assert first.result(timeout=5) == second.result(timeout=5)
        assert first.snapshot().status == "succeeded"
        assert second.snapshot().status == "succeeded"


def test_render_pool_cancels_queued_work_without_running_it() -> None:
    entered = threading.Event()
    release = threading.Event()
    executed_second = threading.Event()

    def slow_work(session, progress, cancelled):
        entered.set()
        assert release.wait(timeout=5)
        return "first"

    def queued_work(session, progress, cancelled):
        executed_second.set()
        return "second"

    with RenderPool(workers=1, queue_size=2, idle_timeout=10) as pool:
        first = pool.submit(slow_work)
        assert entered.wait(timeout=5)
        second = pool.submit(queued_work)
        assert second.cancel()
        release.set()
        assert first.result(timeout=5) == "first"
        with pytest.raises(RenderCancelledError):
            second.result(timeout=5)
        assert not executed_second.is_set()
        assert second.snapshot().status == "cancelled"


def test_render_pool_rejects_work_beyond_bounded_queue() -> None:
    entered = threading.Event()
    release = threading.Event()

    def slow_work(session, progress, cancelled):
        entered.set()
        assert release.wait(timeout=5)
        return "done"

    with RenderPool(workers=1, queue_size=1, idle_timeout=10) as pool:
        first = pool.submit(slow_work)
        assert entered.wait(timeout=5)
        second = pool.submit(lambda session, progress, cancelled: "queued")
        with pytest.raises(RenderQueueFullError):
            pool.submit(lambda session, progress, cancelled: "rejected")
        release.set()
        assert first.result(timeout=5) == "done"
        assert second.result(timeout=5) == "queued"


def test_render_future_records_real_progress_and_timings() -> None:
    def work(session, progress, cancelled):
        progress("Parsing Markdown", 0.2)
        progress("Rendering PDF", 0.8)
        return 42

    with RenderPool(workers=1, queue_size=1, idle_timeout=10) as pool:
        future = pool.submit(work, label="benchmark")
        assert future.result(timeout=5) == 42
        snapshot = future.snapshot()
    assert snapshot.label == "benchmark"
    assert snapshot.status == "succeeded"
    assert snapshot.message == "PDF ready"
    assert snapshot.progress == 1.0
    assert snapshot.queue_wait_ms is not None
    assert snapshot.render_ms is not None


def test_studio_export_manager_canonicalizes_temporary_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_root = tmp_path / "real-export-root"
    real_root.mkdir()
    alias_root = tmp_path / "alias-export-root"
    try:
        alias_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    class AliasTemporaryDirectory:
        name = str(alias_root)

        def __init__(self, *args, **kwargs) -> None:
            pass

        def cleanup(self) -> None:
            pass

    monkeypatch.setattr(studio_jobs.tempfile, "TemporaryDirectory", AliasTemporaryDirectory)

    with StudioExportManager(workers=1, queue_size=1, idle_timeout=10) as manager:
        assert manager.root == real_root.resolve(strict=True)


def test_studio_export_manager_writes_results_outside_memory(tmp_path: Path) -> None:
    with StudioExportManager(workers=1, queue_size=1, idle_timeout=10) as manager:
        def work(directory, session, progress, cancelled):
            output = directory / "report.pdf"
            output.write_bytes(b"%PDF-1.7\n")
            return output

        job = manager.submit(label="report", filename="report.pdf", work=work)
        artifact = job.future.result(timeout=5)
        assert artifact.path.read_bytes() == b"%PDF-1.7\n"
        assert artifact.filename == "report.pdf"
        assert artifact.path.is_relative_to(manager.root)


def test_studio_export_manager_rejects_results_outside_job_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.7\n")
    with StudioExportManager(workers=1, queue_size=1, idle_timeout=10) as manager:
        job = manager.submit(
            label="unsafe",
            filename="unsafe.pdf",
            work=lambda directory, session, progress, cancelled: outside,
        )
        with pytest.raises(StudioExportJobError, match="valid result file"):
            job.future.result(timeout=5)


def test_studio_export_manager_rejects_symlink_results(tmp_path: Path) -> None:
    target = tmp_path / "target.pdf"
    target.write_bytes(b"%PDF-1.7\n")
    with StudioExportManager(workers=1, queue_size=1, idle_timeout=10) as manager:
        def work(directory, session, progress, cancelled):
            output = directory / "linked.pdf"
            try:
                output.symlink_to(target)
            except OSError:
                pytest.skip("symlink creation is unavailable")
            return output

        job = manager.submit(label="symlink", filename="linked.pdf", work=work)
        with pytest.raises(StudioExportJobError, match="valid result file"):
            job.future.result(timeout=5)


def test_render_session_rejects_cross_thread_use() -> None:
    session = RenderSession()
    session.__enter__()
    errors: list[BaseException] = []

    def close_from_other_thread() -> None:
        try:
            session.close()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=close_from_other_thread)
    thread.start()
    thread.join(timeout=5)
    session.close()
    assert errors
    assert "owning thread" in str(errors[0])


def test_convert_skips_full_debug_html_when_debug_output_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Title\n", encoding="utf-8")
    output = tmp_path / "output.pdf"
    result = renderer.render_markdown_file(source)
    html_calls: list[tuple[bool, bool]] = []

    original_build_html = renderer.build_html

    def record_build_html(result, options, **kwargs):
        html_calls.append((kwargs.get("include_cover", True), kwargs.get("include_content", True)))
        return original_build_html(result, options, **kwargs)

    @contextmanager
    def fake_page(options, session):
        yield object(), False

    def fake_render_pdf(page, html, options, output_path, **kwargs):
        output_path.write_bytes(b"%PDF-1.7\n")

    def fake_merge(parts, output_path, *args, **kwargs):
        output_path.write_bytes(b"%PDF-1.7\n")

    monkeypatch.setattr(renderer, "build_html", record_build_html)
    monkeypatch.setattr(renderer, "_render_page", fake_page)
    monkeypatch.setattr(renderer, "_render_pdf", fake_render_pdf)
    monkeypatch.setattr(renderer, "_merge_pdfs", fake_merge)
    monkeypatch.setattr(renderer, "PdfReader", lambda path: type("Reader", (), {"pages": [1]})())

    renderer.convert_render_result(result, PdfOptions(source, output, cover=True))
    assert html_calls == [(True, False), (False, True)]


def test_cancellation_is_checked_before_browser_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Title\n", encoding="utf-8")
    result = renderer.render_markdown_file(source)
    entered_browser = False

    @contextmanager
    def fake_page(options, session):
        nonlocal entered_browser
        entered_browser = True
        yield object(), False

    monkeypatch.setattr(renderer, "_render_page", fake_page)
    with pytest.raises(RenderCancelledError):
        renderer.convert_render_result(
            result,
            PdfOptions(source, tmp_path / "output.pdf", cancelled=lambda: True),
        )
    assert not entered_browser


def test_book_preparation_honors_cancellation_before_parsing(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "01.md").write_text("# Chapter\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        'schema_version = 1\n[book]\nchapters = ["chapters/01.md"]\n',
        encoding="utf-8",
    )
    config = load_project_config(start=tmp_path).config
    manifest, diagnostics = load_book_manifest(config)
    assert manifest is not None
    assert not diagnostics

    with pytest.raises(RenderCancelledError):
        render_book(manifest, cancelled=lambda: True)


def test_render_session_reuses_chromium_for_real_smoke_when_enabled(tmp_path: Path) -> None:
    import os

    if os.environ.get("MARDAS_RENDER_SMOKE") != "1":
        pytest.skip("Set MARDAS_RENDER_SMOKE=1 to run Chromium reuse smoke")
    source = tmp_path / "input.md"
    source.write_text("# Title\n\nMixed فارسی English.\n", encoding="utf-8")
    with RenderSession() as session:
        for index in range(2):
            renderer.convert(
                PdfOptions(source, tmp_path / f"output-{index}.pdf", cover=False),
                session=session,
            )
        assert session.launch_count == 1
        assert session.page_count == 2
