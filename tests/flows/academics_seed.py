"""Setup-only seeding for the academics chain an assessment hangs off.

``/module/assessment_score`` cannot create anything on its own: the Create
Assessment modal's two required dropdowns are a **lesson** and an **assessment
category**, and the category list is derived from the *lesson's syllabus*. So a
teacher can only reach the feature once a topic, a syllabus (carrying its
categories) and a syllabus lesson already exist — three other modules'
walkthroughs, none of which is the thing an assessments test is proving.

They are therefore seeded over the API as the SchoolAdmin, exactly as
``school_provisioning._seed_fee_group`` seeds the fee group the Add Class dialog
insists on. Nothing here is ever asserted; it is a prerequisite, not a test.

One extra step has nothing to do with the dropdowns and everything to do with
authorization: ``AssessmentService._assert_can_manage`` lets a teacher author an
assessment only for a (subject, class) pair they are the **subject teacher** of
(``teacher_subject_class_association``). Provisioning makes its teacher the
*class teacher* of "Grade 6", which grants read-only visibility and no writes at
all — ``can_manage_subject_class`` deliberately ignores ``class_ids``. Without
the assignment written here the create would answer
403 "Only the subject teacher can manage this".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import structlog

from tests.fixtures.api_client import BackendAPI, Credentials
from tests.fixtures.data_factories import run_tag

log = structlog.get_logger(__name__)

# Named with the "TEST" prefix so the orphan sweeper recognises anything these
# leave behind, and with the run tag so parallel agents never collide.
TOPIC_NAME = "TEST Fractions"
SYLLABUS_NAME = "TEST Term Syllabus"
CATEGORY_NAME = "TEST Class Quizzes"
LESSON_TITLE = "TEST Fractions Lesson"

# A single category has to carry the whole weighting: the backend rejects a
# syllabus whose category weights do not sum to 100%.
CATEGORY_WEIGHT = 100.0


class AcademicsSeedError(RuntimeError):
    """A prerequisite could not be seeded, so the feature is unreachable."""


@dataclass
class AcademicsSeed:
    """The ids and display names the assessments UI will offer."""

    branch_id: int
    subject_id: int
    class_id: int
    teacher_profile_id: int
    topic_id: int
    syllabus_id: int
    category_id: int
    lesson_id: int
    lesson_title: str
    category_name: str


def seed_assessment_prerequisites(
    api: BackendAPI,
    school_admin: Credentials,
    *,
    school_id: int,
    branch_id: int,
    subject_name: str,
    class_name: str,
    teacher_email: str,
) -> AcademicsSeed:
    """Topic → syllabus (+category) → lesson, plus the subject-teacher assignment.

    Raises :class:`AcademicsSeedError` naming the step that failed — a seeding
    failure must not be reported as "the Create Assessment modal offered no
    lessons", which is the same symptom with none of the cause.
    """
    if branch_id <= 0:
        raise AcademicsSeedError("provisioning captured no branch id")

    tag = run_tag()
    token = _login(api, school_admin)

    subject_id = _find_id(
        _json(api.get(f"/subjects/?branch_id={branch_id}&limit=100", token=token)),
        subject_name, what="subject",
    )
    class_id = _find_id(
        _json(api.get(f"/classes/?branch_id={branch_id}&limit=100", token=token)),
        class_name, what="class",
    )
    year_id, term_id = _active_year_and_term(api, token, school_id=school_id)
    teacher_profile_id = _teacher_profile_id(api, token, branch_id=branch_id,
                                             email=teacher_email)

    _assign_subject_teacher(
        api, token,
        teacher_profile_id=teacher_profile_id,
        subject_id=subject_id,
        class_id=class_id,
    )

    topic_name = f"{TOPIC_NAME} {tag}"
    topic_id = _existing_id(
        api.get(
            f"/topics/?branch_id={branch_id}&subject_id={subject_id}&limit=100",
            token=token,
        ),
        topic_name,
    )
    if topic_id is None:
        topic_id = _post_id(
            api, token, f"/topics/?branch_id={branch_id}",
            {
                "name": topic_name,
                "description": "Seeded so a syllabus has something to teach.",
                "subject_id": subject_id,
                "order_index": 0,
            },
            step="topic",
        )

    syllabus_name = f"{SYLLABUS_NAME} {tag}"
    syllabus = _existing_row(
        api.get(
            f"/syllabi/?branch_id={branch_id}&class_id={class_id}"
            f"&subject_id={subject_id}&limit=100",
            token=token,
        ),
        syllabus_name,
    )
    if syllabus is None:
        syllabus = _post(
            api, token, f"/syllabi/?branch_id={branch_id}",
            {
                "name": syllabus_name,
                "description": "Seeded prerequisite for the assessments walkthrough.",
                "class_id": class_id,
                "subject_id": subject_id,
                "academic_year_id": year_id,
                "academic_term_id": term_id,
                "status": "published",
                "topic_ids": [
                    {"topic_id": topic_id, "order_index": 0, "is_optional": False}
                ],
                "assessment_categories": [
                    {
                        "name": f"{CATEGORY_NAME} {tag}",
                        "description": "Seeded assessment category.",
                        "weight_percentage": CATEGORY_WEIGHT,
                    }
                ],
            },
            step="syllabus",
        )
    syllabus_id = int(syllabus["id"])
    category = _first_category(api, token, syllabus_id=syllabus_id, syllabus=syllabus)

    lesson_title = f"{LESSON_TITLE} {tag}"
    lesson_id = _existing_id(
        api.get(
            f"/lessons/?branch_id={branch_id}&class_id={class_id}"
            f"&subject_id={subject_id}&limit=100",
            token=token,
        ),
        lesson_title,
        key="title",
    )
    if lesson_id is None:
        lesson_id = _post_id(
            api, token, f"/lessons/?branch_id={branch_id}",
            {
                "title": lesson_title,
                "description": "Seeded prerequisite for the assessments walkthrough.",
                "lesson_type": "syllabus",
                "topic_id": topic_id,
                "syllabus_id": syllabus_id,
                "subject_id": subject_id,
                "class_id": class_id,
                "teacher_id": teacher_profile_id,
                "scheduled_date": (date.today() + timedelta(days=1)).isoformat(),
                "duration_minutes": 40,
            },
            step="lesson",
        )

    seed = AcademicsSeed(
        branch_id=branch_id,
        subject_id=subject_id,
        class_id=class_id,
        teacher_profile_id=teacher_profile_id,
        topic_id=topic_id,
        syllabus_id=syllabus_id,
        category_id=int(category["id"]),
        lesson_id=lesson_id,
        lesson_title=lesson_title,
        category_name=str(category["name"]),
    )
    log.info(
        "academics_seed.done",
        branch_id=branch_id,
        syllabus_id=seed.syllabus_id,
        category=seed.category_name,
        lesson=seed.lesson_title,
        teacher_profile_id=teacher_profile_id,
    )
    return seed


# ───────────────────────────── internals ─────────────────────────────────────


def _login(api: BackendAPI, creds: Credentials) -> str:
    try:
        return str(api.login(creds.email, creds.password)["access_token"])
    except Exception as exc:  # noqa: BLE001 — re-raised with the step named
        raise AcademicsSeedError(f"could not log in as {creds.email}: {exc}") from exc


def _json(response) -> Any:
    if response.status_code >= 400:
        raise AcademicsSeedError(
            f"{response.request.method} {response.request.url.path} → "
            f"{response.status_code}: {response.text[:300]}"
        )
    return response.json()


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Some list endpoints answer a bare list, others a paginated envelope."""
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    return [row for row in payload if isinstance(row, dict)]


def _existing_row(response, name: str, *, key: str = "name") -> dict[str, Any] | None:
    """A row already seeded under ``name``, or ``None``.

    ``provisioned_school`` is session-scoped, so every academics test in a batch
    shares one school — and the names below carry the *run* tag, which is
    process-wide. Seeding twice against the same school is therefore normal, and
    the backend refuses it: a topic name is unique per subject
    (topic_service: "Topic with this name already exists for this subject") and a
    syllabus is unique per class/term/year/subject. Reusing what is already there
    is what makes this helper safe to call once per test rather than once per run.

    A failed lookup is never fatal — the create that follows reports the real
    problem with far more context than a list GET could.
    """
    if response.status_code >= 400:
        return None
    for row in _rows(response.json()):
        if str(row.get(key, "")).strip().casefold() == name.casefold():
            return row
    return None


def _existing_id(response, name: str, *, key: str = "name") -> int | None:
    row = _existing_row(response, name, key=key)
    return int(row["id"]) if row else None


def _find_id(payload: Any, name: str, *, what: str) -> int:
    for row in _rows(payload):
        if str(row.get("name", "")).strip().casefold() == name.casefold():
            return int(row["id"])
    raise AcademicsSeedError(
        f"no {what} named {name!r} in this branch — provisioning should have "
        f"created it; got {[r.get('name') for r in _rows(payload)]}"
    )


def _active_year_and_term(api: BackendAPI, token: str, *, school_id: int) -> tuple[int, int]:
    years = _rows(_json(api.get(
        f"/academic-year/?skip=0&limit=100&school_id={school_id}", token=token)))
    year = next((y for y in years if y.get("is_active")), years[0] if years else None)
    if not year:
        raise AcademicsSeedError("the school has no academic year")

    terms = _rows(_json(api.get(f"/academic-term/by-year/{year['id']}", token=token)))
    term = next((t for t in terms if t.get("is_active")), terms[0] if terms else None)
    if not term:
        raise AcademicsSeedError("the active academic year has no term")
    return int(year["id"]), int(term["id"])


def _teacher_profile_id(api: BackendAPI, token: str, *, branch_id: int, email: str) -> int:
    payload = _json(api.get(f"/teacher/?branch_id={branch_id}&limit=100", token=token))
    for row in _rows(payload):
        user = row.get("user") or {}
        if str(user.get("email", "")).casefold() == email.casefold():
            return int(row["id"])
    raise AcademicsSeedError(
        f"no teacher profile for {email!r} in branch {branch_id} — "
        "the assessments flow needs the provisioned teacher."
    )


def _assign_subject_teacher(api: BackendAPI, token: str, *, teacher_profile_id: int,
                            subject_id: int, class_id: int) -> None:
    """Make the teacher the subject teacher of (subject, class).

    Idempotent server-side: duplicate triples are skipped. The subject must
    already be part of the class's curriculum, which provisioning's
    ``SubjectsPage.create_subject(classes=[…])`` guarantees.
    """
    response = api.post(
        f"/teacher/{teacher_profile_id}/subject-assignments",
        token=token,
        json={"assignments": [{"subject_id": subject_id, "class_id": class_id}]},
    )
    if response.status_code >= 400:
        raise AcademicsSeedError(
            "could not make the teacher the subject teacher of "
            f"(subject {subject_id}, class {class_id}) — without it the backend "
            f"answers 403 on create: {response.status_code} {response.text[:300]}"
        )


def _post(api: BackendAPI, token: str, path: str, payload: dict, *, step: str) -> dict:
    response = api.post(path, token=token, json=payload)
    if response.status_code >= 400:
        raise AcademicsSeedError(
            f"could not seed the {step}: {response.status_code} {response.text[:300]}"
        )
    body = response.json()
    if not isinstance(body, dict) or "id" not in body:
        raise AcademicsSeedError(f"the {step} create returned no id: {body!r}")
    return body


def _post_id(api: BackendAPI, token: str, path: str, payload: dict, *, step: str) -> int:
    return int(_post(api, token, path, payload, step=step)["id"])


def _first_category(api: BackendAPI, token: str, *, syllabus_id: int,
                    syllabus: dict) -> dict[str, Any]:
    """The category created alongside the syllabus.

    The create response embeds ``assessment_categories``; the by-syllabus list is
    the fallback for the day it stops doing so.
    """
    embedded = _rows(syllabus.get("assessment_categories") or [])
    if embedded:
        return embedded[0]

    listed = _rows(_json(api.get(
        f"/assessments/categories/syllabus/{syllabus_id}", token=token)))
    if listed:
        return listed[0]
    raise AcademicsSeedError(
        f"syllabus {syllabus_id} carries no assessment category — the Create "
        "Assessment modal's category dropdown would stay empty."
    )
