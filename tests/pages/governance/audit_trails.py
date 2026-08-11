"""Audit Trails page object (``/module/audit_trails``).

One screen, rendered by ``smsfrontend/src/app/module/audit_trails/page.tsx``: a
search box, an action filter, a time filter, a paged table of audit rows and a
right-hand drawer that opens one row in full.

Things about this screen that shaped the selectors
    * **The two filters are Radix Selects with no label of any kind.** Their
      triggers carry only their own current value ("All actions", "All Data"),
      which changes the moment anything is picked — so neither
      ``BasePage.select_option_by_label`` (no ``<label>`` to anchor on) nor
      ``select_option_in_combobox`` (the trigger text is a moving target) can be
      used. They are addressed positionally *inside the filter bar*: the bar is
      reached from the search input's grandparent, so a combobox belonging to the
      page chrome can never be picked up by accident.
    * **The table is filtered client-side, over the current page only.**
      ``page.tsx`` fetches ten rows at a time and ``filterData`` narrows *those*
      — so the search box can only ever find something the fetch already
      returned. Anything a test wants to search for must therefore be among the
      newest rows for the branch, which is why the seeding in the test module
      happens immediately before the walkthrough.
    * **The drawer is an antd v6 ``Drawer``.** Its panel is
      ``role="dialog" aria-modal="true"`` (``@rc-component/drawer``'s
      ``DrawerPanel``), and it is not in the DOM at all until it is first opened,
      so it is matched by role and disambiguated by its title text rather than by
      a class name that antd is free to rename.
    * **Every field in the drawer is a bare ``<p>``/``<strong>`` label followed
      by its value.** There is no label association anywhere, so
      ``drawer_value()`` walks to the label's next sibling.

Deliberately not modelled: the "Confirm Revert" modal. ``page.tsx`` declares it
but nothing ever sets ``isModalOpen`` to true — there is no control on the screen
that opens it, and reverting an audited action is not a capability the backend
implements. Modelling it would be modelling a button that does not exist.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage

# ── page chrome ──────────────────────────────────────────────────────────────
HEADING = re.compile(r"^\s*Audit Logs\s*$", re.I)
SUBHEADING = re.compile(r"^\s*Track all system activities here\.\s*$", re.I)
# What PageError renders instead of the table when the mount fetch fails.
LOAD_FAILURE = re.compile(r"^\s*Failed to load audit logs\s*$", re.I)

# ── toolbar ──────────────────────────────────────────────────────────────────
SEARCH_FIELD = re.compile(r"^\s*Search logs\s*$", re.I)

# ── the action filter's four options (SelectItem labels) ─────────────────────
ALL_ACTIONS_OPTION = re.compile(r"^\s*All actions\s*$", re.I)
CREATE_OPTION = re.compile(r"^\s*Create\s*$", re.I)
UPDATE_OPTION = re.compile(r"^\s*Update\s*$", re.I)
DELETE_OPTION = re.compile(r"^\s*Delete\s*$", re.I)

# ── the time filter's five options ───────────────────────────────────────────
ALL_DATA_OPTION = re.compile(r"^\s*All Data\s*$", re.I)
THIS_WEEK_OPTION = re.compile(r"^\s*This week\s*$", re.I)
THIS_MONTH_OPTION = re.compile(r"^\s*This month\s*$", re.I)

# ── table ────────────────────────────────────────────────────────────────────
COLUMN_RECORD_ID = re.compile(r"^\s*Record ID\s*$", re.I)
COLUMN_CREATED_AT = re.compile(r"^\s*Created At\s*$", re.I)
COLUMN_USER = re.compile(r"^\s*User\s*$", re.I)
COLUMN_RESOURCE = re.compile(r"^\s*Resource\s*$", re.I)
# "Action" is used twice — once for the log's action, once for the row's
# controls — so it is never asserted as a unique column header.
DETAILS_BUTTON = re.compile(r"^\s*Details\s*$", re.I)
EMPTY_STATE = re.compile(r"^\s*No matching audit logs found\.\s*$", re.I)
PAGINATION = re.compile(r"Page\s+\d+\s+of\s+\d+", re.I)
PREVIOUS_BUTTON = re.compile(r"^\s*Previous\s*$", re.I)
NEXT_BUTTON = re.compile(r"^\s*Next\s*$", re.I)

# ── details drawer ───────────────────────────────────────────────────────────
DRAWER_TITLE = "Audit Log Details"
DRAWER_USER_DETAILS = "User Details"
DRAWER_TIME_OF_ACTION = "Time of Action:"
DRAWER_AFFECTED_RESOURCE = "Affected Resource:"
DRAWER_BEFORE_STATE = "Before State:"
DRAWER_AFTER_STATE = "After State:"
DRAWER_BRANCH_ID = "Branch ID:"
# What `parseState` falls back to for a state the row does not carry — a CREATE
# has no before-state, a DELETE no after-state.
DRAWER_NOT_PROVIDED = re.compile(r"^\s*Not Provided\s*$", re.I)


class AuditTrailsPage(BasePage):
    URL = "/module/audit_trails"

    # ─────────────────────────── page state ──────────────────────────────────

    def expect_loaded(self, timeout_ms: int = 30_000) -> None:
        """Wait for the register itself, not merely for the route.

        The whole screen is replaced by a spinner while the fetch is in flight
        and by ``PageError`` if it fails, so the heading is the first thing that
        means "the log rendered".
        """
        expect(self.page.get_by_role("heading", name=HEADING)).to_be_visible(
            timeout=timeout_ms
        )

    def expect_no_load_failure(self) -> None:
        expect(self.page.get_by_text(LOAD_FAILURE)).to_have_count(0)

    # ─────────────────────────── toolbar ─────────────────────────────────────

    def search_box(self) -> Locator:
        return self.page.get_by_placeholder(SEARCH_FIELD).first

    def search(self, term: str) -> None:
        """Type into the search box. ``""`` clears it again.

        The filter is applied by a ``useEffect`` on ``searchQuery``, so nothing
        needs to be pressed — and nothing may be: this input sits in the page's
        own form-less markup, but the project rule holds everywhere (never commit
        a value with Enter).
        """
        self.search_box().fill(term)

    def _filter_bar(self) -> Locator:
        """The row holding the search box and the two Selects.

        Reached from the search input rather than by class name: the input's
        parent is the icon wrapper, whose parent is the bar.
        """
        return self.search_box().locator("xpath=../..")

    def filter_by_action(self, option: str | re.Pattern) -> None:
        """Pick from the first Select in the filter bar."""
        self._select(0, option)

    def filter_by_period(self, option: str | re.Pattern) -> None:
        """Pick from the second Select in the filter bar."""
        self._select(1, option)

    def _select(self, index: int, option: str | re.Pattern) -> None:
        self._filter_bar().get_by_role("combobox").nth(index).click()
        # Radix portals its listbox to <body>, so the option is looked for at
        # page level rather than inside the bar.
        self.page.get_by_role("option", name=_pattern(option)).first.click()

    # ─────────────────────────── the table ───────────────────────────────────

    def column_header(self, name: str | re.Pattern) -> Locator:
        """The table's header cell for ``name``.

        Deliberately **not** ``get_by_role("columnheader", …)``. These headers
        are bare ``<th>`` with no ``scope`` attribute (``components/ui/table.tsx``
        renders ``TableHead`` as ``<th class=…>``), and Playwright's HTML-to-ARIA
        mapping only calls a ``<th>`` a ``columnheader`` when it carries
        ``scope="col"`` — otherwise it maps to ``cell`` (roleUtils' ``TH`` rule:
        scope col → columnheader, scope row → rowheader, else cell/gridcell).
        So the columnheader role resolves to nothing on this table, and asking
        for it would fail whatever the screen renders. Adding ``scope="col"`` to
        the app to suit the test is not this suite's call to make.
        """
        return self.page.locator("thead th").filter(has_text=_pattern(name))

    def log_row(self, *terms: str) -> Locator:
        """Rows carrying every one of ``terms``.

        Plain strings, not patterns: Playwright's ``has_text`` treats a string as
        a case-insensitive substring, which is what a table cell needs, and it
        sidesteps escaping the JSON and punctuation these rows are full of.
        """
        rows = self.page.get_by_role("row")
        for term in terms:
            rows = rows.filter(has_text=term)
        return rows

    def expect_empty(self, timeout_ms: int = 10_000) -> None:
        expect(self.page.get_by_text(EMPTY_STATE)).to_be_visible(timeout=timeout_ms)

    # ─────────────────────────── the drawer ──────────────────────────────────

    def drawer(self) -> Locator:
        return self.page.get_by_role("dialog").filter(has_text=DRAWER_TITLE).first

    def record_id_cell(self, row: Locator) -> Locator:
        """The Record ID cell of ``row`` — the table's first column."""
        return row.get_by_role("cell").first

    def open_details(self, row: Locator, timeout_ms: int = 15_000) -> Locator:
        """Open one row's drawer and return it."""
        row.get_by_role("button", name=DETAILS_BUTTON).first.click()
        drawer = self.drawer()
        expect(drawer).to_be_visible(timeout=timeout_ms)
        return drawer

    def drawer_value(self, label: str) -> Locator:
        """The value rendered next to ``label`` inside the drawer.

        Every field is ``<p>Label</p>`` (or ``<strong>Label</strong>``) followed
        by its value element — no ``for``, no ``aria-labelledby`` — so the value
        is the label's next sibling.
        """
        node = self.drawer().get_by_text(
            re.compile(rf"^\s*{re.escape(label)}\s*$", re.I)
        ).first
        return node.locator("xpath=following-sibling::*[1]")

    def close_drawer(self) -> None:
        self.drawer().locator("button.ant-drawer-close").first.click()


def _pattern(value: str | re.Pattern) -> re.Pattern:
    return value if isinstance(value, re.Pattern) else re.compile(value, re.I)
