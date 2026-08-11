"""Governance → Academic Year & Term — the academic calendar (`academic_year_and_term`).

This file is written one ledger unit at a time; each section below owns its own
constants (prefixed, never shared) so appending a unit can never silently rebind
a name an earlier section relies on.

Where this module lives
    One page: ``/module/academic_year_and_term``
    (``smsfrontend/src/app/module/academic_year_and_term/page.tsx``). It is the
    "Academic Settings" workspace — two tabs ("Academic Years" / "Academic
    Terms") over a table of Name / Status / Start Date / End Date / Date Created
    / Last Modified / Actions, a "Create Academic Year" and a "Create Academic
    Term" button, and a row menu offering Edit / Activate / Deactivate / Delete.
    Its data sources are ``GET /academic-year/`` and
    ``GET /academic-term/by-year/{id}``; its writes are ``POST|PUT|DELETE
    /academic-year/`` and ``POST|PUT|DELETE /academic-term/``.

Negative unit: a SchoolAdmin of the ``minimal`` school, whose scenario asks for a
pack holding only ``school_configuration`` and ``school_admin_dashboard``
(``test_academic_year_and_term_is_unexcludable_and_never_denied_to_a_school_admin``).

THERE IS NO DENIAL TO ASSERT — and there is no unlicensed school to assert it on
    Two independent findings meet here, and the test pins down both.

FINDING 1 — the module cannot be left out of a feature pack at all
    ``smsfrontend/src/app/module/feature_flag/create/page.tsx`` (and its
    ``edit/[id]`` twin) declares ``BASIC_GROUPS = ["people", "governance"]`` and
    treats every module in those two groups as mandatory:
    ``isBasicLockedModule`` renders the checkbox ``locked``, ``toggleModule``
    returns early for it, ``clearAll`` resets the selection *to* the locked set
    rather than to nothing, the panel is captioned "Basic Modules Required", and
    ``handleSave`` refuses outright with "All basic modules (People &
    Governance) must be selected." ``academic_year_and_term`` is in the
    ``governance`` group (``services/feature_pack_service.SYSTEM_MODULE_GROUPS``),
    so **every pack the product can build carries it** — the ``minimal`` pack
    included, whatever ``config/feature_scenarios.yaml`` asks for. Reading the
    packs back off the running system confirms it: every ``TEST Minimal Pack``
    holds the same ten modules (the six governance ones plus home, dashboard,
    students, staff).

    So the state this unit was written against — "a school whose pack excludes
    ``academic_year_and_term``" — is not reachable through the product. The
    backend would store such a pack happily (``POST /feature-packs/`` takes any
    module list), which is exactly the contradiction that has to be settled by a
    human: either the governance/people modules are core and should stop being
    offered as licensable, or the pack builder should let them be cleared. That
    question is on the "may NOT decide alone" list, so the unit is reported
    BLOCKED and nothing in either app was changed.

FINDING 2 — even if it *were* excluded, nothing would deny this role
    Every candidate surface was checked in the source, and not one of them fires
    for a SchoolAdmin:

    1. **The sidebar.** ``nav-config.tsx`` lists
       ``{ label: "Academic Year & Term", … module: "academic_year_and_term" }``
       in the "Governance Module" section with **no** ``permission`` key.
       ``SideNavigation.canShowItem`` reaches its module gate only after the
       line ``if (currentRoleName?.toLowerCase() === "schooladmin") return
       true;`` — commented "SchoolAdmin bypasses the module gate: they own the
       school config and governance pages". So the entry is rendered whatever
       the pack says.
    2. **The route guard.** ``src/middleware.ts`` skips its module enforcement
       for a SchoolAdmin outright ("SchoolAdmin bypasses: governance pages …
       are not feature-flag modules"), and ``useModuleGuard`` — which this page
       does call, on the module's own name — returns ``true`` for a SchoolAdmin
       before it ever reads the ``schoolModules`` cookie. Its
       ``hasModuleAccess === false`` branch is unreachable for this role, so
       there is no ``/auth/no-access`` redirect.
    3. **The API.** This is the one that would normally supply the denial, the
       way it does for topics, syllabi, lessons and audit trails: a 403
       "Feature not available in your plan" from the feature-pack half of
       ``utils.permissions.has_permission``, which the axios interceptor in
       ``src/utils/handleErrorMessage.ts`` turns into a hard redirect to
       ``/auth/no-access``. It cannot fire here. **Every** gated route in
       ``api/routes/academic_year.py`` and ``api/routes/academic_term.py``
       names ``school_configuration`` as its module —
       ``Depends(has_permission("manage", "school_configuration"))`` — and
       ``school_configuration`` is in the ``minimal`` pack (the loader in
       ``config/scenarios.py`` *requires* it in every scenario). Several routes
       — ``GET /academic-year/``, ``GET /academic-term/by-year/{id}``,
       ``PUT /academic-*/activate|deactivate/{id}`` — carry no
       ``has_permission`` dependency at all.

    So ``academic_year_and_term`` is a **sellable but unenforced** module: it is
    offered in the governance group of ``SYSTEM_MODULE_GROUPS``
    (``services/feature_pack_service.py``) and gates the page for every other
    role, while a SchoolAdmin — the only role the Governance section is shown to
    (``roleGate: ["SchoolAdmin"]``) — keeps the whole calendar regardless.

    Wiring the routes to ``academic_year_and_term`` would close that hole, and
    is deliberately **not** done here: "enforce a gate/licence check that was
    previously unenforced" is a product decision, not a defect fix.

What this test therefore asserts
    The premise, in full, so the conclusion cannot be read as an accident: the
    pack really is assigned; it carries ``academic_year_and_term`` even though
    the scenario asked for it to be left out (finding 1); the pack is
    nonetheless *not* inert for this school — a module the builder does let you
    clear (``catalogue``) really is absent and really does earn a 403 — and the
    SchoolAdmin role really does hold the permission the routes check. Then the
    absence of each of the three denial surfaces above, ending with the
    capability itself: the calendar written through the UI, toast and register
    row and all.

    It is a **guard**, in the same spirit as
    ``academics/test_exams.py::test_exams_is_licensed_but_ships_no_management_surface``:
    the moment the pack builder lets ``academic_year_and_term`` be cleared, or
    anyone gates these routes on it — or hides the nav entry, or lets
    ``useModuleGuard`` bite for a SchoolAdmin — one of the assertions below
    fails, which is the signal to unblock the unit and rewrite it as an ordinary
    denial test.

    Everything it creates carries the "TEST" prefix the orphan sweeper matches
    on plus the run tag, is created **inactive** so it cannot displace the
    current year for the other units sharing this session's school, and is
    deleted again by the ``unlicensed_year`` fixture.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.academic_year import (
    ACTIVE_BADGE,
    CREATE_TERM_TRIGGER,
    CREATE_YEAR_TRIGGER,
    HEADING,
    INACTIVE_BADGE,
    AcademicYearTermPage,
)

ACADEMIC_YEAR_MODULE = "academic_year_and_term"
# The module every gated route on api/routes/academic_year.py and
# api/routes/academic_term.py actually names — see the docstring.
ACADEMIC_YEAR_GATE_MODULE = "school_configuration"

# config/module_catalog.py's route for this module.
ACADEMIC_YEAR_ROUTE = "academic_year_and_term"

DENIED_SCENARIO = "minimal"

# A module the pack builder *does* let a SuperAdmin clear — it lives in the
# `library` group, not in the locked `people`/`governance` pair — and which the
# minimal pack therefore really does omit. Probed below so that "nothing denied
# this school" cannot be read as "feature packs do not bite here at all".
EXCLUDABLE_MODULE = "catalogue"
# A read route gated on it (api/routes/book.py).
EXCLUDABLE_MODULE_ROUTE = "/books/?skip=0&limit=1"

# The role whose permissions are checked against the pack.
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The licence denial utils/permissions.py answers with, and which
# handleErrorMessage.ts keys its /auth/no-access redirect off. Its *absence* is
# what this test is about.
FEATURE_DENIAL_DETAIL = re.compile(r"Feature not available in your plan", re.I)

# Where a denied user would land, and the copy waiting for them there
# (src/app/auth/no-access/page.tsx).
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)

# The sidebar entry (nav-config.tsx, "Governance Module" section). That section
# is noBranchOnly, so it is only rendered while no branch is selected in the
# zustand store — which is the state a fresh login leaves the browser in.
NAV_ACADEMIC_YEAR = re.compile(r"^\s*Academic Year & Term\s*$", re.I)

# The workspace's own chrome (academic_year_and_term/page.tsx). HEADING,
# CREATE_YEAR_TRIGGER and CREATE_TERM_TRIGGER come from the page object.
PAGE_SUBTITLE = re.compile(r"^\s*Manage academic years and terms\s*$", re.I)
YEARS_TAB_LABEL = re.compile(r"^\s*Academic Years\b", re.I)
TERMS_TAB_LABEL = re.compile(r"^\s*Academic Terms\b", re.I)

# The PageError panels the page draws when a fetch fails — neither may appear,
# since neither fetch is refused.
YEARS_LOAD_ERROR = re.compile(r"Failed to load academic years", re.I)
TERMS_LOAD_ERROR = re.compile(r"Failed to load academic terms", re.I)

# The year this unit authors. Deliberately slash-free: an academic year is
# normally named "2026/2027", and a "/" inside a selector pattern has to be
# routed through tests.pages.base.as_pattern — a hazard this unit has no reason
# to take on. Its range is far enough out that it cannot overlap anything the
# other minimal-scenario units create (AcademicYearService._validate_year_dates
# rejects overlaps within a school).
UNLICENSED_YEAR_NAME = f"TEST Unlicensed Calendar {run_tag()}"
UNLICENSED_YEAR_START = "2032-09-01"
UNLICENSED_YEAR_END = "2033-07-31"

# Ids that cannot exist, used to probe the route-level dependency without
# touching a row. has_permission is solved before the path/body params are
# validated and long before anything is looked up, so a 404/400/422 from these
# is itself the proof that the licence gate let the request through.
NO_SUCH_ID = 999_999_999


@pytest.fixture
def unlicensed_year(provisioned_school: SchoolContext, api: BackendAPI) -> Iterator[None]:
    """Delete the academic year this unit authors, however the test ends.

    ``provisioned_school`` is session-scoped and shared, so the row must not
    outlive the test that made it. Cleanup never raises: a failure here would
    mask the assertion that actually failed, and the name carries the "TEST"
    prefix the orphan sweeper matches on either way.
    """
    yield

    ctx = provisioned_school
    try:
        token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
        listed = api.get(
            f"/academic-year/?skip=0&limit=100&school_id={ctx.school_id}", token=token
        )
        if listed.status_code >= 400:
            return
        for row in listed.json():
            if str(row.get("name", "")).strip() == UNLICENSED_YEAR_NAME:
                api.delete(f"/academic-year/{row['id']}", token=token)
    except Exception:  # noqa: BLE001 — cleanup never propagates
        return


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_academic_year_and_term_is_unexcludable_and_never_denied_to_a_school_admin(
    unlicensed_year: None,
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """No pack can leave `academic_year_and_term` out, and nothing denies it anyway.

    Characterisation, not approval — see the module docstring. Each assertion is
    written so that the *arrival* of either half of the denial (a pack that can
    omit the module, or a route that refuses one that does) breaks it, because
    that is the event which makes this unit writable as a real negative test.
    """
    ctx = provisioned_school
    if ACADEMIC_YEAR_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {ACADEMIC_YEAR_MODULE!r}; "
            f"this unit only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The premise: the pack cannot omit the module, but is not inert ─────
    #
    # Asserted first and in full, so "nothing denied them" can never be read as
    # "there was nothing to deny in the first place".
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so nothing "
        f"below says anything about licensing. Provisioning phase A assigns one "
        f"— check that it did."
    )
    modules = body.get("modules") or []
    assert ACADEMIC_YEAR_MODULE in modules, (
        f"{ctx.school_name!r} is NOT licensed for {ACADEMIC_YEAR_MODULE!r}. That "
        f"is the state governance.academic_year_and_term.denied was blocked for "
        f"being unable to reach: the pack builder locks every `governance` and "
        f"`people` module into every pack ('All basic modules (People & "
        f"Governance) must be selected'), so the {ctx.scenario_id!r} pack "
        f"({sorted(ctx.feature_modules)} requested) still ships it. If that has "
        f"changed, unblock the unit and rewrite this as an ordinary denial test. "
        f"Licensed: {sorted(modules)}"
    )
    assert EXCLUDABLE_MODULE not in modules, (
        f"this unit proves the feature pack is not simply ignored for "
        f"{ctx.school_name!r} by pointing at {EXCLUDABLE_MODULE!r}, a module the "
        f"builder does allow to be cleared — but the school is licensed for it, "
        f"so that proof is unavailable. Licensed: {sorted(modules)}"
    )
    excluded = api.get(EXCLUDABLE_MODULE_ROUTE, token=token)
    assert excluded.status_code == 403, (
        f"the pack omits {EXCLUDABLE_MODULE!r}, so {EXCLUDABLE_MODULE_ROUTE} must "
        f"answer this SchoolAdmin with 403 — got {excluded.status_code}: "
        f"{excluded.text[:300]}. Without that, 'the calendar was never denied' "
        f"would only mean feature packs are unenforced for this school entirely."
    )
    assert FEATURE_DENIAL_DETAIL.search(excluded.text), (
        f"{EXCLUDABLE_MODULE_ROUTE} answered 403 for a reason other than the "
        f"licence — got {excluded.text[:300]}"
    )
    assert ACADEMIC_YEAR_GATE_MODULE in modules, (
        f"{ctx.school_name!r} is not licensed for {ACADEMIC_YEAR_GATE_MODULE!r}, "
        f"which is the module every gated academic-year/term route actually "
        f"names. config/scenarios.py requires it in every scenario; if that has "
        f"changed, this school WOULD now be denied and this unit should be "
        f"rewritten as an ordinary denial test."
    )

    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_perms = {
        (p.get("name"), p.get("module")) for p in role.json().get("permissions", [])
    }
    assert ("manage", ACADEMIC_YEAR_GATE_MODULE) in role_perms, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds "
        f"('manage', {ACADEMIC_YEAR_GATE_MODULE!r}), which is the permission half "
        f"of the gate on every academic-year/term write. The role, not the pack, "
        f"would now be what stops them — re-point this unit accordingly."
    )

    # ── 2. The API never refuses them ─────────────────────────────────────────
    #
    # Every route the workspace calls, reads and writes alike. The ids are
    # deliberately unreachable and the create bodies deliberately empty: a
    # route-level dependency is solved before the path and body are validated,
    # so 404/400/422 here means "the gate passed and the handler was reached",
    # while a 403 would mean a licence check finally bit. Nothing is written.
    probes = {
        # What the two tabs fetch on mount. Neither route carries has_permission
        # at all.
        "list_years": api.get(
            f"/academic-year/?skip=0&limit=100&school_id={ctx.school_id}", token=token
        ),
        "list_terms_by_year": api.get(f"/academic-term/by-year/{NO_SUCH_ID}", token=token),
        # read/school_configuration.
        "year_detail": api.get(f"/academic-year/{NO_SUCH_ID}", token=token),
        "term_detail": api.get(f"/academic-term/{NO_SUCH_ID}", token=token),
        # manage/school_configuration — the Create / Edit / Delete affordances.
        "create_year": api.post("/academic-year/", token=token, json={}),
        "update_year": api.put(f"/academic-year/{NO_SUCH_ID}", token=token, json={}),
        "delete_year": api.delete(f"/academic-year/{NO_SUCH_ID}", token=token),
        "create_term": api.post("/academic-term/", token=token, json={}),
        "update_term": api.put(f"/academic-term/{NO_SUCH_ID}", token=token, json={}),
        # Ungated entirely — the row menu's Activate / Deactivate.
        "activate_year": api.put(f"/academic-year/activate/{NO_SUCH_ID}", token=token),
        "activate_term": api.put(f"/academic-term/activate/{NO_SUCH_ID}", token=token),
    }
    for label, res in probes.items():
        assert res.status_code != 403, (
            f"{label}: the backend now refuses a SchoolAdmin of "
            f"{ctx.school_name!r} with {res.status_code}: {res.text[:300]}. The "
            f"calendar routes name {ACADEMIC_YEAR_GATE_MODULE!r} and the school "
            f"holds it, so a refusal here means either the gate was re-pointed at "
            f"{ACADEMIC_YEAR_MODULE!r} or the seeded role lost its permission — "
            f"both are the signal to revisit "
            f"governance.academic_year_and_term.denied."
        )
        assert not FEATURE_DENIAL_DETAIL.search(res.text), (
            f"{label}: answered {res.status_code} carrying the feature-pack "
            f"denial — {res.text[:300]}"
        )

    # ── 3. …and neither does the UI ───────────────────────────────────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # (a) The sidebar still offers the module. The Governance section is
    #     noBranchOnly, and a fresh login has selected no branch, so it renders.
    nav_entry = page.get_by_role("link", name=as_pattern(NAV_ACADEMIC_YEAR)).first
    expect(nav_entry).to_be_visible(timeout=25_000)

    # (b) Following it mounts the workspace rather than bouncing to no-access.
    nav_entry.click()
    academics = AcademicYearTermPage(page, frontend_base_url)
    expect(page.get_by_role("heading", name=as_pattern(HEADING))).to_be_visible(
        timeout=25_000
    )
    expect(page).not_to_have_url(NO_ACCESS_URL)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_have_count(0)
    expect(page.get_by_text(as_pattern(PAGE_SUBTITLE))).to_be_visible()

    # (c) Both fetches succeeded, so neither PageError panel is drawn.
    expect(page.get_by_text(as_pattern(YEARS_LOAD_ERROR))).to_have_count(0)
    expect(page.get_by_text(as_pattern(TERMS_LOAD_ERROR))).to_have_count(0)

    # (d) Typing the URL by hand is no different — worth asserting separately,
    #     because middleware.ts only ever sees a hand-typed navigation, and it is
    #     the surface that redirects every *other* role to /auth/no-access.
    goto_module(page, frontend_base_url, ACADEMIC_YEAR_ROUTE)
    expect(page.get_by_role("heading", name=as_pattern(HEADING))).to_be_visible(
        timeout=25_000
    )
    expect(page).not_to_have_url(NO_ACCESS_URL)

    # (e) Every write affordance is offered, on both tabs.
    expect(page.get_by_role("button", name=as_pattern(YEARS_TAB_LABEL)).first).to_be_visible()
    expect(page.get_by_role("button", name=as_pattern(TERMS_TAB_LABEL)).first).to_be_visible()
    expect(
        page.get_by_role("button", name=as_pattern(CREATE_YEAR_TRIGGER)).first
    ).to_be_enabled()
    academics.show_terms()
    expect(
        page.get_by_role("button", name=as_pattern(CREATE_TERM_TRIGGER)).first
    ).to_be_enabled()

    # (f) And the capability itself works end to end. This is the assertion that
    #     matters: not "a button was rendered" but "the school that asked for a
    #     pack without this module wrote to its academic calendar anyway".
    #     create_year drives the
    #     modal, waits for the "Academic year created successfully" toast and
    #     reads the row back off the register; set_active=False keeps it from
    #     displacing the current year for the other units sharing this school,
    #     and the unlicensed_year fixture deletes it again.
    academics.create_year(
        name=UNLICENSED_YEAR_NAME,
        start_date=UNLICENSED_YEAR_START,
        end_date=UNLICENSED_YEAR_END,
        set_active=False,
    )
    expect(academics.year_row(UNLICENSED_YEAR_NAME)).to_be_visible(timeout=15_000)


# ══════════ governance.academic_year_and_term.manage.school_admin ═══════════
#
# The positive half, against ``finance_only`` — a pack that does license
# ``academic_year_and_term``. A school administrator opens the calendar from the
# Governance menu, files next-but-one year, corrects its name, moves the school
# onto it, opens its first term, corrects that name too, reloads to prove the
# register really was rewritten, and finally puts the school back on the year it
# started the day with.
#
# What "manage" means on this screen
#     ``page.tsx`` offers four writes per row — Edit, Activate, Deactivate,
#     Delete — plus the two Create buttons. This unit drives Create, Edit and
#     Activate, and deliberately never presses Deactivate or Delete from the UI:
#     the rows it authors are removed by the ``managed_calendar`` fixture so that
#     a failure half way through still cleans up, and the *provisioned* year and
#     term are never candidates for either.
#
# Why the terms half has to activate a year first — the shape of the product
#     ``AcademicTermService.get_academic_term_by_year`` filters
#     ``is_active.is_(True)``: ``GET /academic-term/by-year/{id}`` answers with
#     the year's **current** term and nothing else. That is deliberate — the
#     backend's own suite pins it (``test_academic_term_service.py::
#     test_get_academic_term_by_year_excludes_inactive``, added by
#     "feat: update academic term retrieval to exclude inactive and deleted
#     terms") — so it must not be "fixed" to make a test pass.
#
#     Two consequences shape everything below. First, ``fetchData`` only ever
#     fetches ``by-year/{active year}``, so a term is visible on the Academic
#     Terms tab only while **both** its year is the school's current year and
#     the term is that year's current term. A term created inactive is written
#     to the database and then never listed again — it survives the create only
#     as optimistic React state, and vanishes on the first reload. Second, a
#     term therefore has to be added to the year the school is *running*.
#
#     So the walkthrough moves the school onto the new year, opens that year's
#     first term there, and moves it back. That order is what keeps the
#     provisioned year's own calendar untouched: ``set_active_term`` only
#     deactivates terms *of the same academic year*, so "Term 1" of 2026/2027 is
#     never so much as read while the new year is current. Contrast the
#     alternative — adding a second term to 2026/2027 and activating it — which
#     would deactivate Term 1, and could not be undone from this screen at all,
#     since an inactive term is no longer listed for anyone to click Activate on.
#
#     ``provisioned_school`` is session-scoped and *shared* with every other unit
#     in this scenario's batch, and the fee, payroll and staff units bill against
#     the school's active year — so the switch back is not decoration. It is
#     asserted at the end of the test *and* repeated by the fixture, which is
#     what covers a failure that lands while the new year is current.
#
# Why the edits are renames and nothing else
#     The only other editable field is the Date Range, and its antd RangePicker
#     is a *controlled* component: ``value={[dayjs(form.start_date), …]}``, with
#     ``handleYearDateChange`` ignoring any change that does not carry both
#     halves. Re-dating it therefore means re-committing start *and* end against
#     a panel that is already showing a range — a twitchier gesture than
#     ``BasePage.commit_date`` was written for, and not the thing this unit is
#     about. A rename is still a full round-trip of the record:
#     ``updateAcademicYear`` PUTs name, is_active and both dates together, so
#     the "dates survived the rename" assertions below are load-bearing — they
#     are what would catch an edit that silently dropped the range.
#
# Why the new year is dated 2028/29 and its term runs January to April 2029
#     ``AcademicYearService._validate_year_dates`` rejects a year whose range
#     overlaps another year of the same school, and
#     ``AcademicTermService._validate_term_dates`` rejects a term overlapping a
#     sibling term of the same year. Provisioning already laid down
#     2026-09-01→2027-07-31 with "Term 1" running to 2026-12-15, so the year
#     below starts a clear season later, and its term sits inside it.
#
# No branch is selected, and that is deliberate
#     The Governance section of ``nav-config.tsx`` is ``noBranchOnly``, so
#     picking a branch first would remove the very menu entry this walkthrough
#     clicks. Nothing here needs one: an academic year is school-scoped (the
#     page reads ``school_config.id`` from the auth store), which is why the
#     usual ``BranchesPage.select_branch`` prerequisite does not apply.

MANAGE_SCENARIO = "finance_only"
MANAGE_MODULE = "academic_year_and_term"

# Named without a "/" on purpose — see UNLICENSED_YEAR_NAME above. The tag comes
# last on the original and second-to-last on the correction, so neither name is
# a substring of the other and "the old row is gone" can actually be asserted.
MANAGE_TAG = run_tag()
MANAGE_YEAR_NAME = f"TEST Academic Year 2028-2029 {MANAGE_TAG}"
MANAGE_YEAR_RENAMED = f"TEST Academic Year 2028-2029 Corrected {MANAGE_TAG}"
MANAGE_YEAR_START = "2028-09-01"
MANAGE_YEAR_END = "2029-07-31"

# The new year's own first term. It sits inside 2028-09-01→2029-07-31 and is
# hung off the *new* year, never off the provisioned one — see the section
# comment: a term is only ever listed while its year is the school's current
# year, so writing into 2026/2027 would mean deactivating "Term 1", which this
# screen offers no way back from.
MANAGE_TERM_NAME = f"TEST Second Term {MANAGE_TAG}"
MANAGE_TERM_RENAMED = f"TEST Spring Term {MANAGE_TAG}"
MANAGE_TERM_START = "2029-01-08"
MANAGE_TERM_END = "2029-04-06"


@pytest.fixture
def managed_calendar(
    provisioned_school: SchoolContext, api: BackendAPI
) -> Iterator[None]:
    """Put the school's calendar back exactly as provisioning left it.

    Three things, in this order, because each depends on the one before:

    1. **Re-activate the provisioned year.** The walkthrough makes its own year
       current in order to reach the Academic Terms tab for it, and a test that
       fails in between would otherwise leave ``provisioned_school`` — which is
       session-scoped and shared — pointing at a year the fee, payroll and staff
       units know nothing about. This runs even when the test itself already
       switched back; activating the year that is already active is a no-op.
    2. **Delete the term.** Only then, because a year cannot be removed with a
       term still hanging off it, and because ``by-year/{id}`` is the only route
       that lists terms — it answers with the year's *active* term alone
       (``get_academic_term_by_year`` filters ``is_active``), which is why the
       term this unit writes is deliberately left active until it is deleted.
    3. **Delete the year**, now that it is neither current nor a parent.

    Cleanup never raises: a failure here would mask the assertion that actually
    failed, and every name carries the "TEST" prefix the orphan sweeper matches
    on anyway. Both names are matched in either their original or their
    corrected form, because the test may have failed at any point in between.
    """
    yield

    ctx = provisioned_school
    wanted_years = {MANAGE_YEAR_NAME, MANAGE_YEAR_RENAMED}
    wanted_terms = {MANAGE_TERM_NAME, MANAGE_TERM_RENAMED}
    try:
        token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
        listed = api.get(
            f"/academic-year/?skip=0&limit=100&school_id={ctx.school_id}", token=token
        )
        if listed.status_code >= 400:
            return
        years = [row for row in listed.json() if isinstance(row, dict)]

        for year in years:
            if str(year.get("name", "")).strip() == ctx.academic_year:
                api.put(f"/academic-year/activate/{year['id']}", token=token)
                break

        for year in years:
            terms = api.get(f"/academic-term/by-year/{year['id']}", token=token)
            if terms.status_code >= 400:
                continue
            for term in terms.json():
                if str(term.get("name", "")).strip() in wanted_terms:
                    api.delete(f"/academic-term/{term['id']}", token=token)

        for year in years:
            if str(year.get("name", "")).strip() in wanted_years:
                api.delete(f"/academic-year/{year['id']}", token=token)
    except Exception:  # noqa: BLE001 — cleanup never propagates
        return


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="governance.academic_year_and_term.manage.school_admin",
    title="Academic Year & Term",
    subtitle="SchoolAdmin creates and manages academic year & term",
)
def test_school_admin_manages_the_academic_calendar(
    managed_calendar: None,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A school administrator adds a year and a term, and corrects both.

    The school ends the walkthrough running the very year and term it started
    it with: nothing this test writes touches the provisioned year's own
    calendar, and the year it makes current in the middle is handed back at the
    end. That invariant is what the rest of this scenario's batch bills and
    reports against, so it is asserted rather than merely intended.
    """
    ctx = provisioned_school
    assert MANAGE_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {MANAGE_MODULE!r} for this "
        f"unit — it is the create/edit happy path ({sorted(ctx.feature_modules)})"
    )
    current_year = ctx.academic_year
    assert current_year, (
        f"provisioning left {ctx.school_name!r} with no academic year, so there "
        f"is no year for this walkthrough to be measured against. Phase B "
        f"creates one whenever the pack licenses {MANAGE_MODULE!r} — check that "
        f"it did."
    )
    current_term = ctx.current_term
    assert current_term, (
        f"provisioning left {ctx.school_name!r} with no academic term, so "
        f"'the school is running the same term it was' cannot be asserted at "
        f"the end. Phase B creates one alongside the year."
    )

    page: Page = demo.page
    academics = AcademicYearTermPage(page, demo.frontend_base_url)

    with demo.step(f"Sign in as the administrator of {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.school_admin)

    with demo.step("The school calendar lives under Academic Year & Term, in the "
                   "Governance menu"):
        academics.expect_nav_entry()
        academics.open_from_nav()
        # The year the school is running today. Everything below is measured
        # against it staying exactly that.
        expect(
            academics.year_row(current_year).get_by_text(as_pattern(ACTIVE_BADGE)).first
        ).to_be_visible(timeout=20_000)

    with demo.step("Plan ahead: open the 2028-2029 academic year, running "
                   "September 2028 to July 2029"):
        academics.create_year(
            name=MANAGE_YEAR_NAME,
            start_date=MANAGE_YEAR_START,
            end_date=MANAGE_YEAR_END,
            set_active=False,
        )
        year_row = academics.year_row(MANAGE_YEAR_NAME)
        expect(year_row).to_be_visible(timeout=15_000)
        expect(year_row).to_contain_text(_manage_date_label(MANAGE_YEAR_START))
        expect(year_row).to_contain_text(_manage_date_label(MANAGE_YEAR_END))
        # Filed for later, not switched on: this school is still teaching the
        # year provisioning made current.
        expect(year_row.get_by_text(as_pattern(INACTIVE_BADGE)).first).to_be_visible()

    with demo.step("Second thoughts about the name — the row menu can correct it"):
        academics.rename_year(MANAGE_YEAR_NAME, MANAGE_YEAR_RENAMED)
        renamed = academics.year_row(MANAGE_YEAR_RENAMED)
        expect(renamed).to_be_visible(timeout=15_000)
        expect(academics.year_row(MANAGE_YEAR_NAME)).to_have_count(0)
        # A rename PUTs the dates back along with the name, so this is the
        # assertion that catches an edit which quietly dropped the range.
        expect(renamed).to_contain_text(_manage_date_label(MANAGE_YEAR_START))
        expect(renamed).to_contain_text(_manage_date_label(MANAGE_YEAR_END))
        expect(renamed.get_by_text(as_pattern(INACTIVE_BADGE)).first).to_be_visible()

    with demo.step("When the new year comes round, one click makes it the year "
                   "in progress"):
        # Not decoration, and not merely "because the ledger says Activate":
        # the Academic Terms tab is drawn from
        # GET /academic-term/by-year/{active year}, so this is the only way to
        # reach — or to fill — the new year's own term register.
        academics.activate_year(MANAGE_YEAR_RENAMED)
        expect(
            academics.year_row(current_year).get_by_text(as_pattern(INACTIVE_BADGE)).first
        ).to_be_visible(timeout=15_000)

    with demo.step("Its first term runs January to April 2029"):
        # Created current from the start. `get_academic_term_by_year` answers
        # with the year's active term alone, so a term filed inactive is written
        # to the database and then never listed again — see the section comment.
        academics.create_term(
            year_name=MANAGE_YEAR_RENAMED,
            term_name=MANAGE_TERM_NAME,
            start_date=MANAGE_TERM_START,
            end_date=MANAGE_TERM_END,
            set_active=True,
        )
        term_row = academics.term_row(MANAGE_YEAR_RENAMED, MANAGE_TERM_NAME)
        expect(term_row).to_be_visible(timeout=15_000)
        expect(term_row).to_contain_text(_manage_date_label(MANAGE_TERM_START))
        expect(term_row).to_contain_text(_manage_date_label(MANAGE_TERM_END))
        expect(term_row.get_by_text(as_pattern(ACTIVE_BADGE)).first).to_be_visible()

    with demo.step("Terms can be renamed the same way — this one is the Spring term"):
        academics.rename_term(
            MANAGE_YEAR_RENAMED, MANAGE_TERM_NAME, MANAGE_TERM_RENAMED
        )
        renamed_term = academics.term_row(MANAGE_YEAR_RENAMED, MANAGE_TERM_RENAMED)
        expect(renamed_term).to_be_visible(timeout=15_000)
        expect(
            academics.term_row(MANAGE_YEAR_RENAMED, MANAGE_TERM_NAME)
        ).to_have_count(0)
        expect(renamed_term).to_contain_text(_manage_date_label(MANAGE_TERM_START))
        expect(renamed_term).to_contain_text(_manage_date_label(MANAGE_TERM_END))

    with demo.step("Reload: the calendar was written to the school's record, not "
                   "just drawn on screen", dwell_ms=1500):
        # page.tsx updates its tables from each response body without refetching,
        # so until the screen has been rebuilt from GET /academic-year/ and
        # GET /academic-term/by-year/{id} every assertion above is only about
        # optimistic state.
        page.reload()
        academics.expect_loaded()
        expect(academics.year_row(MANAGE_YEAR_RENAMED)).to_be_visible(timeout=20_000)

        academics.show_terms()
        expect(
            academics.term_row(MANAGE_YEAR_RENAMED, MANAGE_TERM_RENAMED)
        ).to_be_visible(timeout=20_000)

    with demo.step(f"Hand the school back to {current_year}, the year it is "
                   f"actually teaching", dwell_ms=1500):
        academics.activate_year(current_year)

        # The school is running exactly the year and term it was before this
        # walkthrough started — which is what the rest of the batch bills and
        # reports against. Read back off a reloaded screen, not off the optimistic
        # state the Activate click left behind.
        page.reload()
        academics.expect_loaded()
        expect(
            academics.year_row(current_year).get_by_text(as_pattern(ACTIVE_BADGE)).first
        ).to_be_visible(timeout=20_000)
        expect(
            academics.year_row(MANAGE_YEAR_RENAMED)
            .get_by_text(as_pattern(INACTIVE_BADGE)).first
        ).to_be_visible(timeout=15_000)

        # …and its own term is untouched: set_active_term only ever deactivates
        # terms of the *same* year, so nothing this unit did could reach it.
        academics.show_terms()
        term_still_current = academics.term_row(current_year, current_term)
        expect(term_still_current).to_be_visible(timeout=20_000)
        expect(
            term_still_current.get_by_text(as_pattern(ACTIVE_BADGE)).first
        ).to_be_visible()


def _manage_date_label(iso: str) -> re.Pattern[str]:
    """How the Start/End Date cells render ``iso`` — date-fns ``"MMM d, yyyy"``.

    Tolerant of one day, deliberately. ``page.tsx`` renders
    ``format(new Date(year.start_date), "MMM d, yyyy")``, and ``new Date()`` on
    a bare "YYYY-MM-DD" parses as UTC midnight while ``format`` prints in the
    *browser's* zone — so on a runner west of Greenwich the cell legitimately
    shows the previous day. The dates this unit asserts are months apart, so
    accepting the neighbouring day costs the assertion nothing and removes a
    whole class of "passes in CI, fails on a laptop".
    """
    day = datetime.strptime(iso, "%Y-%m-%d").date()
    return re.compile("|".join(_manage_date_text(d) for d in (day, day - timedelta(days=1))))


def _manage_date_text(day: date) -> str:
    return re.escape(f"{day:%b} {day.day}, {day.year}")


# ══════════ governance.academic_year_and_term.always_licensed ═══════════════
#
# The mirror image of a denial test, and the unit that replaced
# ``governance.academic_year_and_term.denied``: prove the calendar survives the
# most restricted pack the product can actually build.
#
# Why there is no denial to write instead
#     ``smsfrontend/src/app/module/feature_flag/create/page.tsx`` (and its
#     ``edit/[id]`` twin) declares ``BASIC_GROUPS = ["people", "governance"]``
#     and treats every module in those two groups as mandatory:
#     ``isBasicLockedModule`` renders the checkbox ``locked``, ``toggleModule``
#     returns early for it, ``clearAll`` resets the selection *to* the locked
#     set, and ``handleSave`` refuses outright with "All basic modules (People &
#     Governance) must be selected." ``academic_year_and_term`` sits in the
#     ``governance`` group (``services/feature_pack_service.SYSTEM_MODULE_GROUPS``),
#     so every pack the product can build carries it — the ``minimal`` pack
#     included. Governance being core and always on is intended product
#     behaviour, confirmed 2026-08-09; ``config/module_catalog.MANDATORY_MODULES``
#     is where that decision is recorded, and ``config/feature_scenarios.yaml``
#     now lists the module in the ``minimal`` scenario for the same reason.
#
#     So this unit deliberately asserts *reachability*, and nothing about it is
#     a licensing hole to be closed. In particular nothing here adds or tightens
#     a gate: pointing the calendar routes at ``academic_year_and_term`` (they
#     name ``school_configuration`` today) would be "enforce a gate that was
#     previously unenforced" — a product decision, not a defect fix.
#
# What it therefore checks, on the ``minimal`` school
#     1. the premise — a pack really is assigned, and it carries the module even
#        though this is the floor case;
#     2. the pack is not simply inert here: ``catalogue``, which the builder
#        *does* let a SuperAdmin clear, is absent and really does earn a 403,
#        so "nothing was denied" cannot be read as "feature packs do not bite
#        for this school at all";
#     3. the API answers — both tab fetches, and the read routes behind them;
#     4. the sidebar offers the entry, following it mounts the workspace rather
#        than redirecting to /auth/no-access, and a hand-typed URL behaves the
#        same (middleware.ts only ever sees that second kind of navigation).
#
#     Read-only by design. The create/edit happy path is
#     ``test_school_admin_manages_the_academic_calendar`` above; this unit shares
#     the session-scoped ``provisioned_school`` with the rest of the ``minimal``
#     batch and must hand it back exactly as it found it, so it writes nothing
#     and needs no cleanup fixture.
#
# No branch is selected, deliberately
#     The Governance section of ``nav-config.tsx`` is ``noBranchOnly``, so
#     picking a branch first would remove the very menu entry this unit asserts
#     is offered. Nothing here needs one — an academic year is school-scoped.

LICENSED_SCENARIO = "minimal"
LICENSED_MODULE = "academic_year_and_term"

# A module the pack builder *does* let a SuperAdmin clear — it lives in the
# `library` group, not in the locked `people`/`governance` pair — so the minimal
# pack really does omit it. Probed as the control: without it, "the calendar was
# never denied" would only mean feature packs are unenforced for this school.
LICENSED_CONTROL_MODULE = "catalogue"
LICENSED_CONTROL_ROUTE = "/books/?skip=0&limit=1"

# An id that cannot exist. `has_permission` is solved before the path params are
# validated and long before anything is looked up, so a 404/400/422 from a probe
# using it is itself the proof the licence gate let the request through.
LICENSED_NO_SUCH_ID = 999_999_999


@pytest.mark.school_admin
@pytest.mark.scenario(LICENSED_SCENARIO)
def test_academic_year_and_term_stays_available_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """The calendar is still licensed, still routed and still served on ``minimal``.

    ``academic_year_and_term`` is one of ``config/module_catalog.MANDATORY_MODULES``
    — the pack builder locks the whole ``governance`` group into every pack — so
    the floor-case school must reach it exactly like any other. A failure here
    means the module became excludable (or started being enforced), which is the
    signal to revisit the catalogue and this unit together, not to widen a gate.
    """
    ctx = provisioned_school
    assert LICENSED_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} no longer declares {LICENSED_MODULE!r} "
        f"({sorted(ctx.feature_modules)}). config/feature_scenarios.yaml lists it "
        f"in the floor-case pack precisely because the builder cannot leave it "
        f"out; if that changed, this unit becomes an ordinary denial test."
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The premise: a real pack, carrying the module ──────────────────────
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so nothing "
        f"below says anything about licensing — has_permission treats 'no pack' "
        f"as unrestricted. Provisioning phase A assigns one; check that it did."
    )
    licensed = body.get("modules") or []
    assert LICENSED_MODULE in licensed, (
        f"{ctx.school_name!r} — the most restricted pack the product can build — "
        f"is NOT licensed for {LICENSED_MODULE!r}. The pack builder locks every "
        f"`governance` module in ('All basic modules (People & Governance) must "
        f"be selected'), so this should be impossible through the product. "
        f"Licensed: {sorted(licensed)}"
    )

    # ── 2. The control: the pack is not inert for this school ─────────────────
    assert LICENSED_CONTROL_MODULE not in licensed, (
        f"this unit proves the feature pack is not simply ignored for "
        f"{ctx.school_name!r} by pointing at {LICENSED_CONTROL_MODULE!r}, a module "
        f"the builder does allow to be cleared — but the school is licensed for "
        f"it, so that proof is unavailable. Licensed: {sorted(licensed)}"
    )
    control = api.get(LICENSED_CONTROL_ROUTE, token=token)
    assert control.status_code == 403, (
        f"the pack omits {LICENSED_CONTROL_MODULE!r}, so {LICENSED_CONTROL_ROUTE} "
        f"must answer this SchoolAdmin with 403 — got {control.status_code}: "
        f"{control.text[:300]}. Without that, 'the calendar was never denied' "
        f"would only mean feature packs bite nowhere for this school."
    )
    assert FEATURE_DENIAL_DETAIL.search(control.text), (
        f"{LICENSED_CONTROL_ROUTE} answered 403 for a reason other than the "
        f"licence — got {control.text[:300]}"
    )

    # ── 3. The API answers ────────────────────────────────────────────────────
    #
    # The two fetches the workspace makes on mount, plus the detail reads behind
    # them. Reads only: this school is shared with the rest of the minimal batch.
    years = api.get(
        f"/academic-year/?skip=0&limit=100&school_id={ctx.school_id}", token=token
    )
    assert years.status_code == 200, (
        f"the Academic Years tab fetches GET /academic-year/ on mount; a "
        f"SchoolAdmin of the floor-case school got {years.status_code}: "
        f"{years.text[:300]}"
    )
    if ctx.academic_year:
        names = {str(row.get("name", "")).strip() for row in years.json()}
        assert ctx.academic_year in names, (
            f"the register served to {ctx.school_name!r} does not contain the year "
            f"provisioning created ({ctx.academic_year!r}) — got {sorted(names)}. "
            f"The route answered, but not with this school's calendar."
        )

    reads = {
        "list_terms_by_year": api.get(
            f"/academic-term/by-year/{LICENSED_NO_SUCH_ID}", token=token
        ),
        "year_detail": api.get(f"/academic-year/{LICENSED_NO_SUCH_ID}", token=token),
        "term_detail": api.get(f"/academic-term/{LICENSED_NO_SUCH_ID}", token=token),
    }
    for label, res in reads.items():
        assert res.status_code != 403, (
            f"{label}: the backend refuses a SchoolAdmin of {ctx.school_name!r} "
            f"with {res.status_code}: {res.text[:300]}. The module is licensed on "
            f"this pack, so a licence refusal here means the gate moved."
        )
        assert not FEATURE_DENIAL_DETAIL.search(res.text), (
            f"{label}: answered {res.status_code} carrying the feature-pack "
            f"denial — {res.text[:300]}"
        )

    # ── 4. …and so does the UI ────────────────────────────────────────────────
    login_as(page, frontend_base_url, ctx.school_admin)
    academics = AcademicYearTermPage(page, frontend_base_url)

    # (a) The sidebar offers the entry. The Governance section is noBranchOnly,
    #     and a fresh login has selected no branch, so it renders.
    academics.expect_nav_entry()

    # (b) Following it mounts the workspace rather than bouncing to no-access.
    #     page.tsx returns null while `useModuleGuard("academic_year_and_term")`
    #     is false, so the heading being on screen *is* the guard's answer.
    academics.open_from_nav()
    expect(page).not_to_have_url(NO_ACCESS_URL)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_have_count(0)
    expect(page.get_by_text(as_pattern(PAGE_SUBTITLE))).to_be_visible()

    # (c) Both fetches succeeded, so neither PageError panel is drawn.
    expect(page.get_by_text(as_pattern(YEARS_LOAD_ERROR))).to_have_count(0)
    expect(page.get_by_text(as_pattern(TERMS_LOAD_ERROR))).to_have_count(0)

    # (d) Typing the URL by hand is no different — asserted separately because
    #     middleware.ts only ever sees a hand-typed navigation, and it is the
    #     surface that redirects an unlicensed role to /auth/no-access.
    goto_module(page, frontend_base_url, ACADEMIC_YEAR_ROUTE)
    expect(page.get_by_role("heading", name=as_pattern(HEADING))).to_be_visible(
        timeout=25_000
    )
    expect(page).not_to_have_url(NO_ACCESS_URL)

    # (e) The whole workspace is offered, both tabs and both Create affordances —
    #     a module that is licensed but stripped of its surface would pass every
    #     assertion above and fail here.
    expect(page.get_by_role("button", name=as_pattern(YEARS_TAB_LABEL)).first).to_be_visible()
    expect(page.get_by_role("button", name=as_pattern(TERMS_TAB_LABEL)).first).to_be_visible()
    expect(
        page.get_by_role("button", name=as_pattern(CREATE_YEAR_TRIGGER)).first
    ).to_be_enabled()
    academics.show_terms()
    expect(
        page.get_by_role("button", name=as_pattern(CREATE_TERM_TRIGGER)).first
    ).to_be_enabled()
