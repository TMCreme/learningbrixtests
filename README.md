# LearningBrix Tests

Playwright integration test suite for the LearningBrix school management
application. Drives the full multi-tenant lifecycle through the browser:
SuperAdmin creates a school, the SchoolAdmin onboards branches/users/academic
calendar, then each role exercises their permitted modules. Schools are torn
down in teardown.

The full design lives in [docs/plan.md](docs/plan.md).

---

## Quick start

```bash
# 1. Clone & enter
git clone <repo-url> learningbrixtests
cd learningbrixtests

# 2. Python env + deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 3. Configure
cp .env.example .env
# Edit .env — at minimum set SUPERADMIN_PASSWORD and confirm the backend/frontend URLs.

# 4. Make sure the apps under test are running
#    - backend:  uvicorn app:app --reload          (port 8000)
#    - frontend: npm run dev   (in the smsfrontend repo, port 3000)

# 5. Smoke check
pytest tests/test_smoke.py -v
```

`pytest tests/test_smoke.py` should pass once the backend and frontend are up
and the `.env` is filled in. From there, the rest of the suite layers on top.

---

## What it does (and doesn't)

**Does**
- Creates a SuperAdmin via the backend API at session start (idempotent).
- Logs in via the **UI** and drives the full school provisioning flow.
- Parameterizes every module test over **N feature-pack scenarios**
  (see `config/feature_scenarios.yaml`). Each test asserts the **positive
  path** when its module is enabled and the **negative path** (access denied)
  when it isn't.
- Covers all major roles: SuperAdmin, SchoolAdmin, Admin, Teacher, Student,
  Guardian, Accountant.
- Tears down every school created — even on failure — via
  `DELETE /api/v1/school_profile/{id}`.
- Captures a screenshot of the failing page and embeds it in the HTML report.

**Doesn't (yet)**
- Send real email/SMS. The backend is expected to expose a "test mode"
  that returns invite/reset links inline in the HTTP response under a
  `test_mode` key. Toggle with `BACKEND_TEST_MODE=true`.
- Run tests in parallel. Serial only in v1 to keep cross-school isolation
  simple.
- Cross-browser. Chromium only. Firefox/WebKit can be added later via
  pytest-playwright's `--browser` flag.

---

## Configuration

Everything tunable lives in `.env`. See `.env.example` for the full list.

The most important knobs:

| Variable | Purpose |
|---|---|
| `BACKEND_BASE_URL` / `FRONTEND_BASE_URL` | Where the apps under test are running. |
| `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` | The session-bootstrap account. |
| `BACKEND_TEST_MODE` | When true, the backend should return email-derived links in the response body so the suite can read them without an SMTP server. |
| `HEADLESS` | `false` for local dev (watch the browser drive itself), `true` for CI. |
| `SLOW_MO_MS` | Slows every action by N ms — useful when debugging. |
| `DELETE_ON_FAILURE` | If true (default), schools get torn down even when tests fail. Flip to false for live inspection. |

---

## Feature-pack scenarios (the test matrix)

Each entry in `config/feature_scenarios.yaml` provisions one school with a
specific feature-pack mix. Every module test runs once per scenario:

- If the test's module is in the scenario's `modules` list → **positive
  path** (the feature should work).
- If it isn't → **negative path** (UI should hide the module / direct
  navigation should redirect to `/auth/no-access` or the API should
  return 403).

Define ~5 scenarios so that every module in `config/module_catalog.py` is
enabled by at least one scenario and disabled by at least one other. The
loader (`config/scenarios.py`) prints warnings for modules that are never
toggled either way.

A starting template:

```yaml
scenarios:
  - id: full_access
    school_name: "TEST Mountain View Academy"
    feature_pack_name: "TEST All Modules"
    modules: [home, students, staff, ..., school_configuration]

  - id: academics_only
    school_name: "TEST Sunrise Prep"
    feature_pack_name: "TEST Academics Pack"
    modules: [home, school_configuration, students, staff,
              classes_and_timetables, subjects, attendance,
              lessons, assessments, academic_year_and_term]

  # … 3 more scenarios with different module subsets
```

`school_configuration` is required in every scenario — without it, the
SchoolAdmin can't complete the onboarding walkthrough.

---

## Running tests

```bash
# Everything
pytest

# A single module
pytest tests/modules/academics -v

# Only smoke (Phase 0/1 sanity checks)
pytest -m smoke

# Headed (default), with a small slow-mo
HEADLESS=false SLOW_MO_MS=250 pytest tests/modules/people/test_students.py

# Headless (CI mode)
HEADLESS=true pytest

# Override a single setting without editing .env
BACKEND_BASE_URL=http://staging.example.com pytest tests/test_smoke.py
```

### Artifacts

- HTML report: `reports/report.html` (self-contained, shareable)
- Screenshot on failure: `artifacts/<test-nodeid>.png`, also embedded in the
  HTML report.

---

## Project layout

```
learningbrixtests/
├── conftest.py                      # session fixtures + screenshot hook
├── pytest.ini                       # markers, HTML report wiring
├── requirements.txt
├── .env.example
│
├── config/
│   ├── settings.py                  # typed env loader (pydantic-settings)
│   ├── module_catalog.py            # canonical list of backend modules
│   ├── scenarios.py                 # YAML loader + validator
│   └── feature_scenarios.yaml       # ← edit this to define your scenarios
│
├── tests/
│   ├── conftest.py                  # per-test timeouts, helpers
│   ├── fixtures/
│   │   ├── api_client.py            # httpx wrapper (setup-only backend calls)
│   │   ├── bootstrap.py             # idempotent SuperAdmin seed
│   │   └── data_factories.py        # Faker + unique-per-run tag
│   ├── pages/                       # lightweight page objects (role/text selectors)
│   │   ├── base.py
│   │   ├── login.py
│   │   └── super_admin/
│   ├── flows/                       # multi-step UI flows (e.g. provision_school)
│   ├── modules/                     # module-by-module tests, parameterized over scenarios
│   └── role_matrix/                 # end-to-end "day in the life" tests per role
│
├── docs/
│   └── plan.md                      # full design doc
│
├── reports/                         # html report output (gitignored)
└── artifacts/                       # screenshots (gitignored)
```

---

## Adding a new module test

1. Make sure the module key exists in `config/module_catalog.py`.
2. Make sure at least one scenario in `feature_scenarios.yaml` enables it
   (positive path) and at least one disables it (negative path).
3. Create `tests/modules/<category>/test_<feature>.py`. Use the
   `provisioned_school` fixture (arriving in Phase 2) and gate behavior on
   `if "<module_key>" in school.feature_modules`.
4. Build any new UI interactions into `tests/pages/<area>/` so selectors are
   centralized.

---

## Selectors

The frontend doesn't use `data-testid` attributes, so the suite relies on
Playwright's role/text/label selectors:

- Buttons: `page.get_by_role("button", name=re.compile("...", re.I))`
- Form fields: `page.get_by_label(...)` with `get_by_placeholder(...)` as
  fallback.
- Modals: scope to `page.get_by_role("dialog")` before reaching inside.
- Tables: `page.get_by_role("row").filter(has_text=...)`.
- Toasts: helper on `BasePage` — react-hot-toast renders into a portal that
  the helper matches by text.

If a page is genuinely too dynamic to target this way, flag it and we'll add
a single `data-testid` to the frontend rather than write a brittle CSS
selector.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `pytest.exit: Backend not reachable` | Backend isn't running on `BACKEND_BASE_URL`, or it's running but `/api/v1/roles/` is unreachable. |
| `Role 'SuperAdmin' not found` | Backend started without seeding roles. Restart it — `seed_roles_and_permissions()` runs at app startup. |
| `Login failed for playwright-super@...` | Stale `SUPERADMIN_PASSWORD` in `.env` doesn't match what's already in the DB. Either wipe the user from the DB or set the password in `.env` to match. |
| Toast doesn't appear / test times out | Animation timing or the toast lives in a portal we haven't targeted. Tag the helper in `tests/pages/base.py::BasePage.toast` and adjust. |
| Frontend redirects to `/auth/no-access` mid-test | The current scenario doesn't include this module — the test should be on its negative path, not the positive one. Check the scenario YAML. |

---

## Status

| Phase | Status |
|---|---|
| 0. Scaffolding (config, fixtures, hooks) | ✅ done |
| 1. Bootstrap (SuperAdmin seed, login helpers) | ✅ done |
| 2. School provisioning playbook (UI walkthrough) | ⏳ next |
| 3. Module tests — core (academics, people, account, library, configuration) | ⏳ |
| 4. Module tests — extended (payroll, ledger, attendance, …) | ⏳ |
| 5. Role-journey tests | ⏳ |
| 6. Cross-cutting (negative-access matrix, error states) | ⏳ |
| 7. CI integration | ⏳ |
