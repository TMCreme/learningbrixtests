"""Incident Reports — the log a teacher files an incident in, and then works.

Three walkthroughs, one log
    ``test_teacher_creates_and_manages_incident_report`` is the writing half: a
    teacher files a report from the browser and then works it through its
    lifecycle. ``test_school_admin_reviews_the_branch_incident_log`` is the
    reading half: an administrator opens the branch, finds a report a teacher
    filed, reads the record and narrows the log down — and writes nothing.
    ``test_incidents_denied_for_school_admin_when_module_disabled`` is the
    negative half: the same administrator at a school whose feature pack omits
    ``incidents`` gets no log at all. The section comment above each of the last
    two covers what is particular to it.

Why a *teacher* is the right role for "manage" here
    ``db/repository/permissions.py`` grants the Teacher role
    ``("manage", "incidents")`` — one of only a handful of manage rights it
    holds — and ``nav-config.tsx`` puts "Incidents Reporting" in front of them.
    That is the product's own answer to who writes these up: the adult who was
    standing there when it happened. So the whole of this walkthrough is done as
    the teacher, from the login page onward, with nothing seeded behind the
    scenes — the incident this test reads back is the one the browser typed.

What "manage" means on this module, and where it stops
    Create and edit, both as full-page forms rather than modals
    (``/module/incidents_reporting/create`` and ``…/{id}/edit``). The edit form
    is where an incident moves through its life: ``reported`` →
    ``under_investigation`` → ``resolved`` → ``closed``, plus severity, actions
    taken and resolution notes. Delete exists on the row menu and is
    deliberately not exercised — the record this test files is what the closing
    server-side check reads back.

Two things this test works *around* rather than through, on purpose
    1. **The incident is left unassigned.** The create form offers an "Assigned
       To" picker, but it is filled from ``GET /teacher/``, which is gated on
       ``read staff`` — a permission the Teacher role does not hold, so the
       picker answers 403 and renders "No staff found" for exactly the role the
       module is written for. Whether a teacher should be able to hand an
       incident to a colleague is a product decision (it needs either a new
       permission on the role or a different source for that list), not a defect
       to fix unattended, so the walkthrough simply does not assign anyone. The
       stray "You do not have permission to perform this action." toast the
       failed fetch raises is the same story and is likewise not asserted on.
    2. **The Incident Time is always filled.** ``createIncidentReport`` sends
       ``incident_time: form.incident_time || ""`` and ``IncidentReportBase``
       types that field ``Optional[time]``, so an empty string is a 422 — a
       report filed without a time cannot be saved. Filling it is the realistic
       path anyway (a report says when), and whether ``""`` ought to be coerced
       to ``null`` is an API-shape call for the owners.

A backend defect this unit uncovered (fixed in place, newschoolapp is dirty)
    ``POST /incidents/`` declared ``branch_id: int = Query(...)`` — *required* —
    and never called ``branch_id_required``, while every other route in
    ``api/routes/incident_report.py`` declares it optional and resolves it from
    the caller. The frontend appends ``branch_id`` only for a SchoolAdmin or
    SuperAdmin (``incidentReportingHandler.createIncidentReport``), so for the
    Teacher the module is actually written for, the create went out with no
    query string at all and FastAPI answered 422 before the handler ran. The
    module contradicted itself: the same teacher could edit and delete incidents
    they could never create. See ``state/app_changes_review.md``.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from tests.fixtures.api_client import BackendAPI
from tests.fixtures.data_factories import run_tag
from tests.flows.school_provisioning import SchoolContext
from tests.pages.base import as_pattern
from tests.pages.incidents.incidents import (
    BEHAVIORAL,
    EMPTY_TITLE,
    HEADING,
    INJURY,
    LOAD_FAILURE,
    MY_ASSIGNED_BUTTON,
    NEW_INCIDENT_BUTTON,
    SEARCH_PLACEHOLDER,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    STATUS_REPORTED,
    STATUS_UNDER_INVESTIGATION,
    STUDENT_HISTORY_BUTTON,
    SUBHEADING,
    IncidentsPage,
)
from tests.pages.login import login_as
from tests.pages.school_admin.branches import BranchesPage

INCIDENTS_SCENARIO = "library_and_community"
INCIDENTS_MODULE = "incidents"

# ── the report this walkthrough files ────────────────────────────────────────
# The title carries the "TEST" prefix the orphan sweeper matches on and the
# per-run tag, so the row it creates is unambiguous even when several agents
# share a school.
TAG = run_tag()
INCIDENT_TITLE = f"TEST Playground collision at morning break {TAG}"
INCIDENT_DATE = date.today().isoformat()
INCIDENT_TIME = "10:15"
INCIDENT_LOCATION = "Lower playground, by the Block A steps"
INCIDENT_DESCRIPTION = (
    "TEST Two pupils ran for the same ball and collided. One grazed a knee and "
    "was shaken but walked back to class unaided."
)
INCIDENT_WITNESSES = "TEST The duty teacher on the lower playground"
INCIDENT_ACTIONS = (
    "TEST Both pupils were checked over on the spot and walked to the office."
)
FOLLOW_UP_NOTES = "TEST Ring both guardians before the end of the day."

# ── what the edit turns it into ──────────────────────────────────────────────
UPDATED_ACTIONS = (
    "TEST Grazed knee cleaned and dressed at the office; both guardians rang."
)

# Enum values as the server stores them (utils/enums.py); the UI title-cases
# them for display, which is what the page object asserts on.
TYPE_VALUE = "behavioral"
SEVERITY_VALUE_MEDIUM = "medium"
SEVERITY_VALUE_HIGH = "high"
STATUS_VALUE_UNDER_INVESTIGATION = "under_investigation"


class IncidentReadbackError(RuntimeError):
    """The incident could not be read back from the API after the walkthrough."""


@pytest.mark.teacher
@pytest.mark.scenario(INCIDENTS_SCENARIO)
@pytest.mark.demo(
    feature_id="incident_reports.incidents.manage.teacher",
    title="Incident Reports",
    subtitle="Teacher creates and manages incident reports",
)
def test_teacher_creates_and_manages_incident_report(
    provisioned_school: SchoolContext,
    demo,
    api: BackendAPI,
) -> None:
    """A teacher writes up what happened at break, then works the report.

    The full arc of "manage": file it, read it back on the school's log, open
    what was recorded, then escalate it — severity up, status moved to under
    investigation, and the actions taken rewritten now that more is known.

    The closing check is deliberately made against the API rather than the
    screen. Every earlier assertion could in principle be satisfied by a
    frontend that kept its own state; ``GET /incidents/list`` answers with what
    the school will still hold tomorrow.
    """
    ctx = provisioned_school
    assert ctx.teacher is not None, (
        "provisioning created no teacher for this school, and the Teacher role "
        "is the one this module grants manage rights to"
    )
    assert ctx.student is not None, (
        "provisioning admitted no student, so no pupil can be named as involved "
        "in the incident"
    )
    assert INCIDENTS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} does not license {INCIDENTS_MODULE!r}; "
        f"this is the positive path and needs the module on"
    )

    page: Page = demo.page
    incidents = IncidentsPage(page, demo.frontend_base_url)
    teacher = ctx.teacher
    student_name = ctx.student.full_name

    with demo.step(f"Sign in as {teacher.full_name}, a teacher at {ctx.school_name}"):
        login_as(page, demo.frontend_base_url, teacher)

    with demo.step("Their menu carries the Incidents module — open the log"):
        incidents.expect_nav_entry()
        incidents.open_from_sidebar().wait_for_table()
        incidents.expect_loaded()
        incidents.expect_no_load_failure()
        incidents.expect_headers()
        incidents.expect_manage_controls()
        # Nothing of ours is on the log yet; everything below puts it there.
        incidents.expect_incident_absent(INCIDENT_TITLE)

    with demo.step("Something happened at break — start a new report"):
        incidents.start_new_incident()

    with demo.step("Write up what happened, when, where, and who saw it"):
        incidents.fill_incident_form(
            title=INCIDENT_TITLE,
            incident_type=BEHAVIORAL,
            severity=SEVERITY_MEDIUM,
            incident_date=INCIDENT_DATE,
            incident_time=INCIDENT_TIME,
            location=INCIDENT_LOCATION,
            description=INCIDENT_DESCRIPTION,
            witnesses=INCIDENT_WITNESSES,
            actions_taken=INCIDENT_ACTIONS,
        )

    with demo.step("Name the pupil involved, flag it for follow-up, and file it"):
        incidents.fill_incident_form(
            student_name=student_name,
            follow_up_notes=FOLLOW_UP_NOTES,
        )
        incidents.submit_new_incident()

    with demo.step("The report is on the school's log — open it and read it back"):
        incidents.expect_incident(
            INCIDENT_TITLE,
            incident_type=BEHAVIORAL,
            severity=SEVERITY_MEDIUM,
            status=STATUS_REPORTED,
            reported_by=teacher.full_name,
            student_count=1,
            follow_up=True,
        )
        incidents.view_details(INCIDENT_TITLE)
        incidents.expect_details(
            severity=SEVERITY_MEDIUM,
            status=STATUS_REPORTED,
            incident_type=BEHAVIORAL,
            location=INCIDENT_LOCATION,
            description=INCIDENT_DESCRIPTION,
            actions_taken=INCIDENT_ACTIONS,
            witnesses=INCIDENT_WITNESSES,
            student_name=student_name,
            follow_up=True,
        )
        incidents.close_details()

    with demo.step("More is known by lunchtime — escalate it and record the care given"):
        incidents.start_editing(INCIDENT_TITLE)
        incidents.expect_form_prefilled(
            title=INCIDENT_TITLE, location=INCIDENT_LOCATION
        )
        incidents.fill_incident_form(
            status=STATUS_UNDER_INVESTIGATION,
            severity=SEVERITY_HIGH,
            actions_taken=UPDATED_ACTIONS,
        )
        incidents.submit_edits()

    with demo.step("The log shows it under investigation — and so does the school's "
                   "own record of it", dwell_ms=2000):
        incidents.expect_incident(
            INCIDENT_TITLE,
            severity=SEVERITY_HIGH,
            status=STATUS_UNDER_INVESTIGATION,
            reported_by=teacher.full_name,
            student_count=1,
        )
        _expect_stored(api, ctx)


def _expect_stored(api: BackendAPI, ctx: SchoolContext) -> None:
    """Read the incident back out of the API, as the teacher who filed it.

    The screen above proves the browser rendered the right thing; this proves
    the server *stored* it — the fields the create wrote, and the three the edit
    changed. Read with the teacher's own token so it also stands as evidence
    that ``read incidents`` reaches the record their ``manage`` right created
    (``has_permission`` lets "manage" stand in for "read").
    """
    assert ctx.teacher is not None

    try:
        token = str(api.login(ctx.teacher.email, ctx.teacher.password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise IncidentReadbackError(
            f"could not log in as {ctx.teacher.email} to read the incident back: "
            f"{exc}"
        ) from exc

    response = api.get("/incidents/list?skip=0&limit=100", token=token)
    assert response.status_code == 200, (
        f"a teacher must be able to list their branch's incidents — got "
        f"{response.status_code}: {response.text[:300]}"
    )

    wanted = re.compile(rf"^\s*{re.escape(INCIDENT_TITLE)}\s*$")
    rows = [row for row in response.json() if isinstance(row, dict)]
    filed = next(
        (row for row in rows if wanted.match(str(row.get("title") or ""))), None
    )
    assert filed is not None, (
        f"the incident the teacher filed is not in GET /incidents/list. The log "
        f"is scoped to the caller's branch and the school's active academic "
        f"year, so a missing row means it was written against neither; the "
        f"branch holds {[row.get('title') for row in rows]}"
    )

    # What the create form wrote.
    assert str(filed.get("incident_type")) == TYPE_VALUE
    assert str(filed.get("incident_date")) == INCIDENT_DATE
    assert str(filed.get("location")) == INCIDENT_LOCATION
    assert str(filed.get("description")) == INCIDENT_DESCRIPTION
    assert str(filed.get("witnesses")) == INCIDENT_WITNESSES
    assert filed.get("follow_up_required") is True, (
        "the follow-up switch was flipped on before filing, so the server must "
        f"hold it — got {filed.get('follow_up_required')!r}"
    )
    assert str(filed.get("follow_up_notes")) == FOLLOW_UP_NOTES
    assert int(filed.get("student_count") or 0) == 1, (
        f"one pupil was named as involved, so the incident must be linked to "
        f"exactly one student — got {filed.get('student_count')!r}"
    )
    assert str(filed.get("reported_by_name")).strip() == ctx.teacher.full_name, (
        f"the reporter is taken from the token, never from the form, so it must "
        f"be {ctx.teacher.full_name!r} — got {filed.get('reported_by_name')!r}"
    )
    assert filed.get("assigned_to_user_id") is None, (
        "nobody was assigned (the Teacher role cannot list staff), so the "
        f"incident must still be unassigned — got {filed.get('assigned_to_name')!r}"
    )

    # …and what the edit changed.
    assert str(filed.get("status")) == STATUS_VALUE_UNDER_INVESTIGATION, (
        f"the report was moved to {STATUS_VALUE_UNDER_INVESTIGATION!r} on the "
        f"edit form — got {filed.get('status')!r}"
    )
    assert str(filed.get("severity")) == SEVERITY_VALUE_HIGH, (
        f"the report was escalated from {SEVERITY_VALUE_MEDIUM!r} to "
        f"{SEVERITY_VALUE_HIGH!r} — got {filed.get('severity')!r}"
    )
    assert str(filed.get("actions_taken")) == UPDATED_ACTIONS, (
        f"the actions taken were rewritten on the edit form, so the original "
        f"text must no longer be stored — got {filed.get('actions_taken')!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The view path — the SchoolAdmin's side of the same log
# ─────────────────────────────────────────────────────────────────────────────
# Why this role, and why "view" is a different walkthrough from "manage"
#     The teacher above *writes* incidents. A SchoolAdmin is who reads them
#     afterwards: they hold ("manage", "incidents") too, so the module is not
#     hidden from them, but what the role actually does on this screen is review
#     what the branch's staff filed — find the report, open what was recorded,
#     and narrow the log down with the toolbar. Nothing here writes.
#
#     Unlike the teacher, a SchoolAdmin has to earn their way in twice over.
#     nav-config declares the whole "Incidents Module" section ``branchOnly``,
#     and a SchoolAdmin belongs to no branch, so the entry does not exist until
#     the branch row's "View" button fills ``useBranchStore``
#     (``BranchesPage.select_branch``). The same store is what
#     ``incidentReportingHandler.listIncidentReports`` appends ``branch_id``
#     from for this role — without it the log's own fetch is a 400
#     BRANCH_ID_REQUIRED. Opening the branch is therefore step two of the
#     walkthrough, not a setup detail.
#
# Why the report is seeded over the API
#     The point of this unit is the reading, and the incident has to have been
#     filed by *somebody else* for the review to mean anything — a SchoolAdmin
#     reading their own writing would prove only that the row round-tripped. So
#     the teacher files it over the API (setup-only use of ``api``, as in
#     ``test_messaging.notice``) and the browser only ever reads. The stamp is
#     fresh per execution, so the searched-for row is unambiguous even though the
#     school is session-scoped and the manage test above files one of its own.

VIEW_SCENARIO = "library_and_community"

_VIEW_STAMP = f"{run_tag()}-view-{uuid.uuid4().hex[:4]}"

REVIEWED_TITLE = f"TEST Slip on the wet corridor floor {_VIEW_STAMP}"
REVIEWED_DESCRIPTION = (
    "TEST A pupil slipped on the corridor floor by the science lab shortly "
    "after it had been mopped. They landed on their left wrist and were taken "
    "to the office."
)
REVIEWED_LOCATION = "Science block corridor, outside Lab 2"
REVIEWED_WITNESSES = "TEST The lab technician and two Year 8 pupils"
REVIEWED_ACTIONS = (
    "TEST Wrist iced at the office and the corridor cordoned off until dry."
)
REVIEWED_FOLLOW_UP_NOTES = (
    "TEST Ask the caretaker for wet-floor signage on the science corridor."
)
REVIEWED_TIME = "11:40:00"

# What the seeded report is, in the server's own vocabulary and in the UI's.
REVIEWED_TYPE_VALUE = "injury"
REVIEWED_SEVERITY_VALUE = "high"

# A severity the seeded report is *not*, used to prove the toolbar filter does
# something (page.tsx filters ``incidents`` client-side on exactly this field).
OTHER_SEVERITY = "Low"
ALL_SEVERITIES = "All Severities"


class IncidentSeedError(RuntimeError):
    """The report the SchoolAdmin is meant to review could not be filed."""


@dataclass
class FiledIncident:
    """The seeded report, as the administrator should find it on the log."""

    incident_id: int
    title: str
    reporter_name: str
    student_name: str


@pytest.fixture
def filed_incident(
    provisioned_school: SchoolContext, api: BackendAPI
) -> FiledIncident:
    """Have the teacher file one report for the administrator to review.

    Requested before ``demo`` in the test signature so the seeding requests
    happen before the camera rolls rather than as dead frames at the head of the
    video.
    """
    ctx = provisioned_school
    assert INCIDENTS_MODULE in ctx.feature_modules, (
        f"scenario {ctx.scenario_id!r} does not license {INCIDENTS_MODULE!r}; "
        f"this is the positive path and needs the module on"
    )
    assert ctx.teacher is not None, (
        "provisioning created no teacher for this school, and the report the "
        "administrator reviews has to have been filed by somebody else"
    )
    assert ctx.student is not None, (
        "provisioning admitted no student, so no pupil can be named as involved "
        "in the incident"
    )

    try:
        token = str(api.login(ctx.teacher.email, ctx.teacher.password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — a prerequisite, not the thing under test
        raise IncidentSeedError(
            f"could not sign the teacher in to file the report: {exc}"
        ) from exc

    student_id, student_name = _student_profile(api, token, ctx)

    # No ``branch_id``: for a Teacher ``branch_id_required`` takes their own
    # ``school_branch_id``, which is the branch the administrator will open.
    res = api.post(
        "/incidents/",
        token=token,
        json={
            "incident_type": REVIEWED_TYPE_VALUE,
            "severity": REVIEWED_SEVERITY_VALUE,
            "title": REVIEWED_TITLE,
            "description": REVIEWED_DESCRIPTION,
            "incident_date": date.today().isoformat(),
            "incident_time": REVIEWED_TIME,
            "location": REVIEWED_LOCATION,
            "involved_student_ids": [student_id],
            "witnesses": REVIEWED_WITNESSES,
            "actions_taken": REVIEWED_ACTIONS,
            "follow_up_required": True,
            "follow_up_notes": REVIEWED_FOLLOW_UP_NOTES,
        },
    )
    if res.status_code >= 400:
        raise IncidentSeedError(f"POST /incidents/ → {res.status_code}: {res.text[:300]}")
    payload = res.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
        raise IncidentSeedError(f"POST /incidents/ returned no id: {payload!r}")

    return FiledIncident(
        incident_id=int(payload["id"]),
        title=REVIEWED_TITLE,
        reporter_name=ctx.teacher.full_name,
        student_name=student_name,
    )


def _student_profile(api: BackendAPI, token: str, ctx: SchoolContext) -> tuple[int, str]:
    """The admitted pupil's ``StudentProfile`` id, and the name the UI renders.

    ``involved_student_ids`` is expressed in profile ids, not user ids, and the
    name is assembled the way every list in this app assembles it —
    ``first_name other_names`` — so the detail modal can be matched on it.

    ``GET /student/`` answers a ``StudentResponsePagination`` envelope, not a
    bare list, so the rows come out of ``results``.
    """
    assert ctx.student is not None
    res = api.get("/student/?limit=100", token=token)
    if res.status_code >= 400:
        raise IncidentSeedError(
            f"GET /student/ → {res.status_code}: {res.text[:300]}"
        )
    payload = res.json()
    rows = payload.get("results") or [] if isinstance(payload, dict) else payload
    wanted = ctx.student.email.strip().lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        user = row.get("user") or {}
        if str(user.get("email", "")).strip().lower() == wanted:
            name = f"{user.get('first_name', '')} {user.get('other_names', '')}".strip()
            return int(row["id"]), name
    raise IncidentSeedError(
        f"{ctx.student.email!r} is not among the students of this branch — "
        f"provisioning phase C should have admitted them"
    )


@pytest.mark.school_admin
@pytest.mark.scenario(VIEW_SCENARIO)
@pytest.mark.demo(
    feature_id="incident_reports.incidents.view.school_admin",
    title="Incident Reports",
    subtitle="SchoolAdmin views incident reports",
)
def test_school_admin_reviews_the_branch_incident_log(
    filed_incident: FiledIncident,
    demo,
    provisioned_school: SchoolContext,
    api: BackendAPI,
) -> None:
    """An administrator opens the branch's log and reviews what a teacher filed.

    Read-only from end to end: the log, the report's own record, and the
    toolbar's severity filter. The closing check asks the API the same question
    the screen just answered, with the administrator's own token and the branch
    they opened — so "the administrator can see this branch's incidents" is a
    claim about the server, not about what the browser happened to be holding.
    """
    ctx = provisioned_school
    assert ctx.branches, (
        "provisioning left this school with no branch — and a SchoolAdmin "
        "outside a branch is never offered the Incidents module at all"
    )

    page: Page = demo.page
    base_url: str = demo.frontend_base_url
    incidents = IncidentsPage(page, base_url)
    branch_name = str(ctx.branches[0]["name"])

    with demo.step(f"Sign in as the school administrator at {ctx.school_name}"):
        login_as(page, base_url, ctx.school_admin)

    with demo.step(f"Open {branch_name} — incidents are a branch's own log"):
        # Mandatory, not scenic: the Incidents section is branchOnly, and the
        # log's fetch takes its branch_id from the store this button fills.
        BranchesPage(page, base_url).select_branch(branch_name)

    with demo.step("Open the incident log from the Incidents menu"):
        incidents.expect_nav_entry()
        incidents.open_from_sidebar().wait_for_table()
        incidents.expect_loaded()
        incidents.expect_no_load_failure()
        incidents.expect_headers()

    with demo.step(f"{filed_incident.reporter_name} filed a report this morning "
                   "— find it"):
        incidents.search(_VIEW_STAMP)
        incidents.expect_incident(
            filed_incident.title,
            incident_type=INJURY,
            severity=SEVERITY_HIGH,
            status=STATUS_REPORTED,
            reported_by=filed_incident.reporter_name,
            student_count=1,
            follow_up=True,
        )

    with demo.step("Open it and read what was recorded"):
        incidents.view_details(filed_incident.title)
        incidents.expect_details(
            severity=SEVERITY_HIGH,
            status=STATUS_REPORTED,
            incident_type=INJURY,
            location=REVIEWED_LOCATION,
            description=REVIEWED_DESCRIPTION,
            actions_taken=REVIEWED_ACTIONS,
            witnesses=REVIEWED_WITNESSES,
            student_name=filed_incident.student_name,
            follow_up=True,
        )
        incidents.close_details()

    with demo.step("Narrow the log by severity — a high-severity report is not "
                   "a low-severity one", dwell_ms=1500):
        incidents.filter_by(severity=OTHER_SEVERITY)
        incidents.expect_incident_absent(filed_incident.title)
        incidents.filter_by(severity=SEVERITY_HIGH)
        incidents.expect_incident(filed_incident.title, severity=SEVERITY_HIGH)
        incidents.filter_by(severity=ALL_SEVERITIES)

    with demo.step("And the branch's log says the same thing to the server"):
        _expect_visible_to_admin(api, ctx, filed_incident)


def _expect_visible_to_admin(
    api: BackendAPI, ctx: SchoolContext, filed: FiledIncident
) -> None:
    """Read the report back as the administrator, scoped to the branch they opened.

    This is the one thing the screen cannot prove on its own: that the row it
    rendered came out of ``GET /incidents/list`` for *this* branch under this
    role, rather than out of anything the browser was still holding from the
    teacher's session.
    """
    branch_id = int(ctx.branches[0]["id"])
    token = str(
        api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]
    )

    response = api.get(
        f"/incidents/list?skip=0&limit=100&branch_id={branch_id}", token=token
    )
    assert response.status_code == 200, (
        f"a SchoolAdmin must be able to list a branch's incidents — got "
        f"{response.status_code}: {response.text[:300]}"
    )

    rows = [row for row in response.json() if isinstance(row, dict)]
    seen = next((row for row in rows if int(row.get("id") or 0) == filed.incident_id), None)
    assert seen is not None, (
        f"incident {filed.incident_id}, filed by the teacher in branch "
        f"{branch_id}, is not in the administrator's own list of that branch; it "
        f"holds {[row.get('id') for row in rows]}"
    )
    assert str(seen.get("title")) == filed.title
    assert str(seen.get("severity")) == REVIEWED_SEVERITY_VALUE
    assert str(seen.get("incident_type")) == REVIEWED_TYPE_VALUE
    assert str(seen.get("reported_by_name")).strip() == filed.reporter_name, (
        f"the report was filed by the teacher, so that is who the branch's log "
        f"must credit it to — got {seen.get('reported_by_name')!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The negative path — the same administrator at a school that never bought it
# ─────────────────────────────────────────────────────────────────────────────
# Where the denial actually comes from, and where it does not
#     Nothing on the *client* refuses a SchoolAdmin this module. The Next.js
#     middleware exempts the role outright (``!isSchoolAdmin`` in the module
#     enforcement branch of ``src/middleware.ts``), ``useModuleGuard`` returns
#     ``true`` for it before it ever reads the ``schoolModules`` cookie, and
#     ``usePermissionGuard`` returns early for it as well — so
#     ``/module/incidents_reporting`` really does mount for this admin, exactly
#     as it does for the one in the view walkthrough above.
#
#     What denies them is the feature-pack half of
#     ``utils.permissions.has_permission``: it resolves the caller's school, asks
#     ``FeaturePackService`` for its module list, and answers **403 "Feature not
#     available in your plan"** when the module is missing. Every route on
#     ``api/routes/incident_report.py`` carries that dependency — the three
#     ``manage`` writes and the five ``read`` reads alike — and it is solved
#     before the endpoint body runs, which is why the ids and payloads below are
#     deliberately arbitrary but well-formed. A 400 ``BRANCH_ID_REQUIRED``, a 404
#     or a 422 in place of a 403 would itself be the failure: it would mean the
#     body ran before the licence was consulted.
#
#     The UI consequence follows from that 403's detail. The axios response
#     interceptor in ``src/utils/handleErrorMessage.ts`` recognises the plan
#     restriction (``shouldRedirectToNoAccess``) and performs a hard
#     ``window.location`` redirect to **/auth/no-access**, rejecting with
#     ``FeatureNotAvailableError``. That redirect races the page's own ``catch``,
#     which sets ``fetchError`` and renders the "Failed to load incidents"
#     ``PageError`` panel in place of the whole log — so both surfaces are
#     accepted below, and either of them is a refusal.
#
# Three things this test deliberately does NOT assert
#     1. **That the sidebar hides "Incidents Reporting".** It does not, and its
#        presence says nothing about the licence: ``canShowSection`` skips the
#        section's ``moduleGate: "incidents"`` whenever the role holds a
#        ``permissionsGate`` entry (``userHasSectionPermission``), and this admin
#        holds ``("manage", "incidents")``. The entry is gated on the *branch*
#        instead (``branchOnly``), which is a different rule entirely.
#     2. **That ``/module/incidents_reporting/create`` is unreachable.** It is
#        reachable — it is guarded by the same two client hooks that wave a
#        SchoolAdmin through — and whether the frontend ought to gate a
#        SchoolAdmin on the pack is a product decision, not a defect to fix here.
#        The claim this test makes about creating is the one that is actually
#        enforced: ``POST /incidents/`` refuses.
#     3. **The branch is selected first even though the denial does not need it.**
#        ``incidentReportingHandler`` appends ``branch_id`` from
#        ``useBranchStore`` for a SchoolAdmin, and without it the log's own call
#        would be one the backend could refuse for a reason that has nothing to do
#        with the plan. Selecting the branch removes that as a competing
#        explanation for the refusal.

DENIED_INCIDENTS_SCENARIO = "minimal"

# The frontend route, which is *not* the module key — see the header of
# ``tests/pages/incidents/incidents.py``.
DENIED_INCIDENTS_ROUTE = "incidents_reporting"
DENIED_SCHOOL_ADMIN_ROLE = "SchoolAdmin"

# A path id high enough that no provisioned row could carry it, so a 2xx here
# could never be mistaken for a real record being reached.
DENIED_UNREACHABLE_ID = 9_999_999

# The two denials utils/permissions.py can answer with. A school that holds the
# permission but not the module gets the first; one that holds neither gets the
# second. Either is a correct denial — anything else is not.
DENIED_DETAIL = re.compile(
    r"Feature not available in your plan"
    r"|You do not have permission to perform this action",
    re.I,
)

# Where the frontend sends a user whose *plan* excludes the module, and the copy
# it greets them with (src/app/auth/no-access/page.tsx).
DENIED_NO_ACCESS_URL = re.compile(r"/auth/no-access")
DENIED_ACCESS_RESTRICTED = re.compile(r"^\s*Access Restricted\s*$", re.I)
DENIED_ACTIVATION_REQUIRED = re.compile(r"Module Activation Required", re.I)

DENIED_SETTLE_TIMEOUT_MS = 40_000

# Bodies for the write refusals. Well-formed on purpose: a 422 would prove
# nothing about the licence.
UNLICENSED_TITLE = f"TEST incident that must never be filed {run_tag()}"
UNLICENSED_DESCRIPTION = (
    "TEST This report must never be accepted — the school's feature pack does "
    "not include the incidents module."
)


@pytest.mark.negative
@pytest.mark.school_admin
@pytest.mark.scenario(DENIED_INCIDENTS_SCENARIO)
def test_incidents_denied_for_school_admin_when_module_disabled(
    provisioned_school: SchoolContext,
    page: Page,
    frontend_base_url: str,
    api: BackendAPI,
) -> None:
    """With `incidents` off the pack, a SchoolAdmin gets no log and files nothing."""
    ctx = provisioned_school
    if INCIDENTS_MODULE in ctx.feature_modules:
        pytest.skip(
            f"scenario {ctx.scenario_id!r} enables {INCIDENTS_MODULE!r}; the "
            f"denial path only applies when the feature pack omits it"
        )

    assert ctx.branches, (
        "provisioning left this school with no branch, and the incident log is "
        "branch-scoped — phase B creates one for every scenario"
    )
    branch = ctx.branches[0]
    branch_id = int(branch.get("id") or 0)
    assert branch_id > 0, (
        "provisioning could not capture the branch id, and every /incidents "
        "route is scoped to one — re-run provisioning rather than guessing it"
    )

    token = api.login(ctx.school_admin.email, ctx.school_admin.password)["access_token"]

    # ── 1. The role is not what denies them — the licence is ─────────────────
    #
    # Asserted first so a failure below can never be read as "the SchoolAdmin
    # simply never had incident rights anyway", which would make the 403s
    # vacuous. ``manage`` specifically: it is what the three write routes below
    # require, and ``has_permission`` lets it stand in for the ``read`` the other
    # five want, so a role holding only ``read`` would make half the refusals
    # prove nothing.
    role = api.get(f"/roles/{api.role_id_for(DENIED_SCHOOL_ADMIN_ROLE)}")
    assert role.status_code == 200, (
        f"could not read the {DENIED_SCHOOL_ADMIN_ROLE} role — got "
        f"{role.status_code}: {role.text[:300]}"
    )
    role_permissions = {
        (p.get("name"), p.get("module")) for p in role.json().get("permissions", [])
    }
    assert ("manage", INCIDENTS_MODULE) in role_permissions, (
        f"the seeded {DENIED_SCHOOL_ADMIN_ROLE} role no longer holds "
        f"('manage', {INCIDENTS_MODULE!r}), so the refusals below would be a "
        f"denial the role gets for free. Re-point this test at the feature pack "
        f"only, or fix the seed in newschoolapp/db/repository/permissions.py."
    )

    features = api.get(f"/school_profile/{ctx.school_id}/features", token=token)
    assert features.status_code == 200, (
        f"a SchoolAdmin must be able to read their own school's features — got "
        f"{features.status_code}: {features.text[:300]}"
    )
    features_body = features.json()
    assert features_body.get("pack_assigned") is True, (
        f"{ctx.school_name!r} has no feature pack assigned at all, so omitting "
        f"{INCIDENTS_MODULE!r} proves nothing about the gate — an unassigned "
        f"school is unrestricted by design. Provisioning phase A assigns one; "
        f"check that it did."
    )
    assert INCIDENTS_MODULE not in (features_body.get("modules") or []), (
        f"{ctx.school_name!r} is licensed for {INCIDENTS_MODULE!r} despite the "
        f"{ctx.scenario_id!r} pack ({sorted(ctx.feature_modules)}) excluding it."
    )

    # ── 2. The denial itself: every /incidents route is refused ──────────────
    #
    # Reads and writes alike, so the gate cannot regress into covering only the
    # screen this admin happens to open. ``branch_id`` is supplied everywhere the
    # frontend supplies it for this role, so a refusal can never be the backend
    # merely missing it.
    refusals = {
        # ── what the log itself calls on mount ──
        "list": api.get(
            f"/incidents/list?skip=0&limit=50&branch_id={branch_id}", token=token
        ),
        "statistics": api.get(
            f"/incidents/statistics/summary?branch_id={branch_id}"
            f"&from_date={date.today().replace(month=1, day=1).isoformat()}"
            f"&to_date={date.today().isoformat()}",
            token=token,
        ),
        # ── the row menu's "View Details", and the two side screens ──
        "detail": api.get(
            f"/incidents/{DENIED_UNREACHABLE_ID}?branch_id={branch_id}", token=token
        ),
        "student_history": api.get(
            f"/incidents/student/{DENIED_UNREACHABLE_ID}/history"
            f"?branch_id={branch_id}&limit=20",
            token=token,
        ),
        "my_assignments": api.get(
            f"/incidents/my-assignments?branch_id={branch_id}&skip=0&limit=50",
            token=token,
        ),
        # ── the writes: filing one, working it, and removing it ──
        "create": api.post(
            f"/incidents/?branch_id={branch_id}",
            token=token,
            json={
                "incident_type": TYPE_VALUE,
                "severity": SEVERITY_VALUE_MEDIUM,
                "title": UNLICENSED_TITLE,
                "description": UNLICENSED_DESCRIPTION,
                "incident_date": date.today().isoformat(),
                "incident_time": "09:00:00",
                "location": "TEST corridor of a school with no incidents module",
                "involved_student_ids": [],
                "involved_staff_ids": [],
                "follow_up_required": False,
            },
        ),
        "update": api.patch(
            f"/incidents/{DENIED_UNREACHABLE_ID}?branch_id={branch_id}",
            token=token,
            json={"status": STATUS_VALUE_UNDER_INVESTIGATION},
        ),
        "delete": api.delete(
            f"/incidents/{DENIED_UNREACHABLE_ID}?branch_id={branch_id}", token=token
        ),
    }
    for label, res in refusals.items():
        assert res.status_code == 403, (
            f"{label}: a SchoolAdmin of {ctx.school_name!r} (pack "
            f"{sorted(ctx.feature_modules)}) is not licensed for "
            f"{INCIDENTS_MODULE!r}, so the backend must refuse with 403 — got "
            f"{res.status_code}: {res.text[:300]}"
        )
        detail = str((res.json() or {}).get("detail", ""))
        assert DENIED_DETAIL.search(detail), (
            f"{label}: 403 is right but the reason is not one the app "
            f"implements — got {detail!r}"
        )

    # ── 3. …and the UI never puts an incident log in front of them ───────────
    login_as(page, frontend_base_url, ctx.school_admin)

    # Not a data precondition — see honesty note 3 — but it removes the missing
    # branch_id as a competing explanation for what the log's own call returns.
    BranchesPage(page, frontend_base_url).select_branch(str(branch["name"]))
    _settle_branch_selection(page)

    # The response is checked rather than discarded: a redirect still in flight
    # from the previous screen would abort this navigation, and the settle loop
    # below would then read a /auth/no-access this module never caused — a denial
    # test passing for somebody else's denial.
    response = page.goto(
        frontend_base_url.rstrip("/") + f"/module/{DENIED_INCIDENTS_ROUTE}"
    )
    assert response is not None and DENIED_INCIDENTS_ROUTE in response.url, (
        f"the browser never landed on /module/{DENIED_INCIDENTS_ROUTE} — it is "
        f"at {page.url!r} instead. Whatever redirect the assertions below would "
        f"have read came from the previous screen, not from this module."
    )

    surface = _wait_for_settled_incident_surface(page)

    if surface == "redirected":
        # The strongest denial the app can give: the interceptor recognised the
        # plan restriction and took the browser off the module entirely.
        expect(page.get_by_text(as_pattern(DENIED_ACCESS_RESTRICTED))).to_be_visible(
            timeout=15_000
        )
        expect(page.get_by_text(as_pattern(DENIED_ACTIVATION_REQUIRED))).to_be_visible()

    _expect_no_incident_log(page)


def _expect_no_incident_log(page: Page) -> None:
    """None of the log's own chrome reached them, on either refusal surface.

    ``PageError`` replaces the whole screen (the ``fetchError`` branch returns
    before the container is rendered), and ``/auth/no-access`` renders a
    different page entirely — so the same absences hold whichever way the race
    went, and asserting them once keeps the two branches from drifting apart.
    """
    expect(page.get_by_role("heading", name=as_pattern(HEADING))).to_have_count(0)
    expect(page.get_by_text(as_pattern(SUBHEADING))).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(NEW_INCIDENT_BUTTON))).to_have_count(0)
    expect(
        page.get_by_role("button", name=as_pattern(STUDENT_HISTORY_BUTTON))
    ).to_have_count(0)
    expect(page.get_by_role("button", name=as_pattern(MY_ASSIGNED_BUTTON))).to_have_count(0)
    expect(page.get_by_placeholder(as_pattern(SEARCH_PLACEHOLDER))).to_have_count(0)
    # Not even the log's own "nothing here yet" copy: an empty log would say the
    # fetch succeeded and returned nothing, which is not the denial.
    expect(page.get_by_text(as_pattern(EMPTY_TITLE))).to_have_count(0)


def _settle_branch_selection(page: Page, timeout_ms: int = 20_000) -> None:
    """Let the branch row's side-effect navigation finish before moving on.

    ``BranchesPage.select_branch`` lands on ``/module/community`` — and in the
    ``minimal`` scenario *community* is unlicensed too, so that screen fires its
    own refused fetch and the interceptor bounces the browser to
    ``/auth/no-access``. Navigating away while that bounce is still in flight
    would abort the next ``page.goto`` and hand this test a redirect it did not
    cause. Waiting for it to land first means the only redirect the assertions
    can see is the one *this* module provoked.

    Returns quietly if it never comes: a scenario that does license community
    simply stays put, and there is then nothing in flight to steal anything.
    """
    remaining = timeout_ms
    step = 250
    while remaining > 0 and not DENIED_NO_ACCESS_URL.search(page.url):
        page.wait_for_timeout(step)
        remaining -= step


def _wait_for_settled_incident_surface(
    page: Page, timeout_ms: int = DENIED_SETTLE_TIMEOUT_MS
) -> str:
    """Wait until /module/incidents_reporting has stopped loading.

    Returns which of the two refusal surfaces it settled on — ``"redirected"`` or
    ``"page_error"``. Waiting for one of them is what stops the assertions above
    from passing merely because the log had not finished mounting; reaching the
    timeout means the log rendered normally, which for an unlicensed school is
    itself the failure.
    """
    failure = page.get_by_text(as_pattern(LOAD_FAILURE)).first

    remaining = timeout_ms
    step = 500
    while remaining > 0:
        if DENIED_NO_ACCESS_URL.search(page.url):
            return "redirected"
        if failure.count() and failure.is_visible():
            return "page_error"
        page.wait_for_timeout(step)
        remaining -= step

    raise AssertionError(
        f"/module/{DENIED_INCIDENTS_ROUTE} neither redirected to /auth/no-access "
        f"nor rendered its \"Failed to load incidents\" panel within "
        f"{timeout_ms}ms — the browser is at {page.url!r}. For a school whose "
        f"pack excludes {INCIDENTS_MODULE!r} that means the log rendered as "
        f"though it were licensed."
    )
