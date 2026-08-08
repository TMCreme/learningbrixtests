"""Video-recording fixtures for feature demo tests.

Why a dedicated browser instead of reusing pytest-playwright's ``page``:
Playwright's ``slow_mo`` is a *browser launch* option, not a context option, so
the only way to get watchable footage without slowing the whole assertion suite
is to launch a second browser just for demo runs.

Video files only materialise when the context closes, and the path is only
readable from ``page.video.path()`` after that — so the fixture closes the
context in teardown, then moves the file to a deterministic
``<feature_id>.webm`` and writes the caption manifest beside it.

Usage:

    @pytest.mark.demo(
        feature_id="academics.classes.create",
        title="Classes & Timetables",
        subtitle="SchoolAdmin creates a class",
    )
    def test_school_admin_creates_class(demo):
        with demo.step("Log in as SchoolAdmin"):
            ...
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from config.settings import ROOT, Settings
from tests.support.demo import DemoRecorder, slugify


# The Next.js dev-tools badge sits bottom-left of every page under `next dev`
# and would otherwise be burned into every demo video. Hidden here rather than
# by setting `devIndicators: false` in the frontend repo: this touches nothing
# the app ships, works whatever Next version is running, and cannot leak into a
# build.
#
# It has to be an inline style set by a MutationObserver, not an injected
# <style>: Next's hydration replaces <head>, which silently drops any stylesheet
# added by an init script (verified — the tag was gone by the time the page
# settled). The badge also renders its visible content inside a shadow root, so
# the host element measures 0x0 and cannot be found by geometry — it must be
# matched by tag name.
_HIDE_DEV_OVERLAY = """
(() => {
  const SELECTOR = 'nextjs-portal, [data-nextjs-toast], [data-next-badge-root],' +
                   '#__next-build-watcher, #__next-prerender-indicator';
  const hide = () => {
    document.querySelectorAll(SELECTOR).forEach((el) => {
      el.style.setProperty('display', 'none', 'important');
    });
  };
  hide();
  const start = () => {
    hide();
    new MutationObserver(hide).observe(document.documentElement, {
      childList: true, subtree: true,
    });
  };
  if (document.documentElement) start();
  else document.addEventListener('DOMContentLoaded', start);
})();
"""


@dataclass
class DemoSession:
    """What a demo test drives: a page, plus the narration recorder."""

    page: Page
    context: BrowserContext
    recorder: DemoRecorder
    frontend_base_url: str

    def step(self, caption: str, *, dwell_ms: int = 600):
        return self.recorder.step(caption, dwell_ms=dwell_ms)

    def note(self, caption: str) -> None:
        self.recorder.note(caption)


@pytest.fixture(scope="session")
def demo_browser(browser_type, settings: Settings):
    """Dedicated slow-mo browser for demo recording.

    Kept separate so VIDEO_SLOW_MO_MS never leaks into the assertion suite.
    """
    if not settings.video_enabled:
        yield None
        return
    browser = browser_type.launch(
        headless=settings.headless,
        slow_mo=settings.video_slow_mo_ms,
    )
    yield browser
    browser.close()


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else ROOT / p


@pytest.fixture
def demo(request, demo_browser: Browser | None, settings: Settings):
    """Yield a DemoSession recording video for one feature."""
    marker = request.node.get_closest_marker("demo")
    if marker is None:
        pytest.fail(
            "The `demo` fixture requires a @pytest.mark.demo(feature_id=..., "
            "title=..., subtitle=...) marker so the video can be named and "
            "titled."
        )
    if demo_browser is None:
        pytest.skip("VIDEO_ENABLED=false — skipping demo recording test.")

    feature_id: str = marker.kwargs.get("feature_id") or slugify(request.node.name)
    title: str = marker.kwargs.get("title", feature_id)
    subtitle: str = marker.kwargs.get("subtitle", "")

    raw_dir = _resolve(settings.video_raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    scratch = raw_dir / f".{slugify(feature_id)}"
    scratch.mkdir(parents=True, exist_ok=True)

    context = demo_browser.new_context(
        viewport={"width": settings.video_width, "height": settings.video_height},
        base_url=settings.frontend_base_url,
        record_video_dir=str(scratch),
        record_video_size={"width": settings.video_width, "height": settings.video_height},
    )
    context.add_init_script(_HIDE_DEV_OVERLAY)

    page = context.new_page()
    page.set_default_timeout(settings.default_timeout_ms)
    page.set_default_navigation_timeout(settings.navigation_timeout_ms)

    recorder = DemoRecorder(feature_id=feature_id, title=title, subtitle=subtitle)
    recorder.reset_clock()
    started = time.monotonic()

    session = DemoSession(
        page=page,
        context=context,
        recorder=recorder,
        frontend_base_url=settings.frontend_base_url,
    )

    try:
        yield session
    finally:
        duration = time.monotonic() - started
        recorder.failed = bool(getattr(request.node, "_demo_failed", False))

        video = page.video
        context.close()  # flushes the .webm; path is only valid after this

        slug = slugify(feature_id)
        target = raw_dir / f"{slug}.webm"
        if video is not None:
            try:
                shutil.move(video.path(), target)
            except Exception as exc:  # noqa: BLE001 — never mask the test result
                print(f"[demo] could not move video for {feature_id}: {exc}")
        shutil.rmtree(scratch, ignore_errors=True)

        recorder.write_manifest(
            raw_dir / f"{slug}.json",
            video_path=target,
            duration_s=duration,
        )
