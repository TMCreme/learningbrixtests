"""Base page object — shared helpers all pages can rely on."""
from __future__ import annotations

import re
from datetime import datetime
from typing import ClassVar

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect


def as_pattern(text: str | re.Pattern[str], flags: int = re.I) -> re.Pattern[str]:
    """Normalize to a pattern Playwright can serialize into a selector.

    playwright-python renders a Pattern as ``/<source>/<flags>`` inside the
    internal selector and escapes only quotes and ``>>``. An unescaped ``/`` in
    the source — e.g. an academic year named "2026/2027" — closes that literal
    early, so ``internal:role=option[name=/.../i]`` fails to parse.
    """
    pattern = text if isinstance(text, re.Pattern) else re.compile(text, flags)
    if "/" not in pattern.pattern:
        return pattern
    return re.compile(re.sub(r"(?<!\\)/", r"\\/", pattern.pattern), pattern.flags)


class BasePage:
    URL: ClassVar[str | None] = None

    def __init__(self, page: Page, frontend_base_url: str):
        self.page = page
        self.frontend_base_url = frontend_base_url.rstrip("/")

    # ─────────────────────── navigation ──────────────────────────

    def open(self) -> "BasePage":
        if not self.URL:
            raise RuntimeError(f"{type(self).__name__} has no URL set.")
        goto(self.page, self.frontend_base_url + self.URL)
        return self

    def absolute(self, route: str) -> str:
        if route.startswith("http"):
            return route
        return self.frontend_base_url + ("" if route.startswith("/") else "/") + route

    # ───────────────────── common locators ───────────────────────

    def toast(self, pattern: str | re.Pattern):
        """Match react-hot-toast text. Tolerant to surrounding markup."""
        return self.page.get_by_text(as_pattern(pattern))

    def expect_toast(self, pattern: str | re.Pattern, timeout_ms: int = 8_000) -> None:
        expect(self.toast(pattern)).to_be_visible(timeout=timeout_ms)

    def dialog(self):
        return self.page.get_by_role("dialog")

    def click_button(self, name: str | re.Pattern) -> None:
        self.page.get_by_role("button", name=as_pattern(name)).first.click()

    def fill_labeled(self, label: str | re.Pattern, value: str, *, in_dialog: bool = False) -> None:
        pattern = as_pattern(label)
        scope = self.dialog() if in_dialog else self.page
        # Try label first (proper <label for=...> association), fall back to placeholder.
        loc = scope.get_by_label(pattern).first
        if loc.count() == 0:
            loc = scope.get_by_placeholder(pattern).first
        loc.fill(value)

    def commit_date(self, picker, value: str, *,
                    display_format: str | None = None) -> None:
        """Set an antd DatePicker without pressing Enter.

        Typing then pressing Enter is antd's documented commit gesture, but
        several of these pickers sit inside a bare ``<form>`` that has no
        ``onSubmit`` handler (e.g. staff BasicInformation). Enter therefore
        triggers a *native* form submit, the page reloads, and every field the
        step had collected is silently wiped — the symptom being a Continue
        button that never enables.

        Clicking the highlighted cell in the open panel commits the same value
        without the keystroke ever reaching the form.

        Pickers across this app declare different ``format`` props, and their
        placeholders are not reliable hints ("Date of Birth" tells us nothing).
        So ``value`` is typed verbatim unless the caller names the
        ``display_format`` its picker actually renders.
        """
        iso, display = _date_forms(value, display_format)
        picker.click()
        picker.fill(display)

        # The panel highlights the typed date; either selector finds it. It is
        # looked for inside the panel that is actually *open* first: antd leaves
        # every dropdown it has rendered mounted-but-hidden, so on a form with
        # two DatePickers (e.g. the Create Assessment modal's Scheduled/Due
        # dates) a page-wide match resolves to the closed picker's cell and then
        # waits forever for a hidden element to become clickable.
        panel = self.page.locator(".ant-picker-dropdown:visible").last
        roots = [panel, self.page] if panel.count() else [self.page]
        for root in roots:
            cell = root.locator(f'.ant-picker-cell-selected, td[title="{iso}"]').first
            if cell.count():
                cell.click()
                return

        # No panel (not an antd picker after all) — blur to commit and let the
        # caller's own assertion catch it if the value did not stick.
        picker.blur()

    def select_option_by_label(self, label: str | re.Pattern,
                               option_text: str | re.Pattern) -> None:
        """Pick from a combobox identified by its adjacent <label>.

        Use this instead of ``select_option_in_combobox`` when the trigger has
        no readable text to filter on. A Radix Select whose ``value`` matches no
        item — e.g. the non-teaching role dropdown, which initialises to
        ``role_id: 0`` — renders an *empty* trigger rather than falling back to
        its placeholder, so matching on placeholder text finds nothing.

        These fields are laid out as ``<div><label>…</label><Select/></div>``,
        so the label's parent scopes the search.

        The label is looked for among real ``<label>`` elements first. The
        sidebar carries link text identical to several field labels — nav-config
        lists "Syllabus" — and it is far earlier in the DOM, so a bare
        ``get_by_text(...).first`` resolves to the nav item, whose parent holds
        no combobox at all. Anything that is not marked up as a ``<label>`` still
        falls back to the plain text match.
        """
        l_pattern = label if isinstance(label, re.Pattern) else re.compile(label, re.I)
        o_pattern = (option_text if isinstance(option_text, re.Pattern)
                     else re.compile(option_text, re.I))
        labels = self.page.locator("label").filter(has_text=l_pattern)
        node = labels.first if labels.count() else self.page.get_by_text(l_pattern).first
        group = node.locator("xpath=..")
        group.get_by_role("combobox").first.click()
        self.page.get_by_role("option", name=o_pattern).first.click()

    def select_option_in_combobox(self, trigger_text: str | re.Pattern,
                                  option_text: str | re.Pattern) -> None:
        """Radix combobox pattern used everywhere in the app."""
        self.page.get_by_role("combobox").filter(has_text=as_pattern(trigger_text)).first.click()
        self.page.get_by_role("option", name=as_pattern(option_text)).first.click()


def _date_forms(value: str, display_format: str | None = None) -> tuple[str, str]:
    """Return (iso, display) for a date given in either notation.

    The ISO form is what antd puts in the panel cell's ``title`` attribute. The
    display form is what gets typed — the caller's own string unless it asked
    for a specific format.
    """
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(value, fmt).date()
        except ValueError:
            continue
        display = parsed.strftime(display_format) if display_format else value
        return parsed.isoformat(), display
    return value, value


def goto(page: Page, url: str, *, attempts: int = 3) -> None:
    """``page.goto`` that survives the dev server aborting a cold navigation.

    The frontend under test is a ``next dev`` server, which compiles a route the
    first time anyone asks for it. While that compile is in flight the request
    can be dropped and Chromium reports

        Page.goto: net::ERR_ABORTED at http://localhost:3000/module/<route>

    which is not a failure of the page — the very same navigation succeeds a
    second later, and the routes it hits are whichever ones this session happens
    to reach first. Only ERR_ABORTED is retried; every other navigation error is
    raised untouched, and the last abort is re-raised if it never settles.
    """
    last: PlaywrightError | None = None
    for attempt in range(attempts):
        try:
            page.goto(url)
            return
        except PlaywrightError as exc:
            if "ERR_ABORTED" not in str(exc):
                raise
            last = exc
            if attempt < attempts - 1:
                page.wait_for_timeout(2_000)
    assert last is not None
    raise last


def goto_module(page: Page, frontend_base_url: str, route: str) -> None:
    """Navigate directly to /module/<route>."""
    url = frontend_base_url.rstrip("/") + "/module/" + route.lstrip("/")
    goto(page, url)
