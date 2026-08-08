"""/module/syllabus — the "Syllabus Management" register.

The ledger's module key is ``syllabi`` (the permission, the feature-pack entry
and the backend prefix all spell it that way); the frontend route is singular,
``/module/syllabus``, and the sidebar entry reads "Syllabus".

Positive path: a teacher of the ``academics_only`` school drafts a syllabus for
a subject they teach, revises it, and publishes it
(``test_teacher_creates_and_manages_syllabus``).

Negative path: a SchoolAdmin of the ``minimal`` school, whose feature pack does
NOT include ``syllabi``
(``test_syllabi_denied_for_school_admin_when_module_disabled``). Where that
denial lives is spelled out in the section comment above that test — briefly:
not in the sidebar and not in a route guard, but in the feature-pack half of
``utils.permissions.has_permission``, whose 403 the axios interceptor turns into
a hard redirect to /auth/no-access.

What has to be true before the feature is reachable
    A syllabus is keyed on **(class, subject, academic year, academic term)**,
    and ``SyllabusService._assert_can_manage`` lets a teacher write one only for
    a (subject, class) pair they are the **subject teacher** of. Provisioning
    makes its teacher the *class* teacher of "Grade 6", which
    ``can_manage_subject_class`` deliberately ignores — that grants reads and no
    writes at all, so without the assignment the create answers 403 "Only the
    subject teacher can manage this syllabus".

    So the fixture below seeds, over the API as the SchoolAdmin (setup only,
    never asserted — the same use of ``api`` that
    ``school_provisioning._seed_fee_group`` makes):

    * **its own subject**, added to "Grade 6"'s curriculum. Deliberately *not*
      the provisioned "Mathematics": ``create_syllabus`` refuses a duplicate
      (class, term, year, subject) with a 400, and ``tests/flows/academics_seed``
      already puts a Mathematics/Grade 6 syllabus on this very school for the
      lessons and assessments units. Since ``provisioned_school`` is
      session-scoped, that syllabus exists by the time this test runs, and
      reusing the pair would fail on a collision that says nothing about
      syllabi. A subject of its own also keeps the topic list on the create form
      down to exactly the topics this test seeded.
    * the **(subject, class) teaching assignment**, which is the authorization
      above.
    * three **topics** under that subject, because a syllabus with no topics
      cannot be published ("Cannot publish syllabus without topics") and the
      teaching sequence is the substance of the thing.

What "manage" means here, and where each half lives
    Class/subject/year/term are chosen on ``/module/syllabus/add`` and **nowhere
    else** — the edit route renders them as read-only "Fixed Context", since
    changing them would move the syllabus into a slot the create path guards for
    uniqueness. So the create step is the only place the pairing can be
    asserted, and the edit step covers what genuinely is editable: the name, the
    description, and which topics are on the sequence.

    Publishing is a route of its own (``POST /syllabi/{id}/publish``), reached
    from the row menu, and it is the transition that matters to everyone
    downstream: ``/module/lessons`` only cascades onto syllabi, and a draft is a
    private working document until it is published.

A backend defect this unit uncovered (fixed in place, newschoolapp is dirty)
    The register's "Search syllabus..." box had always sent ``search=<term>``
    (``GetSyllabus`` in ``syllabusHandler.ts``), but ``GET /syllabi/`` declared
    no such query parameter, so FastAPI dropped it and the identical unfiltered
    page came back. On a list that is server-paginated at 10 rows that left the
    register's only text lookup dead. ``list_syllabi`` now takes ``search`` and
    matches it against name and description; see ``state/backend_patches.md``.
    This test searches, so the fix is covered rather than merely applied.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import (
    ACADEMIC_YEAR_NAME,
    CLASS_NAME,
    TERM_NAME,
    SchoolContext,
)
from tests.pages.academics.syllabi import (
    ARCHIVE_ITEM,
    DELETE_ITEM,
    DOWNLOAD_ITEM,
    EDIT_ITEM,
    PUBLISH_ITEM,
    SyllabiPage,
)
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as

SYLLABI_MODULE = "syllabi"
SYLLABI_SCENARIO = "academics_only"

# The sidebar entry (SideNavigation/nav-config.tsx). The Academics section is
# `branchOnly`, but that flag only ever applies to a SchoolAdmin — branch state
# is a SchoolAdmin-only concept — so for a teacher the link is on screen
# straight after login.
NAV_SYLLABUS = re.compile(r"^\s*Syllabus\s*$", re.I)

# Everything this unit creates carries the "TEST" prefix the orphan sweeper
# matches on, plus the run tag so parallel agents never collide.
TAG = run_tag()
SUBJECT_NAME = f"TEST Integrated Science {TAG}"
SYLLABUS_NAME = f"TEST Integrated Science Term Syllabus {TAG}"
SYLLABUS_DESCRIPTION = (
    "First-term coverage for Integrated Science: what gets taught, in what "
    "order, and what the class should be able to do by the end of it."
)
REVISED_DESCRIPTION = (
    "Revised after the department meeting: energy moves ahead of forces, and "
    "the field trip write-up is now optional."
)

# Ordered as the teacher wants them taught. The third is added only during the
# edit step, so "the sequence really changed" is an assertion and not a hope.
TOPIC_MATTER = f"TEST States of Matter {TAG}"
TOPIC_ENERGY = f"TEST Energy and Its Forms {TAG}"
TOPIC_FORCES = f"TEST Forces and Motion {TAG}"
SEEDED_TOPICS = (TOPIC_MATTER, TOPIC_ENERGY, TOPIC_FORCES)


@dataclass(frozen=True)
class SyllabusSeed:
    """The (class, subject) pair this teacher is licensed to write for."""

    branch_id: int
    class_id: int
    subject_id: int
    subject_name: str
    topic_names: tuple[str, ...]


class SyllabusSeedError(RuntimeError):
    """A prerequisite could not be seeded, so the feature is unreachable."""


@pytest.fixture
def syllabus_seed(provisioned_school: SchoolContext, api: BackendAPI) -> SyllabusSeed:
    """A subject on Grade 6's curriculum that the teacher is subject teacher of.

    Requested *before* the ``demo`` fixture in the test signature so the seeding
    HTTP calls happen before the camera rolls, rather than as dead frames at the
    head of the video.

    Idempotent: ``provisioned_school`` is session-scoped, so this may be reached
    more than once against the same school. Everything it creates is looked up
    first (subject names are unique per branch and topic names unique per
    subject — the backend refuses a second create either way).
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert ctx.branches, "provisioning created no branch for this school"
    assert ctx.classes, (
        "provisioning created no class, so there is nothing to write a syllabus "
        "for — check that the scenario licenses classes_and_timetables"
    )

    branch_id = int(ctx.branches[0]["id"])
    if branch_id <= 0:
        raise SyllabusSeedError("provisioning captured no branch id")

    token = _login(api, ctx.school_admin.email, ctx.school_admin.password)

    class_id = _find_id(
        _rows(_json(api.get(f"/classes/?branch_id={branch_id}&limit=100", token=token))),
        CLASS_NAME,
        what="class",
    )
    subject_id = _ensure_subject(api, token, branch_id=branch_id)
    _attach_subject_to_class(api, token, class_id=class_id, subject_id=subject_id)
    _assign_subject_teacher(
        api, token,
        teacher_profile_id=_teacher_profile_id(
            api, token, branch_id=branch_id, email=ctx.teacher.email
        ),
        subject_id=subject_id,
        class_id=class_id,
    )
    _ensure_topics(api, token, branch_id=branch_id, subject_id=subject_id)

    return SyllabusSeed(
        branch_id=branch_id,
        class_id=class_id,
        subject_id=subject_id,
        subject_name=SUBJECT_NAME,
        topic_names=SEEDED_TOPICS,
    )


@pytest.mark.teacher
@pytest.mark.scenario(SYLLABI_SCENARIO)
@pytest.mark.demo(
    feature_id="academics.syllabi.manage.teacher",
    title="Syllabi",
    subtitle="Teacher creates and manages syllabi",
)
def test_teacher_creates_and_manages_syllabus(
    syllabus_seed: SyllabusSeed,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A subject teacher drafts a syllabus, revises it, and publishes it."""
    ctx = provisioned_school
    assert ctx.teacher is not None, "provisioning created no teacher for this school"
    assert SYLLABI_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {SYLLABI_MODULE!r} for this "
        f"unit — a teacher refused the module has no syllabus to manage"
    )

    page: Page = demo.page
    syllabi = SyllabiPage(page, demo.frontend_base_url)
    subject = syllabus_seed.subject_name

    with demo.step(
        f"Sign in as {ctx.teacher.full_name}, who teaches {CLASS_NAME}"
    ):
        login_as(page, demo.frontend_base_url, ctx.teacher)

    with demo.step("Open Syllabus from the Academics menu"):
        link = page.get_by_role("link", name=as_pattern(NAV_SYLLABUS)).first
        expect(link).to_be_visible(timeout=20_000)
        link.click()
        syllabi.expect_loaded()
        syllabi.expect_no_load_failure()
        syllabi.wait_for_rows()

    with demo.step("Start a syllabus for the term ahead"):
        syllabi.open_create_form()

    with demo.step(f"Name it, and pin it to {CLASS_NAME} for {TERM_NAME}"):
        syllabi.fill_create_form(
            name=SYLLABUS_NAME,
            class_name=CLASS_NAME,
            subject_name=subject,
            academic_year=ACADEMIC_YEAR_NAME,
            academic_term=TERM_NAME,
            description=SYLLABUS_DESCRIPTION,
        )

    with demo.step("Choose the topics the term will cover, and their order"):
        syllabi.select_topic(TOPIC_MATTER)
        syllabi.set_topic_order(TOPIC_MATTER, 1)
        syllabi.select_topic(TOPIC_ENERGY)
        syllabi.set_topic_order(TOPIC_ENERGY, 2)
        syllabi.expect_topics_selected(2)

    with demo.step("Save it — the syllabus lands on the register as a draft",
                   dwell_ms=1500):
        syllabi.submit_create()
        syllabi.search(SYLLABUS_NAME)
        syllabi.expect_row(SYLLABUS_NAME)

        syllabi.expect_context(
            SYLLABUS_NAME, class_name=CLASS_NAME, subject_name=subject
        )
        syllabi.expect_period(
            SYLLABUS_NAME, year=ACADEMIC_YEAR_NAME, term=TERM_NAME
        )
        syllabi.expect_description(SYLLABUS_NAME, SYLLABUS_DESCRIPTION)
        # A new syllabus is a private working document until it is published.
        syllabi.expect_status(SYLLABUS_NAME, "draft")

    with demo.step("Reopen it to revise the plan and add a third topic",
                   dwell_ms=1500):
        syllabi.open_edit_form(SYLLABUS_NAME)
        syllabi.expect_topics_included(2)
        syllabi.fill_edit_form(description=REVISED_DESCRIPTION)
        syllabi.select_topic(TOPIC_FORCES)
        syllabi.set_topic_order(TOPIC_FORCES, 3)
        syllabi.expect_topics_included(3)
        syllabi.submit_update()

        syllabi.search(SYLLABUS_NAME)
        syllabi.expect_row(SYLLABUS_NAME)
        syllabi.expect_description(SYLLABUS_NAME, REVISED_DESCRIPTION)
        syllabi.expect_status(SYLLABUS_NAME, "draft")

    with demo.step("Publish it, so the school can teach from it", dwell_ms=1800):
        # The row menu is the teacher's whole manage surface; asserting it in
        # full here means a regression that quietly drops one of these controls
        # fails as a missing affordance rather than as a puzzling later timeout.
        syllabi.open_row_menu(SYLLABUS_NAME)
        for item in (DOWNLOAD_ITEM, EDIT_ITEM, PUBLISH_ITEM, ARCHIVE_ITEM, DELETE_ITEM):
            expect(page.get_by_role("menuitem", name=item)).to_be_visible()
        syllabi.close_row_menu()

        syllabi.publish(SYLLABUS_NAME)
        syllabi.expect_row(SYLLABUS_NAME)
        syllabi.expect_status(SYLLABUS_NAME, "published")

    with demo.step(
        "The published syllabus reads back with its teaching sequence intact",
        dwell_ms=2500,
    ):
        syllabi.open_details(SYLLABUS_NAME)
        # Read from /syllabi/{id}/topics rather than from the form's own state,
        # so this is the proof the sequence was persisted and not merely posted.
        for topic in (TOPIC_MATTER, TOPIC_ENERGY, TOPIC_FORCES):
            syllabi.expect_details_topic(topic)
        syllabi.close_details()


# ───────────────────── negative path: the unlicensed school ──────────────────
#
# Constants below are prefixed rather than sharing the manage section's names:
# this module file is written one unit at a time, and a shared module-level name
# would silently rebind under whichever section is appended last.
#
# Where the denial actually lives
#     Not in the sidebar, and not in a route guard. ``useModuleGuard`` hands a
#     SchoolAdmin ``hasAccess = true`` outright — it short-circuits on the
#     ``userRole`` cookie before it ever reads the ``schoolModules`` cookie — and
#     ``usePermissionGuard`` returns early for the same role. So
#     /module/syllabus, /module/syllabus/add and /module/syllabus/edit/{id} all
#     really do mount for them. The seeded SchoolAdmin role also *holds*
#     ``("manage", "syllabi")`` (newschoolapp/db/repository/permissions.py), so
#     the permission half of the backend gate passes too — which is asserted
#     first below, so the 403s cannot be read as a role that never had syllabus
#     rights anyway.
#
#     What denies them is the feature-pack half of
#     ``utils.permissions.has_permission``: every route on
#     ``api/routes/syllabus.py`` carries a ``Depends(has_permission(…, "syllabi"))``,
#     that dependency is solved before the handler runs — before
#     ``branch_id_required``'s 400 and before any row is looked up — so for a
#     school whose pack omits ``syllabi`` it answers
#     **403 "Feature not available in your plan"**, whatever ids the path carries.
#
#     The UI consequence follows from that 403, and it does *not* end in this
#     screen's own PageError ("Failed to load syllabus data"). The axios response
#     interceptor in src/utils/handleErrorMessage.ts recognises that particular
#     detail (``shouldRedirectToNoAccess``) and performs a hard
#     ``window.location`` redirect to **/auth/no-access**, rejecting the promise
#     with ``FeatureNotAvailableError`` before page.tsx's own ``catch`` can put
#     anything into ``fetchError``. So the landing page, not the error panel, is
#     the denial surface here.
#
# One honesty note about what the UI half can and cannot prove
#     ``minimal`` switches off ``classes_and_timetables`` and ``subjects`` as well
#     as ``syllabi`` — it switches off nearly everything, which is the point of
#     that scenario — and ``loadFilterData`` fetches classes and subjects in the
#     same mount tick as ``fetchSyllabi``. Whichever 403 lands first is the one
#     that fires the redirect, so the UI assertions prove "this SchoolAdmin never
#     reaches a syllabus workspace", not "it was the *syllabi* licence that
#     stopped them". The syllabi-specific gate is proved at the API level
#     instead, route by route, which is why that half comes first and is
#     exhaustive.
#
#     Deliberately *not* asserted: that the sidebar hides "Syllabus". That entry
#     carries both ``permission: "syllabi"`` and ``module: "syllabi"``
#     (SideNavigation/nav-config.tsx), and for a SchoolAdmin the permission check
#     takes priority — so its presence or absence says nothing about this
#     school's feature pack, and asserting on it would be asserting the wrong
#     gate.

DENIED_SCENARIO = "minimal"

# The role whose permissions are checked against the pack in the negative path.
DENIED_ROLE = "SchoolAdmin"

# The three routes the module owns (tests/pages/academics/syllabi.py): the
# register, the create form, and an edit form reached by id.
SYLLABI_LIST_ROUTE = "syllabus"
SYLLABI_ADD_ROUTE = "syllabus/add"
SYLLABI_EDIT_ROUTE = "syllabus/edit/1"

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

# The workspace's own chrome, none of which may reach this admin
# (src/app/module/syllabus/page.tsx and .../add/page.tsx).
DENIED_PAGE_HEADING = re.compile(r"^\s*Syllabus Management\s*$", re.I)
DENIED_CREATE_BUTTON = re.compile(r"^\s*Create Syllabus\s*$", re.I)
DENIED_SEARCH_FIELD = re.compile(r"Search syllabus", re.I)
DENIED_ADD_HEADING = re.compile(r"^\s*Create New Syllabus\s*$", re.I)
DENIED_EDIT_HEADING = re.compile(r"^\s*Edit Syllabus\s*$", re.I)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_SCENARIO)
def test_syllabi_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `syllabi` off the pack, a SchoolAdmin gets no register and no data."""
    ctx = provisioned_school
    if SYLLABI_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {SYLLABI_MODULE!r}; "
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
    assert SYLLABI_MODULE in role_modules, (
        f"the seeded {DENIED_ROLE} role no longer holds a {SYLLABI_MODULE!r} "
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
        f"{SYLLABI_MODULE!r} proves nothing about the gate. Provisioning phase A "
        f"assigns one — check that it did."
    )
    assert SYLLABI_MODULE not in (body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {SYLLABI_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every /syllabi route is refused ─────────────────
    #
    # Every route in api/routes/syllabus.py is covered, reads and writes alike, so
    # the gate cannot regress into being merely read-only or merely cosmetic. The
    # ids are deliberately arbitrary: has_permission is a route-level dependency,
    # solved before the path/body params are validated and long before any row is
    # looked up, so a 404 here would itself be the failure.
    branch_id = (
        int(ctx.branches[0]["id"]) if ctx.branches and ctx.branches[0].get("id") else 0
    )
    branch_query = f"?branch_id={branch_id}" if branch_id else ""
    school_branch_query = f"?school_branch_id={branch_id}" if branch_id else ""

    refusals: dict[str, Any] = {
        # What the register calls on mount…
        "list": api.get(
            f"/syllabi/?skip=0&limit=10"
            f"{f'&branch_id={branch_id}' if branch_id else ''}",
            token=token,
        ),
        # …the row's View details, and the topic list inside it.
        "detail": api.get(f"/syllabi/1{branch_query}", token=token),
        "topics": api.get(f"/syllabi/1/topics{branch_query}", token=token),
        # The row menu's Download PDF.
        "pdf": api.get(f"/syllabi/1/pdf{branch_query}", token=token),
        # And the write half, so the gate is not merely read-only.
        "create": api.post(
            f"/syllabi/{branch_query}",
            token=token,
            json={
                "name": f"TEST Unlicensed Syllabus {run_tag()}",
                "description": "Must never be created — the pack excludes syllabi.",
                "class_id": 1,
                "subject_id": 1,
                "academic_year_id": 1,
                "academic_term_id": 1,
            },
        ),
        "update": api.put(
            f"/syllabi/1{school_branch_query}",
            token=token,
            json={"name": f"TEST Unlicensed Rename {run_tag()}"},
        ),
        "publish": api.post(f"/syllabi/1/publish{school_branch_query}", token=token),
        "delete": api.delete(f"/syllabi/1{school_branch_query}", token=token),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{SYLLABI_MODULE!r}, so the backend must refuse with 403 — "
            f"got {res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIAL_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts a syllabus workspace in front of them ───────
    login_as(page, frontend_base_url, ctx.school_admin)

    # (a) The register. A SchoolAdmin is exempt from both frontend guards, so the
    # route really does mount and really does ask for the list — which is refused,
    # and the axios interceptor turns that answer into a hard redirect long before
    # PageError could render (see the section comment above). Waiting for the URL
    # is therefore also what stops the "register is absent" assertions below from
    # passing merely because the page had not finished loading.
    goto_module(page, frontend_base_url, SYLLABI_LIST_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(page.get_by_text(as_pattern(ACTIVATION_REQUIRED))).to_be_visible()

    # Nothing of the register came with them.
    expect(
        page.get_by_role("heading", name=as_pattern(DENIED_PAGE_HEADING))
    ).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(DENIED_CREATE_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(DENIED_SEARCH_FIELD))).to_have_count(0)
    expect(page.get_by_role("row")).to_have_count(0)

    # (b) Typing the create form's URL by hand is no way round it either…
    goto_module(page, frontend_base_url, SYLLABI_ADD_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(
        page.get_by_role("heading", name=as_pattern(DENIED_ADD_HEADING))
    ).to_have_count(0)

    # (c) …nor is guessing an edit route's id.
    goto_module(page, frontend_base_url, SYLLABI_EDIT_ROUTE)
    page.wait_for_url(NO_ACCESS_URL, timeout=25_000)
    expect(page.get_by_text(as_pattern(ACCESS_RESTRICTED))).to_be_visible(timeout=15_000)
    expect(
        page.get_by_role("heading", name=as_pattern(DENIED_EDIT_HEADING))
    ).to_have_count(0)


# ───────────────────── setup-only API helpers (never asserted) ───────────────


def _login(api: BackendAPI, email: str, password: str) -> str:
    try:
        return str(api.login(email, password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise SyllabusSeedError(f"could not log in as {email}: {exc}") from exc


def _json(response) -> Any:
    if response.status_code >= 400:
        raise SyllabusSeedError(
            f"{response.request.method} {response.request.url.path} → "
            f"{response.status_code}: {response.text[:300]}"
        )
    return response.json()


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Some list endpoints answer a bare list, others a paginated envelope."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _find_id(rows: list[dict[str, Any]], name: str, *, what: str) -> int:
    for row in rows:
        if str(row.get("name", "")).strip().casefold() == name.casefold():
            return int(row["id"])
    raise SyllabusSeedError(
        f"no {what} named {name!r} in this branch — provisioning should have "
        f"created it; got {[r.get('name') for r in rows]}"
    )


def _ensure_subject(api: BackendAPI, token: str, *, branch_id: int) -> int:
    """The syllabus's own subject, created once per school."""
    listed = _rows(
        _json(api.get(f"/subjects/?branch_id={branch_id}&limit=100", token=token))
    )
    for row in listed:
        if str(row.get("name", "")).strip().casefold() == SUBJECT_NAME.casefold():
            return int(row["id"])

    created = api.post(
        f"/subjects/?branch_id={branch_id}",
        token=token,
        json={
            "name": SUBJECT_NAME,
            "description": "Seeded so the syllabus walkthrough owns its own subject.",
        },
    )
    if created.status_code >= 400:
        raise SyllabusSeedError(
            f"could not seed the subject: {created.status_code} {created.text[:300]}"
        )
    return int(created.json()["id"])


def _attach_subject_to_class(
    api: BackendAPI, token: str, *, class_id: int, subject_id: int
) -> None:
    """Put the subject on the class's curriculum.

    ``PUT /classes/{id}`` *replaces* ``subjects`` wholesale
    (``ClassService.update_class``), so the class's existing subjects are read
    back and resubmitted — dropping "Mathematics" here would break the lessons
    and assessments units, which share this session's school.
    """
    current = _json(api.get(f"/classes/{class_id}", token=token))
    subject_ids = {int(s["id"]) for s in _rows(current.get("subjects") or [])}
    if subject_id in subject_ids:
        return

    updated = api.put(
        f"/classes/{class_id}",
        token=token,
        json={"subject_ids": sorted(subject_ids | {subject_id})},
    )
    if updated.status_code >= 400:
        raise SyllabusSeedError(
            f"could not add subject {subject_id} to class {class_id}: "
            f"{updated.status_code} {updated.text[:300]}"
        )


def _teacher_profile_id(
    api: BackendAPI, token: str, *, branch_id: int, email: str
) -> int:
    payload = _json(api.get(f"/teacher/?branch_id={branch_id}&limit=100", token=token))
    for row in _rows(payload):
        user = row.get("user") or {}
        if str(user.get("email", "")).casefold() == email.casefold():
            return int(row["id"])
    raise SyllabusSeedError(
        f"no teacher profile for {email!r} in branch {branch_id} — "
        "the syllabus flow needs the provisioned teacher."
    )


def _assign_subject_teacher(
    api: BackendAPI, token: str, *, teacher_profile_id: int,
    subject_id: int, class_id: int,
) -> None:
    """Make the teacher the *subject* teacher of (subject, class).

    Idempotent server-side: duplicate triples are skipped. Without it every
    write answers 403 "Only the subject teacher can manage this syllabus" —
    being the class teacher grants reads only.
    """
    response = api.post(
        f"/teacher/{teacher_profile_id}/subject-assignments",
        token=token,
        json={"assignments": [{"subject_id": subject_id, "class_id": class_id}]},
    )
    if response.status_code >= 400:
        raise SyllabusSeedError(
            "could not make the teacher the subject teacher of "
            f"(subject {subject_id}, class {class_id}): "
            f"{response.status_code} {response.text[:300]}"
        )


def _ensure_topics(
    api: BackendAPI, token: str, *, branch_id: int, subject_id: int
) -> None:
    """The topics the syllabus sequences. Names are unique per subject."""
    existing = {
        str(row.get("name", "")).strip().casefold()
        for row in _rows(
            _json(
                api.get(
                    f"/topics/?branch_id={branch_id}&subject_id={subject_id}&limit=100",
                    token=token,
                )
            )
        )
    }
    for index, name in enumerate(SEEDED_TOPICS):
        if name.casefold() in existing:
            continue
        created = api.post(
            f"/topics/?branch_id={branch_id}",
            token=token,
            json={
                "name": name,
                "description": "Seeded so the syllabus has something to sequence.",
                "subject_id": subject_id,
                "order_index": index,
            },
        )
        if created.status_code >= 400:
            raise SyllabusSeedError(
                f"could not seed the topic {name!r}: "
                f"{created.status_code} {created.text[:300]}"
            )
