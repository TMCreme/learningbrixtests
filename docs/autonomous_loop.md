# The autonomous feature loop

Agents work through the feature queue in parallel: write a Playwright test,
make it pass, record a narrated demo video of the passing feature, and record
the result. It runs unattended and only stops for a real blocker.

This document is the operating manual. [plan.md](plan.md) is the original suite
design; where the two disagree, this one is current — several of plan.md's
assumptions turned out to be wrong (see [What plan.md got wrong](#what-planmd-got-wrong)).

---

## Running it

```bash
# 0. One-time: make the environment runnable (idempotent, self-healing)
.venv/bin/python scripts/preflight.py

# 1. One iteration
#    (from a Claude Code session)
Workflow({ scriptPath: 'workflows/autonomous_feature_loop.workflow.js' })

# 2. Or let it self-pace until the queue drains
/loop Workflow({ scriptPath: 'workflows/autonomous_feature_loop.workflow.js' })
```

Check on it at any time:

```bash
.venv/bin/python scripts/ledger.py stats     # progress
cat state/blockers.md                        # what needs a human
open artifacts/videos/out/index.html         # the videos so far
```

---

## How it fits together

```
┌─ scripts/preflight.py ──────────────────────────────────────────────┐
│  venv · deps · chromium · ffmpeg · .env · backend · frontend        │
│  QA mode · SuperAdmin · feature queue · git guardrail               │
│  Self-heals what it can. Only reports what it genuinely cannot fix. │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─ workflows/autonomous_feature_loop.workflow.js ─────────────────────┐
│  Preflight → Provisioning gate → Claim N units                      │
│                                      │                              │
│              ┌───────────────────────┴──────────────────┐           │
│              ▼ (per unit, independently — no barrier)   ▼           │
│        Build: write the test                                        │
│        Verify: run it, fix root causes, up to 3 rounds              │
│        Record: re-run with video, render, verify duration           │
│              └───────────────────────┬──────────────────┘           │
│                                      ▼                              │
│                        Report + ledger writeback                    │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
      state/feature_ledger.json   ← the loop's memory
      state/blockers.md           ← the only thing that asks for a human
      artifacts/videos/out/       ← the deliverable
```

Each invocation is **one bounded iteration**. State lives in the ledger, so
iterations never redo finished work and the run survives being interrupted at
any point.

---

## The feature queue

`config/features.yaml` is generated from `config/module_catalog.py` crossed with
the role matrix in [plan.md §8](plan.md):

```bash
.venv/bin/python scripts/build_feature_queue.py     # regenerate
.venv/bin/python scripts/ledger.py init             # seed new units, keep progress
```

A unit is one **module × role × intent**:

| intent | what it asserts | video |
|---|---|---|
| `manage` | create/edit happy path | yes |
| `view` | read-only happy path | yes |
| `negative` | module disabled by the feature pack → access denied | no |

Currently **93 units, 62 with video**. Negative units get no video — "access
denied" is a correct outcome but not a feature demo.

Each unit names the scenario it runs against. Positive units get a scenario
where the module is enabled; negative units get one where it is not. The
generator picks the *most specialised* enabling scenario, so demos are recorded
against a realistically-scoped school rather than always the everything-on one.

Regenerating the queue rewrites `features.yaml` but **not** the ledger, so
progress survives.

---

## The ledger

`state/feature_ledger.json`. This is what makes the loop a loop rather than a
one-shot.

```
pending ──claim──▶ claimed ──▶ test_written ──▶ passing ──▶ video_done
   ▲                  │                            │
   └──── release ─────┘                            └──▶ blocked
```

```bash
.venv/bin/python scripts/ledger.py stats
.venv/bin/python scripts/ledger.py next --limit 4 --agent a1
.venv/bin/python scripts/ledger.py set <id> --status passing
.venv/bin/python scripts/ledger.py set <id> --status blocked --reason "..."
.venv/bin/python scripts/ledger.py release --stale-minutes 45
```

Writes take an exclusive `flock`, so parallel agents cannot double-claim a unit
or clobber each other's status. `release` returns units held by agents that died
mid-flight back to the queue — the first thing each iteration does.

---

## What counts as a blocker

This is the policy that decides whether the loop actually runs unattended. Get
it wrong in one direction and agents stop constantly; wrong in the other and
they grind forever on something unfixable.

**Agents fix these silently. Not blockers:**
- selector drift, timing and flake
- missing fixtures or page objects
- a genuine frontend or backend bug — **fix it in place**
- a crashed backend container — restart it
- a wrong assumption baked into an existing page object

**Escalate only these** — mark the unit `blocked`, then keep going:
- a change requiring a destructive DB migration
- a third-party credential nobody has (SMTP, payment sandbox, SMS gateway)
- two equally-valid product behaviours, where "fixing" it would change product
  semantics rather than repair a defect
- the same root cause surviving 3 fix rounds

**A blocker blocks one unit, never the run.** Blocked units land in
`state/blockers.md` with their reason and last error.

The one thing agents must never do is make a test pass dishonestly: no bare
`assert True`, no `try/except` swallowing the failure, no skip, no assertion
loosened until it no longer tests the feature. If it cannot pass honestly, that
is a blocker.

---

## The git guardrail

Agents may **edit** `newschoolapp` and `smsfrontend` — fixing app bugs is part
of the job — but must never **commit** to them. The working tree is the
deliverable.

`scripts/preflight.py` records each repo's `HEAD` in `state/repo_baseline.json`
on first run and compares on every later run. A moved HEAD fails the preflight
loudly. Working-tree changes are expected and are not a violation.

Every backend change is documented in
[state/backend_patches.md](../state/backend_patches.md), including how to revert it.

---

## Videos

Recording is opt-in per test, via a marker plus the `demo` fixture:

```python
@pytest.mark.demo(
    feature_id="academics.classes_and_timetables.manage.school_admin",
    title="Classes & Timetables",
    subtitle="SchoolAdmin creates a class",
)
def test_school_admin_creates_class(demo, ...):
    with demo.step("Log in as SchoolAdmin"):
        ...
    with demo.step('Create class "Grade 6"'):
        ...
```

Each `demo.step(...)` records the elapsed time of that action; those become the
burned-in captions. Write them as short sentences a viewer would want to read,
not as descriptions of the code. Four to nine steps is the right length.

```
tests/fixtures/video.py   dedicated slow-mo browser + recording context
tests/support/demo.py     the step recorder and its manifest
scripts/captions.py       title card + caption strips (Pillow)
scripts/render_video.py   ffmpeg composite → artifacts/videos/out/<slug>.mp4
```

```bash
.venv/bin/python scripts/render_video.py            # render everything pending
.venv/bin/python scripts/render_video.py --force    # re-render
.venv/bin/python scripts/render_video.py --index-only
```

Every demo starts from the login page and navigates to the module through the
UI — no deep-linking to a module route. A viewer should see how a real user
reaches the feature, not just the end screen.

Three deliberate choices worth knowing:

- **The Next.js dev badge is hidden** during recording. `tests/fixtures/video.py`
  injects a MutationObserver that sets `display: none` on `nextjs-portal` as it
  appears. It has to be an inline style, not an injected `<style>` — Next's
  hydration replaces `<head>` and silently drops the stylesheet — and it has to
  match by tag name, since the badge renders in a shadow root and its host
  measures 0×0. Doing it test-side means the frontend repo is untouched and
  nothing can leak into a build.

- **A failing test's video is never published.** The fixture stamps `failed` on
  the manifest and the renderer skips it. A demo must only ever show a feature
  that actually works.
- **Captions are drawn as PNGs, not by ffmpeg.** The available ffmpeg build has
  no freetype and no libass, so `drawtext` and `subtitles` do not exist. Pillow
  rasterises the text and ffmpeg's `overlay` composites it. This also buys real
  word-wrap and rounded backing plates. A `.srt` sidecar is still written for
  reuse elsewhere.

A dedicated browser is launched for demo runs because Playwright's `slow_mo` is
a *browser launch* option, not a context option — reusing the suite's browser
would slow every assertion test down too.

---

## Throughput: why verification groups by scenario

Provisioning a school is ~40 UI steps and dominates the cost of a unit. The
first design gave each unit its own agent and therefore its own pytest process,
paying that walkthrough **once per unit**. Measured:

| Batch | Wall time | Units | Per unit |
|---|---|---|---|
| 2 | 92 min | 2 | 46 min |
| 8 | 428 min | 4 | **107 min** |

Batch 8 was *worse* per unit — 8 concurrent browsers all driving full
provisioning against one Next dev server and one backend container contend
badly, and this machine's concurrency cap is 12.

`provisioned_school` is session-scoped, so tests in **one** pytest run that
target the same scenario share a single provisioning. The loop now exploits
that:

1. Write every claimed unit's test — parallel, one agent each.
2. Barrier, then group units by scenario.
3. Per group: **one** pytest invocation for the whole group, fixed to green.
4. Per group: render the videos that run already produced.

Provisioning therefore costs once per *scenario* per iteration instead of once
per *unit* — with 5 scenarios, that ceiling holds no matter how large the batch.

This depends on every test carrying `@pytest.mark.scenario("<id>")`. Without it
`provisioned_school` parametrises over all five scenarios and one test
provisions five schools by itself. The write stage treats the marker as
mandatory.

## Parallel isolation

Every pytest process gets a unique run tag
(`tests/fixtures/data_factories._RUN_TAG`). School names, feature-pack names and
generated emails all carry it, so concurrent groups never collide on names or on
each other's data.

```js
Workflow({ scriptPath: '...', args: { batch: 8, agent: 'a1' } })
```

---

## What plan.md got wrong

Verified against the running stack. These cost fix rounds if rediscovered:

| plan.md says | Actually |
|---|---|
| §10: the backend exposes a test mode returning invite links | It did not. **Now implemented** — see [state/backend_patches.md](../state/backend_patches.md). Enable with `touch ../newschoolapp/.qa_mode_enabled`. |
| §6: SuperAdmin is created via `POST /users/register` | Refused: *"Cannot self-register with super admin privileges."* Seeded via `docker exec` into the backend container instead — `tests/fixtures/bootstrap.py`. |
| §4: test emails use `@learningbrix.test` | The backend's email validator **422s on reserved TLDs** (`.test`, `.example`, `.invalid`). Use `TEST_EMAIL_DOMAIN` (`learningbrix-qa.com`). |
| §4: backend on port 8000 | It runs in the `schoolapp` Docker container on **8093**; the DB is `salschdb` on 5415. |
| "Non-goal: parallel execution" | Parallel at the *agent* level, one school per agent. |
| Nothing about video | The whole point of this loop. |

`school_configuration` is the one module never negatively tested — the scenario
loader requires it in every scenario, since a SchoolAdmin cannot complete
onboarding without it. That is by design, and `coverage_warnings()` will keep
reporting it.
