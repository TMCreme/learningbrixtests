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
