"""People → Students — the student register, and what a parent is shown instead.

Where this module lives
    ``/module/students`` (``smsfrontend/src/app/module/students/page.tsx``) — the
    "Manage Students" workspace: a ModuleHeader stat strip over
    ``GET /statistics/student``, a paginated register over ``GET /student/``, and
    the four-step admission wizard at ``/module/students/admit-student``.

This file is written one ledger unit at a time, so every section below owns its
own constants (prefixed, never shared). Appending the next unit must never
silently rebind a name an earlier section relies on.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import unquote

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.credentials import CredentialCaptureError, capture_credentials
from tests.fixtures.data_factories import TEST_PREFIX, make_person, run_tag
from tests.flows.school_provisioning import Credentials, SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.people.guardian_home import GuardianHomePage
from tests.pages.school_admin.branches import BranchesPage
from tests.pages.people.students import (
    ADMIT_TRIGGER,
    MANAGE_CONTROLS,
    NOT_PROVIDED,
    PAGE_HEADING,
    STAT_FEMALE,
    STAT_MALE,
    STAT_TOTAL,
    STUDENTS_PANEL,
    StudentsPage,
)

# ═════════════════════ people.students.view.guardian ═════════════════════════
#
# What "a Guardian views students" is in this product
#     Not the register. The Guardian role is seeded with exactly six permissions
#     — ``home, messaging, lessons, student_scores, families, reports``
#     (``newschoolapp/db/repository/permissions.py``) — and ``students`` is not
#     one of them, for either "read" or "manage". Every student route is declared
#     ``Depends(has_permission(<read|manage>, "students"))``, the sidebar's
#     "Students" entry carries ``permission: "students"``, and
#     ``/module/students`` calls ``usePermissionGuard("students")``. So a parent
#     reaches no part of the school-wide register.
#
#     What a parent *does* get is the child themselves. ``/module/home`` renders
#     ``ViewsComponents/GuardianView.tsx`` — a "Your Ward(s)" table — and each row
#     links to ``/module/home/[guardianward]``, a read-only student record with
#     Basic Info / Contact / Academic / Reports tabs. Both screens read the same
#     single endpoint, ``GET /guardian/{guardian_id}/wards``, which is gated on
#     ``has_permission("read", "home")`` — the one permission a Guardian holds
#     that returns student rows. That is the ward-scoped read this unit records:
#     a parent sees their own children's records and no one else's.
#
# Why the two halves belong in one test
#     Asserting only the happy path would leave "and nothing wider" unstated,
#     which is the whole point of a ward-scoped read; asserting only the denial
#     would claim the product shows a parent nothing about their child, which is
#     false. The video therefore walks the read first and probes the boundary
#     last.
#
# Why the family has to be seeded here
#     The ``minimal`` pack licenses ``students`` but not ``guardians`` — those and
#     ``families`` are the only optional members of the otherwise locked "people"
#     group (BASIC_GROUPS in
#     ``smsfrontend/src/app/module/feature_flag/{create,edit}/page.tsx``). So
#     provisioning phase C skips guardian creation, and with no guardian to pick
#     in its Contact Details step it skips the admission wizard too:
#     ``ctx.guardian`` and ``ctx.student`` are both ``None`` at this school.
#
#     One parent and one child are therefore seeded over the API as the
#     SuperAdmin — the only role ``has_permission`` exempts from feature-pack
#     enforcement outright. This is setup, never an assertion, and it is the same
#     setup-only use of ``api`` as ``school_provisioning._seed_fee_group`` and as
#     the guardian seeded by ``account.fees.view.guardian``. ``POST /student/``
#     takes ``guardian_id`` directly and ``StudentService.create_student`` both
#     appends the ward and calls ``FamilyService.ensure_family``, so the link the
#     Assign Ward modal would otherwise make is made by the create itself.
#
#     ``UserService.create_user`` honours an explicit ``school_branch_id`` from a
#     SuperAdmin, which is what puts both of them inside this school — without it
#     they resolve to no school at all and every refusal below would read "User is
#     not associated with a school", which would prove nothing about students.
#
# Why the HTTP half runs in the fixture
#     The fixture is requested *before* ``demo`` in the test signature, so the
#     seeding and the API probes happen before the camera rolls rather than as
#     dead frames at the head of the video. The fixture only collects; the test
#     body does every assertion, so a real regression is reported as a failure and
#     not as a fixture error.
#
# Deliberately *not* asserted: ``GET /statistics/student``
#     The stat strip's endpoint carries no ``has_permission`` dependency at all —
#     ``api/routes/statistics.py`` has it commented out — so a Guardian's token is
#     answered there. Adding that gate would be enforcing a check the product does
#     not enforce today, which is a behaviour change and not this test's call. It
#     is recorded here so the next reader does not mistake the silence for an
#     oversight. Nothing on ``/module/students`` renders for a parent anyway: the
#     permission guard returns before the strip is drawn.
#
# Deliberately *not* asserted: that ``GET /student/{ward_id}`` should succeed
#     It does not — the route is gated on ``students`` like every other one, so a
#     parent is refused even their own child's row *through that path*. That is
#     not a defect: the ward-scoped read the product implements is
#     ``/guardian/{id}/wards``, and it answers with exactly the same
#     ``StudentProfileResponse`` payload. The refusal is pinned below as behaviour.

GUARDIAN_VIEW_SCENARIO = "minimal"
GUARDIAN_VIEW_MODULE = "students"
GUARDIAN_VIEW_ROUTE = "students"
GUARDIAN_VIEW_ROLE = "Guardian"

# The seeded parent. Every name is written by the API here, not typed into a
# wizard, so no input filter applies — but the addresses still come from
# make_person/unique_email, which carry the run tag and TEST_EMAIL_DOMAIN (the
# backend answers 422 for reserved TLDs).
GUARDIAN_VIEW_PARENT_DOB = "1987-03-09"
GUARDIAN_VIEW_PARENT_GENDER = "Female"
GUARDIAN_VIEW_OCCUPATION = "TEST Parent"
GUARDIAN_VIEW_RELATIONSHIP = "Mother"

# …and the child, whose record is what the parent reads. These values are what
# every assertion on the ward profile compares against.
GUARDIAN_VIEW_WARD_GENDER = "Male"
GUARDIAN_VIEW_WARD_DOB = "2014-05-12"
GUARDIAN_VIEW_WARD_ADMITTED = "2026-09-01"
GUARDIAN_VIEW_WARD_BLOOD_TYPE = "O+"
GUARDIAN_VIEW_WARD_LOCATION = "Accra"
GUARDIAN_VIEW_WARD_PREVIOUS_SCHOOL = f"{TEST_PREFIX} Riverbank Primary"

# GuardianView.tsx — the parent's landing screen.
GUARDIAN_VIEW_WARDS_HEADING = re.compile(r"Your Ward", re.I)
GUARDIAN_VIEW_ROW_ACTION = re.compile(r"^\s*View\s*$", re.I)

# home/[guardianward]/page.tsx — the ward's own record.
GUARDIAN_VIEW_WARD_URL = re.compile(r"/module/home/\d+")
GUARDIAN_VIEW_STUDENT_BADGE = re.compile(r"^\s*Student\s*$", re.I)
GUARDIAN_VIEW_NOT_FOUND = re.compile(r"^\s*Ward not found\s*$", re.I)
GUARDIAN_VIEW_LOAD_FAILURE = re.compile(r"Failed to load ward details", re.I)
GUARDIAN_VIEW_TAB_BASIC = re.compile(r"^\s*Basic Info\s*$", re.I)
GUARDIAN_VIEW_TAB_CONTACT = re.compile(r"^\s*Contact\s*$", re.I)
GUARDIAN_VIEW_TAB_ACADEMIC = re.compile(r"^\s*Academic\s*$", re.I)
# Its InfoField captions, anchored: "Phone" must not resolve to "Secondary
# Phone", and "Email" must not resolve to anything the header card renders.
GUARDIAN_VIEW_FIELD_FIRST_NAME = re.compile(r"^\s*First Name\s*$", re.I)
GUARDIAN_VIEW_FIELD_OTHER_NAMES = as_pattern(r"^\s*Other Name\(s\)\s*$")
GUARDIAN_VIEW_FIELD_GENDER = re.compile(r"^\s*Gender\s*$", re.I)
GUARDIAN_VIEW_FIELD_STUDENT_ID = re.compile(r"^\s*Student ID\s*$", re.I)
GUARDIAN_VIEW_FIELD_DOB = re.compile(r"^\s*Date of Birth\s*$", re.I)
GUARDIAN_VIEW_FIELD_BLOOD_TYPE = re.compile(r"^\s*Blood Type\s*$", re.I)
GUARDIAN_VIEW_FIELD_NATIONALITY = re.compile(r"^\s*Nationality\s*$", re.I)
GUARDIAN_VIEW_FIELD_EMAIL = re.compile(r"^\s*Email\s*$", re.I)
GUARDIAN_VIEW_FIELD_PHONE = re.compile(r"^\s*Phone\s*$", re.I)
GUARDIAN_VIEW_FIELD_ADDRESS = re.compile(r"^\s*Residential Address\s*$", re.I)
GUARDIAN_VIEW_FIELD_LOCATION = re.compile(r"^\s*Location\s*$", re.I)
GUARDIAN_VIEW_FIELD_CLASS = re.compile(r"^\s*Current Class\s*$", re.I)
GUARDIAN_VIEW_FIELD_ADMITTED = re.compile(r"^\s*Date of Admission\s*$", re.I)
GUARDIAN_VIEW_FIELD_PREVIOUS_SCHOOL = re.compile(r"^\s*Previous School\s*$", re.I)
# What InfoField prints for a value the record does not carry.
GUARDIAN_VIEW_NOT_PROVIDED = "Not Provided"

# Sidebar (SideNavigation/nav-config.tsx). "Home" is the non-vacuous anchor: it
# is the one People-Module entry a Guardian's permissions earn, so finding it
# proves the menu rendered before "Students" is declared missing.
GUARDIAN_VIEW_NAV_HOME = re.compile(r"^\s*Home\s*$", re.I)
GUARDIAN_VIEW_NAV_STUDENTS = re.compile(r"^\s*Students\s*$", re.I)

# The register's own chrome (module/students/page.tsx). None of it may appear.
GUARDIAN_VIEW_REGISTER_HEADING = re.compile(r"^\s*Manage Students\s*$", re.I)
GUARDIAN_VIEW_REGISTER_SUBHEADING = re.compile(
    r"Easily update student information to ensure data accuracy", re.I
)
GUARDIAN_VIEW_REGISTER_TOTAL = re.compile(r"^\s*Total Students\s*$", re.I)
GUARDIAN_VIEW_REGISTER_ADMIT = re.compile(r"^\s*Admit Student\s*$", re.I)

# Where usePermissionGuard sends a role that lacks the permission, and the copy
# that page carries (src/app/unauthorized/page.tsx).
GUARDIAN_VIEW_UNAUTHORIZED_URL = re.compile(r"/unauthorized")
GUARDIAN_VIEW_ACCESS_DENIED = re.compile(r"^\s*Access Denied\s*$", re.I)
GUARDIAN_VIEW_UNAUTHORIZED_ACCESS = re.compile(r"^\s*Unauthorized Access\s*$", re.I)

# The two denials utils/permissions.has_permission can answer with. The role half
# runs first and short-circuits, so a Guardian never reaches the pack half — which
# matters here, because this school *is* licensed for students.
GUARDIAN_VIEW_ROLE_DENIAL = re.compile(
    r"You do not have permission to perform this action", re.I
)
GUARDIAN_VIEW_PLAN_DENIAL = re.compile(r"Feature not available in your plan", re.I)

GUARDIAN_VIEW_DENIAL_TIMEOUT_S = 30.0


class GuardianViewSeedError(RuntimeError):
    """A prerequisite for this unit could not be seeded."""


@dataclass
class GuardianStudentView:
    """The seeded family, plus what the API already answered as the parent.

    ``wards`` is the ward-scoped read the parent's screens make; ``refusals``
    maps a label to the ``(status, detail)`` their token got from the register's
    own routes. Both are collected here and asserted in the test body, so a
    regression is a failure rather than a fixture error.
    """

    guardian: Credentials
    guardian_id: int
    ward_id: int
    ward_student_id: str
    ward_first_name: str
    ward_other_names: str
    ward_email: str
    ward_phone: str
    ward_address: str
    ward_nationality: str
    branch_id: int
    licensed_modules: list[str] = field(default_factory=list)
    role_modules: set[str] = field(default_factory=set)
    wards: tuple[int, Any] = (0, None)
    refusals: dict[str, tuple[int, str]] = field(default_factory=dict)

    @property
    def ward_full_name(self) -> str:
        return f"{self.ward_first_name} {self.ward_other_names}".strip()


@pytest.fixture
def guardian_student_view(
    provisioned_school: SchoolContext, api: BackendAPI, superadmin: Any
) -> GuardianStudentView:
    """Seed a parent and their child at the minimal school, then ask as the parent."""
    ctx = provisioned_school
    super_token = _guardian_view_super_token(api, superadmin)
    branch_id = _guardian_view_branch_id(api, super_token, ctx)

    parent = make_person(
        "students-guardian", ctx.school_id, gender=GUARDIAN_VIEW_PARENT_GENDER
    )
    guardian, guardian_id = _guardian_view_seed_guardian(
        api,
        super_token,
        person=parent,
        branch_id=branch_id,
        role_id=api.role_id_for(GUARDIAN_VIEW_ROLE),
    )

    child = make_person(
        "students-ward", ctx.school_id, gender=GUARDIAN_VIEW_WARD_GENDER
    )
    ward = _guardian_view_seed_student(
        api, super_token, person=child, branch_id=branch_id, guardian_id=guardian_id
    )

    access = GuardianStudentView(
        guardian=guardian,
        guardian_id=guardian_id,
        ward_id=int(ward["id"]),
        ward_student_id=str(ward.get("student_id") or ""),
        ward_first_name=child.first_name,
        ward_other_names=child.last_name,
        ward_email=child.email,
        ward_phone=child.phone,
        ward_address=child.address,
        ward_nationality=child.nationality,
        branch_id=branch_id,
    )

    # What the school is licensed for, read as the SchoolAdmin. The point of this
    # unit is that students IS licensed here, so nothing below can be blamed on
    # the pack.
    admin_token = api.login(
        ctx.school_admin.email, ctx.school_admin.password
    )["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=admin_token)
    if features.status_code != 200:
        raise GuardianViewSeedError(
            f"could not read {ctx.school_name!r}'s features: "
            f"{features.status_code} {features.text[:300]}"
        )
    body = features.json()
    if body.get("pack_assigned") is not True:
        raise GuardianViewSeedError(
            f"{ctx.school_name!r} has no feature pack assigned, so this unit could "
            f"not tell a role denial from a licence one. Provisioning phase A "
            f"assigns one — check that it did."
        )
    access.licensed_modules = list(body.get("modules") or [])

    # What the Guardian role itself holds, read back rather than assumed.
    role = api.get(f"/roles/{api.role_id_for(GUARDIAN_VIEW_ROLE)}")
    if role.status_code != 200:
        raise GuardianViewSeedError(
            f"could not read the {GUARDIAN_VIEW_ROLE} role: "
            f"{role.status_code} {role.text[:300]}"
        )
    access.role_modules = {
        str(p.get("module")) for p in (role.json().get("permissions") or [])
    }

    # Now ask as the parent: the one read their screens make, and the register's
    # own routes they must not reach. The list is asked with the branch named so
    # a refusal cannot be blamed on a missing scope parameter.
    guardian_token = api.login(guardian.email, guardian.password)["access_token"]
    wards = api.get(f"/guardian/{guardian_id}/wards", token=guardian_token)
    access.wards = (wards.status_code, _guardian_view_json(wards))
    for label, path in (
        ("register", f"/student/?skip=0&limit=10&branch_id={branch_id}"),
        ("register_unscoped", "/student/"),
        ("own_ward_through_register", f"/student/{access.ward_id}"),
    ):
        response = api.get(path, token=guardian_token)
        access.refusals[label] = (response.status_code, _guardian_view_detail(response))

    return access


@pytest.mark.guardian
@pytest.mark.scenario(GUARDIAN_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="people.students.view.guardian",
    title="Students",
    subtitle="Guardian views students",
)
def test_guardian_views_only_their_own_wards_student_record(
    guardian_student_view: GuardianStudentView,
    demo,
    provisioned_school: SchoolContext,
) -> None:
    """A parent reads their child's student record — and nothing wider.

    The school is licensed for ``students``, so every refusal below is about who
    the user is rather than what the school bought; and the record the parent
    *does* read is asserted field by field against what was admitted, so a screen
    that renders a shell of empty "Not Provided" boxes fails instead of passing
    quietly.
    """
    ctx = provisioned_school
    access = guardian_student_view
    guardian = access.guardian
    ward_name = access.ward_full_name

    # ── 1. The licence is not what limits them ───────────────────────────────
    assert GUARDIAN_VIEW_MODULE in access.licensed_modules, (
        f"{ctx.school_name!r} is not licensed for {GUARDIAN_VIEW_MODULE!r} "
        f"(pack modules: {sorted(access.licensed_modules)}), so the refusals "
        f"below would say nothing about the {GUARDIAN_VIEW_ROLE} role. The "
        f"{ctx.scenario_id!r} pack locks the 'people' group in, so students is "
        f"always on — check provisioning phase A assigned the pack at all."
    )

    # ── 2. …their role is ────────────────────────────────────────────────────
    #
    # Read back rather than hard-coded: if anyone ever grants the Guardian role
    # `students`, this unit must fail loudly rather than keep asserting a denial
    # the product no longer makes. GET /student/ is branch-scoped, not
    # ward-scoped, so that grant would hand every parent the whole campus roll.
    assert GUARDIAN_VIEW_MODULE not in access.role_modules, (
        f"the seeded {GUARDIAN_VIEW_ROLE} role now holds "
        f"{GUARDIAN_VIEW_MODULE!r} ({sorted(access.role_modules)}). "
        f"list_all_students filters on the branch and not on the caller's wards, "
        f"so this grant exposes every child at the campus to every parent."
    )

    # ── 3. The ward-scoped read the product does implement ───────────────────
    wards_status, wards_body = access.wards
    assert wards_status == 200, (
        f"GET /guardian/{access.guardian_id}/wards answered {wards_status} for the "
        f"parent themselves. It is gated on has_permission('read', 'home') — the "
        f"one permission a {GUARDIAN_VIEW_ROLE} holds that returns student rows — "
        f"and both /module/home and the ward profile render from it, so a refusal "
        f"here leaves a parent with no way to see their own child. Body: "
        f"{str(wards_body)[:300]}"
    )
    assert isinstance(wards_body, list), (
        f"the wards read must answer a list of students; got {type(wards_body).__name__}"
    )
    ward_ids = {row.get("id") for row in wards_body if isinstance(row, dict)}
    assert ward_ids == {access.ward_id}, (
        f"the parent's wards are {sorted(str(i) for i in ward_ids)}, expected "
        f"exactly the one child seeded for them ({access.ward_id}). More than one "
        f"would mean the read is not scoped to this family at all."
    )

    # ── 4. …and the register's own routes are refused ────────────────────────
    for label, (status, detail) in access.refusals.items():
        assert status == 403, (
            f"{label}: a {GUARDIAN_VIEW_ROLE} at {ctx.school_name!r} must be "
            f"refused the student register — got {status}: {detail[:300]}"
        )
        assert GUARDIAN_VIEW_ROLE_DENIAL.search(detail), (
            f"{label}: 403 is right, but not for the reason this school implies. "
            f"The pack licenses {GUARDIAN_VIEW_MODULE!r}, so the refusal must come "
            f"from the role half of has_permission, matching "
            f"{GUARDIAN_VIEW_ROLE_DENIAL.pattern!r} — got {detail!r}. A "
            f"{GUARDIAN_VIEW_PLAN_DENIAL.pattern!r} here would mean the licence "
            f"lapsed rather than the role being refused."
        )

    # ── 5. …which is exactly the story the browser tells ─────────────────────
    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    home = GuardianHomePage(page, base_url)

    with demo.step(f"Sign in as {guardian.full_name}, a parent at {ctx.school_name}"):
        login_as(page, base_url, guardian)

    with demo.step("A parent's menu offers Home — and no student register"):
        expect(
            page.get_by_role("link", name=as_pattern(GUARDIAN_VIEW_NAV_HOME)).first
        ).to_be_visible(timeout=30_000)
        expect(
            page.get_by_role("link", name=as_pattern(GUARDIAN_VIEW_NAV_STUDENTS))
        ).to_have_count(0)

    with demo.step("Their home page lists the children they look after"):
        # Walked to from the menu rather than deep-linked: this is the only entry
        # a parent is offered, and it is how they would actually get here.
        page.get_by_role("link", name=as_pattern(GUARDIAN_VIEW_NAV_HOME)).first.click()
        home.expect_loaded()
        home.expect_ward(ward_name)
        row = home.ward_row(ward_name)
        expect(row).to_contain_text(access.ward_student_id)
        expect(row).to_contain_text(access.ward_email)

    with demo.step(f"Open {ward_name}'s record"):
        row.get_by_role("link", name=as_pattern(GUARDIAN_VIEW_ROW_ACTION)).first.click()
        page.wait_for_url(GUARDIAN_VIEW_WARD_URL, timeout=30_000)
        # Both of these would otherwise let every field assertion below pass
        # against an empty screen.
        expect(page.get_by_text(as_pattern(GUARDIAN_VIEW_NOT_FOUND))).to_have_count(0)
        expect(page.get_by_text(as_pattern(GUARDIAN_VIEW_LOAD_FAILURE))).to_have_count(0)
        expect(
            page.get_by_role("heading", name=as_pattern(re.escape(ward_name))).first
        ).to_be_visible(timeout=30_000)
        expect(
            page.get_by_text(as_pattern(GUARDIAN_VIEW_STUDENT_BADGE)).first
        ).to_be_visible()

    with demo.step("Who the child is: the details the school admitted them with"):
        _guardian_view_open_tab(page, GUARDIAN_VIEW_TAB_BASIC)
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_FIRST_NAME)).to_have_text(
            access.ward_first_name
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_OTHER_NAMES)).to_have_text(
            access.ward_other_names
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_GENDER)).to_have_text(
            GUARDIAN_VIEW_WARD_GENDER
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_STUDENT_ID)).to_have_text(
            access.ward_student_id
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_DOB)).to_have_text(
            _guardian_view_uk_date(GUARDIAN_VIEW_WARD_DOB)
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_BLOOD_TYPE)).to_have_text(
            GUARDIAN_VIEW_WARD_BLOOD_TYPE
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_NATIONALITY)).to_have_text(
            access.ward_nationality
        )

    with demo.step("How to reach them"):
        _guardian_view_open_tab(page, GUARDIAN_VIEW_TAB_CONTACT)
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_EMAIL)).to_have_text(
            access.ward_email
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_PHONE)).to_have_text(
            access.ward_phone
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_ADDRESS)).to_have_text(
            access.ward_address
        )
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_LOCATION)).to_have_text(
            GUARDIAN_VIEW_WARD_LOCATION
        )

    with demo.step("…and where they are in school"):
        _guardian_view_open_tab(page, GUARDIAN_VIEW_TAB_ACADEMIC)
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_ADMITTED)).to_have_text(
            _guardian_view_uk_date(GUARDIAN_VIEW_WARD_ADMITTED)
        )
        expect(
            _guardian_view_field(page, GUARDIAN_VIEW_FIELD_PREVIOUS_SCHOOL)
        ).to_have_text(GUARDIAN_VIEW_WARD_PREVIOUS_SCHOOL)
        # This school's pack has no classes module, so nobody has been put in a
        # class — the screen says so rather than rendering an empty box.
        expect(_guardian_view_field(page, GUARDIAN_VIEW_FIELD_CLASS)).to_have_text(
            GUARDIAN_VIEW_NOT_PROVIDED
        )

    with demo.step("The school's own register, though, is not theirs to open"):
        goto_module(page, base_url, GUARDIAN_VIEW_ROUTE)
        surface = _guardian_view_wait_for_denial(page)
        if surface == "unauthorized":
            expect(
                page.get_by_text(as_pattern(GUARDIAN_VIEW_ACCESS_DENIED)).first
            ).to_be_visible(timeout=15_000)
            expect(
                page.get_by_text(as_pattern(GUARDIAN_VIEW_UNAUTHORIZED_ACCESS)).first
            ).to_be_visible(timeout=15_000)

    with demo.step("Not one other child's record reaches a parent", dwell_ms=1500):
        # Invariant under both denial surfaces — the guard has either redirected
        # or is rendering null, and neither may put any of the register on screen.
        for absent in (
            GUARDIAN_VIEW_REGISTER_HEADING,
            GUARDIAN_VIEW_REGISTER_SUBHEADING,
            GUARDIAN_VIEW_REGISTER_TOTAL,
            GUARDIAN_VIEW_REGISTER_ADMIT,
        ):
            expect(page.get_by_text(as_pattern(absent))).to_have_count(0)
        expect(page.locator("table")).to_have_count(0)


def _guardian_view_wait_for_denial(page: Page) -> str:
    """Wait for whichever denial surface /module/students reaches, and name it.

    ``usePermissionGuard("students")`` pushes a Guardian to ``/unauthorized``
    once the persisted role permissions have rehydrated; until they have, the
    page renders ``null``, which is also a denial and the fallback accepted here.
    Only "the register appeared" is a failure, and the caller's assertions catch
    that under either surface.
    """
    deadline = time.monotonic() + GUARDIAN_VIEW_DENIAL_TIMEOUT_S
    while time.monotonic() < deadline:
        if GUARDIAN_VIEW_UNAUTHORIZED_URL.search(page.url):
            return "unauthorized"
        page.wait_for_timeout(250)
    return "blank"


def _guardian_view_open_tab(page: Page, label: re.Pattern[str]) -> None:
    """Switch the ward profile to one of its tabs (they are plain buttons)."""
    page.get_by_role("button", name=as_pattern(label)).first.click()


def _guardian_view_field(page: Page, label: str | re.Pattern[str]) -> Locator:
    """The value InfoField renders under ``label``.

    ``<p>label</p><p>value</p>`` siblings, with the caption upper-cased in CSS
    only — so the DOM text is still the caption as written in the source.
    """
    return page.get_by_text(as_pattern(label)).first.locator(
        "xpath=following-sibling::p[1]"
    )


def _guardian_view_uk_date(iso: str) -> str:
    """What ``toLocaleDateString("en-GB", {day:"2-digit", month:"long", …})`` prints."""
    parsed = datetime.strptime(iso, "%Y-%m-%d").date()
    return f"{parsed.day:02d} {parsed.strftime('%B')} {parsed.year}"


# ─────────── setup-only seeding for this unit (never asserted) ──────────────


def _guardian_view_super_token(api: BackendAPI, superadmin: Any) -> str:
    """The SuperAdmin bearer token — the one role the feature-pack gate exempts."""
    token = getattr(superadmin, "access_token", None)
    if token:
        return str(token)
    email = getattr(superadmin, "email", "")
    password = getattr(superadmin, "password", "")
    try:
        return str(api.login(email, password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise GuardianViewSeedError(
            f"could not log in as the SuperAdmin {email!r}: {exc}"
        ) from exc


def _guardian_view_branch_id(api: BackendAPI, token: str, ctx: SchoolContext) -> int:
    """The campus the seeded family belongs to.

    Provisioning normally captures this from ``POST /branch/``; when that response
    could not be read it stores ``-1``, so fall back to listing the school's
    branches as the SuperAdmin.
    """
    if ctx.branches:
        captured = ctx.branches[0].get("id")
        if isinstance(captured, int) and captured > 0:
            return captured

    response = api.get(f"/branch/?school_id={ctx.school_id}&limit=100", token=token)
    if response.status_code >= 400:
        raise GuardianViewSeedError(
            f"could not list branches of school {ctx.school_id}: "
            f"{response.status_code} {response.text[:300]}"
        )
    rows = [row for row in response.json() if isinstance(row, dict)]
    if not rows:
        raise GuardianViewSeedError(
            f"{ctx.school_name!r} has no branch, so a family cannot be scoped to "
            f"it. Provisioning phase B creates one — check that it did."
        )
    return int(rows[0]["id"])


def _guardian_view_seed_guardian(
    api: BackendAPI,
    token: str,
    *,
    person: Any,
    branch_id: int,
    role_id: int,
) -> tuple[Credentials, int]:
    """Create one parent at ``branch_id`` as the SuperAdmin, with a real login.

    A SchoolAdmin cannot do this here: ``POST /guardian/`` is gated on
    ``has_permission("manage", "guardians")`` and the ``minimal`` pack omits
    ``guardians``, so their request is refused by the pack half. The SuperAdmin is
    exempt from that gate outright.

    The password is server-generated and only ever emailed, so it is read out of
    the backend's QA mode — the same ``X-Test-Mode`` channel
    ``tests.fixtures.credentials`` reads through Playwright, taken off the httpx
    response here because no page is driving this request.
    """
    payload = {
        "occupation": GUARDIAN_VIEW_OCCUPATION,
        "relationship_type": GUARDIAN_VIEW_RELATIONSHIP,
        "additional_remarks": f"Seeded for people.students.view.guardian {run_tag()}",
        "student_ids": [],
        "user": {
            "first_name": person.first_name,
            "other_names": person.last_name,
            "email": person.email,
            "gender": GUARDIAN_VIEW_PARENT_GENDER,
            "date_of_birth": GUARDIAN_VIEW_PARENT_DOB,
            "nationality": person.nationality,
            "residential_address": person.address,
            "location": GUARDIAN_VIEW_WARD_LOCATION,
            "primary_phone": person.phone,
            "school_branch_id": branch_id,
            "role_id": role_id,
            # Overwritten by GuardianService with the generated guardian id before
            # the user is created; sent only because the schema requires it. The
            # real password comes back through QA mode below.
            "password": "seeded-by-qa",
            "password_confirmation": "seeded-by-qa",
            "is_active": True,
        },
    }
    response = api.post("/guardian/", token=token, json=payload)
    if response.status_code >= 400:
        raise GuardianViewSeedError(
            f"could not seed a guardian in branch {branch_id}: "
            f"{response.status_code} {response.text[:400]}"
        )
    body = _guardian_view_json(response)
    guardian_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(guardian_id, int):
        raise GuardianViewSeedError(
            f"POST /guardian/ answered {response.status_code} without a guardian "
            f"id, so their wards cannot be read: {response.text[:300]}"
        )

    credentials = Credentials(
        email=person.email,
        password=_guardian_view_qa_password(response),
        role_name=GUARDIAN_VIEW_ROLE,
        first_name=person.first_name,
        last_name=person.last_name,
        role=GUARDIAN_VIEW_ROLE,
    )
    return credentials, guardian_id


def _guardian_view_seed_student(
    api: BackendAPI,
    token: str,
    *,
    person: Any,
    branch_id: int,
    guardian_id: int,
) -> dict[str, Any]:
    """Admit one child at ``branch_id`` and make them ``guardian_id``'s ward.

    ``guardian_id`` on the create is not a shortcut around the Assign Ward modal
    — it is what the admission wizard itself sends. ``StudentService`` appends the
    student to the guardian and calls ``FamilyService.ensure_family``, so the
    family the parent's home screen reads exists as soon as this returns.

    No ``class_id``: the ``minimal`` pack has no ``classes_and_timetables``, so no
    class exists at this school to enrol into.
    """
    payload = {
        "date_of_admission": GUARDIAN_VIEW_WARD_ADMITTED,
        "previous_school": GUARDIAN_VIEW_WARD_PREVIOUS_SCHOOL,
        "blood_type": GUARDIAN_VIEW_WARD_BLOOD_TYPE,
        "guardian_id": guardian_id,
        "relationship_type": GUARDIAN_VIEW_RELATIONSHIP,
        # Not optional in practice, and omitting it is what the wizard never
        # does. ``StudentProfileCreate`` declares ``fees_breakdown:
        # list[StudentFeeItem] = Field(None)`` (api/api_models/student.py) — a
        # None default against a non-Optional list, so leaving the key out is a
        # 422 "Input should be a valid list". admit-student/page.tsx initialises
        # it to [] and always posts it; this seed sends the same empty list, so
        # it stays a faithful copy of the wizard's own body. The minimal pack has
        # no `fees` module anyway, so there is no fee to break down.
        "fees_breakdown": [],
        "user": {
            "first_name": person.first_name,
            "other_names": person.last_name,
            "email": person.email,
            "gender": GUARDIAN_VIEW_WARD_GENDER,
            "date_of_birth": GUARDIAN_VIEW_WARD_DOB,
            "nationality": person.nationality,
            "residential_address": person.address,
            "location": GUARDIAN_VIEW_WARD_LOCATION,
            "primary_phone": person.phone,
            "school_branch_id": branch_id,
            # Both are replaced by StudentService with the generated student id
            # (which is also the student's own initial password); the schema
            # requires them to be present.
            "role_id": 0,
            "password": "seeded-by-qa",
            "password_confirmation": "seeded-by-qa",
            "is_active": True,
        },
    }
    response = api.post("/student/", token=token, json=payload)
    if response.status_code >= 400:
        raise GuardianViewSeedError(
            f"could not seed a student in branch {branch_id}: "
            f"{response.status_code} {response.text[:400]}"
        )
    body = _guardian_view_json(response)
    if not isinstance(body, dict) or not isinstance(body.get("id"), int):
        raise GuardianViewSeedError(
            f"POST /student/ answered {response.status_code} without a student "
            f"record: {response.text[:300]}"
        )
    if not body.get("student_id"):
        raise GuardianViewSeedError(
            f"the seeded student carries no student_id, which the ward profile "
            f"and the wards table both print: {response.text[:300]}"
        )
    return body


def _guardian_view_json(response: Any) -> Any:
    """The parsed body, or ``None`` when there is not one."""
    try:
        return response.json()
    except Exception:  # noqa: BLE001 — non-JSON bodies are reported by the caller
        return None


def _guardian_view_detail(response: Any) -> str:
    """The FastAPI ``detail`` string, or the raw body when there is none."""
    body = _guardian_view_json(response)
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return response.text


def _guardian_view_qa_password(response: Any) -> str:
    """The generated password QA mode attached to this response.

    Mirrors ``tests.fixtures.credentials.read_test_mode`` for an httpx response:
    the header first (it is present on every response, whatever the body shape),
    then the ``test_mode`` key in the body.
    """
    block: dict[str, Any] = {}
    header = response.headers.get("x-test-mode")
    if header:
        try:
            block = json.loads(header)
        except json.JSONDecodeError:
            block = {}
    if not block:
        body = _guardian_view_json(response)
        if isinstance(body, dict) and isinstance(body.get("test_mode"), dict):
            block = body["test_mode"]

    if not block:
        raise CredentialCaptureError(
            f"No test_mode data on {response.status_code} {response.url}.\n"
            f"QA mode is not enabled on the backend. Enable it with:\n"
            f"  touch <backend-repo>/.qa_mode_enabled\n"
            f"(or set QA_MODE=1), then wait for uvicorn --reload to pick it up."
        )

    password = block.get("initial_password")
    if not password:
        raise CredentialCaptureError(
            f"QA mode answered on {response.url} but carried no initial_password: "
            f"{block!r}"
        )
    return str(password)


# ═════════════════════ people.students.view.teacher ══════════════════════════
#
# What a teacher is given, and what they are not
#     The seeded Teacher role holds exactly ``("read", "students")`` and never
#     ``("manage", "students")`` (``newschoolapp/db/repository/permissions.py``).
#     So a teacher is a *reader* of the register, all the way down: nav-config.tsx
#     offers them the "Students" entry (``permission: "students"``),
#     ``usePermissionGuard("students")`` lets them onto /module/students, and
#     ``GET /student/`` — ``Depends(has_permission("read", "students"))`` — answers
#     them, scoped by ``list_all_students`` to their own branch because they are
#     neither SuperAdmin nor SchoolAdmin.
#
#     Every write control on the screen is rendered by ``StudentsTableToolbar``
#     behind ``usePermission("students", (name) => name === "manage")`` — Admit
#     Student, Bulk Admission, Promote Selected, Promote Entire Class — so a
#     teacher is offered none of them, and ``POST /student/`` refuses their token
#     with the role half of ``has_permission``. That the screen and the API draw
#     the same line is the whole of this unit; it adds no gate of its own.
#
# Why two pupils are seeded, and why over the API
#     The ``minimal`` pack does not license ``guardians``, and the admission
#     wizard's Contact Details step cannot be completed without an existing
#     guardian ("Select a guardian" only lists guardians that already exist), so
#     provisioning phase C admits nobody at this school — ``ctx.student`` is
#     ``None``. A register with no rows would turn "a teacher can read the
#     register" into an assertion about an empty table, which is exactly the
#     failure mode a read test must not have.
#
#     Two pupils are therefore admitted over the API as the SchoolAdmin, who holds
#     ``("manage", "students")`` and whose school is licensed for the module. This
#     is setup and never an assertion — the same setup-only use of ``api`` as
#     ``school_provisioning._seed_fee_group`` and as the pupil seeded by
#     ``people.home.view.student``. One is male and one female so the stat strip
#     has something to say, and there are two so the search box can be shown
#     narrowing the register down to one of them.
#
#     Neither is given a class: ``classes_and_timetables`` is off this pack, so no
#     class exists at this school to enrol anyone into, and "Not Provided" in the
#     Class and Fee Group columns is the truthful reading of this school rather
#     than a thin one.
#
# Why the stat strip is compared against the API rather than against a number
#     ``page.tsx`` seeds all three cards with "0" before ``/statistics/student``
#     answers, and renders a ``PageError`` panel *instead of* ModuleHeader when it
#     throws — so "the cards say 0" is equally consistent with a working, empty
#     school and with a call that never came back. The cards are therefore read
#     against what that endpoint answers for this teacher, and the panel is
#     asserted absent.
#
# Deliberately not asserted: the pupil's own record at /module/students/[student]
#     A different screen, with its own tabs and its own mount fetches. This unit
#     is the register — the row's "View" link is asserted to be *offered*, and
#     following it belongs to whichever unit covers that page.

TEACHER_VIEW_SCENARIO = "minimal"
TEACHER_VIEW_MODULE = "students"
TEACHER_VIEW_ROUTE = "students"
TEACHER_VIEW_ROLE = "Teacher"
TEACHER_VIEW_PUPIL_ROLE = "Student"

# The two pupils this unit admits. Written by the API rather than typed into the
# wizard, but the names are still sanitised the way every name input in this app
# sanitises them (/[A-Za-z\s]/) so the row reads back exactly what was sent.
TEACHER_VIEW_PUPIL_DOB = "2014-05-12"
TEACHER_VIEW_PUPIL_ADMITTED = "2026-09-01"
TEACHER_VIEW_PUPIL_BLOOD_TYPE = "O+"
TEACHER_VIEW_PUPIL_LOCATION = "Accra"
TEACHER_VIEW_PUPIL_PREVIOUS_SCHOOL = f"{TEST_PREFIX} Riverbank Primary"
TEACHER_VIEW_MALE = "Male"
TEACHER_VIEW_FEMALE = "Female"

# What StudentsTableRow prints in the Status cell for an active pupil.
TEACHER_VIEW_STATUS_ACTIVE = "Active"
# …and the per-row link into the record, the one action a reader is offered.
TEACHER_VIEW_ROW_ACTION = re.compile(r"^\s*View\s*$", re.I)

# The register's own routes, as the browser calls them. ``list_all_students``
# forces branch_id from the caller for a teacher, so no scope parameter is sent.
TEACHER_VIEW_LIST_PATH = "/student/?skip=0&limit=25"
TEACHER_VIEW_CREATE_PATH = "/student/"
TEACHER_VIEW_STATS_PATH = "/statistics/student"

# The two refusals utils/permissions.has_permission can answer with. The role half
# runs first and short-circuits, which matters here: this school *is* licensed for
# students, so a plan denial would mean something else entirely had gone wrong.
TEACHER_VIEW_ROLE_DENIAL = re.compile(
    r"You do not have permission to perform this action", re.I
)
TEACHER_VIEW_PLAN_DENIAL = re.compile(r"Feature not available in your plan", re.I)

# Where the frontend sends a user it has decided is not allowed in.
TEACHER_VIEW_DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")


class TeacherViewSeedError(RuntimeError):
    """A prerequisite for this unit could not be seeded."""


@dataclass(frozen=True)
class TeacherViewPupil:
    """One admitted pupil, as the register will render them."""

    first_name: str
    last_name: str
    email: str
    gender: str
    student_id: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass(frozen=True)
class TeacherViewRoll:
    """The pupils on this teacher's branch, and the branch they are on."""

    branch_id: int
    male: TeacherViewPupil
    female: TeacherViewPupil


@pytest.fixture
def teacher_view_roll(
    provisioned_school: SchoolContext, api: BackendAPI
) -> TeacherViewRoll:
    """Admit two pupils to the teacher's own branch, over the API.

    Requested *before* ``demo`` in the test signature so this happens before the
    camera rolls — the video is about what a teacher reads, not about how the
    pupils came to exist.
    """
    ctx = provisioned_school
    if ctx.teacher is None:
        raise TeacherViewSeedError(
            f"provisioning created no teacher for {ctx.school_name!r}, so there is "
            f"no branch to admit these pupils into and nobody to read them back. "
            f"The {TEACHER_VIEW_SCENARIO!r} pack licenses `staff`, so phase C "
            f"should have created one."
        )

    # The register a teacher sees is their own branch's, so that is where the
    # pupils have to go. Read off their own login rather than off ctx.branches,
    # which carries -1 when provisioning could not parse POST /branch/.
    profile = api.login(
        ctx.teacher.email, ctx.teacher.password
    ).get("user_profile") or {}
    branch_id = profile.get("school_branch_id")
    if not isinstance(branch_id, int) or branch_id <= 0:
        raise TeacherViewSeedError(
            f"the login response for {ctx.teacher.email!r} carried no "
            f"school_branch_id ({branch_id!r}). list_all_students scopes a "
            f"teacher's register to exactly that branch, so pupils admitted "
            f"anywhere else would be invisible to them."
        )

    admin_token = api.login(
        ctx.school_admin.email, ctx.school_admin.password
    )["access_token"]
    role_id = api.role_id_for(TEACHER_VIEW_PUPIL_ROLE)

    male = _teacher_view_admit(
        api, admin_token, ctx=ctx, branch_id=branch_id, role_id=role_id,
        gender=TEACHER_VIEW_MALE, tag="students-roll-a",
    )
    female = _teacher_view_admit(
        api, admin_token, ctx=ctx, branch_id=branch_id, role_id=role_id,
        gender=TEACHER_VIEW_FEMALE, tag="students-roll-b",
        unlike=(male.full_name,),
    )
    return TeacherViewRoll(branch_id=branch_id, male=male, female=female)


@pytest.mark.teacher
@pytest.mark.scenario(TEACHER_VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="people.students.view.teacher",
    title="Students",
    subtitle="Teacher views students",
)
def test_teacher_reads_the_student_register(
    teacher_view_roll: TeacherViewRoll,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A teacher opens the register, finds a pupil in it, and cannot change it.

    Every claim is made against what the register actually answered for this
    teacher — the rows, the totals and the stat strip are all compared with the
    endpoints the screen itself calls — so a table that rendered from stale state,
    or a strip left at its seeded zeroes, fails instead of passing quietly.
    """
    ctx = provisioned_school
    roll = teacher_view_roll
    assert ctx.teacher is not None  # guaranteed by the fixture; re-stated for mypy
    teacher = ctx.teacher
    target = roll.male
    other = roll.female

    assert TEACHER_VIEW_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {TEACHER_VIEW_MODULE!r} for "
        f"this unit — it is a locked basic module (the pack builder forces the "
        f"whole `people` group into every pack), so if this ever fails the "
        f"builder has changed and this file's premise with it"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    students = StudentsPage(page, base_url)

    # Setup, never an assertion about /users/login: the token every API reading
    # below is taken with, as the teacher themselves.
    teacher_token = api.login(teacher.email, teacher.password)["access_token"]

    with demo.step(
        f"Sign in as {teacher.full_name}, who teaches at {ctx.school_name}",
        dwell_ms=2500,
    ):
        login_as(page, base_url, teacher)

    with demo.step("Students is one of the entries their role earns them", dwell_ms=2000):
        students.expect_nav_entry()
        students.open_from_nav()
        assert not TEACHER_VIEW_DENIAL_URL.search(page.url), (
            f"the teacher of {ctx.school_name!r} was turned away to {page.url!r}. "
            f"The Teacher role holds ('read', {TEACHER_VIEW_MODULE!r}) and this "
            f"school is licensed for it, so a denial here is a regression rather "
            f"than a gate to keep."
        )

    with demo.step("The register opens on their branch's headline numbers", dwell_ms=2500):
        # Read for this teacher, from the same endpoint page.tsx calls — the cards
        # start life as "0" and PageError replaces them outright when the call
        # throws, so a hardcoded expectation here would prove nothing.
        stats = api.get(TEACHER_VIEW_STATS_PATH, token=teacher_token)
        assert stats.status_code == 200, (
            f"GET {TEACHER_VIEW_STATS_PATH} answered {stats.status_code} for a "
            f"teacher; the route carries no has_permission dependency and derives "
            f"the branch from the caller, so the stat strip should be theirs to "
            f"read. Body: {stats.text[:300]}"
        )
        counts = stats.json()
        students.expect_no_load_failure()
        expect(students.stat(STAT_TOTAL)).to_have_text(
            str(int(counts["total_students"])), timeout=25_000
        )
        expect(students.stat(STAT_MALE)).to_have_text(str(int(counts["total_male"])))
        expect(students.stat(STAT_FEMALE)).to_have_text(str(int(counts["total_female"])))
        assert int(counts["total_male"]) >= 1 and int(counts["total_female"]) >= 1, (
            f"the strip counts {counts['total_male']} boys and "
            f"{counts['total_female']} girls on branch {roll.branch_id}, but this "
            f"unit admitted one of each before signing in. Either the admissions "
            f"landed on another branch or get_student_stats stopped counting "
            f"pupils who are not enrolled in a class — this pack has no classes, "
            f"so every pupil here is unassigned."
        )

    with demo.step("Below them, every pupil on the branch's books", dwell_ms=2500):
        listing = api.get(TEACHER_VIEW_LIST_PATH, token=teacher_token)
        assert listing.status_code == 200, (
            f"GET {TEACHER_VIEW_LIST_PATH} answered {listing.status_code} for the "
            f"teacher of {ctx.school_name!r}. The route is "
            f"Depends(has_permission('read', {TEACHER_VIEW_MODULE!r})) and the "
            f"Teacher role holds exactly that, so this is the read the whole unit "
            f"rests on. Body: {listing.text[:300]}"
        )
        total = int(listing.json().get("total_count") or 0)
        expect(
            page.get_by_role("heading", name=as_pattern(STUDENTS_PANEL)).first
        ).to_be_visible(timeout=25_000)
        expect(
            page.get_by_text(_teacher_view_total_badge(total)).first
        ).to_be_visible(timeout=25_000)
        students.expect_column_headers()

    with demo.step(f"{target.full_name} is on the roll, with what the school knows",
                   dwell_ms=3000):
        # "contains" for the name: the cell also carries the initials avatar the
        # table draws for a pupil with no photo.
        expect(students.cell(target.full_name, "name")).to_contain_text(
            target.full_name, timeout=25_000
        )
        expect(students.cell(target.full_name, "gender")).to_have_text(target.gender)
        expect(students.cell(target.full_name, "status")).to_have_text(
            TEACHER_VIEW_STATUS_ACTIVE
        )
        # This pack has no classes module, so there is no class to be in and no
        # fee group to inherit from one. The register says so rather than
        # inventing either.
        expect(students.cell(target.full_name, "class")).to_have_text(NOT_PROVIDED)
        expect(students.cell(target.full_name, "fee_group")).to_have_text(NOT_PROVIDED)

    with demo.step("Searching the register narrows it to one pupil", dwell_ms=3000):
        students.search(target.full_name)
        # Server-side: every keystroke re-issues GET /student/ with `search`, and
        # list_students matches first_name, other_names or the two concatenated.
        expect(_teacher_view_row(page, other.full_name)).to_have_count(0, timeout=25_000)
        expect(students.find_row(target.full_name)).to_be_visible()

    with demo.step("A teacher reads this register; they do not run it", dwell_ms=3000):
        # StudentsTableToolbar renders each of these behind
        # usePermission("students", name === "manage"), which a teacher fails.
        for control in MANAGE_CONTROLS:
            expect(page.get_by_role("button", name=as_pattern(control))).to_have_count(0)
        # …while the one action a reader is offered is still there.
        expect(
            students.cell(target.full_name, "actions").get_by_role(
                "link", name=as_pattern(TEACHER_VIEW_ROW_ACTION)
            ).first
        ).to_be_visible()

        held = _teacher_view_role_permissions(api, TEACHER_VIEW_ROLE)
        assert ("read", TEACHER_VIEW_MODULE) in held, (
            f"the seeded {TEACHER_VIEW_ROLE} role no longer holds "
            f"('read', {TEACHER_VIEW_MODULE!r}), so the register above is being "
            f"read on some other basis than the permission this unit is about"
        )
        assert ("manage", TEACHER_VIEW_MODULE) not in held, (
            f"the seeded {TEACHER_VIEW_ROLE} role now holds "
            f"('manage', {TEACHER_VIEW_MODULE!r}). That is a product decision — "
            f"teachers admitting, promoting and bulk-uploading pupils — and not "
            f"something this test may absorb: the toolbar would offer all four "
            f"write controls and the refusal below would stop being a refusal. "
            f"Re-read newschoolapp/db/repository/permissions.py, then rewrite this "
            f"unit as the manage path it would have become."
        )

    with demo.step("The register itself draws the same line", dwell_ms=2500):
        # An empty body on purpose: the permission dependency is solved before the
        # request body is parsed, so a 403 proves the gate without risking a pupil
        # being created if it ever stopped firing — a 422 here would mean exactly
        # that, and is reported as such.
        refused = api.post(TEACHER_VIEW_CREATE_PATH, token=teacher_token, json={})
        assert refused.status_code == 403, (
            f"POST {TEACHER_VIEW_CREATE_PATH} answered {refused.status_code} for a "
            f"teacher; it is Depends(has_permission('manage', "
            f"{TEACHER_VIEW_MODULE!r})) and the Teacher role holds only 'read'. A "
            f"422 would mean the gate no longer fires and the body was parsed "
            f"instead — i.e. teachers can now admit pupils. Body: "
            f"{refused.text[:300]}"
        )
        detail = _teacher_view_detail(refused)
        assert TEACHER_VIEW_ROLE_DENIAL.search(detail), (
            f"POST {TEACHER_VIEW_CREATE_PATH} was refused, but not by the role: "
            f"{detail!r}. This school is licensed for {TEACHER_VIEW_MODULE!r}, so a "
            f"{TEACHER_VIEW_PLAN_DENIAL.pattern!r} here would mean the licence "
            f"lapsed rather than the teacher being held to reading."
        )
        # …and the reading half still answers them, so the line is drawn between
        # read and write and not around the module.
        again = api.get(TEACHER_VIEW_LIST_PATH, token=teacher_token)
        assert again.status_code == 200, (
            f"the teacher could not re-read the register after being refused the "
            f"write: {again.status_code} {again.text[:300]}"
        )
        assert not TEACHER_VIEW_DENIAL_URL.search(page.url), (
            f"the browser ended this walk on {page.url!r} rather than on the "
            f"register it spent it reading"
        )


# ─────────── setup-only seeding for this unit (never asserted) ──────────────


def _teacher_view_admit(
    api: BackendAPI,
    token: str,
    *,
    ctx: SchoolContext,
    branch_id: int,
    role_id: int,
    gender: str,
    tag: str,
    unlike: tuple[str, ...] = (),
) -> TeacherViewPupil:
    """Admit one pupil to ``branch_id`` as the SchoolAdmin.

    No ``class_id``: the ``minimal`` pack has no ``classes_and_timetables``, so
    there is no class at this school to enrol into.

    ``fees_breakdown`` is sent empty rather than omitted, exactly as
    ``students/admit-student/page.tsx`` posts it. It cannot be left out:
    ``api/routes/student.create_student`` rebuilds the request model with
    ``fees_breakdown=student_data.fees_breakdown``, which turns the model's own
    ``None`` default into an explicit value and fails its ``list[StudentFeeItem]``
    annotation with a 422.
    """
    person = _teacher_view_person(ctx, gender, tag=tag, unlike=unlike)
    response = api.post(
        "/student/",
        token=token,
        json={
            "date_of_admission": TEACHER_VIEW_PUPIL_ADMITTED,
            "previous_school": TEACHER_VIEW_PUPIL_PREVIOUS_SCHOOL,
            "blood_type": TEACHER_VIEW_PUPIL_BLOOD_TYPE,
            "fees_breakdown": [],
            "user": {
                "first_name": person.first_name,
                "other_names": person.last_name,
                "email": person.email,
                "gender": gender,
                "date_of_birth": TEACHER_VIEW_PUPIL_DOB,
                "nationality": person.nationality,
                "residential_address": person.address,
                "location": TEACHER_VIEW_PUPIL_LOCATION,
                "primary_phone": person.phone,
                "school_branch_id": branch_id,
                # Both are replaced by StudentService.create_student with the
                # generated student id (which is also the pupil's own initial
                # password); the schema requires them to be present.
                "password": "seeded-by-qa",
                "password_confirmation": "seeded-by-qa",
                "role_id": role_id,
                "is_active": True,
            },
        },
    )
    if response.status_code != 201:
        raise TeacherViewSeedError(
            f"could not admit a pupil to branch {branch_id} of {ctx.school_name!r}: "
            f"{response.status_code} {response.text[:400]}. POST /student/ is gated "
            f"on ('manage', 'students'), which the {TEACHER_VIEW_SCENARIO!r} pack "
            f"licenses and the seeded SchoolAdmin role holds."
        )
    body = response.json()
    student_id = str(body.get("student_id") or "")
    if not student_id:
        raise TeacherViewSeedError(
            f"the seeded pupil carries no student_id: {response.text[:300]}"
        )
    return TeacherViewPupil(
        first_name=person.first_name,
        last_name=person.last_name,
        email=person.email,
        gender=gender,
        student_id=student_id,
    )


def _teacher_view_person(
    ctx: SchoolContext, gender: str, *, tag: str, unlike: tuple[str, ...] = ()
) -> Any:
    """A faker pupil whose name is already what the app would have stored.

    Names are sanitised the way every name input in this app sanitises them
    (``/[A-Za-z\\s]/``), and regenerated until this pupil cannot be confused with
    one already admitted — the search step asserts that one row survives a search
    and the other does not, which a shared surname would quietly break.
    """
    for _ in range(10):
        person = make_person(tag, ctx.school_id, gender=gender)
        person.first_name = _teacher_view_letters(person.first_name)
        person.last_name = _teacher_view_letters(person.last_name)
        full = person.full_name
        if not person.first_name or not person.last_name:
            continue
        if all(
            full.lower() not in name.lower() and name.lower() not in full.lower()
            for name in unlike
        ):
            return person
    raise TeacherViewSeedError(
        f"could not generate a pupil name distinguishable from {unlike!r}"
    )


def _teacher_view_letters(value: str) -> str:
    return re.sub(r"[^A-Za-z\s]", "", value).strip()


def _teacher_view_row(page: Page, name: str) -> Locator:
    """Every register row carrying ``name`` — used to assert there are none."""
    return page.get_by_role("row").filter(has_text=re.compile(re.escape(name), re.I))


def _teacher_view_total_badge(total: int) -> re.Pattern[str]:
    """StudentsTable's count badge: ``{totalCount} student{s} total``."""
    return re.compile(
        rf"^\s*{total} student{'' if total == 1 else 's'} total\s*$", re.I
    )


def _teacher_view_role_permissions(api: BackendAPI, role_name: str) -> set[tuple[str, str]]:
    """Every ``(permission, module)`` pair the named seeded role holds."""
    role = api.get(f"/roles/{api.role_id_for(role_name)}")
    assert role.status_code == 200, (
        f"could not read the {role_name} role — got {role.status_code}: "
        f"{role.text[:300]}"
    )
    return {
        (str(p.get("name")), str(p.get("module")))
        for p in (role.json().get("permissions") or [])
    }


def _teacher_view_detail(response: Any) -> str:
    """The FastAPI ``detail`` string, or the raw body when there is none."""
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 — non-JSON bodies are reported as-is
        return response.text
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return response.text


# ═════════════════════ people.students.always_licensed ═══════════════════════
#
# (Restored verbatim: this section was written first and then lost when the
# guardian section above was written over the file. Its constants and helpers are
# its own, per this file's convention.)
#
# Mandatory path: the SchoolAdmin of the ``minimal`` school
#     ``test_students_is_reachable_on_the_minimal_pack``. There is no denial unit
#     for this module and there cannot be one: ``students`` sits in the ``people``
#     group of ``services/feature_pack_service.SYSTEM_MODULE_GROUPS``, and the
#     SuperAdmin's only pack builder (``src/app/module/feature_flag/create/
#     page.tsx`` and its ``edit/[id]`` twin) declares
#     ``BASIC_GROUPS = ["people", "governance"]`` and renders every module of
#     those two groups locked, pre-selected and exempt from "Clear All" — only
#     ``guardians`` and ``families`` are optional inside them. That the people and
#     governance groups are core and always on is **intended product behaviour,
#     confirmed 2026-08-09**, not a licensing hole. So this unit asserts the
#     opposite of a denial — the module is licensed, offered and working on the
#     most restricted pack the product can build — and deliberately adds no gate
#     of any kind.
#
# Why a branch has to be picked first
#     The sidebar entry: "Students" lives in the "People Module" section of
#     ``nav-config.tsx``, which is ``branchOnly: true`` — for a SchoolAdmin the
#     whole section is hidden until ``useBranchStore`` holds a branch, and only
#     the branch row's "View" button fills it (``BranchesPage.select_branch``).
#     The data: ``fetchStudents`` appends ``branch_id`` from that same store for a
#     SchoolAdmin, and ``list_all_students`` answers 400 ``BRANCH_ID_REQUIRED``
#     without one, while ``fetchStatsData`` returns early and leaves the three
#     cards reading 0 with no error on screen at all.
#
# Why the register's own fetch is read off the wire
#     The cards render "0" whether ``/statistics/student`` answered or was
#     skipped, and the table renders "No students found" whether ``/student/``
#     answered empty or is still in flight. So the test waits for the browser's
#     own ``GET /student/?…`` to come back 200 — the route declared
#     ``Depends(has_permission("read", "students"))`` — and re-reads it directly.
#
# Deliberately not asserted: any student row, or the admission wizard itself
#     The ``minimal`` pack omits ``guardians``, so provisioning admits nobody and
#     the empty state is the correct rendering; the register's own total is
#     compared with the API's instead. Driving the wizard belongs to
#     ``people.students.manage.school_admin`` — here "Admit Student" only has to
#     be *offered*, which is what separates a licensed module from a read-only
#     husk.

# config/module_catalog.py — the feature-pack key and the /module/<route>
# segment happen to be the same string for this module.
STUDENTS_MODULE = "students"
STUDENTS_ROUTE = "students"

# The floor case: the most restricted pack the product can actually build.
MANDATORY_SCENARIO = "minimal"

# ── what makes the module mandatory ──────────────────────────────────────────
BASIC_GROUPS = ("people", "governance")
OPTIONAL_BASIC_MODULES = frozenset({"guardians", "families"})
PEOPLE_GROUP = "people"

# ── the sidebar (components/common/SideNavigation/nav-config.tsx) ────────────
NAV_SECTION_PEOPLE = re.compile(r"^\s*People Module\s*$", re.I)
NAV_STUDENTS = re.compile(r"^\s*Students\s*$", re.I)

# ── what the screen renders (src/app/module/students) ────────────────────────
SUBHEADING = re.compile(
    r"Easily update student information to ensure data accuracy", re.I
)
STAT_TOTAL_STUDENTS = re.compile(r"^\s*Total Students\s*$", re.I)
STAT_MALE_COUNT = re.compile(r"^\s*Male Count\s*$", re.I)
STAT_FEMALE_COUNT = re.compile(r"^\s*Female Count\s*$", re.I)
# The PageError that *replaces* ModuleHeader when /statistics/student throws.
STATS_LOAD_FAILURE = re.compile(r"^\s*Failed to load statistics\s*$", re.I)

TABLE_HEADING = re.compile(r"^\s*All Students\s*$", re.I)
TABLE_COLUMNS = ("Name", "Class", "Fee Group", "Status", "Gender", "Actions")
SEARCH_PLACEHOLDER = re.compile(r"^\s*Search student by name\s*$", re.I)
TABLE_EMPTY = re.compile(r"^\s*No students found\s*$", re.I)

# ── the module's own API surface (api/routes/student.py) ─────────────────────
STUDENT_LIST_PATH = "/student/"
STUDENT_LIST_KEYS = ("results", "total_count")
# The browser's own copy of that call. The "?" is what keeps this predicate off
# /statistics/student and off /student/{id}.
STUDENT_LIST_URL_MARKER = "/student/?"

# A module the same pack omits, *outside* the locked basic set, that the backend
# really does gate — the control proving the licence is enforced rather than
# decorative.
ENFORCED_UNLICENSED_MODULE = "fees"
ENFORCED_UNLICENSED_PATH = "/fees/1"
FEATURE_PACK_403 = re.compile(r"feature not available in your plan", re.I)

# The cookie every frontend gate derives its answer from.
MODULES_COOKIE = "schoolModules"

DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")

SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# The register's mount fetch waits on the branch store rehydrating out of
# (encrypted) localStorage before it fires at all, so it is given room.
MOUNT_FETCH_TIMEOUT_MS = 60_000


@pytest.mark.school_admin
@pytest.mark.scenario(MANDATORY_SCENARIO)
def test_students_is_reachable_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """The floor case still has its student register: licensed, offered, answering.

    Ledger unit ``people.students.always_licensed``. See the section header:
    ``students`` is in the ``people`` group, the pack builder locks that whole
    group into every pack, and the people/governance groups being core is
    **intended product behaviour, confirmed 2026-08-09**. So this asserts the
    opposite of a denial — and adds no gate of any kind.

    Read-only throughout. The point here is reachability, so nothing is admitted
    by this test: what matters is that the table is the *table*, that its total
    agrees with the API, and that neither ``/auth/no-access`` nor a load-failure
    panel got there first.
    """
    ctx = provisioned_school
    requested = set(ctx.feature_modules)
    students_page = StudentsPage(page, frontend_base_url)

    assert ctx.branches, (
        f"provisioning left {ctx.school_name!r} with no branch. Both this "
        f"screen's fetches are branch-scoped — GET /student/ answers 400 "
        f"BRANCH_ID_REQUIRED to a SchoolAdmin who names none, and the People "
        f"Module sidebar section is branchOnly — so there would be nothing to "
        f"reach. Phase B creates one for every scenario."
    )
    branch = ctx.branches[0]
    branch_name = str(branch.get("name") or "")
    branch_id = int(branch.get("id") or -1)
    assert branch_name and branch_id > 0, (
        f"provisioning could not capture this school's branch ({branch!r}). The "
        f"register is read per branch, so re-run provisioning rather than "
        f"guessing the id."
    )

    # ── 1. Licensed, and licensed because it cannot be dropped ────────────────
    super_token = api.login(
        ctx.super_admin.email, ctx.super_admin.password
    )["access_token"]
    catalogue = api.get("/feature-packs/system-modules", token=super_token)
    assert catalogue.status_code == 200, (
        "the SuperAdmin must be able to read the system module catalogue — got "
        f"{catalogue.status_code}: {catalogue.text[:300]}"
    )
    groups = {
        str(g.get("group")): [str(m) for m in (g.get("modules") or [])]
        for g in (catalogue.json().get("groups") or [])
    }
    assert STUDENTS_MODULE in groups.get(PEOPLE_GROUP, []), (
        f"{STUDENTS_MODULE!r} is no longer in the {PEOPLE_GROUP!r} group of the "
        f"backend catalogue (services/feature_pack_service.py). The create-pack "
        f"form locks a module in because of the group it belongs to, so that "
        f"membership is the whole reason this module is mandatory. "
        f"Groups: { {k: sorted(v) for k, v in groups.items()} }"
    )
    locked = {
        module
        for name in BASIC_GROUPS
        for module in groups.get(name, [])
        if module not in OPTIONAL_BASIC_MODULES
    }
    assert STUDENTS_MODULE in locked, (
        f"{STUDENTS_MODULE!r} is no longer one of the modules the SuperAdmin's "
        f"create-pack form forces into every pack, so a school's student register "
        f"can now be sold away from it and this unit's premise is gone. That is a "
        f"product change, not a test failure to paper over — re-read "
        f"config/feature_scenarios.yaml's `minimal` note and rewrite this unit as "
        f"a real denial test. Locked: {sorted(locked)}"
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — the "
        f"sidebar calls this on every mount — got {features.status_code}: "
        f"{features.text[:300]}"
    )
    body = features.json()
    assert body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so this is not "
        f"the {MANDATORY_SCENARIO!r} floor and nothing below is about licensing. "
        f"Provisioning phase A assigns one — check that it did."
    )
    licensed = {str(m) for m in (body.get("modules") or [])}
    assert licensed == requested | locked, (
        f"{ctx.school_name!r}'s licence is not 'what the {MANDATORY_SCENARIO!r} "
        f"pack requested plus the locked basic modules'. Requested "
        f"{sorted(requested)}; locked {sorted(locked)}; got {sorted(licensed)}. "
        f"Unexpectedly granted: {sorted(licensed - (requested | locked))}; "
        f"expected but missing: {sorted((requested | locked) - licensed)}."
    )
    assert STUDENTS_MODULE in licensed, (
        f"{ctx.school_name!r} — the most restricted pack this product can build — "
        f"is not licensed for {STUDENTS_MODULE!r}. The people group is core and "
        f"always on by design, so a school has just lost the register of who its "
        f"pupils are. Licensed: {sorted(licensed)}"
    )

    # ── 2. The licence is enforced for this user, on a module outside the lock ─
    assert ENFORCED_UNLICENSED_MODULE not in licensed, (
        f"{ctx.school_name!r} is now licensed for {ENFORCED_UNLICENSED_MODULE!r}, "
        f"so it can no longer serve as the control that the feature gate bites "
        f"for this user. Pick another module the {MANDATORY_SCENARIO!r} pack "
        f"omits, that is outside the locked basic set, and that a backend route "
        f"gates on."
    )
    assert ENFORCED_UNLICENSED_MODULE in _role_modules(api, SCHOOL_ADMIN_ROLE), (
        f"the seeded {SCHOOL_ADMIN_ROLE} role no longer holds an "
        f"{ENFORCED_UNLICENSED_MODULE!r} permission, so the 403 below would come "
        f"from the permission half of has_permission and prove nothing about "
        f"feature packs. Fix newschoolapp/db/repository/permissions.py or "
        f"re-point this control."
    )
    gated = api.get(ENFORCED_UNLICENSED_PATH, token=token)
    assert gated.status_code == 403, (
        f"{ENFORCED_UNLICENSED_PATH} answered {gated.status_code} for a "
        f"SchoolAdmin whose school is not licensed for "
        f"{ENFORCED_UNLICENSED_MODULE!r}; the feature-pack gate in "
        f"utils/permissions.has_permission should have refused it, and until it "
        f"does, 'the student register is reachable' says nothing. "
        f"Body: {gated.text[:300]}"
    )
    assert FEATURE_PACK_403.search(gated.text), (
        f"{ENFORCED_UNLICENSED_PATH} was refused, but not by the feature pack — "
        f"the detail should be 'Feature not available in your plan'. "
        f"Body: {gated.text[:300]}"
    )

    # ── 3. What the register is obliged to show, read from its own route ──────
    listing = api.get(
        f"{STUDENT_LIST_PATH}?skip=0&limit=25&branch_id={branch_id}", token=token
    )
    assert listing.status_code == 200, (
        f"GET {STUDENT_LIST_PATH} answered {listing.status_code} for the "
        f"SchoolAdmin of {ctx.school_name!r}, whose pack licenses "
        f"{STUDENTS_MODULE!r}. The route is "
        f"Depends(has_permission('read', {STUDENTS_MODULE!r})), so a 403 carrying "
        f"'Feature not available in your plan' would mean the people group "
        f"stopped being locked into every pack; anything else is the route itself "
        f"breaking. Body: {listing.text[:300]}"
    )
    assert not FEATURE_PACK_403.search(listing.text), (
        f"GET {STUDENT_LIST_PATH} returned 200 but its body reads like the "
        f"feature-pack refusal: {listing.text[:300]}"
    )
    roll = listing.json()
    for key in STUDENT_LIST_KEYS:
        assert key in roll, (
            f"GET {STUDENT_LIST_PATH} did not answer the paginated shape "
            f"useStudentsData reads (`results` + `total_count`, "
            f"api/api_models — StudentResponsePagination) — got keys {sorted(roll)}"
        )
    total_students = int(roll.get("total_count") or 0)

    # ── 4. Offered: the sidebar entry a SchoolAdmin is given ──────────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    cookie_modules = _school_modules_cookie(page)
    assert cookie_modules is not None, (
        f"the {MODULES_COOKIE!r} cookie was never written for this session. Every "
        f"frontend gate derives its answer from it, so without it the walk below "
        f"says nothing about what this school is licensed for. Both "
        f"src/app/auth/login/page.tsx and SideNavigation are meant to set it."
    )
    assert set(cookie_modules) == licensed, (
        f"the browser session claims {sorted(cookie_modules)} as its licensed "
        f"modules, out of step with /school_profile/{ctx.school_id}/features, "
        f"which reports {sorted(licensed)}"
    )
    assert STUDENTS_MODULE in cookie_modules, (
        f"{STUDENTS_MODULE!r} is missing from this session's {MODULES_COOKIE!r} "
        f"cookie, so src/middleware.ts would gate /module/{STUDENTS_ROUTE} for "
        f"any role without the SchoolAdmin carve-out — the register is not "
        f"reachable on the {MANDATORY_SCENARIO!r} pack for anybody else"
    )

    # Mandatory before the screen is asked for, not scene-setting: a SchoolAdmin
    # belongs to no branch, and both the branchOnly "People Module" nav section
    # and the register's own fetch wait on the branch store that only this click
    # fills. Its handler navigates away as a side effect — to /module/community,
    # and on to /auth/no-access when (as here) the pack has no community module —
    # which select_branch tolerates by design: the store is written before the
    # push, and the register is reached by route afterwards.
    BranchesPage(page, frontend_base_url).select_branch(branch_name)

    # ── 5. Working: the route loads and its own mount fetch answers ───────────
    with page.expect_response(
        _ok_student_list, timeout=MOUNT_FETCH_TIMEOUT_MS
    ) as listing_call:
        students_page.open()

    assert not DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} was redirected to {page.url!r} "
        f"asking for a module their pack licenses. The people group is core and "
        f"always on by design — a denial here is a regression, not a gate to keep."
    )
    assert page.url.rstrip("/").endswith(f"/module/{STUDENTS_ROUTE}"), (
        f"expected to still be on /module/{STUDENTS_ROUTE}, but the app moved to "
        f"{page.url!r}"
    )

    expect(page.get_by_role("heading", name=PAGE_HEADING).first).to_be_visible()
    expect(page.get_by_text(SUBHEADING).first).to_be_visible(timeout=20_000)

    expect(page.get_by_text(STATS_LOAD_FAILURE)).to_have_count(0)
    for label in (STAT_TOTAL_STUDENTS, STAT_MALE_COUNT, STAT_FEMALE_COUNT):
        expect(page.get_by_text(label).first).to_be_visible(timeout=20_000)

    expect(page.get_by_role("heading", name=as_pattern(TABLE_HEADING)).first
           ).to_be_visible(timeout=20_000)
    for column in TABLE_COLUMNS:
        expect(
            page.locator("thead th")
            .filter(has_text=as_pattern(rf"^\s*{re.escape(column)}\s*$"))
            .first
        ).to_be_visible(timeout=20_000)
    expect(page.get_by_placeholder(SEARCH_PLACEHOLDER).first).to_be_visible()

    # The write control the module exists for, offered rather than driven.
    expect(page.get_by_role("button", name=as_pattern(ADMIT_TRIGGER)).first
           ).to_be_visible(timeout=20_000)

    _expect_student_page(listing_call.value.json())
    expect(page.get_by_text(_total_badge(total_students)).first).to_be_visible(
        timeout=20_000
    )
    if total_students == 0:
        expect(page.get_by_text(TABLE_EMPTY).first).to_be_visible(timeout=20_000)

    # ── 6. Offered in the sidebar, now that a branch is selected ──────────────
    expect(page.get_by_text(NAV_SECTION_PEOPLE).first).to_be_visible(timeout=20_000)
    nav = page.get_by_role("navigation")
    expect(
        nav.get_by_role("link", name=as_pattern(NAV_STUDENTS)).first
    ).to_be_visible(timeout=20_000)
    expect(nav.locator(f'a[href="/module/{STUDENTS_ROUTE}"]').first).to_be_visible()


def _ok_student_list(response) -> bool:
    """Predicate for ``page.expect_response``: the register's list call, 200.

    ``useStudentsData`` fires this call again whenever the page, page size or a
    filter changes, and ``fetchStudents`` only appends ``branch_id`` once the
    persisted branch store has rehydrated — so a first attempt can legitimately be
    answered 400 BRANCH_ID_REQUIRED and then succeed. Waiting for the 200 tolerates
    that, while a route that is genuinely gated never produces one.
    """
    return STUDENT_LIST_URL_MARKER in response.url and response.status == 200


def _expect_student_page(payload: Any) -> None:
    """``StudentResponsePagination`` as ``useStudentsData`` destructures it."""
    assert isinstance(payload, dict), (
        f"GET {STUDENT_LIST_PATH} answered the browser with "
        f"{type(payload).__name__}, not the paginated object useStudentsData "
        f"reads: {payload!r}"
    )
    for key in STUDENT_LIST_KEYS:
        assert key in payload, (
            f"GET {STUDENT_LIST_PATH} is missing the {key!r} key the register "
            f"reads (api/api_models — StudentResponsePagination) — got keys "
            f"{sorted(payload)}"
        )
    assert isinstance(payload.get("results"), list), (
        f"GET {STUDENT_LIST_PATH} answered a `results` of "
        f"{type(payload.get('results')).__name__}, but StudentsTable maps over it"
    )


def _total_badge(total: int) -> re.Pattern[str]:
    """StudentsTable's count badge: ``{totalCount} student{s} total``."""
    return re.compile(rf"^\s*{total} student{'' if total == 1 else 's'} total\s*$", re.I)


def _role_modules(api: BackendAPI, role_name: str) -> set[str]:
    """Every module the named seeded role holds a permission on."""
    role = api.get(f"/roles/{api.role_id_for(role_name)}")
    assert role.status_code == 200, (
        f"could not read the {role_name} role — got {role.status_code}: "
        f"{role.text[:300]}"
    )
    return {str(p.get("module")) for p in role.json().get("permissions", [])}


def _school_modules_cookie(page: Page) -> list[str] | None:
    """The ``schoolModules`` cookie as a list, or ``None`` if it is not readable."""
    for cookie in page.context.cookies():
        if cookie.get("name") != MODULES_COOKIE:
            continue
        try:
            parsed = json.loads(unquote(str(cookie.get("value") or "")))
        except json.JSONDecodeError:
            return None
        return [str(m) for m in parsed] if isinstance(parsed, list) else None
    return None


# ═══════════════════ people.students.manage.school_admin ═════════════════════
#
# What "manage" is on this module
#     One pupil's whole clerical life on screen: admitted through the wizard at
#     ``/module/students/admit-student`` (``POST /student/``), read back off the
#     register and off their own record, then corrected through the edit wizard
#     at ``/module/students/edit-student/<id>`` (``PUT /student/<id>``). Every
#     claim is made against what the next person to open the screen would see —
#     the register's own row, the record's Basic Info tab, and finally
#     ``GET /student/<id>`` itself — so a write the wizard toasted about but that
#     never reached the database fails on the following step instead of passing
#     quietly.
#
# Why the ``minimal`` pack, and what that changes about the wizard
#     ``students`` sits in the pack builder's locked ``people`` group, so the
#     floor case licenses it (see ``people.students.always_licensed`` above).
#     What that pack does *not* license is ``guardians`` or
#     ``classes_and_timetables`` — and both of those are optional fields of the
#     admission wizard:
#
#       * "Guardian's Name" is labelled "(Optional)" and the Contact Details
#         step's ``requiredFields`` array is empty, so Continue never waits on it.
#       * "Class" is unlabelled-optional too; ``AdmitStudent.handleSubmit`` omits
#         ``class_id`` from the payload entirely when it is 0, and the register
#         then prints "Not Provided" in the Class and Fee Group columns.
#
#     So the pupil below is admitted with neither, which is a real shape of the
#     product (a school that bought people-management and nothing else), not a
#     shortcut around the wizard.
#
# Why the branch is selected first, and why it is not cosmetic
#     Three reasons, any one of which is fatal on its own. The sidebar's whole
#     "People Module" section is ``branchOnly`` (nav-config.tsx), so the
#     "Students" entry this video walks through is not even drawn until the
#     branch store is filled. Both of the register's mount effects return early
#     for a SchoolAdmin while ``currentSchoolAdminBranch?.branch_id`` is unset,
#     so the table would never load. And the wizard posts
#     ``school_branch_id: currentSchoolAdminBranch?.branch_id ?? 0``, which the
#     backend answers 404 "The Branch does not exist" for. Only the branch row's
#     "View" button fills that store — see ``BranchesPage.select_branch``.
#
# What the edit wizard can actually change — and what it silently cannot
#     ``edit-student/[editstudentId]/page.tsx`` builds its PUT body from
#     ``date_of_admission``, ``previous_school``, ``blood_type``,
#     ``additional_remarks``, ``guardian_id``, ``class_id`` and a ``user`` block
#     of name / gender / date of birth / nationality / religion / residential
#     address / location / phones. The **email** box step 1 renders is not in
#     that body at all, so this test corrects address, region, previous school,
#     blood type and remarks, and asserts the email is *unchanged* — it must not
#     be extended to expect an email edit to stick, and widening the payload
#     would be a product question (what a school may amend about a person after
#     the fact), not a defect anyone can settle from here.
#
# Deliberately not asserted: a delete
#     Nothing under ``/module/students`` offers one — the row has a "View" link
#     and the record screen has Impersonate / Add Fee / Remove Fee / Edit — so
#     retiring the pupil would mean reaching for ``DELETE /student/{id}`` over the
#     API, a route no user of this module can reach. The pupil is left behind
#     carrying the run tag in their generated address, which is what the orphan
#     sweeper matches on, and the whole school is torn down by the provisioning
#     fixture anyway.

MANAGE_SCENARIO = "minimal"
MANAGE_STUDENTS_MODULE = "students"

# Where the walk to the register has to pass through first. `select_branch`
# leaves the browser wherever its hardcoded push landed — on this pack that is
# /auth/no-access, which renders no app shell and therefore no sidebar at all
# — so the People menu can only be picked up again from a licensed module
# reached by route. `home` is in the locked people group, so it is on every pack.
MANAGE_HOME_ROUTE = "home"

# What the pupil is admitted as. Every name-ish box in this wizard strips
# anything outside /[A-Za-z\s]/ (BasicInformation, ContactDetails), so the run
# tag — hex — must stay out of them; the generated email carries it instead, and
# that is what the sweeper and the search box both match on. Residential Address
# is the one free-text field, so it is written as a real address on purpose.
MANAGE_DATE_OF_BIRTH = "2014-05-12"
MANAGE_ADDRESS = "24 Ring Road East, Accra"
MANAGE_LOCATION = "Accra"
MANAGE_PREVIOUS_SCHOOL = "Bright Beginnings School"
MANAGE_BLOOD_TYPE = "O+"

# …and what the school corrects once the family moves.
MANAGE_NEW_ADDRESS = "18 Harbour Road, Takoradi"
MANAGE_NEW_LOCATION = "Takoradi"
MANAGE_NEW_PREVIOUS_SCHOOL = "Sunbeam Preparatory"
MANAGE_NEW_BLOOD_TYPE = "A+"
MANAGE_REMARKS = "Transferred in during the second term"

# Captions on the record screen (students/[student]/page.tsx). Each one is an
# InfoField: <p>CAPTION</p><p>value</p>, the caption upper-cased in CSS only.
# Anchored so "Email" cannot resolve to anything else the page renders.
MANAGE_FIELD_FIRST_NAME = re.compile(r"^\s*First Name\s*$", re.I)
MANAGE_FIELD_OTHER_NAMES = re.compile(r"^\s*Other Name\(s\)\s*$", re.I)
MANAGE_FIELD_EMAIL = re.compile(r"^\s*Email\s*$", re.I)
MANAGE_FIELD_GENDER = re.compile(r"^\s*Gender\s*$", re.I)
MANAGE_FIELD_STUDENT_ID = re.compile(r"^\s*Student ID\s*$", re.I)
MANAGE_FIELD_DATE_OF_BIRTH = re.compile(r"^\s*Date of Birth\s*$", re.I)
MANAGE_FIELD_REGION = re.compile(r"^\s*Region\s*$", re.I)
MANAGE_FIELD_HOME_ADDRESS = re.compile(r"^\s*Home Address\s*$", re.I)
MANAGE_FIELD_CURRENT_LEVEL = re.compile(r"^\s*Current Level\s*$", re.I)
MANAGE_FIELD_PREVIOUS_SCHOOL = re.compile(r"^\s*Previous School\s*$", re.I)

# formatDate() on that screen: toLocaleDateString("en-GB", {day:"2-digit",
# month:"long", year:"numeric"}).
MANAGE_DISPLAY_DATE_OF_BIRTH = "12 May 2014"

# The admission POST. The register's own list call on the same path answers 200,
# so only the 201 identifies the create.
MANAGE_CREATE_PATH = "/student/"
MANAGE_CREATE_STATUS = 201
# The capture window opens before the first wizard step and the admission is
# three steps deep with an antd date picker, so the POST lands well past the
# 25s default.
MANAGE_CREATE_TIMEOUT_MS = 120_000


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="people.students.manage.school_admin",
    title="Students",
    subtitle="SchoolAdmin creates and manages students",
)
def test_school_admin_admits_and_amends_a_student(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin admits a pupil, reads them back, then corrects the record."""
    ctx = provisioned_school
    assert MANAGE_STUDENTS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} must license {MANAGE_STUDENTS_MODULE!r} "
        f"for the manage path. It is in the pack builder's locked 'people' "
        f"group, so a pack without it should not be buildable at all — see "
        f"test_students_is_reachable_on_the_minimal_pack"
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — phase B creates one for "
        "every scenario, and without one in the store the People sidebar section "
        "is not drawn, the register issues no GET at all, and the admission "
        "wizard would post school_branch_id: 0"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    students = StudentsPage(page, base_url)
    branch_name = str(ctx.branches[0]["name"])

    # Faker names, sanitised the way the wizard's inputs sanitise them, so every
    # assertion looks for the name the app will actually have stored rather than
    # the one that was typed.
    person = make_person("student-manage", ctx.scenario_id, gender="Male")
    first_name = _manage_letters(person.first_name)
    last_name = _manage_letters(person.last_name)
    full_name = f"{first_name} {last_name}"

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Point the console at {branch_name}"):
        # Mandatory, not cosmetic: it fills the branch store the register's fetch
        # effects wait on, unlocks the branchOnly People menu, and is what the
        # admission wizard reads school_branch_id from.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open Students from the People menu"):
        # select_branch left the browser on /auth/no-access (its push targets
        # /module/community, which this pack does not license), and that page
        # renders no sidebar. Come back into the app shell by route first —
        # otherwise the People menu below is asserted against a screen that has
        # no menu at all.
        goto_module(page, base_url, MANAGE_HOME_ROUTE)
        students.expect_nav_entry()
        students.open_from_nav()

    with demo.step("This is the school's register of pupils today"):
        # The panel heading first: until the register's own fetch answers, the
        # table is a skeleton loader, and the column assertion below would be
        # reading that instead.
        expect(page.get_by_text(as_pattern(STUDENTS_PANEL)).first).to_be_visible(
            timeout=20_000
        )
        students.expect_column_headers()
        for tile in (STAT_TOTAL, STAT_MALE, STAT_FEMALE):
            expect(page.get_by_text(tile).first).to_be_visible(timeout=20_000)
        expect(
            page.get_by_role("button", name=as_pattern(ADMIT_TRIGGER)).first
        ).to_be_visible()
        students.expect_no_load_failure()

    with demo.step(f"Admit {full_name} through the admission wizard"):
        # No guardian and no class: this pack licenses neither module, and both
        # fields are optional in the wizard (see the section header). The capture
        # reads the generated password out of QA mode, which is also what proves
        # the POST — not just the toast — actually happened.
        captured = capture_credentials(
            page,
            lambda: students.admit_student(
                first_name=first_name,
                last_name=last_name,
                email=person.email,
                gender=person.gender,
                date_of_birth=MANAGE_DATE_OF_BIRTH,
                address=MANAGE_ADDRESS,
                location=MANAGE_LOCATION,
                guardian_name="",
                class_name="",
                previous_school=MANAGE_PREVIOUS_SCHOOL,
                blood_type=MANAGE_BLOOD_TYPE,
            ),
            url_substring=MANAGE_CREATE_PATH,
            email=person.email,
            statuses=(MANAGE_CREATE_STATUS,),
            timeout_ms=MANAGE_CREATE_TIMEOUT_MS,
        )
        created_id = captured.body.get("id")
        assert isinstance(created_id, int), (
            f"POST {MANAGE_CREATE_PATH} answered 201 without an id: "
            f"{sorted(captured.body)}"
        )

    with demo.step("The register now carries them"):
        students.search(full_name)
        expect(students.find_row(full_name)).to_be_visible(timeout=20_000)
        # Name is asserted as "contains": the cell also holds the initials avatar
        # the register draws for a pupil with no photo.
        expect(students.cell(full_name, "name")).to_contain_text(full_name)
        expect(students.cell(full_name, "gender")).to_have_text(person.gender)
        expect(students.cell(full_name, "status")).to_have_text("Active")
        # Admitted without a class, so both class-derived columns say so — which
        # is also what proves the wizard omitted class_id rather than sending 0.
        expect(students.cell(full_name, "class")).to_have_text(NOT_PROVIDED)
        expect(students.cell(full_name, "fee_group")).to_have_text(NOT_PROVIDED)
        students.expect_no_load_failure()

    with demo.step("Open their record — this is what the school now holds"):
        student_id = students.open_detail(full_name)
        assert student_id == created_id, (
            f"the register's row for {full_name!r} links to student "
            f"{student_id}, but the admission created {created_id}"
        )
        expect(students.detail_value(MANAGE_FIELD_FIRST_NAME)).to_have_text(first_name)
        expect(students.detail_value(MANAGE_FIELD_OTHER_NAMES)).to_have_text(last_name)
        expect(students.detail_value(MANAGE_FIELD_EMAIL)).to_have_text(person.email)
        expect(students.detail_value(MANAGE_FIELD_GENDER)).to_have_text(person.gender)
        expect(students.detail_value(MANAGE_FIELD_DATE_OF_BIRTH)).to_have_text(
            MANAGE_DISPLAY_DATE_OF_BIRTH
        )
        expect(students.detail_value(MANAGE_FIELD_HOME_ADDRESS)).to_have_text(
            MANAGE_ADDRESS
        )
        expect(students.detail_value(MANAGE_FIELD_REGION)).to_have_text(MANAGE_LOCATION)
        expect(students.detail_value(MANAGE_FIELD_PREVIOUS_SCHOOL)).to_have_text(
            MANAGE_PREVIOUS_SCHOOL
        )
        # The school generates the admission number itself — the wizard sends an
        # empty student_id and StudentService builds "<initials><year>-<seq>".
        expect(students.detail_value(MANAGE_FIELD_STUDENT_ID)).not_to_have_text(
            NOT_PROVIDED
        )
        # No class was picked, so the record says so too rather than inventing one.
        expect(students.detail_value(MANAGE_FIELD_CURRENT_LEVEL)).to_have_text(
            NOT_PROVIDED
        )

    with demo.step("The family has moved, so correct the record"):
        edited_id = students.edit_student(
            address=MANAGE_NEW_ADDRESS,
            location=MANAGE_NEW_LOCATION,
            previous_school=MANAGE_NEW_PREVIOUS_SCHOOL,
            blood_type=MANAGE_NEW_BLOOD_TYPE,
            description=MANAGE_REMARKS,
        )
        assert edited_id == student_id, (
            f"the record's Edit button opened student {edited_id} while the "
            f"record on screen was {student_id}"
        )

    with demo.step("The correction is what the school now holds", dwell_ms=2000):
        students.search(full_name)
        reopened = students.open_detail(full_name)
        assert reopened == student_id, (
            f"the register's row for {full_name!r} now links to student "
            f"{reopened} but the record that was edited was {student_id} — the "
            f"edit created a second pupil instead of amending the first"
        )
        expect(students.detail_value(MANAGE_FIELD_HOME_ADDRESS)).to_have_text(
            MANAGE_NEW_ADDRESS
        )
        expect(students.detail_value(MANAGE_FIELD_REGION)).to_have_text(
            MANAGE_NEW_LOCATION
        )
        expect(students.detail_value(MANAGE_FIELD_PREVIOUS_SCHOOL)).to_have_text(
            MANAGE_NEW_PREVIOUS_SCHOOL
        )
        # …and the correction touched only what it was asked to. The email box is
        # rendered by the edit wizard but never sent (see the section header), so
        # it must still be the address they were admitted with.
        expect(students.detail_value(MANAGE_FIELD_FIRST_NAME)).to_have_text(first_name)
        expect(students.detail_value(MANAGE_FIELD_OTHER_NAMES)).to_have_text(last_name)
        expect(students.detail_value(MANAGE_FIELD_EMAIL)).to_have_text(person.email)
        expect(students.detail_value(MANAGE_FIELD_DATE_OF_BIRTH)).to_have_text(
            MANAGE_DISPLAY_DATE_OF_BIRTH
        )

        # Finally, straight off the record the backend stores — the screen renders
        # from the same GET, so this is what proves the PUT landed rather than the
        # record having been repainted from local state. Blood type and the
        # remarks are only asserted here: no tab of the record screen prints them.
        _manage_expect_stored(
            api,
            ctx,
            student_id,
            first_name=first_name,
            other_names=last_name,
            email=person.email,
            residential_address=MANAGE_NEW_ADDRESS,
            location=MANAGE_NEW_LOCATION,
            previous_school=MANAGE_NEW_PREVIOUS_SCHOOL,
            blood_type=MANAGE_NEW_BLOOD_TYPE,
            additional_remarks=MANAGE_REMARKS,
        )


def _manage_expect_stored(
    api: BackendAPI,
    ctx: SchoolContext,
    student_id: int,
    *,
    first_name: str,
    other_names: str,
    email: str,
    residential_address: str,
    location: str,
    previous_school: str,
    blood_type: str,
    additional_remarks: str,
) -> None:
    """Assert ``GET /student/<id>`` holds exactly what the screens claimed.

    Read as the same SchoolAdmin the UI ran as, so this is the record the app
    itself would serve — not a privileged view of it.
    """
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    response = api.get(f"/student/{student_id}", token=token)
    assert response.status_code == 200, (
        f"GET /student/{student_id} answered {response.status_code}: "
        f"{response.text[:300]}"
    )
    body = response.json()
    user = body.get("user") or {}

    expected_profile = {
        "previous_school": previous_school,
        "blood_type": blood_type,
        "additional_remarks": additional_remarks,
    }
    for key, value in expected_profile.items():
        assert body.get(key) == value, (
            f"student {student_id} stores {key}={body.get(key)!r}, but the edit "
            f"wizard was given {value!r} and reported success"
        )

    expected_user = {
        "first_name": first_name,
        "other_names": other_names,
        "email": email,
        "residential_address": residential_address,
        "location": location,
    }
    for key, value in expected_user.items():
        assert user.get(key) == value, (
            f"student {student_id}'s user record stores {key}={user.get(key)!r}, "
            f"expected {value!r}"
        )

    assert body.get("student_id"), (
        f"student {student_id} was stored without an admission number; the "
        f"backend generates one (StudentService.create_student) because the "
        f"wizard always sends an empty student_id"
    )


def _manage_letters(value: str) -> str:
    """Name inputs in this wizard drop anything outside /[A-Za-z\\s]/."""
    return re.sub(r"[^A-Za-z\s]", "", value).strip()
