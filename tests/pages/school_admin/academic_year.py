"""SchoolAdmin → Academic Settings page object (/module/academic_year_and_term)."""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage

HEADING = re.compile(r"^\s*academic settings\s*$", re.I)

# The tab buttons carry a count badge ("Academic Years 3"), so never anchor the tail.
YEARS_TAB = re.compile(r"^\s*academic years\b", re.I)
TERMS_TAB = re.compile(r"^\s*academic terms\b", re.I)

CREATE_YEAR_TRIGGER = re.compile(r"^\s*create academic year\s*$", re.I)
CREATE_TERM_TRIGGER = re.compile(r"^\s*create academic term\s*$", re.I)

YEAR_MODAL = re.compile(r"create new academic year", re.I)
TERM_MODAL = re.compile(r"create new academic term", re.I)

NAME_FIELD = re.compile(r"^\s*name\s*\*?\s*$", re.I)
START_DATE_FIELD = re.compile(r"^\s*start date\s*$", re.I)
END_DATE_FIELD = re.compile(r"^\s*end date\s*$", re.I)
YEAR_SELECT_TRIGGER = re.compile(r"^\s*select academic year\s*$", re.I)

# antd swaps the OK label to "Creating..." while the request is in flight.
SUBMIT_BUTTON = re.compile(r"^\s*creat(e|ing)", re.I)

ACTIVATE_ITEM = re.compile(r"^\s*activate\s*$", re.I)
ACTIVE_BADGE = re.compile(r"^\s*active\s*$", re.I)

YEAR_CREATED_TOAST = re.compile(r"academic year created successfully", re.I)
YEAR_ACTIVATED_TOAST = re.compile(r"academic year activated successfully", re.I)
TERM_CREATED_TOAST = re.compile(r"academic term created successfully", re.I)
TERM_ACTIVATED_TOAST = re.compile(r"academic term activated successfully", re.I)


class AcademicYearTermPage(BasePage):
    URL = "/module/academic_year_and_term"

    def open(self) -> "AcademicYearTermPage":
        super().open()
        expect(self.page.get_by_role("heading", name=HEADING)).to_be_visible(timeout=15_000)
        return self

    # ───────────────────────── academic year ──────────────────────────

    def create_year(
        self,
        *,
        name: str,
        start_date: str,
        end_date: str,
        set_active: bool = True,
    ) -> None:
        """Create an academic year. Dates are "YYYY-MM-DD" (the picker's own format).

        The backend rejects a year whose range overlaps an existing one for the
        same school, so callers must pick disjoint ranges.
        """
        self.show_years()
        self.click_button(CREATE_YEAR_TRIGGER)
        modal = self._modal(YEAR_MODAL)
        expect(modal).to_be_visible(timeout=10_000)

        modal.get_by_label(NAME_FIELD).first.fill(name)
        self._fill_date_range(modal, start_date, end_date)
        self._set_switch(modal, set_active)

        self._submit(modal)
        self.expect_toast(YEAR_CREATED_TOAST, timeout_ms=15_000)
        expect(modal).to_be_hidden(timeout=10_000)

        row = self.year_row(name)
        expect(row).to_be_visible(timeout=15_000)
        # The create payload's is_active is advisory — the backend keeps whatever
        # year it already considers current, so fall back to the explicit route.
        if set_active and not _is_active(row):
            self.activate_year(name)

    def activate_year(self, name: str) -> None:
        self.show_years()
        row = self.year_row(name)
        expect(row).to_be_visible(timeout=15_000)
        if _is_active(row):
            return
        self._row_action(row, ACTIVATE_ITEM)
        self.expect_toast(YEAR_ACTIVATED_TOAST, timeout_ms=15_000)
        expect(self.year_row(name).get_by_text(ACTIVE_BADGE).first).to_be_visible(timeout=15_000)

    def year_row(self, name: str) -> Locator:
        return self._row(name)

    # ───────────────────────── academic term ──────────────────────────

    def create_term(
        self,
        *,
        year_name: str,
        term_name: str,
        start_date: str,
        end_date: str,
        set_active: bool = True,
    ) -> None:
        """Create a term under ``year_name``. Dates are "YYYY-MM-DD"."""
        self.show_terms()
        self.click_button(CREATE_TERM_TRIGGER)
        modal = self._modal(TERM_MODAL)
        expect(modal).to_be_visible(timeout=10_000)

        modal.get_by_label(NAME_FIELD).first.fill(term_name)
        self.select_option_in_combobox(
            YEAR_SELECT_TRIGGER, re.compile(rf"^\s*{re.escape(year_name)}\s*$", re.I)
        )
        self._fill_date_range(modal, start_date, end_date)
        self._set_switch(modal, set_active)

        self._submit(modal)
        self.expect_toast(TERM_CREATED_TOAST, timeout_ms=15_000)
        expect(modal).to_be_hidden(timeout=10_000)

        row = self.term_row(year_name, term_name)
        expect(row).to_be_visible(timeout=15_000)
        if set_active and not _is_active(row):
            self.activate_term(year_name, term_name)

    def activate_term(self, year_name: str, term_name: str) -> None:
        """Activate a term.

        The Academic Terms table only lists terms of the *active* year, so the
        term's year is activated first when it is not already current.
        """
        self.activate_year(year_name)
        self.show_terms()
        row = self.term_row(year_name, term_name)
        expect(row).to_be_visible(timeout=15_000)
        if _is_active(row):
            return
        self._row_action(row, ACTIVATE_ITEM)
        self.expect_toast(TERM_ACTIVATED_TOAST, timeout_ms=15_000)
        expect(
            self.term_row(year_name, term_name).get_by_text(ACTIVE_BADGE).first
        ).to_be_visible(timeout=15_000)

    def term_row(self, year_name: str, term_name: str) -> Locator:
        return self._row(term_name, year_name)

    # ─────────────────────────────  tabs  ──────────────────────────────

    def show_years(self) -> None:
        self.click_button(YEARS_TAB)

    def show_terms(self) -> None:
        self.click_button(TERMS_TAB)

    # ──────────────────────────── internals ───────────────────────────

    def _modal(self, title: re.Pattern[str]) -> Locator:
        """Scope to one antd Modal — all three stay mounted once opened."""
        return self.page.get_by_role("dialog").filter(has_text=title).first

    def _fill_date_range(self, modal: Locator, start_date: str, end_date: str) -> None:
        """Type into the RangePicker inputs instead of driving the calendar.

        antd's default display format here is "YYYY-MM-DD", which is what the
        caller already passes, so the strings go in verbatim. Each half is
        committed by clicking its panel cell rather than pressing Enter — see
        BasePage.commit_date for why Enter is unsafe in these forms.
        """
        self.commit_date(modal.get_by_placeholder(START_DATE_FIELD).first, start_date)
        self.commit_date(modal.get_by_placeholder(END_DATE_FIELD).first, end_date)

    def _set_switch(self, modal: Locator, on: bool) -> None:
        switch = modal.get_by_role("switch").first
        if (switch.get_attribute("aria-checked") == "true") != on:
            switch.click()

    def _submit(self, modal: Locator) -> None:
        ok = modal.get_by_role("button", name=SUBMIT_BUTTON).first
        # antd keeps OK disabled until name + dates (+ year, for terms) are set,
        # so this doubles as the assertion that the form took every value.
        expect(ok).to_be_enabled(timeout=10_000)
        ok.click()

    def _row(self, *texts: str) -> Locator:
        row = self.page.get_by_role("row")
        for text in texts:
            row = row.filter(has_text=re.compile(re.escape(text), re.I))
        return row.first

    def _row_action(self, row: Locator, item: re.Pattern[str]) -> None:
        row.get_by_role("button").last.click()
        self.page.get_by_role("menuitem", name=item).first.click()


def _is_active(row: Locator) -> bool:
    """Read the Status badge. Anchored so "Inactive" does not count as active."""
    return row.get_by_text(ACTIVE_BADGE).count() > 0
