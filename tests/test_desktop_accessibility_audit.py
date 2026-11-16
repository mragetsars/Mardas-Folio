"""Structural checks must recognize native HTML label associations."""

import pytest

from scripts.audit_desktop_accessibility import DEFAULT_INPUT, audit_html


@pytest.mark.parametrize("tag", ["input", "select", "textarea"])
def test_external_label_names_its_control(tag):
    html = f'<label for="setting">تنظیمات</label><{tag} id="setting"></{tag}>'
    assert not any(item.code == "A11Y-FORM-LABEL" for item in audit_html(html))


@pytest.mark.parametrize(
    "label",
    [
        '<label for="different">Theme</label>',
        '<label for="setting"> </label>',
        '<label>Theme</label>',
    ],
)
def test_unrelated_or_empty_label_does_not_name_a_control(label):
    findings = audit_html(f'{label}<input id="setting">')
    assert [item.element for item in findings if item.code == "A11Y-FORM-LABEL"] == [
        "input#setting"
    ]


def test_desktop_html_has_no_structural_accessibility_findings():
    assert audit_html(DEFAULT_INPUT.read_text(encoding="utf-8")) == []
