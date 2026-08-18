"""A visible mouse pointer for demo recordings.

Playwright records video through Chrome's screencast API, which captures the
page viewport and nothing else — the real OS cursor is never composited into the
frames. So a demo video shows fields filling and dialogs opening with no
indication of what is doing it. This draws a synthetic pointer *into the page*
so the recording shows the pointer travelling to a control and clicking it.

Two halves, and both are needed:

1. ``CURSOR_SCRIPT`` — an init script that adds an arrow following real
   ``mousemove`` events, with a ripple on ``mousedown``. Playwright's mouse
   dispatches genuine events, so the arrow tracks whatever the test drives.

2. ``install_glide()`` — Playwright *teleports* the mouse: ``locator.click()``
   jumps straight to the target, so a naive cursor blinks from place to place
   instead of moving. The patch below moves the mouse to the target first, waits
   for the travel to land, and only then performs the action.

The travel itself is animated by CSS rather than by dispatching interpolated
move events. A CSS transition on ``transform`` renders the same smooth glide
however abruptly the coordinates arrive, which means even an action this module
does not wrap still looks like movement rather than a jump.

Nothing here is active outside demo recording: the init script is only added to
the demo context, and the patch only engages for pages registered by that
fixture.
"""
from __future__ import annotations

import weakref
from typing import Any, Callable

from playwright.sync_api import Locator, Page


# How long the CSS transition takes the pointer from one place to the next.
TRAVEL_MS = 280

# How long to wait after moving before performing the action, so the click lands
# once the pointer has arrived rather than while it is still travelling. Set by
# install_glide() from the browser's slow_mo: slow_mo already pauses between
# actions, and on a demo browser (400ms) that pause alone outlasts the travel —
# waiting again on top would add ~0.7s to every click for nothing, and the
# longest video is already 59s against the render cap.
_settle_ms = 0

CURSOR_SCRIPT = """
(() => {
  const TRAVEL_MS = %(travel)d;
  const ID = '__demo_cursor__';

  // An init script runs before the document exists, so documentElement can be
  // null here. Creating eagerly threw and took the whole script — listeners
  // included — down with it, which is why the first recording had no cursor at
  // all. Everything is therefore created lazily, on the first event that needs
  // it.
  const make = () => {
    if (!document.documentElement) return null;
    let el = document.getElementById(ID);
    if (el) return el;

    el = document.createElement('div');
    el.id = ID;
    // documentElement, not body: a framework that swaps <body> during hydration
    // would otherwise take the cursor with it.
    el.style.cssText = [
      'position:fixed', 'top:0', 'left:0',
      'width:26px', 'height:26px',
      'z-index:2147483647',
      'pointer-events:none',
      'opacity:0',
      'will-change:transform',
      'transition:transform ' + TRAVEL_MS + 'ms cubic-bezier(.33,.02,.24,1), opacity 140ms linear',
    ].join(';');
    // A pointer that stays legible on both light panels and dark sidebars:
    // white fill, dark outline, soft shadow.
    el.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 26 26" fill="none"' +
      ' xmlns="http://www.w3.org/2000/svg"' +
      ' style="filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))">' +
      '<path d="M5 2.2 L5 19.4 L9.5 15.2 L12.4 21.6 L15.4 20.2 L12.6 14 L18.6 13.6 Z"' +
      ' fill="#FFFFFF" stroke="#14171C" stroke-width="1.4" stroke-linejoin="round"/>' +
      '</svg>';
    document.documentElement.appendChild(el);
    return el;
  };

  let x = -100, y = -100;

  const place = (nx, ny) => {
    x = nx; y = ny;
    const cursor = make();
    if (!cursor) return;
    cursor.style.opacity = '1';
    cursor.style.transform = 'translate3d(' + nx + 'px,' + ny + 'px,0)';
  };

  addEventListener('mousemove', (e) => place(e.clientX, e.clientY), true);

  addEventListener('mousedown', (e) => {
    place(e.clientX, e.clientY);
    if (!document.documentElement) return;
    const ring = document.createElement('div');
    ring.style.cssText = [
      'position:fixed', 'top:0', 'left:0',
      'width:34px', 'height:34px', 'margin:-17px 0 0 -17px',
      'border-radius:50%%',
      'border:2px solid rgba(64,132,255,.95)',
      'background:rgba(64,132,255,.22)',
      'z-index:2147483646', 'pointer-events:none',
      'transform:translate3d(' + e.clientX + 'px,' + e.clientY + 'px,0) scale(.35)',
    ].join(';');
    document.documentElement.appendChild(ring);
    // Web Animations API: no stylesheet to be dropped by hydration.
    const anim = ring.animate(
      [
        { transform: ring.style.transform, opacity: 0.95 },
        { transform: 'translate3d(' + e.clientX + 'px,' + e.clientY + 'px,0) scale(1.6)', opacity: 0 },
      ],
      { duration: 480, easing: 'cubic-bezier(.2,.7,.3,1)' }
    );
    anim.onfinish = () => ring.remove();
  }, true);

  // The app re-renders constantly; if anything detaches the cursor, put it back
  // without losing where it was.
  const watch = () => {
    if (!document.documentElement) return;
    new MutationObserver(() => {
      if (!document.getElementById(ID) && x > -50) place(x, y);
    }).observe(document.documentElement, { childList: true, subtree: false });
  };
  if (document.documentElement) watch();
  else addEventListener('DOMContentLoaded', watch);
})();
""" % {"travel": TRAVEL_MS}


# Pages the glide applies to. A WeakSet so a closed page does not keep its
# context alive, and so the assertion suite's own pages are never affected.
_GLIDING: "weakref.WeakSet[Page]" = weakref.WeakSet()

# Actions worth showing the pointer travel for. `fill` is included because a
# form filling itself with the pointer parked elsewhere reads as ghost typing —
# which is exactly what the first recording showed.
_PATCHED = ("click", "dblclick", "hover", "check", "uncheck", "select_option", "fill")

# The same actions on Page, which take a selector instead of being bound to one.
# Both surfaces have to be covered: the page objects mix `page.fill("input…")`
# with `page.get_by_role(…).click()`, and a cursor that only tracks one of them
# jumps around a form it is supposedly filling.
_PATCHED_PAGE = _PATCHED + ("type", "tap")

_installed = False


def register(page: Page) -> None:
    """Glide for this page's actions."""
    _GLIDING.add(page)


def _glide_to(locator: Locator) -> None:
    """Walk the pointer to the locator, then let the travel land."""
    page = locator.page
    try:
        locator.scroll_into_view_if_needed(timeout=5_000)
        box = locator.bounding_box(timeout=5_000)
    except Exception:  # noqa: BLE001 — never fail an action for the cursor's sake
        return
    if not box or not box.get("width") or not box.get("height"):
        return
    try:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        if _settle_ms:
            page.wait_for_timeout(_settle_ms)
    except Exception:  # noqa: BLE001
        return


def install_glide(slow_mo_ms: int = 0) -> None:
    """Patch Locator and Page actions so demo pages show the pointer travelling.

    ``slow_mo_ms`` is the recording browser's slow_mo. Playwright already pauses
    that long between actions, so only the shortfall against the travel time
    needs waiting for — usually none.

    Patching the Locator class is what makes this work across all 90-odd tests
    without editing any of them — they call ``locator.click()`` directly far more
    often than they go through a page-object helper. Non-demo pages are left
    completely alone.
    """
    global _installed, _settle_ms
    _settle_ms = max(0, TRAVEL_MS - int(slow_mo_ms))
    if _installed:
        return

    def wrap_locator(name: str) -> None:
        original: Callable[..., Any] = getattr(Locator, name)

        def patched(self: Locator, *args: Any, **kwargs: Any) -> Any:
            try:
                gliding = self.page in _GLIDING
            except Exception:  # noqa: BLE001
                gliding = False
            if gliding:
                _glide_to(self)
            return original(self, *args, **kwargs)

        patched.__name__ = name
        patched.__doc__ = original.__doc__
        setattr(Locator, name, patched)

    def wrap_page(name: str) -> None:
        original: Callable[..., Any] = getattr(Page, name, None)
        if original is None:
            return

        def patched(self: Page, selector: str, *args: Any, **kwargs: Any) -> Any:
            if self in _GLIDING:
                try:
                    _glide_to(self.locator(selector).first)
                except Exception:  # noqa: BLE001
                    pass
            return original(self, selector, *args, **kwargs)

        patched.__name__ = name
        patched.__doc__ = original.__doc__
        setattr(Page, name, patched)

    for action in _PATCHED:
        wrap_locator(action)
    for action in _PATCHED_PAGE:
        wrap_page(action)
    _installed = True
