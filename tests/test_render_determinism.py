"""The same document must always render to the same bytes.

Set iteration order for strings varies between processes, so a class list built
with ``list(set(...))`` was stable within one run and different in the next.
Five renders of the published Persian guide produced five different documents,
which quietly cost the project reproducible output: a PDF's checksum depended
on which process produced it.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from mardas_folio.markdown import render_markdown, render_markdown_file

ROOT = Path(__file__).resolve().parents[1]

MIXED_DOCUMENT = textwrap.dedent(
    """\
    # عنوان فارسی

    - [x] وظیفه‌ی انجام‌شده با کلمه‌ی latency
    - [ ] task still open
    - [x] بازبینی نهایی

    <div class="page-break"></div>

    <details><summary>جزئیات</summary>

    متن پنهان.

    </details>

    ![نمودار](https://example.invalid/diagram.png)

    | ستون | Column |
    |---|---|
    | یک | one |
    """
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_same_markdown_renders_to_the_same_html_every_time() -> None:
    first = render_markdown(MIXED_DOCUMENT, toc=True)
    for _ in range(4):
        again = render_markdown(MIXED_DOCUMENT, toc=True)
        assert _digest(again.body_html) == _digest(first.body_html)
        assert again.toc_html == first.toc_html


@pytest.mark.parametrize("seed", ["0", "1", "2", "12345"])
def test_output_does_not_depend_on_the_process_hash_seed(seed: str, tmp_path: Path) -> None:
    """The failure only shows across processes, so this needs real ones.

    ``PYTHONHASHSEED`` changes how strings hash, which changes set iteration
    order. Any set whose order reaches the document makes the render depend on
    which interpreter happened to produce it.
    """

    source = tmp_path / "document.md"
    source.write_text(MIXED_DOCUMENT, encoding="utf-8")
    script = textwrap.dedent(
        """
        import hashlib, sys
        from pathlib import Path
        from mardas_folio.markdown import render_markdown_file
        result = render_markdown_file(Path(sys.argv[1]), document_root=Path(sys.argv[1]).parent,
                                      toc=True)
        print(hashlib.sha256(result.body_html.encode("utf-8")).hexdigest())
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(source)],
        cwd=ROOT,
        env={"PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    digest = completed.stdout.strip()

    expected = _digest(
        render_markdown_file(source, document_root=source.parent, toc=True).body_html
    )
    assert digest == expected, f"PYTHONHASHSEED={seed} produced a different document"


def test_class_attributes_are_never_built_from_set_iteration_order() -> None:
    """Guard the pattern, not only today's instances of it.

    ``list(set(...))`` on class names reads as harmless deduplication and is
    how this was introduced seven times over. ``_add_classes`` sorts.
    """

    for name in ("markdown.py", "references.py", "citations.py", "accessibility.py"):
        source = (ROOT / "src" / "mardas_folio" / name).read_text(encoding="utf-8")
        assert "list(set(" not in source, (
            f"{name} builds a list from set iteration order; use _add_classes or sorted()"
        )
