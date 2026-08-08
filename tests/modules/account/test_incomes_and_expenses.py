"""/module/income_and_expenses — the school's income & expenditure register.

Manage path: the Accountant of the ``finance_only`` school sets up an income
source, records money against it, and corrects the figure after reconciliation
(``test_accountant_creates_and_manages_income``). That is the ledger unit
``account.incomes_and_expenses.manage.accountant``.

Why the Accountant, and what had to be true first
    ``Accountant`` is a first-class role: ``app.py``'s ``lifespan`` creates it on
    every boot and the non-teaching staff wizard offers it in its "Non teaching
    Staff Role" dropdown, which is how provisioning's accountant gets it. But
    ``db/repository/permissions.py`` seeded **no permissions for it at all** —
    ``role_permissions`` simply had no ``"Accountant"`` key — so every accountant
    in the product logged in to an empty application: ``usePermissionGuard``
    returned false and rendered nothing, the sidebar's Account section failed its
    ``permissionsGate``, and ``has_permission("manage", "incomes_and_expenses")``
    answered 403 to every write. The role that the finance module is named after
    could not open the finance module.

    That seed is fixed in place (``newschoolapp`` is left dirty; see
    ``state/backend_patches.md``): ``Accountant`` now carries the back-office
    permissions the ledger's own role model assumes — ``manage fees``,
    ``manage incomes_and_expenses``, plus reads on home/dashboard/students/staff
    and the messaging and change-request baseline every non-teaching staff member
    already had. The feature pack still gates each module per school, so nothing
    about who may license what changed.

    This test is therefore also the guard on that fix. If the seed regresses, it
    fails at the very first step — the sidebar has no Account section to click.

What "manage" means on this screen
    An income cannot exist without an **income type** (``income_type_id`` is
    ``NOT NULL`` on ``school_income``) and a fresh branch has none, so the type
    is created first, from the screen's own "Income Types" tab. That is not
    scaffolding — it is half of what an accountant manages here, and the tab is
    the only place in the app that creates one.

    The edit half goes through the row menu. "Edit income" is offered to every
    role, but what it opens depends on the permission: ``isManage`` picks the
    editable ``IncomeModal``, and everyone else gets ``IncomeChangeRequestModal``
    instead (page.tsx ``handleEditClick``). So waiting for the "Edit Income"
    title is itself the assertion that this accountant edits the record directly
    rather than filing a change request against it.

Two fields deliberately left out of the assertions
    * **Ledger Account Code** on the income type. Setting one makes every
      create/update of an income using that type post a journal through
      ``LedgerService``, which pulls the chart of accounts into a walkthrough
      about recording income. It is optional in the modal and in
      ``IncomeTypeCreate``; the ledger is its own module and its own unit.
    * **Payment Method** on the income. The form offers it and the table renders
      a column for it, but ``school_income`` has no such column and both
      ``FinanceService.create_income`` and ``update_income`` pop the value off
      the payload before it reaches the model — it survives only inside a ledger
      journal. Asserting it in the register would assert a value the backend
      never stores, so the walkthrough does not set it.

Other units in this file
    ``account.incomes_and_expenses.view.school_admin`` and
    ``account.incomes_and_expenses.denied`` are separate ledger entries and live
    in their own sections below, each with its own prefixed constants. Append a
    new section rather than reshaping an existing one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import ACADEMIC_YEAR_NAME, SchoolContext
from tests.pages.account.income_and_expenses import (
    ADD_INCOME_BUTTON,
    EXPENSE_TYPES_TAB,
    EXPENSES_TAB,
    INCOME_HEADING,
    INCOME_SEARCH_FIELD,
    LOAD_FAILURE,
    IncomeExpensesPage,
)
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

INCOMES_MODULE = "incomes_and_expenses"
INCOMES_SCENARIO = "finance_only"

# The sidebar entry (SideNavigation/nav-config.tsx). The Account section is
# `branchOnly`, but that flag only ever applies to a SchoolAdmin — branch state
# is a SchoolAdmin-only concept — so for an accountant the link is on screen
# straight after login.
NAV_INCOME_AND_EXPENSES = re.compile(r"^\s*Income & Expenses\s*$", re.I)

# Everything this unit creates carries the "TEST" prefix the orphan sweeper
# matches on, plus the run tag so parallel agents never collide.
TAG = run_tag()
INCOME_TYPE_NAME = f"TEST Fundraiser Proceeds {TAG}"
INCOME_TYPE_DESCRIPTION = (
    "Gate takings and pledges from school-organised fundraising events."
)
INCOME_DESCRIPTION = f"TEST Harmattan fundraiser gate takings {TAG}"
RECONCILED_DESCRIPTION = f"TEST Harmattan fundraiser gate takings, banked {TAG}"

INCOME_AMOUNT = "4500"
RECONCILED_AMOUNT = "5250"
# `formatCurrency` (utils/format.ts) renders en-GH decimals with two places and a
# group separator; the separator is matched loosely so a locale-data change in
# Chromium does not read as a lost figure.
INCOME_AMOUNT_SHOWN = re.compile(r"4[,\s ]?500\.00")
RECONCILED_AMOUNT_SHOWN = re.compile(r"5[,\s ]?250\.00")

# ISO in, because this is a native <input type="date">. `formatDate` renders it
# through Intl in en-GB, which is where "18 September 2026" comes from.
TRANSACTION_DATE = "2026-09-18"
TRANSACTION_DATE_SHOWN = re.compile(r"18 September 2026", re.I)


@pytest.mark.accountant
@pytest.mark.scenario(INCOMES_SCENARIO)
@pytest.mark.demo(
    feature_id="account.incomes_and_expenses.manage.accountant",
    title="Income & Expenses",
    subtitle="Accountant creates and manages income & expenses",
)
def test_accountant_creates_and_manages_income(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """An accountant books an income against a new source, then corrects it."""
    ctx = provisioned_school
    assert ctx.accountant is not None, (
        "provisioning created no accountant for this school — phase C creates one "
        "from /module/staff's Non-teaching Staff tab, which needs the `staff` "
        "module on the pack"
    )
    assert INCOMES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {INCOMES_MODULE!r} for this "
        f"unit — an accountant refused the module has no register to manage"
    )
    assert ctx.academic_year, (
        "provisioning created no academic year, and every income is booked "
        "against one (the Add Income form requires it) — check that the scenario "
        "licenses academic_year_and_term"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    accountant = ctx.accountant
    finance = IncomeExpensesPage(page, base_url)

    with demo.step(
        f"Sign in as {accountant.full_name}, who keeps the books at "
        f"{ctx.school_name}",
        dwell_ms=2500,
    ):
        login_as(page, base_url, accountant)

    with demo.step("Open Income & Expenses from the Account menu", dwell_ms=1500):
        # Also the guard on the Accountant permission seed: with no permissions
        # the Account section fails its permissionsGate and this link is absent.
        link = page.get_by_role("link", name=as_pattern(NAV_INCOME_AND_EXPENSES)).first
        expect(link).to_be_visible(timeout=25_000)
        link.click()
        finance.expect_loaded()

    with demo.step(
        "A new campus has no income sources yet — set one up first", dwell_ms=1800
    ):
        finance.show_income_types()
        finance.create_income_type(
            name=INCOME_TYPE_NAME, description=INCOME_TYPE_DESCRIPTION
        )
        finance.expect_income_type_row(INCOME_TYPE_NAME)

    with demo.step("Now book what the fundraiser actually brought in", dwell_ms=1800):
        finance.show_income()
        finance.create_income(
            amount=INCOME_AMOUNT,
            income_type=INCOME_TYPE_NAME,
            academic_year=ACADEMIC_YEAR_NAME,
            transaction_date=TRANSACTION_DATE,
            description=INCOME_DESCRIPTION,
        )

    with demo.step(
        "The income lands on the register, dated and priced", dwell_ms=2500
    ):
        finance.search(INCOME_DESCRIPTION)
        finance.expect_row(INCOME_DESCRIPTION)
        # Read back from the table, which renders the list the page refetched
        # after the create — so this is proof the row persisted, not that a form
        # was filled in.
        row = finance.row(INCOME_DESCRIPTION)
        expect(row).to_contain_text(INCOME_TYPE_NAME)
        expect(row).to_contain_text(ACADEMIC_YEAR_NAME)
        expect(row).to_contain_text(INCOME_AMOUNT_SHOWN)
        expect(row).to_contain_text(TRANSACTION_DATE_SHOWN)

    with demo.step(
        "The bank statement came in higher — reopen the entry and correct it",
        dwell_ms=2000,
    ):
        finance.open_edit_form(INCOME_DESCRIPTION)
        finance.update_income(
            amount=RECONCILED_AMOUNT, description=RECONCILED_DESCRIPTION
        )

    with demo.step("The register now reads the reconciled figure", dwell_ms=3000):
        finance.search(RECONCILED_DESCRIPTION)
        reconciled = finance.row(RECONCILED_DESCRIPTION)
        expect(reconciled).to_be_visible(timeout=20_000)
        expect(reconciled).to_contain_text(RECONCILED_AMOUNT_SHOWN)
        expect(reconciled).to_contain_text(INCOME_TYPE_NAME)
        # The correction replaced the entry rather than adding a second one.
        finance.expect_no_row(INCOME_DESCRIPTION)
        finance.expect_no_load_failure()


# ─────────── view path: the SchoolAdmin reads the branch's books ─────────────
#
# Ledger unit ``account.incomes_and_expenses.view.school_admin``. Same screen and
# the same ``finance_only`` school as the accountant path above, but nothing is
# written through the UI: what is under test is the *reading* — the four
# registers this one screen carries and the stat tiles above them.
#
# Constants below are prefixed rather than sharing the accountant section's
# names: this module file is written one role-section at a time, and a shared
# module-level name would silently rebind under whichever section is appended
# last.
#
# Why the rows are seeded over the API rather than typed into the UI
#     Driving the Add Income / Add Expense modals here would be the accountant
#     unit's walkthrough wearing a different name. ``finance_seed`` therefore
#     writes one income type, one expense type, one receipt and one payment
#     straight to ``/finance/…`` — the same setup-only use of ``api`` that
#     ``school_provisioning._seed_fee_group`` makes — and every assertion is then
#     made on what the screen renders back. It also gives this unit an *expense*,
#     which the accountant path never creates, so the Expenses and Expense Types
#     tabs are read against real rows rather than against an empty state.
#
#     Neither seeded type carries a ``ledger_account_code``, for the same reason
#     the page object leaves that field blank: it would post a ledger journal for
#     every income using the type and pull the chart of accounts into this unit.
#
# Why picking the branch is a narrated step and not hidden setup
#     For a SchoolAdmin it is what opens the way in, twice over. ``page.tsx``'s
#     data effect returns early while ``useBranchStore`` is empty — it never calls
#     ``fetchIncomes`` at all, so the workspace would render four empty tabs — and
#     the sidebar's whole "Account Module" section is ``branchOnly: true``
#     (nav-config.tsx), so until that store is filled there is no "Income &
#     Expenses" link to click. (The accountant above needs neither: branch state
#     is a SchoolAdmin-only concept, and they carry their own
#     ``school_branch_id``.)
#
# Deliberately *not* asserted: that the write controls are absent. The seeded
# SchoolAdmin role holds ``("manage", "incomes_and_expenses")``
# (newschoolapp/db/repository/permissions.py), so "Add Income", "Add Expense" and
# the rows' Edit/Delete items are correctly on screen for this role. Read-only
# here means this test never uses them, not that the app hides them — the role
# for which this screen offers no writes at all is a different unit.
#
# Deliberately not asserted either: the Payment column, for the reason recorded
# in the page object's docstring — the value is popped before the insert and
# ``school_income`` has no column for it, so every row's Payment cell reads "—".

VIEW_SCENARIO = "finance_only"

# The sidebar entry (SideNavigation/nav-config.tsx). Unlike the accountant's, a
# SchoolAdmin's copy of this link only exists once a branch is selected.
VIEW_NAV_INCOME_AND_EXPENSES = re.compile(r"^\s*Income\s*&\s*Expenses\s*$", re.I)

# Header.tsx rebuilds its <h1> from the active tab. The page object exports the
# two Income headings; the expense side is named here.
VIEW_HEADING_EXPENSES = re.compile(r"^\s*Manage Expenses\s*$", re.I)
VIEW_HEADING_EXPENSE_TYPES = re.compile(r"^\s*Manage Expense Types\s*$", re.I)

# The <h3> each register renders above its own table.
VIEW_TABLE_INCOME_RECORDS = re.compile(r"^\s*Income Records\s*$", re.I)
VIEW_TABLE_EXPENSE_RECORDS = re.compile(r"^\s*Expense Records\s*$", re.I)
VIEW_TABLE_INCOME_TYPES = re.compile(r"^\s*Income Types\s*$", re.I)
VIEW_TABLE_EXPENSE_TYPES = re.compile(r"^\s*Expense Types\s*$", re.I)

# ModuleHeader.tsx stat tiles; getStats() names them from the active tab.
VIEW_STAT_TOTAL_INCOME = "Total Income (GHC)"
VIEW_STAT_TOTAL_EXPENSE = "Total Expense (GHC)"

# The status badge both type registers put on a live category.
VIEW_ACTIVE_BADGE = re.compile(r"^\s*Active\s*$", re.I)

# EmptyState title, asserted once the search box is narrowed to nothing.
VIEW_EMPTY_INCOMES = re.compile(r"^\s*No incomes found\s*$", re.I)

# ── what finance_seed writes. "TEST" is what the orphan sweeper matches on, and
#    the run tag keeps parallel agents from colliding. ─────────────────────────
VIEW_TAG = run_tag()

VIEW_INCOME_TYPE_NAME = f"TEST Tuition Receipts {VIEW_TAG}"
VIEW_INCOME_TYPE_DESCRIPTION = "Termly tuition collected at the front desk."
VIEW_EXPENSE_TYPE_NAME = f"TEST Campus Utilities {VIEW_TAG}"
VIEW_EXPENSE_TYPE_DESCRIPTION = "Electricity, water and internet for the campus."

VIEW_INCOME_DESCRIPTION = f"TEST Term one tuition banked {VIEW_TAG}"
VIEW_INCOME_AMOUNT = 2500
VIEW_EXPENSE_DESCRIPTION = f"TEST September electricity bill {VIEW_TAG}"
VIEW_EXPENSE_AMOUNT = 1250

# `formatCurrency` (utils/format.ts) renders en-GH decimals with two places; the
# group separator is matched loosely so a Chromium locale-data change does not
# read as a lost figure.
VIEW_INCOME_AMOUNT_SHOWN = re.compile(r"2[,\s ]?500\.00")
VIEW_EXPENSE_AMOUNT_SHOWN = re.compile(r"1[,\s ]?250\.00")
# The stat tiles are *branch* totals, not this unit's totals: every test in the
# `finance_only` scenario shares one provisioned school, and the accountant unit
# above books its own income into the same branch. So the tile can never be
# asserted against VIEW_INCOME_AMOUNT alone — it is checked against the figure
# /finance/{income,expense}/statistics serves for the branch at that moment
# (_expected_stat_tile below), which is what the tile is supposed to be showing
# and is independent of which other unit ran first.

# A term no seeded row carries, used to prove the search box really filters.
VIEW_NO_SUCH_RECORD = f"TEST No Such Receipt {VIEW_TAG}"


@dataclass(frozen=True)
class FinanceBooks:
    """The one receipt and one payment this unit puts on the screen."""

    branch_id: int
    academic_year_id: int
    academic_year_name: str
    income_type_id: int
    expense_type_id: int
    income_id: int
    expense_id: int


@pytest.fixture
def finance_seed(provisioned_school: SchoolContext, api: BackendAPI) -> FinanceBooks:
    """One income type, one expense type, one receipt and one payment.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert INCOMES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {INCOMES_MODULE!r} for this "
        f"unit — a school refused the module has no register to read"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch, so there is no scope to "
        "keep books for — phase B creates one for every scenario"
    )
    branch_id = int(ctx.branches[0].get("id") or -1)
    assert branch_id > 0, (
        "provisioning could not capture the branch id, and every /finance route "
        "is scoped to one — re-run provisioning rather than guessing it"
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    years = api.get(
        f"/academic-year/?skip=0&limit=100&school_id={ctx.school_id}", token=token
    )
    assert years.status_code == 200, (
        f"could not read this school's academic years: "
        f"{years.status_code} {years.text[:300]}"
    )
    rows = years.json()
    assert rows, (
        f"{ctx.school_name!r} has no academic year, and IncomeResponse and "
        f"ExpenseResponse both carry a non-optional academic_year_id — "
        f"provisioning phase B creates one whenever the pack licenses "
        f"'academic_year_and_term'"
    )
    year = next((y for y in rows if y.get("is_active")), rows[0])

    income_type = _seed_finance_row(
        api, token,
        f"/finance/income-types/?school_branch_id={branch_id}",
        {
            "name": VIEW_INCOME_TYPE_NAME,
            "description": VIEW_INCOME_TYPE_DESCRIPTION,
            "school_branch_id": branch_id,
        },
        what="income type",
    )
    expense_type = _seed_finance_row(
        api, token,
        f"/finance/expense-types/?school_branch_id={branch_id}",
        {
            "name": VIEW_EXPENSE_TYPE_NAME,
            "description": VIEW_EXPENSE_TYPE_DESCRIPTION,
            "school_branch_id": branch_id,
        },
        what="expense type",
    )

    today = date.today().isoformat()
    income = _seed_finance_row(
        api, token, "/finance/income/",
        {
            "amount": VIEW_INCOME_AMOUNT,
            "description": VIEW_INCOME_DESCRIPTION,
            "income_type_id": int(income_type["id"]),
            "academic_year_id": int(year["id"]),
            "school_branch_id": branch_id,
            "transaction_date": today,
        },
        what="income",
    )
    expense = _seed_finance_row(
        api, token, "/finance/expense/",
        {
            "amount": VIEW_EXPENSE_AMOUNT,
            "description": VIEW_EXPENSE_DESCRIPTION,
            "expense_type_id": int(expense_type["id"]),
            "academic_year_id": int(year["id"]),
            "school_branch_id": branch_id,
            "transaction_date": today,
        },
        what="expense",
    )

    return FinanceBooks(
        branch_id=branch_id,
        academic_year_id=int(year["id"]),
        academic_year_name=str(year.get("name") or ""),
        income_type_id=int(income_type["id"]),
        expense_type_id=int(expense_type["id"]),
        income_id=int(income["id"]),
        expense_id=int(expense["id"]),
    )


def _seed_finance_row(
    api: BackendAPI, token: str, path: str, payload: dict[str, Any], *, what: str
) -> dict[str, Any]:
    """POST one setup row, failing loudly rather than leaving an empty screen."""
    response = api.post(path, token=token, json=payload)
    assert response.status_code < 400, (
        f"could not seed the {what}: {response.status_code} {response.text[:300]}"
    )
    return response.json()


@pytest.mark.school_admin
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="account.incomes_and_expenses.view.school_admin",
    title="Income & Expenses",
    subtitle="SchoolAdmin views income & expenses",
)
def test_school_admin_views_incomes_and_expenses(
    finance_seed: FinanceBooks,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin reads the branch's books: receipts, payments and categories.

    Every assertion is made on the register the next person to open the screen
    would see, so a row the backend holds but the screen never renders — the
    failure mode an unset branch scope produces — cannot pass.
    """
    ctx = provisioned_school
    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    finance = IncomeExpensesPage(page, base_url)
    branch_name = str(ctx.branches[0]["name"])

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Open the books for {branch_name}"):
        # Mandatory, not merely convenient: until the branch store is filled the
        # Account section of the sidebar is not rendered at all, and the finance
        # page's own fetches never fire. See the section comment above.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("The Account menu now offers Income & Expenses — open it"):
        # By route first: "View" on the branch row routes to /module/community,
        # which this pack does not license, so selecting the branch leaves the
        # browser on /auth/no-access — a page with no sidebar on it. Returning
        # to the branches list to find one would undo the selection, because its
        # mount effect calls clearBranch(). The sidebar entry is therefore
        # asserted (and used) from inside the module chrome.
        finance.open()
        link = page.get_by_role(
            "link", name=as_pattern(VIEW_NAV_INCOME_AND_EXPENSES)
        ).first
        expect(link).to_be_visible(timeout=20_000)
        link.click()
        page.wait_for_url(re.compile(r"/module/income_and_expenses"), timeout=20_000)
        finance.expect_loaded()

    with demo.step("Everything the school has taken in, receipt by receipt",
                   dwell_ms=1800):
        expect(
            page.get_by_role("heading", name=VIEW_TABLE_INCOME_RECORDS)
        ).to_be_visible(timeout=20_000)

        receipt = finance.row(VIEW_INCOME_DESCRIPTION)
        expect(receipt).to_be_visible(timeout=20_000)
        expect(receipt).to_contain_text(VIEW_INCOME_TYPE_NAME)
        expect(receipt).to_contain_text(VIEW_INCOME_AMOUNT_SHOWN)
        if finance_seed.academic_year_name:
            # "2026/2027" is only ever an *assertion* string here — as a locator
            # it would have to go through as_pattern to survive the slash.
            expect(receipt).to_contain_text(finance_seed.academic_year_name)

        # The tile above the table is computed by the backend from the same rows,
        # so it is the cross-check that the register is not a stale client list.
        # It is a whole-branch figure — the accountant unit banks its own income
        # into this shared school — so it is asserted against what the statistics
        # route serves for the branch, not against this unit's own receipt.
        expect(_finance_stat(page, VIEW_STAT_TOTAL_INCOME)).to_contain_text(
            _expected_stat_tile(
                api, ctx, kind="income",
                branch_id=finance_seed.branch_id, floor=VIEW_INCOME_AMOUNT,
            )
        )

    with demo.step("Search the register down to a single receipt", dwell_ms=1500):
        finance.search(VIEW_INCOME_DESCRIPTION)
        finance.expect_row(VIEW_INCOME_DESCRIPTION)

        finance.search(VIEW_NO_SUCH_RECORD)
        expect(page.get_by_text(VIEW_EMPTY_INCOMES)).to_be_visible(timeout=10_000)

        # Cleared again: searchQuery is shared by all four tabs, so leaving it set
        # would empty every register the steps below read.
        finance.search("")
        finance.expect_row(VIEW_INCOME_DESCRIPTION)

    with demo.step("Switch to Expenses to see what the school has paid out",
                   dwell_ms=1800):
        finance.click_button(EXPENSES_TAB)
        expect(page.get_by_role("heading", name=VIEW_HEADING_EXPENSES)).to_be_visible(
            timeout=20_000
        )
        expect(
            page.get_by_role("heading", name=VIEW_TABLE_EXPENSE_RECORDS)
        ).to_be_visible(timeout=20_000)

        payment = finance.row(VIEW_EXPENSE_DESCRIPTION)
        expect(payment).to_be_visible(timeout=20_000)
        expect(payment).to_contain_text(VIEW_EXPENSE_TYPE_NAME)
        expect(payment).to_contain_text(VIEW_EXPENSE_AMOUNT_SHOWN)
        expect(_finance_stat(page, VIEW_STAT_TOTAL_EXPENSE)).to_contain_text(
            _expected_stat_tile(
                api, ctx, kind="expense",
                branch_id=finance_seed.branch_id, floor=VIEW_EXPENSE_AMOUNT,
            )
        )

    with demo.step("Income Types shows how every receipt is categorised",
                   dwell_ms=1500):
        finance.show_income_types()
        expect(
            page.get_by_role("heading", name=VIEW_TABLE_INCOME_TYPES)
        ).to_be_visible(timeout=20_000)

        category = finance.row(VIEW_INCOME_TYPE_NAME)
        expect(category).to_be_visible(timeout=20_000)
        expect(category).to_contain_text(VIEW_INCOME_TYPE_DESCRIPTION)
        expect(category.get_by_text(VIEW_ACTIVE_BADGE)).to_be_visible()

    with demo.step("And Expense Types does the same for the school's spending",
                   dwell_ms=1500):
        finance.click_button(EXPENSE_TYPES_TAB)
        expect(
            page.get_by_role("heading", name=VIEW_HEADING_EXPENSE_TYPES)
        ).to_be_visible(timeout=20_000)
        expect(
            page.get_by_role("heading", name=VIEW_TABLE_EXPENSE_TYPES)
        ).to_be_visible(timeout=20_000)

        category = finance.row(VIEW_EXPENSE_TYPE_NAME)
        expect(category).to_be_visible(timeout=20_000)
        expect(category).to_contain_text(VIEW_EXPENSE_TYPE_DESCRIPTION)
        expect(category.get_by_text(VIEW_ACTIVE_BADGE)).to_be_visible()
        finance.expect_no_load_failure()

    with demo.step("Behind the screen, these books belong to this branch alone",
                   dwell_ms=2000):
        _expect_backend_serves_the_same_books(api, ctx, finance_seed)


# ─────────────────────── helpers for the view path ──────────────────────────


def _finance_stat(page: Page, name: str) -> Locator:
    """The value of the ModuleHeader tile labelled ``name``.

    The tiles are a ``<dt>`` label followed by a ``<dd>`` figure, and the label is
    the only readable anchor — nothing on the card carries a role.
    """
    label = page.get_by_text(re.compile(rf"^\s*{re.escape(name)}\s*$", re.I)).first
    return label.locator("xpath=following-sibling::dd[1]")


def _expected_stat_tile(
    api: BackendAPI,
    ctx: SchoolContext,
    *,
    kind: str,
    branch_id: int,
    floor: float,
) -> re.Pattern:
    """The figure the "Total …" tile must be showing, read from its own route.

    ``getStats()`` renders ``statsData.year.total.toLocaleString()`` from
    ``/finance/{kind}/statistics`` (income_and_expenses/page.tsx), so that route
    is the only correct expectation for the tile: it is a *branch* total, and
    every unit in the ``finance_only`` scenario books money into the same branch.

    ``floor`` keeps this from degenerating into "whatever the screen says" — the
    total must still be at least the row this unit put on the register, so a tile
    that has stopped counting these books fails here rather than agreeing with an
    equally broken backend.
    """
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    response = api.get(f"/finance/{kind}/statistics?branch_id={branch_id}", token=token)
    assert response.status_code == 200, (
        f"the {kind} stat tiles are served by /finance/{kind}/statistics, which "
        f"a SchoolAdmin holding ('manage', {INCOMES_MODULE!r}) must be able to "
        f"read — got {response.status_code}: {response.text[:300]}"
    )
    total = float(response.json()["year"]["total"])
    assert total >= floor, (
        f"the branch's yearly {kind} total ({total}) is below the single row this "
        f"unit booked ({floor}), so the statistics are not counting the books the "
        f"register is showing"
    )

    # Number.prototype.toLocaleString(): grouped thousands, no trailing zeros,
    # at most three fraction digits. The separator is matched loosely so a
    # Chromium locale-data change does not read as a lost figure.
    whole = int(total)
    shown = f"{whole:,}" if total == whole else f"{total:,.3f}".rstrip("0").rstrip(".")
    return re.compile(r"[,\s ]?".join(re.escape(part) for part in shown.split(",")))


def _expect_backend_serves_the_same_books(
    api: BackendAPI, ctx: SchoolContext, books: FinanceBooks
) -> None:
    """The reads behind the screen answer this SchoolAdmin, and only for the branch.

    Without this the UI half proves only that *a* list rendered; it says nothing
    about the ``BRANCH_ID_REQUIRED`` contract every /finance list route enforces
    for a SchoolAdmin, which is the single thing most likely to regress this
    screen into showing another campus's money.
    """
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    incomes = api.get(
        f"/finance/income/?skip=0&limit=100&branch_id={books.branch_id}", token=token
    )
    assert incomes.status_code == 200, (
        f"a SchoolAdmin holds ('manage', {INCOMES_MODULE!r}) and this school is "
        f"licensed for it, so the register's own list call must succeed — got "
        f"{incomes.status_code}: {incomes.text[:300]}"
    )
    assert books.income_id in {int(row["id"]) for row in incomes.json()}, (
        "the seeded receipt is missing from the branch's income list, so the "
        "screen above was rendering something other than these books"
    )

    expenses = api.get(
        f"/finance/expense/?skip=0&limit=100&branch_id={books.branch_id}", token=token
    )
    assert expenses.status_code == 200, (
        f"the expenses register's list call must succeed for a SchoolAdmin — got "
        f"{expenses.status_code}: {expenses.text[:300]}"
    )
    assert books.expense_id in {int(row["id"]) for row in expenses.json()}, (
        "the seeded payment is missing from the branch's expense list"
    )

    stats = api.get(
        f"/finance/income/statistics?branch_id={books.branch_id}", token=token
    )
    assert stats.status_code == 200, (
        f"the stat tiles above the register are served by this route — got "
        f"{stats.status_code}: {stats.text[:300]}"
    )
    assert float(stats.json()["year"]["total"]) >= VIEW_INCOME_AMOUNT, (
        f"the year's income total is below the single receipt this unit banked "
        f"({VIEW_INCOME_AMOUNT}), so the statistics are not counting the branch "
        f"the register is showing; got {stats.json()['year']}"
    )

    # The scope itself: the same route without a branch is refused rather than
    # quietly pooling every branch in the school.
    unscoped = api.get("/finance/income/?skip=0&limit=100", token=token)
    assert unscoped.status_code == 400, (
        f"a SchoolAdmin belongs to no branch, so /finance/income/ must refuse "
        f"them a branch-less read (core/exceptions.BRANCH_ID_REQUIRED) rather "
        f"than pooling every campus's money — got {unscoped.status_code}: "
        f"{unscoped.text[:300]}"
    )


# ═══════════════ account.incomes_and_expenses.denied ════════════════════════
#
# The negative path for this module: the SchoolAdmin of the ``minimal`` school,
# whose feature pack licenses only ``school_configuration`` and
# ``school_admin_dashboard``. They hold every permission the module defines and
# are still refused, because their school is not licensed for it.
#
# Where the denial actually lives
#     Not in the sidebar, and not in a route guard. ``useModuleGuard`` hands a
#     SchoolAdmin ``hasAccess = true`` before it ever reads the ``schoolModules``
#     cookie, and ``src/middleware.ts`` makes ``!isSchoolAdmin`` a condition of
#     its module redirect — so ``/module/income_and_expenses`` really does mount
#     for this admin. The seeded SchoolAdmin role also *holds*
#     ``("manage", "incomes_and_expenses")`` (db/repository/permissions.py), so
#     ``usePermissionGuard`` lets them through and the permission half of the
#     backend gate passes as well.
#
#     What denies them is the feature-pack half of
#     ``utils.permissions.has_permission``: it resolves the caller's school, asks
#     ``FeaturePackService`` for its module list, and answers **403 "Feature not
#     available in your plan"** when the module is missing. Every route on
#     ``api/routes/finance.py`` carries that dependency, and it is solved before
#     the endpoint body runs — which is why the ids and payloads below are
#     deliberately arbitrary, and why a 400 ``BRANCH_ID_REQUIRED`` (raised inside
#     the body of every list route for a SchoolAdmin) in place of a 403 would
#     itself be the failure: it would mean the licence was never consulted.
#
#     The UI consequence follows from it. ``page.tsx``'s mount effect fires seven
#     reads — incomes, expenses, income types, expense types, both statistics
#     calls and the academic years — and the axios response interceptor in
#     ``src/utils/handleErrorMessage.ts`` recognises that particular detail
#     (``shouldRedirectToNoAccess``) and performs a hard ``window.location``
#     redirect to **/auth/no-access**, rejecting with ``FeatureNotAvailableError``.
#     That redirect races ``fetchAcademicYears``'s own ``catch``, which sets
#     ``fetchError`` and renders the "Failed to load income & expenses data"
#     ``PageError`` panel — so both surfaces are accepted below, exactly as the
#     fees denial accepts both.
#
# Two honesty notes about what this test does and does not claim
#     1. Selecting the branch first is mandatory, not a convenience. ``page.tsx``
#        returns early from its data effect while ``useBranchStore`` is empty, so
#        without it the screen renders its four tabs and requests *nothing* — an
#        empty register that would prove nothing about the plan.
#     2. Deliberately *not* asserted: that the sidebar hides "Income & Expenses".
#        ``nav-config.tsx`` gates the Account section on a ``permissionsGate``,
#        and ``SideNavigation`` lets the permission check take priority over the
#        module gate — so for a SchoolAdmin its presence says nothing about the
#        school's pack.
#     3. Deliberately *not* asserted: the ``/ledger`` router. Its routes are gated
#        on the same ``incomes_and_expenses`` permission, but ``ledger`` is not a
#        licensable module in ``config/module_catalog.py`` and the chart of
#        accounts is its own screen — asserting it here would be this unit
#        claiming a module it does not own.

DENIED_INCOMES_MODULE = "incomes_and_expenses"
DENIED_INCOMES_SCENARIO = "minimal"
DENIED_INCOMES_ROUTE = "income_and_expenses"
DENIED_SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# Path ids for the gated routes. High enough that no provisioned row could carry
# one, so a 2xx here could never be mistaken for a real record being reached.
DENIED_UNREACHABLE_ID = 9_999_999

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIED_INCOMES_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# Where the frontend sends a user whose *plan* excludes the module, and the copy
# it greets them with (src/app/auth/no-access/page.tsx).
DENIED_NO_ACCESS_URL = re.compile(r"/auth/no-access")
DENIED_ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
DENIED_ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

# The register's own chrome (components/Header.tsx, components/Tabs.tsx), none of
# which may put a usable set of books on screen.
DENIED_INCOME_HEADING = INCOME_HEADING
DENIED_INCOME_SEARCH = INCOME_SEARCH_FIELD
DENIED_ADD_INCOME = ADD_INCOME_BUTTON
DENIED_LOAD_FAILURE = LOAD_FAILURE

DENIED_SETTLE_TIMEOUT_MS = 40_000


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_INCOMES_SCENARIO)
def test_incomes_and_expenses_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `incomes_and_expenses` off the pack, a SchoolAdmin can neither read
    the books nor write a receipt, a payment or a category."""
    ctx = provisioned_school
    if DENIED_INCOMES_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {DENIED_INCOMES_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    assert ctx.branches, (
        "provisioning left this school with no branch, so there is no scope to "
        "keep books for — phase B creates one for every scenario"
    )
    branch = ctx.branches[0]
    branch_id = int(branch.get("id") or 0)
    assert branch_id > 0, (
        "provisioning could not capture the branch id, and every /finance route "
        "is scoped to one — re-run provisioning rather than guessing it"
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ─────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had finance rights anyway", which would make the 403s vacuous.
    role = api.get(f"/roles/{api.role_id_for(DENIED_SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {DENIED_SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert DENIED_INCOMES_MODULE in role_modules, (
        f"the seeded {DENIED_SCHOOL_ADMIN_ROLE} role no longer holds an "
        f"{DENIED_INCOMES_MODULE!r} permission, so this test would be asserting "
        f"a denial the role gets for free. Re-point it at the feature pack only, "
        f"or fix the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    features_body = features.json()
    assert features_body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{DENIED_INCOMES_MODULE!r} proves nothing about the gate — an unassigned "
        f"school is unrestricted by design. Provisioning phase A assigns one; "
        f"check that it did."
    )
    assert DENIED_INCOMES_MODULE not in (features_body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {DENIED_INCOMES_MODULE!r} despite "
        f"the {ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every /finance route is refused ────────────────
    #
    # Reads and writes alike, across all four registers the screen carries, so
    # the gate cannot regress into being merely read-only or merely cosmetic.
    denied_tag = run_tag()
    denied_income_type = f"TEST Unlicensed Income Type {denied_tag}"
    denied_expense_type = f"TEST Unlicensed Expense Type {denied_tag}"

    refusals = {
        # ── the Income tab ──
        "list_incomes": api.get(
            f"/finance/income/?skip=0&limit=100&branch_id={branch_id}", token=token
        ),
        "income_statistics": api.get(
            f"/finance/income/statistics?branch_id={branch_id}", token=token
        ),
        "read_income": api.get(f"/finance/income/{DENIED_UNREACHABLE_ID}", token=token),
        "create_income": api.post(
            "/finance/income/",
            token=token,
            json={
                "amount": 100,
                "description": (
                    "TEST receipt that must never be booked — the pack excludes "
                    "incomes_and_expenses."
                ),
                "income_type_id": DENIED_UNREACHABLE_ID,
                "academic_year_id": DENIED_UNREACHABLE_ID,
                "school_branch_id": branch_id,
                "transaction_date": "2026-09-18",
            },
        ),
        "update_income": api.put(
            f"/finance/income/{DENIED_UNREACHABLE_ID}",
            token=token,
            json={"amount": 150},
        ),
        "delete_income": api.delete(
            f"/finance/income/{DENIED_UNREACHABLE_ID}", token=token
        ),
        # ── the Expenses tab ──
        "list_expenses": api.get(
            f"/finance/expense/?skip=0&limit=100&branch_id={branch_id}", token=token
        ),
        "expense_statistics": api.get(
            f"/finance/expense/statistics?branch_id={branch_id}", token=token
        ),
        "read_expense": api.get(
            f"/finance/expense/{DENIED_UNREACHABLE_ID}", token=token
        ),
        "create_expense": api.post(
            "/finance/expense/",
            token=token,
            json={
                "amount": 100,
                "description": (
                    "TEST payment that must never be booked — the pack excludes "
                    "incomes_and_expenses."
                ),
                "expense_type_id": DENIED_UNREACHABLE_ID,
                "academic_year_id": DENIED_UNREACHABLE_ID,
                "school_branch_id": branch_id,
                "transaction_date": "2026-09-18",
            },
        ),
        "update_expense": api.put(
            f"/finance/expense/{DENIED_UNREACHABLE_ID}",
            token=token,
            json={"amount": 150},
        ),
        "delete_expense": api.delete(
            f"/finance/expense/{DENIED_UNREACHABLE_ID}", token=token
        ),
        # ── the two category registers ──
        "list_income_types": api.get(
            f"/finance/income-types/?include_inactive=false"
            f"&school_branch_id={branch_id}",
            token=token,
        ),
        "create_income_type": api.post(
            f"/finance/income-types/?school_branch_id={branch_id}",
            token=token,
            json={"name": denied_income_type, "description": "Must never exist."},
        ),
        "update_income_type": api.put(
            f"/finance/income-types/{DENIED_UNREACHABLE_ID}",
            token=token,
            json={"name": denied_income_type},
        ),
        "delete_income_type": api.delete(
            f"/finance/income-types/{DENIED_UNREACHABLE_ID}", token=token
        ),
        "list_expense_types": api.get(
            f"/finance/expense-types/?include_inactive=false"
            f"&school_branch_id={branch_id}",
            token=token,
        ),
        "create_expense_type": api.post(
            f"/finance/expense-types/?school_branch_id={branch_id}",
            token=token,
            json={"name": denied_expense_type, "description": "Must never exist."},
        ),
        "update_expense_type": api.put(
            f"/finance/expense-types/{DENIED_UNREACHABLE_ID}",
            token=token,
            json={"name": denied_expense_type},
        ),
        "delete_expense_type": api.delete(
            f"/finance/expense-types/{DENIED_UNREACHABLE_ID}", token=token
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{DENIED_INCOMES_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIED_INCOMES_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}. 'Branch id is required' here would "
            f"mean the endpoint body ran before the licence was consulted."
        )

    # ── 3. …and the UI never puts a set of books in front of them ────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory before the register reads anything at all — see honesty note 1.
    BranchesPage(page, frontend_base_url).select_branch(str(branch["name"]))
    _settle_branch_selection(page)

    # Deliberately not goto_module: the response is needed. A redirect still in
    # flight from the previous screen would abort this navigation, and the
    # settle loop below would then read a /auth/no-access this module never
    # caused — a denial test passing for somebody else's denial.
    response = page.goto(
        frontend_base_url.rstrip("/") + f"/module/{DENIED_INCOMES_ROUTE}"
    )
    assert response is not None and DENIED_INCOMES_ROUTE in response.url, (
        f"the browser never landed on /module/{DENIED_INCOMES_ROUTE} — it is at "
        f"{page.url!r} instead. Whatever redirect the assertions below would "
        f"have read came from the previous screen, not from this module."
    )

    surface = _wait_for_settled_finance_surface(page)

    if surface == "redirected":
        # The strongest denial the app can give: the interceptor recognised the
        # plan restriction and took the browser off the module entirely.
        expect(page.get_by_text(as_pattern(DENIED_ACCESS_RESTRICTED))).to_be_visible(
            timeout=15_000
        )
        expect(page.get_by_text(as_pattern(DENIED_ACTIVATION_REQUIRED))).to_be_visible()
        expect(
            page.get_by_role("heading", name=as_pattern(DENIED_INCOME_HEADING))
        ).to_have_count(0)
        expect(page.get_by_placeholder(as_pattern(DENIED_INCOME_SEARCH))).to_have_count(0)
        expect(
            page.get_by_role("button", name=as_pattern(DENIED_ADD_INCOME))
        ).to_have_count(0)
        return

    # The page's own catch won the race with the redirect. Still a refusal — and
    # stronger than an empty register, because PageError renders the backend's
    # own detail rather than a blank table.
    expect(page.get_by_text(as_pattern(DENIED_LOAD_FAILURE)).first).to_be_visible()
    expect(page.get_by_role("row")).to_have_count(0)


def _settle_branch_selection(page: Page, timeout_ms: int = 20_000) -> None:
    """Let the branch row's side-effect navigation finish before moving on.

    ``BranchesPage.select_branch`` lands on ``/module/community`` — and in the
    ``minimal`` scenario *community* is unlicensed too, so that screen fires its
    own refused fetch and the interceptor bounces the browser to
    ``/auth/no-access``. Navigating away while that bounce is still in flight
    would abort the next ``page.goto`` and hand this test a redirect it did not
    cause. Waiting for it to land first means the only redirect the assertions
    can see is the one *this* module provoked.

    Returns quietly if it never comes: a scenario that does license community
    simply stays put, and there is then nothing in flight to steal anything.
    """
    remaining = timeout_ms
    step = 250
    while remaining > 0 and not DENIED_NO_ACCESS_URL.search(page.url):
        page.wait_for_timeout(step)
        remaining -= step


def _wait_for_settled_finance_surface(
    page: Page, timeout_ms: int = DENIED_SETTLE_TIMEOUT_MS
) -> str:
    """Wait until /module/income_and_expenses has stopped loading.

    Returns which of the two refusal surfaces it settled on — ``"redirected"`` or
    ``"page_error"``. Waiting for one of them is what stops the assertions above
    from passing merely because the workspace had not finished mounting; and
    reaching the timeout means the register rendered normally, which for an
    unlicensed school is itself the failure.
    """
    failure = page.get_by_text(as_pattern(DENIED_LOAD_FAILURE)).first

    remaining = timeout_ms
    step = 500
    while remaining > 0:
        if DENIED_NO_ACCESS_URL.search(page.url):
            return "redirected"
        if failure.count() > 0:
            return "page_error"
        page.wait_for_timeout(step)
        remaining -= step

    raise AssertionError(
        "/module/income_and_expenses neither redirected to a no-access page nor "
        "rendered its load-failure panel within "
        f"{timeout_ms}ms — current url {page.url!r}. If the four registers "
        "mounted instead, the feature-pack gate is not being enforced for this "
        "school."
    )
