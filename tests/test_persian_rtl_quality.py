from pathlib import Path
import os

from bs4 import BeautifulSoup
import pytest

from mardas_folio.markdown import render_markdown
from mardas_folio.renderer import FooterContext, PdfOptions, _footer_template, _layout_css


def test_persian_blocks_get_explicit_rtl_direction_classes():
    result = render_markdown('---\nlang: fa\n---\n\nاین یک پاراگراف فارسی برای بررسی جهت متن است.\n')

    assert 'dir="rtl"' in result.body_html
    assert 'md2pdf-rtl-text' in result.body_html


def test_mixed_persian_latin_text_gets_bidi_and_numeric_classes():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "در خروجی PDF مقدار version 1.8.9 و شماره ۱۲۳ باید خوانا بماند.\n"
    )

    paragraph = BeautifulSoup(result.body_html, "html.parser").find("p")
    assert paragraph["dir"] == "rtl"
    assert 'mixed-script' in result.body_html
    assert 'mixed-numeral' in result.body_html


def test_english_mixed_prose_keeps_its_base_direction_after_latin_isolation():
    result = render_markdown(
        "---\nlang: en\ndir: ltr\n---\n\n"
        "This sample mixes Persian متن فارسی, English identifiers such as `renderer.pipeline`, "
        "version 1.2, and inline math $a^2 + b^2 = c^2$.\n"
    )
    paragraph = BeautifulSoup(result.body_html, "html.parser").find("p")
    assert paragraph["dir"] == "ltr"
    assert "md2pdf-mixed-prose" in paragraph["class"]
    assert paragraph.find("span", class_="md2pdf-ltr-isolate").get_text() == "This sample mixes Persian"


def test_mixed_prose_preserves_an_explicit_author_direction():
    result = render_markdown(
        '<p dir="rtl">English words followed by متن فارسی.</p>\n'
    )
    paragraph = BeautifulSoup(result.body_html, "html.parser").find("p")
    assert paragraph["dir"] == "rtl"
    assert "md2pdf-mixed-prose" in paragraph["class"]


def test_comma_separated_persian_phrases_are_isolated_in_ltr_source_order():
    text = "English terms include راست به چپ, فونت فارسی, and گزارش فنی with `renderer.pipeline` 1.2."
    result = render_markdown(f"---\nlang: en\ndir: ltr\n---\n\n{text}\n")
    paragraph = BeautifulSoup(result.body_html, "html.parser").find("p")
    assert [span.get_text() for span in paragraph.select(".md2pdf-rtl-isolate")] == [
        "راست به چپ", "فونت فارسی", "گزارش فنی",
    ]
    assert paragraph.get_text() == text.replace("`", "")
    assert paragraph.find("code").get_text() == "renderer.pipeline"
    assert paragraph.find("code").find("span") is None


def test_rtl_phrase_list_isolation_keeps_rtl_prose_and_numeric_tokens_unchanged():
    result = render_markdown(
        "---\nlang: fa\ndir: rtl\n---\n\n"
        "این جمله فارسی، گزارش فنی, فونت فارسی, و `renderer.pipeline` ۱۴۰۵ و 1.2 را حفظ می‌کند.\n"
    )
    paragraph = BeautifulSoup(result.body_html, "html.parser").find("p")
    assert paragraph["dir"] == "rtl"
    assert not paragraph.select(".md2pdf-rtl-isolate")
    assert "۱۴۰۵" in paragraph.get_text()
    assert "1.2" in paragraph.get_text()


@pytest.mark.skipif(
    os.environ.get("MARDAS_RENDER_SMOKE") != "1",
    reason="set MARDAS_RENDER_SMOKE=1 to verify RTL phrase order in Chromium",
)
def test_chromium_comma_separated_persian_phrases_follow_ltr_source_order(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    from mardas_folio.renderer import build_html

    text = "English terms: راست به چپ, فونت فارسی, and گزارش فنی."
    result = render_markdown(f"---\nlang: en\ndir: ltr\n---\n\n{text}\n")
    options = PdfOptions(input_path=tmp_path / "mixed.md", output_path=tmp_path / "mixed.pdf")
    document = build_html(result, options, include_cover=False, include_mathjax=False)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 1000, "height": 700})
            page.set_content(document)
            page.evaluate("document.fonts.ready")
            phrases = page.locator("p .md2pdf-rtl-isolate").evaluate_all(
                "elements => elements.map(element => ({text:element.textContent,left:element.getBoundingClientRect().left}))"
            )
            assert [phrase["text"] for phrase in phrases] == ["راست به چپ", "فونت فارسی", "گزارش فنی"]
            assert phrases[0]["left"] < phrases[1]["left"] < phrases[2]["left"]
        finally:
            browser.close()


def test_mixed_prose_css_honors_base_direction_instead_of_plaintext_detection(tmp_path: Path):
    options = PdfOptions(input_path=tmp_path / "mixed.md", output_path=tmp_path / "mixed.pdf")
    css, _classes = _layout_css(options, document_direction="ltr")
    for direction in ["ltr", "rtl"]:
        selector = f'.md2pdf-article .md2pdf-mixed-prose[dir="{direction}"]'
        declaration = css.split(selector, 1)[1].split("}", 1)[0]
        assert f"direction: {direction};" in declaration
        assert "unicode-bidi: isolate;" in declaration
        assert "unicode-bidi: plaintext;" not in declaration


@pytest.mark.skipif(
    os.environ.get("MARDAS_RENDER_SMOKE") != "1",
    reason="set MARDAS_RENDER_SMOKE=1 to verify mixed-script layout in Chromium",
)
@pytest.mark.parametrize(
    ("direction", "text"),
    [
        ("ltr", "This sentence فارسی has version 1.2?"),
        ("rtl", "این جمله فارسی شامل renderer. و شماره 1.2 است؟"),
    ],
)
def test_chromium_mixed_prose_starts_on_its_correct_side(tmp_path: Path, direction: str, text: str):
    from playwright.sync_api import sync_playwright

    from mardas_folio.renderer import build_html

    lang = "en" if direction == "ltr" else "fa"
    result = render_markdown(f"---\nlang: {lang}\ndir: {direction}\n---\n\n{text}\n")
    options = PdfOptions(input_path=tmp_path / "mixed.md", output_path=tmp_path / "mixed.pdf")
    document = build_html(result, options, include_cover=False, include_mathjax=False)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 900, "height": 700})
            page.set_content(document)
            page.evaluate("document.fonts.ready")
            metrics = page.locator("p.md2pdf-mixed-prose").evaluate(
                """paragraph => {
                    const range = document.createRange();
                    range.selectNodeContents(paragraph.firstChild);
                    const leading = range.getBoundingClientRect();
                    const bounds = paragraph.getBoundingClientRect();
                    const style = getComputedStyle(paragraph);
                    return {
                        leadingLeft: leading.left,
                        leadingRight: leading.right,
                        midpoint: (bounds.left + bounds.right) / 2,
                        direction: style.direction,
                        unicodeBidi: style.unicodeBidi,
                    };
                }"""
            )
            assert metrics["direction"] == direction
            assert metrics["unicodeBidi"] == "isolate"
            if direction == "ltr":
                assert metrics["leadingLeft"] < metrics["midpoint"]
            else:
                assert metrics["leadingRight"] > metrics["midpoint"]
        finally:
            browser.close()


def test_rtl_tables_get_direction_and_cell_profiles():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "| ستون | مقدار | شناسه |\n"
        "|---|---|---|\n"
        "| نسخه | version 1.8.9 و ۱.۸.۹ | PDF |\n"
        "| وضعیت | پایدار | stable |\n"
    )

    assert 'table-wrap--rtl' in result.body_html
    assert 'table-wrap--mixed-direction' in result.body_html
    assert 'table-wrap--mixed-numerals' in result.body_html
    assert 'table-cell--rtl' in result.body_html
    assert 'table-cell--ltr' in result.body_html
    assert 'table-cell--mixed' in result.body_html



def test_persian_mixed_table_cells_prefer_rtl_direction_for_readability():
    result = render_markdown(
        "---\nlang: fa\ndir: rtl\n---\n\n"
        "| Style | کاربرد پیشنهادی |\n"
        "|---|---|\n"
        "| `modern` | مستندات عمومی، proposal، گزارش نرم‌افزاری و راهنمای محصول. |\n"
        "| `github` | مستندات پروژه‌ای شبیه README و خروجی نزدیک به GitHub-style Markdown. |\n"
    )

    assert 'table-wrap--rtl' in result.body_html
    assert 'data-md2pdf-rtl-direction-votes=' in result.body_html
    assert 'data-md2pdf-ltr-direction-votes=' in result.body_html
    assert 'table-cell--mixed table-cell--mixed-rtl' in result.body_html
    assert 'dir="rtl">مستندات عمومی، <span class="md2pdf-ltr-isolate" dir="ltr" lang="en">proposal</span>' in result.body_html
    assert 'dir="rtl">مستندات پروژه‌ای شبیه <span class="md2pdf-ltr-isolate" dir="ltr" lang="en">README</span>' in result.body_html

def test_layout_css_contains_persian_rtl_quality_rules(tmp_path: Path):
    options = PdfOptions(input_path=tmp_path / "input.md", output_path=tmp_path / "out.pdf")
    css, _classes = _layout_css(options, document_direction="rtl")

    assert ".md2pdf-rtl-text" in css
    assert ".mixed-script" in css
    assert ".mixed-numeral" in css
    assert ".table-wrap--rtl table" in css
    assert ".table-cell--mixed" in css
    assert ".table-cell--mixed-rtl" in css
    assert ".table-cell--mixed-ltr" in css
    assert ".table-wrap--rtl .table-cell--mixed:not(.table-cell--mixed-ltr)" in css
    assert "unicode-bidi: plaintext" in css


def test_persian_digits_and_punctuation_get_stable_quality_classes():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "آیا PDF version 1.9.1 با شماره ۱۴۰۵ درست است? پاسخ: بله، پایدار است؛"
    )

    assert 'mixed-script' in result.body_html
    assert 'mixed-numeral' in result.body_html
    assert 'persian-punctuation' in result.body_html
    assert 'rtl-ascii-punctuation' in result.body_html





def test_persian_checked_task_lists_survive_mixed_script_isolation():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "## فهرست وظایف\n\n"
        "- [x] ورودی Markdown\n"
        "- [ ] بازبینی انسانی نهایی\n"
    )

    assert "[x]" not in result.body_html
    assert "task-list" in result.body_html
    assert result.body_html.count('type="checkbox"') == 2
    assert result.body_html.count('checked="checked"') == 1
    assert "ورودی" in result.body_html
    assert "Markdown" in result.body_html

def test_persian_callout_markers_are_normalized_before_ltr_isolation():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "> [!NOTE]\n"
        "> این Callout درباره PDF و Markdown است.\n\n"
        "> [!IMPORTANT]\n"
        "> این متن مهم باید بدون marker خام چاپ شود.\n"
    )

    assert "[!NOTE]" not in result.body_html
    assert "[!IMPORTANT]" not in result.body_html
    assert "callout-note" in result.body_html
    assert "callout-important" in result.body_html
    assert '<strong class="callout-title">نکته</strong>' in result.body_html
    assert '<strong class="callout-title">مهم</strong>' in result.body_html
    assert 'md2pdf-ltr-isolate' in result.body_html

def test_persian_mixed_script_latin_runs_are_isolated_with_trailing_punctuation():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "این متن فارسی با renderer. و GitHub Actions. و PDF navigation? باید در PDF خوانا بماند.\n"
    )

    assert 'md2pdf-ltr-isolate md2pdf-ltr-isolate--punct' in result.body_html
    assert 'dir="ltr" lang="en">renderer.</span>' in result.body_html
    assert 'dir="ltr" lang="en">GitHub Actions.</span>' in result.body_html
    assert 'dir="ltr" lang="en">PDF navigation?</span>' in result.body_html
    assert 'mixed-script' in result.body_html


def test_persian_mixed_script_isolation_skips_inline_code():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "در متن فارسی `renderer.py` باید inline code بماند، اما renderer. باید isolate شود.\n"
    )

    assert '<code dir="ltr">renderer.py</code>' in result.body_html
    assert 'dir="ltr" lang="en">renderer.</span>' in result.body_html
    assert '<span class="md2pdf-ltr-isolate' not in result.body_html.split('<code dir="ltr">renderer.py</code>', 1)[0]


def test_persian_mixed_script_latin_run_keeps_following_footnote_reference_grouped():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "این نمونه زنده renderer.[^pipeline] باید footnote را کنار token نگه دارد.\n\n"
        "[^pipeline]: توضیح فارسی.\n"
    )

    assert 'md2pdf-ltr-isolate-group md2pdf-ltr-isolate-group--footnote' in result.body_html
    assert 'dir="ltr" lang="en"><span class="md2pdf-ltr-isolate md2pdf-ltr-isolate--punct" dir="ltr" lang="en">renderer.</span><sup class="footnote-ref persian-generated-number footnote-ref--rtl"' in result.body_html


def test_single_script_numeral_profiles_are_distinguished():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "شماره ۱۴۰۵ در متن فارسی.\n\n"
        "Version 1.9.1 remains Latin.\n"
    )

    assert 'persian-numeral' in result.body_html
    assert 'latin-numeral' in result.body_html


def test_persian_captions_get_numbered_rtl_caption_classes():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "![نمودار](diagram.svg)\n\n"
        "*شکل ۱۲. نمودار PDF version 1.9.1 و ۱.۹.۱؟*\n"
    )

    assert 'md2pdf-caption--figure' in result.body_html
    assert 'md2pdf-caption--persian' in result.body_html
    assert 'md2pdf-caption--mixed' in result.body_html
    assert 'md2pdf-caption--numbered' in result.body_html
    assert 'mixed-numeral' in result.body_html
    assert 'persian-punctuation' in result.body_html


def test_table_cells_receive_numeral_and_punctuation_profiles():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "| بخش | مقدار | توضیح |\n"
        "|---|---|---|\n"
        "| تاریخ | ۱۴۰۵ | آیا آماده است? |\n"
        "| نسخه | 1.9.1 | پایدار؛ آماده |\n"
    )

    assert 'persian-numeral' in result.body_html
    assert 'latin-numeral' in result.body_html
    assert 'rtl-ascii-punctuation' in result.body_html
    assert 'persian-punctuation' in result.body_html


def test_layout_css_contains_persian_numeral_and_caption_rules(tmp_path: Path):
    options = PdfOptions(input_path=tmp_path / "input.md", output_path=tmp_path / "out.pdf")
    css, _classes = _layout_css(options, document_direction="rtl")

    assert ".persian-numeral" in css
    assert ".latin-numeral" in css
    assert ".persian-punctuation" in css
    assert ".rtl-ascii-punctuation" in css
    assert ".md2pdf-caption--persian" in css
    assert ".md2pdf-caption--numbered" in css
    assert ".md2pdf-ltr-isolate" in css
    assert ".md2pdf-ltr-isolate-group" in css
    assert "unicode-bidi: isolate" in css


def test_persian_toc_uses_rtl_nav_and_localized_section_numbers():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "# معرفی\n\n## نصب\n\n## خروجی PDF\n",
        toc=True,
    )

    assert 'class="md2pdf-toc md2pdf-toc--rtl md2pdf-toc--profiled" dir="rtl"' in result.toc_html
    assert 'class="toc-number persian-generated-number"' in result.toc_html
    assert 'data-md2pdf-number="1-1"' in result.toc_html
    assert '>۱</span>' in result.toc_html
    assert '>۱-۱</span>' in result.toc_html


def test_persian_footnotes_use_localized_markers_and_rtl_section():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "یک ارجاع فارسی[^note].\n\n"
        "[^note]: متن پانویس فارسی با version 1.9.2.\n"
    )

    assert 'class="footnote-ref persian-generated-number footnote-ref--rtl"' in result.body_html
    assert '>۱</a></sup>' in result.body_html
    assert '<section aria-label="پانویس‌ها" class="footnotes footnotes--local footnotes--rtl" dir="rtl">' in result.body_html
    assert 'class="footnote-marker persian-generated-number">۱.</span>' in result.body_html


def test_caption_number_profiles_distinguish_persian_latin_and_mixed_numbers():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "![الف](a.svg)\n\n"
        "*شکل ۱۲. نمودار فارسی.*\n\n"
        "![b](b.svg)\n\n"
        "*Figure 2. English figure.*\n\n"
        "![ج](c.svg)\n\n"
        "*شکل 3 و ۴. نمودار mixed.*\n"
    )

    assert 'md2pdf-caption--persian-number' in result.body_html
    assert 'md2pdf-caption--latin-number' in result.body_html
    assert 'md2pdf-caption--mixed-number' in result.body_html


def test_layout_css_contains_persian_navigation_and_footnote_rules(tmp_path: Path):
    options = PdfOptions(input_path=tmp_path / "input.md", output_path=tmp_path / "out.pdf")
    css, _classes = _layout_css(options, document_direction="rtl")

    assert ".md2pdf-toc--rtl" in css
    assert ".persian-generated-number" in css
    assert ".footnotes--rtl" in css
    assert ".footnote-ref--rtl" in css
    assert ".md2pdf-caption--persian-number" in css


def test_persian_footnote_body_gets_direction_and_number_profiles():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "ارجاع فارسی[^audit].\n\n"
        "[^audit]: متن پانویس با version 1.9.3 و شماره ۱۴۰۵؟\n"
    )

    assert 'footnote-item--persian' in result.body_html
    assert 'footnote-item--mixed-number' in result.body_html
    assert 'class="footnote-body' in result.body_html
    assert 'footnote-body--mixed' in result.body_html
    assert 'data-md2pdf-direction-profile="mixed"' in result.body_html
    assert 'data-md2pdf-number-profile="mixed"' in result.body_html
    assert 'mixed-numeral' in result.body_html
    assert 'persian-punctuation' in result.body_html


def test_persian_caption_profiles_expose_visual_audit_metadata():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "![نمودار](diagram.svg)\n\n"
        "*شکل ۱۲. نمودار PDF version 1.9.3 و ۱۴۰۵؟*\n"
    )

    assert 'md2pdf-caption--profiled' in result.body_html
    assert 'md2pdf-caption--persian' in result.body_html
    assert 'data-md2pdf-direction-profile="mixed"' in result.body_html
    assert 'data-md2pdf-number-profile="mixed"' in result.body_html
    assert 'dir="auto"' in result.body_html


def test_persian_footer_template_uses_readable_page_total_phrase():
    template = _footer_template(
        FooterContext(
            title="راهنمای Mardas Folio",
            metadata="انتشار حرفه‌ای Markdown · 1.9.3 · Stable",
            lang="fa",
            document_direction="rtl",
        ),
        "modern",
        "light",
    )

    assert "صفحه" in template
    assert " از " in template
    assert 'dir="rtl"' in template
    assert 'class="pageNumber"' in template
    assert 'class="totalPages"' in template


def test_layout_css_contains_persian_footnote_caption_audit_rules(tmp_path: Path):
    options = PdfOptions(input_path=tmp_path / "input.md", output_path=tmp_path / "out.pdf")
    css, _classes = _layout_css(options, document_direction="rtl")

    assert ".footnote-body--rtl" in css
    assert ".footnote-body--mixed" in css
    assert ".footnote-item--persian" in css
    assert ".md2pdf-caption--profiled" in css


def test_persian_toc_items_expose_visual_audit_profiles():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "# معرفی\n\n## نصب Python 3.10 و خروجی PDF\n\n## جدول‌های RTL ۱۴۰۵\n",
        toc=True,
    )

    assert 'md2pdf-toc--profiled' in result.toc_html
    assert 'data-md2pdf-number-locale="fa"' in result.toc_html
    assert 'toc-item--mixed-script' in result.toc_html
    assert 'toc-item--persian-number' in result.toc_html
    assert 'data-md2pdf-title-profile="mixed"' in result.toc_html
    assert 'data-md2pdf-title-number-profile="persian"' in result.toc_html
    assert 'data-md2pdf-number-display="۱-۱"' in result.toc_html
    assert 'class="toc-title' in result.toc_html


def test_persian_tables_expose_table_level_visual_audit_metadata():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "| بخش | مقدار | شناسه |\n"
        "|---|---|---|\n"
        "| نسخه | version 1.9.4 و ۱.۹.۴ | PDF |\n"
        "| تاریخ | ۱۴۰۵ | stable |\n"
        "| شناسه | 42 | پایدار |\n"
    )

    assert 'table-wrap--profiled' in result.body_html
    assert 'table-wrap--rtl' in result.body_html
    assert 'table-wrap--mixed-direction' in result.body_html
    assert 'table-wrap--mixed-number' in result.body_html
    assert 'data-md2pdf-direction-profile="mixed"' in result.body_html
    assert 'data-md2pdf-number-profile="mixed"' in result.body_html
    assert 'data-md2pdf-rtl-cells=' in result.body_html
    assert 'data-md2pdf-ltr-cells=' in result.body_html
    assert 'data-md2pdf-mixed-cells=' in result.body_html
    assert 'data-md2pdf-numeric-cells=' in result.body_html
    assert 'data-md2pdf-number-profile="persian"' in result.body_html
    assert 'data-md2pdf-number-profile="latin"' in result.body_html


def test_persian_table_caption_adds_captioned_table_audit_classes():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "| بخش | مقدار |\n"
        "|---|---|\n"
        "| نسخه | ۱.۹.۴ |\n\n"
        "جدول ۱۲. وضعیت خروجی PDF در ۱۴۰۵؟\n"
    )

    assert 'table-wrap--captioned' in result.body_html
    assert 'table-wrap--persian-caption' in result.body_html
    assert 'table-wrap--caption-mixed' in result.body_html
    assert 'md2pdf-caption--table' in result.body_html
    assert 'data-md2pdf-direction-profile="rtl"' in result.body_html
    assert 'data-md2pdf-number-profile="persian"' in result.body_html


def test_layout_css_contains_persian_table_and_toc_visual_audit_rules(tmp_path: Path):
    options = PdfOptions(input_path=tmp_path / "input.md", output_path=tmp_path / "out.pdf")
    css, _classes = _layout_css(options, document_direction="rtl")

    assert ".md2pdf-toc--profiled" in css
    assert ".toc-item--mixed" in css
    assert ".toc-item--mixed-script" in css
    assert ".table-wrap--profiled" in css
    assert ".table-wrap--persian-number" in css
    assert ".table-wrap--mixed-number" in css
    assert ".table-wrap--persian-caption caption" in css


def test_persian_toc_nested_lists_keep_rtl_tree_indentation_hooks():
    result = render_markdown(
        "---\nlang: fa\n---\n\n"
        "# فصل اول\n\n## بخش اول\n\n### زیربخش A ۱۴۰۵\n\n# فصل دوم\n",
        toc=True,
    )

    assert 'class="toc-list toc-depth-2 toc-list--nested" data-depth="2"' in result.toc_html
    assert 'class="toc-list toc-depth-3 toc-list--nested" data-depth="3"' in result.toc_html
    assert 'data-toc-depth="2"' in result.toc_html
    assert 'data-toc-depth="3"' in result.toc_html
    assert 'data-md2pdf-number-display="۱-۱-۱"' in result.toc_html


def test_layout_css_contains_bidirectional_toc_tree_indentation_rules(tmp_path: Path):
    options = PdfOptions(input_path=tmp_path / "input.md", output_path=tmp_path / "out.pdf")
    css, _classes = _layout_css(options, document_direction="rtl")

    assert ".md2pdf-toc--rtl .toc-list--nested" in css
    assert "margin-inline-start: 1.35em" in css
    assert "border-inline-start: 1px solid" in css
    assert "border-inline-end: 0" in css
    assert ".md2pdf-toc--rtl .toc-item > a" in css
    assert "display: inline-flex" in css
    assert "flex-direction: row" in css
    assert "grid-template-columns: minmax(0, 1fr) max-content" not in css
    assert ".md2pdf-toc--ltr .toc-list--nested" in css
    assert "grid-template-columns: max-content minmax(0, 1fr)" in css
