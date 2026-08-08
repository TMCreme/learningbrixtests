"""/module/lessons — the "Manage Lessons" workspace.

Positive path: a teacher of the ``academics_only`` school writes a lesson plan
and then revises it (``test_teacher_creates_and_manages_lesson``).

What has to be true before the feature is reachable
    ``LessonForm`` is a four-step cascade — Class → Subject → Syllabus → Topic —
    and every step but the first is disabled until the one before it has a
    value. So a teacher can only author a plan once a *syllabus* carrying a
    *topic* exists for the (class, subject) pair they teach. That chain is three
    other modules' walkthroughs, so it is seeded over the API by
    ``tests/flows/academics_seed.py`` — the same setup-only use of the backend
    that ``school_provisioning._seed_fee_group`` makes.

    The same helper writes the one row that is about authorization rather than
    about dropdowns: ``LessonService.create_lesson`` calls
    ``assert_subject_teacher``, so a teacher may only author a plan for a
    (subject, class) pair they are the **subject teacher** of. Provisioning makes
    its teacher the *class* teacher of "Grade 6", which grants no writes at all —
    without the seeded assignment the create answers 403.

Why the plan comes out "pending"
    ``create_lesson`` auto-approves only admin- and staff-authored plans; a
    teacher's start ``PENDING``. So "pending" in the Approval column is what a
    *successful* create looks like here, and the test asserts it rather than
    treating it as a half-failure.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack does
NOT include ``lessons`` (``test_lessons_denied_for_school_admin_when_module_disabled``).

Where that denial actually lives
    Not in the sidebar, and not in a route guard. ``useModuleGuard`` returns
    ``true`` outright for a SchoolAdmin ("SuperAdmin or SchoolAdmin"), and
    ``usePermissionGuard`` returns early for the same role ("SchoolAdmin has
    access to all modules"), so /module/lessons neither redirects to
    /auth/no-access nor to /unauthorized — the page mounts. The seeded
    SchoolAdmin role also *holds* ``("manage", "lessons")``
    (newschoolapp/db/repository/permissions.py), so the permission half of the
    backend gate passes too.

    What denies them is the feature-pack half of ``utils.permissions.has_permission``:
    every ``/lessons`` route answers **403 "Feature not available in your plan"**.
    That 403 is what this test is built on.

    The UI consequence follows from it, and it does *not* end in the register's
    own ``PageError``. ``loadLessons``'s fetch is refused, and the axios response
    interceptor in ``src/utils/handleErrorMessage.ts`` recognises that particular
    detail (``shouldRedirectToNoAccess``) and performs a hard
    ``window.location`` redirect to **/auth/no-access** — rejecting the promise
    with ``FeatureNotAvailableError`` before page.tsx's own ``catch`` can put
    "Failed to load lessons" on screen. So the landing page, not the error panel,
    is the denial surface here, and this test asserts it exactly: a school that
    is *permitted* but not *licensed* is thrown out of the module entirely.

    Both halves are asserted, so a regression that silently starts serving
    lessons to an unlicensed school fails here.

    Deliberately *not* asserted: that the sidebar hides "Lessons". For a
    SchoolAdmin that entry is gated on the role permission rather than on the
    feature pack (SideNavigation: "Permission check takes priority"), so its
    presence or absence says nothing about this school's pack.

Read-only path: a pupil of the ``academics_only`` school reads the plans for
their own class (``test_student_reads_the_lessons_planned_for_their_class``).

What a pupil is actually allowed to see
    Two independent narrowings, both in ``LessonService._scope_lessons``, and the
    test is built on both. A ``student`` scope is restricted to the classes they
    are *enrolled* in (``ClassStudent``) **and** to plans whose
    ``approval_status`` is ``APPROVED``. So a plan a teacher is still drafting is
    invisible to the class it is written for — which is the point of the approval
    workflow, and is asserted here rather than assumed.

    The seeded ``Student`` role holds ``("read", "lessons")``
    (newschoolapp/db/repository/permissions.py), so nothing about this path is a
    denial: the pupil is offered the sidebar entry, the register renders, and the
    row is there. What they must never get is a way to *change* it — every write
    affordance on both routes is gated on ``usePermission("lessons", "manage")``,
    and every mutating ``/lessons`` route answers 403.

A frontend defect this unit uncovered (fixed in place, smsfrontend is dirty)
    ``lessons/[id]/page.tsx`` rendered its "Edit Lesson" button unconditionally,
    while the register's row menu had always gated the identical action on
    ``usePermission("lessons", "manage")``. A pupil opening a plan was therefore
    one click from an editor the backend refuses the PUT from. The button now
    carries the same gate as the row menu, and this test asserts it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.academics_seed import (
    SYLLABUS_NAME,
    TOPIC_NAME,
    AcademicsSeed,
    seed_assessment_prerequisites,
)
from tests.flows.school_provisioning import CLASS_NAME, SUBJECT_NAME, SchoolContext
from tests.pages.academics.lessons import (
    ADD_BUTTON,
    BULK_CREATE_BUTTON,
    COLUMN,
    DETAIL_EDIT_BUTTON,
    PAGE_HEADING,
    SEARCH_PLACEHOLDER,
    STATUS_LABELS,
    WEEKLY_PLAN_BUTTON,
    LessonsPage,
)
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as

LESSONS_MODULE = "lessons"
LESSONS_ROUTE = "lessons"
LESSONS_SCENARIO = "academics_only"
DENIED_SCENARIO = "minimal"

# The role whose permissions are checked against the pack in the negative path.
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

# The sidebar entry for this module (SideNavigation/nav-config.tsx). For a
# Teacher the section's `branchOnly` flag does not apply — branch state is a
# SchoolAdmin-only concept — so the link is on screen straight after login.
NAV_LESSONS = re.compile(r"^\s*Lessons\s*$", re.I)

# Named with the "TEST" prefix the orphan sweeper matches on, and with the run
# tag so parallel agents never collide.
LESSON_TITLE = f"TEST Long Division Lesson {run_tag()}"
LESSON_OBJECTIVES = (
    "Divide a three-digit number by a one-digit number using the standard "
    "algorithm, and explain each step."
)
LESSON_DESCRIPTION = "Introduces long division through sharing problems on the board."
LESSON_STRUCTURE = "1. Starter quiz  2. Worked example  3. Paired practice  4. Plenary"
LESSON_HOMEWORK = "Workbook page 42, questions 1-8."
CREATE_DURATION = 40
EDIT_DURATION = 60

# The syllabus and topic seeded below. Matched on their stable prefix rather
# than on the full tagged name, which the seed does not hand back.
SYLLABUS_OPTION = re.compile(re.escape(SYLLABUS_NAME), re.I)
TOPIC_OPTION = re.compile(re.escape(TOPIC_NAME), re.I)

PLANNED = STATUS_LABELS["planned"]
COMPLETED = STATUS_LABELS["completed"]
PENDING_APPROVAL = "pending"


@pytest.fixture
def lesson_seed(provisioned_school: SchoolContext, api: BackendAPI) -> AcademicsSeed:
    """The syllabus/topic chain the lesson form cascades through.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    return seed_assessment_prerequisites(
        api,
        ctx.school_admin,
        school_id=ctx.school_id,
        branch_id=int(ctx.branches[0]["id"]),
        subject_name=SUBJECT_NAME,
        class_name=CLASS_NAME,
        teacher_email=ctx.teacher.email,
    )


@pytest.mark.teacher
@pytest.mark.scenario(LESSONS_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.lessons.manage.teacher",
    title="Lessons",
    subtitle="Teacher creates and manages lessons",
)
def test_teacher_creates_and_manages_lesson(
    lesson_seed: AcademicsSeed,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A subject teacher plans a lesson, then revises it and marks it taught."""
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"

    page: Page = demo.page
    lessons = LessonsPage(page, demo.frontend_base_url)
    scheduled_date = (date.today() + timedelta(days=3)).isoformat()

    with demo.step(f"Sign in as {ctx.teacher.full_name}, who teaches {SUBJECT_NAME}"):
        login_as(page, demo.frontend_base_url, ctx.teacher)

    with demo.step("Open Lessons from the Academics menu"):
        link = page.get_by_role("link", name=NAV_LESSONS).first
        if link.count():
            link.click()
            lessons.expect_loaded()
        else:
            # The sidebar collapses on narrow viewports; the route is the point,
            # not the way in.
            lessons.open()
        lessons.expect_no_load_failure()
        lessons.wait_for_rows()

    with demo.step("Start a new lesson plan"):
        lessons.open_create_form()

    with demo.step(f"Pick the class, subject and syllabus topic for {CLASS_NAME}"):
        lessons.fill_form(
            title=LESSON_TITLE,
            class_name=CLASS_NAME,
            subject_name=SUBJECT_NAME,
            syllabus_name=SYLLABUS_OPTION,
            topic_name=TOPIC_OPTION,
        )

    with demo.step("Schedule the lesson and say how long it will run"):
        lessons.fill_form(
            scheduled_date=scheduled_date,
            scheduled_time="09:30",
            duration_minutes=CREATE_DURATION,
        )

    with demo.step("Write the plan: objectives, structure and homework"):
        lessons.fill_form(
            objectives=LESSON_OBJECTIVES,
            description=LESSON_DESCRIPTION,
            lesson_structure=LESSON_STRUCTURE,
            homework=LESSON_HOMEWORK,
        )

    with demo.step("Save it — the plan is on the register, awaiting approval",
                   dwell_ms=1200):
        lessons.submit_create()
        lessons.search(LESSON_TITLE)
        lessons.expect_row(LESSON_TITLE)

        expect(lessons.cell(LESSON_TITLE, COLUMN["class"])).to_have_text(
            _exact(CLASS_NAME)
        )
        expect(lessons.cell(LESSON_TITLE, COLUMN["teacher"])).to_have_text(
            _exact(ctx.teacher.full_name)
        )
        lessons.expect_status(LESSON_TITLE, PLANNED)
        # A teacher's plan is created PENDING — only admins' are auto-approved.
        lessons.expect_approval(LESSON_TITLE, PENDING_APPROVAL)

    with demo.step("Reopen the plan, give it a full hour and mark it taught"):
        lessons.open_edit_form(LESSON_TITLE)
        lessons.fill_form(duration_minutes=EDIT_DURATION, status=COMPLETED)
        lessons.submit_update()

    with demo.step("The register shows the lesson as completed", dwell_ms=1500):
        lessons.search(LESSON_TITLE)
        lessons.expect_row(LESSON_TITLE)
        lessons.expect_status(LESSON_TITLE, COMPLETED)
        lessons.expect_approval(LESSON_TITLE, PENDING_APPROVAL)


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)


# ───────────────────── negative path: the unlicensed school ──────────────────


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_lessons_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `lessons` off the pack, a SchoolAdmin gets no register and no data."""
    ctx = provisioned_school
    if LESSONS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {LESSONS_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had lessons rights anyway", which would make the 403s vacuous.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert LESSONS_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{LESSONS_MODULE!r} permission, so this test would be asserting a "
        f"denial the role gets for free. Re-point it at the feature pack only, "
        f"or fix the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{LESSONS_MODULE!r} proves nothing about the gate. Provisioning phase A "
        f"assigns one — check that it did."
    )
    assert LESSONS_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {LESSONS_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every lessons route is refused ──────────────────
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"&branch_id={branch_id}" if branch_id else ""
    week_start = date.today()
    week_end = week_start + timedelta(days=6)

    refusals = {
        # What the register itself calls on mount.
        "list": api.get(f"/lessons/?skip=0&limit=10{branch_query}", token=token),
        # The "Weekly Plan" screen the register links out to.
        "weekly_plan": api.get(
            f"/lessons/weekly-plan/1?start_date={week_start.isoformat()}"
            f"&end_date={week_end.isoformat()}",
            token=token,
        ),
        # And the write half, so the gate is not merely read-only.
        "create": api.post(
            "/lessons/",
            token=token,
            json={
                "title": "TEST Unlicensed Lesson",
                "description": "Must never be created — the pack excludes lessons.",
                "lesson_type": "adhoc",
                "subject_id": 1,
                "class_id": 1,
                "duration_minutes": 40,
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{LESSONS_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a register in front of them ─────────────────
    login_as(page, frontend_base_url, ctx.school_admin)
    goto_module(page, frontend_base_url, LESSONS_ROUTE)

    # A SchoolAdmin is exempt from both frontend route guards, so /module/lessons
    # really does mount and really does ask for the list — which is refused…
    # …and the axios interceptor turns that answer into a hard redirect long
    # before PageError could render (see the module docstring). Waiting for the
    # URL is therefore also what stops the "register is absent" assertions below
    # from passing merely because the page had not finished loading.
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(
        timeout=15_000
    )
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the register came with them.
    expect(page.get_by_role("heading", name=as_pattern(PAGE_HEADING))).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(ADD_BUTTON))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


# ──────────────── read-only path: a pupil reads their own lessons ────────────
#
# Constants below are prefixed rather than sharing the teacher section's names:
# this module file is written one role-section at a time, and a shared
# module-level name would silently rebind under whichever section is appended
# last.

STUDENT_VIEW_SCENARIO = "academics_only"

# The plan the school publishes to the class. Authored over the API as the
# SchoolAdmin because ``create_lesson`` auto-approves admin-authored plans, and
# only an *approved* plan is visible to a pupil at all — driving the teacher's
# create through the UI here would produce a pending plan and an empty register.
STUDENT_LESSON_TITLE = f"TEST Measuring Angles {run_tag()}"
STUDENT_LESSON_OBJECTIVES = (
    "Measure and draw angles to the nearest degree using a protractor, and say "
    "whether an angle is acute, right or obtuse."
)
STUDENT_LESSON_DESCRIPTION = (
    "A practical lesson on reading a protractor from whichever scale starts at "
    "the base line."
)
# Single-spaced on purpose: Playwright normalises whitespace when it matches
# text, so a doubled space in the expected string would never line up with the
# rendered card.
STUDENT_LESSON_STRUCTURE = (
    "1. Estimate the angle. 2. Measure it. 3. Draw one of your own. "
    "4. Swap books and check."
)
STUDENT_LESSON_HOMEWORK = "Workbook page 58, questions 1 to 6."
STUDENT_LESSON_DURATION = 45

# The teacher's unfinished plan for the very same class. It stays PENDING, and
# the pupil must never see it — that is the approval workflow doing its job.
STUDENT_DRAFT_TITLE = f"TEST Draft Angles Plan Awaiting Approval {run_tag()}"

# What the register renders in the Approval column for the published plan.
APPROVED_APPROVAL = "approved"

# The one denial utils/permissions.py can answer a pupil with here: the school
# holds the module, so it is the role that is refused, never the plan.
STUDENT_ROLE_DENIAL_DETAIL = re.compile(
    r"You do not have permission to perform this action", re.I
)


@dataclass(frozen=True)
class PupilLessons:
    """The two plans this unit puts in front of (and behind) the pupil."""

    published_id: int
    published_title: str
    draft_id: int
    draft_title: str


@pytest.fixture
def pupil_lessons(
    provisioned_school: SchoolContext, api: BackendAPI
) -> PupilLessons:
    """One approved plan for the pupil's class, and one still awaiting sign-off.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert ctx.classes, (
        "provisioning created no class, so the pupil is enrolled in nothing and "
        "every lesson is correctly invisible to them"
    )

    seed = seed_assessment_prerequisites(
        api,
        ctx.school_admin,
        school_id=ctx.school_id,
        branch_id=int(ctx.branches[0]["id"]),
        subject_name=SUBJECT_NAME,
        class_name=CLASS_NAME,
        teacher_email=ctx.teacher.email,
    )

    admin_token = api.login(
        ctx.school_admin.email, ctx.school_admin.password
    )["access_token"]
    published = _author_lesson(
        api, admin_token, seed,
        title=STUDENT_LESSON_TITLE,
        objectives=STUDENT_LESSON_OBJECTIVES,
        description=STUDENT_LESSON_DESCRIPTION,
        lesson_structure=STUDENT_LESSON_STRUCTURE,
        homework=STUDENT_LESSON_HOMEWORK,
        duration_minutes=STUDENT_LESSON_DURATION,
    )
    assert published["approval_status"] == APPROVED_APPROVAL, (
        f"a SchoolAdmin-authored plan is auto-approved by "
        f"LessonService.create_lesson, and only an approved plan is visible to a "
        f"pupil — got {published['approval_status']!r}"
    )

    teacher_token = api.login(
        ctx.teacher.email, ctx.teacher.password
    )["access_token"]
    draft = _author_lesson(
        api, teacher_token, seed,
        title=STUDENT_DRAFT_TITLE,
        objectives="Still being written — this plan has not been signed off.",
        description="Must stay invisible to the class until it is approved.",
        duration_minutes=STUDENT_LESSON_DURATION,
    )
    assert draft["approval_status"] == PENDING_APPROVAL, (
        f"a teacher's plan starts PENDING, which is what makes it the control "
        f"case for the visibility assertions — got {draft['approval_status']!r}"
    )

    return PupilLessons(
        published_id=int(published["id"]),
        published_title=STUDENT_LESSON_TITLE,
        draft_id=int(draft["id"]),
        draft_title=STUDENT_DRAFT_TITLE,
    )


def _author_lesson(
    api: BackendAPI, token: str, seed: AcademicsSeed, *, title: str, **fields: Any
) -> dict[str, Any]:
    """Create a syllabus lesson on the seeded chain, as whoever holds ``token``.

    Setup only, never an assertion: the author's role is what decides the plan's
    approval status, which is the whole reason both plans are written here rather
    than through the UI.
    """
    payload: dict[str, Any] = {
        "title": title,
        "lesson_type": "syllabus",
        "topic_id": seed.topic_id,
        "syllabus_id": seed.syllabus_id,
        "subject_id": seed.subject_id,
        "class_id": seed.class_id,
        "teacher_id": seed.teacher_profile_id,
        "scheduled_date": (date.today() + timedelta(days=2)).isoformat(),
        "scheduled_time": "10:15:00",
        **fields,
    }
    response = api.post(
        f"/lessons/?branch_id={seed.branch_id}", token=token, json=payload
    )
    assert response.status_code < 400, (
        f"could not seed the lesson {title!r}: "
        f"{response.status_code} {response.text[:300]}"
    )
    return response.json()


@pytest.mark.student
@pytest.mark.scenario(STUDENT_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.lessons.view.student",
    title="Lessons",
    subtitle="Student views lessons",
)
def test_student_reads_the_lessons_planned_for_their_class(
    pupil_lessons: PupilLessons,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A pupil reads their class's approved plans, and can change none of them."""
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert LESSONS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {LESSONS_MODULE!r} for this "
        f"unit — a pupil who is refused the module has no read-only view to show"
    )

    page: Page = demo.page
    lessons = LessonsPage(page, demo.frontend_base_url)
    student = ctx.student

    with demo.step(f"Sign in as {student.full_name}, a pupil in {CLASS_NAME}"):
        login_as(page, demo.frontend_base_url, student)

    with demo.step("Their Academics menu offers Lessons — open it", dwell_ms=1500):
        link = page.get_by_role("link", name=as_pattern(NAV_LESSONS)).first
        expect(link).to_be_visible(timeout=20_000)
        link.click()
        lessons.expect_loaded()
        lessons.expect_no_load_failure()
        lessons.wait_for_rows()

    with demo.step(
        f"There is the plan their school published for {CLASS_NAME}", dwell_ms=1800
    ):
        lessons.search(pupil_lessons.published_title)
        lessons.expect_row(pupil_lessons.published_title)

        expect(
            lessons.cell(pupil_lessons.published_title, COLUMN["class"])
        ).to_have_text(_exact(CLASS_NAME))
        expect(
            lessons.cell(pupil_lessons.published_title, COLUMN["subject"])
        ).to_contain_text(SUBJECT_NAME)
        expect(
            lessons.cell(pupil_lessons.published_title, COLUMN["teacher"])
        ).to_have_text(_exact(ctx.teacher.full_name))
        lessons.expect_status(pupil_lessons.published_title, PLANNED)
        lessons.expect_approval(pupil_lessons.published_title, APPROVED_APPROVAL)

    with demo.step(
        "A plan their teacher has not had signed off yet is not theirs to read",
        dwell_ms=2000,
    ):
        lessons.search(pupil_lessons.draft_title)
        lessons.expect_empty()

    with demo.step(
        "Nothing on the register lets a pupil write lessons, only read them",
        dwell_ms=2000,
    ):
        # Always offered, so that the two absences below cannot pass on a header
        # bar that simply never rendered.
        expect(
            page.get_by_role("button", name=as_pattern(WEEKLY_PLAN_BUTTON))
        ).to_be_visible()
        expect(page.get_by_role("button", name=as_pattern(ADD_BUTTON))).to_have_count(0)
        expect(
            page.get_by_role("button", name=as_pattern(BULK_CREATE_BUTTON))
        ).to_have_count(0)

        lessons.search(pupil_lessons.published_title)
        lessons.expect_row(pupil_lessons.published_title)
        lessons.expect_row_is_read_only(pupil_lessons.published_title)

    with demo.step("Open the plan and read what the lesson will cover", dwell_ms=1500):
        lessons.open_details(pupil_lessons.published_title)

    with demo.step(
        "Objectives, the shape of the lesson, and the homework that follows it",
        dwell_ms=2500,
    ):
        lessons.expect_detail_section("objectives", STUDENT_LESSON_OBJECTIVES)
        lessons.expect_detail_section("description", STUDENT_LESSON_DESCRIPTION)
        lessons.expect_detail_section("structure", STUDENT_LESSON_STRUCTURE)
        lessons.expect_detail_section("homework", STUDENT_LESSON_HOMEWORK)
        # The plan is theirs to read and no more (see the module docstring: this
        # button used to render for every role).
        expect(
            page.get_by_role("button", name=as_pattern(DETAIL_EDIT_BUTTON))
        ).to_have_count(0)

    with demo.step(
        "Behind the screen the pupil may read a lesson, never write one",
        dwell_ms=2000,
    ):
        _expect_lessons_are_read_only_for_student(api, ctx, pupil_lessons)


def _expect_lessons_are_read_only_for_student(
    api: BackendAPI, ctx: SchoolContext, pupil_lessons: PupilLessons
) -> None:
    """Assert the backend gives this pupil the same read-only deal the UI does.

    Without this the UI half proves only that the *frontend* hides the write
    controls, which a hand-built request would walk straight past. Both halves of
    ``LessonService._scope_lessons`` are covered — the approval filter and the
    enrolled-class filter — and every mutating route is checked, so the gate
    cannot regress into being cosmetic.
    """
    assert ctx.student is not None
    token = api.login(ctx.student.email, ctx.student.password)["access_token"]

    # ── the read half: exactly the approved plans for their own class ─────────
    listed = api.get("/lessons/?skip=0&limit=100", token=token)
    assert listed.status_code == 200, (
        f"a pupil holds ('read', 'lessons'), so the register's own list call "
        f"must succeed — got {listed.status_code}: {listed.text[:300]}"
    )
    titles = {str(row.get("title", "")) for row in listed.json()}
    assert pupil_lessons.published_title in titles, (
        f"the approved plan for {CLASS_NAME} is missing from the pupil's list, "
        f"so either the enrollment or the approval scoping regressed; got {titles}"
    )
    assert pupil_lessons.draft_title not in titles, (
        f"a plan still awaiting approval reached the class it was written for — "
        f"LessonService._scope_lessons must filter a student's list down to "
        f"APPROVED plans only; got {titles}"
    )

    approved = api.get(f"/lessons/{pupil_lessons.published_id}", token=token)
    assert approved.status_code == 200, (
        f"the pupil lists the approved plan, so they must be able to open it "
        f"too — got {approved.status_code}: {approved.text[:300]}"
    )
    hidden = api.get(f"/lessons/{pupil_lessons.draft_id}", token=token)
    assert hidden.status_code == 404, (
        f"assert_can_view_lesson uses the same predicate as the list, and hides "
        f"an unapproved plan behind a 404 rather than leaking its existence with "
        f"a 403 — got {hidden.status_code}: {hidden.text[:300]}"
    )

    # ── the write half: refused on the role, whatever the plan ────────────────
    refusals = {
        "create": api.post(
            "/lessons/",
            token=token,
            json={
                "title": f"TEST Pupil Should Not Create This {run_tag()}",
                "description": "Must never be created — a pupil cannot plan lessons.",
                "lesson_type": "adhoc",
                "subject_id": 1,
                "class_id": 1,
                "duration_minutes": 40,
            },
        ),
        "update": api.put(
            f"/lessons/{pupil_lessons.published_id}",
            token=token,
            json={"title": f"TEST Pupil Rewrote This {run_tag()}"},
        ),
        "delete": api.delete(f"/lessons/{pupil_lessons.published_id}", token=token),
        # The approval workflow is staff work too, and it is what decides what
        # this pupil gets to see at all.
        "approve": api.post(
            f"/lessons/{pupil_lessons.draft_id}/approve", token=token
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a pupil holds only ('read', 'lessons'), so every mutating "
            f"/lessons route must refuse them with 403 — got {res.status_code}: "
            f"{res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert STUDENT_ROLE_DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right, but the reason must be the role rather than "
            f"the feature pack — this school *is* licensed for "
            f"{LESSONS_MODULE!r}; got {detail!r}"
        )
