"""/module/subjects — the "Manage Subjects & Topics" workspace.

Manage path: a SchoolAdmin of the ``academics_only`` school opens the Subjects
tab, adds a subject to the curriculum, corrects it, and finally retires it
(``test_school_admin_creates_and_manages_a_subject``). See the section comment
above that test for why all three writes are aimed at one subject, and why the
branch has to be activated before any of them.

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack does
NOT include ``subjects``
(``test_subjects_denied_for_school_admin_when_module_disabled``). Where that
denial actually lives is spelled out in the section comment above that test —
briefly: not in the sidebar and not in a route guard, but in the feature-pack
half of ``utils.permissions.has_permission``, whose 403 the axios interceptor
turns into a hard redirect to /auth/no-access.

Two things about this screen that are not obvious from the route, recorded here
so the next unit does not re-derive them:

* **The create payload is ``{name, description}`` and nothing else.** A subject
  is attached to a class from the Edit Class modal on
  ``/module/classes_and_timetables``, and the (teacher, subject, class) link is
  written from the teaching-staff form under ``/module/staff``. Neither belongs
  to this unit, so this test stays inside the Subjects tab and asserts the three
  writes the screen itself owns — ``SubjectsPage.create_subject`` drives the
  class attachment when a caller asks for it, which is how provisioning links
  ``Mathematics`` to ``Grade 6``.
* **The "Search subject by name" box now filters — it used not to.** page.tsx
  has always sent ``?search=…`` to ``GET /subjects/``, but that endpoint's
  signature declared only ``skip``, ``limit`` and ``branch_id``, so FastAPI
  dropped the parameter and every refetch came back unfiltered. Fixed in place
  (``api/routes/subject.py::list_subjects`` →
  ``SubjectService.list_subjects``, which now applies a case-insensitive
  ``name ILIKE`` before the teacher scoping); the view unit below is what
  asserts it. The consequence for the tests here is that a filter left in the
  box is a real one, so each section clears it before making any claim about
  "the register" — every assertion below is against the whole list, which is
  the stronger claim (a renamed subject must be gone from the *whole* register,
  not merely from a filtered page of it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI, Credentials
from tests.fixtures.data_factories import run_tag
from tests.flows.academics_seed import seed_assessment_prerequisites
from tests.flows.school_provisioning import CLASS_NAME, SUBJECT_NAME, SchoolContext
from tests.pages.academics.my_subject_summary import MySubjectSummaryPage
from tests.pages.academics.subjects import (
    ADD_SUBJECT_TRIGGER,
    ASSIGN_SUBJECTS_BUTTON,
    EMPTY_DESCRIPTION,
    EMPTY_TITLE,
    MY_SUBJECT_SUMMARY_BUTTON,
    PAGE_HEADING,
    SEARCH_FIELD,
    SUBJECTS_PANEL,
    SubjectsPage,
)
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

SUBJECTS_MODULE = "subjects"
SUBJECTS_ROUTE = "subjects"


# ─────────────── manage path: the SchoolAdmin runs the curriculum ────────────
#
# The role the workspace is built for: a SchoolAdmin holds
# ("manage", "subjects") on the seeded role
# (newschoolapp/db/repository/permissions.py), and page.tsx renders both the
# "Add Subject" trigger and every per-row menu behind
# ``usePermission("subjects", name === "manage")`` — so each control this test
# touches is one a read-only role never sees.
#
# "Manage" here is three writes against one subject, because that is the whole
# life of a curriculum entry: POST /subjects/ opens it, PUT /subjects/{id}
# corrects it, DELETE /subjects/{id} retires it. Doing all three to the *same*
# subject is deliberate — each assertion is made on the reloaded register row
# rather than on the success toast, so a write the frontend announced but that
# never reached the database fails on the following step instead of passing
# quietly. The delete also leaves the school exactly as provisioning left it.
#
# The branch has to be activated first, and this is not optional: a SchoolAdmin
# belongs to no branch, ``fetchSubjects`` only appends ``branch_id`` for that
# role when ``useBranchStore`` holds one, and ``list_subjects`` answers
# 400 BRANCH_ID_REQUIRED without it — which the page renders as its
# "Failed to load subjects data" panel rather than as an empty table.
#
# ``academics_only`` is the right plan for this: it licenses ``subjects`` while
# excluding fees, library and comms, so nothing on this screen depends on a
# module the school does not have.

MANAGE_SCENARIO = "academics_only"

# The sidebar entry for this module (SideNavigation/nav-config.tsx, "Academics
# Module" group) — note the label is not the route name.
NAV_SUBJECTS = re.compile(r"^\s*Subject\s*&\s*Topic\s*$", re.I)

# page.tsx renders Date Added through formatDateTime, i.e. toLocaleString with
# {month: "long", day: "2-digit", year: "numeric", hour/minute, hour12} — e.g.
# "August 07, 2026 at 09:41 AM". The separator between date and time differs
# between ICU versions, so it is matched loosely.
DATE_ADDED = re.compile(r"^\s*[A-Z][a-z]+\s+\d{2},\s+\d{4}\b.*\b\d{1,2}:\d{2}\s*[AP]M\s*$")

NEW_SUBJECT_DESCRIPTION = "Practical science for the upper primary stream."
CORRECTED_DESCRIPTION = (
    "Practical science for the upper primary stream, taught in the new lab."
)


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.subjects.manage.school_admin",
    title="Subjects",
    subtitle="SchoolAdmin creates and manages subjects",
)
def test_school_admin_creates_and_manages_a_subject(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin adds a subject to the curriculum, corrects it, retires it.

    Every assertion is made on the register the next person to open the screen
    would see — the row's own Subject, Date Added and Description cells — so a
    write that the UI reported as successful but that the backend never stored
    cannot pass.
    """
    ctx = provisioned_school
    assert SUBJECTS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {SUBJECTS_MODULE!r} for the "
        f"manage path — a school without the module has no workspace to manage"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — phase B creates one for "
        "every scenario, and GET /subjects/ is a 400 for a branch-less "
        "SchoolAdmin, so the register would never load"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    subjects = SubjectsPage(page, base_url)

    branch_name = str(ctx.branches[0]["name"])
    tag = run_tag()
    subject_name = f"TEST Chemistry {tag}"
    renamed_subject = f"TEST Chemistry Practical {tag}"

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Point the console at {branch_name}"):
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open Subject & Topic from the Academics menu"):
        link = page.get_by_role("link", name=NAV_SUBJECTS).first
        if link.count():
            link.click()
            page.wait_for_url(re.compile(rf"/module/{SUBJECTS_ROUTE}"), timeout=20_000)
            expect(page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
                timeout=20_000
            )
        else:
            # The sidebar collapses on narrow viewports; the workspace is the
            # point, not the way in.
            subjects.open()
        subjects.expect_no_load_failure()

    with demo.step("The curriculum already carries the subjects the school teaches"):
        if ctx.subjects:
            expect(subjects.find_row(SUBJECT_NAME)).to_be_visible(timeout=20_000)

    with demo.step("Add Chemistry to the curriculum"):
        # No classes: attaching a subject to a class is the Edit Class modal on
        # another route, and this unit is about the subject itself.
        subjects.create_subject(
            name=subject_name, classes=[], description=NEW_SUBJECT_DESCRIPTION
        )

    with demo.step("The new subject is on the register, described and dated"):
        # create_subject leaves the name it just typed in the search box, and
        # that box really does filter (see the module docstring). Clear it, so
        # every assertion from here on is made against the whole register rather
        # than against one filtered page of it — including the "the old name is
        # gone" claim below, which would otherwise be trivially true.
        subjects.search("")
        expect(subjects.cell(subject_name, "name")).to_have_text(subject_name)
        expect(subjects.cell(subject_name, "description")).to_have_text(
            NEW_SUBJECT_DESCRIPTION
        )
        expect(subjects.cell(subject_name, "date_added")).to_have_text(DATE_ADDED)

    with demo.step("Rename it, and say more precisely what it covers"):
        subjects.edit_subject(
            name=subject_name,
            new_name=renamed_subject,
            description=CORRECTED_DESCRIPTION,
        )

    with demo.step("The correction is what the register now shows"):
        expect(subjects.cell(renamed_subject, "name")).to_have_text(renamed_subject)
        expect(subjects.cell(renamed_subject, "description")).to_have_text(
            CORRECTED_DESCRIPTION
        )
        # Renamed, not duplicated: the name it was corrected *from* is gone.
        #
        # Asserted on the register's rows rather than page-wide, because antd
        # leaves every modal it has opened mounted-but-hidden and ``get_by_text``
        # matches hidden nodes — the Delete Subject confirmation below renders
        # the subject's name as literal text, so a page-wide count would be
        # asserting the modal's leftovers rather than the table.
        expect(subjects.find_row(subject_name)).to_have_count(0)
        subjects.expect_no_load_failure()

    with demo.step("Retire the subject, and it leaves the curriculum for good"):
        # delete_subject confirms the modal names this subject, then asserts the
        # row is gone from the reloaded register.
        subjects.delete_subject(name=renamed_subject)
        if ctx.subjects:
            # The rest of the curriculum is untouched — a delete that took the
            # whole branch's subjects with it would fail here.
            expect(subjects.find_row(SUBJECT_NAME)).to_be_visible(timeout=20_000)
        subjects.expect_no_load_failure()


# ───────────────────── negative path: the unlicensed school ──────────────────
#
# Constants below are prefixed rather than sharing the manage section's names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# Where the denial lives, and why the assertions below are the ones that prove it
#     Not in the sidebar, and not in a route guard. ``useModuleGuard`` hands a
#     SchoolAdmin ``hasAccess = true`` outright — it short-circuits on the
#     ``userRole`` cookie before it ever reads ``schoolModules`` — and
#     ``usePermissionGuard`` returns early for the same role ("SchoolAdmin has
#     access to all modules — they own the school config/governance pages"). So
#     /module/subjects redirects to neither /auth/no-access nor /unauthorized of
#     its own accord: the page really does mount. The seeded SchoolAdmin role
#     also *holds* ("manage", "subjects")
#     (newschoolapp/db/repository/permissions.py), so the permission half of the
#     backend gate passes too — which is asserted first below, so that the 403s
#     cannot be read as a role that never had subjects rights anyway.
#
#     What denies them is the feature-pack half of
#     ``utils.permissions.has_permission``: every /subjects route answers
#     **403 "Feature not available in your plan"**. Note the ordering that makes
#     that unambiguous — ``has_permission`` is a *route dependency*, so it runs
#     before ``list_subjects``'s own 400 BRANCH_ID_REQUIRED and before
#     ``get_subject_statistics`` looks at a branch at all. A licensed school
#     answers 200 or 400 on these calls; only an unlicensed one answers 403.
#
#     The UI consequence follows from that 403, and it does *not* end in this
#     screen's own PageError ("Failed to load subjects data", which the manage
#     path asserts the absence of). ``fetchAllSubjects``'s GET is refused, the
#     axios response interceptor in src/utils/handleErrorMessage.ts recognises
#     that particular detail (``shouldRedirectToNoAccess`` matches "not available
#     in your plan") and performs a hard ``window.location`` redirect to
#     **/auth/no-access**, rejecting the promise with ``FeatureNotAvailableError``
#     before page.tsx's own ``catch`` can put anything into ``fetchError``. So the
#     landing page, not the error panel, is the denial surface here.
#
#     Both halves are asserted, so a regression that silently starts serving
#     subjects to an unlicensed school fails here rather than passing as a blank
#     table.
#
#     Deliberately *not* asserted: that the sidebar hides "Subject & Topic". That
#     entry carries both ``permission: "subjects"`` and ``module: "subjects"``
#     (SideNavigation/nav-config.tsx), and for a SchoolAdmin the permission check
#     takes priority — so its presence or absence says nothing about this
#     school's feature pack, and asserting on it would be asserting the wrong
#     gate.

DENIED_SCENARIO = "minimal"

# The role whose permissions are checked against the pack in the negative path.
DENIED_ROLE = "SchoolAdmin"

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


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_subjects_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `subjects` off the pack, a SchoolAdmin gets no register and no data."""
    ctx = provisioned_school
    if SUBJECTS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {SUBJECTS_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ──────────────────
    role = api.get(f"/roles/{api.role_id_for(DENIED_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {DENIED_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_modules = {p.get("module") for p in role.json().get("permissions", [])}
    assert SUBJECTS_MODULE in role_modules, (
        f"the seeded {DENIED_ROLE} role no longer holds a {SUBJECTS_MODULE!r} "
        f"permission, so this test would be asserting a denial the role gets for "
        f"free. Re-point it at the feature pack only, or fix the seed in "
        f"newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{SUBJECTS_MODULE!r} proves nothing about the gate. Provisioning phase A "
        f"assigns one — check that it did."
    )
    assert SUBJECTS_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {SUBJECTS_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every subjects route is refused ─────────────────
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_param = f"branch_id={branch_id}" if branch_id else ""

    refusals = {
        # What the Subjects tab calls on mount…
        "list": api.get(f"/subjects/?skip=0&limit=10&{branch_param}", token=token),
        # …alongside the stat tiles above it.
        "statistics": api.get(
            f"/subjects/statistics/overview?{branch_param}", token=token
        ),
        # The read the Edit Class modal makes when it mirrors a class's curriculum.
        "class_subjects": api.get(f"/subjects/class/1?{branch_param}", token=token),
        # And the write half, so the gate is not merely read-only.
        "create": api.post(
            f"/subjects/?{branch_param}",
            token=token,
            json={
                "name": f"TEST Unlicensed Subject {run_tag()}",
                "description": "Must never be created — the pack excludes subjects.",
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{SUBJECTS_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a register in front of them ─────────────────
    login_as(page, frontend_base_url, ctx.school_admin)
    goto_module(page, frontend_base_url, SUBJECTS_ROUTE)

    # A SchoolAdmin is exempt from both frontend route guards, so /module/subjects
    # really does mount and really does ask for the list — which is refused…
    # …and the axios interceptor turns that answer into a hard redirect long
    # before PageError could render (see the section comment above). Waiting for
    # the URL is therefore also what stops the "register is absent" assertions
    # below from passing merely because the page had not finished loading.
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(
        timeout=15_000
    )
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the register came with them.
    expect(page.get_by_role("heading", name=as_pattern(PAGE_HEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(SUBJECTS_PANEL))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(SEARCH_FIELD))).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(ADD_SUBJECT_TRIGGER))
    ).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(ASSIGN_SUBJECTS_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)


# ──────────────── view path: a teacher reads their own curriculum ────────────
#
# Constants below are prefixed rather than sharing the sections above, for the
# same reason theirs are: this module file is written one unit at a time, and a
# shared module-level name would silently rebind under whichever section is
# appended last.
#
# What a teacher is actually allowed to see, and why that is the whole point
#     A Teacher holds ("read", "subjects") and nothing more
#     (newschoolapp/db/repository/permissions.py), so this is not a denial path:
#     the sidebar offers them "Subject & Topic", the register renders, and their
#     subjects are on it. What they must never get is a way to *change* the
#     curriculum — every write affordance on the screen is behind
#     ``usePermission("subjects", name === "manage")`` and every mutating
#     /subjects route is behind ``has_permission("manage", "subjects")``.
#
#     The register they get is also *narrower* than the school's.
#     ``SubjectService.list_subjects`` runs the branch's subjects through
#     ``scope_by_subject(resolve_academic_scope(...))``, which for a teacher
#     resolves to the subjects they are the subject teacher of, plus every
#     subject of any class they are class teacher of. So a subject the school
#     teaches but this teacher does not must not reach them at all — this test
#     seeds exactly such a subject and asserts its absence, because without a
#     control subject "the register shows Mathematics" would pass just as well
#     against a scoping filter that had been removed entirely.
#
# Where the second half of the story lives
#     /module/subjects/my-subject-summary, reached from the "My Subject Summary"
#     button page.tsx renders for the Teacher role alone. It answers what the
#     register cannot — *which classes* the teacher takes each subject for — and
#     it reads ``teacher_subject_class_association`` only, so being merely the
#     class teacher of a class does not put its subjects there. Provisioning
#     leaves its teacher exactly that (phase D logs
#     ``subject_teacher_unassigned``: the association is written from the
#     teaching-staff form, another module's walkthrough), so the fixture below
#     seeds the assignment over the API the same way the lessons and assessments
#     units do.
#
# A defect this unit uncovered (fixed in place, newschoolapp is dirty)
#     The "Search subject by name" box filtered nothing: page.tsx has always sent
#     ``?search=…``, but ``GET /subjects/`` declared no such parameter and
#     FastAPI dropped it, so every refetch came back the same unfiltered page.
#     ``SubjectService.list_subjects`` now applies a case-insensitive name match
#     before the teacher scoping, and the search steps below are what assert it —
#     including the one that matters most, that searching cannot reach *past* the
#     scope into a subject the teacher does not teach.

VIEW_SCENARIO = "academics_only"

# The subject the school teaches and this teacher does not. Seeded over the API
# as the SchoolAdmin and attached to no class, which is what keeps it outside
# ``resolve_academic_scope``'s answer for the teacher. Named with the "TEST"
# prefix the orphan sweeper matches on, and the run tag so parallel agents never
# collide.
UNTAUGHT_SUBJECT = f"TEST Latin {run_tag()}"
UNTAUGHT_DESCRIPTION = "Taught by another department — not this teacher's."

# What provisioning's SubjectsPage.create_subject writes into the description
# column for the subject the teacher does teach.
TAUGHT_DESCRIPTION = f"{SUBJECT_NAME} (integration test suite)"

# The one denial utils/permissions.py can answer a teacher with here: the school
# *is* licensed for subjects, so it is the role that is refused, never the plan.
# A "Feature not available in your plan" would mean this test had drifted onto a
# school whose pack omits the module, where it would prove nothing about roles.
TEACHER_DENIAL_DETAIL = re.compile(
    r"You do not have permission to perform this action", re.I
)

# The Assigned Subjects table renders "<n> class"/"<n> classes"; the teacher is
# seeded against exactly one.
ONE_CLASS = re.compile(r"^\s*1 class\s*$", re.I)


@dataclass(frozen=True)
class TeacherCurriculum:
    """The two subjects this unit puts in front of (and behind) the teacher."""

    branch_id: int
    taught_id: int
    taught_name: str
    untaught_id: int
    untaught_name: str


@pytest.fixture
def teacher_curriculum(
    provisioned_school: SchoolContext, api: BackendAPI
) -> TeacherCurriculum:
    """Make the teacher a subject teacher, and add a subject that is not theirs.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.branches, (
        "provisioning left this school with no branch, so there is no branch for "
        "a subject to belong to and the teacher's register cannot load"
    )
    assert ctx.subjects, (
        f"provisioning created no subject, so there is nothing for the teacher to "
        f"read — phase D creates {SUBJECT_NAME!r} whenever the scenario licenses "
        f"both subjects and classes"
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

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    untaught_id = _ensure_subject(
        api, token,
        branch_id=branch_id,
        name=UNTAUGHT_SUBJECT,
        description=UNTAUGHT_DESCRIPTION,
    )
    return TeacherCurriculum(
        branch_id=branch_id,
        taught_id=seed.subject_id,
        taught_name=SUBJECT_NAME,
        untaught_id=untaught_id,
        untaught_name=UNTAUGHT_SUBJECT,
    )


def _ensure_subject(
    api: BackendAPI, token: str, *, branch_id: int, name: str, description: str
) -> int:
    """Create a subject over the API, reusing one already under that name.

    Setup only, never an assertion. ``provisioned_school`` is session-scoped, so
    a rerun of this test inside one process would meet the subject it created
    last time — and the backend refuses a duplicate name within a branch.
    """
    existing = _find_subject(api, token, branch_id=branch_id, name=name)
    if existing is not None:
        return existing

    created = api.post(
        f"/subjects/?branch_id={branch_id}",
        token=token,
        json={"name": name, "description": description},
    )
    assert created.status_code < 400, (
        f"could not seed the control subject {name!r}: "
        f"{created.status_code} {created.text[:300]}"
    )
    return int(created.json()["id"])


def _find_subject(
    api: BackendAPI, token: str, *, branch_id: int, name: str
) -> int | None:
    listed = api.get(f"/subjects/?branch_id={branch_id}&limit=100", token=token)
    if listed.status_code >= 400:
        return None
    for row in listed.json():
        if str(row.get("name", "")).strip().casefold() == name.casefold():
            return int(row["id"])
    return None


@pytest.mark.teacher
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.subjects.view.teacher",
    title="Subjects",
    subtitle="Teacher views subjects",
)
def test_teacher_reads_the_subjects_they_teach(
    teacher_curriculum: TeacherCurriculum,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A teacher reads their own curriculum, and can change none of it."""
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert SUBJECTS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {SUBJECTS_MODULE!r} for this "
        f"unit — a teacher who is refused the module has no read-only view to show"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    subjects = SubjectsPage(page, base_url)
    summary = MySubjectSummaryPage(page, base_url)
    teacher = ctx.teacher

    with demo.step(
        f"Sign in as {teacher.full_name}, who teaches {SUBJECT_NAME} to {CLASS_NAME}"
    ):
        login_as(page, base_url, teacher)

    with demo.step("Their Academics menu offers Subject & Topic — open it"):
        # No branch to pick first: a branch is a SchoolAdmin-only concept, and a
        # teacher's own school_branch_id is what scopes GET /subjects/ for them.
        subjects.open_from_nav()
        subjects.expect_no_load_failure()
        expect(page.get_by_text(as_pattern(SUBJECTS_PANEL)).first).to_be_visible(
            timeout=20_000
        )

    with demo.step(
        f"The register holds {SUBJECT_NAME} — and only what this teacher teaches",
        dwell_ms=1800,
    ):
        expect(subjects.cell(SUBJECT_NAME, "name")).to_have_text(_exact(SUBJECT_NAME))
        expect(subjects.cell(SUBJECT_NAME, "description")).to_have_text(
            TAUGHT_DESCRIPTION
        )
        # The school teaches this one too; this teacher does not, so it must be
        # nowhere on the unfiltered register.
        expect(subjects.find_row(UNTAUGHT_SUBJECT)).to_have_count(0)

    with demo.step(f"Search the register by name for {SUBJECT_NAME}"):
        subjects.search(SUBJECT_NAME)
        expect(subjects.find_row(SUBJECT_NAME)).to_be_visible(timeout=20_000)
        subjects.expect_no_load_failure()

    with demo.step(
        "A subject the school teaches but this teacher does not cannot be found "
        "at all",
        dwell_ms=2000,
    ):
        subjects.search(UNTAUGHT_SUBJECT)
        expect(page.get_by_text(EMPTY_TITLE).first).to_be_visible(timeout=20_000)
        expect(page.get_by_text(EMPTY_DESCRIPTION).first).to_be_visible()
        expect(subjects.find_row(UNTAUGHT_SUBJECT)).to_have_count(0)

    with demo.step(
        "Nothing on the screen lets a teacher change the curriculum", dwell_ms=2000
    ):
        subjects.search("")
        expect(subjects.find_row(SUBJECT_NAME)).to_be_visible(timeout=20_000)

        # Always offered to a Teacher, so the two absences below cannot pass on a
        # header bar that simply never rendered.
        expect(
            page.get_by_role("button", name=as_pattern(MY_SUBJECT_SUMMARY_BUTTON))
        ).to_be_visible()
        expect(
            page.get_by_role("button", name=as_pattern(ADD_SUBJECT_TRIGGER))
        ).to_have_count(0)
        expect(
            page.get_by_role("button", name=as_pattern(ASSIGN_SUBJECTS_BUTTON))
        ).to_have_count(0)
        # The row's actions cell is empty for a read-only role — the kebab that
        # opens Edit subject / Delete subject is the only button a row ever has.
        expect(subjects.find_row(SUBJECT_NAME).get_by_role("button")).to_have_count(0)

    with demo.step(
        f"My Subject Summary says which classes they take {SUBJECT_NAME} for",
        dwell_ms=2500,
    ):
        subjects.click_button(MY_SUBJECT_SUMMARY_BUTTON)
        summary.expect_loaded()
        summary.expect_no_load_failure()
        summary.expect_teacher(teacher.full_name)

        expect(summary.cell(SUBJECT_NAME, "name")).to_contain_text(SUBJECT_NAME)
        expect(summary.cell(SUBJECT_NAME, "classes")).to_have_text(ONE_CLASS)
        # Same scoping, one screen further in: a subject they do not teach is not
        # summarised for them either.
        expect(summary.find_row(UNTAUGHT_SUBJECT)).to_have_count(0)

    with demo.step(
        "Behind the screen a teacher may read subjects, never write them",
        dwell_ms=2000,
    ):
        _expect_subjects_are_read_only_for_teacher(api, teacher, teacher_curriculum)


def _expect_subjects_are_read_only_for_teacher(
    api: BackendAPI, teacher: Credentials, curriculum: TeacherCurriculum
) -> None:
    """Assert the backend gives this teacher the same read-only deal the UI does.

    Without this the UI half proves only that the *frontend* hides the write
    controls, which a hand-built request would walk straight past — and only that
    the *rendered* register is scoped, which a client-side filter could fake.
    """
    token = api.login(teacher.email, teacher.password)["access_token"]

    # ── the read half: their own subjects, and no branch_id needed ────────────
    listed = api.get("/subjects/", token=token, params={"skip": 0, "limit": 100})
    assert listed.status_code == 200, (
        f"a teacher holds ('read', 'subjects'), and list_subjects derives their "
        f"branch from the user, so the register's own call must succeed — got "
        f"{listed.status_code}: {listed.text[:300]}"
    )
    names = {str(row.get("name", "")) for row in listed.json()}
    assert curriculum.taught_name in names, (
        f"{curriculum.taught_name!r} is missing from the teacher's list, so the "
        f"academic scoping has narrowed past the subjects they actually teach; "
        f"got {sorted(names)}"
    )
    assert curriculum.untaught_name not in names, (
        f"{curriculum.untaught_name!r} belongs to no class this teacher teaches, "
        f"so SubjectService.list_subjects must scope it out; got {sorted(names)}"
    )

    # Search narrows that same scoped list — it never reaches past it.
    searched = api.get(
        "/subjects/", token=token, params={"search": curriculum.untaught_name}
    )
    assert searched.status_code == 200, (
        f"search is a filter on a read the teacher is allowed to make — got "
        f"{searched.status_code}: {searched.text[:300]}"
    )
    assert searched.json() == [], (
        f"searching for a subject outside their scope must answer nothing, or "
        f"the name filter is being applied instead of the scoping rather than "
        f"alongside it; got {searched.json()!r}"
    )

    # ── the write half: refused on the role, whatever the subject ─────────────
    refusals: dict[str, Any] = {
        "create": api.post(
            "/subjects/",
            token=token,
            json={
                "name": f"TEST Teacher Should Not Create This {run_tag()}",
                "description": "Must never be created — a teacher cannot write.",
            },
        ),
        "update": api.put(
            f"/subjects/{curriculum.taught_id}",
            token=token,
            json={"name": f"TEST Teacher Renamed This {run_tag()}"},
        ),
        "archive": api.put(f"/subjects/{curriculum.taught_id}/archive", token=token),
        "delete": api.delete(f"/subjects/{curriculum.taught_id}", token=token),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a teacher holds only ('read', 'subjects'), so every "
            f"mutating /subjects route must refuse them with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert TEACHER_DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right, but the reason must be the role rather than "
            f"the feature pack — this school *is* licensed for "
            f"{SUBJECTS_MODULE!r}; got {detail!r}"
        )


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
