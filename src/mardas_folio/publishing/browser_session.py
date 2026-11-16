"""Thread-affine Chromium lifecycle and per-document browser rendering."""
from __future__ import annotations
import logging
import os
import shutil
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from ..page_geometry import _playwright_page_size_kwargs
from ..quality import FontValidationError, MathJaxRenderError
from ..render_contracts import PdfOptions
from ..runtime import resolved_chromium_path
from .html_document import FooterContext, _footer_template
from .quality import _enforce_quality_issue, _font_directory_manifest, _resolve_quality_options


def _validate_browser_fonts(page: Page, options: PdfOptions, *, artifact: Path) -> None:
    if not options.required_fonts and options.quality_report is None:
        return
    try:
        report = page.evaluate(_FONT_REPORT_SCRIPT, list(options.required_fonts))
    except Exception as exc:
        _enforce_quality_issue(
            options,
            category="fonts",
            policy=options.font_error_policy or "warn",
            message=f"Browser font validation failed: {exc}",
            details={"artifact": artifact.name, "required_fonts": list(options.required_fonts)},
            error_type=FontValidationError,
        )
        return
    details = dict(report or {})
    details["artifact"] = artifact.name
    details["font_directory"] = str(options.font_dir) if options.font_dir else None
    details["font_files"] = _font_directory_manifest(options.font_dir)
    missing = [str(name) for name in details.get("missing") or []]
    if missing:
        _enforce_quality_issue(
            options,
            category="fonts",
            policy=options.font_error_policy or "warn",
            message=f"Required publication fonts are unavailable: {', '.join(missing)}",
            details=details,
            error_type=FontValidationError,
        )
        return
    options.quality_log.record(
        "fonts",
        "passed",
        "Required publication fonts are available." if options.required_fonts else "Browser font evidence collected.",
        details=details,
    )


def _typeset_and_validate_mathjax(page: Page, options: PdfOptions, *, artifact: Path) -> None:
    try:
        report = page.evaluate(_MATHJAX_REPORT_SCRIPT)
    except Exception as exc:
        _enforce_quality_issue(
            options,
            category="mathjax",
            policy=options.math_error_policy or "warn",
            message=f"MathJax rendering failed; equations may remain in TeX form: {exc}",
            details={"artifact": artifact.name, "exception": str(exc)},
            error_type=MathJaxRenderError,
        )
        return
    details = dict(report or {})
    details["artifact"] = artifact.name
    detected = int(details.get("detected") or 0)
    rendered = int(details.get("rendered") or 0)
    unresolved = int(details.get("unresolved") or 0)
    errors = list(details.get("errors") or [])
    exception = str(details.get("exception") or "")
    available = bool(details.get("available"))
    failed = bool(exception or errors or unresolved or (detected and not available) or rendered != detected)
    if failed:
        _enforce_quality_issue(
            options,
            category="mathjax",
            policy=options.math_error_policy or "warn",
            message=(
                "MathJax did not render every detected expression "
                f"(detected={detected}, rendered={rendered}, unresolved={unresolved})."
            ),
            details=details,
            error_type=MathJaxRenderError,
        )
        return
    options.quality_log.record(
        "mathjax",
        "passed",
        f"MathJax rendered {rendered} of {detected} detected expressions.",
        details=details,
    )


def _render_pdf(
    page: Page,
    html_text: str,
    options: PdfOptions,
    path: Path,
    *,
    display_footer: bool,
    footer_context: FooterContext | str,
) -> None:
    _resolve_quality_options(options)
    page.set_content(html_text, wait_until="load")
    page.evaluate("() => document.fonts && document.fonts.ready")
    _validate_browser_fonts(page, options, artifact=path)
    if not options.no_mathjax:
        _typeset_and_validate_mathjax(page, options, artifact=path)
    page.emulate_media(media="print")
    pdf_kwargs: dict[str, Any] = {
        "path": str(path),
        "print_background": True,
        "prefer_css_page_size": True,
        "margin": {"top": "0", "right": "0", "bottom": "0", "left": "0"},
    }
    pdf_kwargs.update(_playwright_page_size_kwargs(options.page_size))
    if display_footer and not options.no_header_footer:
        pdf_kwargs.update(
            {
                "display_header_footer": True,
                "header_template": "<div></div>",
                "footer_template": _footer_template(footer_context, options.style, options.mode),
            }
        )
    page.pdf(**pdf_kwargs)


def _should_disable_chromium_sandbox(mode: str) -> bool:
    normalized = (mode or "auto").strip().lower()
    if normalized == "off":
        return True
    if normalized == "on":
        return False
    if normalized != "auto":
        raise ValueError("chromium_sandbox must be one of: auto, on, off")
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def _chromium_launch_args(options: PdfOptions) -> list[str]:
    args = [
        "--font-render-hinting=medium",
        "--disable-dev-shm-usage",
        # Printing to PDF goes through Skia's vector backend, so the GPU process
        # buys this renderer nothing. On machines without a usable Vulkan/ANGLE
        # driver it also loses: Chromium starts a GPU process, fails to
        # initialise a display, and exits it again on every launch.
        "--disable-gpu",
        # Chromium's default log sink is a debug.log next to the executable,
        # which for a frozen build means writing into the installation
        # directory. Nothing reads that file, and the engine reports its own
        # failures over JSON-RPC.
        "--disable-logging",
        "--log-level=3",
    ]
    if sys.platform == "win32":
        # Headless Shell's separate GPU process initializes its own logging
        # before honoring these switches and writes beside the executable.
        # Acceleration is already disabled; keeping its software service in
        # the browser process avoids that writer in frozen Windows bundles.
        args.append("--in-process-gpu")
    if _should_disable_chromium_sandbox(options.chromium_sandbox):
        args.append("--no-sandbox")
    return args


def _resolve_pdf_chromium_path(options: PdfOptions) -> None:
    """Attach the lazily discovered browser only at the PDF rendering boundary."""

    if options.chromium_path:
        return
    resolved = resolved_chromium_path()
    if resolved is not None:
        options.chromium_path = str(resolved)


class RenderSession:
    """Thread-affine reusable Chromium session for repeated PDF exports.

    A fresh browser context is created for every conversion, so cookies, page
    state, and temporary object URLs never leak between documents.  Only the
    expensive Playwright and Chromium process lifecycle is reused.
    """

    def __init__(self) -> None:
        self._owner_thread: int | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_key: tuple[str | None, tuple[str, ...]] | None = None
        self.launch_count = 0
        self.page_count = 0
        self.last_page_reused_browser = False

    def __enter__(self) -> "RenderSession":
        self._claim_thread()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _claim_thread(self) -> None:
        current = threading.get_ident()
        if self._owner_thread is None:
            self._owner_thread = current
        elif self._owner_thread != current:
            raise RuntimeError("RenderSession must only be used from its owning thread.")

    def _close_browser(self) -> None:
        browser, self._browser = self._browser, None
        self._browser_key = None
        if browser is not None:
            try:
                browser.close()
            except Exception:
                LOGGER.debug("Failed to close reusable Chromium browser", exc_info=True)

    def close(self) -> None:
        self._claim_thread()
        self._close_browser()
        playwright, self._playwright = self._playwright, None
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                LOGGER.debug("Failed to stop reusable Playwright session", exc_info=True)

    def restart(self) -> None:
        """Discard the current browser so the next conversion launches cleanly."""
        self._claim_thread()
        self._close_browser()

    def _ensure_browser(self, options: PdfOptions) -> tuple[Browser, bool]:
        self._claim_thread()
        _resolve_pdf_chromium_path(options)
        executable = options.chromium_path or shutil.which("chromium") or shutil.which("google-chrome")
        key = (executable, tuple(_chromium_launch_args(options)))
        reusable = bool(
            self._browser is not None
            and self._browser_key == key
            and self._browser.is_connected()
        )
        if reusable and self._browser is not None:
            return self._browser, True

        self._close_browser()
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": True, "args": list(key[1])}
        if executable:
            launch_kwargs["executable_path"] = executable
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._browser_key = key
        self.launch_count += 1
        return self._browser, False

    @contextmanager
    def page(self, options: PdfOptions) -> Iterator[Page]:
        browser, reused = self._ensure_browser(options)
        self.last_page_reused_browser = reused
        context: BrowserContext | None = None
        try:
            context = browser.new_context(device_scale_factor=1)
            page = context.new_page()
            page.set_default_timeout(options.timeout_ms)
            self.page_count += 1
            yield page
        except Exception:
            if self._browser is not None and not self._browser.is_connected():
                self.restart()
            raise
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    self.restart()


@contextmanager
def _render_page(
    options: PdfOptions, session: RenderSession | None
) -> Iterator[tuple[Page, bool]]:
    if session is not None:
        with session.page(options) as page:
            yield page, session.last_page_reused_browser
        return
    with RenderSession() as owned_session:
        with owned_session.page(options) as page:
            yield page, False


LOGGER = logging.getLogger("mardas_folio.renderer")


_FONT_REPORT_SCRIPT = r"""
(requiredFonts) => {
  const normalize = value => String(value || '').replace(/["']/g, '').trim().toLowerCase();
  const loadedFaces = Array.from(document.fonts || []).map(face => ({
    family: String(face.family || '').replace(/["']/g, ''),
    status: String(face.status || ''),
    weight: String(face.weight || ''),
    style: String(face.style || ''),
  }));
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  const sample = 'mmmmmmmmmmlliWW00۱۲۳۴۵۶۷۸۹';
  const width = font => {
    context.font = `72px ${font}`;
    return context.measureText(sample).width;
  };
  const fontAvailable = family => {
    const target = normalize(family);
    if (loadedFaces.some(face => normalize(face.family) === target && face.status === 'loaded')) {
      return true;
    }
    return ['monospace', 'serif', 'sans-serif'].some(fallback => {
      const baseline = width(fallback);
      const candidate = width(`"${family}",${fallback}`);
      return Math.abs(candidate - baseline) > 0.01;
    });
  };
  const computed = selector => {
    const node = document.querySelector(selector);
    return node ? getComputedStyle(node).fontFamily : '';
  };
  const required = Array.from(requiredFonts || []);
  const availability = Object.fromEntries(required.map(name => [name, fontAvailable(name)]));
  return {
    status: document.fonts ? document.fonts.status : 'unsupported',
    required: availability,
    missing: required.filter(name => !availability[name]),
    computed: {
      body: computed('body'),
      article: computed('.md2pdf-article'),
      persian: computed('[lang^="fa"], [dir="rtl"]'),
      code: computed('code, pre'),
    },
    loaded_faces: loadedFaces,
  };
}
"""


_MATHJAX_REPORT_SCRIPT = r"""
async () => {
  const nodes = Array.from(document.querySelectorAll('.math'));
  const report = {
    detected: nodes.length,
    rendered: 0,
    unresolved: 0,
    available: Boolean(window.MathJax && window.MathJax.typesetPromise),
    errors: [],
    unresolved_samples: [],
    exception: '',
  };
  try {
    if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
      await window.MathJax.startup.promise;
    }
    if (window.MathJax && window.MathJax.typesetPromise) {
      await window.MathJax.typesetPromise();
    }
  } catch (error) {
    report.exception = String(error && (error.stack || error.message) || error);
  }
  for (const node of nodes) {
    if (node.querySelector('mjx-container')) {
      report.rendered += 1;
    } else {
      report.unresolved += 1;
      if (report.unresolved_samples.length < 5) {
        report.unresolved_samples.push(String(node.textContent || '').trim().slice(0, 160));
      }
    }
  }
  report.errors = Array.from(document.querySelectorAll('mjx-merror, [data-mjx-error]'))
    .slice(0, 10)
    .map(node => String(node.textContent || node.getAttribute('data-mjx-error') || '').trim().slice(0, 240));
  return report;
}
"""
