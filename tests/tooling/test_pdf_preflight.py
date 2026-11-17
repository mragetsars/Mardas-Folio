from __future__ import annotations

import sys

from tests._paths import ROOT

sys.path.insert(0, str(ROOT / "scripts"))

from check_pdf_preflight import classify_preflight_stderr, parse_pdffonts_output  # noqa: E402


def test_parse_pdffonts_output_finds_type3_fonts() -> None:
    sample = """name                                 type              encoding         emb sub uni object ID
------------------------------------ ----------------- ---------------- --- --- --- ---------
AAAAAA+DejaVuSans                    Type 3            Custom           yes yes yes     10  0
BAAAAA+NotoSansArabic-Regular        CID TrueType      Identity-H       yes yes yes     11  0
"""

    fonts = parse_pdffonts_output(sample)

    assert len(fonts) == 2
    assert fonts[0].name == "AAAAAA+DejaVuSans"
    assert fonts[0].type == "Type 3"
    assert fonts[1].type == "CID TrueType"


def test_classify_preflight_stderr_marks_type3_bbox_as_warning() -> None:
    findings = classify_preflight_stderr("Syntax Warning: Bad bounding box in Type 3 glyph\n")

    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].code == "bad_type3_bbox"


def test_classify_preflight_stderr_escalates_other_syntax_warnings() -> None:
    findings = classify_preflight_stderr("Syntax Warning: Damaged xref table\n")

    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].code == "pdf_syntax_warning"
