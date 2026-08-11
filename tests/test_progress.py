from io import StringIO
from pathlib import Path

from mardas_folio.cli import _CliProgressBar, build_parser
from mardas_folio.renderer import _report_progress


GUI_HTML = Path(__file__).resolve().parents[1] / "src" / "mardas_folio" / "assets" / "gui.html"


def test_progress_reporter_clamps_values_and_ignores_callback_errors():
    events: list[tuple[str, float]] = []

    _report_progress(lambda message, value: events.append((message, value)), "start", -1)
    _report_progress(lambda message, value: events.append((message, value)), "done", 2)

    def broken_callback(_message: str, _value: float) -> None:
        raise RuntimeError("progress UI failed")

    _report_progress(broken_callback, "ignored", 0.5)

    assert events == [("start", 0.0), ("done", 1.0)]


def test_cli_progress_option_is_available():
    parser = build_parser()
    action = next(action for action in parser._actions if "--progress" in action.option_strings)

    assert action.default == "auto"
    assert set(action.choices) == {"auto", "on", "off"}


def test_cli_progress_bar_renders_final_line():
    stream = StringIO()
    progress = _CliProgressBar(stream=stream, width=4)

    progress("Parsing", 0.25)
    progress("PDF created", 1.0)

    output = stream.getvalue()
    assert "25%" in output
    assert "100%" in output
    assert "PDF created" in output
    assert output.endswith("\n")


def test_gui_exposes_export_progress_bar():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'id="exportProgress"' in html
    assert "progressbar" in html
    assert "startExportProgress" in html
    assert "finishExportProgress" in html
    assert "Rendering PDF..." in html
