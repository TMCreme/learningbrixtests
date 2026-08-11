"""``exams`` — the licensable academics module that ships no workspace.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack
carries just ``school_configuration`` and ``school_admin_dashboard``
(``test_exams_denied_for_school_admin_when_module_disabled``).

View path: a Teacher of the ``academics_only`` school, where the module *is*
licensed and the role *does* hold it — and who still has nothing to open
(``test_teacher_views_exams``). See the section comment above that test for what
a licensed read can honestly assert when the module has no page.

Manage path: none, and that absence is itself asserted by
``test_exams_is_licensed_but_ships_no_management_surface``. The
``academics.exams.manage.school_admin`` unit is recorded BLOCKED in the ledger —
``exams`` has no router, no table and no page, so "create/edit an exam" cannot be
written without building the module. The section comment above that test spells
out the evidence and what will fail here first when the module does get built.

Licensed-but-empty path: the same for a SchoolAdmin, asserted from the API end
too (``test_exams_is_licensed_but_ships_no_management_surface``) — the guard that
stands in for the blocked "manage exams" unit.

Where the denial actually lives
    Nowhere the other academics modules put theirs, so this unit is deliberately
    shaped differently from ``test_attendance.py`` / ``test_assessments.py``.

    * Not in a route guard. ``src/middleware.ts`` gates ``/module/<segment>`` on
      the ``schoolModules`` cookie, but the condition carries ``!isSchoolAdmin``
      ("SchoolAdmin bypasses: governance pages are not feature-flag modules"),
      and ``useModuleGuard``/``usePermissionGuard`` return early for that role
      too. So a SchoolAdmin is never redirected to /auth/no-access here.
    * Not in a role permission either. The seeded SchoolAdmin role *holds*
      ``("manage", "exams")`` — newschoolapp/db/repository/permissions.py — which
      this test re-reads from ``GET /roles/{id}`` rather than assuming, because
      it is the whole point: the permission half of the gate passes and the
      feature-pack half is the only thing standing between this user and an
      exams workspace.
    * Not in a 403 from an exams endpoint, because there is no exams endpoint.
      ``exams`` appears in the backend exclusively as a *gateable module name*
      (services/feature_pack_service.py ``SYSTEM_MODULE_GROUPS``) and as a
      permission (db/repository/permissions.py). No router in newschoolapp/api
      mentions it.
    * Not in a page, because ``smsfrontend/src/app/module/exams/`` does not
      exist. ``config/module_catalog.py`` already records this as
      ``frontend_route=None``, and nav-config.tsx lists ``exams`` only inside the
      Academics section's ``permissionsGate`` — never as an item.

    What is left, and what this test therefore asserts, is the single place the
    licence is actually expressed: ``GET /school_profile/{id}/features``. Every
    downstream guard in the app reads its ``modules`` list (the login page and
    SideNavigation both write it straight into the ``schoolModules`` cookie that
    middleware.ts, ``useModuleGuard``, ``usePermissionGuard`` and
    /auth/no-access all consume), so a school whose features response omits
    ``exams`` is denied everywhere at once.

    The UI half then asserts the consequence rather than re-deriving it: with a
    branch active — the state in which a SchoolAdmin's sidebar is at its *most*
    permissive, since ``canShowItem`` short-circuits on the held permission — the
    navigation still offers no way into ``/module/exams``, and typing the route
    by hand lands on the app's 404 (``src/app/not-found.tsx``) rather than on an
    exams screen.

Reading this test when it fails
    ``exams`` missing from ``/feature-packs/system-modules`` means the backend
    dropped the module; that is a catalogue change, not a denial regression, and
    ``config/module_catalog.py`` needs updating with it. ``exams`` *present* in
    the school's own features list means the ``minimal`` pack was built wrong.
    An exams page rendering at ``/module/exams`` means the module grew a
    workspace, at which point this unit needs a real positive path beside it.
"""
from __future__ import annotations

import json
import re
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

EXAMS_MODULE = "exams"
EXAMS_ROUTE = "exams"
DENIED_SCENARIO = "minimal"

# The role whose permissions are checked against the pack.
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# src/app/not-found.tsx. The apostrophes there are typographic (’), so the
# pattern steps over whatever character sits in that slot.
NOT_FOUND_HEADING = re.compile(r"^\s*404\s*$")
NOT_FOUND_MESSAGE = re.compile(r"page you.{0,3}re looking for doesn.{0,3}t exist", re.I)
# Where the frontend sends a user it has decided is not allowed in.
DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_exams_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `exams` off the pack, a SchoolAdmin is licensed for nothing exams-shaped.

    The role holds ``manage exams`` outright, so the only thing denying them is
    the feature pack — which is read back from the endpoint every guard in the
    frontend derives its answer from.
    """
    ctx = provisioned_school
    if EXAMS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {EXAMS_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    # ── 1. `exams` is a real, licensable module, not a typo in the catalogue ──
    super_token = api.login(
        ctx.super_admin.email, ctx.super_admin.password
    )["access_token"]
    catalogue = api.get("/feature-packs/system-modules", token=super_token)
    assert catalogue.status_code == 200, (
        "the SuperAdmin must be able to read the system module catalogue — got "
        f"{catalogue.status_code}: {catalogue.text[:300]}"
    )
    all_modules = catalogue.json().get("all_modules") or []
    assert EXAMS_MODULE in all_modules, (
        f"{EXAMS_MODULE!r} is no longer a gateable module in the backend "
        f"(services/feature_pack_service.py). The denial below would then be "
        f"vacuous — update config/module_catalog.py and this unit together. "
        f"Catalogue: {sorted(all_modules)}"
    )

    # ── 2. …and the SchoolAdmin role holds it, so permissions do not deny ─────
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert EXAMS_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds an {EXAMS_MODULE!r} "
        f"permission, so this test would be asserting a denial the role gets for "
        f"free. Re-point it at the feature pack only, or fix the seed in "
        f"newschoolapp/db/repository/permissions.py."
    )

    # ── 3. The denial itself: the school's licence omits the module ───────────
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{EXAMS_MODULE!r} proves nothing about the gate. Provisioning phase A "
        f"assigns one — check that it did."
    )
    licensed = body.get("modules") or []
    assert licensed, (
        f"{ctx.school_name!r} reports an empty module list; the "
        f"{ctx.scenario_id!r} pack should carry "
        f"{sorted(ctx.feature_modules)}"
    )
    assert EXAMS_MODULE not in licensed, (
        f"{ctx.school_name!r} is licensed for {EXAMS_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it. "
        f"Every frontend guard reads this list, so the school would be let into "
        f"the module everywhere at once. Licensed: {sorted(licensed)}"
    )

    # ── 4. …and the UI offers no way in, even at maximum sidebar visibility ───
    login_as(page, frontend_base_url, ctx.school_admin)
    if ctx.branches:
        # With a branch active the SchoolAdmin's sidebar renders its module
        # sections (SideNavigation builds `currentUserRole` only once
        # `useBranchStore` is filled), which is the state in which an exams entry
        # would appear if one existed.
        BranchesPage(page, frontend_base_url).select_branch(str(ctx.branches[0]["name"]))

    module_links = page.locator('a[href^="/module/"]')
    expect(module_links.first).to_be_visible(timeout=20_000)
    expect(page.locator('a[href^="/module/exams"]')).to_have_count(0)
    expect(page.get_by_role("link", name=re.compile(r"exam", re.I))).to_have_count(0)

    # Typing the route by hand is the last way in, and the app has no page there.
    goto_module(page, frontend_base_url, EXAMS_ROUTE)
    if not _wait_for_denial(page):
        expect(page.get_by_text(as_pattern(NOT_FOUND_MESSAGE))).to_be_visible()
        expect(page.get_by_text(NOT_FOUND_HEADING).first).to_be_visible()


def _wait_for_denial(page: Page, timeout_ms: int = 20_000) -> bool:
    """Wait for whichever denial surface the app produces; True if it redirected.

    Returns as soon as the page has settled, so a 404 assertion cannot pass — or
    fail — merely because the route was still resolving. ``not-found.tsx`` paints
    "Determining your redirect…" for a beat before the 404 itself, so the wait
    anchors on the message rather than on navigation finishing.
    """
    not_found = page.get_by_text(as_pattern(NOT_FOUND_MESSAGE)).first
    step = 500
    remaining = timeout_ms
    while remaining > 0:
        if DENIAL_URL.search(page.url):
            return True
        if not_found.count() > 0:
            return False
        page.wait_for_timeout(step)
        remaining -= step

    raise AssertionError(
        f"/module/{EXAMS_ROUTE} neither redirected to a no-access page nor "
        f"rendered the app's 404 within {timeout_ms}ms — current url "
        f"{page.url!r}. If an exams workspace rendered instead, the module has "
        f"grown a page and this unit needs a positive path written beside it."
    )


# ───────────── view path: the licensed teacher, and the empty licence ─────────
#
# Same module, opposite school: the ``academics_only`` pack DOES license
# ``exams``, and the seeded Teacher role holds ``("manage", "exams")``
# (newschoolapp/db/repository/permissions.py). Both halves of
# ``utils.permissions.has_permission`` therefore say yes — and the teacher still
# has no exams screen to read, because the app ships none (see the module
# docstring: no route in newschoolapp/api, no directory under
# smsfrontend/src/app/module/, no entry in nav-config.tsx).
#
# So "Teacher views exams" cannot be written as "open the workspace and read it".
# What it *can* assert — and what this unit does — is the complete, observable
# state of a granted exams licence for the one role the ledger names:
#
#   * The licence really is granted, in the two places the app reads it from:
#     ``GET /school_profile/{id}/features`` (which SideNavigation and the login
#     page both call) and the ``schoolModules`` cookie those two write, which is
#     what ``src/middleware.ts`` gates every ``/module/*`` request on.
#   * The role really does hold the permission, read back from ``GET /roles/{id}``
#     rather than assumed — otherwise the walk below would be proving a denial
#     the teacher gets for a different reason entirely.
#   * Because both hold, /module/exams is NOT a denial for this teacher. A
#     Teacher is not exempt from the middleware module gate the way a SchoolAdmin
#     is (``!isSchoolAdmin`` in the condition), so a teacher of an unlicensed
#     school is bounced to /auth/no-access. This one is let straight through —
#     and lands on the app's own 404 (``src/app/not-found.tsx``). "Not built" and
#     "not allowed" are different screens, and which one appears is the whole
#     result of this test.
#   * Meanwhile the Academics menu they *do* get renders its licensed workspaces
#     and offers no way into exams at all.
#
# If this unit ever fails on its 404 because an exams page rendered instead, that
# is the good failure: the module grew a workspace, and this test should be
# rewritten to read it.

VIEW_SCENARIO = "academics_only"
TEACHER_ROLE = "Teacher"

# nav-config.tsx — the Academics section header, plus two entries this teacher
# holds. They are asserted visible so that "no Exams entry" cannot pass on a
# sidebar that simply never rendered.
NAV_SECTION_ACADEMICS = re.compile(r"^\s*Academics Module\s*$", re.I)
NAV_SUBJECTS = re.compile(r"^\s*Subject\s*&\s*Topic\s*$", re.I)
NAV_ATTENDANCE = re.compile(r"^\s*Attendance\s*$", re.I)
# Anything exams-shaped, however it were labelled.
NAV_ANY_EXAM = re.compile(r"exam", re.I)

# The cookie every frontend gate derives its answer from, written by
# src/app/auth/login/page.tsx and refreshed by SideNavigation.
MODULES_COOKIE = "schoolModules"


@pytest.mark.teacher
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.exams.view.teacher",
    title="Exams",
    # Deliberately not "Teacher views exams": there is no exams view in the app,
    # and captioning the footage that way would promise the viewer a screen that
    # is never going to appear. Same call as
    # test_guardian_is_denied_the_attendance_register.
    subtitle="A teacher's exams licence has no workspace to open",
)
def test_teacher_views_exams(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A licensed teacher is refused nothing about exams — and shown nothing either.

    The read this unit performs is of the licence itself, on every surface the
    app exposes it: the features endpoint, the ``schoolModules`` cookie the
    middleware gates on, the role's own permission list, and the sidebar. The
    conclusion they add up to is asserted on the route: the app's 404, never
    /auth/no-access.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert EXAMS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {EXAMS_MODULE!r} for this unit "
        f"— the point is that nothing denies this teacher, so a school without "
        f"the module would make every assertion below mean the opposite"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    teacher = ctx.teacher

    with demo.step(
        f"Sign in as {teacher.full_name}, a teacher at {ctx.school_name}",
        dwell_ms=2500,
    ):
        login_as(page, base_url, teacher)

    with demo.step(
        "Their school is licensed for the Academics modules, exams included",
        dwell_ms=2500,
    ):
        expect(page.get_by_text(NAV_SECTION_ACADEMICS).first).to_be_visible(
            timeout=20_000
        )
        licensed = _licensed_modules(api, ctx)
        assert EXAMS_MODULE in licensed, (
            f"{ctx.school_name!r} reports no {EXAMS_MODULE!r} licence even though "
            f"the {ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) carries "
            f"it. Every guard in the frontend reads this list, so the teacher "
            f"below would be refused for the wrong reason. Licensed: "
            f"{sorted(licensed)}"
        )

    with demo.step(
        "The Academics menu opens the workspaces the school actually ships",
        dwell_ms=2000,
    ):
        expect(page.get_by_role("link", name=NAV_SUBJECTS).first).to_be_visible(
            timeout=20_000
        )
        expect(page.get_by_role("link", name=NAV_ATTENDANCE).first).to_be_visible()

    with demo.step("Exams is not one of them — there is no entry to click", dwell_ms=2500):
        expect(page.locator(f'a[href^="/module/{EXAMS_ROUTE}"]')).to_have_count(0)
        expect(page.get_by_role("link", name=NAV_ANY_EXAM)).to_have_count(0)

    with demo.step("Ask for the exams workspace by name instead", dwell_ms=2000):
        goto_module(page, base_url, EXAMS_ROUTE)

    with demo.step(
        "The app has nothing to show there — a 404, not a locked door", dwell_ms=3000
    ):
        redirected = _wait_for_denial(page)
        assert not redirected, (
            f"a teacher of {ctx.school_name!r} was sent to {page.url!r}. The school "
            f"IS licensed for {EXAMS_MODULE!r} and the {TEACHER_ROLE} role holds it, "
            f"so middleware.ts should have let this request through — a no-access "
            f"redirect here means the module gate is refusing a licensed module."
        )
        expect(page.get_by_text(as_pattern(NOT_FOUND_MESSAGE))).to_be_visible()
        expect(page.get_by_text(NOT_FOUND_HEADING).first).to_be_visible()

    with demo.step(
        "Nothing turned them away: the licence and the role both said yes",
        dwell_ms=3000,
    ):
        # The middleware gate is only meaningful if the browser was carrying a
        # module list at all — without the cookie the condition short-circuits and
        # the 404 above would prove nothing about licensing.
        cookie_modules = _school_modules_cookie(page)
        assert cookie_modules is not None, (
            f"the {MODULES_COOKIE!r} cookie was never written for this session, so "
            f"src/middleware.ts skipped its module gate entirely and the route "
            f"above was never actually licence-checked. Both "
            f"src/app/auth/login/page.tsx and SideNavigation are meant to set it."
        )
        assert EXAMS_MODULE in cookie_modules, (
            f"the session carries {sorted(cookie_modules)} as its licensed modules, "
            f"without {EXAMS_MODULE!r} — so the teacher reached the 404 only "
            f"because middleware happened not to refuse them, not because the "
            f"module is licensed. The cookie is out of step with "
            f"/school_profile/{ctx.school_id}/features."
        )

        role_modules = _role_modules(api, TEACHER_ROLE)
        assert EXAMS_MODULE in role_modules, (
            f"the seeded {TEACHER_ROLE} role no longer holds an {EXAMS_MODULE!r} "
            f"permission, so this unit would be asserting the emptiness of a "
            f"licence the role cannot use anyway. Fix the seed in "
            f"newschoolapp/db/repository/permissions.py, or re-point this test."
        )


def _licensed_modules(api: BackendAPI, ctx: SchoolContext) -> list[str]:
    """The modules the school's own features endpoint reports, read as the teacher.

    Read with the teacher's token on purpose: this is the exact call SideNavigation
    makes on their behalf, and a 403 here would mean the sidebar could never learn
    what the school is licensed for.
    """
    assert ctx.teacher is not None
    token = api.login(ctx.teacher.email, ctx.teacher.password)["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a teacher must be able to read their own school's features — the "
        f"sidebar calls this on every mount — got {features.status_code}: "
        f"{features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so nothing "
        f"below is testing a licence. Provisioning phase A assigns one."
    )
    return [str(m) for m in (body.get("modules") or [])]


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


# ────────────── licensed path: the module that grants nothing ────────────────
#
# This is where ``academics.exams.manage.school_admin`` — "SchoolAdmin creates
# and manages exams" — would live, and the reason it cannot be written as a
# create/edit happy path. The unit is recorded BLOCKED in the ledger; this test
# is the guard that will tell whoever unblocks it that the situation changed.
#
# The `academics_only` pack DOES license `exams`, and the seeded SchoolAdmin
# role DOES hold ("manage", "exams"). Both halves of the gate therefore pass —
# and there is still nothing to manage, because `exams` is implemented nowhere
# but in the two lists that name it:
#
#   * newschoolapp/services/feature_pack_service.py  — a gateable module name
#   * newschoolapp/db/repository/permissions.py      — a role permission
#
# There is no `newschoolapp/api/routes/exam*.py`, no exams table, and no
# `smsfrontend/src/app/module/exams/` (verified: the only three frontend files
# that mention "exams" are the permission enum, the access-roles module map, and
# the Academics section's `permissionsGate` in nav-config.tsx — never a nav
# item, never an href). Writing a create/edit walkthrough would mean building
# the module: new tables plus a migration, a router, and a workspace. That is
# product scope, not a defect to fix in place, so it is escalated rather than
# invented — a green "manage exams" test driving some *other* module's screens
# would be worse than no test at all.
#
# What is asserted instead is the exact shape of the gap, from both ends, so
# that the day exams grows a surface this fails loudly and points at the unit
# that needs writing.

MANAGE_SCENARIO = "academics_only"

# Every path an exams API could plausibly have been mounted on. FastAPI matches
# the route before it authenticates, so an *unregistered* path answers 404 "Not
# Found" whatever token is presented — which is how "there is no router" is told
# apart from "the router refused me" (403) or "my token is bad" (401). This is
# the assertion that will fail first the day someone builds the module.
CANDIDATE_EXAM_ROUTES = (
    "/exams/",
    "/exams",
    "/exam/",
    "/examinations/",
)
NOT_FOUND_DETAIL = re.compile(r"^\s*not found\s*$", re.I)

# The other Academics entries this SchoolAdmin does hold, asserted visible so
# that "no Exams entry" cannot pass on a sidebar that simply never rendered.
NAV_CLASSES = re.compile(r"^\s*Classes\s*&\s*Timetables\s*$", re.I)


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.exams.manage.school_admin",
    title="Exams",
    # Deliberately not "SchoolAdmin creates and manages exams": there is nothing
    # to create, and captioning the footage that way would promise the viewer a
    # workspace that never appears. Same call as test_teacher_views_exams above.
    subtitle="A SchoolAdmin's exams licence has nothing to manage",
)
def test_exams_is_licensed_but_ships_no_management_surface(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """`exams` is licensed and permitted, and still has nowhere to be managed.

    Both halves of the gate pass for this SchoolAdmin — the pack licenses the
    module and the seeded role holds ``("manage", "exams")`` — so anything they
    cannot do here is not an access failure, it is an absence. The unit
    ``academics.exams.manage.school_admin`` is recorded blocked on that absence;
    see the section comment above.

    The walkthrough is the SchoolAdmin half of what ``test_teacher_views_exams``
    proves for a teacher, plus the one thing a read-only role could not check:
    that no exams endpoint exists behind the missing screen either, so there is
    no create or edit to reach even with a token in hand.
    """
    ctx = provisioned_school
    assert EXAMS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {EXAMS_MODULE!r} for this unit "
        f"— without the licence every absence below is an ordinary denial, which "
        f"test_exams_denied_for_school_admin_when_module_disabled already covers"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    admin = ctx.school_admin

    with demo.step(
        f"Sign in as {admin.full_name}, who administers {ctx.school_name}",
        dwell_ms=2500,
    ):
        login_as(page, base_url, admin)

    with demo.step("Open the campus whose academics they manage", dwell_ms=2000):
        # `branchOnly: true` on the Academics section: a SchoolAdmin belongs to no
        # branch, so the section only renders once `useBranchStore` is filled —
        # and only the branch row's "View" button fills it. Skip this and the menu
        # is hidden for a reason that has nothing to do with exams.
        assert ctx.branches, (
            "provisioning left this school with no branch, so the Academics menu "
            "cannot render at all and nothing below would be about exams"
        )
        BranchesPage(page, base_url).select_branch(str(ctx.branches[0]["name"]))
        # select_branch always routes to /module/community, which this pack does
        # not license — its 403 hard-redirects to /auth/no-access, a page with no
        # sidebar at all. Asserting the menu on whatever it happened to land on
        # made this test fail for a reason that has nothing to do with exams.
        # Land somewhere the pack *does* license before reading the sidebar.
        goto_module(page, base_url, "subjects")
        expect(page.get_by_text(NAV_SECTION_ACADEMICS).first).to_be_visible(
            timeout=20_000
        )

    with demo.step("Their plan includes Exams, and their role can manage it", dwell_ms=2500):
        token = api.login(admin.email, admin.password)["access_token"]
        features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
        assert features.status_code == 200, (
            f"a SchoolAdmin must be able to read their own school's features — "
            f"the sidebar calls this on every mount — got "
            f"{features.status_code}: {features.text[:300]}"
        )
        body = features.json()
        assert body.get("pack_assigned") is True, (
            f"{ctx.school_name!r} has no feature pack assigned at all, so nothing "
            f"below is testing a licence. Provisioning phase A assigns one."
        )
        licensed = [str(m) for m in (body.get("modules") or [])]
        assert EXAMS_MODULE in licensed, (
            f"the {ctx.scenario_id!r} pack is supposed to license {EXAMS_MODULE!r} "
            f"(config/feature_scenarios.yaml) but {ctx.school_name!r} reports "
            f"{sorted(licensed)}"
        )
        assert EXAMS_MODULE in _role_modules(api, SCHOOL_ADMIN_ROLE), (
            f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds an "
            f"{EXAMS_MODULE!r} permission (newschoolapp/db/repository/"
            f"permissions.py), so this administrator is denied for an ordinary "
            f"reason and this unit no longer describes the gap it was written for."
        )

    with demo.step(
        "The Academics menu opens the workspaces the school actually ships",
        dwell_ms=2000,
    ):
        expect(page.get_by_role("link", name=NAV_SUBJECTS).first).to_be_visible(
            timeout=20_000
        )
        expect(page.get_by_role("link", name=NAV_CLASSES).first).to_be_visible()
        expect(page.get_by_role("link", name=NAV_ATTENDANCE).first).to_be_visible()

    with demo.step(
        "Exams is not one of them — there is nothing here to create or edit",
        dwell_ms=2500,
    ):
        expect(page.locator(f'a[href^="/module/{EXAMS_ROUTE}"]')).to_have_count(0)
        expect(page.get_by_role("link", name=NAV_ANY_EXAM)).to_have_count(0)

    with demo.step("Ask for the exams workspace by name instead", dwell_ms=2000):
        goto_module(page, base_url, EXAMS_ROUTE)

    with demo.step(
        "The app has nothing to show there — a 404, not a locked door", dwell_ms=3000
    ):
        redirected = _wait_for_denial(page)
        assert not redirected, (
            f"a SchoolAdmin of {ctx.school_name!r} was sent to {page.url!r}. The "
            f"school IS licensed for {EXAMS_MODULE!r} and the role holds it, so a "
            f"no-access redirect here would mean a licensed module is being "
            f"refused rather than simply being unbuilt."
        )
        expect(page.get_by_text(as_pattern(NOT_FOUND_MESSAGE))).to_be_visible()
        expect(page.get_by_text(NOT_FOUND_HEADING).first).to_be_visible()

    with demo.step(
        "And no exams API behind it either — the module is licensable, not built",
        dwell_ms=3000,
    ):
        for route in CANDIDATE_EXAM_ROUTES:
            res = api.get(route, token=token)
            assert res.status_code == 404, (
                f"{route} answered {res.status_code}, not 404 — the backend has "
                f"grown an exams surface. `academics.exams.manage.school_admin` "
                f"is blocked precisely because it had none: unblock it and write "
                f"the create/edit walkthrough against this router. Body: "
                f"{res.text[:300]}"
            )
            detail = str((res.json() or {}).get("detail", ""))
            assert NOT_FOUND_DETAIL.search(detail), (
                f"{route} returned 404 but with detail {detail!r}. A 404 from a "
                f"*registered* route (a missing exam record) would mean the "
                f"router exists after all — re-check before trusting this."
            )
