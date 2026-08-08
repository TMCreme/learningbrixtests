"""Student timetables — the generated week grid a learner reads their own
schedule off, and how a guardian gets to their child's copy of it.

The screen
    /module/student_timetables renders one ``GET /lessons/timetable/student/{id}``
    into a Monday–Sunday grid: every ``Lesson`` scheduled for the student's class
    in the chosen week becomes a card under its start time. Nothing on the page
    authors anything — the timetable is a *view* of the lesson plans another
    module writes — so this unit is a read-only path throughout.

Why a guardian has to enter their ward's view first
    ``page.tsx`` reads ``user_profile.student_profile.id`` off the auth store and
    offers no student picker at all. A guardian has a ``guardian_profile`` and no
    ``student_profile``, so visiting the route as themselves yields the "No
    student profile found for this account." error state, and the seeded Guardian
    role does not hold ``student_timetables`` either
    (db/repository/permissions.py grants it to Student only), so the sidebar
    never offers them the link.

    That is not a gap in the product: the guardian's route into every
    learner-facing screen is the "Impersonate" action on their own Home page
    (``ViewsComponents/GuardianView.tsx`` → ``POST
    /users/guardian/impersonate-ward/{student_id}``, which the backend allows
    only for a *direct* ward). It swaps the ward's profile, token and role
    permissions into the very stores the page and the sidebar read, so from that
    point the guardian is shown exactly what their child is shown, under a
    standing "You are currently impersonating …" banner. The backend agrees
    independently: ``LessonService.assert_can_view_student_timetable`` has a
    guardian branch that answers 404 "Student not found" for any student who is
    not one of the caller's wards.

    So the walkthrough below is the whole feature for this role: Home → the ward
    → the ward's week.

What is seeded, and why over the API
    The grid only reads. Everything it reads is the *lessons* module's
    walkthrough — a topic, a syllabus, and lesson plans placed on a day at a time
    of day. ``tests/flows/academics_seed`` already builds the first two (plus the
    subject-teacher assignment that puts a teacher's name on the card);
    ``timetabled_week`` below adds two lesson plans in the *current* week on top
    of it, exactly as ``school_provisioning._seed_fee_group`` seeds the fee group
    the Add Class dialog insists on. The current week specifically, because the
    screen opens on ``startOfWeek(new Date(), { weekStartsOn: 1 })`` — a lesson
    seeded on any other week would leave the default view empty for a reason that
    looks nothing like the cause.

    Both seeded plans carry an explicit ``scheduled_time``: the column is
    nullable and the grid has no row for a lesson with no start time, so a
    timeless plan is (correctly) not drawn at all and could not be asserted on.

Negative path
    A SchoolAdmin of the ``minimal`` school, whose pack excludes
    ``student_timetables``
    (``test_student_timetables_denied_for_school_admin_when_module_disabled``).
    That school has no pupil and no guardian to ask with — the pack switches
    ``students`` off too — so the denial is asserted through the strongest
    account it does have. Which half of ``has_permission`` answers is *derived*
    rather than hard-coded, because the seeded SchoolAdmin role holds no
    ``student_timetables`` permission today; see the section comment above that
    test.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI, Credentials
from tests.flows.academics_seed import AcademicsSeed, seed_assessment_prerequisites
from tests.flows.school_provisioning import CLASS_NAME, SUBJECT_NAME, SchoolContext
from tests.pages.academics.student_timetables import (
    NAV_STUDENT_TIMETABLE,
    StudentTimetablesPage,
)
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.people.guardian_home import GuardianHomePage

TIMETABLE_SCENARIO = "academics_only"

# Two plans in the week the screen opens on, on different days and at different
# times so the grid has to place each one in the right cell rather than merely
# render something. Named with the "TEST" prefix the orphan sweeper matches on.
FIRST_LESSON_TITLE = "TEST Monday Fractions Period"
FIRST_LESSON_DAY = "Monday"
FIRST_LESSON_WEEKDAY = 0  # date.weekday(): Monday is 0
FIRST_LESSON_TIME = "08:00"
FIRST_LESSON_MINUTES = 40

SECOND_LESSON_TITLE = "TEST Wednesday Fractions Period"
SECOND_LESSON_DAY = "Wednesday"
SECOND_LESSON_WEEKDAY = 2
SECOND_LESSON_TIME = "10:30"
SECOND_LESSON_MINUTES = 55


class TimetableSeedError(RuntimeError):
    """A prerequisite could not be seeded, so the week would render empty."""


@dataclass
class TimetabledWeek:
    """The two periods the guardian is expected to find, and whose week it is."""

    ward_name: str
    class_name: str
    teacher_name: str
    monday: date
    wednesday: date


@pytest.fixture
def timetabled_week(
    provisioned_school: SchoolContext, api: BackendAPI
) -> TimetabledWeek:
    """Put two lesson plans in the ward's class this week.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert ctx.guardian is not None, "provisioning created no guardian for this school"
    assert ctx.branches, "provisioning created no branch for this school"
    assert ctx.classes, "provisioning created no class for this school"

    branch_id = int(ctx.branches[0]["id"])
    seed = seed_assessment_prerequisites(
        api,
        ctx.school_admin,
        school_id=ctx.school_id,
        branch_id=branch_id,
        subject_name=SUBJECT_NAME,
        class_name=CLASS_NAME,
        teacher_email=ctx.teacher.email,
    )

    token = _seed_login(api, ctx.school_admin)
    _assert_ward_is_linked(api, token, ctx, branch_id=branch_id)

    monday = _monday_of_this_week()
    wednesday = monday + timedelta(days=SECOND_LESSON_WEEKDAY)

    _seed_lesson(
        api, token, seed,
        title=FIRST_LESSON_TITLE,
        on=monday,
        at=FIRST_LESSON_TIME,
        minutes=FIRST_LESSON_MINUTES,
    )
    _seed_lesson(
        api, token, seed,
        title=SECOND_LESSON_TITLE,
        on=wednesday,
        at=SECOND_LESSON_TIME,
        minutes=SECOND_LESSON_MINUTES,
    )

    return TimetabledWeek(
        ward_name=ctx.student.full_name,
        class_name=CLASS_NAME,
        teacher_name=ctx.teacher.full_name,
        monday=monday,
        wednesday=wednesday,
    )


@pytest.mark.guardian
@pytest.mark.scenario(TIMETABLE_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.student_timetables.view.guardian",
    title="Student Timetables",
    subtitle="Guardian views student timetables",
)
def test_guardian_views_ward_student_timetable(
    timetabled_week: TimetabledWeek,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A guardian steps into their ward's view and reads the child's week.

    Every figure the grid shows is derived server-side — the class the timetable
    is titled after comes from the ward's *enrollment*, the subject and teacher
    from the lesson plan, the row from its start time — so matching them proves
    the screen really fetched this ward's timetable rather than rendering
    something the browser already had.
    """
    ctx = provisioned_school
    assert ctx.guardian is not None, "provisioning created no guardian for this school"

    page: Page = demo.page
    home = GuardianHomePage(page, demo.frontend_base_url)
    timetable = StudentTimetablesPage(page, demo.frontend_base_url)
    ward_name = timetabled_week.ward_name

    with demo.step(f"Sign in as {ctx.guardian.full_name}, a parent at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.guardian)

    with demo.step(f"Home opens on the child they look after — {ward_name}"):
        home.expect_loaded()
        home.expect_ward(ward_name)

    with demo.step("Step into the ward's view to see the school as they see it"):
        home.view_as_ward(ward_name)

    with demo.step("Open Student Timetable from the Academics menu"):
        timetable.expect_nav_entry()
        timetable.open_from_sidebar().wait_for_grid()
        timetable.expect_no_load_failure()

    with demo.step(f"This week's schedule for {timetabled_week.class_name}, day by day"):
        timetable.expect_class_heading(timetabled_week.class_name)
        timetable.expect_weekly_view()
        timetable.expect_headers()

    with demo.step(
        f"{FIRST_LESSON_DAY} starts at {FIRST_LESSON_TIME} with {SUBJECT_NAME}, "
        f"taught by {timetabled_week.teacher_name}"
    ):
        timetable.expect_lesson(
            time_label=FIRST_LESSON_TIME,
            day=FIRST_LESSON_DAY,
            subject=SUBJECT_NAME,
            teacher=timetabled_week.teacher_name,
            duration_minutes=FIRST_LESSON_MINUTES,
        )

    with demo.step(
        f"{SECOND_LESSON_DAY}'s longer period is there too — and a parent may "
        f"read the week, never rewrite it",
        dwell_ms=1500,
    ):
        timetable.expect_lesson(
            time_label=SECOND_LESSON_TIME,
            day=SECOND_LESSON_DAY,
            subject=SUBJECT_NAME,
            teacher=timetabled_week.teacher_name,
            duration_minutes=SECOND_LESSON_MINUTES,
        )
        timetable.expect_write_controls_absent()


# ────────────────── the same week, read by the pupil themselves ──────────────
#
# The guardian walkthrough above reaches this grid the long way round, through
# impersonation. The pupil is who the screen was built for, and their path is the
# short one: the sidebar entry is on offer the moment they log in.
#
# Why the link is there for them and for nobody else
#     ``nav-config.tsx`` gates the "Student Timetable" entry on both
#     ``permission: "student_timetables"`` and ``module: "student_timetables"``.
#     The seeded Student role is the only role granted ``("read",
#     "student_timetables")`` at all (db/repository/permissions.py) — not the
#     Teacher, not the Guardian, not even the SchoolAdmin — and the
#     ``academics_only`` pack licenses the module, so both halves pass. The
#     branch-only "Academics Module" section that holds it is not a problem
#     either: ``SideNavigation.canShowSection`` treats branch state as a
#     SchoolAdmin-only concept and leaves every other role's sections alone.
#
# What the pupil is entitled to see
#     Their own week and no one else's. ``page.tsx`` reads
#     ``user_profile.student_profile.id`` and there is no picker to change it, and
#     ``LessonService.assert_can_view_student_timetable`` refuses any other id
#     with 404 "Student not found" — so the grid that renders here can only be
#     this pupil's. That is what makes the class heading worth asserting: "Grade
#     6 Timetable" is the server's answer to *which class this account is
#     enrolled in*, resolved from ``ClassStudent``, not anything the browser
#     could have guessed.
#
# The seeding is shared with the guardian unit on purpose. ``timetabled_week``
# is idempotent by lesson title, and both roles are supposed to be looking at the
# very same two periods — that they do is part of what the pair proves.


@pytest.mark.student
@pytest.mark.scenario(TIMETABLE_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.student_timetables.view.student",
    title="Student Timetables",
    subtitle="Student views student timetables",
)
def test_student_views_their_own_weekly_timetable(
    timetabled_week: TimetabledWeek,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A pupil signs in, opens their timetable and reads their own week off it.

    Every value asserted is derived server-side — the class the grid titles itself
    after comes from the pupil's enrollment, the subject and teacher from the
    lesson plan, the row from its start time and the card from its duration — so
    matching them proves the screen really fetched this pupil's timetable rather
    than rendering something the browser already had.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"

    page: Page = demo.page
    timetable = StudentTimetablesPage(page, demo.frontend_base_url)
    pupil = ctx.student.full_name

    with demo.step(f"Sign in as {pupil}, a pupil at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.student)

    with demo.step("The session that opens is the pupil's own account"):
        # Deliberately *not* an assertion about which page they land on. Login
        # sends a non-admin to `/module/<first permission's module>`
        # (auth/login/page.tsx::handlePostLoginNavigation), and "community" is
        # in that file's CORE_MODULES list, so it is always accessible and a
        # pupil lands there rather than on Home. What matters here is only whose
        # session this is, and NavigationHeader states that on every route: the
        # signed-in name and the address the account was created under.
        expect(
            page.get_by_text(as_pattern(re.escape(pupil))).first
        ).to_be_visible(timeout=30_000)
        expect(
            page.get_by_text(as_pattern(re.escape(ctx.student.email))).first
        ).to_be_visible(timeout=30_000)

    with demo.step("Student Timetable is waiting in their Academics menu"):
        timetable.expect_nav_entry()
        timetable.open_from_sidebar().wait_for_grid()
        timetable.expect_no_load_failure()

    with demo.step(f"The week opens on {timetabled_week.class_name}, the class they "
                   f"are enrolled in"):
        timetable.expect_class_heading(timetabled_week.class_name)
        timetable.expect_weekly_view()
        timetable.expect_headers()

    with demo.step(
        f"{FIRST_LESSON_DAY} begins at {FIRST_LESSON_TIME} with {SUBJECT_NAME}, "
        f"taught by {timetabled_week.teacher_name}"
    ):
        timetable.expect_lesson(
            time_label=FIRST_LESSON_TIME,
            day=FIRST_LESSON_DAY,
            subject=SUBJECT_NAME,
            teacher=timetabled_week.teacher_name,
            duration_minutes=FIRST_LESSON_MINUTES,
        )

    with demo.step(f"{SECOND_LESSON_DAY} carries the longer "
                   f"{SECOND_LESSON_MINUTES}-minute period at {SECOND_LESSON_TIME}"):
        timetable.expect_lesson(
            time_label=SECOND_LESSON_TIME,
            day=SECOND_LESSON_DAY,
            subject=SUBJECT_NAME,
            teacher=timetabled_week.teacher_name,
            duration_minutes=SECOND_LESSON_MINUTES,
        )

    with demo.step("A pupil may read their timetable — nothing here rewrites it",
                   dwell_ms=1500):
        timetable.expect_write_controls_absent()


# ───────────────────── negative path: the unlicensed school ──────────────────
#
# Constants below are prefixed rather than sharing the two view sections' names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# Why the SchoolAdmin is the role this is asserted through
#     ``minimal`` is the floor scenario: its pack holds ``school_configuration``
#     and ``school_admin_dashboard`` and nothing else, so provisioning never gets
#     as far as admitting a pupil or a guardian — the SchoolAdmin is the only
#     account this school has. That is fine for a denial: the question the unit
#     answers is "can anyone at a school whose pack excludes
#     ``student_timetables`` reach a timetable", and the school's own
#     administrator is the strongest account to ask it with.
#
# Which half of ``utils.permissions.has_permission`` answers
#     It refuses twice over: first if the caller's *role* holds no
#     ``(read|manage, student_timetables)`` pair, and only then if the school's
#     *feature pack* omits the module. The seeded SchoolAdmin role does not hold
#     ``student_timetables`` at all — db/repository/permissions.py grants it to
#     Student alone — so today it is the permission half that answers, with "You
#     do not have permission to perform this action".
#
#     Hard-coding that string would break the day someone widens the seed, even
#     though the denial would still be correct (the pack would refuse it
#     instead). So the expected detail is *derived*: the role is read back from
#     ``GET /roles/{id}`` and the assertion demands the plan message when the role
#     holds the module and the permission message when it does not. The licence is
#     asserted separately, so "the pack really does exclude student_timetables" is
#     never taken on trust.
#
# What the browser does, and what it therefore proves
#     Nothing redirects this role. ``src/middleware.ts`` skips its module
#     enforcement for a SchoolAdmin outright and ``useModuleGuard`` hands them
#     ``hasAccess = true`` before it ever reads the ``schoolModules`` cookie, so
#     /module/student_timetables really does mount for them. It then never even
#     asks the backend: ``page.tsx`` reads
#     ``user_profile.student_profile.id`` off the auth store, a SchoolAdmin has no
#     ``student_profile``, and the missing id short-circuits ``fetchData`` into
#     the "No student profile found for this account." error state. So the UI half
#     below proves "no grid, no week, no schedule reaches this account" — it is
#     the API half that proves the *module* is gated, which is why that half comes
#     first and covers both routes ``api/routes/lesson.py`` puts behind
#     ``has_permission("read", "student_timetables")``.
#
#     The sidebar is asserted too, but as a *role* verdict rather than a licence
#     one: "Student Timetable" carries ``permission: "student_timetables"``
#     (SideNavigation/nav-config.tsx) and the permission check takes priority for
#     a SchoolAdmin, so its absence says nothing about this school's pack. It is
#     worth pinning as a denial surface all the same, and the Governance entry
#     asserted alongside it is what keeps "no Student Timetable link" from passing
#     on a sidebar that never rendered.

STUDENT_TIMETABLES_MODULE = "student_timetables"
STUDENT_TIMETABLES_ROUTE = "student_timetables"
DENIED_SCENARIO = "minimal"
DENIED_ROLE = "SchoolAdmin"

# The two denials utils/permissions.py can answer with. The permission half runs
# first and short-circuits, so a role lacking the module never reaches the pack
# half and never sees the plan message.
PLAN_DENIAL = re.compile(r"Feature not available in your plan", re.I)
ROLE_DENIAL = re.compile(r"You do not have permission to perform this action", re.I)

# Sidebar entries (SideNavigation/nav-config.tsx). The Governance section is
# ``noBranchOnly``, so it is exactly what a freshly logged-in SchoolAdmin — who
# has selected no branch — sees, which makes it the honest non-vacuous anchor.
NAV_GOVERNANCE_ANCHOR = re.compile(r"^\s*School Admin Dashboard\s*$", re.I)

# Where the frontend sends someone it has decided is not licensed, in case a
# future guard starts throwing this role out of the route entirely.
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)

# The screen's own states (src/app/module/student_timetables/page.tsx).
DENIED_ERROR_HEADING = re.compile(r"^\s*Error Loading Timetable\s*$", re.I)
DENIED_NO_PROFILE = re.compile(r"No student profile found for this account", re.I)
# Chrome that exists only on a rendered grid.
DENIED_WEEKLY_VIEW = re.compile(r"^\s*Weekly View\s*$", re.I)
DENIED_TIME_HEADER = "Time / Day"

DENIAL_TIMEOUT_S = 30.0


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_student_timetables_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `student_timetables` off the pack, no timetable is served at all."""
    ctx = provisioned_school
    if STUDENT_TIMETABLES_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {STUDENT_TIMETABLES_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. Work out which half of the gate is expected to answer ──────────────
    #
    # Read first so a failure below can never be misread as "the role never had
    # timetable rights anyway, so the 403s say nothing about the licence".
    role = api.get(f"/roles/{api.role_id_for(DENIED_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {DENIED_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    role_holds_module = STUDENT_TIMETABLES_MODULE in role_modules
    expected_detail = PLAN_DENIAL if role_holds_module else ROLE_DENIAL
    expected_reason = (
        "the feature pack (the role does hold the permission)"
        if role_holds_module
        else "the role's own permissions (the pack half is never reached)"
    )

    # ── 2. The licence really does exclude the module ─────────────────────────
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{STUDENT_TIMETABLES_MODULE!r} proves nothing about the gate. "
        f"Provisioning phase A assigns one — check that it did."
    )
    assert STUDENT_TIMETABLES_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {STUDENT_TIMETABLES_MODULE!r} "
        f"despite the {ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) "
        f"excluding it."
    )

    # ── 3. The denial itself: both timetable routes are refused ───────────────
    #
    # These are the only two routes whose dependency names
    # ``student_timetables`` (api/routes/lesson.py), so a regression in a
    # neighbouring module's gate can never make this pass. The ids are arbitrary:
    # ``has_permission`` is a route *dependency*, answered before the handler ever
    # looks a class or a student up — a 404 here would mean the gate had let the
    # request through, which is exactly the regression being watched for.
    refusals = {
        "student_timetable": api.get("/lessons/timetable/student/1", token=token),
        "class_timetable": api.get("/lessons/timetable/1", token=token),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) must be refused "
            f"{STUDENT_TIMETABLES_MODULE!r} by {expected_reason} — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert expected_detail.search(detail), (
            f"{label}: 403 is right, but the reason is not the one this role and "
            f"this pack imply. Expected a denial from {expected_reason}, matching "
            f"{expected_detail.pattern!r} — got {detail!r}"
        )

    # ── 4. The sidebar never offers the screen ────────────────────────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    expect(
        page.get_by_role("link", name=as_pattern(NAV_GOVERNANCE_ANCHOR)).first
    ).to_be_visible(timeout=25_000)
    expect(
        page.get_by_role("link", name=as_pattern(NAV_STUDENT_TIMETABLE))
    ).to_have_count(0)

    # ── 5. …and typing the route in anyway yields no week ─────────────────────
    goto_module(page, frontend_base_url, STUDENT_TIMETABLES_ROUTE)

    if _wait_for_timetable_denial(page) == "no-access":
        expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(
            timeout=15_000
        )
    else:
        # The screen's own refusal, and the one this role gets today: it resolved
        # no learner to draw a week for, so it asked the backend for nothing.
        # Asserted rather than merely tolerated, so a build that started serving
        # *somebody's* timetable here could not slip through as "an error state".
        expect(page.get_by_text(as_pattern(DENIED_NO_PROFILE))).to_be_visible(
            timeout=15_000
        )

    # Invariant under both surfaces: no schedule was drawn. The grid is the only
    # thing on this route that renders a table, a "Weekly View" badge or a
    # "Time / Day" header, so none of them may exist. (The static "Student Class
    # Timetable" heading belongs to the error state itself and says nothing about
    # a week, which is why the grid's own "<class> Timetable" title — a heading
    # this school could not produce, having no class — is not what is asserted.)
    expect(page.get_by_text(as_pattern(DENIED_WEEKLY_VIEW))).to_have_count(0)
    expect(page.get_by_text(as_pattern(DENIED_TIME_HEADER))).to_have_count(0)
    expect(page.locator("table")).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


def _wait_for_timetable_denial(page: Page) -> str:
    """Wait for whichever denial surface this route reaches, and name it.

    Today a SchoolAdmin gets the screen's own error state, because the page
    resolves no ``student_profile`` for them and never calls the backend at all
    (see the section comment above). A guard that started throwing the role out of
    the module entirely would land them on /auth/no-access instead — also a
    correct denial — so both are accepted, and only "neither arrived" is a
    failure, since that would mean a timetable had been served.
    """
    deadline = time.monotonic() + DENIAL_TIMEOUT_S
    while time.monotonic() < deadline:
        if NO_ACCESS_URL.search(page.url):
            return "no-access"
        if page.get_by_text(as_pattern(DENIED_ERROR_HEADING)).count():
            return "error-state"
        page.wait_for_timeout(250)

    raise AssertionError(
        f"/module/{STUDENT_TIMETABLES_ROUTE} neither redirected to /auth/no-access "
        f"nor reported an error within {DENIAL_TIMEOUT_S:.0f}s — the screen appears "
        f"to have been served to a school whose pack excludes "
        f"{STUDENT_TIMETABLES_MODULE!r}. Current URL: {page.url}"
    )


# ──────────── setup-only seeding for this unit (never asserted) ──────────────


def _monday_of_this_week() -> date:
    """The Monday the screen's default range starts on.

    ``page.tsx`` opens on ``startOfWeek(new Date(), { weekStartsOn: 1 })``, which
    is the same Monday ``date.weekday()`` counts from — so a plan placed here
    lands inside the range the grid asks the backend for, with no date picking
    required in the walkthrough.
    """
    today = date.today()
    return today - timedelta(days=today.weekday())


def _seed_login(api: BackendAPI, creds: Credentials) -> str:
    try:
        return str(api.login(creds.email, creds.password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise TimetableSeedError(f"could not log in as {creds.email}: {exc}") from exc


def _seed_rows(payload) -> list[dict]:
    """Some list endpoints answer a bare list, others a paginated envelope."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _assert_ward_is_linked(
    api: BackendAPI, token: str, ctx: SchoolContext, *, branch_id: int
) -> None:
    """Fail loudly here rather than as a missing Impersonate button later.

    The whole walkthrough hangs off the ``guardian_students`` edge the admission
    wizard's guardian picker writes: without it the ward never appears in "Your
    Ward(s)", ``POST /users/guardian/impersonate-ward/{id}`` answers 403, and
    ``assert_can_view_student_timetable`` would answer 404 even if it did. One
    extra request buys the diagnosis instead of three confusing symptoms.
    """
    assert ctx.guardian is not None and ctx.student is not None
    response = api.get(f"/student/?branch_id={branch_id}&limit=100", token=token)
    if response.status_code >= 400:
        raise TimetableSeedError(
            f"could not list students in branch {branch_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    profile_id = None
    for row in _seed_rows(response.json()):
        user = row.get("user") or {}
        if str(user.get("email", "")).casefold() == ctx.student.email.casefold():
            profile_id = int(row["id"])
            break
    if profile_id is None:
        raise TimetableSeedError(
            f"no student profile for {ctx.student.email!r} in branch {branch_id} — "
            "provisioning phase C should have admitted one."
        )

    detail = api.get(f"/student/{profile_id}?branch_id={branch_id}", token=token)
    if detail.status_code >= 400:
        raise TimetableSeedError(
            f"could not read student {profile_id}: "
            f"{detail.status_code} {detail.text[:300]}"
        )
    if not _seed_rows(detail.json().get("guardians") or []):
        raise TimetableSeedError(
            f"student {profile_id} has no guardian linked to them, so no guardian "
            "may view their timetable. Provisioning phase C admits the student "
            "through the admission wizard's guardian picker, which is what writes "
            "that link."
        )


def _seed_lesson(
    api: BackendAPI,
    token: str,
    seed: AcademicsSeed,
    *,
    title: str,
    on: date,
    at: str,
    minutes: int,
) -> int:
    """One lesson plan, which is one card on the grid.

    Authored as the SchoolAdmin: ``LessonService.create_lesson`` auto-approves an
    admin's plan and skips the subject-teacher scoping a teacher would be held
    to. ``teacher_id`` is still the provisioned teacher, because the card names
    whoever the *plan* is assigned to.
    """
    existing = _existing_lesson_id(api, token, seed, title=title)
    if existing is not None:
        return existing

    response = api.post(
        f"/lessons/?branch_id={seed.branch_id}",
        token=token,
        json={
            "title": title,
            "description": "Seeded so the ward's week has something on it.",
            "lesson_type": "syllabus",
            "topic_id": seed.topic_id,
            "syllabus_id": seed.syllabus_id,
            "subject_id": seed.subject_id,
            "class_id": seed.class_id,
            "teacher_id": seed.teacher_profile_id,
            "scheduled_date": on.isoformat(),
            "scheduled_time": f"{at}:00",
            "duration_minutes": minutes,
        },
    )
    if response.status_code >= 400:
        raise TimetableSeedError(
            f"could not seed the lesson {title!r} on {on.isoformat()} at {at}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


def _existing_lesson_id(
    api: BackendAPI, token: str, seed: AcademicsSeed, *, title: str
) -> int | None:
    """Reuse a plan a previous test in this scenario already seeded.

    The whole batch shares one provisioned school, and two identical plans in the
    same cell would make the grid ambiguous to assert on.
    """
    response = api.get(
        f"/lessons/?branch_id={seed.branch_id}&class_id={seed.class_id}"
        f"&subject_id={seed.subject_id}&limit=100",
        token=token,
    )
    if response.status_code >= 400:
        return None
    wanted = re.compile(rf"^\s*{re.escape(title)}\s*$", re.I)
    for row in _seed_rows(response.json()):
        if wanted.match(str(row.get("title", ""))):
            return int(row["id"])
    return None
