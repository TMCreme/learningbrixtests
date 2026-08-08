"""Student scores — the gradebook a teacher writes into.

Positive path (this file): a teacher of the ``academics_only`` school records a
whole class's marks for one assessment and then corrects one of them
(``test_teacher_records_and_corrects_student_scores``).

Where a *teacher's* student-scores feature actually lives
    Not at /module/student_assessment_score. That route is the pupil-facing
    "Assignments & Scores" page: it calls ``GET /assessments/scores/me`` and
    ``GET /assessments/assignments/me``, both of which answer
    403 INADEQUATE_PERMISSIONS for any caller without a ``student_profile``
    (newschoolapp/api/routes/assessment.py::list_my_scores,
    api/routes/assignment.py::list_my_assignments). Its sidebar entry is gated on
    the ``student_scores`` permission, which the seeded Teacher role does not
    hold at all (db/repository/permissions.py) — so a teacher never even sees the
    link. It is the read surface for the ``…view.student`` and ``…view.guardian``
    units.

    The *write* surface for the same rows is the Score tab of
    /module/assessment_score: "Bulk Score Entry" posts
    ``POST /assessments/scores/bulk`` and the row's "Edit Score" modal puts
    ``/assessments/scores/{id}`` — the very ``StudentScore`` records the pupil
    page later reads back. Both are gated on ``("manage", "assessments")``, which
    the Teacher role does hold, plus ``AssessmentService._assert_can_grade``,
    which narrows it to the (subject, class) pairs the teacher is the **subject
    teacher** of.

What has to exist before the feature is reachable
    Bulk Score Entry is two dependent fetches deep: choosing an assessment loads
    the students of *that assessment's class*, which the backend resolves through
    category → syllabus → class. So the flow needs a syllabus (carrying an
    assessment category) for a class the teacher teaches, a lesson on it, an
    assessment hanging off the category, and a student enrolled in that class for
    the syllabus's academic year — otherwise ``get_class_student_id`` answers 404
    "Student … is not enrolled in class … for academic year …".

    Provisioning supplies the class, the subject and the enrolled student;
    ``tests/flows/academics_seed.py`` supplies the topic/syllabus/category/lesson
    chain **and** the subject-teacher assignment (without which every write here
    is a 403). The assessment itself is seeded over the API by the fixture below
    for the same reason those are: creating one is
    ``academics.assessments.manage.teacher``'s walkthrough, not this one's.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI, Credentials
from tests.fixtures.data_factories import run_tag
from tests.flows.academics_seed import AcademicsSeed, seed_assessment_prerequisites
from tests.flows.school_provisioning import CLASS_NAME, SUBJECT_NAME, SchoolContext
from tests.pages.academics.student_assessment_score import (
    ASSIGNMENT_COLUMN,
    ASSIGNMENT_HEADERS,
    SCORE_COLUMN,
    SCORE_HEADERS,
    TODO_FILTER,
    StudentAssessmentScorePage,
)
from tests.pages.academics.student_scores import COLUMN, StudentScoresPage
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as

SCORES_SCENARIO = "academics_only"

# Named with the "TEST" prefix the orphan sweeper matches on, and with the run
# tag so parallel agents never collide.
ASSESSMENT_NAME = f"TEST Fractions Quiz {run_tag()}"
ASSESSMENT_DESCRIPTION = "Ten questions on equivalent fractions, taken in class."
MAX_MARKS = 25

RECORDED_MARKS = 21
RECORDED_REMARKS = "Confident with equivalent fractions."
CORRECTED_MARKS = 23
CORRECTED_REMARKS = "Re-marked question 7 — full credit after all."

# ScoreTable renders the mark and its denominator as two adjacent spans, and the
# percentage through toFixed(1).
RECORDED_PERCENTAGE = "84.0%"
CORRECTED_PERCENTAGE = "92.0%"


@dataclass
class ScorableAssessment:
    """The assessment this unit puts marks against, and the chain behind it."""

    seed: AcademicsSeed
    assessment_id: int
    name: str
    max_marks: int


@pytest.fixture
def scorable_assessment(
    provisioned_school: SchoolContext, api: BackendAPI
) -> ScorableAssessment:
    """Seed the syllabus chain plus one assessment for the teacher to mark.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.

    Created as the teacher rather than as the SchoolAdmin deliberately: it proves
    the subject-teacher assignment the seed wrote really did take, so a failure
    surfaces here rather than later as an empty dropdown on the bulk-entry form.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert ctx.branches, "provisioning created no branch for this school"

    seed = seed_assessment_prerequisites(
        api,
        ctx.school_admin,
        school_id=ctx.school_id,
        branch_id=int(ctx.branches[0]["id"]),
        subject_name=SUBJECT_NAME,
        class_name=CLASS_NAME,
        teacher_email=ctx.teacher.email,
    )

    token = api.login(ctx.teacher.email, ctx.teacher.password)["access_token"]
    created = api.post(
        f"/assessments/?branch_id={seed.branch_id}",
        token=token,
        json={
            "name": ASSESSMENT_NAME,
            "description": ASSESSMENT_DESCRIPTION,
            "max_marks": MAX_MARKS,
            "category_id": seed.category_id,
            "lesson_id": seed.lesson_id,
            "scheduled_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=7)).isoformat(),
            "is_assignment": False,
        },
    )
    assert created.status_code < 400, (
        "could not seed the assessment the gradebook is supposed to mark — "
        f"{created.status_code}: {created.text[:300]}. A 403 here means the "
        "teacher is not the subject teacher of "
        f"({SUBJECT_NAME}, {CLASS_NAME}); a 400 means the category or lesson id "
        "did not survive seeding."
    )

    return ScorableAssessment(
        seed=seed,
        assessment_id=int(created.json()["id"]),
        name=ASSESSMENT_NAME,
        max_marks=MAX_MARKS,
    )


@pytest.mark.teacher
@pytest.mark.scenario(SCORES_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.student_scores.manage.teacher",
    title="Student Scores",
    subtitle="Teacher creates and manages student scores",
)
def test_teacher_records_and_corrects_student_scores(
    scorable_assessment: ScorableAssessment,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A subject teacher marks a quiz for their class, then re-marks one paper.

    The two halves are the whole feature: ``POST /assessments/scores/bulk``
    creates the gradebook rows, ``PUT /assessments/scores/{id}`` revises one, and
    every derived figure the table shows — the mark out of the maximum, the
    percentage — is recomputed from the assessment, so asserting them proves the
    score really was written rather than merely echoed back into the form.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.student is not None, "provisioning admitted no student for this school"

    page: Page = demo.page
    scores = StudentScoresPage(page, demo.frontend_base_url)
    student_name = ctx.student.full_name
    assessment_name = scorable_assessment.name

    with demo.step(f"Sign in as {ctx.teacher.full_name}, who teaches {SUBJECT_NAME}"):
        login_as(page, demo.frontend_base_url, ctx.teacher)

    with demo.step("Open Assessment & Scores from the Academics menu"):
        scores.open_from_sidebar()

    with demo.step(f"Switch to Scores and pick the {CLASS_NAME} quiz — nothing marked yet"):
        scores.show_scores()
        scores.filter_by_assessment(assessment_name)
        scores.expect_empty()

    with demo.step("Open bulk entry to mark the whole class in one pass"):
        scores.open_bulk_entry()

    with demo.step(f"Choose the quiz — every pupil in {CLASS_NAME} gets a marks box"):
        scores.choose_assessment_to_score(assessment_name)
        # The banner the form draws once the assessment's details have loaded;
        # `.first` because the regex also matches its wrapper.
        expect(
            page.get_by_text(
                re.compile(rf"Max Marks for this assessment:\s*{MAX_MARKS}", re.I)
            ).first
        ).to_be_visible(timeout=20_000)

    with demo.step(f"Award {student_name} {RECORDED_MARKS} of {MAX_MARKS} with a remark"):
        scores.set_student_marks(
            student_name, marks=RECORDED_MARKS, remarks=RECORDED_REMARKS
        )

    with demo.step("Submit the marks — the gradebook now carries the score", dwell_ms=1200):
        scores.submit_scores()
        scores.filter_by_assessment(assessment_name)

        expect(scores.find_row(student_name)).to_be_visible(timeout=20_000)
        expect(scores.cell(student_name, COLUMN["assessment"])).to_contain_text(
            assessment_name
        )
        expect(scores.cell(student_name, COLUMN["score"])).to_have_text(
            _fraction(RECORDED_MARKS, MAX_MARKS)
        )
        expect(scores.cell(student_name, COLUMN["percentage"])).to_contain_text(
            RECORDED_PERCENTAGE
        )
        expect(scores.cell(student_name, COLUMN["remarks"])).to_have_text(
            _exact(RECORDED_REMARKS)
        )

    with demo.step(f"Re-mark the paper: raise it to {CORRECTED_MARKS} and say why"):
        modal = scores.open_edit_score(student_name)
        scores.submit_edit_score(
            modal, marks=CORRECTED_MARKS, remarks=CORRECTED_REMARKS
        )

    with demo.step("The gradebook shows the corrected mark and its new percentage",
                   dwell_ms=1500):
        expect(scores.cell(student_name, COLUMN["score"])).to_have_text(
            _fraction(CORRECTED_MARKS, MAX_MARKS), timeout=20_000
        )
        expect(scores.cell(student_name, COLUMN["percentage"])).to_contain_text(
            CORRECTED_PERCENTAGE
        )
        expect(scores.cell(student_name, COLUMN["remarks"])).to_have_text(
            _exact(CORRECTED_REMARKS)
        )


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)


def _fraction(marks: int, max_marks: int) -> re.Pattern[str]:
    """The Score cell: ``<span>21</span><span>/ 25</span>``.

    The slash is escaped so the same pattern is safe to hand to a *selector*
    later — playwright serialises a Pattern as ``/<source>/<flags>`` and a bare
    slash closes that literal early (see ``tests.pages.base.as_pattern``).
    """
    return re.compile(rf"^\s*{marks}\s*\/\s*{max_marks}\s*$")


# ─────────────── negative path: the unlicensed school's SchoolAdmin ──────────
#
# The gradebook above is where a *teacher* writes marks. This unit is about the
# other end of the same module: the pupil-facing "Assignments & Scores" screen at
# /module/student_assessment_score, which is the only route ``middleware.ts``
# maps onto the ``student_scores`` feature-flag module (MODULE_PATH_MAP, mirrored
# in config/module_catalog.py). /module/student_scores does not exist.
#
# Why a SchoolAdmin is the right role to prove the gate with
#     Because nothing on the client stops them. ``middleware.ts`` exempts a
#     SchoolAdmin from module enforcement outright, ``useModuleGuard`` returns
#     true for "SuperAdmin or SchoolAdmin", and ``usePermissionGuard`` returns
#     early for the same role. The screen really does mount for them, so the
#     denial has to come from the server or it does not exist.
#
# Which half of ``utils.permissions.has_permission`` answers
#     It refuses twice over: first if the caller's *role* holds no
#     ``(read|manage, module)`` pair, and only then if the school's *feature pack*
#     omits the module. Unlike ``lessons``, the seeded SchoolAdmin role does not
#     hold ``student_scores`` at all — db/repository/permissions.py grants it to
#     Student and Guardian only — so today it is the permission half that answers,
#     with "You do not have permission to perform this action".
#
#     Hard-coding that string would break the day someone widens the seed, even
#     though the denial would still be correct (the pack would refuse it
#     instead). So the expected detail is *derived*: the role is read back from
#     ``GET /roles/{id}`` and the assertion demands the plan message when the role
#     holds the module and the permission message when it does not. The licence is
#     asserted separately, so "the pack really does exclude student_scores" is
#     never taken on trust.
#
# What the browser does with that
#     The screen fires both of its fetches in the same effect tick:
#     ``GET /assessments/scores/me`` (gated on ``student_scores``) and
#     ``GET /assessments/assignments/me`` (gated on ``assessments``, which the
#     ``minimal`` pack also omits). The second answers 403 "Feature not available
#     in your plan", which ``shouldRedirectToNoAccess`` in
#     src/utils/handleErrorMessage.ts turns into a hard ``window.location``
#     redirect to /auth/no-access. The first answers 403 "You do not have
#     permission…", which that same helper deliberately does *not* redirect on —
#     it ends in the tab's own ``PageError``.
#
#     Both are correct denials of the same screen, and which one lands first is a
#     race between two fetches, so ``_wait_for_denial`` accepts either surface and
#     the assertions that follow are the invariant holding under both: neither
#     table mounted, no column header, not one row. Pinning the race would make
#     this unit flake for a reason that has nothing to do with student scores.
#
# The sidebar is asserted too, but as a *role* verdict rather than a licence one.
# A branch-less SchoolAdmin never sees the "Academics Module" section at all —
# ``SideNavigation.canShowSection`` gates it on ``branchOnly`` plus a
# ``permissionsGate`` that the null ``currentUserRole`` of a branch-less
# SchoolAdmin cannot satisfy — so "Student Scores" is absent for reasons the
# feature pack has no say in. Worth pinning as a denial surface, not as evidence
# about the pack; the Governance entry asserted alongside it is what keeps "no
# Student Scores link" from passing on a sidebar that never rendered.

STUDENT_SCORES_MODULE = "student_scores"
# The URL segment, which is NOT the module key — see above.
STUDENT_SCORES_ROUTE = "student_assessment_score"
DENIED_SCENARIO = "minimal"
SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The two denials utils/permissions.py can answer with. The permission half runs
# first and short-circuits, so a role lacking the module never reaches the pack
# half and never sees the plan message.
PLAN_DENIAL = re.compile(r"Feature not available in your plan", re.I)
ROLE_DENIAL = re.compile(r"You do not have permission to perform this action", re.I)

# Where the frontend sends someone it has decided is not licensed, and the copy it
# greets them with (src/app/auth/no-access/page.tsx).
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)

# The pupil-facing screen this unit must never see, quoted from
# src/app/module/student_assessment_score/page.tsx and its two table components.
PUPIL_PAGE_HEADING = re.compile(r"^\s*Assignments\s*&\s*Scores\s*$", re.I)
PUPIL_SCORES_TAB = re.compile(r"^\s*Scores\s*$", re.I)
PUPIL_SCORES_COLUMN = re.compile(r"^\s*Assessment Name\s*$", re.I)
PUPIL_ASSIGNMENTS_COLUMN = re.compile(r"^\s*Assignment\s*$", re.I)
# PageError titles, one per tab; each replaces its own tab's table.
PUPIL_ASSIGNMENTS_FAILURE = re.compile(r"Failed to load assignments", re.I)
PUPIL_SCORES_FAILURE = re.compile(r"Failed to load assessment scores", re.I)

# Sidebar entries (SideNavigation/nav-config.tsx). The Governance section is
# ``noBranchOnly``, so it is exactly what a freshly logged-in SchoolAdmin — who
# has selected no branch — sees, which makes it the honest non-vacuous anchor.
NAV_STUDENT_SCORES = re.compile(r"^\s*Student Scores\s*$", re.I)
NAV_GOVERNANCE_ANCHOR = re.compile(r"^\s*School Admin Dashboard\s*$", re.I)

DENIAL_TIMEOUT_S = 30.0


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_student_scores_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `student_scores` off the pack, a SchoolAdmin gets no scores at all."""
    ctx = provisioned_school
    if STUDENT_SCORES_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {STUDENT_SCORES_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. Work out which half of the gate is expected to answer ──────────────
    #
    # Read first so a failure below can never be misread as "the role never had
    # student_scores rights anyway, so the 403s say nothing about the licence".
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    role_holds_module = STUDENT_SCORES_MODULE in role_modules
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
        f"{STUDENT_SCORES_MODULE!r} proves nothing about the gate. Provisioning "
        f"phase A assigns one — check that it did."
    )
    assert STUDENT_SCORES_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {STUDENT_SCORES_MODULE!r} despite "
        f"the {ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 3. The denial itself: every student-scores route is refused ───────────
    #
    # Only routes whose dependency names ``student_scores`` are listed, so a
    # regression in a neighbouring module's gate can never make this pass.
    # ``/scores/me`` is the one the screen calls on mount; the two ward routes are
    # the guardian-facing half of the same module, included so the gate is proven
    # on the module rather than on a single endpoint.
    #
    # The ids in those paths are arbitrary: ``has_permission`` is a route
    # *dependency*, so it answers before the handler ever looks a student up. A
    # 404 here would mean the gate had wrongly let the request through, which is
    # exactly the regression being watched for.
    refusals = {
        "my_scores": api.get("/assessments/scores/me", token=token),
        "ward_assignments": api.get("/assessments/assignments/ward/1", token=token),
        "ward_submission": api.get("/assessments/1/submissions/ward/1", token=token),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) must be refused "
            f"{STUDENT_SCORES_MODULE!r} by {expected_reason} — got "
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
    expect(page.get_by_role("link", name=as_pattern(NAV_STUDENT_SCORES))).to_have_count(0)

    # ── 5. …and typing the route in anyway yields no marks ────────────────────
    goto_module(page, frontend_base_url, STUDENT_SCORES_ROUTE)

    if _wait_for_denial(page) == "no-access":
        # The interceptor threw them out of the module entirely.
        expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(
            timeout=15_000
        )
        expect(page.get_by_text(as_pattern(PUPIL_PAGE_HEADING))).to_have_count(0)
        expect(
            page.get_by_role("button", name=as_pattern(PUPIL_SCORES_TAB))
        ).to_have_count(0)

    # Invariant under both surfaces: the screen put no marks on. Neither table is
    # mounted — a PageError replaces whichever tab failed — so not one column
    # header and not one row survives.
    expect(
        page.get_by_role("columnheader", name=as_pattern(PUPIL_SCORES_COLUMN))
    ).to_have_count(0)
    expect(
        page.get_by_role("columnheader", name=as_pattern(PUPIL_ASSIGNMENTS_COLUMN))
    ).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


def _wait_for_denial(page: Page) -> str:
    """Wait for whichever denial surface this route reaches, and name it.

    Two fetches race on mount (see the section comment above): the assignments one
    is refused with the plan message and redirects to /auth/no-access, the scores
    one is refused with the permission message and ends in a ``PageError``. Both
    are correct denials of the same screen, so this polls for either rather than
    pinning the race — and fails loudly if *neither* arrives, which is the only
    outcome that would mean the screen had been served.
    """
    deadline = time.monotonic() + DENIAL_TIMEOUT_S
    while time.monotonic() < deadline:
        if NO_ACCESS_URL.search(page.url):
            return "no-access"
        for title in (PUPIL_ASSIGNMENTS_FAILURE, PUPIL_SCORES_FAILURE):
            if page.get_by_text(as_pattern(title)).count():
                return "page-error"
        page.wait_for_timeout(250)

    raise AssertionError(
        f"/module/{STUDENT_SCORES_ROUTE} neither redirected to /auth/no-access nor "
        f"reported a failed load within {DENIAL_TIMEOUT_S:.0f}s — the screen "
        f"appears to have been served to a school whose pack excludes "
        f"{STUDENT_SCORES_MODULE!r}. Current URL: {page.url}"
    )


# ──────────────── read-only path: the guardian's ward-scoped view ────────────
#
# Same gradebook rows, read from the other end. /module/student_assessment_score
# is the pupil-facing "Assignments & Scores" screen, and a **guardian** is one of
# only two roles the seed grants ``("read", "student_scores")`` to — Student is
# the other (db/repository/permissions.py). The sidebar entry is gated on exactly
# that permission, so the link is on screen for a guardian straight after login;
# the "Academics Module" section's ``branchOnly`` flag does not apply to them,
# because ``SideNavigation.canShowSection`` treats branch state as a
# SchoolAdmin-only concept.
#
# What a guardian is entitled to read
#     Not their own feed — they have no ``student_profile``, and
#     ``GET /assessments/scores/me`` answers 403 for anyone who hasn't got one.
#     The backend serves them a *ward-scoped* pair instead, and has from the
#     start: ``GET /assessments/assignments/ward/{student_id}`` and
#     ``GET /assessments/scores/ward/{student_id}``, both gated on
#     ``read:student_scores`` and both answering **404 "Student not found"** for a
#     student who is not one of the caller's wards, so a guardian cannot probe
#     other children's existence
#     (``utils/teacher_permissions.assert_guardian_of_student``). The contract is
#     written down in newschoolapp/docs/frontend_assignments.md under "Guardian
#     views". This test asserts it from the browser: the screen a guardian reaches
#     from their own sidebar shows *their ward's* work, and offers no control that
#     would change a grade.
#
# What is seeded, and why over the API
#     The screen only reads. Everything it reads is another module's walkthrough —
#     a topic, a syllabus carrying an assessment category, a lesson, an assessment
#     and a mark against the ward. ``tests/flows/academics_seed`` already builds
#     the first three; the fixture below adds the assessment and the score on top
#     of it as the SchoolAdmin (``assert_can_grade`` and ``_assert_can_manage``
#     both bypass for an admin), exactly as ``school_provisioning._seed_fee_group``
#     seeds the fee group the Add Class dialog insists on. None of it is asserted:
#     it is the ward's homework, not the thing under test.
#
#     Two assessments, because the screen has two tabs — one graded (the Scores
#     tab) and one published assignment due next week (the Assignments tab, which
#     is the tab the screen opens on). Both must be **published**: the feed query
#     filters on it, and an unpublished one would leave the default tab empty for
#     a reason that looks nothing like the cause.

GUARDIAN_SCENARIO = "academics_only"

WARD_GRADED_ASSESSMENT = f"TEST Fractions Class Test {run_tag()}"
WARD_ASSIGNMENT_NAME = f"TEST Fractions Worksheet {run_tag()}"
WARD_GRADED_MAX_MARKS = 100
WARD_GRADED_MARKS = 82
# AssessmentScoresTable renders the percentage through toFixed(1).
WARD_GRADED_PERCENTAGE = "82.0%"
WARD_GRADED_REMARK = "Handled the harder denominators without prompting."
WARD_ASSIGNMENT_MAX_MARKS = 20
WARD_ASSIGNMENT_DUE_IN_DAYS = 7

# AssignmentsFeedTable renders the backend's sentinel with its underscore swapped
# for a space, so an unsubmitted assignment reads "not submitted" in Status.
NOT_SUBMITTED = re.compile(r"not\s+submitted", re.I)

# GuardianView.tsx — the landing page a guardian is dropped on after login.
WARDS_HEADING = re.compile(r"Your Ward", re.I)


class WardWorkSeedError(RuntimeError):
    """A prerequisite could not be seeded, so the ward's screen would be empty."""


@dataclass
class WardWork:
    """The marked work the guardian is expected to find, plus whose it is."""

    student_profile_id: int
    ward_name: str
    graded_assessment: str
    assignment_name: str


@pytest.fixture
def ward_work(provisioned_school: SchoolContext, api: BackendAPI) -> WardWork:
    """Give the provisioned ward one graded test and one open assignment.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert ctx.guardian is not None, "provisioning created no guardian for this school"
    assert ctx.branches, "provisioning created no branch for this school"

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
    return _seed_ward_work(api, ctx.school_admin, ctx.student, seed, branch_id=branch_id)


@pytest.mark.guardian
@pytest.mark.scenario(GUARDIAN_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.student_scores.view.guardian",
    title="Student Scores",
    subtitle="Guardian views student scores",
)
def test_guardian_views_ward_assessment_scores(
    ward_work: WardWork,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A guardian reads their ward's assignments and marks, and can change none of it.

    Every figure asserted is derived server-side from the assessment — the mark
    over its maximum, the percentage — so matching them proves the screen really
    fetched the ward's gradebook rather than rendering something it was handed.
    """
    ctx = provisioned_school
    assert ctx.guardian is not None, "provisioning created no guardian for this school"

    page: Page = demo.page
    scores = StudentAssessmentScorePage(page, demo.frontend_base_url)

    with demo.step(f"Sign in as {ctx.guardian.full_name}, a parent at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.guardian)

    with demo.step(f"Home opens on the child they look after — {ward_work.ward_name}"):
        expect(
            page.get_by_role("heading", name=as_pattern(WARDS_HEADING))
        ).to_be_visible(timeout=25_000)
        expect(
            page.get_by_text(as_pattern(re.escape(ward_work.ward_name))).first
        ).to_be_visible(timeout=20_000)

    with demo.step("Open Student Scores from the Academics menu"):
        scores.open_from_sidebar().expect_loaded()
        scores.expect_no_load_failure()
        scores.wait_for_table()

    with demo.step("The screen opens on what the ward still has to hand in"):
        scores.expect_headers(ASSIGNMENT_HEADERS)
        scores.filter_assignments(TODO_FILTER)
        scores.expect_row(ward_work.assignment_name)
        expect(
            scores.cell(ward_work.assignment_name, ASSIGNMENT_COLUMN["subject"])
        ).to_have_text(_exact(SUBJECT_NAME))
        expect(
            scores.cell(ward_work.assignment_name, ASSIGNMENT_COLUMN["status"])
        ).to_contain_text(NOT_SUBMITTED)
        scores.expect_no_load_failure()

    with demo.step("Switch to Scores to see how the ward's marked work went"):
        scores.open_scores_tab()
        scores.expect_no_load_failure()
        scores.expect_headers(SCORE_HEADERS)

    with demo.step(
        f"The class test comes back at {WARD_GRADED_MARKS} out of "
        f"{WARD_GRADED_MAX_MARKS}, with the teacher's remark",
        dwell_ms=1500,
    ):
        scores.expect_row(ward_work.graded_assessment)
        marks = scores.cell(ward_work.graded_assessment, SCORE_COLUMN["marks"])
        expect(marks).to_contain_text(str(WARD_GRADED_MARKS))
        expect(marks).to_contain_text(str(WARD_GRADED_MAX_MARKS))
        expect(
            scores.cell(ward_work.graded_assessment, SCORE_COLUMN["percentage"])
        ).to_contain_text(WARD_GRADED_PERCENTAGE)
        expect(
            scores.cell(ward_work.graded_assessment, SCORE_COLUMN["remarks"])
        ).to_contain_text(WARD_GRADED_REMARK)

    with demo.step("A guardian may read the gradebook — never write to it", dwell_ms=1200):
        scores.expect_write_controls_absent()


# ───────── setup-only seeding for the guardian path (never asserted) ─────────


def _seed_ward_work(
    api: BackendAPI,
    school_admin: Credentials,
    student: Credentials,
    seed: AcademicsSeed,
    *,
    branch_id: int,
) -> WardWork:
    """One graded assessment and one open assignment, both against the ward."""
    token = _seed_login(api, school_admin)
    student_profile_id, ward_name = _ward_profile(
        api, token, branch_id=branch_id, email=student.email
    )
    _assert_ward_has_a_guardian(api, token, student_profile_id, branch_id=branch_id)

    today = date.today()

    graded_id = _create_assessment(
        api, token, branch_id=branch_id, category_id=seed.category_id,
        lesson_id=seed.lesson_id,
        payload={
            "name": WARD_GRADED_ASSESSMENT,
            "description": "Seeded so the ward's Scores tab has something to show.",
            "max_marks": WARD_GRADED_MAX_MARKS,
            "scheduled_date": (today - timedelta(days=1)).isoformat(),
        },
    )
    _publish_assessment(api, token, graded_id, branch_id=branch_id)
    _record_ward_score(
        api, token, branch_id=branch_id, assessment_id=graded_id,
        student_profile_id=student_profile_id,
    )

    assignment_id = _create_assessment(
        api, token, branch_id=branch_id, category_id=seed.category_id,
        lesson_id=seed.lesson_id,
        payload={
            "name": WARD_ASSIGNMENT_NAME,
            "description": "Seeded so the ward's Assignments tab has something to show.",
            "max_marks": WARD_ASSIGNMENT_MAX_MARKS,
            "scheduled_date": today.isoformat(),
            "due_date": (today + timedelta(days=WARD_ASSIGNMENT_DUE_IN_DAYS)).isoformat(),
            "is_assignment": True,
            "allow_late_submissions": True,
        },
    )
    _publish_assessment(api, token, assignment_id, branch_id=branch_id)

    return WardWork(
        student_profile_id=student_profile_id,
        ward_name=ward_name,
        graded_assessment=WARD_GRADED_ASSESSMENT,
        assignment_name=WARD_ASSIGNMENT_NAME,
    )


def _seed_login(api: BackendAPI, creds: Credentials) -> str:
    try:
        return str(api.login(creds.email, creds.password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise WardWorkSeedError(f"could not log in as {creds.email}: {exc}") from exc


def _seed_rows(payload) -> list[dict]:
    """Some list endpoints answer a bare list, others a paginated envelope."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _ward_profile(api: BackendAPI, token: str, *, branch_id: int,
                  email: str) -> tuple[int, str]:
    """The admitted student's StudentProfile id and the name the UI renders.

    The name is assembled the way every list in this app assembles it —
    ``first_name other_names`` — so the guardian's home page and the ward's own
    row can be matched on the same string.
    """
    response = api.get(f"/student/?branch_id={branch_id}&limit=100", token=token)
    if response.status_code >= 400:
        raise WardWorkSeedError(
            f"could not list students in branch {branch_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    for row in _seed_rows(response.json()):
        user = row.get("user") or {}
        if str(user.get("email", "")).casefold() == email.casefold():
            name = f"{user.get('first_name', '')} {user.get('other_names', '')}".strip()
            return int(row["id"]), name
    raise WardWorkSeedError(
        f"no student profile for {email!r} in branch {branch_id} — provisioning "
        "phase C should have admitted one."
    )


def _assert_ward_has_a_guardian(api: BackendAPI, token: str, student_profile_id: int,
                                *, branch_id: int) -> None:
    """Fail loudly here rather than as an empty screen later.

    The guardian's whole view hangs off ``GuardianProfile.students``. If the
    admission wizard's guardian picker ever stopped writing that link, every ward
    endpoint answers 404 "Student not found" and the screen merely looks empty —
    a symptom with none of the cause in it. One extra request buys the diagnosis.
    """
    response = api.get(f"/student/{student_profile_id}?branch_id={branch_id}", token=token)
    if response.status_code >= 400:
        raise WardWorkSeedError(
            f"could not read student {student_profile_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    if not _seed_rows(response.json().get("guardians") or []):
        raise WardWorkSeedError(
            f"student {student_profile_id} has no guardian linked to them, so no "
            "guardian is entitled to read their scores. Provisioning phase C "
            "admits the student through the admission wizard's guardian picker, "
            "which is what writes that link."
        )


def _create_assessment(api: BackendAPI, token: str, *, branch_id: int, category_id: int,
                       lesson_id: int, payload: dict) -> int:
    body = {**payload, "category_id": category_id, "lesson_id": lesson_id}
    response = api.post(f"/assessments/?branch_id={branch_id}", token=token, json=body)
    if response.status_code >= 400:
        raise WardWorkSeedError(
            f"could not seed the assessment {payload.get('name')!r}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return int(response.json()["id"])


def _publish_assessment(api: BackendAPI, token: str, assessment_id: int, *,
                        branch_id: int) -> None:
    response = api.post(
        f"/assessments/{assessment_id}/publish?branch_id={branch_id}", token=token
    )
    if response.status_code >= 400:
        raise WardWorkSeedError(
            f"could not publish assessment {assessment_id}: "
            f"{response.status_code} {response.text[:300]}"
        )


def _record_ward_score(api: BackendAPI, token: str, *, branch_id: int,
                       assessment_id: int, student_profile_id: int) -> None:
    """Put a mark against the ward.

    ``class_student_id`` is left out on purpose: the backend derives it from the
    student and the assessment's syllabus (class + academic year + term), which is
    the very enrollment provisioning phase D wrote.
    """
    response = api.post(
        f"/assessments/scores/bulk?branch_id={branch_id}",
        token=token,
        json={
            "assessment_id": assessment_id,
            "scores": [
                {
                    "student_id": student_profile_id,
                    "marks_obtained": WARD_GRADED_MARKS,
                    "remarks": WARD_GRADED_REMARK,
                }
            ],
        },
    )
    if response.status_code >= 400:
        raise WardWorkSeedError(
            f"could not record a score for student {student_profile_id} on "
            f"assessment {assessment_id}: {response.status_code} {response.text[:300]}"
        )


# ─────────────── read-only path: the pupil reading their own marks ───────────
#
# The third and last audience for the same ``StudentScore`` rows, and the only
# one the endpoints were named after. /module/student_assessment_score resolves
# its viewer from the signed-in profile (``page.tsx::GradebookViewer``): a caller
# who has a ``student_profile`` is ``kind: "self"`` and reads the ``/me`` pair —
# ``GET /assessments/assignments/me`` and ``GET /assessments/scores/me`` — which
# derive the student from the token rather than from anything in the URL. There
# is no id a pupil could tamper with to read someone else's marks; that is the
# whole point of the ``/me`` twins existing beside the ``/ward/{id}`` ones.
#
# Why the Student role reaches it at all
#     ``read:student_scores`` is seeded onto exactly two roles, Student and
#     Guardian (db/repository/permissions.py), and the "Student Scores" sidebar
#     entry is gated on that same permission plus the ``student_scores`` module.
#     The "Academics Module" section's ``branchOnly`` flag does not keep a pupil
#     out — ``SideNavigation.canShowSection`` treats branch state as a
#     SchoolAdmin-only concept — so the link is on screen straight after login,
#     which is how this demo reaches the screen.
#
# How this differs from the guardian unit above
#     Not merely "a different login". The guardian test proves the ward-scoped
#     read; this one proves the self-scoped read, which is a different pair of
#     endpoints behind the same two tabs. It also asserts the one control a pupil
#     legitimately *does* get and a guardian never does: the Assignments tab's
#     "Submit" action on work not yet handed in. The Scores tab stays read-only
#     for both — a pupil may see their mark and may not touch it — so
#     ``expect_write_controls_absent`` is asserted there, on the tab where it is
#     actually a claim about permissions rather than about layout.
#
# What is seeded, and why over the API
#     Same reasoning as the guardian fixture: one graded assessment and one open
#     assignment against the provisioned pupil, written as the SchoolAdmin
#     (``_assert_can_grade``/``_assert_can_manage`` both bypass for an admin).
#     Creating them is ``academics.assessments.manage.teacher``'s walkthrough, not
#     this one's. Both are published, because the feed query filters on it and an
#     unpublished one would leave the default tab empty for a reason that looks
#     nothing like the cause. The names are distinct from the guardian unit's so
#     the two tests can share one provisioned school without either reading the
#     other's rows.

STUDENT_SCENARIO = "academics_only"

OWN_GRADED_ASSESSMENT = f"TEST Fractions End of Unit Test {run_tag()}"
OWN_ASSIGNMENT_NAME = f"TEST Fractions Practice Sheet {run_tag()}"
OWN_GRADED_MAX_MARKS = 50
OWN_GRADED_MARKS = 37
# AssessmentScoresTable renders the percentage through toFixed(1).
OWN_GRADED_PERCENTAGE = "74.0%"
OWN_GRADED_REMARK = "Neat working — watch the mixed-number conversions."
OWN_ASSIGNMENT_MAX_MARKS = 30
OWN_ASSIGNMENT_DUE_IN_DAYS = 5

# AssignmentsFeedTable's Action button, whose label is "Submit" while the work is
# still ``not_submitted`` and "View submission" afterwards.
SUBMIT_ACTION = re.compile(r"^\s*Submit\s*$", re.I)


@dataclass
class OwnWork:
    """The pupil's own marked work, and the name their row is rendered under."""

    student_profile_id: int
    student_name: str
    graded_assessment: str
    assignment_name: str


@pytest.fixture
def own_work(provisioned_school: SchoolContext, api: BackendAPI) -> OwnWork:
    """Give the provisioned pupil one graded test and one open assignment.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert ctx.branches, "provisioning created no branch for this school"

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
    return _seed_own_work(api, ctx.school_admin, ctx.student, seed, branch_id=branch_id)


@pytest.mark.student
@pytest.mark.scenario(STUDENT_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.student_scores.view.student",
    title="Student Scores",
    subtitle="Student views student scores",
)
def test_student_views_own_assessment_scores(
    own_work: OwnWork,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A pupil reads their own assignments and marks, and can change none of them.

    Every figure asserted is derived server-side from the assessment — the mark
    over its maximum, the percentage — so matching them proves the screen really
    fetched this pupil's gradebook rather than rendering something it was handed.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"

    page: Page = demo.page
    scores = StudentAssessmentScorePage(page, demo.frontend_base_url)

    with demo.step(f"Sign in as {ctx.student.full_name}, a pupil at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, ctx.student)

    with demo.step("A pupil's own menu carries Student Scores under Academics"):
        expect(
            page.get_by_role("link", name=as_pattern(NAV_STUDENT_SCORES)).first
        ).to_be_visible(timeout=25_000)

    with demo.step("Open it — this is their gradebook, nobody else's"):
        scores.open_from_sidebar().expect_loaded()
        scores.expect_no_load_failure()
        scores.wait_for_table()

    with demo.step("The screen opens on the work still to hand in"):
        scores.expect_headers(ASSIGNMENT_HEADERS)
        scores.filter_assignments(TODO_FILTER)
        scores.expect_row(own_work.assignment_name)
        expect(
            scores.cell(own_work.assignment_name, ASSIGNMENT_COLUMN["subject"])
        ).to_have_text(_exact(SUBJECT_NAME))
        expect(
            scores.cell(own_work.assignment_name, ASSIGNMENT_COLUMN["status"])
        ).to_contain_text(NOT_SUBMITTED)
        # The mark is still blank, but the paper is already out of 30.
        expect(
            scores.cell(own_work.assignment_name, ASSIGNMENT_COLUMN["marks"])
        ).to_contain_text(str(OWN_ASSIGNMENT_MAX_MARKS))
        scores.expect_no_load_failure()

    with demo.step("Unlike a parent, the pupil is offered a way to hand it in"):
        expect(
            scores.cell(own_work.assignment_name, ASSIGNMENT_COLUMN["action"])
            .get_by_role("button", name=as_pattern(SUBMIT_ACTION))
        ).to_be_visible(timeout=15_000)

    with demo.step("Switch to Scores to see how the marked work went"):
        scores.open_scores_tab()
        scores.expect_no_load_failure()
        scores.expect_headers(SCORE_HEADERS)

    with demo.step(
        f"The unit test comes back at {OWN_GRADED_MARKS} out of "
        f"{OWN_GRADED_MAX_MARKS}, with the teacher's remark",
        dwell_ms=1500,
    ):
        scores.expect_row(own_work.graded_assessment)
        marks = scores.cell(own_work.graded_assessment, SCORE_COLUMN["marks"])
        expect(marks).to_contain_text(str(OWN_GRADED_MARKS))
        expect(marks).to_contain_text(str(OWN_GRADED_MAX_MARKS))
        expect(
            scores.cell(own_work.graded_assessment, SCORE_COLUMN["percentage"])
        ).to_contain_text(OWN_GRADED_PERCENTAGE)
        expect(
            scores.cell(own_work.graded_assessment, SCORE_COLUMN["remarks"])
        ).to_contain_text(OWN_GRADED_REMARK)

    with demo.step("A pupil may read their marks — never revise them", dwell_ms=1200):
        scores.expect_write_controls_absent()


# ───────── setup-only seeding for the student path (never asserted) ──────────


def _seed_own_work(
    api: BackendAPI,
    school_admin: Credentials,
    student: Credentials,
    seed: AcademicsSeed,
    *,
    branch_id: int,
) -> OwnWork:
    """One graded assessment and one open assignment, both against the pupil.

    ``_ward_profile`` is reused verbatim: despite the name it only resolves an
    admitted student's ``StudentProfile`` id and the ``first_name other_names``
    string every list in this app renders them under — which is the same lookup
    whoever is going to read the row.
    """
    token = _seed_login(api, school_admin)
    student_profile_id, student_name = _ward_profile(
        api, token, branch_id=branch_id, email=student.email
    )

    today = date.today()

    graded_id = _create_assessment(
        api, token, branch_id=branch_id, category_id=seed.category_id,
        lesson_id=seed.lesson_id,
        payload={
            "name": OWN_GRADED_ASSESSMENT,
            "description": "Seeded so the pupil's Scores tab has something to show.",
            "max_marks": OWN_GRADED_MAX_MARKS,
            "scheduled_date": (today - timedelta(days=2)).isoformat(),
        },
    )
    _publish_assessment(api, token, graded_id, branch_id=branch_id)
    _record_own_score(
        api, token, branch_id=branch_id, assessment_id=graded_id,
        student_profile_id=student_profile_id,
    )

    assignment_id = _create_assessment(
        api, token, branch_id=branch_id, category_id=seed.category_id,
        lesson_id=seed.lesson_id,
        payload={
            "name": OWN_ASSIGNMENT_NAME,
            "description": "Seeded so the pupil's Assignments tab has something to show.",
            "max_marks": OWN_ASSIGNMENT_MAX_MARKS,
            "scheduled_date": today.isoformat(),
            "due_date": (today + timedelta(days=OWN_ASSIGNMENT_DUE_IN_DAYS)).isoformat(),
            "is_assignment": True,
            "allow_late_submissions": True,
        },
    )
    _publish_assessment(api, token, assignment_id, branch_id=branch_id)

    return OwnWork(
        student_profile_id=student_profile_id,
        student_name=student_name,
        graded_assessment=OWN_GRADED_ASSESSMENT,
        assignment_name=OWN_ASSIGNMENT_NAME,
    )


def _record_own_score(api: BackendAPI, token: str, *, branch_id: int,
                      assessment_id: int, student_profile_id: int) -> None:
    """Put this unit's mark against the pupil.

    ``class_student_id`` is left out on purpose: the backend derives it from the
    student and the assessment's syllabus (class + academic year + term), which is
    the very enrollment provisioning phase D wrote.
    """
    response = api.post(
        f"/assessments/scores/bulk?branch_id={branch_id}",
        token=token,
        json={
            "assessment_id": assessment_id,
            "scores": [
                {
                    "student_id": student_profile_id,
                    "marks_obtained": OWN_GRADED_MARKS,
                    "remarks": OWN_GRADED_REMARK,
                }
            ],
        },
    )
    if response.status_code >= 400:
        raise WardWorkSeedError(
            f"could not record a score for student {student_profile_id} on "
            f"assessment {assessment_id}: {response.status_code} {response.text[:300]}"
        )
