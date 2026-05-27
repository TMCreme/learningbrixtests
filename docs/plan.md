# Playwright Integration Test Suite — Plan

## 1. Goals

- Drive the **full school lifecycle through the UI** (not just feature flows): SuperAdmin creates the school, the SchoolAdmin onboards branches/users/academic calendar, then each role exercises their permitted modules.
- Cover **≥90% of features** across all major roles (SuperAdmin, SchoolAdmin, Admin, Teacher, Student, Guardian, Accountant).
- Validate **feature-pack enforcement**: 5 schools with different feature combinations; each test file runs against every school and expects success when the feature is enabled and **graceful denial** when it isn't.
- Be **headed by default** for local dev, **headless-configurable** for CI.
- **Tear down every school created**, even on failure.

## Non-goals (v1)

- Real email/SMS delivery (backend will expose a test mode that returns the link in the response).
- Parallel execution (serial only in v1).
- Cross-browser matrix — Chromium only initially; add Firefox/WebKit later if needed.
- Performance testing.

---

## 2. Architecture overview

```
┌────────────────────────────────────────────────────────────────┐
│  pytest session                                                │
│                                                                │
│   ┌──────────────────────────────────────────────────────┐    │
│   │  Session fixture: bootstrap_superadmin                │    │
│   │   ↳ POST /api/v1/users/register (or admin-seed route) │    │
│   │   ↳ Yield SuperAdmin creds for later use              │    │
│   └──────────────────────────────────────────────────────┘    │
│                            ↓                                   │
│   ┌──────────────────────────────────────────────────────┐    │
│   │  For each scenario in feature_scenarios.yaml (×5):    │    │
│   │                                                       │    │
│   │   ┌─────────────────────────────────────────────────┐│    │
│   │   │  Module fixture: provisioned_school              ││    │
│   │   │   ↳ UI walkthrough as SuperAdmin:                ││    │
│   │   │      • Create school + SchoolAdmin               ││    │
│   │   │      • Create + assign feature pack              ││    │
│   │   │   ↳ UI walkthrough as SchoolAdmin:               ││    │
│   │   │      • Create branch(es), branch admin           ││    │
│   │   │      • Academic year/term (active)               ││    │
│   │   │      • Create teachers, students, guardians,     ││    │
│   │   │        accountant, generic admin                 ││    │
│   │   │      • Create classes, subjects, assignments     ││    │
│   │   │   ↳ Yield SchoolContext (URLs, users, ids)       ││    │
│   │   │   ↳ Finalizer: DELETE /school_profile/{id}       ││    │
│   │   └─────────────────────────────────────────────────┘│    │
│   │                                                       │    │
│   │   For each module test file (academics, fees, library,│    │
│   │   payroll, ledger, community, audit, etc.):           │    │
│   │     If module ∈ school.features:                      │    │
│   │       run positive flows for each role               │    │
│   │     Else:                                             │    │
│   │       run negative flows (asserts UI hides module     │    │
│   │       OR returns 403 / "no access" page)             │    │
│   │                                                       │    │
│   └──────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory structure

```
learningbrixtests/                          # this repo
├── pytest.ini
├── playwright.config.py                    # browser, headless, viewport
├── requirements.txt                        # already exists — update
├── .env.example                            # template
├── .env                                    # local secrets (gitignored)
├── conftest.py                             # root: superadmin + scenarios loader
├── config/
│   ├── feature_scenarios.yaml              # the 5 school definitions
│   └── module_catalog.py                   # canonical list of modules
├── tests/
│   ├── conftest.py                         # provisioned_school + role fixtures
│   ├── fixtures/
│   │   ├── api_client.py                   # backend HTTP for setup-only ops
│   │   ├── browser.py                      # page/context fixtures
│   │   ├── data_factories.py               # faker-driven student/teacher data
│   │   └── selectors.py                    # shared role/text selector helpers
│   ├── pages/                              # lightweight page objects
│   │   ├── base.py
│   │   ├── login.py
│   │   ├── super_admin/
│   │   │   ├── schools.py
│   │   │   └── feature_flag.py
│   │   ├── school_admin/
│   │   │   ├── config.py
│   │   │   ├── branches.py
│   │   │   ├── academic_year_and_term.py
│   │   │   ├── access_roles.py
│   │   │   └── audit_trails.py
│   │   ├── academics/                      # classes, subjects, lessons…
│   │   ├── people/                         # students, staff, guardians
│   │   ├── account/                        # fees, income/expense
│   │   ├── payroll/
│   │   ├── library/
│   │   ├── community/
│   │   └── ...
│   ├── flows/                              # multi-step composed flows
│   │   ├── school_provisioning.py          # the full setup playbook
│   │   ├── enroll_student.py
│   │   ├── pay_fee.py
│   │   └── ...
│   ├── modules/                            # tests organized by backend module
│   │   ├── academics/
│   │   │   ├── test_classes.py
│   │   │   ├── test_subjects.py
│   │   │   ├── test_lessons.py
│   │   │   └── test_assessments.py
│   │   ├── people/
│   │   ├── account/
│   │   ├── payroll/
│   │   ├── library/
│   │   ├── governance/                     # access_roles, audit_trails, config
│   │   ├── general/                        # community, messaging
│   │   └── ...
│   └── role_matrix/
│       ├── test_teacher_journey.py
│       ├── test_student_journey.py
│       ├── test_guardian_journey.py
│       └── test_accountant_journey.py
├── reports/                                # html report output (gitignored)
└── artifacts/                              # screenshots (gitignored)
```

Keeping the existing `Academics Module/`, `Account Module/`, etc. test scaffolding can become a starting point for the new `tests/modules/` layout — I'll migrate, not delete, anything reusable.

---

## 4. Configuration

### `.env`

```env
# Backend
BACKEND_BASE_URL=http://localhost:8000
BACKEND_API_PREFIX=/api/v1
FRONTEND_BASE_URL=http://localhost:3000

# SuperAdmin seed (test creates this via backend API at session start)
SUPERADMIN_EMAIL=playwright-super@learningbrix.test
SUPERADMIN_PASSWORD=<strong-pw>

# Browser
HEADLESS=false
SLOW_MO_MS=0
DEFAULT_TIMEOUT_MS=15000
VIEWPORT_WIDTH=1440
VIEWPORT_HEIGHT=900

# Test mode for backend (returns email/reset/invite links in HTTP response body)
BACKEND_TEST_MODE=true

# Behavior
KEEP_ON_FAILURE=false   # always delete schools even on failure (per your choice)
```

### `config/feature_scenarios.yaml`

This is the heart of the matrix. You'll fill in 5 scenarios; tests parameterize over them.

```yaml
scenarios:
  - id: full_access
    school_name: "TEST_Mountain_View_Academy"
    feature_pack_name: "TEST_All_Modules"
    modules:
      - home
      - students
      - staff
      - guardians
      - classes_and_timetables
      - subjects
      - lessons
      - exams
      - attendance
      - fees
      - incomes_and_expenses
      - employee_benefit
      - staff_payroll
      - categories
      - catalogue
      - statistics
      - requests_and_renewals
      - access_roles
      - audit_trails
      - academic_year_and_term
      - school_configuration
      - messaging
      - community
      - incidents
      - change_requests

  - id: academics_only
    school_name: "TEST_Sunrise_Prep"
    feature_pack_name: "TEST_Academics_Pack"
    modules: [home, students, staff, classes_and_timetables, subjects, attendance]

  # ... 3 more scenarios you'll define
```

A loader (`config/scenarios.py`) reads this and exposes `scenarios()` to pytest as a parametrize source.

---

## 5. Tech stack

| Concern | Choice | Reason |
|---|---|---|
| Test runner | **pytest** | Already used in repo; integrates cleanly with Playwright |
| Browser driver | **pytest-playwright** (Python) | Standard; auto fixtures for `page`, `context`, `browser` |
| Data generation | **Faker** | Realistic unique names, addresses, dates |
| Config | **pydantic-settings** + **PyYAML** | Validated env + yaml scenarios |
| HTTP (setup only) | **httpx** | Async-friendly, for the SuperAdmin bootstrap call |
| Reporting | **pytest-html** | Single static HTML report |
| Retries (flakes) | **pytest-rerunfailures** (optional, off by default) | For known-flaky network/SMTP cases later |
| Logging | **structlog** | Structured logs make CI triage easier |

Will update `requirements.txt` with pinned versions.

---

## 6. Fixture hierarchy

| Scope | Fixture | Purpose |
|---|---|---|
| session | `settings` | Parsed .env via pydantic |
| session | `scenarios` | Parsed feature_scenarios.yaml |
| session | `superadmin` | Creates SuperAdmin via backend API, yields `{email, password, token}` |
| session | `browser` | Single Chromium instance |
| session | `report_dir` | `reports/<timestamp>/` |
| module (per scenario) | `provisioned_school` | The big one. Drives full UI walkthrough as SuperAdmin → SchoolAdmin. Yields a rich `SchoolContext` object. Finalizer deletes the school. |
| function | `context` | Fresh browser context (isolated cookies/storage) per test |
| function | `page` | Standard pytest-playwright page |
| function | `as_super_admin` / `as_school_admin` / `as_teacher` / etc. | Logs in as the requested role using credentials from `SchoolContext` |

`SchoolContext` shape (rough):

```python
@dataclass
class SchoolContext:
    scenario_id: str                         # "full_access"
    school_id: int
    school_name: str
    feature_modules: set[str]                # for "if enabled" checks
    super_admin: Credentials
    school_admin: Credentials
    branch_admin: Credentials
    teacher: Credentials
    student: Credentials
    guardian: Credentials
    accountant: Credentials
    generic_admin: Credentials
    branches: list[Branch]                   # at least 1
    classes: list[Class]
    subjects: list[Subject]
    academic_year_id: int
    current_term_id: int
```

---

## 7. The school provisioning playbook (UI flow)

This is `tests/flows/school_provisioning.py` — the single biggest piece of work. Pseudocode:

```python
def provision_school(page, settings, scenario, superadmin):
    # Phase A — As SuperAdmin
    login_as(page, superadmin)
    schools_page.create_school(name=scenario.school_name, admin_email=..., ...)
    school_id = schools_page.last_created_id()
    feature_flag_page.create_pack(name=scenario.feature_pack_name, modules=scenario.modules)
    feature_flag_page.assign_pack_to_school(scenario.feature_pack_name, scenario.school_name)
    school_admin_creds = read_invite_link_from_test_mode_response()  # OR set password during create
    logout(page)

    # Phase B — As SchoolAdmin
    login_as(page, school_admin_creds)
    config_page.set_currency_and_branding(...)
    branches_page.create_branch("Main Campus")
    branches_page.create_branch_admin(branch="Main Campus", email=...)
    academic_year_page.create_year("2026/2027").activate()
    academic_year_page.create_term("Term 1").activate()

    # Phase C — Create one user per role
    staff_page.create_teaching_staff(...)        # → teacher creds
    staff_page.create_non_teaching_staff(role="Accountant", ...)
    students_page.create_student(...)            # → student creds
    guardians_page.create_guardian(linked_student=..., ...)
    access_roles_page.create_user(role="Admin", ...)   # generic Admin

    # Phase D — Academic structure
    classes_page.create_class("Grade 6", teacher=teacher.email)
    subjects_page.create_subject("Math", classes=["Grade 6"], teacher=teacher.email)
    classes_page.enroll_student(class_="Grade 6", student=student.email)
    logout(page)

    return SchoolContext(...)
```

Each phase is itself testable — if Phase B fails we know provisioning broke before tests even started.

**Note on conditional setup**: if a scenario's feature pack lacks `academic_year_and_term`, the provisioning playbook will skip phases that depend on it and the related downstream tests will run their negative paths. The loader will validate that each scenario includes enough modules to at least log a SchoolAdmin in (i.e., `school_configuration` is mandatory).

---

## 8. Test organization

Each test file targets one **backend module** (matches the `modules` keys in the feature pack). Inside, tests are grouped by **role**:

```python
# tests/modules/academics/test_classes.py

@pytest.mark.parametrize("school", scenarios(), indirect=True, ids=lambda s: s.id)
class TestClasses:

    def test_school_admin_creates_class(self, school, page):
        if "classes_and_timetables" not in school.feature_modules:
            self._assert_module_inaccessible(page, school.school_admin, "classes_and_timetables")
            return
        # positive path
        login_as(page, school.school_admin)
        classes = ClassesPage(page).open()
        classes.create("Grade 7", teacher=school.teacher.email)
        expect(page.get_by_text("Grade 7")).to_be_visible()

    def test_teacher_cannot_create_class(self, school, page):
        login_as(page, school.teacher)
        # teachers should never see "Create Class" button regardless of feature pack
        ...

    def test_student_cannot_access_classes_admin(self, school, page):
        ...
```

The `_assert_module_inaccessible` helper checks one of:
- The sidebar item for the module is not rendered
- Direct navigation to `/module/<route>` redirects to `/auth/no-access` or `/unauthorized`
- The corresponding API call returns 403

### Role coverage matrix (target)

| Module / Role | Super | School | Admin | Teacher | Student | Guardian | Accountant |
|---|---|---|---|---|---|---|---|
| schools / feature_flag | ✓ | — | — | — | — | — | — |
| school_configuration | — | ✓ | ✓ | — | — | — | — |
| access_roles | — | ✓ | ✓ | — | — | — | — |
| audit_trails | — | ✓ | ✓ | — | — | — | — |
| students / staff / guardians | — | ✓ | ✓ | read | self | ward | — |
| classes / subjects / timetables | — | ✓ | ✓ | manage | view | — | — |
| attendance / assessments | — | ✓ | ✓ | manage | view | view ward | — |
| fees / income_expense / ledger | — | ✓ | ✓ | — | — | — | ✓ |
| payroll / benefits | — | ✓ | ✓ | self | — | — | ✓ |
| library | — | ✓ | ✓ | borrow | borrow | — | — |
| community / messaging | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| incidents / change_requests | — | ✓ | ✓ | report | report | report | — |

Each ✓ is at least one happy-path test; each — means at least one negative-access test for that role × module.

---

## 9. Page objects (lightweight)

Since there are no `data-testid`s, page objects centralize selector strategy:

```python
# tests/pages/super_admin/schools.py
class SchoolsPage(BasePage):
    URL = "/module/schools"

    @property
    def create_button(self):
        return self.page.get_by_role("button", name=re.compile("Create School|Add School", re.I))

    def create_school(self, name, admin_email, address, phone, currency="GHS"):
        self.create_button.click()
        dialog = self.page.get_by_role("dialog")
        dialog.get_by_label(re.compile("School Name", re.I)).fill(name)
        dialog.get_by_label(re.compile("Admin Email", re.I)).fill(admin_email)
        # …
        dialog.get_by_role("button", name=re.compile("^Save$|Create", re.I)).click()
        expect(self.page.get_by_text(name)).to_be_visible()
```

Patterns we'll standardize:
- **Buttons**: `get_by_role("button", name=re.compile(...))`
- **Form fields**: `get_by_label(...)` (Next.js forms use proper `<label>` mostly; where not, fall back to `get_by_placeholder`)
- **Dialogs**: scope to `get_by_role("dialog")` to avoid matching closed modal text
- **Tables**: row matching by content — `page.get_by_role("row").filter(has_text=...)`
- **Toasts**: `get_by_text(re.compile(...))` scoped to the toast container (react-hot-toast renders into a known portal)

If a particular page is too dynamic to target reliably with role/text, I'll surface that and we can decide per-case whether to add a single `data-testid`.

---

## 10. Email / SMS handling

You'll add a backend test mode (controlled by env var or header) that returns the email-derived link in the HTTP response, e.g.:

```json
POST /api/v1/users/forgot-password
{ "email": "..." }
→ 200 OK
{
  "message": "Reset link sent",
  "test_mode": { "reset_link": "https://.../auth/reset_password?token=..." }
}
```

Test helper:

```python
def trigger_password_reset_and_get_link(api, email):
    res = api.post("/users/forgot-password", json={"email": email})
    return res.json()["test_mode"]["reset_link"]
```

Same shape for:
- School admin invite email (on school creation)
- Branch admin invite
- Student/Guardian account creation invites
- Any notification preferences flow

This keeps tests deterministic without an external SMTP/mail-server dependency.

---

## 11. Teardown

A `pytest.fixture(scope="module")` finalizer always runs the delete:

```python
yield school_context
try:
    api.delete(f"/school_profile/{school_context.school_id}", token=superadmin.token)
except Exception as e:
    log.error("school cleanup failed", school_id=..., error=str(e))
    # do not re-raise — we don't want cleanup failure to mask test failures
```

Plus a **session-end sweeper** that lists all schools starting with `TEST_` and deletes any leftovers from prior crashed runs (off by default behind `--sweep-orphans` flag).

---

## 12. Headless toggle

```python
# playwright.config.py uses env
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"

# pytest-playwright reads via --headed / --headless CLI OR conftest fixture override:
@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {
        **browser_type_launch_args,
        "headless": HEADLESS,
        "slow_mo": int(os.getenv("SLOW_MO_MS", "0")),
    }
```

Local dev: `HEADLESS=false` in `.env` (the default). CI: `HEADLESS=true` in the workflow.

---

## 13. Reporting

- `pytest --html=reports/<timestamp>/report.html --self-contained-html`
- On failure: pytest hook (`pytest_runtest_makereport`) takes `page.screenshot()` into `artifacts/<test_id>.png` and links it from the report.
- Logs (`structlog`) go to `reports/<timestamp>/run.log`.

---

## 14. Implementation phases

| Phase | Deliverable | Approx. effort |
|---|---|---|
| **0. Scaffolding** | requirements.txt, conftest, config loader, .env.example, playwright.config, HTML report wiring, screenshot-on-failure hook | small |
| **1. Bootstrap** | SuperAdmin-creation API client, login helper, base page objects, browser/context fixtures | small |
| **2. Provisioning playbook** | Full UI walkthrough flow (sections A–D in §7), `provisioned_school` fixture, teardown finalizer, session sweeper | **large** |
| **3. Module tests — core** | academics, people, account (fees + income/expense), library, configuration. Parameterized over 5 scenarios. | large |
| **4. Module tests — extended** | payroll, ledger, attendance, assessments, statistics, audit_trails, access_roles | medium |
| **5. Role journeys** | End-to-end "day in the life" tests per role (teacher_journey, student_journey, etc.) | medium |
| **6. Cross-cutting** | negative-access matrix, toast/error states, navigation guards | medium |
| **7. CI** | GitHub Actions workflow (or whatever you use) starting backend + frontend, running suite headless, uploading artifacts | small |

---

## 15. Risks & things to call out

1. **The provisioning walkthrough is ~30+ UI steps**. If anything in that sequence is even mildly flaky (a slow toast, a race in academic-year activation), every downstream test in the scenario fails. We should plan for instrumentation here — per-phase logging and per-phase screenshots — so when something breaks we know exactly which step.
2. **No `data-testid`s means refactors on the frontend can break the suite silently**. I'd suggest a lightweight rule on the frontend side: any time a button's user-visible text changes, the corresponding selector in `tests/pages/` is updated in the same PR. That's a process change, not code.
3. **5 schemas × all tests × all roles** could grow to 1000+ test cases. We may want to add `pytest -m smoke` markers so a smaller subset can run pre-commit while the full matrix runs nightly.
4. **The 5 scenarios you'll define** should ensure at least one tests every gatable module both ON and OFF. The scenarios loader can sanity-check the YAML against `module_catalog.py` to flag any module that's never enabled in any scenario (i.e., never positively tested).
5. **Backend test mode** for email links is a small backend change but a real one — it needs to land before reset/invite flows can be tested.

---

## Next step

Suggested kickoff: **Phase 0 + 1 + the SuperAdmin bootstrap** as a small first PR, then Phase 2 (the provisioning playbook) on its own since it's the most complex piece.
