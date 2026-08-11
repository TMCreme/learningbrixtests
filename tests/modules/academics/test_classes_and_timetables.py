"""/module/classes_and_timetables — the "Manage Classes & Timetable" workspace.

Student path: a Student of the ``academics_only`` school — where the module IS
licensed — is nonetheless kept out of the workspace, because the seeded Student
role holds no ``classes_and_timetables`` permission at all
(``test_student_is_denied_the_classes_and_timetables_workspace``). See the
section comment above that test for why the app has no student-facing view of
this screen, which surfaces the denial lands on, and where a student's own
timetable actually lives.

Manage path: a SchoolAdmin of the ``academics_only`` school opens a class,
assigns its class teacher, corrects the record and reads the class's weekly
timetable (``test_school_admin_creates_and_manages_a_class``). See the section
comment above that test for why all three writes are aimed at one class, and why
an academics-only plan (no fee groups to pick) is the right school to prove them
on.

Teacher path: a class teacher of that same ``academics_only`` school reads the
register — the class they class-teach, its subjects and their own name in the
Class Teacher column — and is given no control that writes to it
(``test_teacher_views_classes_and_timetables``). See the section comment above
that test for why the Teacher role is the one for which this workspace is
genuinely read-only, and how the rows they see are scoped.

Negative path: a SchoolAdmin of a school whose feature pack
does NOT include ``classes_and_timetables`` (the ``minimal`` scenario).

Where the denial actually lives
    Not in the sidebar, and not in a route guard. ``src/middleware.ts`` skips its
    module gate for a SchoolAdmin ("SchoolAdmin bypasses: governance pages are
    not feature-flag modules"), ``useModuleGuard`` hands that role ``true``
    outright, and ``usePermissionGuard`` returns early for it — so
    /module/classes_and_timetables neither redirects to /auth/no-access nor to
    /unauthorized. The seeded SchoolAdmin role also *holds*
    ``("manage", "classes_and_timetables")``
    (newschoolapp/db/repository/permissions.py), so the permission half of the
    backend gate passes as well, and the sidebar entry — gated on the permission,
    not on the pack (SideNavigation: "Permission check takes priority — having
    the permission implies the module is available") — is still rendered. None of
    those three surfaces says anything about this school's plan, so none of them
    is asserted here.

    What actually denies them is the feature-pack half of
    ``utils.permissions.has_permission``, which every *gated* route in
    ``api/routes/class_route.py`` and ``api/routes/timetable.py`` depends on:
    they answer **403 "Feature not available in your plan"**. That 403 is the
    assertion this test is built on, and it is asserted across both halves of the
    module — the class routes and the timetable routes — and for both reads and
    writes, so the gate cannot regress into being write-only.

Why the register itself is only *read*, never expected to fail
    ``GET /classes/`` and ``GET /classes/{id}`` are the two routes in
    ``class_route.py`` that carry **no** ``has_permission`` dependency (the
    others all do), so an unlicensed school's class list is not refused — it is
    simply always empty, because every route that could put a class into it is.
    That asymmetry is deliberate downstream: six other screens read
    ``GET /classes/`` for roles that hold no ``classes_and_timetables``
    permission at all (the fees page, the fee report header, the student and
    staff admission wizards, the promotion modals, reminders), so adding the
    dependency there is a cross-module permission change, not a fix belonging to
    this unit. It is recorded here so the next unit does not re-derive it.

    The UI consequence, and what this test asserts, is therefore: the workspace
    mounts and stays *empty* — ``EmptyState`` "No classes found" in place of any
    row, and in particular no row for the class the refused ``POST /classes/``
    tried to create. A regression that starts serving classes to an unlicensed
    school fails on the 403s; a regression that lets one be *created* fails on
    the empty register.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import CLASS_NAME, SUBJECT_NAME, SchoolContext
from tests.pages.academics.classes import ADVANCED_SEARCH_BUTTON, ROW_COUNT_SUMMARY, ClassesPage
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

CLASSES_MODULE = "classes_and_timetables"
CLASSES_ROUTE = "classes_and_timetables"

DENIED_SCENARIO = "minimal"

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIAL_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# An id no school in this suite can own, so a *regressed* gate turns these two
# calls into a harmless 404 rather than mutating another school's data.
UNREACHABLE_ID = 999_999_999

# Real strings from src/app/module/classes_and_timetables/page.tsx and its
# ClassList/EmptyState children.
PAGE_HEADING = re.compile(r"^\s*Manage Classes\s*&\s*Timetable\s*$", re.I)
SEARCH_PLACEHOLDER = re.compile(r"^\s*Search class by name\s*$", re.I)
ADD_CLASS_BUTTON = re.compile(r"^\s*Add Class\s*$", re.I)
EMPTY_TITLE = re.compile(r"^\s*No classes found\s*$", re.I)
EMPTY_DESCRIPTION = re.compile(r"^\s*Add a class to get started\.\s*$", re.I)
# src/components/common/PageError.tsx, mounted with this exact title by the page
# whenever GET /classes/ does fail (a 400 without a branch, or a 403 should the
# route ever gain the feature-pack dependency the write routes carry).
LOAD_FAILURE_TITLE = re.compile(r"^\s*Failed to load classes\s*$", re.I)
# Where the frontend sends a user it has decided is not allowed in.
DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_classes_and_timetables_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `classes_and_timetables` off the pack, a SchoolAdmin can neither
    create a class nor reach any timetable, and the register stays empty."""
    ctx = provisioned_school
    if CLASSES_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {CLASSES_MODULE!r}; "
            f"the denial path only applies when the feature pack omits it"
        )

    assert ctx.branches, (
        "provisioning left this school with no branch, so there is no scope to "
        "read classes for — phase B creates one for every scenario"
    )
    branch = ctx.branches[0]
    branch_id = int(branch["id"]) if branch.get("id") else 0
    branch_query = f"?branch_id={branch_id}" if branch_id else ""

    class_name = f"TEST Unlicensed Class {run_tag()}"

    # ── the denial itself: every gated classes/timetables route is refused ────
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    refusals = {
        # The write half of the module — what the Add Class dialog posts.
        "create_class": api.post(
            "/classes/",
            token=token,
            json={
                "name": class_name,
                "description": "Must never be created — the pack excludes classes.",
                "school_branch_id": branch_id,
                "academic_year_id": 1,
                "subject_ids": [],
            },
        ),
        "delete_class": api.delete(f"/classes/{UNREACHABLE_ID}", token=token),
        # The two gated *reads* on the classes router (the plain list is not one
        # of them — see the module docstring).
        "current_year_classes": api.get(
            f"/classes/current-academic-year{branch_query}", token=token
        ),
        "previous_year_classes": api.get(
            f"/classes/previous-academic-year/{UNREACHABLE_ID}", token=token
        ),
        # And the timetable half, so the gate covers the whole module.
        "list_timetables": api.get(
            f"/timetables/?skip=0&limit=10{branch_query.replace('?', '&')}", token=token
        ),
        "create_timetable": api.post(
            f"/timetables/{branch_query}",
            token=token,
            json={
                "name": "TEST Unlicensed Timetable",
                "class_id": UNREACHABLE_ID,
                "academic_year_id": 1,
                "academic_term_id": 1,
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{CLASSES_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── and the workspace never puts a class in front of them ────────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Mandatory before the register reads anything at all: a SchoolAdmin belongs
    # to no branch, and page.tsx returns early from its fetch effect until
    # useBranchStore holds one ("if (!currentSchoolAdminBranch?.branch_id)
    # return"). Without this the list would be empty because nothing was ever
    # requested, which would prove nothing about the plan.
    BranchesPage(page, frontend_base_url).select_branch(str(branch["name"]))

    goto_module(page, frontend_base_url, CLASSES_ROUTE)

    surface = _wait_for_settled_surface(page)

    if surface == "redirected":
        # The strongest denial the app could give — nothing further to check.
        return

    if surface == "page_error":
        # Stronger than the empty register too: the read itself was refused, and
        # PageError renders the backend's own detail.
        expect(page.get_by_text(as_pattern(LOAD_FAILURE_TITLE))).to_be_visible()
        return

    # The register mounted — assert it mounted *empty*, and that the class the
    # refused POST tried to create is nowhere on it.
    expect(page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible()
    expect(page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))).to_be_visible()
    expect(page.get_by_text(as_pattern(EMPTY_TITLE))).to_be_visible()
    expect(page.get_by_text(as_pattern(EMPTY_DESCRIPTION))).to_be_visible()
    expect(page.get_by_text(as_pattern(re.escape(class_name)))).to_have_count(0)

    # The trigger is rendered — it is gated on the role permission, which this
    # SchoolAdmin holds — but pressing it can never produce a class, because
    # POST /classes/ is the 403 asserted above.
    expect(page.get_by_role("button", name=as_pattern(ADD_CLASS_BUTTON))).to_be_visible()


def _wait_for_settled_surface(page: Page, timeout_ms: int = 30_000) -> str:
    """Wait until /module/classes_and_timetables has stopped loading.

    Returns which of the three surfaces it settled on — ``"redirected"``,
    ``"page_error"`` or ``"empty_register"``. Waiting for one of them first is
    what stops the "no class rows" assertions below from passing merely because
    ``ClassTimeTableLoader`` was still on screen.
    """
    failure = page.get_by_text(as_pattern(LOAD_FAILURE_TITLE)).first
    empty = page.get_by_text(as_pattern(EMPTY_TITLE)).first

    remaining = timeout_ms
    step = 500
    while remaining > 0:
        if DENIAL_URL.search(page.url):
            return "redirected"
        if failure.count() > 0:
            return "page_error"
        if empty.count() > 0:
            return "empty_register"
        page.wait_for_timeout(step)
        remaining -= step

    raise AssertionError(
        "/module/classes_and_timetables neither redirected to a no-access page, "
        "nor rendered its load-failure panel, nor settled on the empty register "
        f"within {timeout_ms}ms — current url {page.url!r}. If the register "
        "listed classes instead, the feature-pack gate is not being enforced "
        "for this school."
    )


# ─────────────── manage path: the SchoolAdmin runs the register ──────────────
#
# The licensed half of the same screen, driven by the role the workspace is
# built for. A SchoolAdmin holds ``("manage", "classes_and_timetables")`` on the
# seeded role (newschoolapp/db/repository/permissions.py), which is what renders
# the "Add Class" trigger and the per-row action menu at all — so every control
# this test touches is one a read-only role never sees.
#
# "Manage" here is three writes against one class, because that is how the
# module is actually used: POST /classes/ opens the class, PATCH
# /classes/{id}/class-teacher puts a form teacher in front of it, and PUT
# /classes/{id} corrects the record afterwards. Doing all three to the *same*
# class is deliberate — each assertion is made on the reloaded register row, so
# a write that the frontend reported as successful but that never reached the
# database fails on the next step rather than passing quietly.
#
# The branch has to be activated first, exactly as for the read paths above: a
# SchoolAdmin belongs to no branch, page.tsx returns early from its fetch effect
# until ``useBranchStore`` holds one, and the Add Class dialog resolves
# ``school_branch_id`` from that same store — without it the create posts
# ``school_branch_id: 0`` and the backend answers 404 "The Branch does not
# exist".
#
# Note the fee group: ``academics_only`` excludes the ``fees`` module, so
# ``GET /fees/groups`` is a 403 for this school and the Fee Group dropdown offers
# nothing. ``class.fee_group_id`` is nullable and both dialogs leave the key out
# when unset, so a class is still fully creatable and editable — which is why
# this unit runs against an academics-only plan rather than a full one.

MANAGE_SCENARIO = "academics_only"

# The sidebar entry for this module (SideNavigation/nav-config.tsx), under the
# "Academics Module" group.
NAV_CLASSES_AND_TIMETABLES = re.compile(r"^\s*Classes & Timetables\s*$", re.I)

# Any /module/* route the pack licenses will do — all this needs is a page that
# mounts module/layout.tsx, which is what renders SideNavigation. `home` is on
# every scenario's pack, including this one.
HOME_ROUTE = "home"

NEW_CLASS_DESCRIPTION = (
    "Upper primary stream opened for the new intake."
)


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.classes_and_timetables.manage.school_admin",
    title="Classes & Timetables",
    subtitle="SchoolAdmin creates and manages classes & timetables",
)
def test_school_admin_creates_and_manages_a_class(
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A SchoolAdmin opens a class, staffs it, corrects it, and reads its timetable.

    Every assertion is made on the register the next person to open the screen
    would see — the row's own Class Name, Class Teacher and Subjects cells —
    rather than on the success toast, so a write that the UI announced but the
    backend never stored cannot pass.
    """
    ctx = provisioned_school
    assert CLASSES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {CLASSES_MODULE!r} for the "
        f"manage path — the denial path is the test above"
    )
    assert ctx.teacher is not None, (
        "provisioning created no teaching staff for this school, so there is "
        "nobody to make class teacher"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — phase B creates one for "
        "every scenario, and the Add Class dialog cannot resolve a "
        "school_branch_id without it"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    classes = ClassesPage(page, base_url)

    branch_name = str(ctx.branches[0]["name"])
    teacher_name = ctx.teacher.full_name
    tag = run_tag()
    class_name = f"TEST Grade 7 {tag}"
    renamed_class = f"TEST Grade 7 Gold {tag}"
    # Provisioning creates this subject and links it to its own class; the edit
    # below attaches it to the new one as well.
    subject_name = SUBJECT_NAME if ctx.subjects else ""

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Point the console at {branch_name}"):
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open Classes & Timetables from the Academics menu"):
        # Home first, and not as decoration: ``select_branch`` ends on
        # /module/community — that destination is hardcoded in
        # school_admin_dashboard/page.tsx and takes no account of the plan — and
        # this school's pack has no `community`, so that page's own 403 becomes a
        # hard redirect to /auth/no-access. Only /module/* is wrapped in the
        # layout that renders SideNavigation, so on /auth/no-access there is no
        # menu to click at all. Coming back to home is what lets this step reach
        # the module the way a real user reaches it, rather than by deep link.
        goto_module(page, base_url, HOME_ROUTE)

        # Scoped to the sidebar on purpose: home's own QuickActions panel carries
        # a "Classes & Timetables" tile with the same words. It is a <button>
        # with an onNavigate the page never passes, so it goes nowhere — matching
        # it instead of the menu entry would produce a step that clicks and
        # silently stays put.
        nav = page.get_by_role("navigation")
        link = nav.get_by_role("link", name=as_pattern(NAV_CLASSES_AND_TIMETABLES)).first
        # The sidebar paints a bare placeholder until the school's module list
        # has loaded, so the entry is not on screen the instant the page is —
        # ``count()`` on its own would race and silently take the fallback.
        try:
            link.wait_for(state="visible", timeout=20_000)
        except PlaywrightTimeoutError:
            # Narrow viewports drop the desktop sidebar entirely (module/layout
            # hides it under `md`). The workspace is the point, not the way in.
            classes.open()
        else:
            link.click()
            page.wait_for_url(re.compile(rf"/module/{CLASSES_ROUTE}"), timeout=20_000)
            expect(page.get_by_role("heading", name=as_pattern(PAGE_HEADING))).to_be_visible(
                timeout=20_000
            )
        classes.expect_no_load_failure()

    with demo.step(f"Open a new class for the {ctx.academic_year or 'current'} year"):
        # The dialog picks the active academic year and its first term itself —
        # it keeps "Save Class" disabled until both are set.
        classes.create_class(name=class_name)

    with demo.step(f"Hand the class over to {teacher_name}"):
        classes.assign_teacher(class_name=class_name, teacher_email=teacher_name)
        # ClassList renders the Class Teacher cell as an initials avatar
        # ("JB") followed by the name, so the cell's own text reads
        # "JBJoseph Brennan" — the name is contained, never the whole cell.
        expect(classes.cell(class_name, "class_teacher")).to_contain_text(
            as_pattern(re.escape(teacher_name))
        )

    with demo.step("Rename the stream and record what it is for"):
        classes.edit_class(
            class_name=class_name,
            new_name=renamed_class,
            description=NEW_CLASS_DESCRIPTION,
            subjects=[subject_name] if subject_name else None,
        )

    with demo.step("The register carries the class, its teacher and its subject"):
        expect(classes.cell(renamed_class, "name")).to_have_text(renamed_class)
        expect(classes.cell(renamed_class, "class_teacher")).to_contain_text(
            as_pattern(re.escape(teacher_name))
        )
        if subject_name:
            expect(classes.cell(renamed_class, "subjects")).to_have_text(subject_name)
        # The class it was renamed *from* is gone from the register, not
        # duplicated. Asserted on the table's rows rather than on the page's
        # text: page.tsx renders the "Add Class Teacher" step as an antd
        # <Modal title={`Assign Teacher to ${selectedClass?.name}`}>, and antd
        # leaves a closed modal mounted, so the pre-rename name survives in that
        # hidden title for as long as `selectedClass` is set. It is off screen
        # and refreshed the next time the modal is opened (handleOpenAddTeacher
        # Modal re-reads the class by id), so it is not a defect — but a
        # whole-page text search finds it.
        expect(classes.find_row(class_name)).to_have_count(0)
        classes.expect_no_load_failure()

    with demo.step("Open the new class's weekly timetable", dwell_ms=1500):
        classes.open_timetable(renamed_class)


# ─────────────── read-only path: the Student is kept out of it ───────────────
#
# Same route and the same *licensed* school as the SchoolAdmin paths above — the
# gate here is the role, not the feature pack. The seeded Student role holds only
# ``read home``, ``manage catalogue``, ``manage requests_and_renewals``,
# ``read categories``, ``read student_timetables``, ``read student_scores``,
# ``read messaging``, ``read community``, ``read change_requests``,
# ``read lessons`` and ``read families``
# (newschoolapp/db/repository/permissions.py), so it holds neither
# ``("read", "classes_and_timetables")`` nor ``("manage", …)``.
#
# That is deliberate product behaviour, not a gap this unit should "fix". This
# screen is the school's *administration* of its classes: it lists every class in
# the branch with its fee group and class teacher, and its row menu creates,
# edits, deletes and re-staffs them. A pupil's own read-only view of the same
# subject matter is a different screen entirely — /module/student_timetables,
# gated on ``("read", "student_timetables")``, which the Student role does hold
# and which this school's pack does license. So the read-only truth for this role
# at *this* route is the denial, and it is asserted on all three surfaces at once:
#
#   * the sidebar never offers "Classes & Timetables" — SideNavigation's
#     ``canShowItem`` resolves that entry on its ``permission:
#     "classes_and_timetables"`` gate, which a Student fails — while the
#     neighbouring "Student Timetable" entry, which they do hold, is still there;
#   * typing the route in anyway lands on /unauthorized: ``middleware.ts`` lets
#     them through (the school *is* licensed for the module, so the module gate
#     has nothing to refuse), ``useModuleGuard`` returns true for the same reason,
#     and ``usePermissionGuard("classes_and_timetables")`` is what pushes them
#     out — the page's own ``if (!hasPermission) return null`` meanwhile
#     guarantees the workspace never paints even for the frame before the push;
#   * and every *gated* /classes and /timetables route answers 403 "You do not
#     have permission to perform this action" — the permission half of
#     ``utils.permissions.has_permission`` refuses before the feature-pack half
#     is ever reached.
#
# ``GET /classes/`` is deliberately absent from that last list: it carries no
# ``has_permission`` dependency at all (see "Why the register itself is only
# *read*" in the module docstring), so a Student is not refused it either. Adding
# it here would assert a behaviour the backend does not implement and that six
# other screens depend on it not implementing.

STUDENT_VIEW_SCENARIO = "academics_only"

# Constants below are deliberately prefixed rather than sharing the neighbouring
# sections' names: this module file is written one role-section at a time, and a
# shared module-level name would silently rebind under whichever section happens
# to be appended last.

# The sidebar entry for this module (SideNavigation/nav-config.tsx), under the
# "Academics Module" group — the one a Student must never be offered.
STUDENT_NAV_CLASSES = re.compile(r"^\s*Classes\s*&\s*Timetables\s*$", re.I)
# The neighbouring Academics entry a Student *does* hold (read student_timetables),
# and their real read-only view of their own week. Asserted visible so that "no
# Classes & Timetables entry" cannot pass on a sidebar that simply never rendered.
NAV_STUDENT_TIMETABLE = re.compile(r"^\s*Student Timetable\s*$", re.I)

# src/app/unauthorized/page.tsx, where usePermissionGuard sends them.
UNAUTHORIZED_URL = re.compile(r"/unauthorized")
ACCESS_DENIED_HEADING = re.compile(r"^\s*Access Denied\s*$", re.I)

# The one denial utils/permissions.py can answer with here: the school holds the
# module, so it is the role that is refused, never the plan.
STUDENT_ROLE_DENIAL_DETAIL = re.compile(
    r"You do not have permission to perform this action", re.I
)


@pytest.mark.student
@pytest.mark.scenario(STUDENT_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.classes_and_timetables.view.student",
    title="Classes & Timetables",
    subtitle="Student is kept out of the class register",
)
def test_student_is_denied_the_classes_and_timetables_workspace(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A pupil of the licensed school gets no class register, by menu or by URL.

    The subtitle deliberately does not read "Student views classes & timetables":
    the app implements no such view at this route (see the section comment
    above), and captioning the footage that way would promise a viewer a screen
    they are never going to see. What the video shows instead is the honest
    read-only truth for this role — the school's class administration is closed
    to them, while their own timetable entry sits right beside it in the menu.
    """
    ctx = provisioned_school
    assert ctx.student is not None, "provisioning admitted no student for this school"
    assert CLASSES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {CLASSES_MODULE!r} for this "
        f"unit — the point is that the Student is refused on their *role*, with "
        f"the feature pack having nothing to say about it"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    student = ctx.student

    # Every step here is an assertion rather than an interaction, so the actions
    # themselves take almost no wall-clock time. Without an explicit dwell the six
    # captions would land inside ~4s of footage — most of it under the title card —
    # and none of them would be readable. The dwell only ever applies to demo runs.
    with demo.step(
        f"Sign in as {student.full_name}, a pupil at {ctx.school_name}", dwell_ms=3000
    ):
        login_as(page, base_url, student)

    with demo.step(
        "A pupil lands in their own corner of the school", dwell_ms=2500
    ):
        expect(
            page.get_by_role("link", name=as_pattern(NAV_STUDENT_TIMETABLE)).first
        ).to_be_visible(timeout=20_000)

    with demo.step(
        "Their Academics menu offers their own timetable, never the class register",
        dwell_ms=2500,
    ):
        expect(
            page.get_by_role("link", name=as_pattern(STUDENT_NAV_CLASSES))
        ).to_have_count(0)

    with demo.step(
        "Try the register anyway, straight from the address bar", dwell_ms=2000
    ):
        goto_module(page, base_url, CLASSES_ROUTE)

    with demo.step(
        "The app turns the pupil away — managing classes is staff work", dwell_ms=2500
    ):
        page.wait_for_url(UNAUTHORIZED_URL, timeout=20_000)
        expect(page.get_by_text(as_pattern(ACCESS_DENIED_HEADING)).first).to_be_visible()

        expect(page.get_by_role("heading", name=PAGE_HEADING)).to_have_count(0)
        expect(page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))).to_have_count(0)
        expect(
            page.get_by_role("button", name=as_pattern(ADD_CLASS_BUTTON))
        ).to_have_count(0)
        expect(page.get_by_role("row")).to_have_count(0)

    with demo.step(
        "Behind the screen, every class and timetable route is refused for them too",
        dwell_ms=2500,
    ):
        _expect_classes_and_timetables_refused_for_student(api, ctx)


def _expect_classes_and_timetables_refused_for_student(
    api: BackendAPI, ctx: SchoolContext
) -> None:
    """Assert the backend refuses this Student on both halves of the module.

    Without this the UI half proves only that the *frontend* hides the register,
    which a hand-built request would walk straight past. Reads and writes are
    both covered so the gate cannot regress into being write-only, and the ids in
    the paths are never looked up: ``has_permission`` is a route dependency, so it
    raises before the endpoint body runs — and ``UNREACHABLE_ID`` means that a
    *regressed* gate turns the two mutating calls into a harmless 404 rather than
    letting a pupil delete a real class.
    """
    assert ctx.student is not None
    token = api.login(ctx.student.email, ctx.student.password)["access_token"]

    refusals = {
        # The gated reads on the classes router (the plain list is not one of
        # them — see the module docstring).
        "current_year_classes": api.get("/classes/current-academic-year", token=token),
        "previous_year_classes": api.get(
            f"/classes/previous-academic-year/{UNREACHABLE_ID}", token=token
        ),
        # The write half — what the Add Class dialog and the row menu post.
        "create_class": api.post(
            "/classes/",
            token=token,
            json={
                "name": f"TEST Student Should Not Create This {run_tag()}",
                "description": "Must never be created — a pupil cannot manage classes.",
                "school_branch_id": int(ctx.branches[0]["id"]) if ctx.branches else 0,
                "academic_year_id": 1,
                "subject_ids": [],
            },
        ),
        "delete_class": api.delete(f"/classes/{UNREACHABLE_ID}", token=token),
        # And the timetable half, so the gate covers the whole module.
        "list_timetables": api.get("/timetables/?skip=0&limit=10", token=token),
        "read_timetable": api.get(f"/timetables/{UNREACHABLE_ID}", token=token),
        "create_timetable": api.post(
            "/timetables/",
            token=token,
            json={
                "name": "TEST Student Should Not Create This Timetable",
                "class_id": UNREACHABLE_ID,
                "academic_year_id": 1,
                "academic_term_id": 1,
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a Student of {ctx.school_name!r} holds no "
            f"{CLASSES_MODULE!r} permission, so the backend must refuse with "
            f"403 — got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert STUDENT_ROLE_DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not the role denial this "
            f"school's pack implies — {CLASSES_MODULE!r} is licensed here, so a "
            f"plan-level refusal would mean the permission gate stopped running. "
            f"Got {detail!r}"
        )


# ─────────────── read-only path: the class teacher reads the register ────────
#
# The Teacher role is seeded with ``("read", "classes_and_timetables")`` and
# never ``("manage", …)`` (newschoolapp/db/repository/permissions.py), so this is
# the one role for which the workspace is genuinely read-only — and the frontend
# says so on its own: page.tsx renders "Add Class" behind
# ``usePermission("classes_and_timetables", name === "manage")``, and ClassList
# renders both the Actions column and its per-row menu behind the same check.
# A teacher therefore sees the register and nothing that writes to it.
#
# The rows they see are scoped further, in the backend rather than the browser:
# ``ClassService.list_classes`` runs every non-admin caller through
# ``resolve_academic_scope`` (newschoolapp/utils/academic_scope.py), which for a
# teacher resolves to the classes they class-teach plus the (subject, class)
# pairs they are assigned. Provisioning makes this teacher the class teacher of
# CLASS_NAME, so that class is exactly what the register must offer them.
#
# No branch has to be activated first, unlike the SchoolAdmin read: a teacher
# belongs to a branch, so ``list_classes`` derives ``branch_id`` from their own
# account and the frontend never consults ``useBranchStore`` for this role.

TEACHER_VIEW_SCENARIO = "academics_only"

# The sidebar entry for this module (SideNavigation/nav-config.tsx), under the
# "Academics Module" group. It is gated on the *permission*, which a Teacher
# holds at "read", so it is offered to them. Named apart from the other sections'
# copies of this pattern so each unit stays deletable on its own.
TEACHER_NAV_CLASSES = re.compile(r"^\s*Classes\s*&\s*Timetables\s*$", re.I)

# A class name no school in this suite owns, so filtering by it is guaranteed to
# empty the register rather than to accidentally match a real row.
ABSENT_CLASS_QUERY = "Zzz Nonexistent Class"

# ClassList renders "MMM d, yyyy" through date-fns for every row's Date Added.
DATE_ADDED = re.compile(r"^\s*[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s*$")

# The only denial the backend can answer a teacher of this school with: the pack
# licenses the module, so it is the role that is refused, never the plan.
TEACHER_ROLE_DENIAL_DETAIL = re.compile(
    r"You do not have permission to perform this action", re.I
)


@pytest.mark.teacher
@pytest.mark.scenario(TEACHER_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.classes_and_timetables.view.teacher",
    title="Classes & Timetables",
    subtitle="Teacher views classes & timetables",
)
def test_teacher_views_classes_and_timetables(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A class teacher reads their own class off the register and changes nothing.

    The read *is* the feature for this role. Every assertion is therefore made on
    what the register actually renders — the row for the class they teach, the
    subjects on it, their own name in the Class Teacher column — plus the two
    filters a teacher genuinely uses (the name search and Reset Filter), and
    never on a control they are not given.

    The last step goes behind the screen on purpose: the UI half only proves the
    frontend *hides* the write controls, which a hand-built request would walk
    straight past. Asserting the 403s as well is what makes "read-only" a
    property of the app rather than of its markup.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert CLASSES_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {CLASSES_MODULE!r} for this "
        f"unit — the point is the read-only *role*, with the feature pack having "
        f"nothing to say about it"
    )
    assert ctx.classes, "provisioning created no class for this school to read"

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    classes = ClassesPage(page, base_url)
    teacher_name = ctx.teacher.full_name

    with demo.step(f"Sign in as {teacher_name}, a class teacher at {ctx.school_name}"):
        login_as(page, base_url, ctx.teacher)

    with demo.step("Open Classes & Timetables from the Academics menu"):
        # Scoped to the sidebar, and waited for rather than counted. SideNavigation
        # paints its sections only once the school's module list has resolved, so
        # the entry is not on screen the instant the post-login page is — a bare
        # ``count()`` here would race, silently take the deep-link fallback, and
        # record a video in which nobody ever opens the menu.
        nav = page.get_by_role("navigation")
        link = nav.get_by_role("link", name=as_pattern(TEACHER_NAV_CLASSES)).first
        try:
            link.wait_for(state="visible", timeout=20_000)
        except PlaywrightTimeoutError:
            # Narrow viewports drop the desktop sidebar entirely (module/layout
            # hides it under `md`). The register is the point, not the way in.
            classes.open()
        else:
            link.click()
            page.wait_for_url(re.compile(rf"/module/{CLASSES_ROUTE}"), timeout=20_000)
            expect(page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(
                timeout=20_000
            )
        classes.expect_no_load_failure()

    with demo.step(f"The register opens on the classes they teach — starting with {CLASS_NAME}"):
        expect(classes.find_row(CLASS_NAME)).to_be_visible(timeout=20_000)
        expect(page.get_by_text(ROW_COUNT_SUMMARY).first).to_be_visible()

    with demo.step(f"Read {CLASS_NAME} at a glance — its subjects and who class-teaches it"):
        expect(classes.cell(CLASS_NAME, "name")).to_have_text(_exact_text(CLASS_NAME))
        expect(classes.cell(CLASS_NAME, "class_teacher")).to_contain_text(
            as_pattern(re.escape(teacher_name))
        )
        expect(classes.cell(CLASS_NAME, "date_added")).to_have_text(DATE_ADDED)
        if ctx.subjects:
            expect(classes.cell(CLASS_NAME, "subjects")).to_contain_text(
                as_pattern(re.escape(SUBJECT_NAME))
            )

    with demo.step("Look the class up by name, the way a teacher with a full timetable would"):
        classes.search(CLASS_NAME.split()[0])
        expect(classes.find_row(CLASS_NAME)).to_be_visible(timeout=15_000)
        classes.expect_no_load_failure()

    with demo.step("A name that is on nobody's timetable comes back empty"):
        classes.search(ABSENT_CLASS_QUERY)
        classes.expect_empty()
        expect(classes.find_row(CLASS_NAME)).to_have_count(0)

    with demo.step("Clear the filter and the full register is back"):
        classes.reset_filters()
        expect(classes.find_row(CLASS_NAME)).to_be_visible(timeout=20_000)
        classes.expect_no_load_failure()
        # Advanced Search stays on offer — it reads, so it is not a write control.
        expect(
            page.get_by_role("button", name=ADVANCED_SEARCH_BUTTON).first
        ).to_be_visible()

    with demo.step("Nothing on this screen is theirs to change — the register is read-only"):
        # The Actions column is still there; what a teacher gets inside it is the
        # read ("View Timetable"), never the menu that edits or deletes.
        classes.expect_read_only(CLASS_NAME)

    with demo.step("Behind the screen, every write to a class is refused for them too"):
        _expect_class_writes_refused_for_teacher(api, ctx)


def _expect_class_writes_refused_for_teacher(api: BackendAPI, ctx: SchoolContext) -> None:
    """Assert the teacher's token reads the module but cannot write to it.

    The ids in the write paths are never looked up: ``has_permission`` is a route
    dependency, so it raises before the endpoint body — and before any real class
    could be touched. ``UNREACHABLE_ID`` is used anyway so that a *regressed*
    gate turns these calls into a harmless 404 rather than into a mutation of
    somebody's data.

    The reads are asserted in the same pass, because "403 on everything" would
    also satisfy a write-only assertion while describing a broken module: this
    role is supposed to be let in, just not let loose.
    """
    assert ctx.teacher is not None
    token = api.login(ctx.teacher.email, ctx.teacher.password)["access_token"]

    allowed = {
        # The register itself, and the timetable half of the module — both carry
        # has_permission("read", "classes_and_timetables").
        "list_classes": api.get("/classes/?skip=0&limit=10", token=token),
        "current_year_classes": api.get("/classes/current-academic-year", token=token),
        "list_timetables": api.get("/timetables/?skip=0&limit=10", token=token),
    }
    for label, res in allowed.items():
        assert res.status_code == 200, (
            f"{label}: a Teacher holds ('read', {CLASSES_MODULE!r}) and their "
            f"school licenses the module, so this read must succeed — got "
            f"{res.status_code}: {res.text[:300]}"
        )

    refusals = {
        "create_class": api.post(
            "/classes/",
            token=token,
            json={
                "name": f"TEST Teacher Should Not Create {run_tag()}",
                "description": "Must never be created — a teacher only reads classes.",
                "school_branch_id": int(ctx.branches[0]["id"]) if ctx.branches else 0,
                "academic_year_id": 1,
                "subject_ids": [],
            },
        ),
        "delete_class": api.delete(f"/classes/{UNREACHABLE_ID}", token=token),
        "create_timetable": api.post(
            "/timetables/",
            token=token,
            json={
                "name": "TEST Teacher Should Not Create Timetable",
                "class_id": UNREACHABLE_ID,
                "academic_year_id": 1,
                "academic_term_id": 1,
            },
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a Teacher holds only ('read', {CLASSES_MODULE!r}), so the "
            f"backend must refuse this write with 403 — got {res.status_code}: "
            f"{res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert TEACHER_ROLE_DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not the role denial this "
            f"school's pack implies — {CLASSES_MODULE!r} is licensed here, so a "
            f"plan-level refusal would mean the permission gate stopped running. "
            f"Got {detail!r}"
        )


def _exact_text(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
