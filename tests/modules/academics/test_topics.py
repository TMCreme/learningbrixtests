"""Academics → Topics — the subject-curriculum module (`topics`).

Where this module actually lives in the frontend
    There is **no** ``/module/topics`` route. The ledger names one, but Next.js
    has no such segment, so navigating there is a plain 404 that says nothing
    about licensing. The module's real surfaces are three:

    * ``/module/subjects`` — the "Topics" tab of the "Manage Subjects & Topics"
      screen, which is the topic register (search, view, edit, archive, delete)
      and the launcher for the two pages below;
    * ``/module/subjects/topics/add`` — the bulk "Add Topic" composer;
    * ``/module/subject_topics/reorder_topics`` — "Reorder Subject Topics", the
      drag-and-drop teaching-order editor, and the **only** page in the app that
      guards on ``useModuleGuard("topics")``.

    ``config/module_catalog.py`` therefore records ``subject_topics`` as this
    module's route, and this test drives that page plus the register tab.

Positive path: a teacher of the ``academics_only`` school writes a batch of
topics for a subject they teach, then revises one of them
(``test_teacher_creates_and_manages_topics``). What had to be fixed before that
walkthrough was reachable at all — a Teacher holds ``("manage", "topics")`` but
only ``("read", "subjects")``, and both topic screens read their write
affordances off the *subjects* permission — is spelled out in the section
comment above that test.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack holds
only ``school_configuration`` and ``school_admin_dashboard``
(``test_topics_denied_for_school_admin_when_module_disabled``).

Where the denial actually lives
    Not in the sidebar, and not in a route guard — exactly as for lessons.
    ``src/middleware.ts`` skips its module enforcement for a SchoolAdmin
    outright, ``useModuleGuard`` returns ``true`` for the same role before it
    ever reads the ``schoolModules`` cookie, and ``usePermissionGuard`` returns
    early too. So every one of the three routes above really does mount for a
    SchoolAdmin. The seeded SchoolAdmin role also *holds* ``("manage", "topics")``
    (newschoolapp/db/repository/permissions.py), so the permission half of the
    backend gate passes as well.

    What denies them is the feature-pack half of ``utils.permissions.has_permission``:
    every route on ``api/routes/topic.py`` carries a
    ``Depends(has_permission(..., "topics"))``, that dependency is solved before
    the request body is ever validated, and for a school whose pack omits
    ``topics`` it answers **403 "Feature not available in your plan"**. That 403
    is what this test is built on.

    The UI consequence follows from it. The axios response interceptor in
    ``src/utils/handleErrorMessage.ts`` recognises that particular detail
    (``shouldRedirectToNoAccess``) and performs a hard ``window.location``
    redirect to **/auth/no-access**, rejecting the promise with
    ``FeatureNotAvailableError`` before either page's own ``catch`` can put
    "Failed to load topics" on screen. So the landing page, not a ``PageError``
    panel, is the denial surface here.

Two honesty notes about what the UI half can and cannot prove
    1. ``minimal`` switches off ``subjects`` as well as ``topics`` — it switches
       off nearly everything, which is the point of that scenario. Both topic
       screens fetch subjects before they fetch topics (the reorder page's
       ``loadSubjects`` runs on mount; the register's Topics tab calls
       ``fetchSubjectsForTopics``), so whichever 403 lands first is the one that
       fires the redirect. The UI assertions below therefore prove "this
       SchoolAdmin never reaches a topics workspace", not "it was the *topics*
       licence that stopped them". The topics-specific gate is proved at the API
       level instead, route by route, which is why that half comes first and is
       exhaustive.
    2. Deliberately *not* asserted: that the sidebar hides the topics entry.
       ``nav-config.tsx`` gates "Subject & Topic" on ``permission: "subjects"``,
       and SideNavigation lets the permission check take priority for a
       SchoolAdmin — so its presence or absence says nothing about this school's
       pack.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.academics_seed import AcademicsSeed, seed_assessment_prerequisites
from tests.flows.school_provisioning import CLASS_NAME, SUBJECT_NAME, SchoolContext
from tests.pages.academics.lessons import COLUMN as LESSON_COLUMN
from tests.pages.academics.lessons import DETAIL_EDIT_BUTTON as LESSON_EDIT_BUTTON
from tests.pages.academics.lessons import LessonsPage
from tests.pages.academics.subjects import PAGE_HEADING as SUBJECTS_PAGE_HEADING
from tests.pages.academics.subjects import SEARCH_FIELD as SUBJECT_SEARCH_FIELD
from tests.pages.academics.topics import DURATION_FIELD as TOPIC_FORM_DURATION_FIELD
from tests.pages.academics.topics import NAME_FIELD as TOPIC_FORM_NAME_FIELD
from tests.pages.academics.topics import OUTCOMES_FIELD as TOPIC_FORM_OUTCOMES_FIELD
from tests.pages.academics.topics import TopicsPage
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as

TOPICS_MODULE = "topics"
SUBJECTS_MODULE = "subjects"

# ``config/module_catalog.py``'s route for this module — the one page that
# guards on ``useModuleGuard("topics")``.
TOPICS_REORDER_ROUTE = "subject_topics/reorder_topics"
# The topic register: the "Topics" tab of Manage Subjects & Topics.
TOPICS_REGISTER_ROUTE = "subjects"
# The bulk composer the register's "Add Topic" button pushes to.
TOPICS_ADD_ROUTE = "subjects/topics/add"

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

# ── the topic workspace's own chrome, none of which may reach this admin ─────
# src/app/module/subject_topics/reorder_topics/page.tsx
REORDER_HEADING = re.compile(r"^\s*Reorder Subject Topics\s*$", re.I)
BACK_TO_TOPICS_BUTTON = re.compile(r"^\s*Back to Topics\s*$", re.I)
REORDER_SUBJECT_LABEL = re.compile(r"Select Subject to Reorder Topics", re.I)
# src/app/module/subjects/page.tsx — the Topics tab and its two write launchers.
TOPICS_TAB = re.compile(r"^\s*Topics\s*$", re.I)
ADD_TOPIC_BUTTON = re.compile(r"^\s*Add Topic\s*$", re.I)
REORDER_TOPICS_BUTTON = re.compile(r"^\s*Reorder Topics\s*$", re.I)
TOPIC_SEARCH_FIELD = re.compile(r"^\s*Search topic or subject\s*$", re.I)
# src/app/module/subjects/topics/add/page.tsx
ADD_TOPIC_NAME_FIELD = re.compile(r"^\s*e\.g\. Introduction to Algebra\s*$", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_topics_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `topics` off the pack, a SchoolAdmin gets no curriculum and no data."""
    ctx = provisioned_school
    if TOPICS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {TOPICS_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had topics rights anyway", which would make the 403s vacuous.
    role = api.get(f"/roles/{api.role_id_for(SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert TOPICS_MODULE in role_modules, (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{TOPICS_MODULE!r} permission, so this test would be asserting a denial "
        f"the role gets for free. Re-point it at the feature pack only, or fix "
        f"the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{TOPICS_MODULE!r} proves nothing about the gate. Provisioning phase A "
        f"assigns one — check that it did."
    )
    assert TOPICS_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {TOPICS_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every /topics route is refused ──────────────────
    #
    # Every route in api/routes/topic.py is covered, reads and writes alike, so
    # the gate cannot regress into being merely read-only or merely cosmetic.
    # The ids are deliberately arbitrary: has_permission is a route-level
    # dependency, solved before the path/body params are validated and long
    # before any row is looked up, so a 404 here would itself be the failure.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"?branch_id={branch_id}" if branch_id else ""
    topic_name = f"TEST Unlicensed Topic {run_tag()}"

    refusals = {
        # What the register's Topics tab and the reorder page both call.
        "list": api.get(
            f"/topics/?skip=0&limit=10"
            f"{f'&branch_id={branch_id}' if branch_id else ''}",
            token=token,
        ),
        # The View Topic modal.
        "detail": api.get(f"/topics/1{branch_query}", token=token),
        # The single create, and the "Add Topic" composer's bulk create.
        "create": api.post(
            f"/topics/{branch_query}",
            token=token,
            json={
                "name": topic_name,
                "description": "Must never be created — the pack excludes topics.",
                "subject_id": 1,
            },
        ),
        "bulk_create": api.post(
            f"/topics/bulk{branch_query}",
            token=token,
            json={
                "subject_id": 1,
                "topics": [
                    {
                        "name": topic_name,
                        "description": "Must never be created either.",
                    }
                ],
            },
        ),
        # The row menu's Edit / Archive / Delete.
        "update": api.put(
            f"/topics/1{f'?school_branch_id={branch_id}' if branch_id else ''}",
            token=token,
            json={"name": f"TEST Unlicensed Rename {run_tag()}"},
        ),
        "archive": api.put(f"/topics/1/archive{branch_query}", token=token),
        "delete": api.delete(
            f"/topics/1{f'?school_branch_id={branch_id}' if branch_id else ''}",
            token=token,
        ),
        # And the reorder page's save.
        "reorder": api.post(
            f"/topics/reorder/1{branch_query}",
            token=token,
            json={"topic_order": [1]},
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{TOPICS_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a topic workspace in front of them ──────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # (a) The module's own page: /module/subject_topics/reorder_topics.
    #
    # A SchoolAdmin is exempt from the middleware gate and from useModuleGuard,
    # so this route really does mount and really does start fetching — and the
    # axios interceptor turns the refusal into a hard redirect long before
    # PageError could render (see the module docstring). Waiting for the URL is
    # therefore also what stops the "workspace is absent" assertions below from
    # passing merely because the page had not finished loading.
    goto_module(page, frontend_base_url, TOPICS_REORDER_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    expect(page.get_by_role("heading", name=as_pattern(REORDER_HEADING))).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(BACK_TO_TOPICS_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_text(as_pattern(REORDER_SUBJECT_LABEL))).to_have_count(0)

    # (b) The register that owns the Topics tab, and its two write launchers.
    goto_module(page, frontend_base_url, TOPICS_REGISTER_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)

    expect(
        page.get_by_role("heading", name=as_pattern(SUBJECTS_PAGE_HEADING))
    ).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(TOPICS_TAB))).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(ADD_TOPIC_BUTTON))).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(REORDER_TOPICS_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(TOPIC_SEARCH_FIELD))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(SUBJECT_SEARCH_FIELD))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)

    # (c) And typing the composer's URL by hand is no way round it either.
    goto_module(page, frontend_base_url, TOPICS_ADD_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(page.get_by_placeholder(as_pattern(ADD_TOPIC_NAME_FIELD))).to_have_count(0)


# ─────────────── the pupil's own view of the curriculum ──────────────────────
#
# Constants below are prefixed rather than sharing the negative section's names:
# this file is written one unit at a time, and a shared module-level name would
# silently rebind under whichever section is appended last.
#
# Where a pupil reads a topic, and why it is not the topic register
#     The three screens the module docstring lists are all staff surfaces, and
#     none of them is reachable by a learner. Every one of them mounts
#     ``usePermissionGuard("subjects")`` (or is pushed to from a page that does),
#     and the seeded Student role holds no ``subjects`` permission at all —
#     ``db/repository/permissions.py`` grants a pupil ``read`` on home,
#     categories, student_timetables, student_scores, messaging, community,
#     change_requests, families and **lessons**, and nothing else. So
#     /module/subjects redirects them to /unauthorized, ``nav-config.tsx`` never
#     renders the "Subject & Topic" entry for them (it is gated on the same
#     ``permission: "subjects"``), and ``GET /topics/`` answers 403 on the
#     *permission* half of ``utils.permissions.has_permission`` long before the
#     feature-pack half is reached.
#
#     What a pupil is entitled to is the topic **their own lessons cover**, and
#     the app delivers it through the lessons module they do hold ``read`` on.
#     ``LessonService`` serialises ``topic_name`` onto every lesson it returns
#     (``lesson_service.py``: ``"topic_name": lesson.topic.name if lesson.topic
#     else None``), the register draws it under the subject in its "Subject &
#     Topic" column (``lessons/page.tsx``), the client-side search matches on it,
#     and the read-only detail route renders it as the "Topic" card of the Lesson
#     Information panel (``lessons/[id]/page.tsx``). That chain — not the
#     register — is this unit.
#
#     Both halves are asserted for that reason. The UI half proves the pupil
#     really is shown the topic of each lesson their class was given; the API half
#     proves the same pupil cannot reach the topic *register* behind the screen,
#     so "they can read topics" never quietly becomes "they can read every topic
#     in the school".
#
# What is seeded, and why over the API
#     Authoring a topic, a syllabus and a lesson plan is three other modules'
#     walkthroughs. ``tests/flows/academics_seed`` already builds that chain (and
#     the subject-teacher assignment that puts a name on the card), exactly as
#     ``school_provisioning._seed_fee_group`` seeds the fee group the Add Class
#     dialog insists on.
#
#     A *second* topic is added on top of it, with a second lesson plan hung off
#     that topic. One topic would let the Subject & Topic column pass while
#     rendering a constant; two different topics under the same subject mean the
#     column has to carry each lesson's own value. The second topic has to be
#     attached to the syllabus first — ``LessonService.create_lesson`` refuses a
#     syllabus lesson whose topic is not in its syllabus ("Topic is not part of
#     the specified syllabus").
#
#     Both plans are authored as the SchoolAdmin on purpose: ``create_lesson``
#     auto-approves an admin's plan, and ``_scope_lessons`` shows a pupil only
#     APPROVED plans for the class they are enrolled in. A teacher-authored plan
#     would start PENDING and be (correctly) invisible here.

STUDENT_VIEW_SCENARIO = "academics_only"

# The second topic and the plan that teaches it. "TEST"-prefixed for the orphan
# sweeper, run-tagged so parallel agents never collide on the name (a topic name
# is unique per subject — topic_service: "Topic with this name already exists for
# this subject").
STUDENT_SECOND_TOPIC_NAME = f"TEST Decimals and Percentages {run_tag()}"
STUDENT_SECOND_TOPIC_DESCRIPTION = (
    "Converting between decimals, fractions and percentages."
)
STUDENT_SECOND_LESSON_TITLE = f"TEST Decimals Lesson {run_tag()}"
STUDENT_LESSON_DURATION = 45

# Sidebar entry the pupil reaches the module through (nav-config.tsx). Their role
# holds ("read", "lessons") and the academics_only pack licenses the module, so
# both halves of the nav gate pass.
STUDENT_NAV_LESSONS = re.compile(r"^\s*Lessons\s*$", re.I)

# The Lesson Information panel's cards (lessons/[id]/page.tsx :: InfoCard). Each
# is ``<p>label</p><p>value</p>`` inside one wrapper, so the label paragraph's
# parent is the assertion's scope. The labels are uppercased in CSS only — the
# DOM text is what is matched here.
STUDENT_INFO_TOPIC = re.compile(r"^\s*Topic\s*$", re.I)
STUDENT_INFO_SUBJECT = re.compile(r"^\s*Subject\s*$", re.I)
STUDENT_INFO_CLASS = re.compile(r"^\s*Class\s*$", re.I)

# The one denial has_permission can answer a pupil with here: the school *is*
# licensed for topics, so it is the role that is refused, never the plan.
STUDENT_ROLE_DENIAL = re.compile(
    r"You do not have permission to perform this action", re.I
)


class TopicSeedError(RuntimeError):
    """A prerequisite could not be seeded, so there is no topic to read."""


@dataclass(frozen=True)
class PupilTopics:
    """The two topics this unit puts in front of the pupil, and their lessons."""

    first_topic_id: int
    first_topic: str
    first_lesson: str
    second_topic_id: int
    second_topic: str
    second_lesson: str
    second_lesson_id: int
    subject_id: int


@pytest.fixture
def pupil_topics(provisioned_school: SchoolContext, api: BackendAPI) -> PupilTopics:
    """Two topics under Mathematics, each taught by an approved lesson plan.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert ctx.branches, "provisioning created no branch for this school"
    assert ctx.classes, (
        "provisioning created no class, so the pupil is enrolled in nothing and "
        "every lesson — and so every topic — is correctly invisible to them"
    )

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

    token = _topic_login(api, ctx.school_admin.email, ctx.school_admin.password)
    first_topic = _topic_name(api, token, seed.topic_id, branch_id=branch_id)
    second_topic_id = _ensure_topic(
        api, token, seed, name=STUDENT_SECOND_TOPIC_NAME
    )
    _attach_topics_to_syllabus(
        api, token, seed, topic_ids=[seed.topic_id, second_topic_id]
    )
    second_lesson_id = _ensure_lesson(
        api, token, seed,
        title=STUDENT_SECOND_LESSON_TITLE,
        topic_id=second_topic_id,
    )

    return PupilTopics(
        first_topic_id=seed.topic_id,
        first_topic=first_topic,
        first_lesson=seed.lesson_title,
        second_topic_id=second_topic_id,
        second_topic=STUDENT_SECOND_TOPIC_NAME,
        second_lesson=STUDENT_SECOND_LESSON_TITLE,
        second_lesson_id=second_lesson_id,
        subject_id=seed.subject_id,
    )


@pytest.mark.student
@pytest.mark.scenario(STUDENT_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.topics.view.student",
    title="Subject Topics",
    subtitle="Student views subject topics",
)
def test_student_reads_the_topics_their_lessons_cover(
    pupil_topics: PupilTopics,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A pupil reads the curriculum topic behind each of their class's lessons.

    Every value asserted is derived server-side — ``topic_name`` is resolved from
    the lesson's ``topic`` relationship, the subject and class from the plan
    itself — so matching them proves the screen really fetched this pupil's
    lessons rather than rendering something the browser already had.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert TOPICS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {TOPICS_MODULE!r} for this "
        f"unit — a school that is refused the module has no curriculum to read"
    )

    page: Page = demo.page
    lessons = LessonsPage(page, demo.frontend_base_url)
    pupil = ctx.student.full_name

    with demo.step(f"Sign in as {pupil}, a pupil in {CLASS_NAME}"):
        login_as(page, demo.frontend_base_url, ctx.student)

    with demo.step("Lessons is waiting in their Academics menu — open it"):
        link = page.get_by_role("link", name=as_pattern(STUDENT_NAV_LESSONS)).first
        expect(link).to_be_visible(timeout=25_000)
        link.click()
        lessons.expect_loaded()
        lessons.expect_no_load_failure()
        lessons.wait_for_rows()

    with demo.step(
        f"Every lesson says which topic it covers — this one teaches "
        f"{pupil_topics.first_topic}",
        dwell_ms=1800,
    ):
        lessons.search(pupil_topics.first_lesson)
        lessons.expect_row(pupil_topics.first_lesson)
        subject_and_topic = lessons.cell(
            pupil_topics.first_lesson, LESSON_COLUMN["subject"]
        )
        expect(subject_and_topic).to_contain_text(SUBJECT_NAME)
        expect(subject_and_topic).to_contain_text(pupil_topics.first_topic)

    with demo.step(
        f"A different lesson in the same subject covers "
        f"{pupil_topics.second_topic}",
        dwell_ms=1800,
    ):
        lessons.search(pupil_topics.second_lesson)
        lessons.expect_row(pupil_topics.second_lesson)
        expect(
            lessons.cell(pupil_topics.second_lesson, LESSON_COLUMN["subject"])
        ).to_contain_text(pupil_topics.second_topic)
        # The column carries each plan's own topic, not one shared label: the
        # lesson on the first topic is not among the matches.
        expect(_topic_row(page, pupil_topics.first_lesson)).to_have_count(0)

    with demo.step("Searching the register by topic name finds what teaches it"):
        # lessons/page.tsx filters on `lesson.topic_name` as well as the title,
        # so the topic is something a pupil can look their week up by.
        lessons.search(pupil_topics.second_topic)
        lessons.expect_row(pupil_topics.second_lesson)

    with demo.step("Open the lesson to read the topic in full", dwell_ms=1500):
        lessons.open_details(pupil_topics.second_lesson)

    with demo.step(
        f"Lesson Information names the topic — {pupil_topics.second_topic} — "
        f"under {SUBJECT_NAME} for {CLASS_NAME}",
        dwell_ms=2500,
    ):
        expect(_info_card(page, STUDENT_INFO_TOPIC)).to_contain_text(
            pupil_topics.second_topic, timeout=20_000
        )
        expect(_info_card(page, STUDENT_INFO_SUBJECT)).to_contain_text(SUBJECT_NAME)
        expect(_info_card(page, STUDENT_INFO_CLASS)).to_contain_text(CLASS_NAME)
        # Read-only throughout: the detail page's editor is gated on
        # ("manage", "lessons"), which a pupil does not hold.
        expect(
            page.get_by_role("button", name=as_pattern(LESSON_EDIT_BUTTON))
        ).to_have_count(0)

    with demo.step(
        "The topic reaches them through their lessons — the topic register "
        "itself is not theirs to browse",
        dwell_ms=2000,
    ):
        _expect_topics_reach_the_pupil_only_through_lessons(api, ctx, pupil_topics)


def _expect_topics_reach_the_pupil_only_through_lessons(
    api: BackendAPI, ctx: SchoolContext, pupil_topics: PupilTopics
) -> None:
    """Assert the backend gives this pupil the same deal the UI does.

    Without this the UI half proves only that the *frontend* draws a topic name,
    which says nothing about what a hand-built request could reach. Two things are
    checked, and they are the whole shape of the feature for this role:

    * the topic of a lesson they are entitled to really is served to them, by
      their own token, on the very route the detail page calls; and
    * every route on ``api/routes/topic.py`` refuses them — reads included — so
      "a pupil may read topics" can never widen into "a pupil may read the
      school's whole curriculum, or write to it".

    The denial expected is the *role* one, not the plan one: the school is
    licensed for ``topics`` (asserted in the test body), so ``has_permission``
    stops on its first half, which the seeded Student role fails.
    """
    assert ctx.student is not None
    token = api.login(ctx.student.email, ctx.student.password)["access_token"]

    lesson = api.get(f"/lessons/{pupil_topics.second_lesson_id}", token=token)
    assert lesson.status_code == 200, (
        f"a pupil holds ('read', 'lessons'), so the detail route the screen "
        f"calls must serve them their own class's approved plan — got "
        f"{lesson.status_code}: {lesson.text[:300]}"
    )
    assert str(lesson.json().get("topic_name", "")) == pupil_topics.second_topic, (
        f"the lesson served to the pupil does not carry the topic it was "
        f"authored against — LessonService serialises topic_name from the "
        f"lesson's topic relationship; got {lesson.json().get('topic_name')!r}, "
        f"expected {pupil_topics.second_topic!r}"
    )

    refusals = {
        # The register's Topics tab and the reorder page.
        "list": api.get("/topics/?skip=0&limit=100", token=token),
        # The View Topic modal — including a topic they *do* meet in a lesson,
        # which is the point: the lesson is their entitlement, the topic row is
        # not.
        "detail": api.get(f"/topics/{pupil_topics.first_topic_id}", token=token),
        "create": api.post(
            "/topics/",
            token=token,
            json={
                "name": f"TEST Pupil Authored Topic {run_tag()}",
                "description": "A pupil must never be able to write curriculum.",
                "subject_id": pupil_topics.subject_id,
            },
        ),
        "update": api.put(
            f"/topics/{pupil_topics.second_topic_id}",
            token=token,
            json={"name": f"TEST Pupil Rename {run_tag()}"},
        ),
        "archive": api.put(f"/topics/{pupil_topics.second_topic_id}/archive", token=token),
        "delete": api.delete(f"/topics/{pupil_topics.second_topic_id}", token=token),
        "reorder": api.post(
            f"/topics/reorder/{pupil_topics.subject_id}",
            token=token,
            json={"topic_order": [pupil_topics.second_topic_id]},
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: the seeded Student role holds no {TOPICS_MODULE!r} "
            f"permission, so every route on api/routes/topic.py must refuse a "
            f"pupil with 403 — got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert STUDENT_ROLE_DENIAL.search(detail), (
            f"{label}: 403 is right, but the reason is not the one this role and "
            f"this pack imply. {ctx.school_name!r} *is* licensed for "
            f"{TOPICS_MODULE!r}, so the refusal must come from the role half of "
            f"has_permission — got {detail!r}"
        )


# ──────────── UI helpers for this unit (locators, never assertions) ──────────


def _topic_row(page: Page, title: str) -> Locator:
    """Every register row whose title cell reads ``title`` — for absence checks.

    ``LessonsPage.find_row`` ends in ``.first``, which is what makes it right for
    "assert this row looks like X" and wrong for "assert there is no such row".
    """
    return page.get_by_role("row").filter(has=page.get_by_text(_topic_exact(title)))


def _info_card(page: Page, label: re.Pattern[str]) -> Locator:
    """One card of the detail page's Lesson Information panel, by its label.

    ``InfoCard`` renders ``<div><p>LABEL</p><p title=…>value</p></div>``, so the
    label paragraph's parent is the smallest element holding both — which is what
    makes "the Topic card says X" assertable without also matching the Subject
    card sitting three lines above it.
    """
    node = page.locator("p").filter(has_text=as_pattern(label)).first
    return node.locator("xpath=..")


# ──────────── setup-only seeding for this unit (never asserted) ──────────────


def _topic_login(api: BackendAPI, email: str, password: str) -> str:
    try:
        return str(api.login(email, password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise TopicSeedError(f"could not log in as {email}: {exc}") from exc


def _topic_name(api: BackendAPI, token: str, topic_id: int, *, branch_id: int) -> str:
    """Read the seeded topic's stored name back rather than rebuilding it.

    ``academics_seed`` composes the name from its own constant and the run tag;
    asking the backend what it actually stored keeps this unit from asserting a
    string the seed no longer writes.
    """
    response = api.get(f"/topics/{topic_id}?branch_id={branch_id}", token=token)
    if response.status_code >= 400:
        raise TopicSeedError(
            f"could not read the seeded topic {topic_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    name = str(response.json().get("name", "")).strip()
    if not name:
        raise TopicSeedError(f"topic {topic_id} came back with no name")
    return name


def _ensure_topic(
    api: BackendAPI, token: str, seed: AcademicsSeed, *, name: str
) -> int:
    """A second topic under the same subject, created once per school.

    ``provisioned_school`` is session-scoped, so the whole batch shares one
    school and this fixture may run more than once against it. A topic name is
    unique per subject server-side, so the existing row is reused rather than
    re-created.
    """
    listed = api.get(
        f"/topics/?branch_id={seed.branch_id}&subject_id={seed.subject_id}&limit=100",
        token=token,
    )
    if listed.status_code < 400:
        for row in _topic_rows(listed.json()):
            if str(row.get("name", "")).strip().casefold() == name.casefold():
                return int(row["id"])

    created = api.post(
        f"/topics/?branch_id={seed.branch_id}",
        token=token,
        json={
            "name": name,
            "description": STUDENT_SECOND_TOPIC_DESCRIPTION,
            "subject_id": seed.subject_id,
            "order_index": 1,
        },
    )
    if created.status_code >= 400:
        raise TopicSeedError(
            f"could not seed the topic {name!r}: "
            f"{created.status_code} {created.text[:300]}"
        )
    return int(created.json()["id"])


def _attach_topics_to_syllabus(
    api: BackendAPI, token: str, seed: AcademicsSeed, *, topic_ids: list[int]
) -> None:
    """Put both topics on the seeded syllabus.

    ``LessonService.create_lesson`` refuses a syllabus lesson whose topic is not
    part of its syllabus ("Topic is not part of the specified syllabus"), so this
    has to happen before the second plan is authored.
    ``SyllabusService.update_syllabus`` replaces the association set wholesale,
    which is why the *first* topic is sent again alongside the new one — dropping
    it would break the plans the other academics units hang off it.
    """
    response = api.put(
        f"/syllabi/{seed.syllabus_id}?school_branch_id={seed.branch_id}",
        token=token,
        json={
            "topic_ids": [
                {"topic_id": topic_id, "order_index": index, "is_optional": False}
                for index, topic_id in enumerate(topic_ids)
            ]
        },
    )
    if response.status_code >= 400:
        raise TopicSeedError(
            f"could not attach topics {topic_ids} to syllabus "
            f"{seed.syllabus_id}: {response.status_code} {response.text[:300]}"
        )


def _ensure_lesson(
    api: BackendAPI, token: str, seed: AcademicsSeed, *, title: str, topic_id: int
) -> int:
    """One approved lesson plan on ``topic_id`` — which is one register row.

    Authored with the SchoolAdmin's token on purpose: ``create_lesson``
    auto-approves an admin's plan, and ``_scope_lessons`` shows a pupil only
    APPROVED plans. Reused by title for the same reason ``_ensure_topic`` is.
    """
    listed = api.get(
        f"/lessons/?branch_id={seed.branch_id}&class_id={seed.class_id}"
        f"&subject_id={seed.subject_id}&limit=100",
        token=token,
    )
    if listed.status_code < 400:
        for row in _topic_rows(listed.json()):
            if str(row.get("title", "")).strip().casefold() == title.casefold():
                return int(row["id"])

    created = api.post(
        f"/lessons/?branch_id={seed.branch_id}",
        token=token,
        json={
            "title": title,
            "description": "Seeded so a second topic has a lesson that teaches it.",
            "lesson_type": "syllabus",
            "topic_id": topic_id,
            "syllabus_id": seed.syllabus_id,
            "subject_id": seed.subject_id,
            "class_id": seed.class_id,
            "teacher_id": seed.teacher_profile_id,
            "scheduled_date": (date.today() + timedelta(days=3)).isoformat(),
            "scheduled_time": "11:00:00",
            "duration_minutes": STUDENT_LESSON_DURATION,
        },
    )
    if created.status_code >= 400:
        raise TopicSeedError(
            f"could not seed the lesson {title!r} on topic {topic_id}: "
            f"{created.status_code} {created.text[:300]}"
        )
    return int(created.json()["id"])


def _topic_rows(payload) -> list[dict]:
    """Some list endpoints answer a bare list, others a paginated envelope."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _topic_exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)


# ═════════════ positive path: a teacher authors the curriculum ══════════════
#
# What "manage" means for this module, and where each half lives
#     Topics are written in two places and nowhere else: the bulk composer at
#     ``/module/subjects/topics/add`` (``POST /topics/bulk`` — one subject, a
#     batch of topics) and the single-topic form at
#     ``/module/subjects/topics/edit/{id}`` (``PUT /topics/{id}``). Both are
#     reached from the Topics tab of ``/module/subjects``, which is the register
#     the result has to show up on. So this walkthrough is: stage a batch,
#     create it, read it back on the register in teaching order, reopen one topic
#     and revise it.
#
#     The teaching order itself is deliberately *not* driven through
#     ``/module/subject_topics/reorder_topics``: that page is a dnd-kit drag
#     surface, and the order this unit asserts is the one the backend assigns on
#     insert (``auto_increment_topic_order_index`` on ``Topic``), which is what a
#     newly authored curriculum actually reads like.
#
# Four defects this unit uncovered (all fixed in place; both app repos are dirty)
#     1. **A Teacher could not reach the feature at all.** ``topics`` is a module
#        of its own — every route on ``api/routes/topic.py`` is gated on
#        ``has_permission(…, "topics")`` — and the seeded Teacher role holds
#        ``("manage", "topics")`` but only ``("read", "subjects")``. Both frontend
#        surfaces read the topic write affordances off the *subjects* permission
#        (``usePermission("subjects", name => name === "manage")``), so a teacher
#        was shown the Topics tab with no "Add Topic", no "Reorder Topics" and a
#        row menu holding only "View details", while the API would have accepted
#        every one of those writes. ``subjects/page.tsx`` now reads a separate
#        ``isTopicManage`` for the topic affordances, and
#        ``reorder_topics/page.tsx`` reads its own gate from ``"topics"`` —
#        matching the ``useModuleGuard("topics")`` directly below it.
#     2. **The register's search box did nothing.** It had always sent
#        ``search=<term>`` (``GetTopics`` in ``topicsHandler.ts``) while
#        ``GET /topics/`` declared no such parameter, so FastAPI dropped it — the
#        same defect already fixed for ``GET /syllabi/``. ``list_topics`` now
#        matches on topic name, description and subject name, which is what the
#        box's own placeholder promises.
#     3. **Bulk create threw away four of its own fields.** The composer collects
#        Learning Outcomes, Objectives, Resources and Duration on every topic it
#        stages and ``TopicBulkCreateItem`` accepts all four, but
#        ``bulk_create_topics`` built its insert dict by hand from name,
#        description and order_index only. The single create, which
#        ``model_dump()``s, kept them. This test fills the composer in full and
#        reads the fields back off the edit form, so the fix is covered rather
#        than merely applied.
#     4. **Every topic in a batch came out with the same ``order_index``** — so a
#        curriculum authored through the composer had no teaching order at all.
#        ``auto_increment_topic_order_index`` is a ``before_insert`` hook reading
#        ``MAX(order_index)`` off the connection, and SQLAlchemy dispatches
#        ``before_insert`` for every pending state *before* it emits any INSERT
#        (``orm/persistence.py::_organize_states_for_save``), so adding the whole
#        batch and flushing once left each hook reading the same pre-flush
#        maximum. ``bulk_create_topics`` now flushes per topic. The order
#        assertion below is what covers it.
#
#     All four are written up in ``state/backend_patches.md``.
#
# What has to be seeded first, and why over the API
#     ``TopicService._assert_can_manage_subject`` lets a teacher author topics
#     only for a subject they are the **subject teacher** of
#     (``teacher_subject_class_association``). Provisioning makes its teacher the
#     *class* teacher of "Grade 6", which ``can_manage_subject`` deliberately
#     ignores — that grants reads and no writes at all, so without the assignment
#     the create answers 403 "Only the subject teacher can manage this topic".
#
#     The fixture therefore seeds, as the SchoolAdmin and setup-only (the same
#     use of ``api`` that ``school_provisioning._seed_fee_group`` makes): a
#     subject of its own, that subject on "Grade 6"'s curriculum, and the
#     (subject, class) teaching assignment.
#
#     Its **own** subject, deliberately not the provisioned "Mathematics": this
#     school is session-scoped and shared, and the student unit above already
#     hangs two topics off Mathematics. A subject of its own is what makes
#     "the register, narrowed to this subject, holds exactly these two topics in
#     this order" an assertion rather than a hope.

MANAGE_SCENARIO = "academics_only"

# Everything this unit creates carries the "TEST" prefix the orphan sweeper
# matches on, plus the run tag so parallel agents never collide (a topic name is
# unique per subject, and a subject name unique per branch — the backend refuses
# a second create either way).
MANAGE_TAG = run_tag()
MANAGE_SUBJECT_NAME = f"TEST Creative Arts {MANAGE_TAG}"

# Two topics, staged into one batch so the order the backend assigns is visible.
MANAGE_TOPIC_ONE = f"TEST Line and Shape {MANAGE_TAG}"
MANAGE_TOPIC_ONE_DESCRIPTION = (
    "Line as the first mark: contour, gesture and how shape emerges from it."
)
MANAGE_TOPIC_ONE_OUTCOMES = (
    "Draw a subject from observation using contour line alone."
)
MANAGE_TOPIC_ONE_OBJECTIVES = "Introduce line weight and the language of shape."
MANAGE_TOPIC_ONE_RESOURCES = "Sketchbooks, 2B pencils, still-life objects."
MANAGE_TOPIC_ONE_DURATION = 45

MANAGE_TOPIC_TWO = f"TEST Colour and Tone {MANAGE_TAG}"
MANAGE_TOPIC_TWO_DESCRIPTION = (
    "Mixing a limited palette, and reading tone as light rather than as colour."
)
MANAGE_TOPIC_TWO_OUTCOMES = "Mix a three-step tonal scale from one hue."
MANAGE_TOPIC_TWO_DURATION = 60

# The revision, applied to the first topic on the edit form.
MANAGE_TOPIC_ONE_RENAMED = f"TEST Line, Shape and Composition {MANAGE_TAG}"
MANAGE_REVISED_DESCRIPTION = (
    "Revised after the department meeting: composition now sits with line and "
    "shape rather than waiting for the second term."
)
MANAGE_REVISED_DURATION = 80


@dataclass(frozen=True)
class TeacherTopics:
    """The subject this teacher is licensed to author topics for."""

    branch_id: int
    class_id: int
    subject_id: int
    subject_name: str


@pytest.fixture
def teacher_topics(provisioned_school: SchoolContext, api: BackendAPI) -> TeacherTopics:
    """A subject on Grade 6's curriculum that the teacher is subject teacher of.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.

    Idempotent: ``provisioned_school`` is session-scoped, so this may be reached
    more than once against the same school. Everything it creates is looked up
    first (subject names are unique per branch, and duplicate teaching triples
    are skipped server-side).
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.branches, "provisioning created no branch for this school"
    assert ctx.classes, (
        "provisioning created no class, so no subject can be put on a curriculum "
        "— check that the scenario licenses classes_and_timetables"
    )

    branch_id = int(ctx.branches[0]["id"])
    if branch_id <= 0:
        raise TopicSeedError("provisioning captured no branch id")

    token = _topic_login(api, ctx.school_admin.email, ctx.school_admin.password)

    class_id = _manage_find_id(
        _topic_rows(
            _manage_json(api.get(f"/classes/?branch_id={branch_id}&limit=100", token=token))
        ),
        CLASS_NAME,
        what="class",
    )
    subject_id = _manage_ensure_subject(api, token, branch_id=branch_id)
    _manage_attach_subject_to_class(api, token, class_id=class_id, subject_id=subject_id)
    _manage_assign_subject_teacher(
        api, token,
        teacher_profile_id=_manage_teacher_profile_id(
            api, token, branch_id=branch_id, email=ctx.teacher.email
        ),
        subject_id=subject_id,
        class_id=class_id,
    )

    return TeacherTopics(
        branch_id=branch_id,
        class_id=class_id,
        subject_id=subject_id,
        subject_name=MANAGE_SUBJECT_NAME,
    )


@pytest.mark.teacher
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.topics.manage.teacher",
    title="Subject Topics",
    subtitle="Teacher creates and manages subject topics",
)
def test_teacher_creates_and_manages_topics(
    teacher_topics: TeacherTopics,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A subject teacher writes a batch of topics, then revises one of them."""
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert TOPICS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {TOPICS_MODULE!r} for this "
        f"unit — a teacher refused the module has no curriculum to author"
    )

    page: Page = demo.page
    topics = TopicsPage(page, demo.frontend_base_url)
    subject = teacher_topics.subject_name

    with demo.step(f"Sign in as {ctx.teacher.full_name}, who teaches {CLASS_NAME}"):
        login_as(page, demo.frontend_base_url, ctx.teacher)

    with demo.step("Open Subject & Topic from the Academics menu"):
        topics.open_from_nav()
        topics.expect_no_load_failure()

    with demo.step("Switch to Topics — the school's curriculum register"):
        topics.show_topics()

    with demo.step(f"Start a batch of topics for {subject}"):
        topics.open_add_form()
        topics.choose_subject(subject)

    with demo.step("Write up the first topic and add it to the batch"):
        topics.stage_topic(
            name=MANAGE_TOPIC_ONE,
            description=MANAGE_TOPIC_ONE_DESCRIPTION,
            learning_outcomes=MANAGE_TOPIC_ONE_OUTCOMES,
            objectives=MANAGE_TOPIC_ONE_OBJECTIVES,
            resources=MANAGE_TOPIC_ONE_RESOURCES,
            duration_minutes=MANAGE_TOPIC_ONE_DURATION,
        )

    with demo.step("Add a second topic, so the term has a sequence"):
        topics.stage_topic(
            name=MANAGE_TOPIC_TWO,
            description=MANAGE_TOPIC_TWO_DESCRIPTION,
            learning_outcomes=MANAGE_TOPIC_TWO_OUTCOMES,
            duration_minutes=MANAGE_TOPIC_TWO_DURATION,
        )
        topics.expect_staged_count(2)

    with demo.step("Create them — both land on the register, in teaching order",
                   dwell_ms=1800):
        topics.submit_create()
        # Narrowing by the subject's own name is what makes the order assertion
        # exact, and it is also the proof that the search box filters at all.
        topics.search(subject)
        topics.expect_teaching_order(MANAGE_TOPIC_ONE, MANAGE_TOPIC_TWO)
        topics.expect_subject(MANAGE_TOPIC_ONE, subject)
        topics.expect_status(MANAGE_TOPIC_ONE, "active")

    with demo.step("Reopen the first topic — the composer's detail was all saved",
                   dwell_ms=1500):
        topics.open_edit_form(MANAGE_TOPIC_ONE)
        # Every field here is prefilled from GET /topics/{id}, so this is an
        # assertion about what was *persisted* — not about what the composer
        # posted. Bulk create used to discard outcomes, objectives, resources and
        # duration outright (see the section comment above).
        topics.expect_field(TOPIC_FORM_NAME_FIELD, MANAGE_TOPIC_ONE)
        topics.expect_field(TOPIC_FORM_OUTCOMES_FIELD, MANAGE_TOPIC_ONE_OUTCOMES)
        topics.expect_field(
            TOPIC_FORM_DURATION_FIELD, str(MANAGE_TOPIC_ONE_DURATION)
        )

    with demo.step("Revise it — a new title, a new plan and more time on it"):
        topics.fill_edit_form(
            name=MANAGE_TOPIC_ONE_RENAMED,
            description=MANAGE_REVISED_DESCRIPTION,
            duration_minutes=MANAGE_REVISED_DURATION,
        )
        topics.submit_update()

    with demo.step("The revision reads back on the register, and in the topic",
                   dwell_ms=2500):
        topics.search(subject)
        # The rename replaced the old row rather than adding one, and the
        # teaching order the batch was created in survived the edit.
        topics.expect_teaching_order(MANAGE_TOPIC_ONE_RENAMED, MANAGE_TOPIC_TWO)
        topics.expect_absent(MANAGE_TOPIC_ONE)
        topics.expect_status(MANAGE_TOPIC_ONE_RENAMED, "active")

        topics.open_details(MANAGE_TOPIC_ONE_RENAMED)
        topics.expect_details_text(MANAGE_TOPIC_ONE_RENAMED)
        topics.expect_details_text(MANAGE_REVISED_DESCRIPTION)
        topics.expect_details_text(subject)
        topics.close_details()


# ───────── setup-only API helpers for the manage unit (never asserted) ───────


def _manage_json(response):
    if response.status_code >= 400:
        raise TopicSeedError(
            f"{response.request.method} {response.request.url.path} → "
            f"{response.status_code}: {response.text[:300]}"
        )
    return response.json()


def _manage_find_id(rows: list[dict], name: str, *, what: str) -> int:
    for row in rows:
        if str(row.get("name", "")).strip().casefold() == name.casefold():
            return int(row["id"])
    raise TopicSeedError(
        f"no {what} named {name!r} in this branch — provisioning should have "
        f"created it; got {[r.get('name') for r in rows]}"
    )


def _manage_ensure_subject(api: BackendAPI, token: str, *, branch_id: int) -> int:
    """This unit's own subject, created once per school."""
    listed = _topic_rows(
        _manage_json(api.get(f"/subjects/?branch_id={branch_id}&limit=100", token=token))
    )
    for row in listed:
        if str(row.get("name", "")).strip().casefold() == MANAGE_SUBJECT_NAME.casefold():
            return int(row["id"])

    created = api.post(
        f"/subjects/?branch_id={branch_id}",
        token=token,
        json={
            "name": MANAGE_SUBJECT_NAME,
            "description": "Seeded so the topics walkthrough owns its own subject.",
        },
    )
    if created.status_code >= 400:
        raise TopicSeedError(
            f"could not seed the subject: {created.status_code} {created.text[:300]}"
        )
    return int(created.json()["id"])


def _manage_attach_subject_to_class(
    api: BackendAPI, token: str, *, class_id: int, subject_id: int
) -> None:
    """Put the subject on the class's curriculum.

    ``PUT /classes/{id}`` *replaces* ``subjects`` wholesale
    (``ClassService.update_class``), so the class's existing subjects are read
    back and resubmitted — dropping "Mathematics" here would break every other
    academics unit sharing this session's school.
    """
    current = _manage_json(api.get(f"/classes/{class_id}", token=token))
    subject_ids = {int(s["id"]) for s in _topic_rows(current.get("subjects") or [])}
    if subject_id in subject_ids:
        return

    updated = api.put(
        f"/classes/{class_id}",
        token=token,
        json={"subject_ids": sorted(subject_ids | {subject_id})},
    )
    if updated.status_code >= 400:
        raise TopicSeedError(
            f"could not add subject {subject_id} to class {class_id}: "
            f"{updated.status_code} {updated.text[:300]}"
        )


def _manage_teacher_profile_id(
    api: BackendAPI, token: str, *, branch_id: int, email: str
) -> int:
    payload = _manage_json(
        api.get(f"/teacher/?branch_id={branch_id}&limit=100", token=token)
    )
    for row in _topic_rows(payload):
        user = row.get("user") or {}
        if str(user.get("email", "")).casefold() == email.casefold():
            return int(row["id"])
    raise TopicSeedError(
        f"no teacher profile for {email!r} in branch {branch_id} — "
        "the topics walkthrough needs the provisioned teacher."
    )


def _manage_assign_subject_teacher(
    api: BackendAPI, token: str, *, teacher_profile_id: int,
    subject_id: int, class_id: int,
) -> None:
    """Make the teacher the *subject* teacher of (subject, class).

    Idempotent server-side: duplicate triples are skipped. Without it every write
    answers 403 "Only the subject teacher can manage this topic" — being the
    class teacher grants reads only (``can_manage_subject`` ignores
    ``class_ids``).
    """
    response = api.post(
        f"/teacher/{teacher_profile_id}/subject-assignments",
        token=token,
        json={"assignments": [{"subject_id": subject_id, "class_id": class_id}]},
    )
    if response.status_code >= 400:
        raise TopicSeedError(
            "could not make the teacher the subject teacher of "
            f"(subject {subject_id}, class {class_id}): "
            f"{response.status_code} {response.text[:300]}"
        )
