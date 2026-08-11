"""Library → Statistics — the book-activity dashboard (`statistics`).

Where this module lives
    ``/module/statistics`` (``smsfrontend/src/app/module/statistics/page.tsx``).
    A single read-only screen — "Overview of Book Statistics" — with no write
    path at all. Its header cards come from three
    ``GET /book-statistics/total-books*`` calls made by ``page.tsx`` itself, and
    ``components/StatisticContent.tsx`` composes four more panels, each with its
    own fetch:

    * ``BookActivityChart``  → ``/book-statistics/books-borrowed-vs-returned/{year}``
    * ``BookStats``          → ``/book-statistics/books-overview/{month}``
    * ``BookTable``          → ``/book-statistics/recent-requests``
    * ``ReadCategories``     → ``/book-statistics/top-categories/{year}``

View path: a SchoolAdmin of the ``library_and_community`` school reads the whole
board — the three header cards and all four panels
(``test_school_admin_views_library_statistics``).

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack is the
floor case the pack builder can actually produce — the locked "people" and
"governance" groups and nothing else, so no library group and therefore no
``statistics`` (``test_statistics_denied_for_school_admin_when_module_disabled``).

The gate key is ``catalogue``, not ``statistics`` — and that matters here
    Every route in ``newschoolapp/api/routes/book_statistics.py`` is declared
    ``dependencies=[Depends(has_permission("read", "catalogue"))]``. Not one of
    them names ``statistics``; the only module that does is the *nav* entry and
    ``page.tsx``'s two client-side guards. So what the backend actually refuses
    this school for is the ``catalogue`` licence.

    That is asserted explicitly below rather than glossed over: the ``minimal``
    pack omits both keys, so the denial holds either way, but a pack that
    licensed ``catalogue`` while withholding ``statistics`` would serve every
    number on this screen. That is a product question about how the library group
    is licensed, not a defect this suite may close by tightening a gate, so the
    assertion pins the premise and says so if it ever stops being true.

Where the denial actually lives — and where it does NOT
    Not in the middleware and not in either guard ``page.tsx`` calls. Both wave a
    SchoolAdmin through before any feature pack is consulted:

    * ``useModuleGuard("statistics")`` sets ``hasAccess = true`` for a SchoolAdmin
      *before* it reads the ``schoolModules`` cookie, so the
      ``hasModuleAccess === false`` branch — the one returning ``null`` and
      pushing /auth/no-access — is unreachable for this role.
    * ``usePermissionGuard("statistics")`` returns early on
      ``isSchoolAdminRole(role)`` in its effect, and its ``hasAccess`` memo
      returns ``true`` on the same test, so ``if (!hasAccess) return null`` never
      fires either.
    * ``src/middleware.ts`` exempts a SchoolAdmin from module enforcement, so the
      route is never turned away before it mounts.

    What denies them is the backend 403, and the axios response interceptor in
    ``src/utils/handleErrorMessage.ts`` is what turns it into a denial: its
    ``shouldRedirectToNoAccess`` recognises the "not available in your plan"
    detail and performs a hard ``window.location`` redirect to
    **/auth/no-access**. So the landing page — not the "Failed to fetch
    statistics" line this page renders for an ordinary fetch failure — is the
    denial surface, and that line is asserted absent below for exactly that
    reason.

Why the branch is selected first
    ``page.tsx``'s own fetch effect returns early for a SchoolAdmin while
    ``currentSchoolAdminBranch?.branch_id`` is unset::

        if (authUserProfile?.roles?.name?.toLowerCase().includes("schooladmin") …) {
          if (!currentSchoolAdminBranch?.branch_id) return;
        }

    With no branch in the store the header cards issue no request at all, so the
    header half of the screen produces no 403 and no redirect. (The four panels
    in ``StatisticContent`` fetch unconditionally on mount, so a redirect would
    probably still arrive — but by an accident of their missing branch guard, not
    by the path a real user takes.) ``BranchesPage.select_branch`` fills the store
    the same way every SchoolAdmin create needs it filled, which makes the denial
    observable on the path the app is actually built around.

Deliberately *not* asserted: that the sidebar hides "Statistics"
    ``nav-config.tsx`` gives that entry ``permission: "statistics"``, and
    ``SideNavigation.canShowItem`` returns on the permission check before the
    module gate. The seeded SchoolAdmin role holds ``catalogue``, ``categories``
    and ``requests_and_renewals`` but **no** ``statistics`` permission at all
    (``db/repository/permissions.py``), so that entry is hidden for this role in
    *every* school — licensed or not. Its absence would therefore prove nothing
    about this school's pack, and asserting it would make the test pass for a
    reason that has nothing to do with licensing.

This module has no write path, so there is nothing to create and nothing for the
sweeper to collect: every assertion below is a read.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.library.statistics import StatisticsPage
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

STATISTICS_MODULE = "statistics"

# The module key every /book-statistics/* route is *actually* gated on — see the
# docstring. Both are absent from the `minimal` pack.
GATE_MODULE = "catalogue"

# config/module_catalog.py's route for this module.
STATISTICS_ROUTE = "statistics"

DENIED_SCENARIO = "minimal"

# The role whose permissions are checked against the pack.
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIAL_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# Where the frontend sends a user it has decided is not allowed in, and the copy
# it greets them with (src/app/auth/no-access/page.tsx).
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

# ── the statistics screen's own chrome, none of which may reach this admin ────
# src/app/module/statistics/page.tsx and its components/.
STATISTICS_HEADING = re.compile(r"^\s*Overview of Book Statistics\s*$", re.I)
STATISTICS_SUBHEADING = re.compile(
    r"An overview of all check-ins and check-outs of books", re.I
)
# The three ModuleHeader cards page.tsx builds from the total-books* responses.
TOTAL_BOOKS_CARD = re.compile(r"^\s*Total Books\s*$", re.I)
BORROWED_BOOKS_CARD = re.compile(r"^\s*Borrowed Books\s*$", re.I)
AVAILABLE_BOOKS_CARD = re.compile(r"^\s*Books Copies Available\s*$", re.I)
# The four StatisticContent panels.
ACTIVITY_CHART_LEGEND = re.compile(r"^\s*Borrowed\s*$", re.I)
ADDITIONAL_INFO_PANEL = re.compile(r"^\s*Additional Info\s*$", re.I)
RECENT_CHECKOUTS_PANEL = re.compile(r"^\s*Recent Checkouts\s*$", re.I)
MOST_READ_CATEGORIES_PANEL = re.compile(r"^\s*Most Read Categories\s*$", re.I)
# BookTable's column headers.
BOOK_TABLE_ISBN_COLUMN = re.compile(r"^\s*ISBN\s*$", re.I)
# The line page.tsx renders when its own fetch fails for any *ordinary* reason.
# Seeing it would mean a licensing refusal had been handled as a plain error
# instead of as a denial.
STATISTICS_LOAD_FAILURE = re.compile(r"Failed to fetch statistics", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_statistics_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With the library group off the pack, a SchoolAdmin gets no book statistics."""
    ctx = provisioned_school
    if STATISTICS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {STATISTICS_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had library rights anyway", which would make the 403s vacuous.
    # db/repository/permissions.py seeds this role with ("manage", "catalogue"),
    # and has_permission lets manage stand in for read — so the permission half
    # of every gate asserted below passes outright, leaving the feature pack as
    # the only thing that can refuse.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert GATE_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a {GATE_MODULE!r} "
        f"permission, which is the one every /book-statistics route is gated on "
        f"(api/routes/book_statistics.py). This test would then be asserting a "
        f"denial the role gets for free. Re-point it at the feature pack only, or "
        f"fix the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{STATISTICS_MODULE!r} proves nothing about the gate. Provisioning "
        f"phase A assigns one — check that it did."
    )
    licensed = body.get("modules") or []
    assert STATISTICS_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {STATISTICS_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )
    # The premise of everything below: the routes name `catalogue`, so that is
    # the key that has to be unlicensed for the screen to be refused. If a pack
    # ever licenses catalogue without statistics, this screen serves every number
    # on it while the product considers the module off — a licensing question for
    # the product owner, not a gate this suite may tighten on its own.
    assert GATE_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {GATE_MODULE!r}, which is the module "
        f"key every /book-statistics route is gated on — so the statistics screen "
        f"is served in full even though {STATISTICS_MODULE!r} is off the pack. "
        f"That is a product decision about how the library group is licensed "
        f"(the routes never name {STATISTICS_MODULE!r}), not something this test "
        f"can assert around: escalate it rather than adding a gate."
    )

    # ── 2. The denial itself: every book-statistics route is refused ──────────
    #
    # All seven routes the screen calls, in the shape page.tsx and its four
    # panels build them for a SchoolAdmin (branch-scoped). The path params are
    # arbitrary-but-legal: has_permission is a route-level dependency, solved
    # before the handler runs, so the year/month never reach the service. The
    # list read is asserted unscoped as well, because without a branch_id the
    # *handler* answers 400 BRANCH_ID_REQUIRED — the licence must be refused
    # before that ever runs, and a 400 here would mean it was not.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"?branch_id={branch_id}" if branch_id else ""
    year = date.today().year
    month = date.today().month

    refusals = {
        # The three header cards page.tsx fetches itself.
        "total_books": api.get(
            f"/book-statistics/total-books{branch_query}", token=token
        ),
        "total_books_borrowed": api.get(
            f"/book-statistics/total-books-borrowed{branch_query}", token=token
        ),
        "total_books_available": api.get(
            f"/book-statistics/total-books-available{branch_query}", token=token
        ),
        # …and the four StatisticContent panels.
        "books_borrowed_vs_returned": api.get(
            f"/book-statistics/books-borrowed-vs-returned/{year}{branch_query}",
            token=token,
        ),
        "books_overview": api.get(
            f"/book-statistics/books-overview/{month}{branch_query}", token=token
        ),
        "recent_requests": api.get(
            f"/book-statistics/recent-requests{branch_query}", token=token
        ),
        "top_categories": api.get(
            f"/book-statistics/top-categories/{year}{branch_query}", token=token
        ),
        # The licence is refused before the handler's own branch check.
        "total_books_unscoped": api.get(
            "/book-statistics/total-books", token=token
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{STATISTICS_MODULE!r}/{GATE_MODULE!r}, so the backend must refuse "
            f"with 403 — got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a statistics screen in front of them ────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory, and not merely the usual SchoolAdmin branch prerequisite: this
    # page's header effect refuses to fetch anything until the branch store is
    # filled (see the module docstring), and it is the path a real user takes
    # into the module. Selecting the branch is what makes the denial observable
    # for the right reason.
    if ctx.branches:
        BranchesPage(page, frontend_base_url).select_branch(ctx.branches[0]["name"])

    # A SchoolAdmin is exempt from the middleware gate, from useModuleGuard and
    # from usePermissionGuard, so this route really does mount and really does
    # start fetching — and the axios interceptor turns the refusal into a hard
    # redirect. Waiting for the URL is therefore also what stops the "screen is
    # absent" assertions below from passing merely because the page had not
    # finished loading.
    goto_module(page, frontend_base_url, STATISTICS_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the screen survives the redirect: not its header, not one of the
    # three stat cards, and not one of the four panels. "Failed to fetch
    # statistics" is asserted absent for the same reason as the categories unit:
    # rendering it would mean a licensing refusal had been handled as an ordinary
    # fetch error rather than as a denial.
    expect(
        page.get_by_role("heading", name=as_pattern(STATISTICS_HEADING))
    ).to_have_count(0)
    expect(page.get_by_text(as_pattern(STATISTICS_SUBHEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(TOTAL_BOOKS_CARD))).to_have_count(0)
    expect(page.get_by_text(as_pattern(BORROWED_BOOKS_CARD))).to_have_count(0)
    expect(page.get_by_text(as_pattern(AVAILABLE_BOOKS_CARD))).to_have_count(0)
    expect(page.get_by_text(as_pattern(ACTIVITY_CHART_LEGEND))).to_have_count(0)
    expect(page.get_by_text(as_pattern(ADDITIONAL_INFO_PANEL))).to_have_count(0)
    expect(page.get_by_text(as_pattern(RECENT_CHECKOUTS_PANEL))).to_have_count(0)
    expect(page.get_by_text(as_pattern(MOST_READ_CATEGORIES_PANEL))).to_have_count(0)
    expect(
        page.get_by_role("columnheader", name=as_pattern(BOOK_TABLE_ISBN_COLUMN))
    ).to_have_count(0)
    expect(page.get_by_text(as_pattern(STATISTICS_LOAD_FAILURE))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


# ════════ view path: the SchoolAdmin reads the library's numbers ═════════════
#
# Constants below are prefixed rather than sharing the negative section's names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# Why this role sees the board at all
#     Both halves of the gate pass, though not through the key the module is
#     named after. ``usePermissionGuard("statistics")`` and
#     ``useModuleGuard("statistics")`` both exempt a SchoolAdmin outright (see the
#     module docstring), so nothing client-side is deciding anything here; and
#     every route in ``api/routes/book_statistics.py`` is gated on
#     ``has_permission("read", "catalogue")``, which this role holds
#     (``db/repository/permissions.py`` seeds it ``("manage", "catalogue")``, and
#     manage stands in for read) and which the ``library_and_community`` pack
#     licenses. So the screen serves in full — and the assertions below say so on
#     both keys, because a pack that licensed one without the other would make
#     this unit's premise silently wrong.
#
# The way in is the route, not the sidebar — and that is not a defect to fix here
#     ``nav-config.tsx`` gives the "Statistics" entry ``permission: "statistics"``
#     and ``SideNavigation.canShowItem`` returns on the permission check before
#     the module gate, but the seeded SchoolAdmin role holds no ``statistics``
#     permission at all — only ``catalogue``, ``categories`` and
#     ``requests_and_renewals``. So the link is drawn for no school, licensed or
#     not, while the page it points at is wide open to the role. Closing that gap
#     means granting a role a permission it was never seeded with, which is a
#     product decision rather than a defect, so this test does not touch it:
#     ``StatisticsPage.open_from_nav`` clicks the entry when it is offered and
#     falls back to the route when it is not. What *is* asserted is that the
#     "Library Module" section itself is on offer, so the walkthrough is standing
#     in the library rather than nowhere.
#
# What a read-only unit can honestly assert
#     Not the numbers. This school is shared with the other library units, which
#     add and retire books and categories around it, and a branch that has lent
#     nothing renders EmptyState in two of the four panels — so "there are three
#     borrowings" is not a claim this suite can make twice in a row. What holds
#     whatever the shelf contains is that every panel *resolved*: three cards each
#     carrying a real figure and a comparison against last year, a chart that
#     stopped loading with both its series named, an "Additional Info" card
#     reporting a count and a share for overdue books and for new arrivals, a
#     "Recent Checkouts" table with its four columns in order, and a categories
#     donut that did not report a failed fetch. Each of those is a distinct GET,
#     so between them they prove all seven answered.
#
#     The two filter changes at the end are the only interaction a view unit has:
#     they are reads, they re-issue two of those GETs against different path
#     params, and they are what shows a viewer the board is live rather than a
#     screenshot.
#
# The branch has to be activated first, and it is not the usual formality
#     ``page.tsx``'s fetch effect *returns early* for a SchoolAdmin whose
#     ``useBranchStore`` is empty, so the header would sit on "Loading
#     statistics…" for ever — and every /book-statistics route answers 400
#     BRANCH_ID_REQUIRED for that role without ``?branch_id`` anyway.
#     ``BranchesPage.select_branch`` fills the store, and is also what makes the
#     sidebar's ``branchOnly`` "Library Module" section appear.

VIEW_SCENARIO = "library_and_community"

# The chart's year picker offers the current year and the five before it
# (BookActivityChart.YEAR_OPTIONS), so last year is always selectable. Whether it
# holds any borrowings is beside the point — an empty year is a legitimate answer
# and renders EmptyState, which expect_activity_chart accepts.
VIEW_PREVIOUS_YEAR = str(date.today().year - 1)

# Any month other than the one already selected, so the picker's value visibly
# changes and BookStats really refetches. December when today is January: the
# endpoint always reads the *current* year, so that month is simply still to
# come and answers with zeros.
VIEW_OTHER_MONTH = calendar.month_name[12 if date.today().month == 1 else date.today().month - 1]


@pytest.mark.school_admin
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="library.statistics.view.school_admin",
    title="Library Statistics",
    subtitle="SchoolAdmin views library statistics",
)
def test_school_admin_views_library_statistics(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin opens the library board and reads every panel on it.

    Read-only throughout: nothing is created, nothing is edited, and the only
    interactions are the two filters, which re-issue the same GETs against a
    different year and a different month. The assertions are about each panel
    having *resolved* rather than about any particular figure — see the section
    comment for why a shared school cannot support the latter.
    """
    ctx = provisioned_school
    assert STATISTICS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {STATISTICS_MODULE!r} for the "
        f"view path — a school without the module has no statistics board to read"
    )
    # The premise the whole screen rests on: the routes name `catalogue`, not
    # `statistics`, so this is the key that has to be licensed for a single number
    # to arrive. A pack holding one without the other is a licensing question for
    # the product owner (see the negative test's own note), not something this
    # test can paper over.
    assert GATE_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} licenses {STATISTICS_MODULE!r} but not "
        f"{GATE_MODULE!r}, which is the module key every /book-statistics route is "
        f"actually gated on (api/routes/book_statistics.py). Every panel below "
        f"would be refused with 403 for a reason that has nothing to do with this "
        f"unit — escalate the pack, do not re-point the gate."
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — phase B creates one for "
        "every scenario, and this page issues no request at all for a branch-less "
        "SchoolAdmin, so the board would never load"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    statistics = StatisticsPage(page, base_url)
    branch_name = str(ctx.branches[0]["name"])

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Point the console at {branch_name}"):
        # Mandatory, not cosmetic: it is what fills the branch store this page's
        # fetch effect waits on, and what unlocks the branchOnly Library menu.
        BranchesPage(page, base_url).select_branch(branch_name)
        statistics.expect_library_section()

    with demo.step("Open the library's statistics board"):
        statistics.open_from_nav()

    with demo.step("The shelf at a glance: books held, borrowed and available"):
        statistics.expect_header_cards()
        statistics.expect_no_load_failure()

    with demo.step("How borrowing tracked against returns this year"):
        statistics.expect_activity_chart()
        expect(statistics.activity_year_picker()).to_have_text(
            re.compile(rf"^\s*{date.today().year}\s*$")
        )

    with demo.step("Overdue books and new arrivals for the month"):
        statistics.expect_additional_info()

    with demo.step("The latest checkouts, and what the school is reading"):
        statistics.expect_recent_checkouts()
        statistics.expect_most_read_categories()

    with demo.step(f"Rewind the borrowing chart to {VIEW_PREVIOUS_YEAR}"):
        statistics.select_activity_year(VIEW_PREVIOUS_YEAR)
        # The panel re-fetched and settled — on a chart or on "No Data Found",
        # both of which are honest answers for a year of this school's life.
        statistics.expect_activity_chart()
        statistics.expect_no_load_failure()

    with demo.step(f"…and look up {VIEW_OTHER_MONTH}'s overdue list"):
        statistics.select_month(VIEW_OTHER_MONTH)
        statistics.expect_additional_info()
        # The header cards belong to a different fetch and must be untouched by a
        # panel-level filter — a shared-state regression would blank them here.
        statistics.expect_header_cards()
