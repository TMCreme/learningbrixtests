# Backend patches (uncommitted)

Changes made to `newschoolapp` so the integration suite can run unattended.
**None of these are committed** — they live in the working tree only. Review
them before deciding whether any belong in the product.

Verify at any time:

```bash
git -C ../newschoolapp status --porcelain
git -C ../newschoolapp diff
```

---

## QA mode — return generated secrets in the API response

**Why.** Every user this backend creates gets a server-generated password that
is only ever delivered by email, and invite/reset links are email-only too. An
unattended suite has no mailbox, so without this it cannot log in as any user it
creates — which is most of the test matrix. `docs/plan.md` §10 assumed a backend
test mode existed; it did not.

**Design.** A per-request `ContextVar` collects secrets as they are produced,
and one middleware attaches them to the response. Hooking `hash_password` rather
than each service means every user-creation path is covered by a single change
instead of ~20.

| File | Change |
|---|---|
| `utils/qa_mode.py` | **New.** Capture buffer, enable check, payload builder. Named `qa_mode` (not `test_mode`) so pytest's `test_*.py` collection does not import it as a test module. |
| `utils/utils.py` | `hash_password()` and `generate_random_password()` record the plaintext. Wrapped in try/except so instrumentation can never break a request. |
| `utils/mail_service.py` | `send_email()` records recipient/subject/links; `send_password_reset_email()` records the reset link and token directly. |
| `app.py` | New `qa_mode_capture` middleware, registered first. Adds `import json` and `Response` to the imports. |
| `.qa_mode_enabled` | **New.** Flag file that turns the mode on. |

**Response shape.**

```jsonc
// POST /api/v1/users/register → 200
{
  "id": 2, "email": "...",
  "test_mode": {
    "initial_password": "...",
    "passwords": ["..."],
    "emails": [{"recipient": "...", "subject": "...", "links": []}]
  }
}
```

Every response also carries an `X-Test-Mode` header with the same JSON. That
header is what makes endpoints returning a list or `null` readable — e.g.
`POST /users/forgot-password` returns a `null` body but its header carries
`reset_link` and `reset_token`.

**Enabling / disabling.**

```bash
touch ../newschoolapp/.qa_mode_enabled     # on  (uvicorn --reload picks it up)
rm    ../newschoolapp/.qa_mode_enabled     # off
```

A flag file rather than an env var because the container reads `env_file` only
at creation, while the repo is bind-mounted — so the flag flips without
recreating the container. `QA_MODE=1` in the environment works too and takes
precedence.

**Safety.** This puts plaintext passwords in HTTP responses, so it is
hard-disabled whenever `settings.PRODUCTION_ENV` is true, regardless of the flag
file or env var. When disabled the middleware returns the original response
untouched — no capture, no header, no body rewrite.

**Known limitation.** Emails dispatched from a FastAPI `BackgroundTasks` job run
*after* the response is produced, so their links are not captured. Password
capture is unaffected (hashing happens inside the request). If a flow needs a
link that is sent in the background, trigger it through an endpoint that sends
synchronously, or read it from `reset_token` on the originating call.

### Emails are suppressed while QA mode is on

`send_email` and `send_microsoft_email` record the message and return early
without contacting the provider.

**Why.** Creating a school sends a welcome email *inside the request*. Once the
Gmail account's daily quota was exhausted, that send raised and `POST
/school_profile/` started returning

```
400: 500: An error occurred: (550, b'5.4.5 Daily user sending limit exceeded. ...')
```

so **every school creation failed** — the whole request lost to an email nobody
reads. The recipients are synthetic test addresses, and the capture above
already gives the suite everything the message contained, so sending is pure
liability here. This also removes an external-service dependency from the test
run entirely.

Suppression is gated on QA mode; with it off, mail behaves exactly as before.

---

## School deletion — let Postgres cascade

**Why.** `DELETE /school_profile/{id}` failed for any school that had an
academic year — i.e. every provisioned one — with

```
null value in column "school_id" of relation "academic_year" violates not-null constraint
```

The FKs are declared `ON DELETE CASCADE` in Postgres, but the ORM relationships
did not say `passive_deletes=True`, so SQLAlchemy loaded each child and set its
`school_id` to NULL before deleting the parent. Teardown could therefore never
clean up, and leftovers eventually hit the 100-row cap on `/school_profile/` and
`/feature-packs/` — at which point newly created feature packs became invisible
to the assign-pack dialog and provisioning failed with an unrelated-looking
selector timeout.

| File | Change |
|---|---|
| `db/models/school.py` | `passive_deletes=True` on `academic_years`, `admin_associations`, `notification_config`, `report_config`, `notification_logs` — each has an `ON DELETE CASCADE` FK. |
| `db/models/school.py` | `cascade="all, delete-orphan"` on `branches`. **Not** passive: `school_branch.school_id` carries no FK constraint at all (only `admin_id` does), so Postgres cannot cascade it and the ORM must delete branches itself. |
| `db/models/feature_pack.py` | `passive_deletes=True` on the `feature_pack_assignment` backref, plus the `backref` import. |

Verified: provisioning a school with an academic year, a branch and an assigned
feature pack, then `DELETE /school_profile/{id}` → succeeds.

`scripts/cleanup_test_data.py` remains as a backstop for leftovers predating
this fix, and `scripts/preflight.py` sweeps automatically above 60 test schools.

**To revert everything:**

```bash
rm ../newschoolapp/.qa_mode_enabled ../newschoolapp/utils/qa_mode.py
git -C ../newschoolapp checkout -- app.py utils/utils.py utils/mail_service.py
```

---

## School deletion, part 2 — the branch's own children

**Why.** The patch above made the school delete reach its branches, which
exposed the same bug one level down. `teardown_school` swallows errors, so the
smoke test still reported green while every run silently leaked its school.
Deleting a branch failed in two stages:

```
null value in column "school_branch_id" of relation "school_fees" violates not-null constraint
update or delete on table "school_branch" violates foreign key constraint
    "families_school_branch_id_fkey" on table "families"
```

The first is the `passive_deletes` bug again: those children cascade in
Postgres, but the ORM loaded them and nulled a NOT NULL FK first. The second is
the opposite shape — `families.school_branch_id` is a plain FK (NO ACTION) and
`SchoolBranch` had **no** `families` relationship at all, so nothing ever
deleted them and Postgres refused to drop the branch.

| File | Change |
|---|---|
| `db/models/branch.py` | `passive_deletes=True` on `classes`, `subjects`, `books`, `book_categories`, `school_fee_group`, `school_fees` — each child's `school_branch_id` is `ON DELETE CASCADE` in the live schema. |
| `db/models/branch.py` | New `families` relationship with `cascade="all, delete-orphan"`. **Not** passive: no DB-level cascade exists. Safe because `student_profiles.family_id` and `guardian_profiles.family_id` are `ON DELETE SET NULL`, so the profiles outlive the family. |

Deliberately left alone: `users`, `school_fee_payment` and `fee_payment_summary`
declare `use_alter` FKs to `school_branch` that were **never created in the live
schema** (`pg_constraint` shows no row). Postgres cannot cascade them, so
`passive_deletes=True` there would orphan rows instead of fixing anything.

Verified: `DELETE /school_profile/{id}` → 204 on six real provisioned schools,
then a full smoke run ended with `school_profiles` empty and **zero** new
orphan branches (99 orphans predate this fix; newest 13:37, none after).

---

## School deletion, part 3 — the branch's income & expense *types*

**Why.** The same `passive_deletes` bug, one table further along, and invisible
until a school actually had finance rows. Any school whose branch had an income
type — i.e. every school the `finance_only` scenario provisions — failed
teardown with

```
DELETE /school_profile/{id} → 400
null value in column "school_branch_id" of relation "income_types"
violates not-null constraint
```

`income_types.school_branch_id` and `expense_types.school_branch_id` are both
`NOT NULL` and `ON DELETE CASCADE` in the live schema (`pg_constraint.confdeltype
= 'c'`), but `SchoolBranch.income_types` / `.expense_types` carried no
`passive_deletes`, so SQLAlchemy loaded each row and nulled the FK before
deleting the branch.

| File | Change |
|---|---|
| `db/models/branch.py` | `passive_deletes=True` on `income_types` and `expense_types`. |

The incomes/expenses that reference those types are deleted by the ORM in the
same flush (`school_income` / `school_expense` already carry
`cascade="all, delete-orphan"`) and are emitted before the branch row goes, so
the DB-side cascade never meets a live `income_type_id` reference.

Verified: `DELETE /school_profile/{id}` → **204** on a `finance_only` school
carrying two income types, one expense type, two incomes and one expense — the
same delete answered 400 immediately before the change.

---

## `GET /syllabi/` ignored the register's own search box

**Why.** `/module/syllabus` renders a "Search syllabus..." input whose debounced
handler calls `GetSyllabus({ search })` (`smsfrontend/src/lib/handlers/syllabusHandler.ts`),
which appends `search=<term>` to the request. `list_syllabi` declared no such
query parameter, so FastAPI dropped it silently and the endpoint answered with
the same unfiltered page. Typing in the box refetched the identical rows —
indistinguishable, from the UI, from "nothing matched but the table forgot to
say so", and it left the register's only text lookup dead on a list that is
server-paginated at 10 rows.

| File | Change |
|---|---|
| `api/routes/syllabus.py` | `list_syllabi` takes `search: Optional[str]` and forwards it on both the teacher/branch-scoped and the admin branch. |
| `services/syllabus_service.py` | `list_syllabi(..., search=None)` adds `ILIKE %term%` on `Syllabus.name` **or** `Syllabus.description` — the two fields the first table column renders. Applied before `query.count()`, so `total_count`/pagination stay consistent with the filtered set. |

Purely additive and guarded by `if search:`; every existing caller (which passes
nothing) behaves exactly as before. Exercised by
`tests/modules/academics/test_syllabi.py`.

---

## Frontend — the syllabus edit form discarded edits made while it was still loading

**Where.** `smsfrontend/src/app/module/syllabus/edit/[id]/page.tsx`

**Why.** `loadSyllabusData` seeds `editForm` from `GET /syllabi/{id}` and had no
way to tell a superseded invocation from the live one. Whenever the effect
re-ran while a fetch was still in flight, the older response still landed and
called `setEditForm(...)` a second time — resetting every field to the server's
copy and silently throwing away anything typed in between. React's development
double-invoke makes it reproducible: two `GET /syllabi/{id}` go out, the **first**
to answer clears `isFetching` and paints the form, and the second overwrites it
some tens of milliseconds later.

The failure is nastier than a lost keystroke, because the *rest* of the form
survives: the topic pickers write through functional `setEditForm(prev => …)`
updates applied after both fetches, so "Save Changes" posts the new topic list
alongside the **old** description, the API answers 200 and the page toasts
"Syllabus updated successfully". Verified end to end: the PUT body carried the
pre-edit description and `syllabi.description` in Postgres was unchanged while
`syllabus_topic_association` showed all three new rows.

| File | Change |
|---|---|
| `src/app/module/syllabus/edit/[id]/page.tsx` | `loadSyllabusData(run?)` takes a run token and returns without touching state — including `setIsFetching(false)` — once `run.cancelled` is set. The effect creates the token and cancels it on cleanup. |
| `src/app/module/syllabus/edit/[id]/page.tsx` | `onRetry={() => loadSyllabusData()}` so `PageError`'s click event is not passed in as the run token. |

Not committed. Because only the live run clears `isFetching`, the form is now
painted strictly *after* the last load settles, which also makes waiting on
"Fixed Context" a sound signal that the form is ready to be typed into.
Exercised by `tests/modules/academics/test_syllabi.py::test_teacher_creates_and_manages_syllabus`.

---

## Backend — the `community` feature-pack module gated nothing

**Where.** `newschoolapp/api/routes/feed.py`

**Why.** `services/feature_pack_service.SYSTEM_MODULE_GROUPS` offers
`community` (alongside `messaging`) in the "general" group, so a SuperAdmin can
build and assign a pack that excludes it — `config/feature_scenarios.yaml`'s
`minimal` pack does exactly that. Nothing enforced it. Every route on
`/feed/*` depended on `get_current_user` alone, with no `has_permission` and no
`has_feature_access`, so a school that had never been licensed for the module
could still read the whole community feed, post to it, comment and react. The
frontend cannot compensate: `community` is listed in
`smsfrontend/src/utils/postAuthRedirect.ts::CORE_MODULES`, which `middleware.ts`
and `usePermissionGuard` both use to *skip* their feature-flag check, and the
sidebar's "General" section carries neither a `permissionsGate` nor a per-item
`module`. The pack toggle was decorative.

| File | Change |
|---|---|
| `api/routes/feed.py` | `feed_router` declares `dependencies=[Depends(has_feature_access("community"))]`. |

`has_feature_access`, not `has_permission`: this is a licence check only. Who may
do what inside the feed is still decided per action by
`services/group_permission_service.py`, so every role keeps exactly the access it
has today whenever the module *is* licensed, and a school with no pack assigned
at all stays unrestricted (`get_school_modules` → `None`). Declared on the router
rather than per route so no endpoint added later escapes the gate.

The UI consequence follows from the 403 detail "Feature not available in your
plan": the axios interceptor in `smsfrontend/src/utils/handleErrorMessage.ts`
recognises it and hard-redirects to `/auth/no-access`.

Not committed. Exercised by
`tests/modules/general/test_community.py::test_community_denied_for_school_admin_when_module_disabled`.

---

## Topics — a Teacher was locked out of the module the API authorises them for

**Where.** `smsfrontend/src/app/module/subjects/page.tsx`,
`smsfrontend/src/app/module/subject_topics/reorder_topics/page.tsx`

**Why.** `topics` is a module of its own: every route on
`newschoolapp/api/routes/topic.py` is gated on `has_permission("manage"|"read",
"topics")`, and the seeded **Teacher** role holds `("manage", "topics")` but only
`("read", "subjects")` (`db/repository/permissions.py`). Both frontend surfaces
read the topic write affordances off the *subjects* permission instead —
`usePermission("subjects", name => name === "manage")` — so a Teacher was shown
the Topics tab with no "Add Topic", no "Reorder Topics" and a row menu holding
only "View details", while the API would have accepted every one of those
writes. The reorder page was the starker case: it guards its module on
`useModuleGuard("topics")` and then refused the same user with "You don't have
permission to reorder topics".

| File | Change |
|---|---|
| `src/app/module/subjects/page.tsx` | New `isTopicManage = usePermission("topics", …)`. The Topics tab's "Reorder Topics"/"Add Topic" buttons and the topic row menu's Edit/Archive/Delete now read it; `isManage` still gates the Subjects tab. |
| `src/app/module/subject_topics/reorder_topics/page.tsx` | `isManage` reads `usePermission("topics", …)`, matching the `useModuleGuard("topics")` immediately below it. |

No role gains anything the backend would refuse: SchoolAdmin and Admin hold
`("manage", "topics")` as well, so their affordances are unchanged. Not
committed. Exercised by
`tests/modules/academics/test_topics.py::test_teacher_creates_and_manages_topics`.

---

## Backend — `GET /topics/` ignored the register's search box

**Where.** `newschoolapp/api/routes/topic.py`,
`newschoolapp/services/topic_service.py`

**Why.** The Topics tab's "Search topic or subject" box has always sent
`search=<term>` (`GetTopics` in `smsfrontend/src/lib/handlers/topicsHandler.ts`),
but `list_topics` declared no such query parameter, so FastAPI dropped it and the
identical unfiltered page came back. On a list the UI paginates at 10 rows that
left the register's only text lookup dead — the same defect already fixed for
`GET /syllabi/` above.

| File | Change |
|---|---|
| `api/routes/topic.py` | `list_topics` takes `search`, passed through on both the scoped and the admin branch. |
| `services/topic_service.py` | `TopicService.list_topics(search=…)` matches `Topic.name`, `Topic.description` and the related `Subject.name` — the three things the box's placeholder names. |

Not committed.

---

## Backend — bulk topic create threw away four of its own fields

**Where.** `newschoolapp/services/topic_service.py`

**Why.** `/module/subjects/topics/add` collects **Learning Outcomes**,
**Objectives**, **Resources** and **Duration (Minutes)** on every topic it
stages, and `TopicBulkCreateItem` accepts all four. But
`bulk_create_topics` built its insert dict by hand from
`name`/`description`/`order_index` only, so everything else was silently
discarded — while the single-topic `create_topic`, which `model_dump()`s, kept
it. A teacher who filled the composer in full got a topic with four empty
fields and no error.

A second defect sat in the same loop: every topic in a batch came out with the
**same `order_index`**, so a curriculum authored through the composer had no
teaching order at all. `auto_increment_topic_order_index` (`db/models/topic.py`)
is a `before_insert` hook that reads `MAX(order_index)` off the connection, and
SQLAlchemy dispatches `before_insert` for every pending state *before* it emits
any INSERT (`orm/persistence.py::_organize_states_for_save`) — so adding the
whole batch and flushing once left each hook reading the same pre-flush maximum.

| File | Change |
|---|---|
| `services/topic_service.py` | `topic_dict = topic_item.model_dump()`, then `subject_id`/`school_branch_id` set on top. |
| `services/topic_service.py` | `bulk_create_topics` flushes per topic instead of once after the loop, so each `before_insert` sees the row before it. |

Not committed. Exercised by
`tests/modules/academics/test_topics.py::test_teacher_creates_and_manages_topics`,
which reads the fields back off the edit form.

---

## Backend — the `messaging` feature-pack module gated nothing

**Where.** `newschoolapp/api/routes/messaging.py`

**Why.** Same defect as the `community` one above, in the other half of the same
module group. `services/feature_pack_service.SYSTEM_MODULE_GROUPS` offers
`messaging` in the "general" group, and three of the five packs in
`config/feature_scenarios.yaml` (`academics_only`, `finance_only`, `minimal`)
are built without it — but all twenty `/messaging/*` routes depended on
`get_current_user` alone, with no `has_permission` and no `has_feature_access`.
An unlicensed school could read its inbox, sent, drafts, scheduled and trash
folders, compose, send, schedule and trash mail exactly as a licensed one could.
The frontend cannot compensate: `messages` is in
`smsfrontend/src/utils/postAuthRedirect.ts::CORE_MODULES`, which `middleware.ts`
and `usePermissionGuard` both use to *skip* their feature-flag check;
`/module/messages` declares no `useModuleGuard`; and the sidebar's "General"
section carries neither a `permissionsGate` nor a per-item `module`. The pack
toggle was decorative.

| File | Change |
|---|---|
| `api/routes/messaging.py` | `messaging_router` declares `dependencies=[Depends(has_feature_access("messaging"))]`. |

`has_feature_access`, not `has_permission`: this is a licence check only. Who may
message whom is still decided inside `services/message_service.py`, so every role
keeps exactly the access it has today whenever the module *is* licensed, and a
school with no pack assigned at all stays unrestricted (`get_school_modules` →
`None`). Declared on the router rather than per route so no endpoint added later
escapes the gate.

The UI consequence follows from the 403 detail "Feature not available in your
plan": `FolderPage` asks for its folder on mount, and the axios interceptor in
`smsfrontend/src/utils/handleErrorMessage.ts` recognises that detail and
hard-redirects to `/auth/no-access`.

Not committed. Exercised by
`tests/modules/general/test_messaging.py::test_messaging_denied_for_school_admin_when_module_disabled`.

---

## Backend — the `Accountant` role was seeded with no permissions at all

**Where.** `newschoolapp/db/repository/permissions.py`

**Why.** `Accountant` is a first-class role: `app.py`'s `lifespan` creates it on
every boot (`RoleChoices.Accountant`) and the non-teaching staff wizard offers it
in its "Non teaching Staff Role" dropdown, which is how a school actually gets
one. But `seed_roles_and_permissions` had no `"Accountant"` key in
`role_permissions`, so the role was created and then left empty — `GET /roles/`
reported **0 permissions** against 28 for `Admin` and `SchoolAdmin`.

Every accountant in the product therefore logged in to an empty application:

* the sidebar's "Account Module" section failed its
  `permissionsGate: ["fees", "incomes_and_expenses"]` and was not rendered, so
  there was no way to reach Fee Management or Income & Expenses at all;
* `usePermissionGuard("fees")` returned false and `/module/fees` rendered
  `null`;
* `has_permission("manage", "fees")` answered 403 to every write.

The role the finance module is named after could not open the finance module.

| File | Change |
|---|---|
| `db/repository/permissions.py` | New `"Accountant"` entry in `role_permissions`: `manage fees`, `manage incomes_and_expenses`, plus reads on `home`, `dashboard`, `students`, `staff` and the `messaging`/`change_requests` baseline `Non_teaching_staff` already carried. |

Deliberately narrower than `Admin`: nothing academic, nothing in payroll,
library, access roles or school configuration. The feature pack still gates each
module per school — `has_permission` checks the licence after the role — so
nothing about who may license what changed, and no other role is touched.

Seeding is idempotent and additive (`if permission not in role.permissions`), so
it applies to the existing role on the next boot; `uvicorn --reload` picks the
edit up and re-runs `lifespan`. Verified: `GET /api/v1/roles/` reports the eight
permissions above against `Accountant`.

Not committed. Exercised by
`tests/modules/account/test_fees.py::test_accountant_creates_and_manages_fees`
and
`tests/modules/account/test_incomes_and_expenses.py::test_accountant_creates_and_manages_income`,
both of which fail at their first navigation step if the seed regresses.

---

## A school without the `community` licence could not log anyone in
*(frontend — `src/utils/postAuthRedirect.ts`, `src/app/auth/login/page.tsx`)*

Uncovered by `tests/modules/academics/test_topics.py`; it broke **every** UI unit
for Teacher, Student and Guardian on the `academics_only`, `finance_only` and
`minimal` scenarios at once.

`MODULE_ORDER` (`src/types/userRolePermissions.ts`) sorts `community` first, and
both post-login landing computations — the one in `login/page.tsx` and
`getPostAuthRedirect`, which `middleware.ts` uses — treated `community` as a
*core* module, i.e. one no feature pack can withhold. So every role holding the
`community` permission was landed on `/module/community` whatever their school
had bought.

That was survivable only while `/feed` was ungated. Once
`api/routes/feed.py` gained `Depends(has_feature_access("community"))`, the
landing page's first fetch answered 403 "Feature not available in your plan",
`shouldRedirectToNoAccess` in `src/utils/handleErrorMessage.ts` recognised it and
hard-redirected to `/auth/no-access` — so a teacher or pupil of an unlicensed
school never got past sign-in. The symptom is any UI test failing on its first
locator with the Access Restricted card on screen.

| File | Change |
|---|---|
| `src/utils/postAuthRedirect.ts` | `community` removed from `CORE_MODULES`, with a comment saying why. It is a system module (`FeaturePackService.SYSTEM_MODULE_GROUPS`, group `general`), so it must be licence-checked like any other. |
| `src/app/auth/login/page.tsx` | Same removal from the local `CORE_MODULES` copy that picks the landing route. |

A school that *does* license `community` is unaffected: the module is then in
`availableModules` and stays first. A school that does not now lands the user on
their first genuinely licensed module (`home` for the academics scenarios), and
typing `/module/community` by hand is refused by `middleware.ts` — the correct
denial surface — instead of by an interceptor redirect mid-fetch.

---

## Home fetched other modules' data and threw the user off its own page
*(frontend — `src/app/module/home/ViewsComponents/StaffView.tsx`,
`src/app/module/home/components/StudentDashboardTabs.tsx`)*

Same failure mode, one page further in. `/module/home` is licensed for every
academics scenario, but it mounts panels belonging to other modules:
`StaffBookDashboard` calls `GET /book-requests/student/{id}` (gated on
`catalogue`) on mount, `RecentPayslips` calls `/payroll/*` (gated on
`staff_payroll`), and the pupil dashboard's Fees and Library tabs do the same for
`fees` and `catalogue`. A Teacher holds `manage catalogue`, so for a school
without the library the refusal is the *plan* one — and the axios interceptor
turned it into a redirect to `/auth/no-access`.

| File | Change |
|---|---|
| `StaffView.tsx` | Renders `RecentPayslips` / `StaffBookDashboard` only when `hasModuleLicence("staff_payroll")` / `("catalogue")`. |
| `StudentDashboardTabs.tsx` | Tabs carry the module they read and are filtered through `hasModuleLicence` before render. |

`src/utils/moduleLicence.ts` already existed for exactly this (a missing cookie
is permissive, so a SuperAdmin is unaffected); this applies it to home.

---

## Deleting a school with any teaching data on it failed with a 400
*(backend — `db/models/branch.py` and the seven academics models)*

`DELETE /school_profile/{id}` answered

```
(psycopg2.errors.ForeignKeyViolation) update or delete on table "school_branch"
violates foreign key constraint "topics_school_branch_id_fkey" on table "topics"
```

and then the same for `syllabi`, `lessons`, `assessments`, … Nine tables carry a
plain (NO ACTION) `school_branch_id` FK; `families` had already been given an ORM
cascade for this reason, and the rest had nothing pointing at them from
`SchoolBranch` at all, so neither Postgres nor SQLAlchemy removed them. Every
academics run therefore leaked its school — which is what eventually trips the
100-row cap on `/school_profile/` and `/feature-packs/`.

| File | Change |
|---|---|
| `db/models/branch.py` | `topics`, `syllabi`, `lessons`, `assessments`, `assessment_categories`, `attendance_records`, `timetables`, `activities` relationships added, each `cascade="all, delete-orphan"`, following the existing `families` precedent. |
| `db/models/{topic,syllabus,lesson,assessment,assessment_category,attendance,timetable,activity}.py` | `school_branch = relationship("SchoolBranch")` → `back_populates=` the matching collection. |

No schema change. Child-of-child rows follow the cascades already declared on
each model, and `lessons.topic_id` / `lessons.syllabus_id` are ON DELETE SET
NULL, so ordering between the new collections is not load-bearing. Verified by
deleting the two schools this investigation had leaked (204) and by the
`provisioning.teardown.done` line the passing run now ends on.

Not committed.
