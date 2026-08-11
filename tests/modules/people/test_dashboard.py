"""/module/dashboard — the Admin Dashboard a SchoolAdmin lands on.

Mandatory path: the SchoolAdmin of the ``minimal`` school
    ``test_dashboard_is_reachable_on_the_minimal_pack`` — the ledger unit
    ``people.dashboard.always_licensed``. There is no denial unit for this module
    and there cannot be one: ``dashboard`` sits in the ``people`` group of
    ``services/feature_pack_service.SYSTEM_MODULE_GROUPS``, and the SuperAdmin's
    only pack builder (``src/app/module/feature_flag/create/page.tsx`` and its
    ``edit/[id]`` twin) declares ``BASIC_GROUPS = ["people", "governance"]`` and
    renders every module of those two groups locked, pre-selected and exempt from
    "Clear All" — only ``guardians`` and ``families`` are optional inside them,
    and ``handleSave`` refuses a pack missing any of the rest outright. That the
    people and governance groups are core and always on is **intended product
    behaviour, confirmed 2026-08-09**, not a licensing hole. So this unit asserts
    the opposite of a denial — the module is licensed, offered and working on the
    most restricted pack the product can build — and deliberately adds no gate.

    The frontend says the same thing twice, independently of any pack
        ``hooks/useModuleGuard.ts`` short-circuits ``moduleName === "dashboard"``
        to ``true`` for every role, ``usePermissionGuard``'s ``CORE_MODULES`` list
        contains ``"dashboard"``, and ``utils/postAuthRedirect.CORE_MODULES`` —
        which ``src/middleware.ts`` reads — contains it too. Three separate
        carve-outs is a design statement, not an oversight to "fix".

Why a branch has to be picked first, unlike the governance screens
    Two things need it, and both are ``branchOnly``/branch-scoped by design.

    The sidebar entry: "Admin Dashboard" lives in the "People Module" section of
    ``nav-config.tsx``, which is ``branchOnly: true`` — for a SchoolAdmin the
    whole section is hidden until ``useBranchStore`` holds a branch, and only the
    branch row's "View" button on /module/school_admin_dashboard fills it
    (``BranchesPage.select_branch``).

    The data: ``page.tsx`` returns early from both of its fetch effects while
    ``currentSchoolAdminBranch?.branch_id`` is empty, and the routes themselves
    answer 400 ``BRANCH_ID_REQUIRED`` to a SuperAdmin or SchoolAdmin whose request
    carries no ``branch_id`` (``api/routes/statistics.py``). A SchoolAdmin belongs
    to no branch of their own, so selecting one is a prerequisite here, not
    scene-setting.

Why the mount fetches are read off the wire rather than out of the DOM
    The three stat cards render 0 whether the call answered or was refused —
    ``fetchDashboardStatistics`` swallows its error into a ``console.error`` and
    leaves the zeroed initial state on screen. So "the cards are there" cannot
    distinguish a working dashboard from a 403'd one. The test therefore waits
    for the browser's own ``/statistics/dashboard/stats`` and
    ``/statistics/dashboard/recent-transactions`` responses to come back 200, and
    then re-reads both routes directly.

Deliberately not asserted: the bar chart's heading, or any chart data
    ``components/BarChart.tsx`` renders its "Revenue & Expenses Analytics"
    heading only in the success branch, and — unlike ``page.tsx`` — it does not
    guard its fetch on the branch store at all: it interpolates
    ``branch_id=${currentSchoolAdminBranch?.branch_id}`` unconditionally, so the
    mount call made before the persisted store rehydrates sends
    ``branch_id=undefined`` and lands in the error branch until the effect refires
    on the store. ``components/PieChart.tsx`` has the mirror-image problem: its
    effect depends on ``[year]`` alone, so it never refires. Both are pre-existing
    frontend races, neither is what this unit is about, and neither is a defect
    this pass is entitled to "fix" — the assertions stay on the panels that render
    unconditionally (the greeting, the three stat cards, the transactions table,
    the Members Overview card) plus the wire.

Why a control on a module the pack really does omit
    Every frontend gate on this screen carries a SchoolAdmin carve-out on top of
    the dashboard-specific ones above, so "the page loaded" is on its own
    compatible with a licence system that does nothing at all. The test pins that
    down with ``fees``: outside the locked basic set, omitted by this pack, held
    as a permission by the seeded SchoolAdmin role, and refused 403 "Feature not
    available in your plan" by ``utils.permissions.has_permission``. The gate
    bites; it just does not bite here, by design.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import unquote

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import BasePage, as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

# config/module_catalog.py — the feature-pack key and the /module/<route> segment
# happen to be the same string for this module.
DASHBOARD_MODULE = "dashboard"
DASHBOARD_ROUTE = "dashboard"

# The floor case: the most restricted pack the product can actually build.
MANDATORY_SCENARIO = "minimal"

# ── what makes the module mandatory ──────────────────────────────────────────
# src/app/module/feature_flag/create/page.tsx — the SuperAdmin's only surface for
# building a pack. Every module of a "basic" group is rendered locked and forced
# into the pack; only these two are exempt.
BASIC_GROUPS = ("people", "governance")
OPTIONAL_BASIC_MODULES = frozenset({"guardians", "families"})
PEOPLE_GROUP = "people"

# ── the sidebar (components/common/SideNavigation/nav-config.tsx) ────────────
# The section is `branchOnly: true` for a SchoolAdmin, and the entry is gated on
# the "dashboard" *permission* rather than on a module. Its label is a suffix of
# the "School Admin Dashboard" entry sitting directly above it, so it is anchored.
NAV_SECTION_PEOPLE = re.compile(r"^\s*People Module\s*$", re.I)
NAV_ADMIN_DASHBOARD = re.compile(r"^\s*Admin Dashboard\s*$", re.I)

# ── what the screen renders (src/app/module/dashboard) ───────────────────────
# page.tsx's <header>: the greeting depends on the hour, so all three are allowed.
GREETING = re.compile(r"Good (morning|afternoon|evening)", re.I)
# ModuleHeader's <dt> labels, from page.tsx::getStats(). Escaped — "(GHC)".
STAT_FEES_COLLECTED = re.compile(re.escape("Fees Collected (GHC)"), re.I)
STAT_REVENUE_GENERATED = re.compile(re.escape("Revenue Generated (GHC)"), re.I)
STAT_MONTHLY_EXPENSES = re.compile(r"^\s*Monthly Expenses\s*$", re.I)
# components/Table.tsx::getHeaderText for the default transactionType, "fees".
# Hard-coded in the component, academic year and all. Routed through as_pattern
# because of the slash.
TABLE_HEADER_FEES = as_pattern(r"Recent Fees for 2023/2024 Academic Year")
# The transaction-type Select beside it (components/Table.tsx), whose three items
# are the only readable text a Radix trigger on this screen can be filtered by.
TABLE_TYPE_TRIGGER = as_pattern(r"Fees|Revenue|Expenses")
# components/PieChart.tsx's card title — rendered outside renderContent(), so it
# is on screen whatever that fetch did.
PIE_CHART_HEADING = re.compile(r"^\s*Members Overview\s*$", re.I)

# ── the module's own API surface (api/routes/statistics.py) ──────────────────
# Both are declared Depends(has_permission("read", "dashboard")), so a school
# that lost the module would be refused here before the handler ran.
STATS_PATH = "/statistics/dashboard/stats"
TRANSACTIONS_PATH = "/statistics/dashboard/recent-transactions"
# api/api_models — DashboardStats' three keys, which page.tsx destructures.
STATS_KEYS = ("fees_collected", "revenue_generated", "monthly_expenses")

# A module the same pack omits, *outside* the locked basic set, that the backend
# really does gate — the control proving the licence is enforced rather than
# decorative. The SchoolAdmin role holds ("manage", "fees") in
# newschoolapp/db/repository/permissions.py, so a refusal can only come from the
# pack. Any fee id will do: has_permission runs as a route dependency, before the
# handler ever looks the row up.
ENFORCED_UNLICENSED_MODULE = "fees"
ENFORCED_UNLICENSED_PATH = "/fees/1"
# newschoolapp/utils/permissions.py, the feature-pack branch of has_permission.
FEATURE_PACK_403 = re.compile(r"feature not available in your plan", re.I)

# The cookie every frontend gate derives its answer from, written by
# src/app/auth/login/page.tsx and refreshed by SideNavigation.
MODULES_COOKIE = "schoolModules"

# Where the frontend sends a user it has decided is not allowed in
# (src/app/auth/no-access/page.tsx and /unauthorized).
DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")

SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The dashboard's mount fetches wait on the branch store rehydrating out of
# (encrypted) localStorage before they fire at all, so they are given room.
MOUNT_FETCH_TIMEOUT_MS = 60_000


@pytest.mark.school_admin
@pytest.mark.scenario(MANDATORY_SCENARIO)
def test_dashboard_is_reachable_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """The floor case still has its dashboard: licensed, offered and answering.

    Ledger unit ``people.dashboard.always_licensed``. See the module docstring:
    ``dashboard`` is in the ``people`` group, the pack builder locks that whole
    group into every pack, and the people/governance groups being core is
    **intended product behaviour, confirmed 2026-08-09**. So this asserts the
    opposite of a denial — and adds no gate of any kind.

    Read-only throughout. The dashboard is a read-only screen (three GETs behind
    it and no write control anywhere in page.tsx), and the point here is
    reachability, so nothing is seeded: zeroed stat cards and an empty
    transactions table are a perfectly good pass as long as the calls behind them
    answered 200 rather than being refused.
    """
    ctx = provisioned_school
    requested = set(ctx.feature_modules)

    assert ctx.branches, (
        f"provisioning left {ctx.school_name!r} with no branch, and both this "
        f"screen's fetches answer 400 BRANCH_ID_REQUIRED to a SchoolAdmin whose "
        f"request carries none — phase B creates one for every scenario"
    )
    branch = ctx.branches[0]
    branch_name = str(branch.get("name") or "")
    branch_id = int(branch.get("id") or -1)
    assert branch_name and branch_id > 0, (
        f"provisioning could not capture this school's branch ({branch!r}). The "
        f"dashboard is read per branch, so re-run provisioning rather than "
        f"guessing the id."
    )

    # ── 1. Licensed, and licensed because it cannot be dropped ────────────────
    super_token = api.login(
        ctx.super_admin.email, ctx.super_admin.password
    )["access_token"]
    catalogue = api.get("/feature-packs/system-modules", token=super_token)
    assert catalogue.status_code == 200, (
        "the SuperAdmin must be able to read the system module catalogue — got "
        f"{catalogue.status_code}: {catalogue.text[:300]}"
    )
    groups = {
        str(g.get("group")): [str(m) for m in (g.get("modules") or [])]
        for g in (catalogue.json().get("groups") or [])
    }
    assert DASHBOARD_MODULE in groups.get(PEOPLE_GROUP, []), (
        f"{DASHBOARD_MODULE!r} is no longer in the {PEOPLE_GROUP!r} group of the "
        f"backend catalogue (services/feature_pack_service.py). The create-pack "
        f"form locks a module in because of the group it belongs to, so that "
        f"membership is the whole reason this module is mandatory. "
        f"Groups: { {k: sorted(v) for k, v in groups.items()} }"
    )
    locked = {
        module
        for name in BASIC_GROUPS
        for module in groups.get(name, [])
        if module not in OPTIONAL_BASIC_MODULES
    }
    assert DASHBOARD_MODULE in locked, (
        f"{DASHBOARD_MODULE!r} is no longer one of the modules the SuperAdmin's "
        f"create-pack form forces into every pack, so the admin dashboard can now "
        f"be sold away from a school and this unit's premise is gone. That is a "
        f"product change, not a test failure to paper over — re-read "
        f"config/feature_scenarios.yaml's `minimal` note and rewrite this unit as "
        f"a real denial test. Locked: {sorted(locked)}"
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — the "
        f"sidebar calls this on every mount — got {features.status_code}: "
        f"{features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so this is not "
        f"the {MANDATORY_SCENARIO!r} floor and nothing below is about licensing. "
        f"Provisioning phase A assigns one — check that it did."
    )
    licensed = {str(m) for m in (body.get("modules") or [])}
    assert licensed == requested | locked, (
        f"{ctx.school_name!r}'s licence is not 'what the {MANDATORY_SCENARIO!r} "
        f"pack requested plus the locked basic modules'. Requested "
        f"{sorted(requested)}; locked {sorted(locked)}; got {sorted(licensed)}. "
        f"Unexpectedly granted: {sorted(licensed - (requested | locked))}; "
        f"expected but missing: {sorted((requested | locked) - licensed)}."
    )
    assert DASHBOARD_MODULE in licensed, (
        f"{ctx.school_name!r} — the most restricted pack this product can build — "
        f"is not licensed for {DASHBOARD_MODULE!r}. The people group is core and "
        f"always on by design, so an Admin has just lost the landing screen that "
        f"reports what the school collected, earned and spent. "
        f"Licensed: {sorted(licensed)}"
    )

    # ── 2. The licence is enforced for this user, on a module outside the lock ─
    #
    # Without this, everything below is equally consistent with a feature-pack
    # system that never refuses anybody — and this screen carves the SchoolAdmin
    # out three separate ways before a pack is even consulted (module docstring).
    assert ENFORCED_UNLICENSED_MODULE not in licensed, (
        f"{ctx.school_name!r} is now licensed for {ENFORCED_UNLICENSED_MODULE!r}, "
        f"so it can no longer serve as the control that the feature gate bites "
        f"for this user. Pick another module the {MANDATORY_SCENARIO!r} pack "
        f"omits, that is outside the locked basic set, and that a backend route "
        f"gates on."
    )
    assert ENFORCED_UNLICENSED_MODULE in _role_modules(api, SCHOOL_ADMIN_ROLE), (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds an "
        f"{ENFORCED_UNLICENSED_MODULE!r} permission, so the 403 below would come "
        f"from the permission half of has_permission and prove nothing about "
        f"feature packs. Fix newschoolapp/db/repository/permissions.py or "
        f"re-point this control."
    )
    gated = api.get(ENFORCED_UNLICENSED_PATH, token=token)
    assert gated.status_code == 403, (
        f"{ENFORCED_UNLICENSED_PATH} answered {gated.status_code} for a "
        f"SchoolAdmin whose school is not licensed for "
        f"{ENFORCED_UNLICENSED_MODULE!r}; the feature-pack gate in "
        f"utils/permissions.has_permission should have refused it, and until it "
        f"does, 'the dashboard is reachable' says nothing. Body: {gated.text[:300]}"
    )
    assert FEATURE_PACK_403.search(gated.text), (
        f"{ENFORCED_UNLICENSED_PATH} was refused, but not by the feature pack — "
        f"the detail should be 'Feature not available in your plan'. "
        f"Body: {gated.text[:300]}"
    )

    # ── 3. Offered: the sidebar entry a SchoolAdmin is given ──────────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    cookie_modules = _school_modules_cookie(page)
    assert cookie_modules is not None, (
        f"the {MODULES_COOKIE!r} cookie was never written for this session. Every "
        f"frontend gate derives its answer from it, so without it the walk below "
        f"says nothing about what this school is licensed for. Both "
        f"src/app/auth/login/page.tsx and SideNavigation are meant to set it."
    )
    assert set(cookie_modules) == licensed, (
        f"the browser session claims {sorted(cookie_modules)} as its licensed "
        f"modules, out of step with /school_profile/{ctx.school_id}/features, "
        f"which reports {sorted(licensed)}"
    )
    assert DASHBOARD_MODULE in cookie_modules, (
        f"{DASHBOARD_MODULE!r} is missing from this session's {MODULES_COOKIE!r} "
        f"cookie. It is listed in utils/postAuthRedirect.CORE_MODULES, so "
        f"src/middleware.ts would let the route through anyway — but the sidebar "
        f"and the school's own licence would disagree about a module the pack "
        f"builder cannot drop"
    )

    # A SchoolAdmin belongs to no branch, and both the "People Module" nav section
    # (branchOnly) and page.tsx's fetch effects wait on the branch store that only
    # this click fills. Its handler navigates away as a side effect — to
    # /module/community, or on to /auth/no-access when (as here) the pack has no
    # community module — so the dashboard is reached by route afterwards, never by
    # coming back through the branches list, whose mount effect clears the store.
    BranchesPage(page, frontend_base_url).select_branch(branch_name)

    # ── 4. Working: the route loads and its own mount fetches answer ──────────
    # Asking for the route by hand is the request middleware.ts actually sees.
    # The two responses are awaited around the navigation because the stat cards
    # render zeros either way — see the module docstring.
    with page.expect_response(
        _ok_response(STATS_PATH), timeout=MOUNT_FETCH_TIMEOUT_MS
    ) as stats_call, page.expect_response(
        _ok_response(TRANSACTIONS_PATH), timeout=MOUNT_FETCH_TIMEOUT_MS
    ) as transactions_call:
        goto_module(page, frontend_base_url, DASHBOARD_ROUTE)

    assert not DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} was redirected to {page.url!r} "
        f"asking for a module their pack licenses. The people group is core and "
        f"always on by design — a denial here is a regression, not a gate to keep."
    )
    assert page.url.rstrip("/").endswith(f"/module/{DASHBOARD_ROUTE}"), (
        f"expected to still be on /module/{DASHBOARD_ROUTE}, but the app moved to "
        f"{page.url!r}"
    )

    # The screen itself, not a shell behind a guard. `hasModuleAccess === false`
    # and `!hasPermission` both return null from page.tsx, so any of these being
    # on screen means neither guard fired.
    expect(page.get_by_role("heading", name=GREETING).first).to_be_visible(
        timeout=30_000
    )
    for label in (STAT_FEES_COLLECTED, STAT_REVENUE_GENERATED, STAT_MONTHLY_EXPENSES):
        expect(page.get_by_text(label).first).to_be_visible(timeout=20_000)
    expect(page.get_by_text(TABLE_HEADER_FEES).first).to_be_visible(timeout=20_000)
    expect(page.get_by_text(PIE_CHART_HEADING).first).to_be_visible(timeout=20_000)
    # The transactions table's own control, proving the panel mounted rather than
    # its header text merely existing somewhere.
    type_picker = page.get_by_role("combobox").filter(has_text=TABLE_TYPE_TRIGGER).first
    expect(type_picker).to_be_visible(timeout=20_000)

    # What the browser actually got back on mount.
    _expect_dashboard_stats(stats_call.value.json())
    transactions = transactions_call.value.json()
    assert isinstance(transactions, list), (
        f"GET {TRANSACTIONS_PATH} answered the browser with "
        f"{type(transactions).__name__}, but components/Table.tsx maps over it — "
        f"api/routes/statistics.py declares List[RecentTransactionItem]"
    )

    # ── 5. And the module's API surface answers this admin directly ───────────
    stats = api.get(f"{STATS_PATH}?branch_id={branch_id}", token=token)
    assert stats.status_code == 200, (
        f"GET {STATS_PATH} answered {stats.status_code} for the SchoolAdmin of "
        f"{ctx.school_name!r}, whose pack licenses {DASHBOARD_MODULE!r}. The route "
        f"is Depends(has_permission('read', {DASHBOARD_MODULE!r})), so a 403 "
        f"carrying 'Feature not available in your plan' would mean the people "
        f"group stopped being locked into every pack; anything else is the route "
        f"itself breaking. Body: {stats.text[:300]}"
    )
    assert not FEATURE_PACK_403.search(stats.text), (
        f"GET {STATS_PATH} returned 200 but its body reads like the feature-pack "
        f"refusal: {stats.text[:300]}"
    )
    _expect_dashboard_stats(stats.json())

    recent = api.get(
        f"{TRANSACTIONS_PATH}?transaction_type=fees&limit=5&branch_id={branch_id}",
        token=token,
    )
    assert recent.status_code == 200, (
        f"GET {TRANSACTIONS_PATH} answered {recent.status_code} for the "
        f"SchoolAdmin of {ctx.school_name!r} — the dashboard's transactions panel "
        f"is gated on the same ('read', {DASHBOARD_MODULE!r}) permission as its "
        f"stat cards. Body: {recent.text[:300]}"
    )
    assert isinstance(recent.json(), list), (
        f"GET {TRANSACTIONS_PATH} did not answer the list shape "
        f"components/Table.tsx maps over — got {recent.text[:300]}"
    )
    # Deliberately no assertion about rows or amounts. This school has booked no
    # fees, revenue or expenses — the `minimal` pack licenses neither `fees` nor
    # `incomes_and_expenses` — so an empty list is the expected answer, and
    # reachability is what this unit is about.

    # ── 6. Offered in the sidebar, now that a branch is selected ──────────────
    # Asserted last because the "People Module" section is branchOnly and the
    # /auth/no-access page select_branch can land on renders no sidebar at all.
    expect(page.get_by_text(NAV_SECTION_PEOPLE).first).to_be_visible(timeout=20_000)
    nav = page.get_by_role("navigation")
    expect(
        nav.get_by_role("link", name=as_pattern(NAV_ADMIN_DASHBOARD)).first
    ).to_be_visible(timeout=20_000)
    expect(nav.locator(f'a[href="/module/{DASHBOARD_ROUTE}"]').first).to_be_visible()


# ───────────────────────────── helpers ───────────────────────────────────────


def _ok_response(path: str):
    """Predicate for ``page.expect_response``: this route, answered 200.

    Status is part of the predicate rather than asserted afterwards on purpose.
    Both effects in ``page.tsx`` fire again whenever the branch store changes, so
    a first attempt made before the persisted store rehydrates can legitimately be
    refused a 400 and then succeed — waiting for the 200 tolerates that, while a
    route that is genuinely gated never produces one and the wait times out.
    """
    return lambda response: path in response.url and response.status == 200


def _expect_dashboard_stats(payload: Any) -> None:
    """``DashboardStats`` as page.tsx destructures it: three ``{amount,
    percentage_change}`` blocks. No assertion on the numbers — this school has
    booked nothing, so zeros are correct."""
    assert isinstance(payload, dict), (
        f"GET {STATS_PATH} answered {type(payload).__name__}, not the "
        f"DashboardStats object page.tsx reads: {payload!r}"
    )
    for key in STATS_KEYS:
        block = payload.get(key)
        assert isinstance(block, dict) and "amount" in block, (
            f"GET {STATS_PATH} is missing the {key!r} block the dashboard's stat "
            f"cards render (api/api_models — DashboardStats) — got keys "
            f"{sorted(payload)}"
        )


def _role_modules(api: BackendAPI, role_name: str) -> set[str]:
    """Every module the named seeded role holds a permission on."""
    role = api.get(f"/roles/{api.role_id_for(role_name)}")
    assert role.status_code == 200, (
        f"could not read the {role_name} role — got {role.status_code}: "
        f"{role.text[:300]}"
    )
    return {str(p.get("module")) for p in role.json().get("permissions", [])}


def _school_modules_cookie(page: Page) -> list[str] | None:
    """The ``schoolModules`` cookie as a list, or ``None`` if it is not readable.

    The frontend stores it URL-encoded JSON; ``None`` covers both "never set" and
    "set to something that is not a JSON array", which are the same failure from
    middleware.ts's point of view — it falls back to ``[]`` and skips the gate.
    """
    for cookie in page.context.cookies():
        if cookie.get("name") != MODULES_COOKIE:
            continue
        try:
            parsed = json.loads(unquote(str(cookie.get("value") or "")))
        except json.JSONDecodeError:
            return None
        return [str(m) for m in parsed] if isinstance(parsed, list) else None
    return None


# ────────── view path: the teacher the admin dashboard is not for ─────────────
#
# Ledger unit: ``people.dashboard.view.teacher`` (scenario ``minimal``, role
# ``teacher``, intent ``view``). **RECORDED BLOCKED** — see state/blockers.md.
# This test is the guard that stands in its place, and it is deliberately not a
# read-only happy path, because there is no dashboard for this role to read.
#
# The product question it is blocked on
#     Should a Teacher have an admin dashboard at all — and if so, is it this
#     screen, or is /module/home already their landing page? Answering "yes, this
#     one" means adding ``("read", "dashboard")`` to the seeded Teacher role and
#     widening the sidebar entry's ``roleGate``. That is *granting a role a
#     permission it does not have*, which this pass may not do unattended, so
#     nothing was changed in either app.
#
# Why the happy path cannot be written — three independent layers, all agreeing
#     * **The role does not hold the permission.** ``newschoolapp/db/repository/
#       permissions.py`` seeds Teacher with eighteen modules and ``dashboard`` is
#       not among them; ``Admin``, ``SchoolAdmin`` and (since an earlier fix)
#       ``Accountant`` each carry ``("read", "dashboard")`` explicitly. Read back
#       from ``GET /roles/{id}`` in step 5 below rather than assumed.
#     * **The sidebar never offers it.** The "Admin Dashboard" entry in
#       ``nav-config.tsx`` carries ``roleGate: ["Admin", "SchoolAdmin"]``, and
#       ``SideNavigation.canShowItem`` applies role gates before anything else. A
#       teacher's "People Module" section renders — they hold ``students`` and
#       ``home`` — with those two entries and no dashboard.
#     * **The API refuses.** All three ``/statistics/dashboard/*`` routes are
#       ``Depends(has_permission("read", "dashboard"))``, whose permission branch
#       answers 403 "You do not have permission to perform this action" long
#       before the handler runs.
#
#     And the screen itself is a finance report — "Fees Collected (GHC)",
#     "Revenue Generated (GHC)", "Monthly Expenses", recent fee transactions —
#     whose header falls back to the literal word "Administrator" when it cannot
#     name the user. Its absence for a teacher reads as deliberate, not as an
#     oversight, which is exactly why it is escalated rather than patched.
#
# What is asserted instead
#     The denial in the precise shape the app produces it, so that the day any of
#     the three layers moves, this fails loudly and the real view path can be
#     written:
#
#     1. The school IS licensed for ``dashboard`` — it is in the locked ``people``
#        group (see the module docstring), so on the ``minimal`` floor pack the
#        licence half of every gate says *yes*. Without this the refusal below
#        would just be an ordinary unlicensed module.
#     2. The sidebar renders for this teacher, with the entries they do hold, and
#        offers no way to ``/module/dashboard``.
#     3. Asking for the route by hand lands on **/unauthorized**, not
#        ``/auth/no-access``. Those are different verdicts from different code —
#        ``usePermissionGuard`` sends a user with no *permission* to the former,
#        ``useModuleGuard``/``middleware.ts`` send an *unlicensed* school to the
#        latter — and which one appears is the whole result of this unit.
#     4. None of the dashboard's own panels render behind that redirect.
#     5. The refusal really is about the role: the seeded Teacher role holds no
#        ``dashboard`` permission, and all three statistics routes answer this
#        teacher 403 with the *permission* detail rather than the feature-pack one.
#     6. Control — the same routes are NOT refused to this school's SchoolAdmin,
#        so step 5 is a role boundary and not a broken endpoint.
#
# Reading this test when it fails
#     A visible "Admin Dashboard" entry, a /module/dashboard that renders, or a
#     200 from /statistics/dashboard/stats for a teacher all mean the same thing:
#     the product answered the blocked question with "yes". Unblock the unit and
#     rewrite this as the ordinary read the ledger asked for. A redirect to
#     /auth/no-access instead of /unauthorized means something quite different —
#     the school lost its ``dashboard`` licence, which
#     ``test_dashboard_is_reachable_on_the_minimal_pack`` above covers.

TEACHER_VIEW_SCENARIO = "minimal"
TEACHER_ROLE = "Teacher"

# nav-config.tsx — the two "People Module" entries a Teacher's permissions do
# earn them (``home`` and ``students``). Asserted visible so that "no Admin
# Dashboard entry" cannot pass on a sidebar that simply never rendered.
NAV_HOME = re.compile(r"^\s*Home\s*$", re.I)
NAV_STUDENTS = re.compile(r"^\s*Students\s*$", re.I)

# src/app/unauthorized/page.tsx — where usePermissionGuard sends a signed-in user
# whose role lacks the module permission.
UNAUTHORIZED_URL = re.compile(r"/unauthorized")
UNAUTHORIZED_HEADING = re.compile(r"^\s*Access Denied\s*$", re.I)
UNAUTHORIZED_MESSAGE = re.compile(
    r"do not have the necessary permissions to view this page", re.I
)
# src/app/auth/no-access — the *other* denial, for an unlicensed school. Reaching
# it here would mean the module left the locked `people` group.
NO_ACCESS_URL = re.compile(r"/auth/no-access")

# The third dashboard route, which page.tsx reaches through components/BarChart.
# Gated identically to the two the mandatory test above already names.
ANALYTICS_PATH = "/statistics/dashboard/monthly-analytics"

# newschoolapp/core/exceptions.INADEQUATE_PERMISSIONS — the *permission* branch of
# utils.permissions.has_permission, as opposed to FEATURE_PACK_403 above.
ROLE_PERMISSION_403 = re.compile(
    r"do not have permission to perform this action", re.I
)


@pytest.mark.teacher
@pytest.mark.scenario(TEACHER_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="people.dashboard.view.teacher",
    title="Dashboard",
    # Deliberately not the ledger's "Teacher views dashboard": there is no
    # teacher view of this screen, and captioning the footage that way would
    # promise a viewer something that never appears. Same call as
    # tests/modules/academics/test_exams.py::test_teacher_views_exams.
    subtitle="The admin dashboard is not a teacher's screen",
)
def test_teacher_is_not_given_the_admin_dashboard(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A teacher's school has the dashboard; the teacher does not.

    The unit ``people.dashboard.view.teacher`` is recorded blocked on the product
    question in the section comment above. What this walk proves is that the
    refusal is a *role* boundary and nothing else: the licence is granted, the
    same routes answer the school's own administrator, and every layer that turns
    the teacher away does so on the missing ``("read", "dashboard")`` permission.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, (
        f"provisioning created no teacher for {ctx.school_name!r}. The "
        f"{TEACHER_VIEW_SCENARIO!r} pack licenses `staff`, so phase C should have "
        f"created one; without a teacher there is no role boundary to observe."
    )
    teacher = ctx.teacher

    page: Page = demo.page
    base_url: str = demo.frontend_base_url

    with demo.step(
        f"Sign in as {teacher.full_name}, who teaches at {ctx.school_name}",
        dwell_ms=2500,
    ):
        login_as(page, base_url, teacher)

    with demo.step("Their school's plan does include the admin dashboard", dwell_ms=2500):
        # This is what makes everything below a role boundary rather than an
        # ordinary unlicensed module: `dashboard` is in the locked `people` group,
        # so even the floor pack carries it (see the module docstring).
        teacher_token = api.login(teacher.email, teacher.password)["access_token"]
        features = api.get(f"/school_profile/{ctx.school_id}/features", token=teacher_token)
        assert features.status_code == 200, (
            f"a teacher must be able to read their own school's features — the "
            f"sidebar calls this on every mount — got {features.status_code}: "
            f"{features.text[:300]}"
        )
        body = features.json()
        assert body.get("pack_assigned") is True, (
            f"{ctx.school_name!r} has no feature pack assigned at all, so nothing "
            f"below distinguishes 'not permitted' from 'not licensed'. "
            f"Provisioning phase A assigns one — check that it did."
        )
        licensed = {str(m) for m in (body.get("modules") or [])}
        assert DASHBOARD_MODULE in licensed, (
            f"{ctx.school_name!r} is not licensed for {DASHBOARD_MODULE!r}, so the "
            f"teacher below would be refused by the feature pack rather than by "
            f"their role, and this unit would stop describing the gap it was "
            f"written for. The module is supposed to be un-droppable — see "
            f"test_dashboard_is_reachable_on_the_minimal_pack above. "
            f"Licensed: {sorted(licensed)}"
        )

        cookie_modules = _school_modules_cookie(page)
        assert cookie_modules is not None, (
            f"the {MODULES_COOKIE!r} cookie was never written for this session, so "
            f"src/middleware.ts skipped its module gate entirely and the route "
            f"below was never licence-checked at all. Both "
            f"src/app/auth/login/page.tsx and SideNavigation are meant to set it."
        )
        assert DASHBOARD_MODULE in cookie_modules, (
            f"the browser session carries {sorted(cookie_modules)} as its licensed "
            f"modules, without {DASHBOARD_MODULE!r} — out of step with "
            f"/school_profile/{ctx.school_id}/features. Every frontend gate reads "
            f"the cookie, so the two must agree for the denial below to mean what "
            f"it says."
        )

    with demo.step("The People menu gives them Home and Students…", dwell_ms=2500):
        expect(page.get_by_text(NAV_SECTION_PEOPLE).first).to_be_visible(timeout=25_000)
        expect(page.get_by_role("link", name=NAV_HOME).first).to_be_visible(
            timeout=20_000
        )
        expect(page.get_by_role("link", name=NAV_STUDENTS).first).to_be_visible()

    with demo.step("…but there is no Admin Dashboard among them", dwell_ms=2500):
        expect(page.locator(f'a[href="/module/{DASHBOARD_ROUTE}"]')).to_have_count(0)
        expect(
            page.get_by_role("link", name=as_pattern(NAV_ADMIN_DASHBOARD))
        ).to_have_count(0)

    with demo.step("Ask for the admin dashboard by name instead", dwell_ms=2000):
        goto_module(page, base_url, DASHBOARD_ROUTE)

    with demo.step("The app turns them away: Access Denied", dwell_ms=3000):
        landed = _wait_for_denial_url(page)
        assert landed is not None, (
            f"a teacher of {ctx.school_name!r} was left on {page.url!r} instead of "
            f"being redirected. If the dashboard rendered for them, that is the "
            f"*good* failure: the product answered the question "
            f"people.dashboard.view.teacher is blocked on (state/blockers.md) with "
            f"'yes, teachers get a dashboard' — unblock the unit and rewrite this "
            f"as the ordinary read the ledger asked for."
        )
        assert not NO_ACCESS_URL.search(landed), (
            f"the teacher was sent to {landed!r} — the *unlicensed* denial "
            f"(useModuleGuard / middleware.ts), not the *unpermitted* one. But "
            f"{ctx.school_name!r} reports {DASHBOARD_MODULE!r} among its licensed "
            f"modules, so either the licence and the cookie have drifted apart or "
            f"useModuleGuard stopped short-circuiting `moduleName === 'dashboard'`."
        )
        assert UNAUTHORIZED_URL.search(landed), (
            f"expected usePermissionGuard to send this teacher to /unauthorized; "
            f"the app went to {landed!r} instead"
        )
        expect(page.get_by_role("heading", name=UNAUTHORIZED_HEADING).first).to_be_visible(
            timeout=20_000
        )
        expect(page.get_by_text(UNAUTHORIZED_MESSAGE).first).to_be_visible()

        # …and none of the dashboard actually rendered on the way past. page.tsx
        # returns null from `!hasPermission`, so any of these on screen would mean
        # the guard let the finance report through before redirecting.
        for label in (STAT_FEES_COLLECTED, STAT_REVENUE_GENERATED, STAT_MONTHLY_EXPENSES):
            expect(page.get_by_text(label)).to_have_count(0)
        expect(page.get_by_text(PIE_CHART_HEADING)).to_have_count(0)

    with demo.step(
        "The Teacher role simply holds no key to the school's money screen",
        dwell_ms=3000,
    ):
        role_modules = _role_modules(api, TEACHER_ROLE)
        assert DASHBOARD_MODULE not in role_modules, (
            f"the seeded {TEACHER_ROLE} role now holds a {DASHBOARD_MODULE!r} "
            f"permission (newschoolapp/db/repository/permissions.py). That is the "
            f"*good* failure — the blocked product question has been answered — so "
            f"unblock people.dashboard.view.teacher and write the read path. "
            f"Teacher modules: {sorted(role_modules)}"
        )
        for path in (
            f"{STATS_PATH}",
            f"{TRANSACTIONS_PATH}?transaction_type=fees&limit=5",
            f"{ANALYTICS_PATH}?year={date.today().year}",
        ):
            refused = api.get(path, token=teacher_token)
            assert refused.status_code == 403, (
                f"GET {path} answered {refused.status_code} for a teacher of "
                f"{ctx.school_name!r}. Every /statistics/dashboard/* route is "
                f"Depends(has_permission('read', {DASHBOARD_MODULE!r})) and the "
                f"{TEACHER_ROLE} role does not hold it, so 403 is the only answer "
                f"that matches the app as built. Body: {refused.text[:300]}"
            )
            assert ROLE_PERMISSION_403.search(refused.text), (
                f"GET {path} refused the teacher, but not on their role — the "
                f"detail should be core/exceptions.INADEQUATE_PERMISSIONS. A "
                f"'Feature not available in your plan' body would mean the school "
                f"lost the {DASHBOARD_MODULE!r} licence and this unit is measuring "
                f"the wrong denial. Body: {refused.text[:300]}"
            )
            assert not FEATURE_PACK_403.search(refused.text), (
                f"GET {path} was refused by the feature pack rather than by the "
                f"teacher's role: {refused.text[:300]}"
            )

    with demo.step(
        "Their administrator opens the very same screen without trouble",
        dwell_ms=3000,
    ):
        # The control. Without it, the six assertions above are equally consistent
        # with three statistics routes that are simply broken for everybody.
        admin_token = api.login(
            ctx.school_admin.email, ctx.school_admin.password
        )["access_token"]
        branch_id = int((ctx.branches[0] or {}).get("id") or -1) if ctx.branches else -1
        # A SchoolAdmin belongs to no branch, so these routes want one named
        # (api/routes/statistics.py → 400 BRANCH_ID_REQUIRED without it). A 400 is
        # still past the permission dependency, which is all this control needs.
        query = f"?branch_id={branch_id}" if branch_id > 0 else ""
        allowed = api.get(f"{STATS_PATH}{query}", token=admin_token)
        assert allowed.status_code != 403, (
            f"GET {STATS_PATH} answered 403 to the SchoolAdmin of "
            f"{ctx.school_name!r} too, whose role does hold "
            f"('read', {DASHBOARD_MODULE!r}) and whose pack licenses the module. "
            f"The teacher's refusal above is then not a role boundary at all — the "
            f"route is refusing everybody. Body: {allowed.text[:300]}"
        )


def _wait_for_denial_url(page: Page, timeout_ms: int = 25_000) -> str | None:
    """Wait for the client-side guard to redirect; the URL it landed on, or None.

    ``usePermissionGuard`` redirects from an effect that waits on three separate
    pieces of persisted state (the auth store, the role-permissions store and the
    ``role-permissions`` localStorage key), so the bounce happens some way after
    the navigation itself resolves. Returning the URL rather than asserting here
    lets the caller say which denial it expected and why.
    """
    step = 500
    remaining = timeout_ms
    while remaining > 0:
        if UNAUTHORIZED_URL.search(page.url) or NO_ACCESS_URL.search(page.url):
            return page.url
        page.wait_for_timeout(step)
        remaining -= step
    return None


# ───────── view path: the SchoolAdmin reads their branch's dashboard ──────────
#
# Ledger unit: ``people.dashboard.view.school_admin`` (scenario ``minimal``, role
# ``school_admin``, intent ``view``, video).
#
# Constants and helpers below are prefixed ``VIEW_``/``_view_`` rather than
# reusing this file's earlier names where they differ in purpose: the file is
# written one unit at a time, and a shared module-level name would silently
# rebind under whichever section is appended last. The stable ones the sections
# genuinely agree on — ``DASHBOARD_MODULE``, ``DASHBOARD_ROUTE``, ``GREETING``,
# the three ``STAT_*`` labels, ``TABLE_HEADER_FEES``, ``PIE_CHART_HEADING``, the
# three ``*_PATH`` routes, ``NAV_SECTION_PEOPLE``, ``NAV_ADMIN_DASHBOARD`` and
# ``DENIAL_URL`` — are reused deliberately, so a relabelled screen breaks every
# unit at once rather than one of them.
#
# What this unit adds to the mandatory test above
#     ``test_dashboard_is_reachable_on_the_minimal_pack`` asks whether the screen
#     is *allowed*: licensed, offered, and answering 200. It deliberately asserts
#     nothing about the numbers, because reachability was its whole claim. A view
#     unit's claim is the other half — that the screen *reads correctly* — so
#     every figure on it is compared against the very call the page makes, for
#     the same branch and the same year. That matters more here than on a list
#     screen: each block of this dashboard has a plausible-looking fallback
#     ("0" for a missing amount, "No transactions found", "No data to display for
#     the selected year", "No financial activity recorded"), and a dashboard
#     quietly showing the fallback for real data looks identical to a correct
#     one. Each block is therefore driven off the endpoint's own answer — where
#     the branch genuinely has no fees, the empty state is what is *required*.
#
# Why the walk goes in through /module/home, and why that is not a detour
#     ``BranchesPage.select_branch`` ends on a hardcoded
#     ``router.push("/module/community")``, and the ``minimal`` pack has no
#     ``community`` — so the browser lands on /auth/no-access, which renders no
#     sidebar to click. ``/module/home`` is licensed on this pack, carries no
#     module guard of its own, and shows the same sidebar, so it is the landing
#     the "Admin Dashboard" entry is clicked from.
#
#     Arriving by that click is also what makes the two charts assertable, and it
#     is the reason this unit can read them where the mandatory test above
#     declines to. Both chart components fetch on mount using whatever
#     ``useBranchStore`` holds at that instant, and ``PieChart``'s effect depends
#     on ``[year]`` alone so it never refires — a cold ``page.goto`` races
#     zustand's rehydration of the (encrypted) persisted store and can leave the
#     pie chart showing its fetch error for ever. Clicking the sidebar entry is a
#     client-side navigation with the store already in memory, and the entry
#     itself only exists once the store is filled: the "People Module" section is
#     ``branchOnly``. Waiting for that entry is therefore the synchronisation, not
#     a sleep. None of this is patched in the app — the race is real but
#     pre-existing, and a test is not entitled to "fix" it.
#
# Deliberately not asserted
#     Currency formatting of the transaction amounts (``Intl.NumberFormat`` with
#     the "en-GH" locale resolves differently across Chromium builds, so the rows
#     are matched on name and count), and the shape of either chart's SVG. The
#     three toolbar-free panels have no controls to press: the only interactive
#     element on the whole screen is the Fees/Revenue/Expenses switch, which is
#     exercised because re-reading the ledger is part of reading it — it re-issues
#     the same GET with another ``transaction_type`` and writes nothing.

VIEW_SCENARIO = "minimal"

# The licensed, guard-free page the sidebar is clicked from (see above).
VIEW_LANDING_ROUTE = "home"
VIEW_DASHBOARD_URL = re.compile(r"/module/dashboard")

# ModuleHeader's three cards, as page.tsx::getStats() labels them, paired with
# the DashboardStats key each one renders.
VIEW_STAT_CARDS = (
    ("Fees Collected (GHC)", "fees_collected"),
    ("Revenue Generated (GHC)", "revenue_generated"),
    ("Monthly Expenses", "monthly_expenses"),
)

# components/Table.tsx — the Radix trigger in its "fees" state, the option this
# test switches to, and the header that must replace TABLE_HEADER_FEES when it
# does. Both headers carry a "/" ("2023/2024"), which is exactly what
# tests.pages.base.as_pattern exists for.
VIEW_TXN_SWITCH_FEES = re.compile(r"^\s*Fees\s*$", re.I)
VIEW_TXN_OPTION_REVENUE = re.compile(r"^\s*Revenue\s*$", re.I)
VIEW_TABLE_HEADER_REVENUE = as_pattern(r"Revenues for 2023/2024 Academic Year")
VIEW_TXN_EMPTY = re.compile(r"^\s*No transactions found\s*$", re.I)
VIEW_TXN_FAILURE = re.compile(r"failed to load transactions", re.I)

# components/PieChart.tsx::formatChartData — the four legend rows, in order, and
# the panel that replaces them when every slice is zero.
VIEW_PIE_SERIES = (
    ("Teaching Staff", "total_teachers"),
    ("Non-teaching Staff", "total_non_teaching"),
    ("Students", "total_students"),
    ("Guardians", "total_guardians"),
)
VIEW_PIE_EMPTY = re.compile(r"No data to display for the selected year", re.I)

# components/BarChart.tsx — its heading, its two legitimate body states, and the
# panel that means the fetch failed.
VIEW_BAR_HEADING = re.compile(r"^\s*Revenue & Expenses Analytics\s*$", re.I)
VIEW_BAR_EMPTY = re.compile(r"^\s*No financial activity recorded\s*$", re.I)
VIEW_BAR_FAILURE = re.compile(r"^\s*Failed to load chart data\s*$", re.I)

# page.tsx's identity line when it cannot name the signed-in user — i.e. when
# either half of `first_name`/`other_names` is empty.
VIEW_IDENTITY_FALLBACK = "Administrator"

# The pie chart's own source, and the branch register the branch id is read from.
VIEW_MEMBERS_PATH = "/statistics/school-members"
VIEW_BRANCH_STATS_PATH = "/branch/members/statistics"


@pytest.mark.school_admin
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="people.dashboard.view.school_admin",
    title="Dashboard",
    subtitle="SchoolAdmin views dashboard",
)
def test_school_admin_views_the_admin_dashboard(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin opens a branch and reads its dashboard, block by block.

    The read *is* the feature, so nothing here writes. Every figure on screen —
    the three cards, the transaction ledger, the people breakdown and the annual
    chart — is checked against the same call the page itself makes for the same
    branch, which is what separates "the dashboard rendered" from "the dashboard
    rendered this branch's actual numbers".
    """
    ctx = provisioned_school
    assert DASHBOARD_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {DASHBOARD_MODULE!r} for the "
        f"view path. {VIEW_SCENARIO!r} is chosen precisely because it is the "
        f"floor case that still carries it — the pack builder locks the whole "
        f"{PEOPLE_GROUP!r} group into every pack (see the module docstring)."
    )
    branch_name = str((ctx.branches[0] or {}).get("name") or "") if ctx.branches else ""
    assert branch_name, (
        f"provisioning recorded no branch for {ctx.school_name!r}. This screen "
        f"reports on one branch and fetches nothing at all until a SchoolAdmin "
        f"has opened one — phase B creates one for every scenario."
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    year = date.today().year

    # Setup, never an assertion about these endpoints: what the screen is
    # obliged to show, read from the very calls page.tsx and its two chart
    # components make, for the same branch and the same year.
    login = api.login(ctx.school_admin.email, ctx.school_admin.password)
    token = login["access_token"]
    branch_id = _view_branch_id(api, branch_name, token=token)
    stats = _view_read(api, f"{STATS_PATH}?branch_id={branch_id}", token=token)
    fee_rows = _view_read(
        api,
        f"{TRANSACTIONS_PATH}?transaction_type=fees&limit=5&branch_id={branch_id}",
        token=token,
    )
    revenue_rows = _view_read(
        api,
        f"{TRANSACTIONS_PATH}?transaction_type=revenue&limit=5&branch_id={branch_id}",
        token=token,
    )
    members = _view_read(
        api, f"{VIEW_MEMBERS_PATH}?year={year}&branch_id={branch_id}", token=token
    )
    analytics = _view_read(
        api, f"{ANALYTICS_PATH}?year={year}&branch_id={branch_id}", token=token
    )

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Open {branch_name} — a dashboard always reports on one branch"):
        # Mandatory, not scene-setting: this is the only gesture in the product
        # that fills the branch store both fetch effects wait on, and it is what
        # puts the branchOnly People menu on the sidebar.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Take the People menu across to the Admin Dashboard"):
        # /module/home because select_branch leaves the browser somewhere with no
        # sidebar on this pack; the click that follows is a client-side
        # navigation, which is what lets the charts below be read at all (see the
        # section comment).
        goto_module(page, base_url, VIEW_LANDING_ROUTE)
        expect(page.get_by_text(NAV_SECTION_PEOPLE).first).to_be_visible(timeout=25_000)
        nav = page.get_by_role("navigation")
        entry = nav.get_by_role("link", name=as_pattern(NAV_ADMIN_DASHBOARD)).first
        expect(entry).to_be_visible(timeout=25_000)
        entry.click()
        page.wait_for_url(VIEW_DASHBOARD_URL, timeout=25_000)
        assert not DENIAL_URL.search(page.url), (
            f"the SchoolAdmin of {ctx.school_name!r} was sent to {page.url!r} "
            f"instead of the dashboard. On the {ctx.scenario_id!r} pack "
            f"{DASHBOARD_MODULE!r} is licensed and cannot be dropped — see "
            f"test_dashboard_is_reachable_on_the_minimal_pack — so a denial here "
            f"is a real regression."
        )

    with demo.step("The dashboard opens on a greeting and the signed-in identity"):
        expect(page.get_by_role("heading", name=GREETING).first).to_be_visible(
            timeout=30_000
        )
        # The identity line is asserted against the profile the page itself
        # renders from — the `user_profile` of the login response, which
        # userauthstore persists and page.tsx reads — rather than against a
        # literal, because page.tsx only names the user when *both* halves are
        # present:
        #     {first_name && other_names ? `${first_name} ${other_names}`
        #                                : "Administrator"}
        # and a SchoolAdmin created through the product's only school-creation
        # surface never has the second half: the Create New School dialog has a
        # single "Admin Name" field, and UserService.create_school_admin puts all
        # of it in `first_name` with `other_names=""` hard-coded. So the fallback
        # is this role's *correct* rendering, and what is worth asserting is that
        # the page applied its own rule to this session's profile — a page
        # greeting some other user, or one that never resolved a profile at all,
        # still fails here.
        expect(
            page.get_by_role(
                "heading",
                name=as_pattern(
                    rf"^\s*{re.escape(_view_expected_identity(login))}\s*$"
                ),
            ).first
        ).to_be_visible(timeout=20_000)

    with demo.step("Fees, revenue and expenses for the branch, at a glance"):
        for label, key in VIEW_STAT_CARDS:
            block = stats[key]
            expect(_view_card_amount(page, label)).to_have_text(
                _view_locale_string(block["amount"]), timeout=25_000
            )
            # `${percentage_change}%`, prefixed with "+" when page.tsx classes the
            # move as an increase (>= 0).
            change = float(block["percentage_change"])
            expect(_view_card_change(page, label)).to_contain_text(
                f"{'+' if change >= 0 else ''}{_view_js_number(change)}%"
            )

    with demo.step("Underneath, the fees this branch has taken most recently"):
        expect(page.get_by_text(TABLE_HEADER_FEES).first).to_be_visible(timeout=25_000)
        expect(page.get_by_text(VIEW_TXN_FAILURE)).to_have_count(0)
        _view_expect_ledger(page, fee_rows, kind="fees")

    with demo.step("Switch the ledger over to revenue and it re-reads the branch"):
        # The only control on the screen, and a read: it re-issues the same GET
        # with transaction_type=revenue.
        BasePage(page, base_url).select_option_in_combobox(
            VIEW_TXN_SWITCH_FEES, VIEW_TXN_OPTION_REVENUE
        )
        expect(page.get_by_text(VIEW_TABLE_HEADER_REVENUE).first).to_be_visible(
            timeout=25_000
        )
        expect(page.get_by_text(VIEW_TXN_FAILURE)).to_have_count(0)
        _view_expect_ledger(page, revenue_rows, kind="revenue")

    with demo.step("Beside it, everyone the campus is made up of"):
        expect(page.get_by_role("heading", name=PIE_CHART_HEADING).first).to_be_visible(
            timeout=25_000
        )
        counts = {key: int(members[key]) for _, key in VIEW_PIE_SERIES}
        if not any(counts.values()):
            # Every slice zero is the one state the chart refuses to draw.
            expect(page.get_by_text(VIEW_PIE_EMPTY).first).to_be_visible(timeout=25_000)
        else:
            for label, key in VIEW_PIE_SERIES:
                expect(_view_pie_value(page, label)).to_have_text(
                    str(counts[key]), timeout=25_000
                )
            # …and this is not a chart of nothing: `minimal` licenses `staff`, so
            # provisioning put a teacher and an accountant in this branch inside
            # the window StatisticsService counts over.
            assert counts["total_teachers"] >= 1 and counts["total_non_teaching"] >= 1, (
                f"GET {VIEW_MEMBERS_PATH} reports {counts} for {branch_name!r}, "
                f"yet provisioning created a teacher and an accountant in it. "
                f"Either the creates landed in another branch or the statistics "
                f"query stopped counting them — the chart is reading the truth "
                f"either way, so this is not a rendering failure."
            )

    with demo.step("And the year's money, month by month", dwell_ms=2500):
        expect(page.get_by_role("heading", name=VIEW_BAR_HEADING).first).to_be_visible(
            timeout=30_000
        )
        expect(
            page.get_by_text(
                as_pattern(rf"Financial performance overview for {year}")
            ).first
        ).to_be_visible(timeout=15_000)
        expect(page.get_by_text(VIEW_BAR_FAILURE)).to_have_count(0)
        if _view_analytics_all_zero(analytics):
            expect(page.get_by_text(VIEW_BAR_EMPTY).first).to_be_visible(timeout=20_000)
        else:
            # recharts draws into an SVG with no accessible text of its own, so
            # what is assertable is that the chart replaced the empty panel.
            expect(page.get_by_text(VIEW_BAR_EMPTY)).to_have_count(0)
            expect(page.locator("svg.recharts-surface").first).to_be_visible(
                timeout=20_000
            )


# ───────── helpers for the view path ─────────


def _view_expected_identity(login: dict[str, Any]) -> str:
    """The identity line ``/module/dashboard`` must render for this session.

    Mirrors page.tsx exactly — ``first_name && other_names`` joined, and the
    literal ``"Administrator"`` when either half is missing — evaluated against
    the ``user_profile`` the login response carries, which is the same object
    ``userauthstore`` persists and the page reads. See the assertion's comment
    for why a SchoolAdmin legitimately lands on the fallback.
    """
    profile = login.get("user_profile") or {}
    first = str(profile.get("first_name") or "").strip()
    other = str(profile.get("other_names") or "").strip()
    return f"{first} {other}" if first and other else VIEW_IDENTITY_FALLBACK


def _view_card_amount(page: Page, label: str) -> Locator:
    """The ``<dd>`` holding one ModuleHeader card's figure.

    ``ModuleHeader`` renders ``<div><dt>{name}</dt><dd>{stat}</dd><div>…</div>
    </div>`` with no role of its own, so the label is the only anchor. It is
    matched anchored and escaped — two of the three labels end in "(GHC)".
    """
    return _view_card_label(page, label).locator("xpath=following-sibling::dd").first


def _view_card_change(page: Page, label: str) -> Locator:
    """The card's "vs last year" line — the ``<div>`` following its ``<dd>``."""
    return _view_card_label(page, label).locator("xpath=following-sibling::div[1]").first


def _view_card_label(page: Page, label: str) -> Locator:
    # `dt` is used nowhere else on this screen, so it needs no further scoping.
    return page.locator("dt").filter(
        has_text=as_pattern(rf"^\s*{re.escape(label)}\s*$")
    ).first


def _view_pie_value(page: Page, series: str) -> Locator:
    """The count span of one legend row of the Members Overview chart.

    A row is ``<div><div><dot/><span>{name}</span></div><div><span>{value}</span>
    <span>({percentage})</span></div></div>``, so walking from the name span to
    the sibling group's first span reads the number without depending on utility
    classes, and without ``inner_text`` having to guess where the flex gap put a
    space.

    Scoped to the chart's own Card: the sidebar renders its nav labels in spans
    too, and one of them ("Students") is also a legend label.
    """
    card = page.get_by_role("heading", name=PIE_CHART_HEADING).first.locator("xpath=../..")
    label = card.locator("span").filter(
        has_text=as_pattern(rf"^\s*{re.escape(series)}\s*$")
    ).first
    return label.locator("xpath=../following-sibling::div[1]/span[1]").first


def _view_expect_ledger(page: Page, transactions: list, *, kind: str) -> None:
    """The transactions table shows exactly what the endpoint reported.

    Driven off the payload rather than assuming either state: on a pack that
    licenses neither ``fees`` nor ``incomes_and_expenses`` the empty panel is
    what the screen is *required* to show, and asserting rows would be asserting
    a fiction — while on a school that has booked something, the empty panel is
    the bug this checks for. The dashboard renders exactly one ``<table>``.
    """
    body = page.locator("table tbody").first
    if not transactions:
        expect(body.get_by_text(VIEW_TXN_EMPTY).first).to_be_visible(timeout=25_000)
        return
    expect(body.locator("tr")).to_have_count(len(transactions), timeout=25_000)
    for transaction in transactions:
        name = str(transaction.get("name") or "")
        assert name, (
            f"a {kind} transaction came back unnamed, so there is nothing the "
            f"table could have rendered for it: {transaction!r}"
        )
        expect(
            body.locator("tr").filter(has_text=as_pattern(re.escape(name))).first
        ).to_be_visible(timeout=15_000)


def _view_analytics_all_zero(analytics: dict) -> bool:
    """Whether the bar chart will fall back to its "no activity" panel.

    ``BarChart`` maps the payload onto all twelve months and reads a missing
    month as 0, so "every entry zero" is the same test the component makes.
    """
    entries = list(analytics.get("revenue") or []) + list(analytics.get("expenses") or [])
    return all(float(entry.get("amount") or 0) == 0 for entry in entries)


def _view_js_number(value: float) -> str:
    """A number as a JavaScript template literal prints it (``${x}``).

    JS has one number type, so an integral value loses its ".0" — and the
    percentage line is built by interpolation, not by ``toLocaleString``.
    """
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:.10f}".rstrip("0").rstrip(".")


def _view_locale_string(value: float) -> str:
    """A number as ``Number.prototype.toLocaleString()`` renders it.

    Enough of the algorithm for what this endpoint serves: thousands grouped
    with commas and the default maximum of three fraction digits.
    ``DashboardStatItem.amount`` is a ``RoundedFloat`` (two decimals), so the
    rounding here never has to decide anything the backend has not already.
    """
    number = round(float(value), 3)
    whole = int(abs(number))
    fraction = abs(number) - whole
    text = f"{whole:,}"
    if fraction:
        text += f"{fraction:.3f}"[1:].rstrip("0").rstrip(".")
    return ("-" if number < 0 else "") + text


def _view_branch_id(api: BackendAPI, branch_name: str, *, token: str) -> int:
    """The id of the branch under test, resolved the way the app resolves it.

    Setup, not an assertion about this endpoint. Provisioning's recorded id is
    deliberately not trusted here: ``BranchesPage.create_branch`` returns -1 when
    it could not read the create response, and every dashboard call needs a real
    one — they answer 400 BRANCH_ID_REQUIRED to a SchoolAdmin without it.
    """
    branches = _view_read(api, VIEW_BRANCH_STATS_PATH, token=token)
    for branch in branches:
        if str(branch.get("name", "")).strip() == branch_name:
            return int(branch["branch_id"])
    raise AssertionError(
        f"{branch_name!r} is not in {VIEW_BRANCH_STATS_PATH}'s response, so the "
        f"dashboard has no branch to report on either. Branches reported: "
        f"{[b.get('name') for b in branches]}"
    )


def _view_read(api: BackendAPI, path: str, *, token: str):
    """One setup read, or a failure that says why the comparisons cannot be made."""
    res = api.get(path, token=token)
    assert res.status_code == 200, (
        f"a SchoolAdmin must be able to read {path} — /module/{DASHBOARD_ROUTE} "
        f"is built entirely out of these calls, and the statistics ones are gated "
        f"on the ('read', {DASHBOARD_MODULE!r}) permission this unit is about. "
        f"Got {res.status_code}: {res.text[:300]}"
    )
    return res.json()
