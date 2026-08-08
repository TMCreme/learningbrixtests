"""Income & Expenses page object (``/module/income_and_expenses``).

One screen, four tabs — Income, Expenses, Income Types, Expense Types — all
rendered by ``smsfrontend/src/app/module/income_and_expenses/page.tsx``. The tab
decides three things at once: the ``<h1>`` ("Manage Income" vs "Manage Income
Types"), which toolbar button appears ("Add Income" vs "New income Type"), and
which table is mounted. So every helper here names the tab it needs and selects
it first rather than assuming what is on screen.

Things about this screen that shaped the selectors
    * **The modals are not dialogs.** Every one of them is a bare
      ``<div class="fixed inset-0 …">`` with an ``<h3>`` title — no ``role``,
      no ``aria-modal`` — so ``BasePage.dialog()`` finds nothing and the fields
      are addressed by placeholder at page level. Only one modal can be open at
      a time (each has its own ``show*Modal`` boolean), which is what makes that
      safe.
    * **Labels are bare ``<label>`` with no ``for``.** Same trap as the staff
      wizard: ``get_by_label`` never binds. Text inputs are therefore matched on
      their placeholder, and the three Radix selects on the Add/Edit Income form
      go through ``BasePage.select_option_by_label``, which anchors on the
      adjacent ``<label>`` — the "Type*" trigger starts on ``value=""`` and
      cannot be filtered on by its own text.
    * **The academic-year options read "2026/2027 (active)".** That slash would
      close Playwright's ``/<source>/<flags>`` selector literal, so the option
      pattern is built through ``tests.pages.base.as_pattern``.
    * **Tab buttons carry a count badge**, so their accessible name is
      "Income 1", not "Income" — never anchor the tail of those patterns to the
      word alone.

Deliberately left blank: the income type's **Ledger Account Code**. Setting one
makes ``FinanceService.create_income``/``update_income`` post a journal through
``LedgerService`` for every income that uses the type, which drags the whole
chart-of-accounts module into a walkthrough about recording income. The field is
optional in the modal and in ``IncomeTypeCreate``; the ledger is its own unit.

Deliberately not asserted: **Payment Method**. The form offers it and the table
renders a column for it, but ``school_income`` has no such column and both
``create_income`` and ``update_income`` pop the value off the payload before it
reaches the model — it survives only as a field on the ledger journal. Asserting
it in the register would be asserting a value the backend never stores.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── page chrome (components/Header.tsx) ──────────────────────────────────────
# The <h1> is derived from the active tab, so each is anchored exactly:
# "Manage Income" must not also match "Manage Income Types".
INCOME_HEADING = re.compile(r"^\s*Manage Income\s*$", re.I)
INCOME_TYPES_HEADING = re.compile(r"^\s*Manage Income Types\s*$", re.I)
# What page.tsx renders instead of the workspace when any mount fetch fails.
LOAD_FAILURE = re.compile(r"Failed to load income & expenses data", re.I)

# ── tabs (components/Tabs.tsx) — each button ends in a count badge ───────────
INCOME_TAB = re.compile(r"^\s*Income\s*\d*\s*$", re.I)
EXPENSES_TAB = re.compile(r"^\s*Expenses\s*\d*\s*$", re.I)
INCOME_TYPES_TAB = re.compile(r"^\s*Income Types\s*\d*\s*$", re.I)
EXPENSE_TYPES_TAB = re.compile(r"^\s*Expense Types\s*\d*\s*$", re.I)

# ── toolbar ──────────────────────────────────────────────────────────────────
ADD_INCOME_BUTTON = re.compile(r"^\s*Add Income\s*$", re.I)
# Built as `New ${activeTab.split('-')[0]} Type`, so the middle word is the raw
# tab id and really is lowercase on screen.
NEW_INCOME_TYPE_BUTTON = re.compile(r"^\s*New income Type\s*$", re.I)
# `Search ${activeTab.split('-')[0]} records...` — the ellipsis is left off.
INCOME_SEARCH_FIELD = re.compile(r"^\s*Search income records", re.I)

# ── modal titles (<h3>) ──────────────────────────────────────────────────────
ADD_INCOME_TYPE_HEADING = re.compile(r"^\s*Add Income Type\s*$", re.I)
ADD_INCOME_HEADING = re.compile(r"^\s*Add Income\s*$", re.I)
EDIT_INCOME_HEADING = re.compile(r"^\s*Edit Income\s*$", re.I)

# ── modal fields ─────────────────────────────────────────────────────────────
INCOME_TYPE_NAME_FIELD = re.compile(r"^\s*Enter income type name\s*$", re.I)
AMOUNT_FIELD = re.compile(r"^\s*Enter income amount\s*$", re.I)
# Shared by the income-type modal and the income modal; only one is ever open.
REMARKS_FIELD = re.compile(r"^\s*Add additional remarks\s*$", re.I)
# The three Radix selects, addressed by their adjacent <label>.
TYPE_LABEL = re.compile(r"^\s*Type\s*\*\s*$", re.I)
ACADEMIC_YEAR_LABEL = re.compile(r"^\s*Academic Year\s*\*\s*$", re.I)
PAYMENT_METHOD_LABEL = re.compile(r"^\s*Payment Method\s*$", re.I)

# ── modal actions ────────────────────────────────────────────────────────────
# Both flip while the request is in flight ("Saving…", "Creating…", "Updating…").
SAVE_BUTTON = re.compile(r"^\s*(Save Data|Saving\.{0,3}|Creating\.{0,3})\s*$", re.I)
UPDATE_BUTTON = re.compile(r"^\s*(Update Data|Updating\.{0,3})\s*$", re.I)
DISCARD_BUTTON = re.compile(r"^\s*Discard\s*$", re.I)

# ── row menu (components/IncomeTable.tsx) ────────────────────────────────────
EDIT_INCOME_ITEM = re.compile(r"^\s*Edit income\s*$", re.I)
DELETE_INCOME_ITEM = re.compile(r"^\s*Delete income\s*$", re.I)

# ── toasts (react-hot-toast, fired from page.tsx) ────────────────────────────
# Anchored: "Income created successfully" must not be satisfied by the income
# *type* toast that may still be on screen from the previous step.
INCOME_TYPE_CREATED_TOAST = re.compile(r"^\s*Income type created successfully", re.I)
INCOME_CREATED_TOAST = re.compile(r"^\s*Income created successfully", re.I)
INCOME_UPDATED_TOAST = re.compile(r"^\s*Income updated successfully", re.I)


class IncomeExpensesPage(BasePage):
    URL = "/module/income_and_expenses"

    # ─────────────────────────── navigation ──────────────────────────

    def open(self) -> "IncomeExpensesPage":
        super().open()
        self.expect_loaded()
        return self

    def expect_loaded(self, timeout_ms: int = 30_000) -> None:
        """The Income tab is the default, so its heading is the landing signal.

        The PageError check is not decoration: the mount fetches academic years,
        income types, expenses and both statistics endpoints, and any one of them
        failing replaces the whole workspace with that panel — which would
        otherwise show up much later as an inexplicable missing button.
        """
        expect(
            self.page.get_by_role("heading", name=INCOME_HEADING)
        ).to_be_visible(timeout=timeout_ms)
        self.expect_no_load_failure()

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(as_pattern(LOAD_FAILURE))).to_have_count(0)

    def show_income(self) -> None:
        self.click_button(INCOME_TAB)
        expect(self.page.get_by_role("heading", name=INCOME_HEADING)).to_be_visible(
            timeout=15_000
        )

    def show_income_types(self) -> None:
        self.click_button(INCOME_TYPES_TAB)
        expect(
            self.page.get_by_role("heading", name=INCOME_TYPES_HEADING)
        ).to_be_visible(timeout=15_000)

    # ───────────────────────── income types ──────────────────────────

    def create_income_type(self, *, name: str, description: str = "") -> None:
        """Add an income source from the Income Types tab.

        Names are unique per branch (``FinanceService.create_income_type`` 400s a
        duplicate), so callers pass a run-tagged name.
        """
        self.click_button(NEW_INCOME_TYPE_BUTTON)
        heading = self.page.get_by_role("heading", name=ADD_INCOME_TYPE_HEADING)
        expect(heading).to_be_visible(timeout=15_000)

        self.page.get_by_placeholder(as_pattern(INCOME_TYPE_NAME_FIELD)).fill(name)
        if description:
            self.page.get_by_placeholder(as_pattern(REMARKS_FIELD)).fill(description)

        self.click_button(SAVE_BUTTON)
        self.expect_toast(INCOME_TYPE_CREATED_TOAST, timeout_ms=20_000)
        # The modal only unmounts on success, so this is the second half of the
        # assertion rather than a tidy-up.
        expect(heading).to_have_count(0, timeout=15_000)

    def expect_income_type_row(self, name: str) -> None:
        expect(self.row(name)).to_be_visible(timeout=20_000)

    # ──────────────────────────── income ─────────────────────────────

    def create_income(
        self,
        *,
        amount: str,
        income_type: str,
        academic_year: str,
        transaction_date: str = "",
        payment_method: str = "",
        description: str = "",
    ) -> None:
        """Record one income against a type and an academic year.

        ``transaction_date`` is ISO (``YYYY-MM-DD``) — this picker is a native
        ``<input type="date">``, not an antd one, so it is filled directly and no
        key is ever pressed (see trap 1 in the repo notes: Enter inside these
        bare forms fires a native submit).
        """
        self.click_button(ADD_INCOME_BUTTON)
        heading = self.page.get_by_role("heading", name=ADD_INCOME_HEADING)
        expect(heading).to_be_visible(timeout=15_000)

        self.fill_income_form(
            amount=amount,
            income_type=income_type,
            academic_year=academic_year,
            transaction_date=transaction_date,
            payment_method=payment_method,
            description=description,
        )

        self.click_button(SAVE_BUTTON)
        self.expect_toast(INCOME_CREATED_TOAST, timeout_ms=25_000)
        expect(heading).to_have_count(0, timeout=15_000)

    def open_edit_form(self, row_text: str) -> None:
        """Reopen a recorded income through its row menu.

        The menu offers "Edit income" whatever the caller's permission is; what
        it opens differs. A role holding ``manage incomes_and_expenses`` gets the
        editable IncomeModal, anyone else gets IncomeChangeRequestModal — so
        waiting for the "Edit Income" title is also the assertion that this user
        edits directly instead of filing a request.
        """
        self.open_row_menu(row_text)
        self.page.get_by_role("menuitem", name=EDIT_INCOME_ITEM).first.click()
        expect(
            self.page.get_by_role("heading", name=EDIT_INCOME_HEADING)
        ).to_be_visible(timeout=15_000)

    def update_income(self, *, amount: str = "", description: str = "") -> None:
        heading = self.page.get_by_role("heading", name=EDIT_INCOME_HEADING)
        if amount:
            self.page.get_by_placeholder(as_pattern(AMOUNT_FIELD)).fill(amount)
        if description:
            self.page.get_by_placeholder(as_pattern(REMARKS_FIELD)).fill(description)

        self.click_button(UPDATE_BUTTON)
        self.expect_toast(INCOME_UPDATED_TOAST, timeout_ms=25_000)
        expect(heading).to_have_count(0, timeout=15_000)

    def fill_income_form(
        self,
        *,
        amount: str = "",
        income_type: str = "",
        academic_year: str = "",
        transaction_date: str = "",
        payment_method: str = "",
        description: str = "",
    ) -> None:
        if amount:
            self.page.get_by_placeholder(as_pattern(AMOUNT_FIELD)).fill(amount)
        if income_type:
            self.select_option_by_label(TYPE_LABEL, _exact_option(income_type))
        if academic_year:
            self.select_option_by_label(
                ACADEMIC_YEAR_LABEL, _academic_year_option(academic_year)
            )
        if transaction_date:
            self.page.locator('input[type="date"]').first.fill(transaction_date)
        if payment_method:
            self.select_option_by_label(
                PAYMENT_METHOD_LABEL, _exact_option(payment_method)
            )
        if description:
            self.page.get_by_placeholder(as_pattern(REMARKS_FIELD)).fill(description)

    # ─────────────────────── register (the table) ────────────────────

    def search(self, term: str) -> None:
        """Filter the mounted table. Client-side and undebounced (page.tsx)."""
        self.page.get_by_placeholder(as_pattern(INCOME_SEARCH_FIELD)).fill(term)

    def row(self, text: str) -> Locator:
        return self.page.get_by_role("row").filter(has_text=text).first

    def open_row_menu(self, row_text: str) -> None:
        row = self.row(row_text)
        expect(row).to_be_visible(timeout=20_000)
        # The trigger is an icon-only ghost button — no accessible name at all —
        # and it is the only button in the row.
        row.get_by_role("button").last.click()

    def expect_row(self, text: str, timeout_ms: int = 20_000) -> None:
        expect(self.row(text)).to_be_visible(timeout=timeout_ms)

    def expect_no_row(self, text: str) -> None:
        expect(self.page.get_by_role("row").filter(has_text=text)).to_have_count(0)


def _exact_option(text: str) -> re.Pattern[str]:
    return as_pattern(re.compile(rf"^\s*{re.escape(text)}\s*$", re.I))


def _academic_year_option(name: str) -> re.Pattern[str]:
    """Match "2026/2027 (active)" — the option carries its active flag.

    Through ``as_pattern`` because the year's own name contains a slash, which
    would otherwise close the selector literal Playwright serialises the pattern
    into (``internal:role=option[name=/…/i]``).
    """
    return as_pattern(re.compile(rf"^\s*{re.escape(name)}\s*\(", re.I))
