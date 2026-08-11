# App changes awaiting review

Everything the suite has changed in `newschoolapp` and `smsfrontend`, classified
by whether it is a defect fix or a behaviour change. **Nothing is committed** —
both repos still sit on their baseline HEADs.

```bash
git -C ../newschoolapp  diff            # 26 files, +400 / -49
git -C ../smsfrontend   diff            # agent edits + pre-existing docs
```

Read **section C first**. Sections A and B are safe to skim; C is where a human
ruling is genuinely needed, and two of its items could affect live schools.

---

## A. Test infrastructure — inert unless QA mode is on

Only active while `.qa_mode_enabled` exists. With the flag removed, every one of
these is a no-op and the app behaves exactly as shipped. Not intended for the
product; delete the flag file to disable.

| File | What |
|---|---|
| `utils/qa_mode.py` *(new)* | Per-request capture of generated secrets |
| `utils/utils.py` | `hash_password` / `generate_random_password` record plaintext |
| `utils/mail_service.py` | Records outgoing mail; suppresses the actual send |
| `app.py` | `qa_mode_capture` middleware |
| `.qa_mode_enabled` *(new)* | The on switch |

Full rationale in [backend_patches.md](backend_patches.md).

---

## B. Defect fixes — broken behaviour, no product decision involved

Each of these was crashing, losing data, or contradicting itself. They are the
kind of thing the test run exists to find.

| Area | Defect | Evidence |
|---|---|---|
| `db/models/school.py`, `branch.py`, `feature_pack.py`, + 7 `back_populates` tweaks | `DELETE /school_profile/{id}` failed for **every** school that had an academic year. ORM nulled child FKs instead of letting Postgres cascade. | `NotNullViolation` on `academic_year.school_id`; now deletes cleanly |
| `services/lesson_service.py` | 500 on any week mixing timed and untimed lessons — compared `datetime.time` against `str`. | `TypeError` on a legal week |
| `services/topic_service.py` | Bulk topic create **silently discarded** learning outcomes, objectives, resources and duration. The single-item path kept them. | Hand-written dict listed only 3 of 7 fields |
| `services/pending_change_service.py` | Every approval of a `SchoolFee` change request returned 400. | `create_fee() takes 3 positional arguments but 4 were given` |

**Recommendation:** these look worth taking into the product. The school-deletion
one in particular means teardown has never worked.

---

## C. Behaviour changes — need your ruling before they go anywhere

These are not defects. Each adds capability or enforces something previously
unenforced, and an agent decided that on its own. That is the gap in my
instructions, now corrected (see "Rule change" below).

### C1. Accountant role granted 8 permissions — `db/repository/permissions.py`

The role is created in `lifespan()` and offered by the non-teaching staff form,
but was seeded with **no permissions at all**, so every Accountant logged into a
blank app. The agent added:

```
read: home, dashboard, students, staff, change_requests, messaging
manage: fees, incomes_and_expenses
```

**Question for you:** is an empty Accountant role the bug, or is the role not
meant to be usable yet? If it should work, is this the right permission set? This
is a security boundary — worth deciding deliberately rather than inheriting an
agent's guess.

### C2. Feed router now enforces the `community` licence — `api/routes/feed.py`

Adds `Depends(has_feature_access("community"))` at router level. Previously every
`/feed` endpoint answered normally regardless of the school's feature pack.

**Risk:** if any live school uses the feed on a pack that omits `community`,
this cuts them off immediately. The negative test wanted this gate; the product
may not.

### C3. Messaging router now enforces the `messaging` licence — `api/routes/messaging.py`

Identical shape to C2: an unlicensed school could previously read its inbox and
send mail. Same risk profile.

**C2 and C3 together are the highest-risk items here.** They change what existing
customers can reach. Either the modules were always meant to be gated and this
closes a licensing hole, or the gate is wrong — but that is a commercial call.

### C4. Server-side `search` added to subjects, syllabi and topics

`api/routes/{subject,syllabus,topic}.py` + their services now accept a `search`
query parameter.

The frontend's search boxes have always sent it; FastAPI dropped it because no
route declared it, so the boxes silently filtered nothing. Defensible as a bug
fix from the user's point of view — but it is new backend capability, so it
belongs here rather than in section B.

---

## Rule change already applied

Agents may now fix defects in place, but must **ask before adding capability or
changing product behaviour** — granting permissions, adding a route or parameter,
or enforcing a previously unenforced gate. A missing feature is not automatically
a bug.

The community comment-edit case proved the point: the frontend ships an
edit-comment flow calling `PUT /feed/comments/{id}`, which the backend
deliberately does not implement — posts and comments are immutable by design.
The agent correctly escalated instead of adding the route, but framed it as
"unclear whether deliberate". It is deliberate.

---

## Frontend

`smsfrontend` also carries agent edits (login redirect, staff/student dashboard
views, lessons detail, assessment score page, timetable view, subject/syllabus
screens, `assessmentHandler.ts`, some types). These are smaller and mostly
null-guard / shape fixes found by driving the UI.

Note `docs/frontend_*.md` (~1,440 lines) and `tsconfig.json` / `package-lock.json`
in that diff are **yours**, not the suite's — they predate this work.

---

## Incident Reports — `POST /incidents/` was unreachable for every branch-scoped role

**Classification: defect fix** (`newschoolapp/api/routes/incident_report.py`,
`create_incident_report`).

`branch_id` was declared `int = Query(...)` — *required* — and the handler never
called `branch_id_required`. Every other route in the same file declares it
`Optional[int] = Query(None)` and resolves it through
`core.exceptions.branch_id_required`, which returns the caller's own
`user.school_branch_id` for anyone who is not a SuperAdmin/SchoolAdmin.

Evidence that this made the endpoint impossible to call from the product:

* `db/repository/permissions.py` grants **Teacher** `("manage", "incidents")`,
  and `nav-config.tsx` puts "Incidents Reporting" in front of them.
* `smsfrontend/src/lib/handlers/incidentReportingHandler.ts::createIncidentReport`
  appends `branch_id` **only** when the signed-in role is SchoolAdmin or
  SuperAdmin — exactly the two roles for which `branch_id_required` still
  demands one. For a Teacher (or Admin/Accountant/Non_teaching_staff) the POST
  goes out with no query string at all, so FastAPI answered 422 "Field required"
  before the handler ran and the UI toasted "Failed to create incident report".
* The very next route in the file, `PATCH /incidents/{id}`, already accepts the
  same request shape from the same roles — so the module contradicted itself:
  a teacher could edit and delete incidents they could never create.

The change is one line plus a comment: `Optional[int] = Query(None)` and
`branch_id = branch_id_required(current_user, branch_id)`. No capability is
added — SchoolAdmin/SuperAdmin still get 400 `BRANCH_ID_REQUIRED` without a
branch, and the permission dependency is untouched.

Held shut by `tests/modules/incident_reports/test_incidents.py::
test_teacher_creates_and_manages_incident_report`.

**Not fixed, deliberately left alone (frontend, noted only):** the create page
sends `incident_time: form.incident_time || ""`, and `IncidentReportBase`
types it `Optional[time]`, so submitting the form *without* a time is a 422.
The test always fills the Incident Time picker, which is the realistic path;
whether an empty string should be coerced to `null` is a product/API-shape call,
not something to change unattended.

---

## Library loans — `BookRequestResponse.copy` was always `null`

**Classification: defect fix** (`newschoolapp/api/api_models/book_request.py`,
`BookRequestResponse`).

The field was declared

```python
book_copy: Optional[BookCopyResponse] = Field(None, serialization_alias="copy")
```

`serialization_alias` renames only the *output* key. Attribute lookup still went
to `book_copy` — and `db/models/book_request.py` names that relationship `copy`
(`copy = relationship("BookCopy", back_populates="book_request")`). So Pydantic
found no `book_copy` attribute, fell back to the declared default `None`, and
serialised it under the alias. **Every** `BookRequestResponse` the API has ever
returned carried `"copy": null`, on every route that uses it — list, by-id,
by-student, approve, reject.

Reproduced in isolation inside the running container:

```
serialization_alias="copy"  →  {'copy': None}   # attribute `copy` present on the object
alias="copy"                →  {'copy': {...}}
```

Evidence it is a wiring bug and not a deliberate omission:

* `services/book_request.py::handle_book_request` *does* store the choice —
  `book_request.book_copy_id = request_data.book_copy_id` — and flips
  `book_copy.available = False`. The data is written and then never returned.
* `BookRequestApprove` makes `book_copy_id` **required**, so the API forces the
  librarian to name a physical copy it then refuses to tell anyone about.
* The frontend reads the key the alias produces:
  `StudentView.tsx` renders `{request?.copy?.name || "Copy not assigned"}` in
  the Book Copy column and searches on `request.copy?.name`, and
  `requests_and_renewals/overdue/[id]/page.tsx` renders `bookRequest.copy?.id`.
  So a pupil holding a book in their hands was always shown
  "Copy not assigned", and the overdue drill-down always showed `#undefined`.
* The name `book_copy` is not arbitrary: a field literally named `copy` would
  shadow `BaseModel.copy`, which is why the author aliased instead — they simply
  reached for the serialization-only alias.

The change is one line: `Field(None, alias="copy")`. `alias` sets validation and
serialization together, so the attribute is now read from `copy` and still
emitted as `"copy"` — the wire format is byte-identical for any consumer that
was already reading a populated field, since none ever was. `populate_by_name`
is already on this model, so `book_copy` remains accepted on input. No route,
permission, schema key or capability changed.

Held shut by `tests/modules/library/test_requests_and_renewals.py` —
`test_school_admin_works_the_library_request_desk` (the librarian binds a copy
through the Approve dialog, and the closing check reads it back off the server)
and `test_student_reviews_their_library_requests` (the pupil's Book Copy column).

**Noted, not fixed:** `smsfrontend/src/app/module/categories/page.tsx` computes
`totalPages` from `itemsPerPage = 5` and renders Previous/Next, but the table
body maps over the *whole* `filteredCategories` rather than the current page's
slice — the pager is decorative. Cosmetic, contradicts no stored data, and
whether the register is meant to paginate at all is a product call.

---

## Home — a SchoolAdmin without the library was thrown off their own home page

**Classification: defect fix**
(`smsfrontend/src/app/module/home/ViewsComponents/AdminView.tsx`).

`AdminView` is what `/module/home` renders for any admin role. On mount it ran
`fetchDashboardData`, which unconditionally calls

```ts
getBooksRequests({ status: "pending" })   // GET /book-requests/
GetBookStatistics({ branch_id })          // GET /book-statistics/total-books
getBooksRequests()                        // GET /book-requests/
```

Both routes are declared `Depends(has_permission("read", "catalogue"))`
(`newschoolapp/api/routes/book_request.py:31`,
`newschoolapp/api/routes/book_statistics.py:71`). For a school whose feature pack
omits `catalogue`, the feature-pack branch of `utils/permissions.has_permission`
answers **403 "Feature not available in your plan"**, and
`shouldRedirectToNoAccess` in `smsfrontend/src/utils/handleErrorMessage.ts`
turns exactly that detail into a hard `window.location.href = "/auth/no-access"`
inside the global axios response interceptor.

So an admin of such a school could not stay on `/module/home` at all — a page
`home` is *permanently* licensed for (it is in the locked `people` group of
`FeaturePackService.SYSTEM_MODULE_GROUPS`, and `CORE_MODULES` in
`src/utils/postAuthRedirect.ts` lists it as not licensable). The page evicted the
very user it is guaranteed to be available to. The three `.catch(() => …)`
fallbacks inside `fetchDashboardData` cannot prevent it: the interceptor performs
the redirect before the caller's rejection handler runs.

Evidence this is a wiring omission and not a decision:

* The sibling view for the same page, `StaffView.tsx`, already carries the fix,
  with a comment naming this exact failure — `hasModuleLicence("catalogue")` /
  `hasModuleLicence("staff_payroll")` guarding the same kind of panel.
* `StudentDashboardTabs.tsx` and `students/[student]/page.tsx` filter their tabs
  through `hasModuleLicence` for the same reason.
* `src/utils/moduleLicence.ts` exists solely to document and serve this case:
  "a page that is itself licensed but renders a panel belonging to a different
  module … So the panel must not ask for data its school never bought."

The change mirrors those three: one `hasModuleLicence("catalogue")` read at
mount, the library fetch skipped when it is false, and the three library-derived
cards (`Requests to Approve`, `Total Books`, `Total Book Requests`) not rendered
in that case. Nothing else on the page moves — `Header` and the
`Recent System Activities` table (over `GET /audilog/`, gated on `access_roles`,
which is locked into every pack) are untouched, and a school that *is* licensed
for `catalogue` sees exactly what it saw before.

No gate was added or tightened: the backend refusal is unchanged, and the cookie
this reads is the same one `middleware.ts` and `usePermissionGuard` already
consult. What changed is that the page no longer requests data it knows it will
be refused.

Held shut by `tests/modules/people/test_home.py::test_home_is_reachable_on_the_minimal_pack`
(the `minimal` pack omits `catalogue`; that test asserts the admin stays on
`/module/home` rather than landing on `/auth/no-access`).

---

## Guardians — `PUT /guardian/{id}` rejected every edit made through the UI

**Defect fix** — `newschoolapp/api/routes/guardian.py`, `update_guardian`.

The route treated *any* non-empty `user.profile_pic` as a freshly attached
picture and unpacked it as a base64 data URI:

```python
if guardian.user.profile_pic:
    header, encoded = guardian.user.profile_pic.split(",", 1)   # ValueError
```

A value with no comma raises `ValueError`, the surrounding handler converts that
to `400 "Invalid thumbnail format: not enough values to unpack (expected 2, got
1)"`, and the outer `except (HTTPException, Exception)` re-raises it — so the
guardian was never updated.

`smsfrontend/src/app/module/guardians/edit-guardian/[guardianID]/page.tsx`
*always* sends `profile_pic: formData.photo` (line 199), and `formData.photo`
can only hold one of three things:

* `"/assests/avatar-icon.svg"` — `initialFormData.photo` (line 24), what the
  prefill maps in when the guardian has no picture
  (`guardian.user.profile_pic || "/assests/avatar-icon.svg"`, line 133), and what
  the "Remove" button writes (`components/BasicInformation.tsx:57`);
* the stored S3 URL echoed straight back from `GET /guardian/{id}`;
* a genuine `data:image/…;base64,…` URI — only from
  `reader.readAsDataURL(file)` after "Change Photo"
  (`components/BasicInformation.tsx:77-81`).

Only the third is an upload. The first two are locations that are already
stored, carry no base64 payload, and must be written back untouched. So no
guardian edit could succeed through the product's own UI unless the user
happened to attach a new photo in the same visit — the button toasts nothing,
the wizard stays put, and the correction is lost.

Reproduced directly against the running backend with case one, which is exactly
what the failing browser run sent:

```
PUT /api/v1/guardian/116  {"user":{"profile_pic":"/assests/avatar-icon.svg", …}}
→ 400 {"detail":"400: Invalid thumbnail format: not enough values to unpack (expected 2, got 1)"}
```

matching `docker logs schoolapp`: `"PUT /api/v1/guardian/116 HTTP/1.1" 400 Bad
Request`. After the fix the same request answers 200 with the corrected record.

Evidence this is a defect and not a deliberate refusal:

* `POST /guardian/` has the identical block and works only by luck —
  `add-guardians/page.tsx` initialises `photo: ""` (line 25) and sends
  `formData.photo || ""`, which is falsy and skips it. The create path therefore
  never exercises the bug, which is why only editing was broken.
* `api/routes/messaging.py:82` already guards the same decode with
  `if "," in att.url`, so passing a non-data-URI through untouched is the
  codebase's own established handling.
* Nothing about a stored S3 URL is invalid input; the route was refusing the
  value it had itself handed out on the preceding `GET`.

The change narrows the upload branch to values that actually are inline data
(`startswith("data:")` and containing a comma) and passes everything else
through unchanged; it also stops dereferencing `guardian.user`, which
`GuardianProfileUpdate` declares `Optional`, without a null check. No gate was
added or relaxed, no field was newly accepted, and a payload carrying a real
data URI still takes the identical S3 upload path.

Held shut by
`tests/modules/people/test_guardians.py::test_school_admin_creates_and_manages_a_guardian`,
which edits a guardian through the wizard and then asserts the correction on
`GET /guardian/{id}`.

---

## Staff profile — a SchoolAdmin without the library was thrown off a licensed page

**Classification: defect fix**
(`smsfrontend/src/app/module/staff/[staffID]/page.tsx`).

Exactly the failure already recorded above for `/module/home`, in the sibling
screen. The teaching-staff profile ran, unconditionally on mount, once
`staffsData` arrived:

```ts
getStaffLibraryHistory(staffsData.user.id)   // GET /history/{user_id}
```

`GET /history/{user_id}` is declared
`Depends(has_permission("read", "catalogue"))`
(`newschoolapp/api/routes/book_history.py:36`). The seeded `SchoolAdmin` role
holds `("manage", "catalogue")` (`db/repository/permissions.py:144`), so the
permission half of that dependency passes and the *feature-pack* half answers
**403 "Feature not available in your plan"** for a school whose pack omits
`catalogue`. `shouldRedirectToNoAccess` in `src/utils/handleErrorMessage.ts`
turns that detail into a hard `window.location.href = "/auth/no-access"` inside
the global axios response interceptor — before the page's own `catch` runs, so
the `toast.error` fallback around the call cannot prevent it.

The consequence: on any pack without `catalogue` (the `minimal` scenario, for
one), a SchoolAdmin could not open a staff member's profile at all, even though
`staff` is licensed, the role holds `("manage", "staff")`, and the profile is the
*only* way the product offers to reach the edit wizard ("Edit Profile" lives on
this screen; the list has no row action). The page evicted a user it is
entitled to serve, over data belonging to a different module.

Evidence this is a wiring omission and not a decision:

* `students/[student]/page.tsx` already carries the identical fix for the
  identical tab — `TABS` there tags `library-history` with `module: "catalogue"`,
  filters through `hasModuleLicence`, and gates the history fetch on
  `librarySectionEnabled`, with a comment naming this exact failure.
* `AdminView.tsx` was fixed the same way earlier in this run (entry above).
* `src/utils/moduleLicence.ts` exists solely for this case and says so.

The change mirrors those: `payslips` is tagged `staff_payroll` and
`library-history` is tagged `catalogue`, the tab strip renders `visibleTabs`
instead of `TABS`, and the library fetch is skipped when its tab is not on
offer. Payroll is tagged for the same reason and on the same evidence — every
route behind `GetPayrollRuns`/`GetPayslipDetails` is
`has_permission(read|manage, "staff_payroll")` (`api/routes/payroll.py`), and
`SchoolAdmin` holds `("manage", "staff_payroll")`, so clicking that tab in an
unlicensed school produced the same eviction. Nothing else on the screen moves:
Basic Info, Academics and Others are untagged and always render, no gate was
added or tightened, the backend is untouched, and a school licensed for
`catalogue`/`staff_payroll` sees exactly what it saw before.

Held shut by
`tests/modules/people/test_staff.py::test_school_admin_creates_and_manages_staff`,
which runs on the `minimal` pack (no `catalogue`, no `staff_payroll`) and opens a
staff profile, then edits it, asserting the admin stays on `/module/staff/<id>`
rather than landing on `/auth/no-access`.

---

## Student admission/edit wizard — an unlicensed guardian lookup evicted the admin

**Classification: defect fix**
(`smsfrontend/src/app/module/students/components/ContactDetails.tsx`).

The same failure recorded above for `/module/home`, the staff profile and the
student record's Library tab, this time inside the *admission wizard*. Step 2
(Contact Details) runs, unconditionally on mount:

```ts
const url = `${baseURL}/guardian/?${params}`;
const response = await apiGet(url, { headers: … });
```

`GET /guardian/` is declared `Depends(has_permission("read", "guardians"))`
(`newschoolapp/api/routes/guardian.py`). The seeded `SchoolAdmin` role holds
`("manage", "guardians")`, so the permission half passes and the feature-pack
half answers **403 "Feature not available in your plan"** for a school whose
pack omits `guardians`. `shouldRedirectToNoAccess` in
`src/utils/handleErrorMessage.ts` turns that detail into a hard
`window.location.href = "/auth/no-access"` inside the global axios response
interceptor — before this component's own `catch`/`handleErrorMessage` runs, so
the local error handling around the call cannot prevent it.

The consequence: on any pack without `guardians` (the `minimal` scenario, for
one), a SchoolAdmin could not admit a student at all, nor edit one — the same
component is step 2 of `admit-student` *and* of
`edit-student/[editstudentId]`. They were thrown to `/auth/no-access` one step
into a wizard on a module their school is licensed for, and everything typed
into Basic Information was discarded with the unmount.

Evidence this is a wiring omission and not a decision:

* The field itself is labelled **"Guardian's Name (Optional)"** and the step's
  `requiredFields` array is empty, so the wizard already treats a guardian as
  something a school may not have. `AdmitStudent.handleSubmit` sends
  `guardian_id: Number(formData.guardian_id) || 0` regardless.
* `guardians` is one of exactly two optional members of the pack builder's
  locked `people` group (`OPTIONAL_BASIC_MODULES`), so "students licensed,
  guardians not" is a shape the product deliberately sells.
* `src/utils/moduleLicence.ts` exists solely for this case and says so; three
  screens already carry the identical fix.

The change mirrors those: one `hasModuleLicence("guardians")` read at the top of
the fetch, which returns early when false. The picker then renders with only its
placeholder — which is exactly what it renders today for a licensed school with
no guardians yet. No gate was added or tightened, the backend is untouched, and
a school licensed for `guardians` sees exactly what it saw before.

---

## Student record — the Academics tab's fetches evicted the admin on mount

**Classification: defect fix**
(`smsfrontend/src/app/module/students/[student]/page.tsx`).

Same class again, in the screen whose Library tab was already fixed this way.
Two further modules feed that page and were not tagged:

* `loadAttendance` runs from a mount effect as soon as `studentData` resolves —
  **not** on tab click — issuing `GET /attendance/` and
  `GET /attendance/student/{id}/summary`, both
  `Depends(has_permission("read", "attendance"))` (`api/routes/attendance.py`).
* The Academics tab additionally fetches `GET /assessments/scores/student/{id}`
  (`has_permission("read", "assessments")`) and `GET /syllabus/…`
  (`has_permission("read", "syllabi")`).

`SchoolAdmin` holds `("manage", …)` for all three, so the feature-pack half of
the dependency is what answers 403 "Feature not available in your plan", and the
interceptor redirects to `/auth/no-access`. Because the attendance call is on
mount, a SchoolAdmin of a school without the `attendance` module could not open
a student's record **at all** — and that record screen is the only place the
product offers an "Edit" button for a student (the register's row has a "View"
link and nothing else), so the whole manage path for a licensed `students`
module was unreachable.

The change mirrors the existing `librarySectionEnabled` treatment: the three
licences are read once per mount through `hasModuleLicence`, `loadAttendance`
returns early without one, and the two Academics fetches are skipped the same
way. The tabs themselves are untouched (a school licensed for one of the three
still sees the panel it paid for), no gate was added or tightened, the backend
is untouched, and a fully licensed school sees exactly what it saw before.

Both changes above are held shut by
`tests/modules/people/test_students.py::test_school_admin_admits_and_amends_a_student`,
which runs on the `minimal` pack (no `guardians`, no `attendance`, no
`assessments`, no `classes_and_timetables`), admits a pupil through the wizard,
opens their record and edits it — asserting the admin stays on
`/module/students` rather than landing on `/auth/no-access`.

---

## Edit-student wizard — it posted a fee instruction it never collected

**Classification: defect fix**
(`smsfrontend/src/app/module/students/edit-student/[editstudentId]/page.tsx`,
`handleSubmit`). Backend untouched.

`/module/students/edit-student/<id>` renders exactly three steps — Basic
Information, Contact Details, Admission Information (`STEPS` at the top of the
file). None of them mounts `components/feesDiscount.tsx`, so nothing on this
screen can ever write `formData.fees_breakdown`: it is `[]` from
`initialFormData` and set to `[]` again by the prefill effect (line 148).
`handleSubmit` nevertheless sent `fees_breakdown: formData.fees_breakdown` on
every save — i.e. always the empty list.

The backend reads that key as an instruction, not as an absence
(`services/student_service.py::update_student`):

```python
elif fees_breakdown is not None or extra_fees is not None:
    self._update_student_fees(student_id, fees_breakdown, extra_fees)
```

so `[]` routes into `_update_student_fees`, which

1. raises `"No class assignment found for student"` when the pupil has no
   `ClassStudent` row for the active year. `update_student` catches, rolls the
   transaction back, and `api/routes/student.py` answers **400** — so a pupil
   with no class cannot be corrected *at all*, and every field the admin typed
   is discarded. On the `minimal` pack this is every pupil in the school: that
   pack has no `classes_and_timetables` module, so no class exists to enrol
   into, while the admission wizard treats Class as optional and admits them
   happily. The product creates records its own edit screen then refuses to
   save.
2. and for a pupil who *does* have a class, deletes their `StudentClassFeeItem`
   rows and resets `total_net_payable` to the class default (the `else` branch
   at student_service.py:472) — silently wiping per-student discounts that this
   screen never displayed and never offered to change.

**Evidence.** Live probe against `PUT /student/112` (a pupil of the `minimal`
school, no class assignment): identical body **with** `fees_breakdown: []` →
`400`; **without** the key → `200` and the record updated. Backend log for the
failing run: `"PUT /api/v1/student/112 HTTP/1.1" 400 Bad Request`.

**The change.** `fees_breakdown` is now omitted unless this wizard actually
holds one, mirroring the `class_id` guard immediately above it ("Only include
class_id if it's not 0"), which exists for the same reason. Left unset, the
Pydantic default is `None` and the service reads it as "no fee change
requested". A school that has classes and per-student discounts sees exactly
what it saw before, minus the wipe; no route, parameter, permission or licence
gate was touched.

Held shut by
`tests/modules/people/test_students.py::test_school_admin_admits_and_amends_a_student`
(the `minimal` pack), which admits a pupil with no class, edits their record and
asserts the corrections on the reloaded profile and on `GET /student/<id>`.

**Not fixed here, flagged for the ruling:** the backend's
`StudentProfileCreate.fees_breakdown` is declared `list[StudentFeeItem] =
Field(None)` (`api/api_models/student.py:28`) — a `None` default against a
non-`Optional` list, so *omitting* the field on `POST /student/` is a 422
"Input should be a valid list". Only its sibling on the update model is written
`Optional[...]`. Every caller in the product sends `[]`, so nothing in the app
hits it; whether the field is meant to be optional on create is a schema
decision, not something to change unattended. The suite's API-level seed sends
`[]` like the wizard does.
