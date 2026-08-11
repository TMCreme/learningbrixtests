"""People → Staff — the employee register (`staff`).

Where this module lives
    ``/module/staff`` (``smsfrontend/src/app/module/staff/page.tsx``). The
    "Manage Staff" workspace: a ModuleHeader stat strip over
    ``GET /statistics/staff``, two server-paginated tabs — "Teaching Staff"
    (``GET /teacher/``) and "Non-teaching Staff" (``GET /non-teaching/``) — a
    "Search staff by name" box, an "Add Teaching Staff" / "Add Non-teaching
    Staff" link into the three-step wizard (``POST /teacher/`` and
    ``POST /non-teaching/``), and a per-row "View" into the profile screen at
    ``/module/staff/<id>``, from which "Edit Profile" reaches the edit wizard
    (``PUT /teacher/<id>``).

Manage path: a SchoolAdmin of the ``minimal`` school
(``test_school_admin_creates_and_manages_staff``) — one teacher's whole first
day: hired through the three-step wizard, read back off the register and off
their own profile, then corrected through the edit wizard.

Why the ``minimal`` pack, and why that is not an accident
    ``staff`` is one of the modules the feature-pack builder *locks* into every
    pack: it is a member of the "people" group in ``BASIC_GROUPS``
    (``smsfrontend/src/app/module/feature_flag/{create,edit}/page.tsx``), where
    only ``guardians`` and ``families`` stay optional. So there is no pack a
    school can be sold that omits staff, and this unit runs against the floor
    case precisely to show the register still works there — on the most
    restricted school the product can actually produce. No denial is asserted
    anywhere in this file, and none should be added: an unlicensable module has
    no negative path to test.

    The corollary matters for the assertions below. ``minimal`` licenses neither
    ``classes_and_timetables`` nor ``subjects``, so this school has no class and
    no subject at all — the wizard's optional Assigned Class/Subject pickers have
    nothing to offer, the register prints "No subjects assigned", and the
    profile's Academics tab says "No subjects assigned yet." That is the correct
    state for this school, not a failed assignment.

Why the branch is selected first, and why it is not cosmetic
    Both of the register's mount effects return early for a SchoolAdmin while
    ``currentSchoolAdminBranch?.branch_id`` is unset (``page.tsx``), so with no
    branch in the store the page issues no request and simply renders an empty
    table; the sidebar's whole "People Module" section is ``branchOnly``
    (``nav-config.tsx``), so the "Staff" entry the video walks through is not
    even drawn; and the create wizard posts ``school_branch_id:
    resolveBranchId(…) ?? 0``, which the backend answers 404 "The Branch does not
    exist" for. ``BranchesPage.select_branch`` fills that store — see it for why
    only the branch row's "View" button can.

What the edit wizard can actually change — and what it silently cannot
    ``edit-staff/[staffID]/page.tsx`` builds its PUT body from ``job_title``,
    ``employment_type``, ``admission_date``, ``field_of_study``,
    ``highest_degree_earned``, ``additional_remarks`` and a ``user`` block. The
    backend's ``UserUpdate`` model (``api/api_models/user.py``) declares only
    ``first_name``, ``other_names``, ``profile_pic``, ``religion``, ``gender``,
    ``date_of_birth``, ``nationality``, ``marital_status``,
    ``residential_address``, ``location``, ``primary_phone``,
    ``secondary_phone`` and ``zip_code`` — so the ``email``, ``local_dialect``,
    ``is_active``, ``role_id`` and hard-coded ``password`` the page also sends
    are dropped on the floor by Pydantic before ``update_user`` ever sees them.
    This test therefore corrects only fields that can land, and asserts each one
    on the reloaded profile *and* on ``GET /teacher/{id}``. Do not extend it to
    the email box expecting the change to stick, and do not "fix" that by
    widening ``UserUpdate``: whether a school may re-address a member of staff
    after the fact is a product question, not a defect anyone can settle here.

Deliberately *not* asserted: that a staff member can be retired
    Nothing under ``/module/staff`` offers a delete — the list has no row menu
    and the profile screen has no destructive action — so retiring one would mean
    reaching for ``DELETE /teacher/{id}`` over the API, a route no user of this
    module can get to. The staff member is left behind carrying the run tag in
    their generated address, which is what the orphan sweeper matches on, and the
    whole school is torn down by the provisioning fixture anyway.

Deliberately *not* asserted: the subject-assignment panel on the Academics tab
    It is on screen and it is the documented home of assignments (the edit
    wizard's own note says so), but its Class dropdown is fed by
    ``GET /classes/`` and this pack has no classes module, hence no class to
    pick. Driving it here would assert a product decision about an unlicensed
    module rather than anything about staff.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import make_person
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern, goto_module
from tests.pages.login import login_as
from tests.pages.people.staff import (
    ADD_TEACHING_TRIGGER,
    EDIT_PROFILE_BUTTON,
    NO_SUBJECTS_ASSIGNED,
    PAGE_HEADING,
    SEARCH_FIELD,
    StaffPage,
)
from tests.pages.school_admin.branches import BranchesPage

STAFF_MODULE = "staff"

# config/module_catalog.py's route for this module, and the one the walk to it
# starts from — /module/home is the People menu's own first entry.
HOME_ROUTE = "home"

MANAGE_SCENARIO = "minimal"

# ── what the new teacher is hired as ─────────────────────────────────────────
# Every one of these boxes strips anything outside /[A-Za-z\s]/ on the way in
# (staff/components/*.tsx), so the run tag — which is hex — must stay out of
# them; the generated email carries it instead, and that is what the orphan
# sweeper and the register's search box both match on. Residential Address is
# the one free-text field with no such filter, which is why it is written as a
# real address: it is also the only assertion here that would catch that filter
# being applied where it is not today.
MANAGE_JOB_TITLE = "Class Teacher"
MANAGE_EMPLOYMENT_TYPE = "Full-time"
MANAGE_DEGREE = "Bachelor's Degree"
MANAGE_FIELD_OF_STUDY = "Mathematics"
MANAGE_MARITAL_STATUS = "Single"
MANAGE_DIALECT = "Twi"
MANAGE_RELIGION = "Christianity"
MANAGE_LOCATION = "Accra"
MANAGE_DATE_OF_BIRTH = "1990-01-01"
# Today, the way provisioning hires its own staff: the register prints
# ``admission_date`` back verbatim as the ISO string the API stores, and a hire
# date is the one field here that is naturally "now".
MANAGE_ADMISSION_DATE = date.today().isoformat()

# …and what the school corrects once they take on the head-of-department post.
MANAGE_NEW_JOB_TITLE = "Head of Mathematics"
MANAGE_NEW_FIELD_OF_STUDY = "Applied Mathematics"
MANAGE_NEW_RELIGION = "Islam"
MANAGE_NEW_ADDRESS = "18 Ring Road East, Accra"
MANAGE_NEW_PHONE = "0209876543"
MANAGE_DESCRIPTION = "Reachable after four in the afternoon"

# Captions on the profile screen (staff/[staffID]/page.tsx). Anchored so
# "Phone Number" cannot resolve to anything longer and so "Job Title" cannot
# resolve to the edit wizard's field of the same name.
MANAGE_INFO_FIRST_NAME = re.compile(r"^\s*First Name\s*$", re.I)
MANAGE_INFO_OTHER_NAMES = re.compile(r"^\s*Other Name\(s\)\s*$", re.I)
MANAGE_INFO_PHONE = re.compile(r"^\s*Phone Number\s*$", re.I)
MANAGE_INFO_ADDRESS = re.compile(r"^\s*Residential Address\s*$", re.I)
MANAGE_INFO_RELIGION = re.compile(r"^\s*Religion\s*$", re.I)
MANAGE_INFO_NATIONALITY = re.compile(r"^\s*Nationality\s*$", re.I)
MANAGE_INFO_STAFF_ID = re.compile(r"^\s*Staff ID\s*$", re.I)
MANAGE_INFO_LOCATION = re.compile(r"^\s*Location\s*$", re.I)
MANAGE_SIDE_JOB_TITLE = re.compile(r"^\s*Job Title\s*$", re.I)
MANAGE_SIDE_SUBJECTS = re.compile(r"^\s*Subjects Taught\s*$", re.I)
# What the side card prints when a teacher has no (subject, class) pair.
MANAGE_NO_ASSIGNMENTS = "None"
# What the register prints in the same case.
MANAGE_NO_SUBJECTS_CELL = "No subjects assigned"
MANAGE_ACTIVE_STATUS = "Active"

# Where the frontend sends a user it has decided is not allowed in. Asserted
# absent throughout: `staff` is licensed for every school there is, so landing
# here would mean the workspace had evicted the one role it is built for.
NO_ACCESS_URL = re.compile(r"/auth/no-access")


@pytest.mark.school_admin
@pytest.mark.scenario(MANAGE_SCENARIO)
@pytest.mark.demo(
    feature_id="people.staff.manage.school_admin",
    title="Staff",
    subtitle="SchoolAdmin creates and manages staff",
)
def test_school_admin_creates_and_manages_staff(
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """A SchoolAdmin hires a teacher, reads them back, then corrects the record.

    Every claim is made against what the next person to open the screen would
    see — the register's own row, the staff member's profile, and the record as
    ``GET /teacher/{id}`` actually stores it — so a write the wizard toasted
    about but that never reached the database fails on the following step
    instead of passing quietly.
    """
    ctx = provisioned_school
    assert STAFF_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} does not license {STAFF_MODULE!r}, but the "
        f"pack builder locks the whole 'people' group into every pack (only "
        f"guardians and families are optional inside it). If this ever fails, the "
        f"builder has changed and this file's premise with it — do not paper over "
        f"it by adding a denial path here."
    )
    assert ctx.branches, (
        "provisioning left this school with no branch — phase B creates one for "
        "every scenario, and without one in the store this page issues no GET at "
        "all, the People sidebar section is not drawn, and the create wizard "
        "would post school_branch_id: 0"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    staff = StaffPage(page, base_url)
    branch_name = str(ctx.branches[0]["name"])

    # Faker names, sanitised the way the wizard's own inputs sanitise them, so
    # the assertions look for the name the app will have stored rather than the
    # one that was typed.
    person = make_person("staff-manage", ctx.scenario_id, gender="Male")
    first_name = _manage_letters(person.first_name)
    last_name = _manage_letters(person.last_name)
    full_name = f"{first_name} {last_name}"
    phone = _manage_digits(person.phone)

    with demo.step("Sign in as the school administrator"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Point the console at {branch_name}"):
        # Mandatory, not cosmetic: it fills the branch store the register's fetch
        # effects wait on, unlocks the branchOnly People menu, and is what the
        # create wizard reads school_branch_id from. On this pack the method's
        # hardcoded push lands on /auth/no-access, which it tolerates by design —
        # the store is written before the push.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open Staff from the People menu"):
        goto_module(page, base_url, HOME_ROUTE)
        staff.expect_nav_entry()
        staff.open_from_nav()

    with demo.step("This is everyone the school employs today"):
        staff.show_teaching()
        staff.expect_column_headers()
        expect(
            page.get_by_role("button", name=as_pattern(ADD_TEACHING_TRIGGER)).first
        ).to_be_visible(timeout=20_000)
        staff.expect_no_load_failure()

    with demo.step(f"Hire {full_name} as a teacher"):
        # create_teaching_staff walks all three steps, waiting for each Continue
        # to enable, and lands back on the register with the new row on screen.
        # No class or subject is assigned: this pack licenses neither module, so
        # the wizard's optional pickers have nothing to offer.
        staff.create_teaching_staff(
            first_name=first_name,
            last_name=last_name,
            email=person.email,
            gender=person.gender,
            date_of_birth=MANAGE_DATE_OF_BIRTH,
            nationality=person.nationality,
            marital_status=MANAGE_MARITAL_STATUS,
            dialect=MANAGE_DIALECT,
            address=person.address,
            location=MANAGE_LOCATION,
            phone=phone,
            religion=MANAGE_RELIGION,
            job_title=MANAGE_JOB_TITLE,
            employment_type=MANAGE_EMPLOYMENT_TYPE,
            admission_date=MANAGE_ADMISSION_DATE,
            degree=MANAGE_DEGREE,
            field_of_study=MANAGE_FIELD_OF_STUDY,
        )

    with demo.step("The register now carries them, with their contact details"):
        # Name is asserted as "contains": the cell also holds the initials avatar
        # the page draws when a staff member has no photo.
        expect(staff.cell(person.email, "name")).to_contain_text(full_name)
        expect(staff.cell(person.email, "email")).to_have_text(person.email)
        expect(staff.cell(person.email, "phone")).to_have_text(phone)
        expect(staff.cell(person.email, "status")).to_have_text(MANAGE_ACTIVE_STATUS)
        expect(staff.cell(person.email, "hire_date")).to_have_text(MANAGE_ADMISSION_DATE)
        expect(staff.cell(person.email, "subjects")).to_have_text(
            MANAGE_NO_SUBJECTS_CELL
        )
        staff.expect_no_load_failure()

    with demo.step("Open their profile — this is what the school holds on them"):
        staff_id = staff.open_detail(person.email)
        assert not NO_ACCESS_URL.search(page.url), (
            f"opening a staff profile bounced the SchoolAdmin to {page.url!r}. "
            f"{STAFF_MODULE!r} is licensed for every school the product can sell, "
            f"so the profile of a staff member they just hired must be reachable. "
            f"This is the signature of a panel on the page fetching data from a "
            f"module the pack omits — see staff/[staffID]/page.tsx and "
            f"src/utils/moduleLicence.ts."
        )
        expect(staff.detail_value(MANAGE_INFO_FIRST_NAME)).to_have_text(first_name)
        expect(staff.detail_value(MANAGE_INFO_OTHER_NAMES)).to_have_text(last_name)
        expect(staff.detail_value(MANAGE_INFO_PHONE)).to_have_text(phone)
        expect(staff.detail_value(MANAGE_INFO_ADDRESS)).to_have_text(person.address)
        expect(staff.detail_value(MANAGE_INFO_RELIGION)).to_have_text(MANAGE_RELIGION)
        expect(staff.detail_value(MANAGE_INFO_NATIONALITY)).to_have_text(
            person.nationality
        )
        expect(staff.detail_value(MANAGE_INFO_LOCATION)).to_have_text(MANAGE_LOCATION)
        expect(staff.detail_value(MANAGE_SIDE_JOB_TITLE)).to_have_text(MANAGE_JOB_TITLE)
        staff.expect_no_load_failure()

        # The staff number the backend issued on POST /teacher/ — the one field
        # on this screen nobody typed.
        stored_staff_id = staff.detail_value(MANAGE_INFO_STAFF_ID).inner_text().strip()
        assert stored_staff_id, (
            f"the profile of teacher {staff_id} prints no Staff ID; the backend "
            f"generates one on create (TeacherService.create_teacher), so an empty "
            f"box means it never reached the record"
        )

    with demo.step("They teach nothing yet — no subject is assigned to them"):
        staff.open_academics_tab()
        expect(page.get_by_text(as_pattern(NO_SUBJECTS_ASSIGNED)).first).to_be_visible(
            timeout=20_000
        )
        expect(staff.detail_value(MANAGE_SIDE_SUBJECTS)).to_have_text(
            MANAGE_NO_ASSIGNMENTS
        )

    # The record as it stands before the correction, so the "unchanged" claims
    # below are made against what the backend really stored rather than against
    # what the wizard was told to type.
    before = _manage_stored(api, ctx, staff_id)

    with demo.step("They are promoted, so correct the record"):
        expect(
            page.get_by_role("button", name=as_pattern(EDIT_PROFILE_BUTTON)).first
        ).to_be_visible(timeout=20_000)
        staff.edit_teaching_staff(
            job_title=MANAGE_NEW_JOB_TITLE,
            field_of_study=MANAGE_NEW_FIELD_OF_STUDY,
            description=MANAGE_DESCRIPTION,
            address=MANAGE_NEW_ADDRESS,
            phone=MANAGE_NEW_PHONE,
            religion=MANAGE_NEW_RELIGION,
        )

    with demo.step("The correction is what the school now holds", dwell_ms=2000):
        reopened = staff.open_detail(person.email)
        assert reopened == staff_id, (
            f"the register's row for {person.email!r} now links to staff member "
            f"{reopened} but the profile that was edited was {staff_id} — the edit "
            f"created a second record instead of amending the first"
        )
        expect(staff.detail_value(MANAGE_SIDE_JOB_TITLE)).to_have_text(
            MANAGE_NEW_JOB_TITLE
        )
        expect(staff.detail_value(MANAGE_INFO_PHONE)).to_have_text(MANAGE_NEW_PHONE)
        expect(staff.detail_value(MANAGE_INFO_ADDRESS)).to_have_text(MANAGE_NEW_ADDRESS)
        expect(staff.detail_value(MANAGE_INFO_RELIGION)).to_have_text(
            MANAGE_NEW_RELIGION
        )
        # additional_remarks is drawn as a badge beside the name, not as a field.
        expect(
            page.get_by_text(as_pattern(re.escape(MANAGE_DESCRIPTION))).first
        ).to_be_visible(timeout=20_000)
        # …and the correction touched only what it was asked to.
        expect(staff.detail_value(MANAGE_INFO_FIRST_NAME)).to_have_text(first_name)
        expect(staff.detail_value(MANAGE_INFO_OTHER_NAMES)).to_have_text(last_name)
        expect(staff.detail_value(MANAGE_INFO_STAFF_ID)).to_have_text(stored_staff_id)
        staff.expect_no_load_failure()

        # Finally, straight off the record the backend stores — the screen renders
        # from the same GET, so this is what proves the PUT landed rather than the
        # profile having been repainted from local state.
        after = _manage_stored(api, ctx, staff_id)
        changed = {
            "job_title": after["job_title"],
            "field_of_study": after["field_of_study"],
            "additional_remarks": after["additional_remarks"],
            "user.residential_address": after["user.residential_address"],
            "user.primary_phone": after["user.primary_phone"],
            "user.religion": after["user.religion"],
        }
        expected = {
            "job_title": MANAGE_NEW_JOB_TITLE,
            "field_of_study": MANAGE_NEW_FIELD_OF_STUDY,
            "additional_remarks": MANAGE_DESCRIPTION,
            "user.residential_address": MANAGE_NEW_ADDRESS,
            "user.primary_phone": MANAGE_NEW_PHONE,
            "user.religion": MANAGE_NEW_RELIGION,
        }
        assert changed == expected, (
            f"teacher {staff_id} is stored as {changed}, not {expected}. The edit "
            f"wizard's PUT /teacher/{{id}} sends job_title, employment_type, "
            f"admission_date, field_of_study, highest_degree_earned, "
            f"additional_remarks and a user block; a field missing here is one the "
            f"screen displayed but the backend never took."
        )

        untouched = ("staff_id", "employment_type", "admission_date",
                     "user.email", "user.first_name", "user.other_names",
                     "user.location", "user.nationality")
        assert {key: after[key] for key in untouched} == {
            key: before[key] for key in untouched
        }, (
            f"the edit changed fields it was never asked to. Before: "
            f"{ {key: before[key] for key in untouched} }; after: "
            f"{ {key: after[key] for key in untouched} }"
        )


def _manage_stored(api: BackendAPI, ctx: SchoolContext, staff_id: int) -> dict[str, object]:
    """The record ``GET /teacher/{id}`` holds, flattened for comparison."""
    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    res = api.get(f"/teacher/{staff_id}", token=token)
    assert res.status_code == 200, (
        f"GET /teacher/{staff_id} answered {res.status_code} for the SchoolAdmin "
        f"of {ctx.school_name!r}, whose pack licenses {STAFF_MODULE!r} — the record "
        f"the profile screen renders from is unreadable. Body: {res.text[:300]}"
    )
    body = res.json()
    user = body.get("user") or {}
    return {
        "staff_id": body.get("staff_id"),
        "job_title": body.get("job_title"),
        "employment_type": body.get("employment_type"),
        "admission_date": body.get("admission_date"),
        "field_of_study": body.get("field_of_study"),
        "highest_degree_earned": body.get("highest_degree_earned"),
        "additional_remarks": body.get("additional_remarks"),
        "user.email": user.get("email"),
        "user.first_name": user.get("first_name"),
        "user.other_names": user.get("other_names"),
        "user.primary_phone": user.get("primary_phone"),
        "user.residential_address": user.get("residential_address"),
        "user.religion": user.get("religion"),
        "user.location": user.get("location"),
        "user.nationality": user.get("nationality"),
    }


def _manage_letters(value: str) -> str:
    """Name-ish inputs silently drop anything outside /^[A-Za-z\\s]*$/."""
    return re.sub(r"[^A-Za-z\s]", "", value).strip()


def _manage_digits(value: str) -> str:
    """The phone inputs strip non-digits and cap at 10 characters."""
    return re.sub(r"\D", "", value)[:10]


# ══════════════════════ people.staff.always_licensed ═════════════════════════
#
# Mandatory path: the SchoolAdmin of the ``minimal`` school
#     ``test_staff_is_reachable_on_the_minimal_pack``. There is no denial unit
#     for this module and there cannot be one: ``staff`` sits in the ``people``
#     group of ``services/feature_pack_service.SYSTEM_MODULE_GROUPS``, and the
#     SuperAdmin's only pack builder (``src/app/module/feature_flag/create/
#     page.tsx`` and its ``edit/[id]`` twin) declares
#     ``BASIC_GROUPS = ["people", "governance"]``, rendering every module of
#     those two groups locked, pre-selected and exempt from "Clear All" — only
#     ``guardians`` and ``families`` stay optional inside them. That the people
#     and governance groups are core and always on is intended product
#     behaviour, so this unit asserts the opposite of a denial — the module is
#     licensed, offered and answering on the most restricted pack the product
#     can build — and deliberately adds no gate of any kind.
#
# Why the licence is proved to bite somewhere else first
#     "The register loaded" only says something about licensing if the licence
#     is enforced at all. So a module the same pack omits and that lives
#     *outside* the locked basic set (``fees``) is asked for over the API and
#     has to come back 403 "Feature not available in your plan" — the control.
#     Without it, a backend that had stopped checking feature packs entirely
#     would pass this unit.
#
# Why the register's own fetch is read off the wire
#     The table renders "No teaching staff found" whether ``GET /teacher/``
#     answered empty, was skipped for want of a branch, or is still in flight,
#     so the test waits for the browser's own ``GET /teacher/?…`` to come back
#     200 — the route declared ``Depends(has_permission("read", "staff"))`` —
#     and compares its total with the same route called directly.
#
# Read-only: nobody is hired here. Driving the wizard belongs to
# ``people.staff.manage.school_admin`` above; "Add Teaching Staff" only has to
# be *offered*, which is what separates a licensed module from a read-only husk.

MANDATORY_SCENARIO = "minimal"
STAFF_ROUTE = "staff"

# ── what makes the module mandatory (feature_flag/create/page.tsx) ───────────
MANDATORY_BASIC_GROUPS = ("people", "governance")
MANDATORY_OPTIONAL_BASIC_MODULES = frozenset({"guardians", "families"})
MANDATORY_PEOPLE_GROUP = "people"

# ── the sidebar (components/common/SideNavigation/nav-config.tsx) ────────────
MANDATORY_NAV_SECTION_PEOPLE = re.compile(r"^\s*People Module\s*$", re.I)
MANDATORY_NAV_STAFF = re.compile(r"^\s*Staff\s*$", re.I)

# ── what the screen renders (src/app/module/staff/page.tsx) ──────────────────
MANDATORY_STAT_TOTAL = re.compile(r"^\s*Total Staffs\s*$", re.I)
MANDATORY_STAT_TEACHING = re.compile(r"^\s*Teaching Staffs\s*$", re.I)
MANDATORY_STAT_NON_TEACHING = re.compile(r"^\s*Non-teaching Staffs\s*$", re.I)
MANDATORY_STATS_LOAD_FAILURE = re.compile(r"Failed to load staff statistics", re.I)

# ── the module's own API surface (api/routes/teacher.py) ─────────────────────
MANDATORY_TEACHER_PATH = "/teacher/"
MANDATORY_TEACHER_KEYS = ("results", "total_count")
# The browser's own copy of that call. The "?" keeps this predicate off
# /statistics/staff and off /teacher/{id}.
MANDATORY_TEACHER_URL_MARKER = "/teacher/?"

# A module the same pack omits, outside the locked basic set, that the backend
# really does gate — the control proving the licence is enforced, not decorative.
MANDATORY_ENFORCED_UNLICENSED_MODULE = "fees"
MANDATORY_ENFORCED_UNLICENSED_PATH = "/fees/1"
MANDATORY_FEATURE_PACK_403 = re.compile(r"feature not available in your plan", re.I)

# The cookie every frontend gate derives its answer from.
MANDATORY_MODULES_COOKIE = "schoolModules"
MANDATORY_DENIAL_URL = re.compile(r"/auth/no-access|/unauthorized")
MANDATORY_SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# Both mount effects wait on the branch store rehydrating out of (encrypted)
# localStorage before they fire at all, so the first call is given room.
MANDATORY_MOUNT_FETCH_TIMEOUT_MS = 60_000


@pytest.mark.school_admin
@pytest.mark.scenario(MANDATORY_SCENARIO)
def test_staff_is_reachable_on_the_minimal_pack(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """The floor case still has its employee register: licensed, offered, answering.

    Ledger unit ``people.staff.always_licensed``. See the section header: the
    pack builder locks the whole ``people`` group into every pack, so there is
    no school this module can be sold away from, and this unit asserts that on
    the most restricted school the product can actually produce.
    """
    ctx = provisioned_school
    requested = set(ctx.feature_modules)
    staff = StaffPage(page, frontend_base_url)

    assert ctx.branches, (
        f"provisioning left {ctx.school_name!r} with no branch. Both of the "
        f"register's mount effects return early for a SchoolAdmin while the "
        f"branch store is empty, GET /teacher/ answers 400 BRANCH_ID_REQUIRED "
        f"to a SchoolAdmin who names none, and the People Module sidebar "
        f"section is branchOnly — so there would be nothing to reach. Phase B "
        f"creates one for every scenario."
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
    assert STAFF_MODULE in groups.get(MANDATORY_PEOPLE_GROUP, []), (
        f"{STAFF_MODULE!r} is no longer in the {MANDATORY_PEOPLE_GROUP!r} group "
        f"of the backend catalogue (services/feature_pack_service.py). The "
        f"create-pack form locks a module in because of the group it belongs "
        f"to, so that membership is the whole reason this module is mandatory. "
        f"Groups: { {k: sorted(v) for k, v in groups.items()} }"
    )
    locked = {
        module
        for name in MANDATORY_BASIC_GROUPS
        for module in groups.get(name, [])
        if module not in MANDATORY_OPTIONAL_BASIC_MODULES
    }
    assert STAFF_MODULE in locked, (
        f"{STAFF_MODULE!r} is no longer one of the modules the SuperAdmin's "
        f"create-pack form forces into every pack, so a school can now be sold "
        f"without its employee register and this unit's premise is gone. That "
        f"is a product change, not a test failure to paper over — rewrite this "
        f"unit as a real denial test instead. Locked: {sorted(locked)}"
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
        f"{ctx.school_name!r} has no feature pack assigned at all, so this is "
        f"not the {MANDATORY_SCENARIO!r} floor and nothing below is about "
        f"licensing. Provisioning phase A assigns one — check that it did."
    )
    licensed = {str(m) for m in (body.get("modules") or [])}
    assert licensed == requested | locked, (
        f"{ctx.school_name!r}'s licence is not 'what the {MANDATORY_SCENARIO!r} "
        f"pack requested plus the locked basic modules'. Requested "
        f"{sorted(requested)}; locked {sorted(locked)}; got {sorted(licensed)}. "
        f"Unexpectedly granted: {sorted(licensed - (requested | locked))}; "
        f"expected but missing: {sorted((requested | locked) - licensed)}."
    )
    assert STAFF_MODULE in licensed, (
        f"{ctx.school_name!r} — the most restricted pack this product can "
        f"build — is not licensed for {STAFF_MODULE!r}. The people group is "
        f"core and always on by design, so a school has just lost the register "
        f"of who it employs. Licensed: {sorted(licensed)}"
    )

    # ── 2. The licence is enforced for this user, on a module outside the lock ─
    assert MANDATORY_ENFORCED_UNLICENSED_MODULE not in licensed, (
        f"{ctx.school_name!r} is now licensed for "
        f"{MANDATORY_ENFORCED_UNLICENSED_MODULE!r}, so it can no longer serve as "
        f"the control that the feature gate bites for this user. Pick another "
        f"module the {MANDATORY_SCENARIO!r} pack omits, that is outside the "
        f"locked basic set, and that a backend route gates on."
    )
    assert MANDATORY_ENFORCED_UNLICENSED_MODULE in _mandatory_role_modules(
        api, MANDATORY_SCHOOL_ADMIN_ROLE
    ), (
        f"the seeded {MANDATORY_SCHOOL_ADMIN_ROLE} role no longer holds a "
        f"{MANDATORY_ENFORCED_UNLICENSED_MODULE!r} permission, so the 403 below "
        f"would come from the permission half of has_permission and prove "
        f"nothing about feature packs. Re-point this control."
    )
    gated = api.get(MANDATORY_ENFORCED_UNLICENSED_PATH, token=token)
    assert gated.status_code == 403, (
        f"{MANDATORY_ENFORCED_UNLICENSED_PATH} answered {gated.status_code} for "
        f"a SchoolAdmin whose school is not licensed for "
        f"{MANDATORY_ENFORCED_UNLICENSED_MODULE!r}; the feature-pack gate in "
        f"utils/permissions.has_permission should have refused it, and until it "
        f"does, 'the staff register is reachable' says nothing. "
        f"Body: {gated.text[:300]}"
    )
    assert MANDATORY_FEATURE_PACK_403.search(gated.text), (
        f"{MANDATORY_ENFORCED_UNLICENSED_PATH} was refused, but not by the "
        f"feature pack — the detail should be 'Feature not available in your "
        f"plan'. Body: {gated.text[:300]}"
    )

    # ── 3. What the register is obliged to show, read from its own route ──────
    listing = api.get(
        f"{MANDATORY_TEACHER_PATH}?skip=0&limit=25&branch_id={branch_id}",
        token=token,
    )
    assert listing.status_code == 200, (
        f"GET {MANDATORY_TEACHER_PATH} answered {listing.status_code} for the "
        f"SchoolAdmin of {ctx.school_name!r}, whose pack licenses "
        f"{STAFF_MODULE!r}. The route is "
        f"Depends(has_permission('read', {STAFF_MODULE!r})), so a 403 carrying "
        f"'Feature not available in your plan' would mean the people group "
        f"stopped being locked into every pack; anything else is the route "
        f"itself breaking. Body: {listing.text[:300]}"
    )
    assert not MANDATORY_FEATURE_PACK_403.search(listing.text), (
        f"GET {MANDATORY_TEACHER_PATH} returned 200 but its body reads like the "
        f"feature-pack refusal: {listing.text[:300]}"
    )
    _expect_mandatory_teacher_page(listing.json())

    # ── 4. Offered: the licence the browser session is given ──────────────────
    login_as(page, frontend_base_url, ctx.school_admin)

    cookie_modules = _mandatory_modules_cookie(page)
    assert cookie_modules is not None, (
        f"the {MANDATORY_MODULES_COOKIE!r} cookie was never written for this "
        f"session. Every frontend gate derives its answer from it, so without "
        f"it the walk below says nothing about what this school is licensed "
        f"for. Both src/app/auth/login/page.tsx and SideNavigation set it."
    )
    assert set(cookie_modules) == licensed, (
        f"the browser session claims {sorted(cookie_modules)} as its licensed "
        f"modules, out of step with /school_profile/{ctx.school_id}/features, "
        f"which reports {sorted(licensed)}"
    )
    assert STAFF_MODULE in cookie_modules, (
        f"{STAFF_MODULE!r} is missing from this session's "
        f"{MANDATORY_MODULES_COOKIE!r} cookie, so src/middleware.ts would gate "
        f"/module/{STAFF_ROUTE} for any role without the SchoolAdmin carve-out "
        f"— the register is not reachable on the {MANDATORY_SCENARIO!r} pack "
        f"for anybody else"
    )

    # Mandatory before the screen is asked for, not scene-setting: a SchoolAdmin
    # belongs to no branch, and both the branchOnly "People Module" nav section
    # and the register's own fetches wait on the branch store that only this
    # click fills. Its handler navigates away as a side effect — to
    # /module/community, and on to /auth/no-access when (as here) the pack has
    # no community module — which select_branch tolerates by design: the store
    # is written before the push, and the register is reached by route after.
    BranchesPage(page, frontend_base_url).select_branch(branch_name)

    # ── 5. Working: the route loads and its own mount fetch answers ───────────
    with page.expect_response(
        _ok_teacher_list, timeout=MANDATORY_MOUNT_FETCH_TIMEOUT_MS
    ) as listing_call:
        staff.open()

    assert not MANDATORY_DENIAL_URL.search(page.url), (
        f"the SchoolAdmin of {ctx.school_name!r} was redirected to {page.url!r} "
        f"asking for a module their pack licenses. The people group is core and "
        f"always on by design — a denial here is a regression, not a gate to keep."
    )
    assert page.url.rstrip("/").endswith(f"/module/{STAFF_ROUTE}"), (
        f"expected to still be on /module/{STAFF_ROUTE}, but the app moved to "
        f"{page.url!r}"
    )

    expect(page.get_by_role("heading", name=PAGE_HEADING).first).to_be_visible()
    staff.expect_no_load_failure()
    expect(page.get_by_text(as_pattern(MANDATORY_STATS_LOAD_FAILURE))).to_have_count(0)
    for label in (MANDATORY_STAT_TOTAL, MANDATORY_STAT_TEACHING,
                  MANDATORY_STAT_NON_TEACHING):
        expect(page.get_by_text(label).first).to_be_visible(timeout=20_000)

    staff.show_teaching()
    staff.expect_column_headers()
    expect(page.get_by_placeholder(SEARCH_FIELD).first).to_be_visible(timeout=20_000)

    # The write control the module exists for, offered rather than driven.
    expect(
        page.get_by_role("button", name=as_pattern(ADD_TEACHING_TRIGGER)).first
    ).to_be_visible(timeout=20_000)

    # What the browser was actually served, in the shape the page destructures.
    _expect_mandatory_teacher_page(listing_call.value.json())

    # ── 6. Offered in the sidebar, now that a branch is selected ──────────────
    expect(page.get_by_text(MANDATORY_NAV_SECTION_PEOPLE).first).to_be_visible(
        timeout=20_000
    )
    nav = page.get_by_role("navigation")
    expect(
        nav.get_by_role("link", name=as_pattern(MANDATORY_NAV_STAFF)).first
    ).to_be_visible(timeout=20_000)
    expect(nav.locator(f'a[href="/module/{STAFF_ROUTE}"]').first).to_be_visible()


def _ok_teacher_list(response) -> bool:
    """Predicate for ``page.expect_response``: the register's list call, 200.

    ``fetchStaffData`` fires again on every page, page-size, tab or search
    change, and ``getBranchIdParam`` only appends ``branch_id`` once the
    persisted branch store has rehydrated — so a first attempt can legitimately
    be answered 400 BRANCH_ID_REQUIRED and then succeed. Waiting for the 200
    tolerates that, while a route that is genuinely gated never produces one.
    """
    return MANDATORY_TEACHER_URL_MARKER in response.url and response.status == 200


def _expect_mandatory_teacher_page(payload: Any) -> None:
    """``TeacherResponsePagination`` as ``fetchStaffData`` destructures it."""
    assert isinstance(payload, dict), (
        f"GET {MANDATORY_TEACHER_PATH} answered {type(payload).__name__}, not "
        f"the paginated object the register reads: {payload!r}"
    )
    for key in MANDATORY_TEACHER_KEYS:
        assert key in payload, (
            f"GET {MANDATORY_TEACHER_PATH} is missing the {key!r} key the "
            f"register reads (api/api_models — TeacherResponsePagination) — got "
            f"keys {sorted(payload)}"
        )
    assert isinstance(payload.get("results"), list), (
        f"GET {MANDATORY_TEACHER_PATH} answered a `results` of "
        f"{type(payload.get('results')).__name__}, but the table maps over it"
    )


def _mandatory_role_modules(api: BackendAPI, role_name: str) -> set[str]:
    """Every module the named seeded role holds a permission on."""
    role = api.get(f"/roles/{api.role_id_for(role_name)}")
    assert role.status_code == 200, (
        f"could not read the {role_name} role — got {role.status_code}: "
        f"{role.text[:300]}"
    )
    return {str(p.get("module")) for p in role.json().get("permissions", [])}


def _mandatory_modules_cookie(page: Page) -> list[str] | None:
    """The ``schoolModules`` cookie as a list, or ``None`` if it is unreadable."""
    for cookie in page.context.cookies():
        if cookie.get("name") != MANDATORY_MODULES_COOKIE:
            continue
        try:
            parsed = json.loads(unquote(str(cookie.get("value") or "")))
        except json.JSONDecodeError:
            return None
        return [str(m) for m in parsed] if isinstance(parsed, list) else None
    return None
