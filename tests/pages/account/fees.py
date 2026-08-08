"""Account → Fee Management.

Two screens, one module:

``/module/fees`` (:class:`FeesPage`)
    The bursar's dashboard. Three derived totals across the top
    (``GET /fees/fee/statistics``), then one row per student billed by the branch
    (``GET /fee-payment/history``) with what they owe and what they last paid.
    Everything on it is a *read* of figures the backend computes; the row menu's
    Record Payment / Change Request / Send Reminder are the module's write side
    and are deliberately not exposed here.

``/module/fees/fees_config`` (:class:`FeesConfigPage`)
    What the school actually charges, on two tabs: "Fee Group" (the bundles a
    class is billed under, ``GET /fees/groups``) and "Fees" (the individual line
    items, ``GET /fees/``). Both tabs render a shadcn ``<Table>`` with a header
    row and either data rows or their own empty-state row.

Branch scoping
    Every fetch behind both screens appends ``branch_id`` from ``useBranchStore``
    when the caller is a SchoolAdmin, and that store is only filled by the branch
    row's "View" button on /module/school_admin_dashboard. Without it the fees
    list requests ``branch_id=undefined`` and the sidebar hides the whole Account
    section (its entries are ``branchOnly``), so a SchoolAdmin must select a
    branch before either screen is reachable — see
    ``BranchesPage.select_branch``.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, as_pattern

# ── routes ───────────────────────────────────────────────────────────────────
LIST_URL = re.compile(r"/module/fees(?:$|[?#])")
CONFIG_URL = re.compile(r"/module/fees/fees_config(?:$|[?#])")

# The sidebar entry, under the "Account Module" section
# (SideNavigation/nav-config.tsx). Anchored so it cannot also match the
# "Fee Report" entry directly beneath it.
NAV_FEE_MANAGEMENT = re.compile(r"^\s*Fee Management\s*$", re.I)

# ── the dashboard (src/app/module/fees/page.tsx) ─────────────────────────────
PAGE_HEADING = re.compile(r"^\s*Manage Fees\s*$", re.I)

# ModuleHeader tiles. The labels are hard-coded "(GHC)" in the frontend
# regardless of the school's configured currency, so they are quoted verbatim.
STAT_TOTAL_FEES = "Total Fees (GHC)"
STAT_TOTAL_PAID = "Total Paid (GHC)"
STAT_TOTAL_OUTSTANDING = "Total Outstanding (GHC)"
STAT_TILES = (STAT_TOTAL_FEES, STAT_TOTAL_PAID, STAT_TOTAL_OUTSTANDING)

# FeesTable.tsx — the panel over the student ledger, and its empty state.
LEDGER_HEADING = re.compile(r"^\s*All Students\s*$", re.I)
LEDGER_COUNT_BADGE = re.compile(r"\d+\s+students", re.I)
LEDGER_EMPTY = re.compile(r"^\s*No students found\s*$", re.I)

STUDENT_SEARCH_PLACEHOLDER = re.compile(r"^\s*Search student by name\s*$", re.I)
CLASS_FILTER_PLACEHOLDER = re.compile(r"^\s*All Classes\s*$", re.I)
CONFIGURE_FEES_BUTTON = re.compile(r"^\s*Configure Fees\s*$", re.I)

# PageError, mounted with this exact title when any of the three fetches fails.
LOAD_FAILURE_TITLE = re.compile(r"^\s*Failed to load fees data\s*$", re.I)

# ── fee configuration (fees_config/page.tsx and its two tabs) ────────────────
CONFIG_HEADING = re.compile(r"^\s*Configure Fees\s*$", re.I)
FEE_GROUP_TAB = re.compile(r"^\s*Fee Group\s*$", re.I)
FEES_TAB = re.compile(r"^\s*Fees\s*$", re.I)

# feeGroup.tsx
GROUPS_HEADING = re.compile(r"^\s*All Fee Structures\s*$", re.I)
GROUPS_COUNT_BADGE = re.compile(r"\d+\s+fee group\(s\)", re.I)
GROUPS_EMPTY = re.compile(r"^\s*No fee groups found\s*$", re.I)
GROUP_SEARCH_PLACEHOLDER = re.compile(r"^\s*Search fee group by name\s*$", re.I)
GROUP_HEADERS = (
    "Fee Group",
    "Amount Payable",
    "Fees Included",
    "Date Added",
    "Date Updated",
    "Actions",
)
GROUP_COLUMN = {
    "name": 0,
    "amount_payable": 1,
    "fees_included": 2,
    "date_added": 3,
    "date_updated": 4,
}

# fees.tsx
FEES_HEADING = re.compile(r"^\s*All Fees\s*$", re.I)
FEES_COUNT_BADGE = re.compile(r"\d+\s+fee\(s\)", re.I)
FEES_EMPTY = re.compile(r"^\s*No fees found\s*$", re.I)
FEES_NO_MATCH = re.compile(r"^\s*No matching fees found\s*$", re.I)
FEE_SEARCH_PLACEHOLDER = re.compile(r"^\s*Search fee by name\s*$", re.I)
FEE_HEADERS = (
    "Name",
    "Amount",
    "Description",
    "Academic Year",
    "Academic Term",
    "Date Created",
    "Actions",
)
FEE_COLUMN = {
    "name": 0,
    "amount": 1,
    "description": 2,
    "academic_year": 3,
    "academic_term": 4,
    "date_created": 5,
}

# ── the write side of the Fees tab (fees.tsx) ────────────────────────────────
#
# Create and edit share one antd ``<Modal>`` whose title is the only thing that
# distinguishes them (``currentFeeId ? "Edit Fee" : "Create New Fee"``), and antd
# leaves every modal it has opened mounted-but-hidden — so each is scoped by
# title rather than by ``get_by_role("dialog").first``, which would resolve to
# whichever one happens to be earlier in the DOM.
CREATE_FEE_BUTTON = re.compile(r"^\s*Create Fee\s*$", re.I)
CREATE_FEE_MODAL = re.compile(r"Create New Fee", re.I)
EDIT_FEE_MODAL = re.compile(r"Edit Fee", re.I)

# antd swaps the OK label while the request is in flight ("Creating..." /
# "Updating..."), so each pattern covers both faces of the same button.
CREATE_FEE_SUBMIT = re.compile(r"^\s*Creat(e|ing)", re.I)
UPDATE_FEE_SUBMIT = re.compile(r"^\s*Updat(e|ing)", re.I)

# The modal's ``<label>``s carry no ``htmlFor``, so ``get_by_label`` never binds
# and the placeholder alternation in each pattern is what actually matches.
FEE_NAME_FIELD = re.compile(r"^\s*Name\s*\*?\s*$|^\s*Enter fee name\s*$", re.I)
FEE_AMOUNT_FIELD = re.compile(r"^\s*Amount\s*\*?\s*$|^\s*Enter amount\s*$", re.I)
FEE_DESCRIPTION_FIELD = re.compile(
    r"^\s*Description\s*$|^\s*Enter description \(optional\)\s*$", re.I
)

# The two Radix selects, anchored on the label beside them: their triggers show
# the placeholder until a value is picked, which is not enough to tell them
# apart from every other combobox on the screen.
FEE_YEAR_LABEL = re.compile(r"Academic Year", re.I)
FEE_TERM_LABEL = re.compile(r"Academic Term", re.I)

FEE_CREATED_TOAST = re.compile(r"fee created successfully", re.I)
FEE_UPDATED_TOAST = re.compile(r"fee updated successfully", re.I)

# Row menu (Radix DropdownMenu). "Edit" is offered to every role, but what it
# opens depends on the permission — ``isManage`` picks the editable modal and
# everyone else gets ``FeeChangeRequestModal`` — and the destructive item is
# "Delete" for a manager against "Request Delete" for everybody else. So which
# of the two is rendered is itself the assertion that the user holds
# ``("manage", "fees")``.
EDIT_FEE_ITEM = re.compile(r"^\s*Edit\s*$", re.I)
DELETE_FEE_ITEM = re.compile(r"^\s*Delete\s*$", re.I)
REQUEST_DELETE_ITEM = re.compile(r"^\s*Request Delete\s*$", re.I)


class FeesPage(BasePage):
    URL = "/module/fees"

    # ───────────────────────── navigation ────────────────────────

    def open(self) -> "FeesPage":
        super().open()
        return self.expect_loaded()

    def open_from_sidebar(self) -> "FeesPage":
        """Reach the dashboard the way a bursar does — via the Account menu.

        Falls back to the route when the sidebar is collapsed (it is on narrow
        viewports); how the user got here is worth showing, but it is not what
        this page object asserts.
        """
        link = self.page.get_by_role("link", name=as_pattern(NAV_FEE_MANAGEMENT)).first
        if link.count():
            link.click()
            self.page.wait_for_url(LIST_URL, timeout=25_000)
            return self.expect_loaded()
        return self.open()

    def expect_nav_entry(self) -> None:
        expect(
            self.page.get_by_role("link", name=as_pattern(NAV_FEE_MANAGEMENT)).first
        ).to_be_visible(timeout=25_000)

    def expect_loaded(self, timeout_ms: int = 30_000) -> "FeesPage":
        """Assert the dashboard is through its guards, however it was reached.

        ``useModuleGuard``/``usePermissionGuard`` render ``null`` rather than an
        error, and a refused fetch swaps the whole screen for ``PageError`` — so
        the heading being on screen is what says "this user got the dashboard".
        """
        expect(
            self.page.get_by_role("heading", name=as_pattern(PAGE_HEADING))
        ).to_be_visible(timeout=timeout_ms)
        return self

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(as_pattern(LOAD_FAILURE_TITLE))).to_have_count(0)

    # ─────────────────────── the three totals ────────────────────

    def stat_tile(self, name: str) -> Locator:
        """One ModuleHeader card, found by its ``<dt>`` label."""
        return self.page.locator("dl > div").filter(
            has_text=as_pattern(re.escape(name))
        ).first

    def expect_stats(self, timeout_ms: int = 25_000) -> None:
        """Every total is rendered, and each carries a figure.

        The figures themselves are the backend's — ``transformStatsData`` only
        ever runs on a resolved ``GET /fees/fee/statistics`` — so this asserts the
        shape of the summary rather than an amount, which depends on what the
        branch has billed.
        """
        for name in STAT_TILES:
            tile = self.stat_tile(name)
            expect(tile).to_be_visible(timeout=timeout_ms)
            expect(tile).to_contain_text(re.compile(r"\d"))

    # ─────────────────────── the student ledger ──────────────────

    def wait_for_ledger(self, timeout_ms: int = 30_000) -> None:
        """Block until the ledger has settled on rows or on its empty state.

        The panel heading renders while ``StudentFeeHistoryLoader`` is still on
        screen, so asserting on the heading alone would pass mid-flight.
        """
        settled = self.page.get_by_text(as_pattern(LEDGER_EMPTY)).first.or_(
            self.page.locator("table tbody tr").first
        )
        expect(settled.first).to_be_visible(timeout=timeout_ms)

    def expect_ledger(self, timeout_ms: int = 30_000) -> None:
        """The ledger panel is on screen and has finished loading."""
        expect(self.page.get_by_text(as_pattern(LEDGER_HEADING)).first).to_be_visible(
            timeout=timeout_ms
        )
        expect(self.page.get_by_text(as_pattern(LEDGER_COUNT_BADGE)).first).to_be_visible(
            timeout=timeout_ms
        )
        self.wait_for_ledger(timeout_ms=timeout_ms)

    def expect_filters(self) -> None:
        """The two controls a bursar narrows the ledger with."""
        expect(
            self.page.get_by_placeholder(as_pattern(STUDENT_SEARCH_PLACEHOLDER)).first
        ).to_be_visible()
        expect(
            self.page.get_by_role("combobox").filter(
                has_text=as_pattern(CLASS_FILTER_PLACEHOLDER)
            ).first
        ).to_be_visible()

    def find_student_row(self, name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has_text=as_pattern(re.escape(name))
        ).first

    # ────────────────────── on to the configuration ──────────────

    def open_fee_configuration(self) -> "FeesConfigPage":
        self.click_button(CONFIGURE_FEES_BUTTON)
        config = FeesConfigPage(self.page, self.frontend_base_url)
        self.page.wait_for_url(CONFIG_URL, timeout=25_000)
        return config.expect_loaded()


class FeesConfigPage(BasePage):
    URL = "/module/fees/fees_config"

    def open(self) -> "FeesConfigPage":
        super().open()
        return self.expect_loaded()

    def expect_loaded(self, timeout_ms: int = 30_000) -> "FeesConfigPage":
        expect(
            self.page.get_by_role("heading", name=as_pattern(CONFIG_HEADING))
        ).to_be_visible(timeout=timeout_ms)
        return self

    # ─────────────────────────── tabs ────────────────────────────

    def open_fee_groups_tab(self) -> "FeesConfigPage":
        self.click_button(FEE_GROUP_TAB)
        expect(self.page.get_by_text(as_pattern(GROUPS_HEADING)).first).to_be_visible(
            timeout=25_000
        )
        return self

    def open_fees_tab(self) -> "FeesConfigPage":
        self.click_button(FEES_TAB)
        expect(self.page.get_by_text(as_pattern(FEES_HEADING)).first).to_be_visible(
            timeout=25_000
        )
        return self

    # ───────────────────────── fee groups ────────────────────────

    def expect_fee_group_headers(self) -> None:
        self._expect_headers(GROUP_HEADERS)

    def expect_fee_group_count(self) -> None:
        expect(self.page.get_by_text(as_pattern(GROUPS_COUNT_BADGE)).first).to_be_visible(
            timeout=25_000
        )

    def wait_for_fee_groups(self, timeout_ms: int = 30_000) -> None:
        self._wait_for_rows(GROUPS_EMPTY, timeout_ms=timeout_ms)

    def fee_group_row(self, name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has_text=as_pattern(re.escape(name))
        ).first

    def expect_fee_group(
        self,
        name: str,
        *,
        amount_payable: str | re.Pattern[str] | None = None,
        includes: tuple[str, ...] = (),
        timeout_ms: int = 25_000,
    ) -> None:
        """Assert one bundle: its name, its total, and the fees it rolls up.

        ``amount_payable`` is the *frontend's* sum
        (``calculateTotalAmount`` → "GHC 300.00"), so matching it proves the row
        was built from the fees the backend attached to the group rather than
        from anything the browser was told separately.
        """
        row = self.fee_group_row(name)
        expect(row).to_be_visible(timeout=timeout_ms)
        if amount_payable is not None:
            expect(row.get_by_role("cell").nth(GROUP_COLUMN["amount_payable"])).to_have_text(
                as_pattern(amount_payable) if isinstance(amount_payable, str)
                else amount_payable
            )
        for fee_name in includes:
            expect(
                row.get_by_role("cell").nth(GROUP_COLUMN["fees_included"])
            ).to_contain_text(as_pattern(re.escape(fee_name)))

    def search_fee_groups(self, term: str) -> None:
        self.page.get_by_placeholder(as_pattern(GROUP_SEARCH_PLACEHOLDER)).first.fill(term)

    # ──────────────────────── individual fees ────────────────────

    def expect_fee_headers(self) -> None:
        self._expect_headers(FEE_HEADERS)

    def expect_fee_count(self) -> None:
        expect(self.page.get_by_text(as_pattern(FEES_COUNT_BADGE)).first).to_be_visible(
            timeout=25_000
        )

    def wait_for_fees(self, timeout_ms: int = 30_000) -> None:
        self._wait_for_rows(FEES_EMPTY, FEES_NO_MATCH, timeout_ms=timeout_ms)

    def fee_row(self, name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has_text=as_pattern(re.escape(name))
        ).first

    def expect_fee(
        self,
        name: str,
        *,
        amount: str | re.Pattern[str] | None = None,
        description: str | None = None,
        academic_year: str | None = None,
        academic_term: str | None = None,
        timeout_ms: int = 25_000,
    ) -> None:
        """Assert one line item and the year/term it is billed for.

        The year and term are joined server-side (``FeeResponse.academic_year`` /
        ``academic_term``), so reading them back off the row proves the fee is
        attached to the school's active calendar and not merely named after it.
        """
        row = self.fee_row(name)
        expect(row).to_be_visible(timeout=timeout_ms)
        cells = row.get_by_role("cell")
        if amount is not None:
            expect(cells.nth(FEE_COLUMN["amount"])).to_have_text(
                as_pattern(amount) if isinstance(amount, str) else amount
            )
        if description is not None:
            expect(cells.nth(FEE_COLUMN["description"])).to_have_text(
                as_pattern(rf"^\s*{re.escape(description)}\s*$")
            )
        if academic_year is not None:
            expect(cells.nth(FEE_COLUMN["academic_year"])).to_have_text(
                as_pattern(rf"^\s*{re.escape(academic_year)}\s*$")
            )
        if academic_term is not None:
            expect(cells.nth(FEE_COLUMN["academic_term"])).to_have_text(
                as_pattern(rf"^\s*{re.escape(academic_term)}\s*$")
            )

    def search_fees(self, term: str) -> None:
        """Filter the Fees tab. The filter is client-side over the fetched page."""
        self.page.get_by_placeholder(as_pattern(FEE_SEARCH_PLACEHOLDER)).first.fill(term)

    def expect_fee_absent(self, name: str) -> None:
        expect(
            self.page.get_by_role("row").filter(has_text=as_pattern(re.escape(name)))
        ).to_have_count(0)

    # ──────────────────── writing a fee (manage) ─────────────────

    def open_create_fee_modal(self) -> Locator:
        """Press "Create Fee" and return the modal it opened.

        Only a role holding ``("manage", "fees")`` gets this modal:
        ``handleCreateClick`` opens ``FeeChangeRequestModal`` instead for anyone
        else, so waiting on the "Create New Fee" title is also the assertion
        that this user writes the fee directly rather than filing a request for
        somebody else to write it.
        """
        self.click_button(CREATE_FEE_BUTTON)
        modal = self._modal(CREATE_FEE_MODAL)
        expect(modal).to_be_visible(timeout=20_000)
        return modal

    def fill_fee_form(
        self,
        modal: Locator,
        *,
        name: str | None = None,
        amount: str | int | None = None,
        description: str | None = None,
        academic_year: str | None = None,
        academic_term: str | None = None,
    ) -> None:
        """Type into whichever of the shared create/edit modals is open.

        Every argument is optional because the edit modal opens pre-filled from
        the row, so a caller may change one field and leave the rest alone.

        Order matters for the two selects: picking a year clears
        ``academic_term_id`` and refetches ``/academic-term/by-year/{id}``, which
        is what re-enables the term trigger — so the term is always chosen after
        the year.
        """
        if name is not None:
            self._fill_in(modal, FEE_NAME_FIELD, name)
        if amount is not None:
            self._fill_in(modal, FEE_AMOUNT_FIELD, str(amount))
        if description is not None:
            self._fill_in(modal, FEE_DESCRIPTION_FIELD, description)
        if academic_year is not None:
            # SelectItem renders "<name> (active|inactive)", and an academic year
            # is named "2026/2027" — the slash is why every selector here goes
            # through as_pattern (see tests/pages/base.as_pattern).
            self._select_in(
                modal,
                FEE_YEAR_LABEL,
                rf"^\s*{re.escape(academic_year)}\s*\(",
            )
        if academic_term is not None:
            self._select_in(
                modal,
                FEE_TERM_LABEL,
                rf"^\s*{re.escape(academic_term)}\s*$",
            )

    def submit_fee_create(self, modal: Locator) -> None:
        """Press OK on the create modal and wait for the fee to be accepted.

        antd keeps OK disabled until name, amount, year and term are all set
        (``okButtonProps.disabled``), so waiting for it to be enabled doubles as
        the assertion that the form took every value.
        """
        self._submit(modal, CREATE_FEE_SUBMIT, FEE_CREATED_TOAST)

    def submit_fee_update(self, modal: Locator) -> None:
        self._submit(modal, UPDATE_FEE_SUBMIT, FEE_UPDATED_TOAST)

    def create_fee(
        self,
        *,
        name: str,
        amount: str | int,
        academic_year: str,
        academic_term: str,
        description: str | None = None,
    ) -> None:
        """Add one line item to what the school charges, end to end."""
        modal = self.open_create_fee_modal()
        self.fill_fee_form(
            modal,
            name=name,
            amount=amount,
            description=description,
            academic_year=academic_year,
            academic_term=academic_term,
        )
        self.submit_fee_create(modal)

    def open_edit_fee_modal(self, name: str) -> Locator:
        """Open ``name``'s row menu, choose Edit, and return the modal.

        As with create, the modal that appears is permission-dependent — the
        change-request modal carries a different title — so this waits on "Edit
        Fee" specifically.
        """
        self.open_fee_row_menu(name)
        self.page.get_by_role("menuitem", name=as_pattern(EDIT_FEE_ITEM)).first.click()
        modal = self._modal(EDIT_FEE_MODAL)
        expect(modal).to_be_visible(timeout=20_000)
        return modal

    def edit_fee(
        self,
        *,
        name: str,
        new_name: str | None = None,
        amount: str | int | None = None,
        description: str | None = None,
    ) -> None:
        """Revise an existing fee from its row menu."""
        modal = self.open_edit_fee_modal(name)
        self.fill_fee_form(
            modal, name=new_name, amount=amount, description=description
        )
        self.submit_fee_update(modal)

    def open_fee_row_menu(self, name: str) -> None:
        """Open the per-row actions menu.

        The trigger is a ghost ``<Button>`` wrapping a lucide ``MoreHorizontal``
        with no accessible name, and it is the only button in the row, so it is
        reached positionally.
        """
        row = self.fee_row(name)
        expect(row).to_be_visible(timeout=25_000)
        row.get_by_role("button").last.click()

    def close_fee_row_menu(self) -> None:
        """Dismiss the row menu without choosing anything."""
        self.page.keyboard.press("Escape")

    # ───────────────────────── internals ─────────────────────────

    def _modal(self, title: re.Pattern[str]) -> Locator:
        """Scope to one antd Modal — every one of them stays mounted once opened."""
        return self.page.get_by_role("dialog").filter(has_text=as_pattern(title)).first

    def _fill_in(self, modal: Locator, field: re.Pattern[str], value: str) -> None:
        """Fill a field inside one specific modal.

        Deliberately not ``BasePage.fill_labeled(..., in_dialog=True)``: that
        scopes to *every* mounted dialog and takes ``.first``, which on this
        screen is whichever antd modal was opened earliest rather than the one on
        screen.
        """
        loc = modal.get_by_label(as_pattern(field)).first
        if loc.count() == 0:
            loc = modal.get_by_placeholder(as_pattern(field)).first
        loc.fill(value)

    def _select_in(
        self, modal: Locator, label: re.Pattern[str], option: str
    ) -> None:
        """Pick from a Radix select inside ``modal``, anchored on its label.

        The trigger is found through the label's parent — the fields are laid out
        as ``<div><label/><Select/></div>`` — because a Radix trigger showing only
        its placeholder has no text worth filtering on. The listbox itself is
        portalled to ``document.body``, so the option is looked for page-wide and
        not inside the modal.
        """
        group = modal.locator("label").filter(has_text=label).first.locator("xpath=..")
        trigger = group.get_by_role("combobox").first
        # The term select is `disabled` until its year's terms have arrived.
        expect(trigger).to_be_enabled(timeout=25_000)
        trigger.click()
        choice = self.page.get_by_role("option", name=as_pattern(option)).first
        expect(choice).to_be_visible(timeout=20_000)
        choice.click()

    def _submit(
        self,
        modal: Locator,
        button: re.Pattern[str],
        toast: re.Pattern[str],
    ) -> None:
        ok = modal.get_by_role("button", name=as_pattern(button)).first
        expect(ok).to_be_enabled(timeout=20_000)
        ok.click()
        self.expect_toast(toast, timeout_ms=25_000)
        expect(modal).to_be_hidden(timeout=15_000)

    def _expect_headers(self, headers: tuple[str, ...]) -> None:
        """Assert the header row by position, which pins the column order the
        ``*_COLUMN`` maps index into."""
        header_cells = self.page.locator("table thead tr").first.locator("th")
        expect(header_cells).to_have_count(len(headers))
        for index, header in enumerate(headers):
            expect(header_cells.nth(index)).to_have_text(
                as_pattern(rf"^\s*{re.escape(header)}\s*$")
            )

    def _wait_for_rows(self, *empty_states: re.Pattern[str],
                       timeout_ms: int = 30_000) -> None:
        """Block until the table settles on data rows or on an empty-state row.

        Both tabs render their header immediately and swap a spinner for the body,
        so an assertion made on the heading alone would pass mid-flight. Only data
        rows carry a ``font-medium`` first cell — the empty state is a single
        centred cell spanning the table.
        """
        body = self.page.locator("table tbody")
        settled = body.locator("td.font-medium").first
        for empty in empty_states:
            settled = settled.or_(body.get_by_text(as_pattern(empty)).first)
        expect(settled.first).to_be_visible(timeout=timeout_ms)
