from __future__ import annotations

import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from visual_qa import compare_pngs, png_stats, write_json  # noqa: E402


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _write_rgb_png(path: Path, rows: list[list[tuple[int, int, int]]]) -> None:
    height = len(rows)
    width = len(rows[0]) if rows else 0
    raw = b"".join(b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def test_visual_qa_png_stats_and_diff_are_dependency_free(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.png"
    candidate = tmp_path / "candidate.png"
    _write_rgb_png(baseline, [[(0, 0, 0), (255, 255, 255)]])
    _write_rgb_png(candidate, [[(0, 0, 0), (250, 250, 250)]])

    stats = png_stats(baseline)
    diff = compare_pngs(baseline, candidate)

    assert stats.width == 2
    assert stats.height == 1
    assert stats.dark_ratio == 0.5
    assert stats.light_ratio == 0.5
    assert diff.changed_ratio > 0
    assert diff.max_delta == 5


@pytest.mark.parametrize(
    "script",
    [
        "audit_appearance_matrix.py",
        "audit_pdf_features.py",
        "compare_visual_snapshots.py",
        "audit_studio_visual.py",
        "run_visual_qa_matrix.py",
        "check_pdf_preflight.py",
        "check_visual_contracts.py",
    ],
)
def test_visual_qa_scripts_define_helpful_cli_entrypoints(script: str) -> None:
    source = (SCRIPTS / script).read_text(encoding="utf-8")

    assert "argparse.ArgumentParser" in source
    assert "--output-dir" in source
    assert 'if __name__ == "__main__"' in source


def test_appearance_matrix_filter_contract_is_bounded_without_rendering() -> None:
    from audit_appearance_matrix import RenderItem, _parse_filter

    assert _parse_filter("modern", ["modern", "github"], label="style") == ("modern",)
    assert RenderItem("modern", "blue", "light").name == "modern-blue-light"




def test_studio_visual_audit_uses_live_server_preview_context() -> None:
    source = (SCRIPTS / "audit_studio_visual.py").read_text(encoding="utf-8")

    assert '<base href="{base_href}">' in source
    assert 'page.route("**/api/**", proxy_studio_api)' in source
    assert "_proxy_local_studio_api" in source
    assert "_open_local_studio_url" in source
    assert "ProxyHandler({})" in source
    assert "urllib.request.urlopen(" not in source
    assert '"--project"' in source
    assert '"project_section_visible"' in source
    assert "_studio_process_env" in source
    assert "X-Mardas-Studio-Token" in source
    assert '("x-mardas-studio-token", "X-Mardas-Studio-Token")' in source
    assert "preview_status" in source
    assert "preview_failed" in source
    assert "preview_mode" in source
    assert "preview_status_unclipped" in source
    assert "toast_region_present" in source
    assert "command_palette_navigation" in source
    assert "export_queue_helpers" in source
    assert "cancel_export_button_present" in source
    assert "pdf_like_scroll_sync_removed" in source
    assert "fast_scroll_sync_guarded" in source
    assert "pdf_like_scrollbar_color" in source
    assert "unexpected Studio preview mode" in source
    assert "Studio preview frame is not visible" in source


def test_visual_snapshot_compare_script_writes_summary(tmp_path: Path) -> None:
    from compare_visual_snapshots import main as compare_main

    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    output = tmp_path / "diff"
    baseline.mkdir()
    candidate.mkdir()
    _write_rgb_png(baseline / "page.png", [[(10, 10, 10), (240, 240, 240)]])
    _write_rgb_png(candidate / "page.png", [[(10, 10, 10), (241, 241, 241)]])

    assert compare_main([
        str(baseline),
        str(candidate),
        "--output-dir",
        str(output),
        "--max-changed-ratio",
        "1",
        "--max-rms-delta",
        "2",
    ]) == 0

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["shared"] == 1
    assert summary["counts"]["failed"] == 0
    assert (output / "SUMMARY.md").is_file()



def test_visual_qa_commands_are_process_tree_timeout_safe() -> None:
    source = (SCRIPTS / "visual_qa.py").read_text(encoding="utf-8")

    assert "start_new_session" in source or "CREATE_NEW_PROCESS_GROUP" in source
    assert "_command_env" in source
    assert "os.killpg" in source
    assert "SIGKILL" in source
    assert "timed out after" in source



def test_build_examples_uses_process_tree_safe_render_commands() -> None:
    source = (SCRIPTS / "build_examples.sh").read_text(encoding="utf-8")

    assert "from visual_qa import run_command" in source
    assert "MARDAS_BUILD_EXAMPLES_COMMAND_TIMEOUT" in source
    assert '"--progress",' in source
    assert '"off",' in source


def test_visual_qa_scripts_expose_reliable_batch_controls() -> None:
    appearance_help = subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_appearance_matrix.py"), "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        timeout=30,
    ).stdout
    feature_help = subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_pdf_features.py"), "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        timeout=30,
    ).stdout

    for flag in ["--resume", "--fail-fast", "--max-cases", "--raster-timeout"]:
        assert flag in appearance_help
        assert flag in feature_help
    assert "--all-appearances" in feature_help



def test_feature_audit_all_appearances_can_be_bounded_without_rendering() -> None:
    from audit_pdf_features import _parse_appearances
    from mardas_md2pdf.appearance import MODES, PALETTES_ORDER, STYLES

    appearances = _parse_appearances(None, all_appearances=True)

    assert len(appearances) == len(STYLES) * len(PALETTES_ORDER) * len(MODES)
    assert appearances[0].name == f"{STYLES[0]}-{PALETTES_ORDER[0]}-{MODES[0]}"


def test_appearance_audit_accepts_explicit_appearance_triples() -> None:
    from audit_appearance_matrix import _parse_appearances

    appearances = _parse_appearances("modern:blue:light,github:slate:dark")

    assert appearances is not None
    assert [appearance.name for appearance in appearances] == ["modern-blue-light", "github-slate-dark"]


def test_chunked_visual_qa_runner_builds_bounded_case_chunks() -> None:
    from run_visual_qa_matrix import AppearanceCase, chunked

    cases = tuple(AppearanceCase("modern", "blue", mode) for mode in ("light", "dark"))

    assert chunked(cases, 1) == [(cases[0],), (cases[1],)]
    assert chunked(cases, 2) == [cases]


def test_chunked_visual_qa_runner_uses_safe_command_capture() -> None:
    source = (SCRIPTS / "run_visual_qa_matrix.py").read_text(encoding="utf-8")

    assert "from visual_qa import ensure_clean_dir, run_command, write_json" in source
    assert "subprocess.run" not in source
    assert "stdout=subprocess.PIPE" not in source


def test_chunked_visual_qa_runner_reports_child_failures_without_crashing() -> None:
    from run_visual_qa_matrix import _run

    result = _run(
        [sys.executable, "-c", "import sys; print('before failure'); print('bad', file=sys.stderr); sys.exit(7)"],
        timeout=10,
    )

    assert result["returncode"] == 1
    assert result["command"]
    assert "before failure" in result["stderr_tail"]
    assert "bad" in result["stderr_tail"]


def test_run_command_supports_heartbeat_callbacks() -> None:
    from visual_qa import run_command

    heartbeats: list[float] = []
    completed = run_command(
        [sys.executable, "-c", "import time; time.sleep(1.2); print('done')"],
        timeout=5,
        description="heartbeat smoke",
        heartbeat=heartbeats.append,
        heartbeat_interval=0.5,
    )

    assert completed.returncode == 0
    assert "done" in completed.stdout
    assert heartbeats


def test_visual_matrix_resume_detects_complete_child_manifest(tmp_path: Path) -> None:
    from run_visual_qa_matrix import _child_manifest_complete

    chunk = tmp_path / "chunk-001"
    write_json(chunk / "manifest.json", {"counts": {"requested": 2, "completed": 2, "failed": 0}})

    assert _child_manifest_complete(chunk, expected_count=2)
    assert not _child_manifest_complete(chunk, expected_count=3)

    write_json(chunk / "manifest.json", {"matrix": {"count": 56, "completed": 1, "failed": 0}})
    assert _child_manifest_complete(chunk, expected_count=1)


def test_visual_matrix_runner_exposes_heartbeat_and_resume_controls() -> None:
    source = (SCRIPTS / "run_visual_qa_matrix.py").read_text(encoding="utf-8")

    assert "--chunk-heartbeat-seconds" in source
    assert "active_chunk" in source
    assert "last_heartbeat_at" in source
    assert "completed manifest reused" in source
    assert "duration_seconds" in source



def test_visual_contract_checker_accepts_complete_manifests(tmp_path: Path) -> None:
    from check_visual_contracts import main as check_contracts

    appearance = tmp_path / "appearance"
    features = tmp_path / "features"
    studio = tmp_path / "studio"
    for directory in (appearance, features, studio):
        directory.mkdir()

    rows = [[(10, 10, 10), (240, 240, 240)] * 450 for _ in range(520)]
    for path in (
        appearance / "cover.png",
        appearance / "content.png",
        features / "page.png",
        studio / "studio.png",
    ):
        _write_rgb_png(path, rows)

    write_json(
        appearance / "manifest.json",
        {
            "matrix": {"completed": 1, "failed": 0},
            "records": [{"cover_png": "cover.png", "content_png": "content.png"}],
            "failures": [],
        },
    )
    write_json(
        features / "manifest.json",
        {
            "counts": {"requested": 1, "completed": 1, "failed": 0},
            "records": [{"png": ["page.png"]}],
            "failures": [],
        },
    )
    checks = {
        "title": "Mardas MD2PDF Studio",
        "preview_mode": "accurate",
        "preview_failed": False,
    }
    from check_visual_contracts import STUDIO_REQUIRED_CHECKS

    checks.update({name: True for name in STUDIO_REQUIRED_CHECKS})
    write_json(studio / "manifest.json", {"screenshot": "studio.png", "checks": checks})

    output = tmp_path / "contract"
    assert check_contracts(
        [
            "--appearance-manifest",
            str(appearance / "manifest.json"),
            "--features-manifest",
            str(features / "manifest.json"),
            "--studio-manifest",
            str(studio / "manifest.json"),
            "--output-dir",
            str(output),
        ]
    ) == 0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["counts"]["feature_images"] == 1


def test_visual_contract_checker_rejects_blank_or_incomplete_artifacts(tmp_path: Path) -> None:
    from check_visual_contracts import main as check_contracts

    appearance = tmp_path / "appearance"
    appearance.mkdir()
    _write_rgb_png(appearance / "blank.png", [[(255, 255, 255)] * 300 for _ in range(400)])
    write_json(
        appearance / "manifest.json",
        {
            "matrix": {"completed": 1, "failed": 0},
            "records": [{"cover_png": "blank.png", "content_png": "missing.png"}],
            "failures": [],
        },
    )

    output = tmp_path / "contract"
    assert check_contracts(
        [
            "--appearance-manifest",
            str(appearance / "manifest.json"),
            "--output-dir",
            str(output),
        ]
    ) == 1
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert len(summary["failures"]) >= 2
