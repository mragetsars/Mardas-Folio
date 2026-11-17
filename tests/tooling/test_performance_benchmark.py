from __future__ import annotations

from tests._paths import ROOT

import importlib.util
import subprocess
import sys


SCRIPT = ROOT / "scripts" / "benchmark_large_documents.py"


def _benchmark_module():
    spec = importlib.util.spec_from_file_location("benchmark_large_documents", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_large_document_benchmark_inputs_are_deterministic() -> None:
    module = _benchmark_module()
    first = module._document_text(module.PROFILES["pages50"])
    second = module._document_text(module.PROFILES["pages50"])

    assert first == second
    assert first.count('<div class="page-break"></div>') == 49
    assert "Mixed فارسی English ۱۴۰۵" in first
    assert module._selected_profiles("small,pages500") == [
        module.PROFILES["small"],
        module.PROFILES["pages500"],
    ]


def test_large_document_benchmark_help_is_executable() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert "pages500" in completed.stdout
    assert "--mode" in completed.stdout
    assert "--repeats" in completed.stdout


def test_large_document_benchmark_help_survives_missing_resource_module() -> None:
    code = r"""
import builtins
import runpy
import sys

original_import = builtins.__import__


def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "resource":
        raise ModuleNotFoundError("No module named 'resource'")
    return original_import(name, globals, locals, fromlist, level)


builtins.__import__ = guarded_import
script = sys.argv[1]
sys.argv = [script, "--help"]
runpy.run_path(script, run_name="__main__")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "pages500" in completed.stdout


def test_peak_rss_kib_is_optional_and_normalizes_macos_units(monkeypatch) -> None:
    module = _benchmark_module()

    monkeypatch.setattr(module, "_resource", None)
    assert module._peak_rss_kib() is None

    class FakeResource:
        RUSAGE_SELF = object()

        @staticmethod
        def getrusage(_scope):
            return type("Usage", (), {"ru_maxrss": 4096})()

    monkeypatch.setattr(module, "_resource", FakeResource)
    monkeypatch.setattr(module.sys, "platform", "darwin")
    assert module._peak_rss_kib() == 4

    monkeypatch.setattr(module.sys, "platform", "linux")
    assert module._peak_rss_kib() == 4096
