"""Payroll → Employee Benefits.

Two screens, one module:

``/module/employee_benefit`` (:class:`EmployeeBenefitsPage`)
    The register: one row per employee who has been given a benefits package —
    who they are, which benefit band they sit on, how many benefit items that
    adds up to, and their tax relief. Everything on it comes from a single
    ``GET /employee-benefit/`` scoped to the branch.

``/module/employee_benefit/create-benefits``
    (:class:`EmployeeBenefitFormPage`)
    One form that both creates and edits, told apart only by the ``user_id``
    query parameter the register's row menu appends. Its heading follows suit
    ("Create Employee Benefits" / "Edit Employee Benefits"), and so does its
    submit button ("Create Benefits" / "Update Benefits") — which is why every
    method here names which of the two it drives.

What has to exist before this module is usable at all
    The form's three fetches are *not* tolerant of an empty branch. The backend
    raises 404 for an empty collection on ``/employee-benefit/``,
    ``/employee-benefit/benefit-item/`` and ``/employee-benefit/salary-band/``
    (and its own ``except Exception`` then re-raises that as a 400), and each
    screen turns any of those into a full-page ``PageError``. So:

      * a branch with no benefit *items* and no *band* renders "Failed to load
        form data" instead of the form, and
      * a branch with no benefit *packages* renders "Failed to load employee
        benefits" instead of the register — the register's own EmptyState, with
        its "Create Benefits" call to action, is unreachable in that state.

    Both are the app's own behaviour and are left exactly as they are; a test
    that wants to *use* these screens therefore seeds the branch's benefit items,
    a band and at least one existing package over the API first. See
    ``tests/modules/payroll/test_employee_benefit.py::benefits_setup``.

Branch scoping
    Every request behind both screens appends ``branch_id`` from
    ``useBranchStore`` when the caller is a SchoolAdmin, and the sidebar's whole
    "Payroll Module" section is ``branchOnly`` — so a SchoolAdmin must select a
    branch before either screen exists for them at all
    (``BranchesPage.select_branch``).

antd, not Radix
    The form's four pickers are antd ``<Select>``s (the rest of the app mostly
    uses Radix), so their options are role-less ``.ant-select-item-option``
    ``<div>``s in a portalled dropdown, and antd keeps every dropdown it has
    opened mounted-but-hidden. Options are therefore matched inside the dropdown
    that is actually ``:visible``, and each control is reached through its
    ``<label>``'s parent — the same anchoring ``BasePage.select_option_by_label``
    uses, and for the same reason.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError, expect

from tests.pages.base import BasePage, as_pattern

# ── routes ───────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/employee_benefit(?:$|[?#])")
FORM_URL = re.compile(r"/module/employee_benefit/create-benefits")

# The sidebar entry, under the "Payroll Module" section
# (SideNavigation/nav-config.tsx). Anchored so it cannot also match the
# "Benefit Items" / "Benefits Band" entries directly above it.
NAV_EMPLOYEE_BENEFITS = re.compile(r"^\s*Employee Benefits\s*$", re.I)

# ── the register (src/app/module/employee_benefit/page.tsx) ──────────────────
PAGE_HEADING = re.compile(r"^\s*Employee Benefits\s*$", re.I)
TABLE_HEADING = re.compile(r"^\s*All Employee Benefits\s*$", re.I)
COUNT_BADGE = re.compile(r"\d+\s+Employees?\s*$", re.I)
SEARCH_PLACEHOLDER = re.compile(
    r"^\s*Search by employee name, email, or benefit band\s*$", re.I
)
CREATE_BUTTON = re.compile(r"^\s*Create Benefits\s*$", re.I)
EMPTY_REGISTER = re.compile(r"^\s*No employee benefits found\s*$", re.I)
# Unanchored: it is used as ``has_not_text`` against a whole row.
LOADING_ROW = re.compile(r"Loading employee benefits", re.I)

# The register's columns, in the order page.tsx declares its <TableHead>s.
COLUMN_HEADERS = (
    "Employee",
    "Benefit Band",
    "Total Benefits",
    "Tax Relief (GHC)",
    "Created",
    "Actions",
)

# The row's "..." menu and the two links inside it. Both are rendered as
# <a> inside a DropdownMenuItem, so they answer to the menuitem role.
ROW_MENU_TRIGGER = re.compile(r"^\s*More actions\s*$", re.I)
VIEW_MENU_ITEM = re.compile(r"^\s*View Benefit\s*$", re.I)
EDIT_MENU_ITEM = re.compile(r"^\s*Edit Benefits\s*$", re.I)

# PageError, mounted with this exact title when the register's fetch fails.
LIST_LOAD_FAILURE = re.compile(r"^\s*Failed to load employee benefits\s*$", re.I)

# ── the form (create-benefits/page.tsx) ──────────────────────────────────────
CREATE_HEADING = re.compile(r"^\s*Create Employee Benefits\s*$", re.I)
EDIT_HEADING = re.compile(r"^\s*Edit Employee Benefits\s*$", re.I)
FORM_CARD_TITLE = re.compile(r"^\s*Employee Benefits Information\s*$", re.I)

# The four labelled controls. Each is a shadcn <Label> immediately followed by
# its control inside one wrapper <div>, so the label's parent scopes the search.
EMPLOYEE_LABEL = re.compile(r"^\s*Employee\s*\*?\s*$", re.I)
BENEFIT_BAND_LABEL = re.compile(r"^\s*Benefit Band\s*\*?\s*$", re.I)
EXTRA_BENEFITS_LABEL = re.compile(r"^\s*Extra Benefits \(Optional\)\s*$", re.I)
TAX_RELIEF_FIELD = re.compile(
    r"^\s*Tax Relief \(GHC\)\s*$|^\s*Enter tax relief amount\s*$", re.I
)
OVERTIME_LABEL = re.compile(r"^\s*Overtime Tax Eligible\s*$", re.I)

# The submit swaps its own label while the request is in flight, so each pattern
# covers both faces of the same button.
CREATE_SUBMIT = re.compile(r"^\s*Creat(e Benefits|ing\.\.\.)\s*$", re.I)
UPDATE_SUBMIT = re.compile(r"^\s*Updat(e Benefits|ing\.\.\.)\s*$", re.I)

CREATED_TOAST = re.compile(r"Employee benefits created successfully", re.I)
UPDATED_TOAST = re.compile(r"Employee benefits updated successfully", re.I)

# PageError on the form, mounted when employees, bands or items fail to load.
FORM_LOAD_FAILURE = re.compile(r"^\s*Failed to load form data\s*$", re.I)

# The band picker prints "<band name> (<n> items)" and the extra-benefit picker
# "<item name> - <amount>", so both are matched as a prefix of the option.
def band_option(band_name: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(band_name)}\s*\(", re.I)


def item_option(item_name: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(item_name)}\s*-", re.I)


class EmployeeBenefitsPage(BasePage):
    URL = "/module/employee_benefit"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "EmployeeBenefitsPage":
        super().open()
        return self.expect_loaded()

    def open_from_sidebar(self) -> "EmployeeBenefitsPage":
        """Reach the register the way an administrator does — via the Payroll menu.

        Falls back to the route when the sidebar is collapsed (it is on narrow
        viewports); how the user got here is worth showing, but it is not what
        this page object asserts.
        """
        link = self.page.get_by_role(
            "link", name=as_pattern(NAV_EMPLOYEE_BENEFITS)
        ).first
        if link.count():
            link.click()
            self.page.wait_for_url(LIST_URL, timeout=25_000)
            return self.expect_loaded()
        return self.open()

    def expect_nav_entry(self) -> None:
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_EMPLOYEE_BENEFITS)).first
        ).to_be_visible(timeout=25_000)

    # ────────────────────────── the register ─────────────────────

    def expect_loaded(self, timeout_ms: int = 30_000) -> "EmployeeBenefitsPage":
        """Assert the register is through its guards, however it was reached.

        ``useModuleGuard``/``usePermissionGuard`` render ``null`` rather than an
        error and a refused fetch swaps the whole screen for ``PageError``, so
        the heading being on screen is what says "this user got the register".
        """
        expect(
            self.page.get_by_role("heading", name=as_pattern(PAGE_HEADING)).first
        ).to_be_visible(timeout=timeout_ms)
        return self

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(as_pattern(LIST_LOAD_FAILURE))).to_have_count(0)

    def expect_column_headers(self) -> None:
        """Every column of the register, in the order page.tsx declares it.

        Anchored on ``thead th``: ``components/ui/table.tsx`` renders a bare
        ``<th>`` with no ``scope``, which Playwright resolves as ``cell`` rather
        than ``columnheader``.
        """
        for header in COLUMN_HEADERS:
            expect(
                self.page.locator("thead th").filter(
                    has_text=as_pattern(rf"^\s*{re.escape(header)}\s*$")
                ).first
            ).to_be_visible(timeout=15_000)

    def wait_for_rows(self, timeout_ms: int = 30_000) -> None:
        """Block until the table has settled on rows or on its empty state.

        The panel heading renders while "Loading employee benefits..." is still
        the only row, so asserting on the heading alone would pass mid-flight.
        """
        settled = self.page.get_by_text(as_pattern(EMPTY_REGISTER)).first.or_(
            self.page.locator("table tbody tr").filter(
                has_not_text=as_pattern(LOADING_ROW)
            ).first
        )
        expect(settled.first).to_be_visible(timeout=timeout_ms)

    def expect_register(self, timeout_ms: int = 30_000) -> None:
        """The register panel is on screen and has finished loading."""
        expect(self.page.get_by_text(as_pattern(TABLE_HEADING)).first).to_be_visible(
            timeout=timeout_ms
        )
        expect(self.page.get_by_text(as_pattern(COUNT_BADGE)).first).to_be_visible(
            timeout=timeout_ms
        )
        self.wait_for_rows(timeout_ms=timeout_ms)

    def row(self, text: str) -> Locator:
        """The register row carrying ``text`` — an email makes it unambiguous."""
        return self.page.get_by_role("row").filter(
            has_text=as_pattern(re.escape(text))
        ).first

    def expect_row(self, text: str, timeout_ms: int = 20_000) -> Locator:
        row = self.row(text)
        expect(row).to_be_visible(timeout=timeout_ms)
        return row

    def expect_no_row(self, text: str) -> None:
        expect(
            self.page.get_by_role("row").filter(has_text=as_pattern(re.escape(text)))
        ).to_have_count(0)

    def search(self, term: str) -> None:
        """Narrow the register. Filtering is client-side over the fetched list."""
        self.page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER)).first.fill(term)

    # ───────────────────── on to the form ────────────────────────

    def open_create_form(self) -> "EmployeeBenefitFormPage":
        """Press "Create Benefits" and land on the empty form.

        The button only renders for a role holding ``manage employee_benefit``
        (``usePermission`` → ``isManage``), so a read-only role fails here as a
        missing control rather than as a backend rejection.
        """
        self.page.get_by_role("button", name=as_pattern(CREATE_BUTTON)).first.click()
        form = EmployeeBenefitFormPage(self.page, self.frontend_base_url)
        self.page.wait_for_url(FORM_URL, timeout=25_000)
        return form.expect_create_loaded()

    def open_edit_form(self, row_text: str) -> "EmployeeBenefitFormPage":
        """Open one employee's package from the row menu's "Edit Benefits"."""
        row = self.expect_row(row_text)
        row.get_by_role("button", name=as_pattern(ROW_MENU_TRIGGER)).first.click()
        self.page.get_by_role("menuitem", name=as_pattern(EDIT_MENU_ITEM)).first.click()

        form = EmployeeBenefitFormPage(self.page, self.frontend_base_url)
        self.page.wait_for_url(re.compile(r"create-benefits\?user_id=\d+"), timeout=25_000)
        return form.expect_edit_loaded()


class EmployeeBenefitFormPage(BasePage):
    URL = "/module/employee_benefit/create-benefits"

    # ───────────────────────── loaded states ─────────────────────

    def expect_create_loaded(self, timeout_ms: int = 30_000) -> "EmployeeBenefitFormPage":
        expect(
            self.page.get_by_role("heading", name=as_pattern(CREATE_HEADING)).first
        ).to_be_visible(timeout=timeout_ms)
        self.expect_no_load_failure()
        return self

    def expect_edit_loaded(self, timeout_ms: int = 30_000) -> "EmployeeBenefitFormPage":
        expect(
            self.page.get_by_role("heading", name=as_pattern(EDIT_HEADING)).first
        ).to_be_visible(timeout=timeout_ms)
        self.expect_no_load_failure()
        return self

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(as_pattern(FORM_LOAD_FAILURE))).to_have_count(0)

    def expect_employee(self, name: str, timeout_ms: int = 20_000) -> None:
        """In edit mode the employee is a disabled ``<Input>`` holding
        "<first> <other> - <role>", prefilled from the fetched package."""
        expect(self.page.get_by_label(as_pattern(EMPLOYEE_LABEL)).first).to_have_value(
            as_pattern(re.escape(name)), timeout=timeout_ms
        )

    # ─────────────────────────── the fields ──────────────────────

    def select_employee(self, name: str) -> None:
        """Pick who the package is for (create mode only).

        The picker is ``showSearch`` over "<first> <other> - <role>", so the name
        is typed to narrow the list and then matched as a substring.
        """
        self._choose(EMPLOYEE_LABEL, re.compile(re.escape(name), re.I), search=name)

    def select_band(self, band_name: str) -> None:
        """Put the employee on a benefit band. Options read "<band> (<n> items)"."""
        self._choose(BENEFIT_BAND_LABEL, band_option(band_name))

    def select_extra_benefits(self, *item_names: str) -> None:
        """Add benefit items on top of the band. Multi-select: the dropdown stays
        open between picks, so it is dismissed with Escape at the end."""
        for name in item_names:
            self._choose(EXTRA_BENEFITS_LABEL, item_option(name), close=False)
        self.page.keyboard.press("Escape")

    def set_tax_relief(self, amount: str) -> None:
        self.fill_labeled(TAX_RELIEF_FIELD, amount)

    def set_overtime_tax_eligible(self, eligible: bool = True) -> None:
        checkbox = self.page.get_by_label(as_pattern(OVERTIME_LABEL)).first
        if eligible:
            checkbox.check()
        else:
            checkbox.uncheck()

    # ────────────────────────── submitting ───────────────────────

    def submit_create(self) -> None:
        """Save a new package and follow the redirect back to the register."""
        self._submit(CREATE_SUBMIT, CREATED_TOAST)

    def submit_update(self) -> None:
        """Save an edited package and follow the redirect back to the register."""
        self._submit(UPDATE_SUBMIT, UPDATED_TOAST)

    # ────────────────────────── internals ────────────────────────

    def _submit(self, button: re.Pattern[str], toast: re.Pattern[str]) -> None:
        self.page.get_by_role("button", name=as_pattern(button)).first.click()
        self.expect_toast(toast, timeout_ms=25_000)
        self.page.wait_for_url(LIST_URL, timeout=25_000)

    def _group(self, label: re.Pattern[str]) -> Locator:
        """The wrapper ``<div>`` holding one ``<label>`` and its control.

        Anchored on real ``<label>`` elements first: the sidebar carries link
        text identical to several field labels, and it is far earlier in the DOM.
        """
        labels = self.page.locator("label").filter(has_text=as_pattern(label))
        node = labels.first if labels.count() else self.page.get_by_text(
            as_pattern(label)
        ).first
        return node.locator("xpath=..")

    def _choose(
        self,
        label: re.Pattern[str],
        option: re.Pattern[str],
        *,
        search: str | None = None,
        close: bool = True,
    ) -> None:
        """Pick one option out of the antd Select labelled ``label``.

        The option is looked for inside the dropdown that is actually *open*:
        antd leaves every dropdown it has rendered mounted-but-hidden, so a
        page-wide match resolves to a closed picker's list and then waits forever
        for a hidden element to become clickable.
        """
        group = self._group(label)
        select = group.locator(".ant-select").first
        select.click()
        if search is not None:
            group.get_by_role("combobox").first.fill(search)

        item = self.page.locator(".ant-select-dropdown:visible").last.locator(
            ".ant-select-item-option"
        ).filter(has_text=as_pattern(option)).first
        try:
            item.wait_for(state="visible", timeout=20_000)
        except PlaywrightTimeoutError as exc:
            raise AssertionError(
                f"The {label.pattern!r} dropdown never offered an option matching "
                f"{option.pattern!r}. Every list on this form is fetched and "
                f"branch-scoped — employees from GET /employee-benefit/employees/, "
                f"bands from /salary-band/, items from /benefit-item/ — so an "
                f"option that is missing is a branch that was never seeded, not a "
                f"slow render."
            ) from exc
        item.click()
        if close:
            self.page.keyboard.press("Escape")
