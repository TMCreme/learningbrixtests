"""The full school-provisioning walkthrough, driven entirely through the UI.

``provision_school`` composes the page objects into the four phases of
``docs/plan.md`` §7 and returns a :class:`SchoolContext` describing everything it
created — school id, one login per role, branches, classes, subjects and the
active academic year/term. Every module test then runs against that context.

Credentials
    Every user this app creates gets a server-generated password that is only
    delivered by email, so each create is wrapped in
    ``tests.fixtures.credentials.capture_credentials``, which reads the real
    password out of the backend's QA mode. If a capture fails with "QA mode is
    not enabled", enable it (``touch <backend>/.qa_mode_enabled``) rather than
    guessing a password — see ``state/backend_patches.md``.

Feature gating
    A scenario's feature pack decides which modules exist at all, so each step
    is skipped (and logged at INFO) when its module is off. A skipped step
    leaves its ``SchoolContext`` field ``None``/empty; the module tests read
    ``feature_modules`` and take their negative path instead.

Prerequisite seeded over the API
    The Add Class dialog keeps "Save Class" disabled until a fee group is
    picked, and a fresh branch has none. Building one through the UI means
    driving the whole fees module first (a fee, then a group of fees) — a
    different module's walkthrough, not the academic structure phase D exists
    to prove. ``_seed_fee_group`` therefore creates it over the API between
    phases C and D, the same setup-only use of ``api`` as ``_resolve_school_id``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from playwright.sync_api import Page

from config.scenarios import Scenario
from config.settings import Settings
from tests.fixtures.api_client import BackendAPI
from tests.fixtures.api_client import Credentials as BaseCredentials
from tests.fixtures.credentials import CapturedUser, capture_credentials
from tests.fixtures.data_factories import PersonData, SchoolSeed, make_person, run_tag
from tests.pages.academics.classes import ClassesPage
from tests.pages.academics.subjects import SubjectsPage
from tests.pages.login import login_as, logout
from tests.pages.people.guardians import GuardiansPage
from tests.pages.people.staff import StaffPage
from tests.pages.people.students import BLOOD_TYPE_PLACEHOLDER, StudentsPage
from tests.pages.school_admin.academic_year import AcademicYearTermPage
from tests.pages.school_admin.access_roles import AccessRolesPage
from tests.pages.school_admin.branches import BranchesPage
from tests.pages.school_admin.config import ConfigPage
from tests.pages.super_admin.feature_flag import FeatureFlagPage
from tests.pages.super_admin.schools import SchoolsPage

log = structlog.get_logger(__name__)

# ── module keys these steps depend on (config/module_catalog.py) ─────────────
CONFIG_MODULE = "school_configuration"
DASHBOARD_MODULE = "school_admin_dashboard"
ACADEMIC_YEAR_MODULE = "academic_year_and_term"
STAFF_MODULE = "staff"
GUARDIANS_MODULE = "guardians"
STUDENTS_MODULE = "students"
ACCESS_ROLES_MODULE = "access_roles"
CLASSES_MODULE = "classes_and_timetables"
SUBJECTS_MODULE = "subjects"

# ── what provisioning creates ────────────────────────────────────────────────
BRANCH_NAME = "Main Campus"
BRANCH_ADDRESS = "Main Campus Road"
BRANCH_PHONE = "0302000000"

ACADEMIC_YEAR_NAME = "2026/2027"
ACADEMIC_YEAR_START = "2026-09-01"
ACADEMIC_YEAR_END = "2027-07-31"
TERM_NAME = "Term 1"
TERM_START = "2026-09-01"
TERM_END = "2026-12-15"

CLASS_NAME = "Grade 6"
SUBJECT_NAME = "Mathematics"

# Seeded over the API so the Add Class dialog has a fee group to offer.
FEE_NAME = "TEST Tuition"
FEE_AMOUNT = 100
FEE_GROUP_NAME = "TEST Standard Fees"

CURRENCY = "GHS"
NOTIFICATION_PREFERENCE = "email"

TEACHER_ROLE = "Teacher"
ACCOUNTANT_ROLE = "Accountant"
ADMIN_ROLE = "Admin"
SCHOOL_ADMIN_ROLE = "SchoolAdmin"
BRANCH_ADMIN_ROLE = "Admin"
GUARDIAN_ROLE = "Guardian"
STUDENT_ROLE = "Student"
SUPER_ADMIN_ROLE = "SuperAdmin"

# Every wizard stars fields the flow has no opinion about; these keep each
# create a one-liner. The dates are ISO because that is what the page objects
# take (they convert to each picker's own display format).
ADULT_DATE_OF_BIRTH = "1990-01-01"
STUDENT_DATE_OF_BIRTH = "2014-05-12"
DEFAULT_GENDER = "Male"
DEFAULT_MARITAL_STATUS = "Single"
DEFAULT_DIALECT = "Twi"
DEFAULT_RELIGION = "Christianity"
DEFAULT_LOCATION = "Accra"
DEFAULT_EMPLOYMENT_TYPE = "Full-time"
DEFAULT_DEGREE = "Bachelor's Degree"
DEFAULT_FIELD_OF_STUDY = "Mathematics"
TEACHER_JOB_TITLE = "Class Teacher"
ACCOUNTANT_JOB_TITLE = "Accountant"
STUDENT_BLOOD_TYPE = "O+"


class ProvisioningError(RuntimeError):
    """A provisioning phase failed. ``phase`` says which one, so a test report
    can point at "B" rather than at a selector timeout with no context."""

    def __init__(self, *, phase: str, original: BaseException) -> None:
        self.phase = phase
        self.original = original
        super().__init__(
            f"School provisioning failed in phase {phase}: "
            f"{type(original).__name__}: {original}"
        )


@dataclass
class Credentials(BaseCredentials):
    """A working login plus the display fields needed to find the user in the UI.

    Subclasses the API client's ``Credentials`` so it can be passed straight to
    ``login_as`` and to anything typed against the base class.
    """

    first_name: str = ""
    last_name: str = ""
    role: str = ""

    @property
    def full_name(self) -> str:
        """How the app renders this user — ``first_name other_names``."""
        return f"{self.first_name} {self.last_name}".strip()


@dataclass
class SchoolContext:
    """Everything one provisioned school exposes to the tests.

    Fields for steps a scenario's feature pack switched off stay ``None`` (or
    empty), which is the signal to take the module's negative path.
    """

    scenario_id: str
    school_id: int
    school_name: str
    feature_modules: frozenset[str]
    super_admin: Credentials
    school_admin: Credentials
    branch_admin: Credentials | None = None
    teacher: Credentials | None = None
    accountant: Credentials | None = None
    generic_admin: Credentials | None = None
    student: Credentials | None = None
    guardian: Credentials | None = None
    branches: list[dict[str, Any]] = field(default_factory=list)
    classes: list[dict[str, Any]] = field(default_factory=list)
    subjects: list[dict[str, Any]] = field(default_factory=list)
    academic_year: str = ""
    current_term: str = ""


def provision_school(
    page: Page,
    settings: Settings,
    scenario: Scenario,
    super_admin_creds: BaseCredentials,
    api: BackendAPI,
) -> SchoolContext:
    """Drive the full multi-step onboarding through the UI.

    Returns the populated :class:`SchoolContext`. Raises
    :class:`ProvisioningError` carrying the phase name ("A".."D") on any step
    that fails, so the test can report which phase broke.

    ``api`` is used for one setup-only read: recovering the school id when the
    create response could not be parsed (teardown needs it).
    """
    log.info(
        "provisioning.start",
        scenario=scenario.id,
        school=scenario.school_name,
        modules=len(scenario.modules),
    )

    try:
        phase_a = _phase_a_super_admin_setup(page, settings, scenario, super_admin_creds)
    except Exception as exc:
        raise ProvisioningError(phase="A", original=exc) from exc

    school_name: str = phase_a["school_name"]
    school_id: int = phase_a["school_id"]
    school_admin: Credentials = phase_a["school_admin"]
    if school_id < 0:
        school_id = _resolve_school_id(api, scenario, super_admin_creds, school_name)

    try:
        phase_b = _phase_b_school_admin_setup(page, settings, scenario, school_admin)
    except Exception as exc:
        raise ProvisioningError(phase="B", original=exc) from exc

    try:
        branches = phase_b.get("branches") or []
        phase_c = _phase_c_create_users(
            page, settings, scenario, school_admin,
            branch_name=branches[0]["name"] if branches else None,
        )
    except Exception as exc:
        raise ProvisioningError(phase="C", original=exc) from exc

    teacher: Credentials | None = phase_c["teacher"]
    student: Credentials | None = phase_c["student"]

    if _enabled(scenario, "D", "classes", CLASSES_MODULE):
        _seed_fee_group(
            api,
            school_admin,
            school_id=school_id,
            branch_id=int((branches[0] or {}).get("id") or -1) if branches else -1,
        )

    try:
        phase_d = _phase_d_academic_structure(
            page,
            settings,
            scenario,
            school_admin,
            teacher.email if teacher else "",
            student.full_name if student else "",
            teacher_name=teacher.full_name if teacher else "",
            branch_name=branches[0]["name"] if branches else None,
        )
    except Exception as exc:
        raise ProvisioningError(phase="D", original=exc) from exc

    context = SchoolContext(
        scenario_id=scenario.id,
        school_id=school_id,
        school_name=school_name,
        feature_modules=scenario.modules,
        super_admin=_promote(super_admin_creds, role=SUPER_ADMIN_ROLE),
        school_admin=school_admin,
        branch_admin=phase_b["branch_admin"],
        teacher=teacher,
        accountant=phase_c["accountant"],
        generic_admin=phase_c["generic_admin"],
        student=student,
        guardian=phase_c["guardian"],
        branches=phase_b["branches"],
        classes=phase_d["classes"],
        subjects=phase_d["subjects"],
        academic_year=phase_b["academic_year"],
        current_term=phase_b["current_term"],
    )
    log.info(
        "provisioning.done",
        scenario=scenario.id,
        school=school_name,
        school_id=school_id,
        branches=len(context.branches),
        classes=len(context.classes),
        subjects=len(context.subjects),
    )
    return context


# ───────────────────────────── phase A ───────────────────────────────────────


def _phase_a_super_admin_setup(
    page: Page,
    settings: Settings,
    scenario: Scenario,
    super_admin_creds: BaseCredentials,
) -> dict[str, Any]:
    """As SuperAdmin: create the school, build its feature pack, assign it.

    Both names carry the per-run tag so parallel agents never collide on them
    (see the header of ``config/feature_scenarios.yaml``).
    """
    base_url = settings.frontend_base_url
    tag = run_tag()
    school_name = f"{scenario.school_name} {tag}"
    pack_name = f"{scenario.feature_pack_name} {tag}"
    seed = SchoolSeed.for_scenario(scenario.id, school_name)

    log.info("provisioning.phase_a.start", scenario=scenario.id, school=school_name)
    login_as(page, base_url, super_admin_creds)

    schools = SchoolsPage(page, base_url).open()
    created: dict[str, int] = {}

    def _create_school() -> None:
        created["school_id"] = schools.create_school(
            name=school_name,
            admin_email=seed.admin_email,
            admin_first_name=seed.admin_first_name,
            admin_last_name=seed.admin_other_names,
            address=seed.address,
            phone=seed.phone,
            currency=CURRENCY,
            notification_preference=NOTIFICATION_PREFERENCE,
            school_email=seed.email,
        )

    captured = capture_credentials(
        page,
        _create_school,
        url_substring="/school_profile/",
        email=seed.admin_email,
        # The create is the only 201 on this path; the list GET is a 200.
        statuses=(201,),
    )
    # No user_id: the captured body is the school profile, so its "id" is the
    # school's, not the admin's.
    school_admin = Credentials(
        email=captured.email,
        password=captured.password,
        role_name=SCHOOL_ADMIN_ROLE,
        first_name=seed.admin_first_name,
        last_name=seed.admin_other_names,
        role=SCHOOL_ADMIN_ROLE,
    )

    school_id = created.get("school_id", -1)
    if school_id < 0:
        body_id = captured.body.get("id")
        school_id = body_id if isinstance(body_id, int) else -1
    if school_id < 0:
        log.warning(
            "provisioning.phase_a.school_id_unknown",
            scenario=scenario.id,
            school=school_name,
        )

    flags = FeatureFlagPage(page, base_url).open()
    flags.create_pack(
        name=pack_name,
        description=f"Playwright scenario {scenario.id}",
        modules=sorted(scenario.modules),
    )
    flags.assign_pack_to_school(school_name=school_name, pack_name=pack_name)

    log.info(
        "provisioning.phase_a.done",
        scenario=scenario.id,
        school=school_name,
        school_id=school_id,
        feature_pack=pack_name,
        school_admin=school_admin.email,
    )
    _logout(page, base_url)

    return {
        "school_id": school_id,
        "school_name": school_name,
        "feature_pack_name": pack_name,
        "school_admin": school_admin,
    }


# ───────────────────────────── phase B ───────────────────────────────────────


def _phase_b_school_admin_setup(
    page: Page,
    settings: Settings,
    scenario: Scenario,
    school_admin_creds: BaseCredentials,
) -> dict[str, Any]:
    """As SchoolAdmin: configuration, the first branch and its admin, year/term.

    The branch admin is created from the branches screen ("Create Admin" →
    ``POST /users/add_admin/{branch_id}``), which is the only screen that scopes
    a user to a branch — ``/module/access_roles`` never creates one.
    """
    base_url = settings.frontend_base_url
    log.info("provisioning.phase_b.start", scenario=scenario.id)
    login_as(page, base_url, school_admin_creds)

    branches: list[dict[str, Any]] = []
    branch_admin: Credentials | None = None
    academic_year = ""
    current_term = ""

    if _enabled(scenario, "B", "school_configuration", CONFIG_MODULE):
        config = ConfigPage(page, base_url).open()
        config.set_currency(CURRENCY)
        config.set_notification_preference(NOTIFICATION_PREFERENCE)
        config.save()

    # Deliberately NOT gated on DASHBOARD_MODULE. A branch is not an optional
    # feature — it is the unit every SchoolAdmin request is scoped to. The
    # backend answers 400 BRANCH_ID_REQUIRED (core/exceptions.branch_id_required)
    # for a SchoolAdmin whose request carries no branch_id, and the frontend can
    # only supply one from the store that this page's "View" button fills. So a
    # school provisioned without a branch cannot create staff, students or
    # guardians at all, and phase C dies on its first create.
    #
    # Reaching the page is never gated either: "school_admin_dashboard" is a
    # CORE_MODULE in smsfrontend/src/middleware.ts, and both useModuleGuard and
    # usePermissionGuard exempt a SchoolAdmin outright. The scenario that omits
    # the module (academics_only) is asserting that its *sidebar entry* is
    # hidden — which is a module test's job, not a reason to leave the school
    # without a branch.
    branches_page = BranchesPage(page, base_url).open()
    branch_id = branches_page.create_branch(
        name=BRANCH_NAME, address=BRANCH_ADDRESS, phone=BRANCH_PHONE
    )
    branches.append({"id": branch_id, "name": BRANCH_NAME})

    person = _person("branchadmin", scenario)
    captured = capture_credentials(
        page,
        lambda: branches_page.create_branch_admin(
            branch_name=BRANCH_NAME,
            email=person.email,
            first_name=person.first_name,
            last_name=person.last_name,
        ),
        url_substring="/add_admin/",
        email=person.email,
    )
    branch_admin = _credentials(captured, person, role=BRANCH_ADMIN_ROLE)

    if _enabled(scenario, "B", "academic_year_and_term", ACADEMIC_YEAR_MODULE):
        academics = AcademicYearTermPage(page, base_url).open()
        academics.create_year(
            name=ACADEMIC_YEAR_NAME,
            start_date=ACADEMIC_YEAR_START,
            end_date=ACADEMIC_YEAR_END,
            set_active=True,
        )
        academics.create_term(
            year_name=ACADEMIC_YEAR_NAME,
            term_name=TERM_NAME,
            start_date=TERM_START,
            end_date=TERM_END,
            set_active=True,
        )
        academic_year, current_term = ACADEMIC_YEAR_NAME, TERM_NAME

    log.info(
        "provisioning.phase_b.done",
        scenario=scenario.id,
        branches=[b["name"] for b in branches],
        branch_admin=branch_admin.email if branch_admin else None,
        academic_year=academic_year,
        current_term=current_term,
    )
    _logout(page, base_url)

    return {
        "branch_admin": branch_admin,
        "branches": branches,
        "academic_year": academic_year,
        "current_term": current_term,
    }


# ───────────────────────────── phase C ───────────────────────────────────────


def _phase_c_create_users(
    page: Page,
    settings: Settings,
    scenario: Scenario,
    school_admin_creds: BaseCredentials,
    branch_name: str | None = None,
) -> dict[str, Any]:
    """As SchoolAdmin: one user per role — teacher, accountant, guardian,
    student, generic admin.

    The guardian is created before the student because the admission wizard's
    guardian picker only lists guardians that already exist, and that picker is
    the only working way to link the two (see ``GuardiansPage.link_ward``).
    """
    base_url = settings.frontend_base_url
    log.info("provisioning.phase_c.start", scenario=scenario.id)
    login_as(page, base_url, school_admin_creds)

    # Mandatory before creating anyone: a SchoolAdmin has no branch of their
    # own, so the frontend reads school_branch_id from a store that only the
    # branch row's "View" button populates. Skip this and every create posts
    # school_branch_id: 0 and the backend answers 404 "The Branch does not
    # exist".
    if branch_name:
        BranchesPage(page, base_url).select_branch(branch_name)
        log.info("provisioning.phase_c.branch_selected", branch=branch_name)

    teacher: Credentials | None = None
    accountant: Credentials | None = None
    guardian: Credentials | None = None
    student: Credentials | None = None
    generic_admin: Credentials | None = None

    if _enabled(scenario, "C", "staff", STAFF_MODULE):
        staff = StaffPage(page, base_url).open()
        teacher = _create_teacher(page, staff, scenario)
        staff.open()
        accountant = _create_accountant(page, staff, scenario)

    if _enabled(scenario, "C", "guardians", GUARDIANS_MODULE):
        guardians = GuardiansPage(page, base_url).open()
        guardian = _create_guardian(page, guardians, scenario)

    if _enabled(scenario, "C", "students", STUDENTS_MODULE):
        if guardian is None:
            log.info(
                "provisioning.step.skipped",
                scenario=scenario.id,
                phase="C",
                step="students",
                reason="the admission wizard requires an existing guardian",
            )
        else:
            students = _StudentAdmission(page, base_url)
            students.open()
            student = _admit_student(page, students, scenario, guardian.full_name)

    if _enabled(scenario, "C", "generic_admin", ACCESS_ROLES_MODULE, DASHBOARD_MODULE):
        access_roles = AccessRolesPage(page, base_url)
        generic_admin = _create_generic_admin(page, access_roles, scenario)

    log.info(
        "provisioning.phase_c.done",
        scenario=scenario.id,
        teacher=teacher.email if teacher else None,
        accountant=accountant.email if accountant else None,
        guardian=guardian.email if guardian else None,
        student=student.email if student else None,
        generic_admin=generic_admin.email if generic_admin else None,
    )
    _logout(page, base_url)

    return {
        "teacher": teacher,
        "accountant": accountant,
        "guardian": guardian,
        "student": student,
        "generic_admin": generic_admin,
    }


def _create_teacher(page: Page, staff: StaffPage, scenario: Scenario) -> Credentials:
    person = _person("teacher", scenario)
    captured = capture_credentials(
        page,
        lambda: staff.create_teaching_staff(
            first_name=person.first_name,
            last_name=person.last_name,
            email=person.email,
            gender=person.gender,
            date_of_birth=ADULT_DATE_OF_BIRTH,
            nationality=person.nationality,
            marital_status=DEFAULT_MARITAL_STATUS,
            dialect=DEFAULT_DIALECT,
            address=person.address,
            location=DEFAULT_LOCATION,
            phone=person.phone,
            religion=DEFAULT_RELIGION,
            job_title=TEACHER_JOB_TITLE,
            employment_type=DEFAULT_EMPLOYMENT_TYPE,
            admission_date=date.today().isoformat(),
            degree=DEFAULT_DEGREE,
            field_of_study=DEFAULT_FIELD_OF_STUDY,
        ),
        url_substring="/teacher/",
        email=person.email,
        # 201 is the create; the tab's list GET on the same path answers 200.
        statuses=(201,),
    )
    return _credentials(captured, person, role=TEACHER_ROLE)


def _create_accountant(page: Page, staff: StaffPage, scenario: Scenario) -> Credentials:
    person = _person("accountant", scenario)
    captured = capture_credentials(
        page,
        lambda: staff.create_non_teaching_staff(
            role=ACCOUNTANT_ROLE,
            first_name=person.first_name,
            last_name=person.last_name,
            email=person.email,
            gender=person.gender,
            date_of_birth=ADULT_DATE_OF_BIRTH,
            nationality=person.nationality,
            marital_status=DEFAULT_MARITAL_STATUS,
            dialect=DEFAULT_DIALECT,
            address=person.address,
            location=DEFAULT_LOCATION,
            phone=person.phone,
            religion=DEFAULT_RELIGION,
            job_title=ACCOUNTANT_JOB_TITLE,
            employment_type=DEFAULT_EMPLOYMENT_TYPE,
            admission_date=date.today().isoformat(),
            degree=DEFAULT_DEGREE,
        ),
        url_substring="/non-teaching/",
        email=person.email,
        statuses=(201,),
    )
    return _credentials(captured, person, role=ACCOUNTANT_ROLE)


def _create_guardian(
    page: Page, guardians: GuardiansPage, scenario: Scenario
) -> Credentials:
    person = _person("guardian", scenario)
    captured = capture_credentials(
        page,
        lambda: guardians.create_guardian(
            first_name=person.first_name,
            last_name=person.last_name,
            email=person.email,
            phone=person.phone,
            address=person.address,
            gender=person.gender,
            date_of_birth=ADULT_DATE_OF_BIRTH,
            location=DEFAULT_LOCATION,
        ),
        url_substring="/guardian/",
        email=person.email,
        statuses=(201,),
    )
    return _credentials(captured, person, role=GUARDIAN_ROLE)


def _admit_student(
    page: Page,
    students: "_StudentAdmission",
    scenario: Scenario,
    guardian_name: str,
) -> Credentials:
    person = _person("student", scenario)
    captured = capture_credentials(
        page,
        lambda: students.admit_student(
            first_name=person.first_name,
            last_name=person.last_name,
            email=person.email,
            gender=person.gender,
            date_of_birth=STUDENT_DATE_OF_BIRTH,
            address=person.address,
            location=DEFAULT_LOCATION,
            guardian_name=guardian_name,
            class_name="",
            blood_type=STUDENT_BLOOD_TYPE,
        ),
        url_substring="/student/",
        email=person.email,
        statuses=(201,),
        # The capture window opens before the first wizard step, and admission
        # is four steps deep with two antd date pickers — the POST lands well
        # past the 25s default, which would time the waiter out on a student
        # that was in fact created.
        timeout_ms=90_000,
    )
    return _credentials(captured, person, role=STUDENT_ROLE)


def _create_generic_admin(
    page: Page, access_roles: AccessRolesPage, scenario: Scenario
) -> Credentials:
    person = _person("admin", scenario)
    captured = capture_credentials(
        page,
        lambda: access_roles.create_user(
            role=ADMIN_ROLE,
            email=person.email,
            first_name=person.first_name,
            last_name=person.last_name,
            nationality=person.nationality,
            residential_address=person.address,
            primary_phone=person.phone,
            gender=person.gender,
        ),
        url_substring="/add_admin/",
        email=person.email,
    )
    return _credentials(captured, person, role=ADMIN_ROLE)


# ──────────────────── phase D prerequisite (API-only) ────────────────────────


def _seed_fee_group(
    api: BackendAPI,
    school_admin: BaseCredentials,
    *,
    school_id: int,
    branch_id: int,
) -> int | None:
    """Give the branch the fee group the Add Class dialog insists on.

    Returns the fee group id, or ``None`` when it could not be seeded — which is
    never fatal here: phase D then fails with the dialog's own "offered nothing
    selectable" message, which says the same thing more precisely.

    Deliberately over the API rather than through the UI; see the module
    docstring. A fee needs an academic year and term, so this runs after phase B
    has created them.
    """
    if branch_id <= 0:
        log.warning("provisioning.fee_group.skipped", reason="no branch id captured")
        return None

    try:
        token = api.login(school_admin.email, school_admin.password)["access_token"]

        existing = api.get(f"/fees/groups?branch_id={branch_id}", token=token)
        if existing.status_code < 400 and existing.json():
            return int(existing.json()[0]["id"])

        years = api.get(
            f"/academic-year/?skip=0&limit=100&school_id={school_id}", token=token
        ).json()
        year = next((y for y in years if y.get("is_active")), years[0] if years else None)
        if not year:
            log.warning("provisioning.fee_group.skipped", reason="no academic year")
            return None

        terms = api.get(f"/academic-term/by-year/{year['id']}", token=token).json()
        if not terms:
            log.warning("provisioning.fee_group.skipped", reason="no academic term")
            return None

        fee = api.post(
            f"/fees/?branch_id={branch_id}",
            token=token,
            json={
                "name": FEE_NAME,
                "amount": FEE_AMOUNT,
                "academic_year_id": year["id"],
                "academic_term_id": terms[0]["id"],
                "school_branch_id": branch_id,
            },
        )
        if fee.status_code >= 400:
            log.warning("provisioning.fee_group.failed", step="fee", body=fee.text[:300])
            return None

        group = api.post(
            f"/fees/group?branch_id={branch_id}",
            token=token,
            json={"name": FEE_GROUP_NAME, "school_fees_ids": [fee.json()["id"]]},
        )
        if group.status_code >= 400:
            log.warning("provisioning.fee_group.failed", step="group", body=group.text[:300])
            return None

        group_id = int(group.json()["id"])
        log.info("provisioning.fee_group.seeded", branch_id=branch_id, fee_group=group_id)
        return group_id
    except Exception as exc:  # noqa: BLE001 — a prerequisite, not the thing under test
        log.warning("provisioning.fee_group.failed", error=str(exc))
        return None


# ───────────────────────────── phase D ───────────────────────────────────────


def _phase_d_academic_structure(
    page: Page,
    settings: Settings,
    scenario: Scenario,
    school_admin_creds: BaseCredentials,
    teacher_email: str,
    student_name: str,
    *,
    teacher_name: str = "",
    branch_name: str | None = None,
) -> dict[str, Any]:
    """As SchoolAdmin: the class, the subject, and the student's enrollment.

    ``teacher_name`` is preferred over ``teacher_email`` when picking the class
    teacher: that dropdown renders display names only, and the generated
    addresses (``playwright+teacher-…``) carry no name to match on.
    """
    base_url = settings.frontend_base_url
    log.info("provisioning.phase_d.start", scenario=scenario.id)
    login_as(page, base_url, school_admin_creds)

    # Same reason as phase C, and just as mandatory: logging in again leaves the
    # branch store empty, and the Add Class dialog reads school_branch_id from
    # it to fetch the branch's fee groups (GET /fees/groups without a branch_id
    # is a 400 for a SchoolAdmin, which the dialog shows as an empty dropdown).
    if branch_name:
        BranchesPage(page, base_url).select_branch(branch_name)
        log.info("provisioning.phase_d.branch_selected", branch=branch_name)

    classes: list[dict[str, Any]] = []
    subjects: list[dict[str, Any]] = []
    classes_page: ClassesPage | None = None

    if _enabled(scenario, "D", "classes", CLASSES_MODULE):
        classes_page = ClassesPage(page, base_url).open()
        teacher = teacher_name or teacher_email
        classes_page.create_class(name=CLASS_NAME, teacher_email=teacher or None)
        classes.append({"id": None, "name": CLASS_NAME, "teacher": teacher or None})

    # Both remaining steps write through the class, so each needs the classes
    # module too, not just its own.
    if classes and _enabled(scenario, "D", "subjects", SUBJECTS_MODULE, CLASSES_MODULE):
        # No teacher_email here on purpose: /module/subjects has no teacher
        # field, and SubjectsPage raises rather than silently ignoring one. The
        # (teacher, subject, class) link is written from the staff form instead.
        log.info(
            "provisioning.phase_d.subject_teacher_unassigned",
            scenario=scenario.id,
            subject=SUBJECT_NAME,
            reason="assignable only from the teaching-staff form under /module/staff",
        )
        subjects_page = SubjectsPage(page, base_url).open()
        subjects_page.create_subject(name=SUBJECT_NAME, classes=[CLASS_NAME])
        subjects.append({"id": None, "name": SUBJECT_NAME, "classes": [CLASS_NAME]})

    enrolled = ""
    if _enabled(scenario, "D", "enroll_student", STUDENTS_MODULE, CLASSES_MODULE):
        if classes_page is None or not student_name:
            log.info(
                "provisioning.step.skipped",
                scenario=scenario.id,
                phase="D",
                step="enroll_student",
                reason="no student was admitted in phase C",
            )
        else:
            classes_page.enroll_student(class_name=CLASS_NAME, student_name=student_name)
            classes[0]["students"] = [student_name]
            enrolled = student_name

    log.info(
        "provisioning.phase_d.done",
        scenario=scenario.id,
        classes=[c["name"] for c in classes],
        subjects=[s["name"] for s in subjects],
        enrolled=enrolled or None,
    )
    _logout(page, base_url)

    return {"classes": classes, "subjects": subjects}


# ───────────────────────────── teardown ──────────────────────────────────────


def teardown_school(api: BackendAPI, school_id: int, super_admin_token: str) -> None:
    """Delete a provisioned school (``DELETE /api/v1/school_profile/{id}``).

    Never raises: a cleanup failure must not mask the failure that is being
    reported. Orphans left behind carry the "TEST" name prefix the sweeper
    matches on.
    """
    if not school_id or school_id < 0:
        log.warning("provisioning.teardown.skipped", school_id=school_id,
                    reason="no school id was captured during provisioning")
        return
    try:
        deleted = api.delete_school(school_id, token=super_admin_token)
    except Exception as exc:  # noqa: BLE001 — cleanup never propagates
        log.warning("provisioning.teardown.failed", school_id=school_id, error=str(exc))
        return
    if deleted:
        log.info("provisioning.teardown.done", school_id=school_id)
    else:
        log.warning("provisioning.teardown.rejected", school_id=school_id)


# ───────────────────────────── internals ─────────────────────────────────────


class _StudentAdmission(StudentsPage):
    """Admits a student while the school still has no classes.

    Phase C runs before phase D creates "Grade 6", and the wizard's Admission
    Information step only *requires* the admission date (its class picker is
    optional), so an empty ``class_name`` skips the picker instead of waiting
    for an option that cannot exist yet. Phase D then sets the class through
    ``ClassesPage.enroll_student``.
    """

    def _fill_admission_information(self, *, class_name: str, blood_type: str) -> None:
        if class_name:
            super()._fill_admission_information(class_name=class_name, blood_type=blood_type)
            return
        self.select_option_in_combobox(
            BLOOD_TYPE_PLACEHOLDER, re.compile(rf"^\s*{re.escape(blood_type)}\s*$", re.I)
        )


def _enabled(scenario: Scenario, phase: str, step: str, *modules: str) -> bool:
    """Whether ``step`` can run, logging the skip (and why) when it cannot."""
    missing = [module for module in modules if not scenario.has(module)]
    if not missing:
        return True
    log.info(
        "provisioning.step.skipped",
        scenario=scenario.id,
        phase=phase,
        step=step,
        missing_modules=missing,
    )
    return False


def _person(role: str, scenario: Scenario) -> PersonData:
    """Faker-generated person whose names are already what the app will store.

    Every name input in these wizards silently drops anything outside
    /[A-Za-z\\s]/, so an unsanitised "O'Brien" is saved as "OBrien" — and the
    later lookups (guardian picker, class-teacher picker, student search) would
    then search for a name that is not there.
    """
    person = make_person(role, scenario.id, gender=DEFAULT_GENDER)
    person.first_name = _letters(person.first_name)
    person.last_name = _letters(person.last_name)
    return person


def _letters(value: str) -> str:
    return re.sub(r"[^A-Za-z\s]", "", value).strip()


def _credentials(captured: CapturedUser, person: PersonData, *, role: str) -> Credentials:
    return Credentials(
        email=captured.email,
        password=captured.password,
        user_id=captured.user_id,
        role_name=role,
        first_name=person.first_name,
        last_name=person.last_name,
        role=role,
    )


def _promote(creds: BaseCredentials, *, role: str) -> Credentials:
    """Widen a plain login (the bootstrapped SuperAdmin) into a flow Credentials."""
    if isinstance(creds, Credentials):
        return creds
    return Credentials(
        email=creds.email,
        password=creds.password,
        user_id=creds.user_id,
        role_id=creds.role_id,
        role_name=creds.role_name or role,
        access_token=creds.access_token,
        role=creds.role_name or role,
    )


def _resolve_school_id(
    api: BackendAPI,
    scenario: Scenario,
    super_admin_creds: BaseCredentials,
    school_name: str,
) -> int:
    """Last resort when the create response could not be read: look the school
    up by name so teardown still has an id. Setup-only, never a test assertion."""
    try:
        token = super_admin_creds.access_token or api.login(
            super_admin_creds.email, super_admin_creds.password
        ).get("access_token", "")
        for school in api.list_schools(token=token):
            if str(school.get("name", "")).strip() == school_name:
                found = school.get("id")
                if isinstance(found, int):
                    log.info(
                        "provisioning.school_id.recovered",
                        scenario=scenario.id,
                        school=school_name,
                        school_id=found,
                    )
                    return found
    except Exception as exc:  # noqa: BLE001 — best effort, provisioning continues
        log.warning(
            "provisioning.school_id.lookup_failed",
            scenario=scenario.id,
            school=school_name,
            error=str(exc),
        )
    return -1


def _logout(page: Page, frontend_base_url: str) -> None:
    """End the session, falling back to clearing the stored auth.

    The profile menu's logout control is the one selector in the flow that no
    page object owns; if it cannot be found, dropping the cookies the Next.js
    middleware reads plus the localStorage the auth store persists leaves the
    browser just as logged out.
    """
    try:
        logout(page)
        return
    except Exception as exc:  # noqa: BLE001 — provisioning must still continue
        log.warning("provisioning.logout.fallback", error=str(exc))

    page.context.clear_cookies()
    page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    page.goto(frontend_base_url.rstrip("/") + "/auth/login")
