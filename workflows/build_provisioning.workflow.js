// build_provisioning.workflow.js
// ─────────────────────────────────────────────────────────────────────────────
// Phase 2 of the LearningBrix Playwright suite — build the full school
// provisioning playbook (SuperAdmin onboarding → SchoolAdmin onboarding →
// users/classes/subjects), then verify it runs end-to-end against ONE
// scenario before fanning out to module tests in a later workflow.
//
// Phase 0+1 (scaffolding, config loaders, bootstrap fixtures, base page
// objects, smoke tests) is assumed to already exist in the repo.
//
// HOW TO RUN
// ───────────
// 1. Make sure backend and frontend are running locally:
//      cd ../newschoolapp && uvicorn app:app --reload
//      cd ../smsfrontend && npm run dev
// 2. Make sure .env is filled in (cp .env.example .env, set SUPERADMIN_PASSWORD).
// 3. Then in this Claude Code session, say:
//      "use a workflow at workflows/build_provisioning.workflow.js"
//    (or run it via the Workflow tool with scriptPath set to this file).
//
// WHAT IT BUILDS
// ──────────────
// tests/pages/super_admin/{schools.py, feature_flag.py}
// tests/pages/school_admin/{config.py, branches.py, academic_year.py, access_roles.py}
// tests/pages/people/{staff.py, students.py, guardians.py}
// tests/pages/academics/{classes.py, subjects.py}
// tests/flows/{__init__.py, school_provisioning.py}
// tests/fixtures/provisioned_school.py   (the provisioned_school fixture)
// tests/test_provisioning_smoke.py        (a one-scenario verification test)
//
// SAFETY
// ──────
// - The Smoke-run phase will create a real school via the UI and delete it.
// - The verification school name is prefixed "TEST" so it's easy to clean
//   up manually if something goes wrong mid-workflow.
// ─────────────────────────────────────────────────────────────────────────────

export const meta = {
  name: 'lb-build-provisioning',
  description: 'Build the LearningBrix school provisioning playbook (Phase 2) — page objects for SuperAdmin + SchoolAdmin + onboarding flows, the provisioned_school fixture, and a one-scenario smoke verification. Stops before fanning out to per-module tests.',
  whenToUse: 'After Phase 0+1 scaffolding is complete and tests/test_smoke.py passes against a running backend+frontend. Idempotent — re-runs overwrite generated page objects.',
  phases: [
    { title: 'Preflight' },
    { title: 'SuperAdmin pages' },
    { title: 'SchoolAdmin pages' },
    { title: 'People pages' },
    { title: 'Academics pages' },
    { title: 'Flow' },
    { title: 'Smoke run' },
    { title: 'Fix' },
  ],
}

const REPO = '/Users/manoffaith/Desktop/projects/lesalami/learningbrixtests'
const BACKEND = '/Users/manoffaith/Desktop/projects/lesalami/newschoolapp'
const FRONTEND = '/Users/manoffaith/Desktop/projects/lesalami/smsfrontend'
const PLAN = `${REPO}/docs/plan.md`

// Common context every page-object agent gets. Keep this tight — it gets
// inlined into every prompt.
const COMMON_CTX = `
You are contributing one Python module to a Playwright integration test suite.

Repo (write here): ${REPO}
Backend (read-only reference): ${BACKEND}
Frontend (read-only reference): ${FRONTEND}
Design doc: ${PLAN} (skim §3, §7, §9)

Rules:
- Read tests/pages/base.py FIRST so you reuse its helpers (click_button, fill_label, expect_toast, select_combobox, open). Do not duplicate them.
- Read the FRONTEND source for the page you're modeling — find the actual button text, form labels, and toast messages. Quote them with re.compile(..., re.I) so case/whitespace drift doesn't break.
- NO data-testid selectors (the frontend has none). Use role/text/label only.
- Python 3.11+ with type hints. 4-space indent. No comments unless explaining a non-obvious "why".
- Imports sorted, unused removed.
- Write the target file with the Write tool. Use Bash to mkdir -p parent dirs if missing.
- Final response: a single line — the absolute file path you wrote.
`.trim()

const PATH_RESULT = {
  type: 'object',
  required: ['path'],
  properties: {
    path: { type: 'string' },
    notes: { type: 'string', description: 'Anything notable, esp. UI elements you could not find or had to guess at.' },
  },
}

// ─── Phase: Preflight ───────────────────────────────────────────────────────
phase('Preflight')

const PREFLIGHT_SCHEMA = {
  type: 'object',
  required: ['backend_up', 'frontend_up', 'smoke_passes'],
  properties: {
    backend_up: { type: 'boolean' },
    frontend_up: { type: 'boolean' },
    smoke_passes: { type: 'boolean' },
    details: { type: 'string' },
  },
}

const preflight = await agent(`
Verify Phase 0+1 is healthy before we build Phase 2.

1. cd ${REPO} && .venv/bin/python scripts/preflight.py --json
   That script self-heals what it can (venv, deps, chromium, backend container
   restart, SuperAdmin seed) and reports the rest. Map its "ready" field and the
   backend/frontend checks onto backend_up / frontend_up.
2. If ready, run the smoke tests:
     .venv/bin/pytest tests/test_smoke.py -q --no-header 2>&1 | tail -20
   smoke_passes = (exit code == 0)
3. Report via schema. Put any failure excerpts in "details".

Do not build page objects here. Just get to a runnable state and report.
`, { schema: PREFLIGHT_SCHEMA, label: 'preflight', phase: 'Preflight' })

if (!preflight || !preflight.backend_up || !preflight.frontend_up) {
  log('Preflight failed — backend or frontend not reachable. Aborting before any UI changes.')
  return { aborted: 'preflight', details: preflight?.details ?? 'preflight agent died' }
}

if (!preflight.smoke_passes) {
  log('Smoke tests do not pass. Aborting — fix smoke first before building Phase 2.')
  return { aborted: 'smoke', details: preflight.details }
}

log('Preflight green. Building page objects.')

// ─── Phase: SuperAdmin pages ────────────────────────────────────────────────
phase('SuperAdmin pages')

const superAdminPages = [
  {
    label: 'super_admin/schools',
    target: 'tests/pages/super_admin/schools.py',
    spec: `
SchoolsPage at /module/schools (SuperAdmin only).

Methods:
- open() -> SchoolsPage
- create_school(*, name: str, admin_email: str, admin_first_name: str, admin_last_name: str, address: str, phone: str, currency: str = "GHS", notification_preference: str = "email") -> int  # returns new school id (read from URL change OR from the row appearing in the table; if id isn't recoverable, return -1 and document)
- find_row(name: str) -> Locator  # row in schools table
- delete_school(name: str) -> None

Read ${FRONTEND}/src/app/module/schools/page.tsx and any /components child to learn the form. The Create modal opens via a button — find its real label.
`
  },
  {
    label: 'super_admin/feature_flag',
    target: 'tests/pages/super_admin/feature_flag.py',
    spec: `
FeatureFlagPage at /module/feature_flag.

Methods:
- open() -> FeatureFlagPage
- switch_tab(name: "Packs" | "Schools" | "Modules") -> None
- create_pack(*, name: str, description: str = "", modules: Iterable[str]) -> None
   # On the Packs tab. The form lists every module as a toggle/checkbox; check the ones in \`modules\`.
- assign_pack_to_school(*, school_name: str, pack_name: str) -> None
   # On the Schools tab.
- delete_pack(name: str) -> None

Read ${FRONTEND}/src/app/module/feature_flag/page.tsx + ${FRONTEND}/src/lib/handlers/featureFlagHandler.ts to learn exact UI and module-name strings.
`
  },
]

await parallel(superAdminPages.map(p => () => agent(
  `${COMMON_CTX}\n\nWrite ${REPO}/${p.target}.\n\n${p.spec}`,
  { label: p.label, phase: 'SuperAdmin pages', schema: PATH_RESULT }
)))

// ─── Phase: SchoolAdmin pages ───────────────────────────────────────────────
phase('SchoolAdmin pages')

const schoolAdminPages = [
  {
    label: 'school_admin/config',
    target: 'tests/pages/school_admin/config.py',
    spec: `
ConfigPage at /module/config.

Methods:
- open() -> ConfigPage
- set_basic_info(*, name: str, address: str, phone: str, email: str) -> None
- set_currency(currency: str) -> None      # e.g. "GHS"
- set_notification_preference(pref: "email" | "sms" | "push") -> None
- save() -> None

Read ${FRONTEND}/src/app/module/config/page.tsx.
`
  },
  {
    label: 'school_admin/branches',
    target: 'tests/pages/school_admin/branches.py',
    spec: `
BranchesPage. The exact route may live under config or its own page —
search ${FRONTEND}/src/app/module/ for "branch" before deciding URL.

Methods:
- open() -> BranchesPage
- create_branch(*, name: str, address: str, phone: str) -> int   # branch id if discoverable
- create_branch_admin(*, branch_name: str, email: str, first_name: str, last_name: str) -> None
- find_row(name: str) -> Locator

If branch admin creation lives on a different page (e.g. access_roles), document the cross-reference in a module docstring.
`
  },
  {
    label: 'school_admin/academic_year',
    target: 'tests/pages/school_admin/academic_year.py',
    spec: `
AcademicYearTermPage at /module/academic_year_and_term.

Methods:
- open() -> AcademicYearTermPage
- create_year(*, name: str, start_date: str, end_date: str, set_active: bool = True) -> None
   start_date / end_date in "YYYY-MM-DD". Use the page's date input rather than the calendar widget if possible (more stable).
- activate_year(name: str) -> None
- create_term(*, year_name: str, term_name: str, start_date: str, end_date: str, set_active: bool = True) -> None
- activate_term(year_name: str, term_name: str) -> None

Read ${FRONTEND}/src/app/module/academic_year_and_term/page.tsx + any components.
`
  },
  {
    label: 'school_admin/access_roles',
    target: 'tests/pages/school_admin/access_roles.py',
    spec: `
AccessRolesPage at /module/access_roles.

Methods:
- open() -> AccessRolesPage
- list_roles() -> list[str]
- create_user(*, role: str, email: str, first_name: str, last_name: str, password: str | None = None, **extra) -> None
   # role in {"Admin", "Accountant"} for v1 (generic non-domain users). Teachers/Students/Guardians have their own dedicated pages.
- find_user_row(email: str) -> Locator

Read ${FRONTEND}/src/app/module/access_roles/page.tsx.
`
  },
]

await parallel(schoolAdminPages.map(p => () => agent(
  `${COMMON_CTX}\n\nWrite ${REPO}/${p.target}. Create tests/pages/school_admin/__init__.py if it does not exist.\n\n${p.spec}`,
  { label: p.label, phase: 'SchoolAdmin pages', schema: PATH_RESULT }
)))

// ─── Phase: People pages ────────────────────────────────────────────────────
phase('People pages')

const peoplePages = [
  {
    label: 'people/staff',
    target: 'tests/pages/people/staff.py',
    spec: `
StaffPage at /module/staff.

Methods:
- open() -> StaffPage
- create_teaching_staff(*, first_name, last_name, email, gender, date_of_birth, nationality, marital_status, dialect, address, location, phone, religion, job_title, employment_type, admission_date, degree, field_of_study) -> None
   # The form is multi-step (Basic → Contact → Admission). Click Continue between steps.
- create_non_teaching_staff(*, role: str, first_name, last_name, email, ..., job_title, employment_type, admission_date) -> None
- find_row(email_or_name: str) -> Locator

Read ${FRONTEND}/src/app/module/staff/* thoroughly — this is a complex multi-step form. Keep parameter coverage focused on REQUIRED fields; optional fields can be skipped.
`
  },
  {
    label: 'people/students',
    target: 'tests/pages/people/students.py',
    spec: `
StudentsPage at /module/students.

Methods:
- open() -> StudentsPage
- admit_student(*, first_name, last_name, email, gender, date_of_birth, address, location, guardian_name: str, class_name: str, previous_school: str = "", blood_type: str = "O+") -> None
   # Multi-step form (Basic → Contact+Guardian → Class+Health).
   # The "Select a guardian" combobox lists existing guardians — pass guardian_name to pick one. If empty, this should raise.
- find_row(name: str) -> Locator

Read ${FRONTEND}/src/app/module/students/*.
`
  },
  {
    label: 'people/guardians',
    target: 'tests/pages/people/guardians.py',
    spec: `
GuardiansPage at /module/guardians.

Methods:
- open() -> GuardiansPage
- create_guardian(*, first_name, last_name, email, phone, address, relationship: str = "Parent") -> None
- link_ward(*, guardian_name: str, student_name: str) -> None  # if there's a "link ward" action; otherwise document that wards are set during student admission only.

Read ${FRONTEND}/src/app/module/guardians/*.
`
  },
]

await parallel(peoplePages.map(p => () => agent(
  `${COMMON_CTX}\n\nWrite ${REPO}/${p.target}. Create tests/pages/people/__init__.py if missing.\n\n${p.spec}`,
  { label: p.label, phase: 'People pages', schema: PATH_RESULT }
)))

// ─── Phase: Academics pages ─────────────────────────────────────────────────
phase('Academics pages')

const academicsPages = [
  {
    label: 'academics/classes',
    target: 'tests/pages/academics/classes.py',
    spec: `
ClassesPage at /module/classes_and_timetables.

Methods:
- open() -> ClassesPage
- create_class(*, name: str, teacher_email: str | None = None) -> None
- assign_teacher(*, class_name: str, teacher_email: str) -> None
- enroll_student(*, class_name: str, student_name: str) -> None
- find_row(name: str) -> Locator

Read ${FRONTEND}/src/app/module/classes_and_timetables/*.
`
  },
  {
    label: 'academics/subjects',
    target: 'tests/pages/academics/subjects.py',
    spec: `
SubjectsPage at /module/subjects.

Methods:
- open() -> SubjectsPage
- create_subject(*, name: str, classes: list[str], teacher_email: str | None = None) -> None
- find_row(name: str) -> Locator

Read ${FRONTEND}/src/app/module/subjects/*.
`
  },
]

await parallel(academicsPages.map(p => () => agent(
  `${COMMON_CTX}\n\nWrite ${REPO}/${p.target}. Create tests/pages/academics/__init__.py if missing.\n\n${p.spec}`,
  { label: p.label, phase: 'Academics pages', schema: PATH_RESULT }
)))

// ─── Phase: Flow ────────────────────────────────────────────────────────────
phase('Flow')

await agent(`
${COMMON_CTX}

Write ${REPO}/tests/flows/__init__.py (empty) and ${REPO}/tests/flows/school_provisioning.py.

This is the BIG one — the full UI walkthrough. It composes the page objects you just wrote. Read all of them before starting:
- tests/pages/super_admin/{schools,feature_flag}.py
- tests/pages/school_admin/{config,branches,academic_year,access_roles}.py
- tests/pages/people/{staff,students,guardians}.py
- tests/pages/academics/{classes,subjects}.py
- tests/pages/login.py
- tests/fixtures/data_factories.py    # for unique_email, person_name, RUN_TAG
- config/scenarios.py                  # Scenario dataclass

Define a dataclass SchoolContext (in this same file) holding:
- scenario_id: str
- school_id: int
- school_name: str
- feature_modules: frozenset[str]
- super_admin: Credentials
- school_admin: Credentials
- branch_admin: Credentials
- teacher: Credentials
- accountant: Credentials
- generic_admin: Credentials
- student: Credentials          # username + password if app generates one; else None
- guardian: Credentials
- branches: list[dict]          # [{id, name}]
- classes: list[dict]
- subjects: list[dict]
- academic_year: str
- current_term: str

Where Credentials is a small dataclass {email, password, first_name, last_name, role}.

Public entry point:

def provision_school(page: Page, settings: Settings, scenario: Scenario, super_admin_creds: Credentials, api: BackendAPI) -> SchoolContext:
    """
    Drives the full multi-step onboarding through the UI. Returns the populated SchoolContext.
    Raises ProvisioningError with the phase name on any step that fails so the test can report which phase broke.
    """

CRITICAL — Credential capture
─────────────────────────────
QA mode is implemented in the backend and is ON. Every user-creating response
carries the generated password under a "test_mode" key in the body, and every
response also carries the same JSON in an "X-Test-Mode" header (which is how
list-/null-bodied endpoints such as forgot-password are read).

DO NOT hand-roll this. The helper already exists — read it, then use it:

    ${REPO}/tests/fixtures/credentials.py
      capture_credentials(page, action, *, url_substring, email) -> CapturedUser
      capture_link(page, action, *, url_substring, kind="reset") -> str

Use it from inside each phase helper:

    from tests.fixtures.credentials import capture_credentials

    school_admin = capture_credentials(
        page,
        lambda: schools_page.create_school(...),
        url_substring="/school_profile/",
        email=seed.admin_email,
    )
    # school_admin.password now works for a real login

Same shape for /teacher/, /student/, /guardian/, /non-teaching/,
/users/branch-admin/, /school_profile/{id}/admins.

If capture raises "QA mode is not enabled", run:
    touch ${BACKEND}/.qa_mode_enabled
and wait ~10s for uvicorn --reload. Never work around it by guessing a password.
The backend side lives in ${BACKEND}/utils/qa_mode.py and is documented in
${REPO}/state/backend_patches.md.

Emails: the backend rejects reserved TLDs (.test/.example/.invalid) with a 422.
Always generate addresses with tests/fixtures/data_factories.unique_email.

Phases inside the flow (each its own helper function so they're individually testable):
A. _phase_a_super_admin_setup(page, scenario, super_admin_creds) -> dict
   - login as SuperAdmin
   - create the school (capture school_admin password via response interceptor on /school_profile/)
   - create the feature pack (scenario.feature_pack_name, modules=scenario.modules)
   - assign pack to school
   - logout
   - returns {school_id, school_admin_creds}

B. _phase_b_school_admin_setup(page, settings, scenario, school_admin_creds) -> dict
   - login as SchoolAdmin
   - config: set currency=GHS, notification_preference=email
   - branches: create one branch "Main Campus"; if branch admin is a separate endpoint, capture branch_admin_creds via response interceptor; if branch admin is created on access_roles page, do it there
   - academic_year_and_term: create year "2026/2027", activate; create "Term 1", activate
   - (skip steps whose module is not in scenario.modules — document each skip with structlog at INFO level)
   - logout
   - returns {branch_admin_creds, branches, academic_year, current_term}

C. _phase_c_create_users(page, settings, scenario, school_admin_creds) -> dict
   - login as SchoolAdmin
   - staff: create 1 teaching staff (teacher) — capture teacher_creds via /teacher/ response
   -        create 1 non-teaching staff (Accountant role) — capture accountant_creds via /non-teaching/ response
   - guardians: create 1 guardian — capture guardian_creds via /guardian/ response
   - students: admit 1 student linked to the guardian — capture student_creds via /student/ response (admit without class first; class set in phase D)
   - access_roles: create 1 generic Admin user — capture generic_admin_creds via /users/branch-admin/ or whatever the access_roles page hits
   - logout
   - returns {teacher, accountant, guardian, student, generic_admin}

D. _phase_d_academic_structure(page, settings, scenario, school_admin_creds, teacher_email, student_name) -> dict
   - login as SchoolAdmin
   - classes: create "Grade 6", assign teacher
   - subjects: create "Mathematics", assign teacher, link to "Grade 6"
   - enroll the phase-C student in "Grade 6"
   - logout
   - returns {classes, subjects}

For each phase, wrap in try/except and re-raise as ProvisioningError(phase="A"|"B"|"C"|"D", original=exc).

Use structlog (already in deps) for per-phase info logs. Include scenario.id in every log.

Use data_factories.unique_email / person_name to generate emails+names for every created user. Store generated credentials in the returned dicts.

Helper at the bottom: teardown_school(api: BackendAPI, school_id: int, super_admin_token: str) -> None — calls DELETE /api/v1/school_profile/{id}. Swallow errors (log warning, do not raise) so cleanup never masks test failure.
`, { label: 'flow:school_provisioning', phase: 'Flow', schema: PATH_RESULT })

await agent(`
${COMMON_CTX}

Write ${REPO}/tests/fixtures/provisioned_school.py.

Defines the provisioned_school pytest fixture (SESSION-scope). It:

@pytest.fixture(scope="session", params=[s for s in load_scenarios()], ids=lambda s: s.id)
def provisioned_school(request, browser, settings: Settings, superadmin, api: BackendAPI):
    """
    Session-scoped: each of the 5 scenarios produces ONE school for the whole test
    session. All tests share these 5 schools across all roles. The provisioning
    browser context is closed before any test starts, so tests get fresh contexts
    and do their own logins per role using the credentials stored in SchoolContext.
    """
    scenario = request.param
    super_admin_creds = Credentials(
        email=superadmin["email"],
        password=superadmin["password"],
        first_name=settings.superadmin_first_name,
        last_name=settings.superadmin_other_names,
        role="SuperAdmin",
    )

    context = browser.new_context(
        viewport={"width": settings.viewport_width, "height": settings.viewport_height},
        base_url=settings.frontend_base_url,
    )
    page = context.new_page()
    page.set_default_timeout(settings.default_timeout_ms)
    try:
        ctx = provision_school(page, settings, scenario, super_admin_creds, api)
    finally:
        context.close()  # provisioning is done; tests will create their own contexts

    yield ctx

    if settings.delete_on_failure or not request.session.testsfailed:
        teardown_school(api, ctx.school_id, superadmin["token"])

Notes:
- Session scope → exactly 5 schools per run (one per scenario), reused across every test that requests provisioned_school.
- Cannot use the function-scoped pytest-playwright "page" — instead take the session-scoped "browser" fixture and build a dedicated context here.
- The dedicated context is CLOSED right after provisioning. Each test then creates its own context via pytest-playwright's normal page/context fixtures and logs in as whatever role it needs using ctx.<role>.email / ctx.<role>.password.
- pass the api fixture into provision_school so the flow can intercept network responses (e.g. for credential capture) or hit backend endpoints directly when needed.
- If DELETE_ON_FAILURE=false and any test failed in the session, skip teardown so the user can inspect.

Also add a session-scoped finalizer fixture _sweep_orphan_schools(api, superadmin, settings):
- Runs at session end.
- Lists all schools (GET /api/v1/school_profile/) and deletes any whose name starts with "TEST" AND whose creation timestamp is older than 10 minutes ago AND younger than 24h.  (Only if a setting --sweep-orphans is passed; default off.)

Register provisioned_school in conftest.py via pytest_plugins. Read root conftest.py first, then Edit to add the line if missing.
`, { label: 'fixture:provisioned_school', phase: 'Flow', schema: PATH_RESULT })

// ─── Phase: Smoke run ──────────────────────────────────────────────────────
phase('Smoke run')

await agent(`
${COMMON_CTX}

Write ${REPO}/tests/test_provisioning_smoke.py.

A single test that proves the provisioning playbook works end-to-end against the first scenario only.

import pytest

@pytest.mark.provisioning
@pytest.mark.smoke
def test_provision_full_access_scenario(provisioned_school):
    ctx = provisioned_school
    assert ctx.school_id > 0
    assert ctx.school_admin.email
    assert ctx.teacher.email
    assert ctx.student.email
    assert "Main Campus" in [b["name"] for b in ctx.branches]
    assert any(c["name"] == "Grade 6" for c in ctx.classes)
    assert any(s["name"] == "Mathematics" for s in ctx.subjects)

Limit pytest collection to JUST the first scenario via params filter:
- Add a pytest_collection_modifyitems hook in tests/conftest.py (or this test file) that filters out all scenarios except "full_access" for this specific test. Use a marker like @pytest.mark.provisioning_smoke_only on the test; the hook filters the param list when the marker is present.

Then run the test:
1. cd ${REPO}
2. .venv/bin/pytest tests/test_provisioning_smoke.py -v 2>&1 | tee /tmp/lb_smoke_run.log
3. Tail and report:
   - status: "pass" | "fail" | "error"
   - failing_phase: A | B | C | D | (none) — derive from the log for "ProvisioningError(phase=..."
   - tail: last 80 lines of output

After running, report via this schema (NOT the standard PATH_RESULT — different schema):
`, {
  label: 'smoke:provisioning_run',
  phase: 'Smoke run',
  schema: {
    type: 'object',
    required: ['status'],
    properties: {
      status: { enum: ['pass', 'fail', 'error', 'not_run'] },
      failing_phase: { type: 'string' },
      tail: { type: 'string' },
      written_path: { type: 'string' },
    },
  }
})

// We don't capture the smoke result here for branching; instead a separate
// verify agent re-runs the suite and decides whether to enter the Fix phase.

const smokeVerdict = await agent(`
Just re-run the smoke and report. Do NOT write code.

cd ${REPO} && .venv/bin/pytest tests/test_provisioning_smoke.py -v 2>&1 | tail -100

Report:
- status: "pass" if exit code 0, else "fail"
- failing_phase: A | B | C | D if you see "ProvisioningError(phase=X)" in the output; "unknown" otherwise; empty string if pass
- tail: last 60 lines
- summary: one sentence
`, {
  label: 'verify:smoke',
  phase: 'Smoke run',
  schema: {
    type: 'object',
    required: ['status'],
    properties: {
      status: { enum: ['pass', 'fail'] },
      failing_phase: { type: 'string' },
      tail: { type: 'string' },
      summary: { type: 'string' },
    },
  }
})

if (smokeVerdict && smokeVerdict.status === 'pass') {
  log('Provisioning smoke passes. Phase 2 complete — ready to fan out per-module tests in the next workflow.')
  return { phase_2: 'green', smoke: smokeVerdict }
}

// ─── Phase: Fix ─────────────────────────────────────────────────────────────
phase('Fix')

log(`Provisioning smoke failed (phase: ${smokeVerdict?.failing_phase ?? 'unknown'}). Attempting adversarial fix.`)

// Up to 3 fix rounds. Each round: one agent investigates with full repo access
// and patches whatever's wrong. Then we re-verify. We stop early on pass.
let lastVerdict = smokeVerdict
for (let round = 1; round <= 3; round++) {
  await agent(`
${COMMON_CTX}

The provisioning smoke test is failing.

Latest run tail:
\`\`\`
${lastVerdict?.tail ?? '(no tail captured)'}
\`\`\`

Failing phase (per ProvisioningError): ${lastVerdict?.failing_phase ?? 'unknown'}

Your job:
1. Identify the ROOT cause. The page object likely uses a selector that doesn't match the real UI. Open the relevant page object AND the frontend source for that page side by side. Compare.
2. Fix the page object (preferred) OR fix the flow step that calls it. Do not invent data-testid attributes on the frontend — selectors must be role/text/label.
3. If the failure is in Phase B/C/D and it looks like a UI element is genuinely missing (e.g. a feature pack doesn't expose a needed module), update the flow to skip that step with a structlog warning and continue.

Do not add try/except as a band-aid. Diagnose, fix, move on.

Final response: one sentence describing the fix.
`, { label: `fix:round-${round}`, phase: 'Fix' })

  lastVerdict = await agent(`
cd ${REPO} && .venv/bin/pytest tests/test_provisioning_smoke.py -v 2>&1 | tail -100

Report the same schema as before: status (pass|fail), failing_phase, tail, summary.
`, {
    label: `re-verify:round-${round}`,
    phase: 'Fix',
    schema: {
      type: 'object',
      required: ['status'],
      properties: {
        status: { enum: ['pass', 'fail'] },
        failing_phase: { type: 'string' },
        tail: { type: 'string' },
        summary: { type: 'string' },
      },
    }
  })

  if (lastVerdict && lastVerdict.status === 'pass') {
    log(`Smoke passes after fix round ${round}.`)
    return { phase_2: 'green-after-fix', rounds: round, smoke: lastVerdict }
  }
}

log('3 fix rounds exhausted, smoke still failing. Surfacing for human review.')
return { phase_2: 'failed', smoke: lastVerdict }
