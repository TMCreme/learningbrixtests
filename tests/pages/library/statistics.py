"""Library → Statistics page object (/module/statistics).

One read-only screen, "Overview of Book Statistics", assembled from seven
independent GETs (``smsfrontend/src/app/module/statistics/page.tsx`` plus
``components/StatisticContent.tsx``):

* the three header cards — ``/book-statistics/total-books``,
  ``…/total-books-borrowed``, ``…/total-books-available`` — rendered through
  ``components/common/ModuleHeader`` as a ``<dl>`` of ``<dt>``/``<dd>`` pairs;
* ``BookActivityChart``  → ``…/books-borrowed-vs-returned/{year}``, a recharts
  line chart behind a "Borrowed" / "Returned" legend and a year picker;
* ``BookStats``          → ``…/books-overview/{month}``, the "Additional Info"
  card, with a month picker over "Overdue Books" and "New Books Added";
* ``BookTable``          → ``…/recent-requests``, the "Recent Checkouts" table;
* ``ReadCategories``     → ``…/top-categories/{year}``, the "Most Read
  Categories" donut behind a second year picker.

There is no write path anywhere on this screen, so this object only reads.

Four things that are not obvious from the route:

* **A SchoolAdmin must have picked a branch first.** ``page.tsx``'s fetch effect
  returns early while ``useBranchStore`` is empty, so the three header cards
  never leave "Loading statistics…"; and every route answers 400
  BRANCH_ID_REQUIRED for that role without ``?branch_id``. Call
  ``BranchesPage.select_branch(...)`` before opening this page.
* **The sidebar never offers "Statistics" to a SchoolAdmin.** ``nav-config.tsx``
  gives that entry ``permission: "statistics"`` and
  ``SideNavigation.canShowItem`` returns on the permission check before the
  module gate — but ``db/repository/permissions.py`` seeds the SchoolAdmin role
  with ``catalogue``/``categories``/``requests_and_renewals`` and **no**
  ``statistics`` permission at all. The screen itself is wide open to them (both
  of ``page.tsx``'s guards exempt the role, and every ``/book-statistics`` route
  is gated on ``catalogue``, which they hold), so this is a gap between the nav
  config and the role seed — a product question, not something a test may close
  by granting the role a permission. ``open_from_nav`` therefore clicks the link
  when it is offered and falls back to the route when it is not, so the day the
  seed changes the demo improves by itself.
* **Both year pickers look identical.** The chart's and "Most Read Categories'"
  triggers both read the current year, so filtering comboboxes by their text
  finds two. Every control here is reached from the text beside it via
  ``_control_near`` instead.
* **Empty is a legitimate result.** A branch with no borrowing history renders
  ``EmptyState`` ("No Data Found") in the chart and in the categories donut, and
  zeros in the cards. Nothing here asserts that the library has activity — only
  that each panel resolved to *something* rather than to an error.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage

PAGE_HEADING = re.compile(r"^\s*Overview of Book Statistics\s*$", re.I)
PAGE_SUBHEADING = re.compile(
    r"An overview of all check-ins and check-outs of books", re.I
)

# Sidebar entry ("Library Module" section, ``branchOnly``). See the module
# docstring for why the Statistics link is not offered to a SchoolAdmin.
NAV_LIBRARY_SECTION = re.compile(r"^\s*Library Module\s*$", re.I)
NAV_STATISTICS = re.compile(r"^\s*Statistics\s*$", re.I)

LIST_URL = re.compile(r"/module/statistics")

# page.tsx's own two transient lines.
LOADING_STATISTICS = re.compile(r"^\s*Loading statistics\.\.\.\s*$", re.I)
LOAD_FAILURE = re.compile(r"Failed to fetch statistics", re.I)

# The three ModuleHeader cards, in the order page.tsx builds them.
TOTAL_BOOKS_CARD = re.compile(r"^\s*Total Books\s*$", re.I)
BORROWED_BOOKS_CARD = re.compile(r"^\s*Borrowed Books\s*$", re.I)
AVAILABLE_BOOKS_CARD = re.compile(r"^\s*Books Copies Available\s*$", re.I)
HEADER_CARDS = (TOTAL_BOOKS_CARD, BORROWED_BOOKS_CARD, AVAILABLE_BOOKS_CARD)

# What a card's <dd> holds: ``Number.toLocaleString()``, so thousands are
# grouped ("1,204").
CARD_VALUE = re.compile(r"^\s*[\d,]+\s*$")
# The line under it: an arrow, the signed percentage, then "vs last year".
CARD_CHANGE = re.compile(r"[\d.]+%\s*vs last year", re.I)

# BookActivityChart: the two series in its legend, and its EmptyState.
CHART_BORROWED_SERIES = re.compile(r"^\s*Borrowed\s*$", re.I)
CHART_RETURNED_SERIES = re.compile(r"^\s*Returned\s*$", re.I)
CHART_LOADING = re.compile(r"^\s*Loading data\.\.\.\s*$", re.I)
CHART_EMPTY_TITLE = re.compile(r"^\s*No Data Found\s*$", re.I)

# BookStats ("Additional Info"): its two rows, and the line it renders when the
# month's response could not be read at all.
ADDITIONAL_INFO_PANEL = re.compile(r"^\s*Additional Info\s*$", re.I)
OVERDUE_BOOKS_ROW = re.compile(r"^\s*Overdue Books\s*$", re.I)
NEW_BOOKS_ADDED_ROW = re.compile(r"^\s*New Books Added\s*$", re.I)
NO_INFO_AVAILABLE = re.compile(r"^\s*No data available\s*$", re.I)
# How a StatItem reads once its spans are concatenated: label, count, share.
INFO_ROW_VALUE = re.compile(r"[\d,]+\s*\([\d.]+%\)")

# BookTable ("Recent Checkouts") and its columns, in render order.
RECENT_CHECKOUTS_PANEL = re.compile(r"^\s*Recent Checkouts\s*$", re.I)
CHECKOUT_COLUMN_HEADERS = (
    re.compile(r"^\s*Title\s*$", re.I),
    re.compile(r"^\s*Author\s*$", re.I),
    re.compile(r"^\s*ISBN\s*$", re.I),
    re.compile(r"^\s*Category\s*$", re.I),
)
CHECKOUTS_EMPTY_TITLE = re.compile(r"^\s*No books found\s*$", re.I)

# ReadCategories.
MOST_READ_CATEGORIES_PANEL = re.compile(r"^\s*Most Read Categories\s*$", re.I)
CATEGORIES_EMPTY_TITLE = re.compile(r"^\s*No data found\s*$", re.I)
CATEGORIES_LOAD_FAILURE = re.compile(r"^\s*Failed to fetch data\. Please try again\.\s*$", re.I)


class StatisticsPage(BasePage):
    URL = "/module/statistics"

    # ────────────────────────── navigation ─────────────────────────

    def open(self) -> "StatisticsPage":
        super().open()
        self.expect_loaded()
        return self

    def open_from_nav(self) -> "StatisticsPage":
        """Reach the screen the way a user would — the sidebar entry.

        A recorded test has to show how someone gets to a module rather than
        teleport there. For a SchoolAdmin the entry is not drawn at all (see the
        module docstring: the role seed carries no ``statistics`` permission, and
        granting it is a product decision), so this falls back to the route —
        the workspace is the point, not the way in.
        """
        link = self.page.get_by_role("link", name=NAV_STATISTICS).first
        if link.count():
            link.click()
            self.page.wait_for_url(LIST_URL, timeout=20_000)
            self.expect_loaded()
            return self
        return self.open()

    def expect_library_section(self) -> None:
        """The ``branchOnly`` "Library Module" section is on offer.

        Asserted instead of the Statistics link itself: for a SchoolAdmin the
        section renders (they hold ``catalogue``/``categories``/
        ``requests_and_renewals``) while the Statistics entry inside it does not.
        """
        expect(self.page.get_by_text(NAV_LIBRARY_SECTION).first).to_be_visible(
            timeout=25_000
        )

    def expect_loaded(self) -> None:
        """Wait for the screen itself, not merely for the route.

        The heading mounts before any fetch resolves, so the first card is waited
        on too: for a SchoolAdmin with no branch selected the header never leaves
        "Loading statistics…", and waiting on something only the resolved screen
        renders is what turns that into a legible failure.
        """
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
            timeout=25_000
        )
        expect(self.card_label(TOTAL_BOOKS_CARD)).to_be_visible(timeout=30_000)
        self.expect_no_load_failure()

    # ───────────────────────── header cards ────────────────────────

    def card_label(self, name: re.Pattern[str]) -> Locator:
        """The ``<dt>`` naming one ModuleHeader card."""
        return self.page.locator("dl dt").filter(has_text=name).first

    def card_value(self, name: re.Pattern[str]) -> Locator:
        """The ``<dd>`` holding that card's number."""
        return self.card_label(name).locator("xpath=following-sibling::dd[1]")

    def card_change(self, name: re.Pattern[str]) -> Locator:
        """The "+x.xx% vs last year" line under that card's number."""
        return self.card_label(name).locator("xpath=following-sibling::div[1]")

    def expect_header_cards(self) -> None:
        """All three cards carry a real number and a comparison to last year."""
        for name in HEADER_CARDS:
            expect(self.card_label(name)).to_be_visible(timeout=30_000)
            expect(self.card_value(name)).to_have_text(CARD_VALUE, timeout=30_000)
            expect(self.card_change(name)).to_have_text(CARD_CHANGE)

    # ─────────────────────── the four panels ───────────────────────

    def expect_activity_chart(self) -> None:
        """The borrowing-vs-returns panel resolved — to a chart or to EmptyState.

        Both are correct outcomes: a branch that has lent nothing this year gets
        "No Data Found". What is asserted is that it stopped loading and that its
        legend is there to read the two series off.
        """
        expect(self.page.get_by_text(CHART_BORROWED_SERIES).first).to_be_visible(
            timeout=30_000
        )
        expect(self.page.get_by_text(CHART_RETURNED_SERIES).first).to_be_visible()
        expect(self.page.get_by_text(CHART_LOADING)).to_have_count(0, timeout=30_000)

    def expect_additional_info(self) -> None:
        """"Additional Info" shows the month's overdue books and new arrivals.

        ``/book-statistics/books-overview/{month}`` always answers with both
        counts (zeros for a quiet month), so "No data available" — the line
        BookStats falls back to when its state is still null — is a failure here,
        not an empty month.
        """
        expect(self.page.get_by_text(ADDITIONAL_INFO_PANEL).first).to_be_visible(
            timeout=30_000
        )
        expect(self.info_row(OVERDUE_BOOKS_ROW)).to_have_text(
            INFO_ROW_VALUE, timeout=30_000
        )
        expect(self.info_row(NEW_BOOKS_ADDED_ROW)).to_have_text(INFO_ROW_VALUE)
        expect(self.page.get_by_text(NO_INFO_AVAILABLE)).to_have_count(0)

    def info_row(self, label: re.Pattern[str]) -> Locator:
        """One "Additional Info" StatItem — label, count and share together."""
        return self.page.get_by_text(label).first.locator("xpath=../..")

    def expect_recent_checkouts(self) -> None:
        """The "Recent Checkouts" table, asserted header cell by header cell.

        Pinning the columns is the only durable claim this panel supports: the
        rows are whatever the branch last lent out, and an empty shelf renders
        EmptyState inside a single spanning cell.
        """
        expect(self.page.get_by_text(RECENT_CHECKOUTS_PANEL).first).to_be_visible(
            timeout=30_000
        )
        cells = self.page.locator("table thead tr").first.locator("th")
        expect(cells).to_have_count(len(CHECKOUT_COLUMN_HEADERS))
        for index, header in enumerate(CHECKOUT_COLUMN_HEADERS):
            expect(cells.nth(index)).to_have_text(header)

    def expect_most_read_categories(self) -> None:
        """The categories donut resolved — to slices or to its own EmptyState.

        Its ``catch`` branch prints "Failed to fetch data. Please try again.",
        which is asserted absent: that is the panel reporting a refused or broken
        GET, as distinct from a year with nothing borrowed in it.
        """
        expect(self.page.get_by_text(MOST_READ_CATEGORIES_PANEL).first).to_be_visible(
            timeout=30_000
        )
        expect(self.page.get_by_text(CATEGORIES_LOAD_FAILURE)).to_have_count(
            0, timeout=30_000
        )

    # ───────────────────────── the pickers ─────────────────────────

    def activity_year_picker(self) -> Locator:
        """BookActivityChart's year Select, found from its legend.

        The panel has no heading, so the "Borrowed" legend chip is the anchor;
        the nearest ancestor holding a combobox is the header row the picker
        shares with it.
        """
        return self._control_near(CHART_BORROWED_SERIES)

    def month_picker(self) -> Locator:
        """The "Additional Info" month Select."""
        return self._control_near(ADDITIONAL_INFO_PANEL)

    def categories_year_picker(self) -> Locator:
        """The "Most Read Categories" year Select — the *other* year picker."""
        return self._control_near(MOST_READ_CATEGORIES_PANEL)

    def select_activity_year(self, year: str) -> None:
        """Re-run the borrowed-vs-returned chart over another year."""
        self._pick(self.activity_year_picker(), year)
        expect(self.page.get_by_text(CHART_LOADING)).to_have_count(0, timeout=30_000)

    def select_month(self, month_name: str) -> None:
        """Re-run "Additional Info" over another month ("January", …)."""
        self._pick(self.month_picker(), month_name)

    def select_categories_year(self, year: str) -> None:
        """Re-run the most-read-categories donut over another year."""
        self._pick(self.categories_year_picker(), year)

    # ─────────────────────────── shared ────────────────────────────

    def expect_no_load_failure(self) -> None:
        """Fail loudly when page.tsx is showing its error line instead of cards.

        Without this, "the cards are absent" would read the same as "the cards
        are still loading", and a refused GET would look like a slow one.
        """
        expect(self.page.get_by_text(LOAD_FAILURE)).to_have_count(0)

    # ────────────────────────── internals ──────────────────────────

    def _control_near(self, anchor: re.Pattern[str]) -> Locator:
        """The Radix Select trigger sitting beside ``anchor``'s text.

        Both year pickers render the same value, so they cannot be told apart by
        their own text; and the labels here are headings and legend chips, not
        ``<label>``s, so ``BasePage.select_option_by_label`` has nothing to bind
        to. Walking up to the nearest ancestor that contains a combobox lands on
        the flex row the heading shares with its picker in all three cases.
        """
        node = self.page.get_by_text(anchor).first
        group = node.locator("xpath=ancestor::div[.//*[@role='combobox']][1]")
        return group.get_by_role("combobox").first

    def _pick(self, trigger: Locator, option: str) -> None:
        """Choose ``option`` from one Radix Select and wait for it to stick.

        The listbox is portalled, so the option is scoped to it rather than
        matched page-wide — the month picker and both year pickers would
        otherwise offer overlapping labels. Radix does unmount a closed
        ``SelectContent``, so a page-wide match is the fallback if that role ever
        moves off the content wrapper.

        The trigger is re-read afterwards: a Select whose value did not change
        (the option was already selected) is indistinguishable from one whose
        click missed, and this screen refetches on the value, not on the click.
        """
        pattern = re.compile(rf"^\s*{re.escape(option)}\s*$", re.I)
        trigger.click()
        listbox = self.page.get_by_role("listbox").last
        scope = listbox if listbox.count() else self.page
        scope.get_by_role("option", name=pattern).first.click()
        expect(trigger).to_have_text(pattern, timeout=15_000)
