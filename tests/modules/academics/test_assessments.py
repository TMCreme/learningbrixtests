"""/module/assessment_score — the "Manage Assessment & Scores" workspace.

Positive path: a teacher of the ``academics_only`` school creates an assessment
and then edits it (``test_teacher_creates_and_publishes_assessment``).

Read-only path: a SchoolAdmin of that same school reads the assessment register
and the score sheet without writing anything
(``test_school_admin_views_assessments``).

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack does
NOT include ``assessments`` (``test_assessments_denied_for_school_admin_when_module_disabled``).

Where the denial actually lives
    Not in the sidebar, and not in a route guard. ``src/middleware.ts`` skips its
    module gate for a SchoolAdmin ("SchoolAdmin bypasses: governance pages are
    not feature-flag modules"), and both ``useModuleGuard`` and
    ``usePermissionGuard`` return early for that role too — so
    /module/assessment_score really does mount for them. The seeded SchoolAdmin
    role also *holds* ``("manage", "assessments")``
    (newschoolapp/db/repository/permissions.py), so the permission half of the
    backend gate passes as well.

    What actually denies them is the feature-pack half of
    ``utils.permissions.has_permission``: every ``/assessments`` route answers
    **403 "Feature not available in your plan"**. That 403 is the assertion this
    test is built on.

    The UI consequence follows from it, and it is a redirect rather than an
    in-page error. ``setupAxiosInterceptors`` (src/utils/handleErrorMessage.ts)
    inspects every rejected response: a 403 whose detail matches
    ``shouldRedirectToNoAccess``'s plan-restriction indicators triggers a hard
    ``window.location.href = "/auth/no-access"`` and rejects with
    ``FeatureNotAvailableError``. So the Assessment tab's mount-time
    ``GetAllAssessments`` never reaches its own ``setFetchError`` branch — the
    ``PageError`` panel ("Failed to load assessments") is what an *unrelated*
    failure would render, and asserting it here would assert the wrong denial.
    The test therefore waits for /auth/no-access and its "Access Restricted" /
    "Module Activation Required" copy, and separately proves the workspace's
    controls are nowhere on screen.

    Deliberately *not* asserted: that the sidebar hides "Assessment & Scores".
    For a SchoolAdmin that entry is gated on the role permission, not on the
    feature pack (SideNavigation: "Permission check takes priority — having the
    permission implies the module is available"), so its absence on the landing
    dashboard says nothing about this school's pack.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.academics_seed import AcademicsSeed, seed_assessment_prerequisites
from tests.flows.school_provisioning import (
    BRANCH_ADDRESS,
    BRANCH_NAME,
    BRANCH_PHONE,
    CLASS_NAME,
    SUBJECT_NAME,
    SchoolContext,
)
from tests.pages.academics.assessments import COLUMN, AssessmentsPage
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

ASSESSMENTS_MODULE = "assessments"
ASSESSMENTS_ROUTE = "assessment_score"
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

# Real strings from src/app/module/assessment_score/(views)/Assessment/page.tsx.
SEARCH_PLACEHOLDER = re.compile(r"Search assessments", re.I)
CREATE_BUTTON = re.compile(r"Create Assessment", re.I)
# The workspace header itself (src/app/module/assessment_score/page.tsx), which
# mounts before any fetch — so its absence is what proves the user did not merely
# lose the table, they lost the page.
WORKSPACE_HEADING = re.compile(r"Manage Assessment\s*&\s*Scores", re.I)
# src/components/common/PageError.tsx, mounted with this exact title.
LOAD_FAILURE_TITLE = re.compile(r"Failed to load assessments", re.I)
# Where the axios interceptor sends a user whose 403 names a plan restriction,
# and the copy that greets them (src/app/auth/no-access/page.tsx).
NO_ACCESS_URL = re.compile(r"/auth/no-access")
ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_assessments_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `assessments` off the pack, a SchoolAdmin gets no workspace and no data."""
    ctx = provisioned_school
    if ASSESSMENTS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {ASSESSMENTS_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had assessments rights anyway", which would make the 403s
    # vacuous.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert ASSESSMENTS_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds an "
        f"{ASSESSMENTS_MODULE!r} permission, so this test would be asserting a "
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
        f"{ASSESSMENTS_MODULE!r} proves nothing about the gate. Provisioning "
        f"phase A assigns one — check that it did."
    )
    assert ASSESSMENTS_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {ASSESSMENTS_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every assessments route is refused ──────────────
    branch_id = int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    branch_query = f"&branch_id={branch_id}" if branch_id else ""

    refusals = {
        # What the Assessment tab itself calls on mount.
        "list": api.get(f"/assessments/?skip=0&limit=10{branch_query}", token=token),
        # Read of the categories the create form would need.
        "categories": api.get("/assessments/categories", token=token),
        # And the write half of the module, so the gate is not read-only.
        "create": api.post(
            f"/assessments/?branch_id={branch_id}" if branch_id else "/assessments/",
            token=token,
            json={
                "name": "TEST Unlicensed Assessment",
                "description": "Must never be created — the pack excludes assessments.",
                "max_marks": 100,
                "category_id": 1,
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{ASSESSMENTS_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts an assessments workspace in front of them ───
    login_as(page, frontend_base_url, ctx.school_admin)
    goto_module(page, frontend_base_url, ASSESSMENTS_ROUTE)

    # A SchoolAdmin is exempt from both frontend guards, so /module/assessment_score
    # really does mount and really does ask for the list — which is refused, and
    # the axios interceptor turns that answer into a hard redirect (see the module
    # docstring). Waiting for the URL is therefore also what stops the "workspace
    # is absent" assertions below from passing merely because the page had not
    # finished loading yet.
    try:
        page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    except PlaywrightTimeoutError as exc:
        raise AssertionError(
            "/module/assessment_score did not redirect a SchoolAdmin of "
            f"{ctx.school_name!r} to /auth/no-access within 25s — current url "
            f"{page.url!r}. If the assessments workspace rendered instead, the "
            "feature-pack gate is not being enforced for this school."
        ) from exc

    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(
        timeout=15_000
    )
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the workspace survived the redirect — neither its header, nor
    # the controls a licensed SchoolAdmin would have, nor a single table row.
    expect(page.get_by_text(as_pattern(WORKSPACE_HEADING))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(CREATE_BUTTON))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


# ─────────────────── read-only path: SchoolAdmin views ───────────────────────

VIEW_SCENARIO = "academics_only"

# The second tab of src/app/module/assessment_score/page.tsx. The first
# ("Assessment") is AssessmentsPage's own; the workspace renders one at a time.
SCORE_TAB = re.compile(r"^\s*Score\s*$", re.I)

# The sidebar entry for this module (SideNavigation/nav-config.tsx). It sits in
# the "Academics Module" section, which is `branchOnly: true` — for a SchoolAdmin
# it does not render at all until the branch store is filled.
NAV_ASSESSMENTS = re.compile(r"^\s*Assessment\s*&\s*Scores\s*$", re.I)

# Somewhere inside the app shell to come back to after picking a branch; see
# the "Academics menu" step for why the journey has to pass through here.
HOME_ROUTE = "home"

# The status Select initialises to "all", which *does* match a SelectItem, so
# its trigger renders that item's label rather than the "Status" placeholder —
# which is what makes filtering the combobox by its own text work here.
STATUS_ALL = re.compile(r"^\s*All Statuses\s*$", re.I)
STATUS_PUBLISHED = re.compile(r"^\s*Published\s*$", re.I)

# AssessmentTable.tsx / ScoreTable.tsx column headers, in render order.
ASSESSMENT_COLUMNS = (
    "Name", "Lesson", "Category", "Max Marks",
    "Status", "Scheduled Date", "Due Date", "Actions",
)
SCORE_COLUMNS = (
    "Student Name", "ID Number", "Assessment", "Score",
    "Percentage", "Weighted", "Remarks", "Date", "Actions",
)

# The empty states each table settles on when the school has no rows yet.
ASSESSMENTS_EMPTY = re.compile(r"No assessments found\.", re.I)
SCORES_EMPTY = re.compile(r"No scores found\.", re.I)
SCORES_FAILURE_TITLE = re.compile(r"Failed to load scores", re.I)


@pytest.mark.school_admin
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.assessments.view.school_admin",
    title="Assessments",
    subtitle="SchoolAdmin views assessments",
)
def test_school_admin_views_assessments(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin reads both halves of the workspace and writes nothing.

    The read itself is the feature: ``GET /assessments/`` and
    ``GET /assessments/{id}/scores`` are branch-scoped for this role, so the
    assertions are that both tables *render their own content* — column headers
    plus either real rows or the module's own empty state — rather than the
    ``PageError`` panel each tab falls back to when its fetch is refused.

    "Create Assessment" is deliberately not asserted absent: the seeded
    SchoolAdmin role holds ``("manage", "assessments")``, so the button is
    expected to be there. This test simply never presses it.
    """
    ctx = provisioned_school
    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    assessments = AssessmentsPage(page, base_url)

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step("Choose the campus whose records to review"):
        branch_name = _activate_branch(page, base_url, ctx)

    with demo.step(f"Back inside {branch_name}, the Academics menu is now on offer"):
        # Not scene-setting, and not a shortcut past the UI either. Opening a
        # branch hands off to a hardcoded ``router.push("/module/community")``
        # (school_admin_dashboard/page.tsx), and this scenario's pack has no
        # `community` — so that page's own 403 becomes a hard redirect to
        # /auth/no-access, which renders no sidebar at all. Home is the nearest
        # place inside the app shell to pick the journey back up; the module
        # itself is still reached the way a real user reaches it, by clicking
        # its sidebar entry below.
        goto_module(page, base_url, HOME_ROUTE)
        nav_link = page.get_by_role("link", name=as_pattern(NAV_ASSESSMENTS)).first
        expect(nav_link).to_be_visible(timeout=30_000)

    with demo.step("Open the Assessment & Scores workspace"):
        nav_link.click()
        page.wait_for_url(re.compile(rf"/module/{ASSESSMENTS_ROUTE}"), timeout=20_000)
        assessments.expect_loaded()
        expect(
            page.get_by_role("button", name=as_pattern(SCORE_TAB)).first
        ).to_be_visible()

    with demo.step("Read the assessment register for this campus"):
        _wait_for_table(page, ASSESSMENTS_EMPTY)
        expect(page.get_by_text(as_pattern(LOAD_FAILURE_TITLE))).to_have_count(0)
        _expect_columns(page, ASSESSMENT_COLUMNS)

    with demo.step("Narrow the register down to published assessments"):
        assessments.select_option_in_combobox(STATUS_ALL, STATUS_PUBLISHED)
        expect(
            page.get_by_role("combobox").filter(has_text=as_pattern(STATUS_PUBLISHED))
        ).to_be_visible()
        _wait_for_table(page, ASSESSMENTS_EMPTY)
        expect(page.get_by_text(as_pattern(LOAD_FAILURE_TITLE))).to_have_count(0)

    with demo.step("Switch to the Score tab to review recorded marks", dwell_ms=1200):
        page.get_by_role("button", name=as_pattern(SCORE_TAB)).first.click()
        _wait_for_table(page, SCORES_EMPTY)
        expect(page.get_by_text(as_pattern(SCORES_FAILURE_TITLE))).to_have_count(0)
        _expect_columns(page, SCORE_COLUMNS)


def _activate_branch(page: Page, base_url: str, ctx: SchoolContext) -> str:
    """Give the SchoolAdmin an active branch, and return its name.

    Mandatory before *reading* anything here, not just before writing: a
    SchoolAdmin belongs to no branch, ``GET /assessments/`` answers 400
    BRANCH_ID_REQUIRED without one (api/routes/assessment.py::list_assessments),
    and the frontend only sends ``branch_id`` when ``useBranchStore`` is filled —
    which only the branch row's "View" button does.

    Provisioning normally leaves one behind on ``ctx.branches``; the create is a
    fallback for a school whose phase B skipped it, so this unit does not fail
    for a reason that has nothing to do with assessments.

    ``expect_loaded`` before the row lookup is what keeps that fallback honest:
    ``open()`` only waits for the heading, and the rows arrive with
    ``GET /branch/members/statistics``. Counting too early sees zero rows on a
    school that has a branch, creates a *second* one, and makes it active — so
    every read below would then be scoped to an empty campus rather than to the
    one provisioning put the class and the subject in.
    """
    branches = BranchesPage(page, base_url).open().expect_loaded()
    name = str(ctx.branches[0]["name"]) if ctx.branches else ""

    if not name or branches.find_row(name).count() == 0:
        name = f"TEST {BRANCH_NAME} {run_tag()}"
        branches.create_branch(name=name, address=BRANCH_ADDRESS, phone=BRANCH_PHONE)

    branches.select_branch(name)
    return name


def _wait_for_table(page: Page, empty_message: re.Pattern, timeout_ms: int = 30_000) -> None:
    """Block until the table has finished loading, whether or not it has rows.

    Both tables render their header immediately and swap a spinner row for
    either data rows or an empty-state row, so asserting on the header alone
    would pass while the fetch was still in flight — and would therefore also
    pass a moment before ``PageError`` replaced the whole tab. Every data row
    starts with a ``font-medium`` cell; the empty state is a single centred
    message.
    """
    body = page.locator("table tbody")
    settled = body.get_by_text(as_pattern(empty_message)).first.or_(
        body.locator("td.font-medium").first
    )
    expect(settled.first).to_be_visible(timeout=timeout_ms)


def _expect_columns(page: Page, columns: tuple[str, ...]) -> None:
    """Assert the table's header row spells out ``columns``.

    Not ``get_by_role("columnheader")``: these ``<th>``s carry no ``scope``
    attribute (src/components/ui/table.tsx renders a bare ``<th>``), and
    Playwright's role computation maps such a cell to ``cell``, not
    ``columnheader`` — so that locator matches nothing at all here. The header
    row itself is the reliable anchor.
    """
    header = page.locator("table thead tr").first
    expect(header).to_be_visible(timeout=15_000)
    for column in columns:
        cell = header.locator("th").filter(
            has_text=re.compile(rf"^\s*{re.escape(column)}\s*$", re.I)
        )
        expect(cell.first).to_be_visible()


# ───────────────────── positive path: teacher manages ────────────────────────
#
# Everything the Create Assessment modal needs is seeded over the API first —
# see tests/flows/academics_seed.py for why (a lesson, a syllabus behind it, a
# category on that syllabus, and the subject-teacher assignment without which
# the backend answers 403).

ASSESSMENTS_SCENARIO = "academics_only"

ASSESSMENT_NAME = f"TEST Mid-Term Quiz {run_tag()}"
ASSESSMENT_DESCRIPTION = "Ten questions on equivalent fractions, taken in class."
CREATE_MAX_MARKS = 40
EDIT_MAX_MARKS = 50
DRAFT_STATUS = re.compile(r"^\s*draft\s*$", re.I)
PUBLISHED_STATUS = re.compile(r"^\s*published\s*$", re.I)
PUBLISHED_OPTION = "Published"

# NAV_ASSESSMENTS (the sidebar entry) is declared with the read-only path's
# constants above; the teacher journey below reuses it.


@pytest.fixture
def assessment_seed(
    provisioned_school: SchoolContext, api: BackendAPI
) -> AcademicsSeed:
    """The topic/syllabus/category/lesson chain an assessment hangs off.

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
@pytest.mark.scenario(ASSESSMENTS_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.assessments.manage.teacher",
    title="Assessments",
    subtitle="Teacher creates and manages assessments",
)
def test_teacher_creates_and_publishes_assessment(
    assessment_seed: AcademicsSeed,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A subject teacher schedules a quiz, then revises and publishes it."""
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ASSESSMENTS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {ASSESSMENTS_MODULE!r} for this "
        f"unit — a teacher refused the module has no workspace to manage"
    )

    assessments = AssessmentsPage(demo.page, demo.frontend_base_url)
    scheduled_date = (date.today() + timedelta(days=7)).isoformat()
    due_date = (date.today() + timedelta(days=21)).isoformat()

    with demo.step(f"Sign in as {ctx.teacher.full_name}, who teaches {SUBJECT_NAME}"):
        login_as(demo.page, demo.frontend_base_url, ctx.teacher)

    with demo.step("Open Assessment & Scores from the Academics menu"):
        # The sidebar renders its Academics group only once SideNavigation has
        # fetched the school's licensed modules, so the entry appears a beat
        # after the landing page does — polling for it immediately would find
        # nothing and silently deep-link instead, which is exactly the shortcut
        # this walkthrough is meant to show a viewer taking the long way round.
        link = demo.page.get_by_role("link", name=NAV_ASSESSMENTS).first
        try:
            link.wait_for(state="visible", timeout=30_000)
            link.click()
        except PlaywrightTimeoutError:
            # The sidebar collapses on narrow viewports; the route is the point,
            # not the way in.
            assessments.open()
        assessments.expect_loaded()

    with demo.step("Start a new assessment"):
        modal = assessments.open_create_form()

    with demo.step(f"Describe the quiz and attach it to the {SUBJECT_NAME} lesson"):
        assessments.fill_create_form(
            modal,
            name=ASSESSMENT_NAME,
            lesson_title=assessment_seed.lesson_title,
            category_name=assessment_seed.category_name,
            description=ASSESSMENT_DESCRIPTION,
            max_marks=CREATE_MAX_MARKS,
            scheduled_date=scheduled_date,
            due_date=due_date,
        )

    with demo.step("Save it — the quiz is now on the register as a draft", dwell_ms=1200):
        assessments.submit_create(modal, name=ASSESSMENT_NAME)

        expect(assessments.cell(ASSESSMENT_NAME, COLUMN["lesson"])).to_have_text(
            _exact_text(assessment_seed.lesson_title)
        )
        expect(assessments.cell(ASSESSMENT_NAME, COLUMN["category"])).to_have_text(
            _exact_text(assessment_seed.category_name)
        )
        expect(assessments.cell(ASSESSMENT_NAME, COLUMN["max_marks"])).to_have_text(
            _exact_text(str(CREATE_MAX_MARKS))
        )
        expect(assessments.cell(ASSESSMENT_NAME, COLUMN["status"])).to_have_text(
            DRAFT_STATUS
        )

    with demo.step(f"Reopen it, raise the total to {EDIT_MAX_MARKS} marks and publish it"):
        assessments.edit_assessment(
            name=ASSESSMENT_NAME,
            max_marks=EDIT_MAX_MARKS,
            status=PUBLISHED_OPTION,
        )

    with demo.step("The register shows the published quiz, ready to be scored", dwell_ms=1500):
        expect(assessments.cell(ASSESSMENT_NAME, COLUMN["max_marks"])).to_have_text(
            _exact_text(str(EDIT_MAX_MARKS))
        )
        expect(assessments.cell(ASSESSMENT_NAME, COLUMN["status"])).to_have_text(
            PUBLISHED_STATUS
        )


def _exact_text(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
