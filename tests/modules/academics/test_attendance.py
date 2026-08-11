"""/module/attendance — the attendance register.

Read-only path: a SchoolAdmin of the ``academics_only`` school reads the daily
register and the month calendar without marking anybody
(``test_school_admin_views_attendance``).

Guardian path: a Guardian of that same ``academics_only`` school — where the
module IS licensed — is nonetheless refused the register, because the seeded
Guardian role holds no attendance permission at all
(``test_guardian_is_denied_the_attendance_register``). See the section comment
above that test for why the app has no guardian-facing attendance view to walk
through, and which three surfaces the denial is asserted on.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack does
NOT include ``attendance``
(``test_attendance_denied_for_school_admin_when_module_disabled``).

Where the denial actually lives
    Not in the router, and not in the sidebar. Both frontend guards
    (``useModuleGuard``/``usePermissionGuard``) and ``src/middleware.ts``
    deliberately let a SchoolAdmin through every module gate — "SchoolAdmin
    bypasses: governance pages are not feature-flag modules" — so navigating
    straight to /module/attendance neither redirects to /auth/no-access nor
    renders the "unauthorized" page. The seeded SchoolAdmin role also *holds*
    ``("manage", "attendance")`` (newschoolapp/db/repository/permissions.py), so
    the permission half of the backend gate passes too.

    What actually denies them is the feature-pack half of
    ``utils.permissions.has_permission``: every ``/attendance`` route answers
    **403 "Feature not available in your plan"**. That 403 is the assertion this
    test is built on.

    The UI consequence follows from it: the page mounts and every fetch it makes
    is refused. Which panel that leaves on screen depends on *which* fetch failed
    first — ``page.tsx`` routes a 403 from ``fetchData`` to ``classAccessDenied``
    (the in-page ``NoClassAccess`` panel) but a failure in ``initData`` to
    ``fetchError`` (the full-screen ``PageError``). The test accepts either, plus
    a redirect, and asserts on what holds in all three: no register rows, no
    "View All Attendance", no "Export Data". So a regression that silently starts
    serving attendance to an unlicensed school fails here.
"""
from __future__ import annotations

import re
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import (
    BRANCH_ADDRESS,
    BRANCH_NAME,
    BRANCH_PHONE,
    CLASS_NAME,
    SchoolContext,
)
from tests.pages.academics.attendance import COLUMN, AttendancePage
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

ATTENDANCE_MODULE = "attendance"
ATTENDANCE_ROUTE = "attendance"

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIAL_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# Real strings from src/app/module/attendance/page.tsx.
REGISTER_HEADING = re.compile(r"Attendance Management", re.I)
VIEW_ALL_BUTTON = re.compile(r"View All Attendance", re.I)
EXPORT_BUTTON = re.compile(r"Export Data", re.I)
# src/components/common/PageError.tsx, mounted with this exact title.
LOAD_FAILURE_TITLE = re.compile(r"Failed to load attendance data", re.I)
# components/NoClassAccess.tsx — the in-page panel the register swaps its table
# for when the /attendance reads come back 403. page.tsx catches that status
# specially (``setClassAccessDenied(true)``) instead of routing it to fetchError,
# so it is a *different* surface from the PageError panel above, not a variant.
NO_ACCESS_PANEL = re.compile(
    r"No Attendance Access|No Class Assigned to You", re.I
)
# Where the frontend sends a user it has decided is not allowed in.
DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")

# The floor pack. ``minimal`` is the only scenario that both omits `attendance`
# and is a pack the product can really build (config/feature_scenarios.yaml), so
# it is the one school this denial is worth provisioning against — the marker
# deselects the other four `provisioned_school` params rather than walking each
# of them through a full UI provisioning run to reach a skip.
DENIED_SCENARIO = "minimal"


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_attendance_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `attendance` off the pack, a SchoolAdmin gets no register and no data."""
    ctx = provisioned_school
    assert ATTENDANCE_MODULE not in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} licenses {ATTENDANCE_MODULE!r}, so there is "
        f"no denial here to assert. This unit is pinned to {DENIED_SCENARIO!r}; if "
        f"that pack has gained the module, the unit needs a different scenario "
        f"rather than a silent skip"
    )

    # ── the denial itself: every attendance route is refused ──────────────────
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    refusals = {
        "list": api.get("/attendance/?skip=0&limit=10", token=token),
        "stats": api.get(
            f"/attendance/stats/summary?attendance_date={date.today().isoformat()}",
            token=token,
        ),
        "mark": api.post(
            "/attendance/",
            token=token,
            json={
                "student_id": 1,
                "class_id": 1,
                "attendance_date": date.today().isoformat(),
                "status": "present",
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{ATTENDANCE_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── and the UI never puts a register in front of them ─────────────────────
    login_as(page, frontend_base_url, ctx.school_admin)
    goto_module(page, frontend_base_url, ATTENDANCE_ROUTE)

    # A SchoolAdmin is exempt from the frontend's own module gate, so the page is
    # expected to mount and fail its fetches rather than redirect. Accept the
    # redirect too — it is the stronger denial, not a weaker one.
    surface = _wait_for_denial(page)

    # True on every surface: no register data, and none of the controls that act
    # on it. Both buttons are rendered behind ``!classAccessDenied``, so they are
    # gone in the in-page panel case as well as the other two.
    expect(page.get_by_role("button", name=as_pattern(VIEW_ALL_BUTTON))).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(EXPORT_BUTTON))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)

    if surface == "no_access_panel":
        # The page chrome (its <h1>) still renders here — the denial is the panel
        # that replaced AttendanceTable, so that is what gets asserted.
        expect(page.get_by_text(as_pattern(NO_ACCESS_PANEL)).first).to_be_visible()
        return

    # PageError and the redirect both unmount the register entirely, heading and
    # all, so nothing of it may be on screen.
    expect(page.get_by_text(as_pattern(REGISTER_HEADING))).to_have_count(0)
    if surface == "load_failure":
        expect(page.get_by_text(as_pattern(LOAD_FAILURE_TITLE)).first).to_be_visible()


def _wait_for_denial(page: Page, timeout_ms: int = 20_000) -> str:
    """Wait for whichever denial surface the app produces, and name it.

    Returns as soon as the page has settled into one of them, so the "register is
    absent" assertions cannot pass merely because the page had not finished
    loading yet. There are three, and which one appears is not this test's
    business to pin down — only that one of them did:

    ``"redirect"``
        ``useModuleGuard``/``usePermissionGuard`` pushed to /auth/no-access or
        /unauthorized. Not expected for a SchoolAdmin (both guards exempt the
        role outright) but accepted: it is a stricter denial, not a weaker one.
    ``"load_failure"``
        ``initData``'s own fetches were refused, so ``fetchError`` is set and
        ``PageError`` replaces the whole screen.
    ``"no_access_panel"``
        ``fetchData`` got its 403 and set ``classAccessDenied``, so the register
        keeps its header but swaps the table for ``NoClassAccess``.
    """
    failure = page.get_by_text(as_pattern(LOAD_FAILURE_TITLE)).first
    panel = page.get_by_text(as_pattern(NO_ACCESS_PANEL)).first
    deadline = timeout_ms
    step = 500
    while deadline > 0:
        if DENIAL_URL.search(page.url):
            return "redirect"
        if failure.count() > 0:
            return "load_failure"
        if panel.count() > 0:
            return "no_access_panel"
        page.wait_for_timeout(step)
        deadline -= step

    raise AssertionError(
        "/module/attendance produced none of the three denials the app "
        "implements — no redirect to a no-access page, no load-failure panel and "
        f"no NoClassAccess panel within {timeout_ms}ms; current url {page.url!r}. "
        "If the register rendered instead, the feature-pack gate is not being "
        "enforced for this school."
    )


# ─────────────────── read-only path: SchoolAdmin views ───────────────────────

VIEW_SCENARIO = "academics_only"

# The sidebar entry for this module (SideNavigation/nav-config.tsx), under the
# "Academics Module" group.
NAV_ATTENDANCE = re.compile(r"^\s*Attendance\s*$", re.I)
NAV_SECTION_ACADEMICS = re.compile(r"^\s*Academics Module\s*$", re.I)

# Where a SchoolAdmin picks the menu back up after choosing a branch — see
# _open_from_academics_menu for why they cannot simply click on from where
# select_branch left them. `home` is licensed on this pack.
HOME_ROUTE = "home"

# Every status badge AttendanceTable can render, including the "Not Marked"
# fallback it uses for a student with no record on the selected date. Asserted
# as an alternation rather than as "Not Marked" so the test still reads the
# register correctly on a day somebody *has* been marked.
STATUS_BADGE = re.compile(
    r"^\s*(Present|Absent|Late|Excused|Half Day|Not Marked)\s*$", re.I
)


@pytest.mark.school_admin
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.attendance.view.school_admin",
    title="Attendance",
    subtitle="SchoolAdmin views attendance",
)
def test_school_admin_views_attendance(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin reads the day's register and the month calendar, and writes nothing.

    The read *is* the feature. ``GET /attendance/``, ``GET /attendance/stats/summary``
    and ``GET /students/`` are all branch-scoped for this role, so the assertions
    are that each surface renders its own content — the seven-tile summary, the
    register's own columns, and either real student rows or the table's empty
    state — rather than the ``PageError`` panel the page falls back to when any
    of those fetches is refused.

    "Export Data" and the row menu's Mark Attendance / Check In / Check Out are
    deliberately not asserted absent: the seeded SchoolAdmin role holds
    ``("manage", "attendance")``, so those controls are expected to be there.
    This test simply never presses them.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    attendance = AttendancePage(page, base_url)
    student_name = ctx.student.full_name
    this_month = date.today().strftime("%B %Y")

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step("Choose the campus whose register to review"):
        _activate_branch(page, base_url, ctx)

    with demo.step("Open Attendance from the Academics menu"):
        _open_from_academics_menu(page, base_url, attendance)

    with demo.step("Read today's register for the whole campus"):
        attendance.expect_stats()
        attendance.expect_columns()
        attendance.wait_for_rows()
        attendance.expect_no_load_failure()

    with demo.step("The register already follows the active academic year and term"):
        if ctx.academic_year:
            attendance.expect_filter_shows(ctx.academic_year)
        if ctx.current_term:
            attendance.expect_filter_shows(ctx.current_term)

    with demo.step(f"Narrow the register down to {CLASS_NAME}"):
        attendance.filter_by_class(CLASS_NAME)
        attendance.expect_no_load_failure()

    with demo.step(f"Look up {student_name} and read the day's status"):
        attendance.search(ctx.student.first_name)
        expect(attendance.find_row(student_name)).to_be_visible(timeout=20_000)
        expect(attendance.cell(student_name, COLUMN["class"])).to_have_text(
            _exact_text(CLASS_NAME)
        )
        expect(attendance.cell(student_name, COLUMN["status"])).to_have_text(STATUS_BADGE)
        attendance.expect_no_load_failure()

    with demo.step("Open the calendar overview of every recorded day", dwell_ms=1500):
        attendance.open_view_all()
        attendance.expect_calendar_grid(this_month)


def _open_from_academics_menu(
    page: Page, base_url: str, attendance: AttendancePage
) -> None:
    """Reach the register the way an administrator does — off the sidebar.

    Not a stylistic preference: this unit records video, and the footage has to
    show how a real user gets to the register rather than cutting to its URL.

    The detour through ``/module/home`` is what makes that possible. Picking a
    branch is a prerequisite here (see ``_activate_branch``), and
    ``BranchesPage.select_branch`` ends on a hardcoded push to
    ``/module/community``; the ``academics_only`` pack does not license
    community, so that fetch answers 403 "Feature not available in your plan"
    and ``utils/handleErrorMessage.ts`` turns it into a hard redirect to
    ``/auth/no-access`` — a route under ``app/auth/layout.tsx``, which renders no
    sidebar at all. Clicking straight on from there is impossible, and a bare
    "is the link on screen?" check would silently fall through to a deep link
    every single run. ``/module/home`` is licensed on this pack, sits under the
    module layout, and is the first entry of the very menu that carries
    Attendance.

    The sidebar's "Academics Module" section is ``branchOnly: true``
    (nav-config.tsx), so it only renders once the branch store is filled — which
    is why the section heading is asserted before the entry: a missing link
    there means the branch selection did not take, not that attendance is
    hidden.
    """
    goto_module(page, base_url, HOME_ROUTE)
    expect(page.get_by_text(NAV_SECTION_ACADEMICS).first).to_be_visible(timeout=30_000)

    # Scoped to the sidebar: each nav-config section renders its own <nav>, and
    # a page-wide "Attendance" match could land on page chrome instead of on the
    # menu entry.
    link = page.get_by_role("navigation").get_by_role(
        "link", name=as_pattern(NAV_ATTENDANCE)
    ).first
    expect(link).to_be_visible(timeout=30_000)
    link.click()

    page.wait_for_url(re.compile(rf"/module/{ATTENDANCE_ROUTE}"), timeout=30_000)
    attendance.expect_loaded()


def _activate_branch(page: Page, base_url: str, ctx: SchoolContext) -> str:
    """Give the SchoolAdmin an active branch, and return its name.

    Mandatory before *reading* anything here, not just before writing: a
    SchoolAdmin belongs to no branch, ``GET /attendance/stats/summary`` answers
    400 BRANCH_ID_REQUIRED without one (api/routes/attendance.py::
    get_attendance_stats), and the frontend only sends ``branch_id`` when
    ``useBranchStore`` is filled — which only the branch row's "View" button
    does.

    Provisioning normally leaves one behind on ``ctx.branches``; the create is a
    fallback for a school whose phase B skipped it, so this unit does not fail
    for a reason that has nothing to do with attendance.
    """
    branches = BranchesPage(page, base_url).open()
    name = str(ctx.branches[0]["name"]) if ctx.branches else ""

    if not name or branches.find_row(name).count() == 0:
        name = f"TEST {BRANCH_NAME} {run_tag()}"
        branches.create_branch(name=name, address=BRANCH_ADDRESS, phone=BRANCH_PHONE)

    branches.select_branch(name)
    return name


def _exact_text(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)


# ──────────────── read-only path: Guardian is kept out of it ─────────────────
#
# Same route, same licensed school as the SchoolAdmin read above — but the gate
# here is the role, not the feature pack. The seeded Guardian role holds only
# ``read home``, ``manage messaging``, ``read lessons``, ``read student_scores``,
# ``read families`` and ``read reports`` (newschoolapp/db/repository/
# permissions.py), so it holds neither ``("read", "attendance")`` nor
# ``("manage", "attendance")``.
#
# That is deliberate product behaviour, not a gap this unit should "fix": the
# register is a staff instrument — it lists every student in a class and records
# their marks — and a parent learns about their own ward's absence from
# services/attendance_notifications.py, which emails the guardians of a student
# marked absent. There is no guardian-facing attendance screen anywhere in the
# frontend (GuardianView lists wards; /module/home/[guardianward] shows Basic
# Info / Contact / Academic and no attendance tab), so the read-only truth for
# this role is the denial, asserted on all three surfaces at once:
#
#   * the sidebar never offers "Attendance" — SideNavigation's ``canShowItem``
#     resolves that entry on its ``permission: "attendance"`` gate, which a
#     Guardian fails;
#   * typing the route in anyway lands on /unauthorized — ``middleware.ts`` lets
#     them through (the school *is* licensed for the module, so the module gate
#     has nothing to refuse) and ``usePermissionGuard("attendance")`` is what
#     pushes them out;
#   * and every /attendance route answers 403 "You do not have permission to
#     perform this action" — the permission half of
#     ``utils.permissions.has_permission`` refuses before the feature-pack half
#     is ever reached.

# The neighbouring Academics entry a Guardian *does* hold (read lessons). It is
# asserted visible so that "no Attendance entry" cannot pass on a sidebar that
# simply never rendered.
NAV_LESSONS = re.compile(r"^\s*Lessons\s*$", re.I)

# GuardianView.tsx — the heading over the wards table on the guardian home page.
GUARDIAN_HOME_HEADING = re.compile(r"Your Ward\(s\)", re.I)

# src/app/unauthorized/page.tsx, where usePermissionGuard sends them.
UNAUTHORIZED_URL = re.compile(r"/unauthorized")
ACCESS_DENIED_HEADING = re.compile(r"Access Denied", re.I)

# The one denial utils/permissions.py can answer with here: the school holds the
# module, so it is the role that is refused, never the plan.
ROLE_DENIAL_DETAIL = re.compile(
    r"You do not have permission to perform this action", re.I
)


@pytest.mark.guardian
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.attendance.view.guardian",
    title="Attendance",
    subtitle="Guardian is kept out of the attendance register",
)
def test_guardian_is_denied_the_attendance_register(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A parent of the licensed school gets no register, by menu or by URL.

    The subtitle deliberately does not read "Guardian views attendance": the app
    implements no such view (see the section comment above), and captioning the
    footage that way would describe a screen the viewer is never going to see.
    """
    ctx = provisioned_school
    assert ctx.guardian is not None, "provisioning created no guardian for this school"
    assert ATTENDANCE_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {ATTENDANCE_MODULE!r} for this "
        f"unit — the point is that the Guardian is refused on their *role*, with "
        f"the feature pack having nothing to say about it"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    guardian = ctx.guardian

    # Every step here is an assertion rather than an interaction, so the actions
    # themselves take almost no wall-clock time. Without an explicit dwell the six
    # captions would land inside ~4s of footage — most of it under the title card —
    # and none of them would be readable. The dwell only ever applies to demo runs.
    with demo.step(
        f"Sign in as {guardian.full_name}, a parent at {ctx.school_name}",
        dwell_ms=3000,
    ):
        login_as(page, base_url, guardian)

    with demo.step(
        "A parent lands on their own home page, listing their wards", dwell_ms=2500
    ):
        expect(page.get_by_text(as_pattern(GUARDIAN_HOME_HEADING)).first).to_be_visible(
            timeout=20_000
        )

    with demo.step(
        "Their Academics menu offers Lessons, but never the Attendance register",
        dwell_ms=2500,
    ):
        expect(page.get_by_role("link", name=as_pattern(NAV_LESSONS)).first).to_be_visible(
            timeout=20_000
        )
        expect(page.get_by_role("link", name=as_pattern(NAV_ATTENDANCE))).to_have_count(0)

    with demo.step(
        "Try the register anyway, straight from the address bar", dwell_ms=2000
    ):
        goto_module(page, base_url, ATTENDANCE_ROUTE)

    with demo.step(
        "The app turns the parent away — the class register is staff-only",
        dwell_ms=2500,
    ):
        page.wait_for_url(UNAUTHORIZED_URL, timeout=20_000)
        expect(page.get_by_text(as_pattern(ACCESS_DENIED_HEADING)).first).to_be_visible()

        expect(page.get_by_text(as_pattern(REGISTER_HEADING))).to_have_count(0)
        expect(page.get_by_role("button", name=as_pattern(VIEW_ALL_BUTTON))).to_have_count(0)
        expect(page.get_by_role("button", name=as_pattern(EXPORT_BUTTON))).to_have_count(0)
        expect(page.get_by_role("row")).to_have_count(0)

    with demo.step(
        "Behind the screen, every attendance read is refused for them too",
        dwell_ms=2500,
    ):
        _expect_attendance_refused_for(api, ctx)


def _expect_attendance_refused_for(api: BackendAPI, ctx: SchoolContext) -> None:
    """Assert the backend refuses this Guardian on all three read surfaces.

    Without this the UI half proves only that the *frontend* hides the register,
    which a hand-built request would walk straight past. The ids in the paths are
    never looked up: ``has_permission`` is a route dependency, so it raises
    before the endpoint body runs.
    """
    assert ctx.guardian is not None
    token = api.login(ctx.guardian.email, ctx.guardian.password)["access_token"]
    today = date.today().isoformat()

    refusals = {
        # What the register itself calls on mount.
        "list": api.get("/attendance/?skip=0&limit=10", token=token),
        "stats": api.get(
            f"/attendance/stats/summary?attendance_date={today}", token=token
        ),
        # And the ward-scoped read, so "but it's only my own child" is refused too.
        "ward_summary": api.get("/attendance/student/1/summary", token=token),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a Guardian of {ctx.school_name!r} holds no attendance "
            f"permission, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert ROLE_DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not the role denial this "
            f"school's pack implies — {ATTENDANCE_MODULE!r} is licensed here, so "
            f"a plan-level refusal would mean the permission gate stopped "
            f"running. Got {detail!r}"
        )


# ──────────────── manage path: the class teacher marks the day ───────────────
#
# The register is the one academics screen a teacher writes to every morning, and
# the backend scopes that write twice over: ``has_permission("manage",
# "attendance")`` lets the Teacher role through, and then ``assert_class_teacher``
# (api/routes/attendance.py) refuses anyone who is not the assigned teacher of the
# row's class. Provisioning's teacher is exactly that for CLASS_NAME, so this unit
# runs as the person the feature was designed for rather than as an admin standing
# in for one.
#
# The same modal serves both halves of "manage": page.tsx sends POST /attendance/
# when the student has no record for the selected date and PUT /attendance/{id}
# when they do, deciding on its own from ``attendanceRecords``. So marking a
# student and then correcting that mark is one screen used twice — the create and
# the edit — not two different flows.
#
# No branch has to be activated first, unlike the SchoolAdmin read above: a
# teacher belongs to a branch, so ``branch_id_required`` derives it from their own
# account and ``useBranchStore`` is never consulted.

MANAGE_SCENARIO = "academics_only"

# AttendanceActionModal's STATUS_OPTIONS labels, which AttendanceTable then
# renders back as the row's status badge.
PRESENT_STATUS = "Present"
LATE_STATUS = "Late"

# The status a student carries before anyone has touched the day's register.
UNMARKED_STATUS = "Not Marked"

LATE_NOTE = "Arrived twenty minutes after registration closed."

# The modal defaults an unmarked student's check-in to 08:00 and the table
# reformats whatever the backend stored back to HH:mm, so any clock time here is
# proof the check-in was persisted rather than dropped.
CLOCK_TIME = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")


@pytest.mark.teacher
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.attendance.manage.teacher",
    title="Attendance",
    subtitle="Teacher creates and manages attendance",
)
def test_teacher_marks_and_corrects_attendance(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """The class teacher marks a student present, then corrects the record to late.

    Both writes go through the row's Mark Attendance modal: the first creates the
    day's record, the second edits it. The assertions are made on the register
    itself — the status badge, the check-in time and the note the teacher typed —
    because that reloaded row is what the next person to open the register sees.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.student is not None, "provisioning admitted no student for this school"

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    attendance = AttendancePage(page, base_url)
    teacher_name = ctx.teacher.full_name
    student_name = ctx.student.full_name

    with demo.step(f"Sign in as {teacher_name}, the class teacher for {CLASS_NAME}"):
        login_as(page, base_url, ctx.teacher)

    with demo.step("Open Attendance from the Academics menu"):
        link = page.get_by_role("link", name=as_pattern(NAV_ATTENDANCE)).first
        if link.count():
            link.click()
            page.wait_for_url(re.compile(rf"/module/{ATTENDANCE_ROUTE}"), timeout=20_000)
            attendance.expect_loaded()
        else:
            # The sidebar collapses on narrow viewports; the route is the point,
            # not the way in.
            attendance.open()
        attendance.expect_no_load_failure()

    with demo.step(f"Call today's register for {CLASS_NAME}"):
        attendance.filter_by_class(CLASS_NAME)
        attendance.search(ctx.student.first_name)
        expect(attendance.find_row(student_name)).to_be_visible(timeout=20_000)
        # Nobody has been marked yet today — this is the register the teacher
        # actually starts their morning with.
        attendance.expect_status(student_name, UNMARKED_STATUS)

    with demo.step(f"Mark {student_name} present for the day"):
        attendance.mark_attendance(student_name=student_name, status=PRESENT_STATUS)

    with demo.step("The register now carries the mark and the arrival time"):
        attendance.expect_status(student_name, PRESENT_STATUS)
        expect(attendance.cell(student_name, COLUMN["check_in"])).to_have_text(CLOCK_TIME)
        attendance.expect_no_load_failure()

    with demo.step(f"{ctx.student.first_name} was in fact late — correct the record"):
        attendance.mark_attendance(
            student_name=student_name, status=LATE_STATUS, notes=LATE_NOTE
        )

    with demo.step("The corrected day stands, note and all", dwell_ms=1500):
        attendance.expect_status(student_name, LATE_STATUS)
        expect(attendance.cell(student_name, COLUMN["notes"])).to_have_text(
            _exact_text(LATE_NOTE)
        )
        attendance.expect_no_load_failure()
