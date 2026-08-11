// autonomous_feature_loop.workflow.js
// ─────────────────────────────────────────────────────────────────────────────
// One iteration of the autonomous feature loop.
//
//   preflight (self-healing)
//     → ensure the provisioning playbook is green
//       → claim a batch of feature units from the ledger
//         → write every unit's test in parallel
//           → group by scenario, then per group: run & fix → render videos
//             → write results back to the ledger
//
// Each invocation is ONE bounded iteration. Re-fire it (via /loop, or by hand)
// until `python scripts/ledger.py stats` reports complete. State lives in
// state/feature_ledger.json, so iterations never redo finished work and the
// run survives being interrupted at any point.
//
// HOW TO RUN
//   Workflow({ scriptPath: 'workflows/autonomous_feature_loop.workflow.js' })
//   Optional args: { batch: 4, agent: 'a1' }
//
// WHY IT GROUPS BY SCENARIO
//   provisioned_school is session-scoped, so every test in ONE pytest run that
//   targets the same scenario shares a single ~40-step UI provisioning. An
//   earlier version verified each unit in its own pytest process and paid that
//   walkthrough per unit — ~107 min/unit. Grouping brought it to ~30-40.
//   Writing stays per-unit and parallel (no browser, so it is cheap); the
//   barrier after it is real and necessary, since units cannot be grouped until
//   every test is written. Groups then pipeline independently so a green group
//   renders its videos without waiting for the slowest sibling.
//
//   Because concurrency is bounded by the number of distinct SCENARIOS (<=5),
//   not by the batch size, a bigger batch adds units per group rather than more
//   concurrent browsers — it amortises provisioning further instead of causing
//   the contention that a per-unit design suffered from.
// ─────────────────────────────────────────────────────────────────────────────

export const meta = {
  name: 'lb-autonomous-feature-loop',
  description: 'One iteration of the LearningBrix autonomous loop: claim feature units from the ledger, write and fix their Playwright tests in parallel, record a narrated demo video for each passing feature, and write results back to the ledger.',
  whenToUse: 'After scripts/preflight.py reports READY. Re-fire until the ledger reports complete. Safe to interrupt — progress is persisted per unit.',
  phases: [
    { title: 'Preflight' },
    { title: 'Provisioning' },
    { title: 'Claim' },
    { title: 'Build' },
    { title: 'Verify' },
    { title: 'Record' },
    { title: 'Report' },
  ],
}

const REPO = '/Users/manoffaith/Desktop/projects/lesalami/learningbrixtests'
const BACKEND = '/Users/manoffaith/Desktop/projects/lesalami/newschoolapp'
const FRONTEND = '/Users/manoffaith/Desktop/projects/lesalami/smsfrontend'
const PY = `${REPO}/.venv/bin/python`
const PYTEST = `${REPO}/.venv/bin/pytest`

// `args` sometimes arrives as a JSON *string* rather than an object. Reading
// .batch off a string yields undefined, so this silently fell back to the
// default of 4 — every run launched as "batch 8" actually claimed 4 units, and
// the batch-size comparison built on it measured nothing.
let ARGS = args
if (typeof ARGS === 'string') {
  try { ARGS = JSON.parse(ARGS) } catch { ARGS = {} }
}
const BATCH = Number(ARGS && ARGS.batch) > 0 ? Number(ARGS.batch) : 4
const AGENT = (ARGS && ARGS.agent) || 'loop'

// Every agent gets this. It encodes the things that are true about THIS
// codebase and were discovered the hard way — an agent that rediscovers them
// burns a fix round for nothing.
const GROUND_RULES = `
Repo under test (write freely):        ${REPO}
Backend app (fix, NEVER commit):       ${BACKEND}
Frontend app (fix, NEVER commit):      ${FRONTEND}

HARD RULES
1. NEVER run \`git commit\`, \`git add\`, \`git push\`, \`git stash\`, \`git checkout\`
   or \`git reset\` inside ${BACKEND} or ${FRONTEND}. Edit files in place and
   leave them dirty. The working tree IS the deliverable. A preflight guardrail
   compares each repo's HEAD against a recorded baseline and fails the run if it
   moved.
2. Use ${PYTEST} and ${PY} — never bare \`pytest\`/\`python\`.
3. The apps are running locally and you may create/update/delete any data in
   them. Every entity you create must carry the "TEST" prefix or the run tag so
   the sweeper can find it.

FACTS ABOUT THIS STACK (verified — do not re-derive)
- QA mode IS implemented in the backend and is ON. Every user-creating response
  carries the generated password under a \`test_mode\` key in the body, and every
  response carries the same JSON in an \`X-Test-Mode\` header (which is how
  list-/null-bodied endpoints like forgot-password are read).
  NEVER hand-roll this capture. Use the helper:
      from tests.fixtures.credentials import capture_credentials, capture_link
      creds = capture_credentials(
          page, lambda: staff_page.create_teaching_staff(**person),
          url_substring="/teacher/", email=person["email"])
      # creds.password now works for a real login
  If capture raises "QA mode is not enabled", run:
      touch ${BACKEND}/.qa_mode_enabled
  and wait ~10s for uvicorn --reload. Do not work around it by guessing
  passwords — the backend implementation is in ${BACKEND}/utils/qa_mode.py and
  is documented in ${REPO}/state/backend_patches.md.
- The backend REJECTS reserved TLDs (.test/.example/.invalid) with a 422.
  All generated emails must use TEST_EMAIL_DOMAIN (learningbrix-qa.com).
  Use tests/fixtures/data_factories.unique_email — never hardcode an address.
- /users/register REFUSES to create SuperAdmins. The SuperAdmin is seeded by
  tests/fixtures/bootstrap.py via \`docker exec\` into the backend container.
  Do not try to register one over HTTP.
- The frontend has NO data-testid attributes. Use role/label/text selectors only
  and do NOT add test ids to the frontend.

FIVE TRAPS ALREADY DIAGNOSED — do not spend fix rounds rediscovering these:
1. NEVER press Enter to commit a date. Several pickers sit in a bare <form>
   with no onSubmit, so Enter fires a NATIVE submit: the page reloads and every
   field collected so far is silently wiped. The symptom is a "Continue" button
   that never enables. Use BasePage.commit_date(), which clicks the panel cell.
2. A SchoolAdmin MUST select a branch before creating any person. They belong to
   no branch, so the frontend reads school_branch_id from a zustand store that
   only the branch row's "View" button on /module/school_admin_dashboard fills.
   Without it every create posts school_branch_id: 0 and the backend answers
   404 "The Branch does not exist". Use BranchesPage.select_branch(name).
3. A Radix Select whose value matches no option (e.g. non-teaching role, which
   initialises to role_id 0) renders an EMPTY trigger, NOT its placeholder. So
   filtering a combobox by placeholder text finds nothing — use
   BasePage.select_option_by_label() to anchor on the adjacent <label>.
4. Any selector text containing "/" — "dd/mm/yyyy", "2026/2027" — must go
   through tests.pages.base.as_pattern(). Playwright serialises a Pattern as
   /<source>/<flags> and a bare slash closes that literal early, raising
   InvalidSelectorError.
5. Labels are bare <label> with no \`for\`, so get_by_label never binds;
   BasePage.fill_labeled falls through to the placeholder. Always give the
   placeholder as an alternation branch in the field pattern.

6. Emails are SUPPRESSED while QA mode is on. Do not "fix" a flow by trying to
   make SMTP work. Sending used to run inside the request, so once the Gmail
   daily quota was hit every school creation returned 400 "Daily user sending
   limit exceeded". The message is still captured — read it through
   tests/fixtures/credentials.capture_link.
7. Leftover test data is swept automatically by preflight above 60 schools.
   /school_profile/ and /feature-packs/ both cap their responses at 100 rows,
   and past that a newly created feature pack falls outside the page the
   assign-pack dialog renders — provisioning then fails at "assign pack" with a
   selector timeout that looks nothing like the cause. If you ever see that,
   run: ${PY} scripts/cleanup_test_data.py --yes

ALREADY FIXED IN THE BACKEND (do not re-diagnose)
- DELETE /school_profile/{id} now works; the ORM relationships were nulling
  child FKs instead of letting Postgres cascade. See state/backend_patches.md.
- The backend runs in the docker container \`schoolapp\` on :8093; the frontend
  dev server is on :3000.

DEFECT vs BEHAVIOUR CHANGE — the line you must not cross alone
You may fix DEFECTS in the app in place: something that crashes, loses data,
returns 500, or contradicts itself. Examples already taken: a TypeError on a
legal week of lessons, a bulk create silently discarding fields, a delete that
could never succeed.

You may NOT, on your own, add capability or change product behaviour, even when
a test cannot pass without it. Specifically, NEVER do any of these unattended:
  - grant a role permissions it does not have
  - add an API route, or a request parameter the backend never accepted
  - enforce a gate/licence check that was previously unenforced
  - implement a feature whose absence you inferred was accidental
Mark the unit BLOCKED with the precise product question instead, and move on.

A MISSING FEATURE IS NOT AUTOMATICALLY A BUG. Absence is often deliberate.
Worked example: the frontend ships an edit-comment flow calling
PUT /feed/comments/{id}, which the backend does not implement. That is BY
DESIGN — community posts and comments are immutable, deliberately, like Twitter.
Adding the route would have been wrong. Do not add it.

Anything you do change in ${BACKEND} or ${FRONTEND} must be appended to
${REPO}/state/app_changes_review.md, classified as "defect fix" or "behaviour
change", with the evidence that made you sure.

WHAT COUNTS AS A BLOCKER
Fix these yourself, silently — they are NOT blockers:
  selector drift, timing/flake, missing fixtures, an outright app DEFECT as
  defined above, a crashed backend container (docker start schoolapp), a wrong
  assumption in an existing page object.
Escalate ONLY these, by marking the unit blocked in the ledger and moving on:
  - anything on the "may NOT" list above — a product decision, not a defect
  - a change that would require a destructive DB migration
  - a third-party credential nobody has (SMTP, payment sandbox, SMS gateway)
  - the same root cause surviving 3 fix rounds
A blocker blocks ONE unit. Never stop the run for it.
`.trim()

// ─── Phase: Preflight ───────────────────────────────────────────────────────
phase('Preflight')

const preflight = await agent(`
Get the environment ready. Do not write test code in this step.

Run: cd ${REPO} && ${PY} scripts/preflight.py --json

That script self-heals what it can (venv, deps, chromium, backend container
restart, SuperAdmin seed, feature queue) and reports what it cannot.

If it reports ready=false:
- frontend unreachable  → try starting it: \`cd ${FRONTEND} && npm run dev\` in
  the background, wait up to 90s for http://localhost:3000/auth/login, re-run
  preflight.
- backend unreachable   → \`docker start schoolapp\`, wait, re-run preflight.
- anything else         → report ready=false with the failing check names.

Also run: ${PY} scripts/ledger.py release --stale-minutes 45
(returns units abandoned by a previous crashed iteration to the queue).

Report the final state.
`, {
  label: 'preflight',
  phase: 'Preflight',
  schema: {
    type: 'object',
    required: ['ready'],
    properties: {
      ready: { type: 'boolean' },
      failing_checks: { type: 'array', items: { type: 'string' } },
      detail: { type: 'string' },
    },
  },
})

if (!preflight || !preflight.ready) {
  log(`Preflight could not reach a runnable state: ${preflight?.failing_checks?.join(', ') ?? 'preflight agent died'}`)
  return {
    iteration: 'aborted',
    stage: 'preflight',
    failing_checks: preflight?.failing_checks ?? [],
    detail: preflight?.detail ?? '',
  }
}

log(`Preflight green. Effective batch: ${BATCH}, agent: ${AGENT}.`)

// ─── Phase: Provisioning ────────────────────────────────────────────────────
// Every feature test needs a provisioned school. If the playbook does not exist
// or is red, no unit can pass, so this gate runs before any unit is claimed.
phase('Provisioning')

const provisioning = await agent(`
${GROUND_RULES}

Ensure the school provisioning playbook exists and passes.

1. Check whether ${REPO}/tests/flows/school_provisioning.py exists.
   - If it does NOT: report exists=false and status="absent". Do not build it
     here; the caller runs workflows/build_provisioning.workflow.js for that.
   - If it does: run
       cd ${REPO} && ${PYTEST} tests/test_provisioning_smoke.py -q --no-header 2>&1 | tail -40
     and report whether it passes.

2. If it exists but fails, diagnose and fix it — up to 3 attempts. Compare the
   failing page object against the actual frontend source side by side. Re-run
   after each fix.

Report honestly. Do not claim green without a passing run.
`, {
  label: 'provisioning-gate',
  phase: 'Provisioning',
  schema: {
    type: 'object',
    required: ['exists', 'status'],
    properties: {
      exists: { type: 'boolean' },
      status: { enum: ['green', 'red', 'absent'] },
      detail: { type: 'string' },
    },
  },
})

if (!provisioning || provisioning.status === 'absent') {
  log('Provisioning playbook does not exist yet — running the Phase 2 builder workflow first.')
  const built = await workflow({ scriptPath: `${REPO}/workflows/build_provisioning.workflow.js` })
  log(`Provisioning builder finished: ${JSON.stringify(built).slice(0, 300)}`)
  if (!built || (built.phase_2 !== 'green' && built.phase_2 !== 'green-after-fix')) {
    return { iteration: 'aborted', stage: 'provisioning', detail: built }
  }
} else if (provisioning.status === 'red') {
  log('Provisioning playbook is red and could not be fixed — no feature unit can pass. Stopping this iteration.')
  return { iteration: 'aborted', stage: 'provisioning', detail: provisioning.detail }
}

// ─── Phase: Claim ───────────────────────────────────────────────────────────
phase('Claim')

const claim = await agent(`
Claim the next batch of feature units from the ledger. Do NOT write any code.

Run: cd ${REPO} && ${PY} scripts/ledger.py next --limit ${BATCH} --agent ${AGENT}

That prints a JSON array of claimed units. Return them verbatim in "units".
Then run \`${PY} scripts/ledger.py stats\` and return its numbers.

If the array is empty, set units to [] — the queue is drained.
`, {
  label: 'claim-batch',
  phase: 'Claim',
  schema: {
    type: 'object',
    required: ['units'],
    properties: {
      units: {
        type: 'array',
        items: {
          type: 'object',
          required: ['id'],
          properties: {
            id: { type: 'string' },
            module: { type: 'string' },
            title: { type: 'string' },
            subtitle: { type: 'string' },
            roles: { type: 'array', items: { type: 'string' } },
            intent: { type: 'string' },
            scenario: { type: 'string' },
            test_path: { type: 'string' },
            video: { type: 'boolean' },
          },
        },
      },
      remaining: { type: 'number' },
      done: { type: 'number' },
      blocked: { type: 'number' },
    },
  },
})

const units = (claim && claim.units) || []
if (units.length === 0) {
  log('Ledger is drained — every feature unit is done or blocked.')
  return { iteration: 'complete', done: claim?.done ?? 0, blocked: claim?.blocked ?? 0 }
}

log(`Claimed ${units.length} unit(s): ${units.map(u => u.id).join(', ')}`)

// ─── Phases: Build → Verify → Record ────────────────────────────────────────
// pipeline(), not parallel(): a unit that goes green records its video straight
// away instead of waiting on the slowest sibling's test-writing stage.
phase('Build')

// ── Stage 1: write every claimed unit's test, in parallel ───────────────────
// A barrier is genuinely required after this stage: units cannot be grouped by
// scenario until every test is written, and the grouping is the whole point.
const written = await parallel(units.map(unit => () => agent(`
${GROUND_RULES}

Write the Playwright test for ONE feature unit.

  id:        ${unit.id}
  module:    ${unit.module}
  route:     /module/${unit.route || unit.module}
  intent:    ${unit.intent}        (manage = create/edit happy path,
                                    view = read-only happy path,
                                    negative = module disabled, expect denial,
                                    mandatory = module can NEVER be unlicensed,
                                      assert it is still reachable on the
                                      "minimal" pack — see step 4)
  roles:     ${(unit.roles || []).join(', ')}
  scenario:  ${unit.scenario}      (the feature-pack mix this runs against)
  file:      ${unit.test_path}
  video:     ${unit.video}

Steps:
1. READ FIRST, in this order:
   - ${REPO}/tests/pages/base.py           (reuse its helpers, do not duplicate)
   - ${REPO}/tests/flows/school_provisioning.py  (SchoolContext shape)
   - ${REPO}/tests/conftest.py             (the scenario marker, see step 3)
   - ${REPO}/config/feature_scenarios.yaml (what "${unit.scenario}" enables)
   - an existing test under ${REPO}/tests/modules/ for house style
   - the FRONTEND source for this module under
     ${FRONTEND}/src/app/module/${unit.route || unit.module}/
     Get the REAL button labels, form labels and toast text. Quote them with
     re.compile(..., re.I).
2. FIRST check whether this unit's test already exists. A run can be
   interrupted (session limit, crash) after the test was written but before it
   was verified, so the unit comes back round with its file already on disk.
   Look in ${unit.test_path} for a test matching THIS unit${unit.video ? ` —
   its @pytest.mark.demo would carry feature_id="${unit.id}"` : ` (its intent
   and role)`}.
   - If it exists: do NOT write a second one. Review it against the guidance
     below, repair anything wrong, and report its path and name.
   - If it does not: add it to ${unit.test_path} (create the file and any
     __init__.py if missing). If the file already holds tests for OTHER units,
     ADD to it — never rewrite it.
   Two tests for one unit is a defect: they duplicate a provisioning-heavy run
   and the second video silently overwrites the first.
3. MANDATORY: mark the test @pytest.mark.scenario("${unit.scenario}").
   provisioned_school is parametrised over every scenario, and each param costs
   a full UI provisioning walkthrough. The marker deselects the rest, so the
   whole batch shares ONE provisioned school per scenario. A test without it
   provisions five schools by itself and wrecks the run's throughput.
4. For intent=negative, assert the denial the app actually implements: the
   sidebar entry is absent, OR direct navigation redirects to a no-access page,
   OR the API returns 403. Check which one is true before asserting.

   For intent=mandatory, assert the OPPOSITE, and do not treat reachability as a
   licensing hole. The pack builder locks the "people" and "governance" groups
   into every pack (BASIC_GROUPS in
   ${FRONTEND}/src/app/module/feature_flag/{create,edit}/page.tsx) — only
   guardians and families are optional inside them. Governance is core and
   always on: CONFIRMED INTENDED by the user, not a gap. So the test proves the
   module is still reachable on the "minimal" pack — the module loads, its
   sidebar entry is offered, its API answers — and that is the whole assertion.
   Do NOT add or tighten any gate here.
${unit.video ? `5. This unit records video, so the test MUST take the \`demo\` fixture and
   carry the marker:

     @pytest.mark.demo(
         feature_id="${unit.id}",
         title="${(unit.title || '').replace(/"/g, '\\"')}",
         subtitle="${(unit.subtitle || '').replace(/"/g, '\\"')}",
     )
     def test_...(demo, provisioned_school, ...):
         with demo.step("Log in as ..."):
             ...

   Drive the browser through \`demo.page\`, NOT the \`page\` fixture. The video
   must tell the whole story on its own: START from the login page, sign in as
   the role, navigate to the module through the UI, then do the thing. Do NOT
   deep-link straight to the module route — a viewer should see how a real user
   gets there. Wrap every meaningful action in a \`with demo.step("...")\` block;
   those captions are burned into the video, so write them as short sentences a
   viewer would want to read, not as descriptions of the code. 5-9 steps.` :
`5. This unit records no video — use the normal \`page\` fixture.`}
6. Do NOT run the test yet. The next stage runs the whole batch at once.

Report the file you wrote and the test function name.
`, {
  label: `write:${unit.id}`,
  phase: 'Build',
  schema: {
    type: 'object',
    required: ['test_path'],
    properties: {
      test_path: { type: 'string' },
      test_name: { type: 'string' },
      notes: { type: 'string' },
    },
  },
}).then(async (result) => {
  // Record progress immediately so a crash mid-iteration does not lose the
  // fact that the test now exists.
  await agent(`Run exactly this and report the resulting status: cd ${REPO} && ${PY} scripts/ledger.py set ${unit.id} --status test_written --test-path "${result?.test_path || unit.test_path}"`,
    { label: `ledger:${unit.id}:written`, phase: 'Build' })
  return { unit, written: result }
})))

// ── Group by scenario ───────────────────────────────────────────────────────
// This is the throughput fix. provisioned_school is session-scoped, so every
// test in ONE pytest invocation that targets the same scenario shares a single
// provisioning. Running a pytest per unit instead paid that ~40-step
// walkthrough once per unit; measured at ~107 min/unit. Grouping collapses it
// to once per scenario for the whole batch.
const groups = []
for (const entry of written.filter(Boolean)) {
  const key = entry.unit.scenario || 'unpinned'
  let group = groups.find(g => g.scenario === key)
  if (!group) {
    group = { scenario: key, entries: [] }
    groups.push(group)
  }
  group.entries.push(entry)
}

log(`Grouped ${written.filter(Boolean).length} unit(s) into ${groups.length} scenario group(s): ` +
    groups.map(g => `${g.scenario}(${g.entries.length})`).join(', '))

// ── Stages 2+3, per scenario group ─────────────────────────────────────────
// pipeline: a group that goes green renders its videos immediately rather than
// waiting on the slowest sibling group.
const results = await pipeline(
  groups,

  // Verify the whole group in ONE pytest run.
  (group) => agent(`
${GROUND_RULES}

Run and fix EVERY test in scenario group "${group.scenario}" in a SINGLE pytest
invocation. Running them separately re-provisions a school per test and is the
single biggest waste in this pipeline — do not do it.

Units in this group:
${group.entries.map(e => `  - ${e.unit.id}  (video: ${e.unit.video})\n      ${e.written?.test_path || e.unit.test_path}`).join('\n')}

1. Run them together, deselecting everything else:
     cd ${REPO} && ${PYTEST} <all the test files above, space separated> \\
       -q --no-header 2>&1 | tail -80
   All these tests carry @pytest.mark.scenario("${group.scenario}"), so the
   session provisions ONE school and every test reuses it.
   If a test is MISSING that marker, add it — that is a bug in the written test.

2. Up to 3 fix rounds over the whole group. Each round:
   a. Read the failures. Identify the ROOT cause of each — do not guess.
   b. Decide where each bug is:
      - test/page-object wrong  → fix it here in ${REPO}
      - the APP is genuinely broken → fix it in ${BACKEND} or ${FRONTEND}, in
        place, WITHOUT committing. Say so explicitly in your report.
   c. Re-run the whole group.

Never paper over a failure with try/except, a bare \`assert True\`, a skip, or a
loosened assertion that no longer tests the feature. If a test cannot pass
honestly, that unit is "blocked", not a weakened test. One blocked unit must not
stop the others — keep the rest of the group moving.

3. The demo fixture records a video during this run, so a passing video unit
   already has its raw footage. Do NOT re-run tests just to record.

4. Write each unit's result to the ledger:
     passing → ${PY} scripts/ledger.py set <id> --status passing
     blocked → ${PY} scripts/ledger.py set <id> --status blocked --reason "<why>" --error "<tail>"
     failed  → ${PY} scripts/ledger.py set <id> --status claimed --error "<tail>"

Report one entry per unit in this group.
`, {
    label: `verify:${group.scenario}`,
    phase: 'Verify',
    schema: {
      type: 'object',
      required: ['results'],
      properties: {
        results: {
          type: 'array',
          items: {
            type: 'object',
            required: ['id', 'outcome'],
            properties: {
              id: { type: 'string' },
              outcome: { enum: ['passing', 'blocked', 'failed'] },
              test_path: { type: 'string' },
              detail: { type: 'string' },
              blocked_reason: { type: 'string' },
            },
          },
        },
        app_fixes: { type: 'string', description: 'Any fix made in the backend or frontend repo' },
      },
    },
  }),

  // Render every passing video unit in the group.
  (verdict, group) => {
    const passing = (verdict?.results || []).filter(r => r.outcome === 'passing')
    const videoUnits = group.entries
      .filter(e => e.unit.video && passing.some(r => r.id === e.unit.id))
      .map(e => e.unit)

    if (!videoUnits.length) {
      return { scenario: group.scenario, results: verdict?.results || [], videos: [] }
    }

    return agent(`
${GROUND_RULES}

Render the demo videos for the units that just passed in scenario group
"${group.scenario}".

Units to render (slug = the id with every non-alphanumeric character replaced
by an underscore):
${videoUnits.map(u => `  - ${u.id}`).join('\n')}

1. The verify run already wrote artifacts/videos/raw/<slug>.webm and a
   <slug>.json manifest for each. Confirm both exist. If a manifest is missing,
   that test did not actually run with the demo fixture — report it rather than
   inventing a video.

2. Render them:
     cd ${REPO} && ${PY} scripts/render_video.py <slug> <slug> ...
   Expect "✓ <slug>: rendered" for each. "skipped_failed" means the test did not
   pass — report that honestly instead of forcing it.

3. Sanity-check each output rather than trusting the exit code:
     ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 artifacts/videos/out/<slug>.mp4
   A video under ~6s means the steps had no dwell time and the footage is
   unusable; report it as failed rather than marking it done.

4. Mark each rendered unit done:
     ${PY} scripts/ledger.py set <id> --status video_done --video-path artifacts/videos/out/<slug>.mp4

Report one entry per unit you were asked to render.
`, {
      label: `record:${group.scenario}`,
      phase: 'Record',
      schema: {
        type: 'object',
        required: ['results'],
        properties: {
          results: {
            type: 'array',
            items: {
              type: 'object',
              required: ['id', 'outcome'],
              properties: {
                id: { type: 'string' },
                outcome: { enum: ['video_done', 'passing', 'blocked', 'failed'] },
                video_path: { type: 'string' },
                duration_s: { type: 'number' },
                detail: { type: 'string' },
              },
            },
          },
        },
      },
    }).then(rendered => ({
      scenario: group.scenario,
      results: verdict?.results || [],
      videos: rendered?.results || [],
    }))
  },
)


// ─── Phase: Report ──────────────────────────────────────────────────────────
phase('Report')

// Each pipeline result is one scenario GROUP — {scenario, results[], videos[]}
// — not a single unit, so per-unit outcomes have to be flattened back out.
// Reading r.id straight off the group is what produced "undefined: undefined"
// in an earlier run's report.
const settled = []
for (const group of results.filter(Boolean)) {
  const videoById = new Map((group.videos || []).map(v => [v.id, v]))
  for (const unit of group.results || []) {
    const video = videoById.get(unit.id)
    settled.push({
      id: unit.id,
      scenario: group.scenario,
      outcome: video?.outcome || unit.outcome,
      video_path: video?.video_path,
      blocked_reason: unit.blocked_reason,
    })
  }
}
const summary = await agent(`
Summarise this iteration. Do NOT write code or change any status.

1. cd ${REPO} && ${PY} scripts/ledger.py stats
2. ${PY} scripts/render_video.py --index-only
3. If ${REPO}/state/blockers.md exists, read it and list any blockers ADDED in
   this iteration (the units below), with their reasons.

Units attempted this iteration:
${settled.map(r => `  - ${r.id}: ${r.outcome}`).join('\n') || '  (none)'}

Also verify the guardrail held:
  git -C ${BACKEND} rev-parse HEAD
  git -C ${FRONTEND} rev-parse HEAD
and compare against ${REPO}/state/repo_baseline.json. Report guardrail_ok.
Report app_files_changed: the count from \`git -C <repo> status --porcelain\`
for each app repo (these SHOULD be non-zero if agents fixed app bugs).
`, {
  label: 'iteration-summary',
  phase: 'Report',
  schema: {
    type: 'object',
    required: ['done', 'blocked', 'remaining', 'guardrail_ok'],
    properties: {
      done: { type: 'number' },
      blocked: { type: 'number' },
      remaining: { type: 'number' },
      complete: { type: 'boolean' },
      guardrail_ok: { type: 'boolean' },
      new_blockers: { type: 'array', items: { type: 'string' } },
      app_files_changed: { type: 'string' },
      index_path: { type: 'string' },
      notes: { type: 'string' },
    },
  },
})

log(`Iteration done — ${summary?.done ?? '?'} complete, ${summary?.blocked ?? '?'} blocked, ${summary?.remaining ?? '?'} remaining.`)

return {
  iteration: 'ok',
  attempted: settled.map(r => ({ id: r.id, outcome: r.outcome, scenario: r.scenario })),
  ...summary,
}
