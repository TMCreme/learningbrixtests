#!/usr/bin/env python
"""Export the tested features as a CSV for product/BA review.

One row per feature unit the suite actually covers, built from the ledger plus
the demo manifests. The manifests matter: their step captions were written to be
read by a viewer of the video, so they describe what the feature genuinely does
rather than what a template guessed.

    python scripts/export_feature_matrix.py            # -> reports/feature_matrix.csv
    python scripts/export_feature_matrix.py --out X    # somewhere else
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ROOT  # noqa: E402


LEDGER = ROOT / "state" / "feature_ledger.json"
RAW = ROOT / "artifacts" / "videos" / "raw"

# The screen a user would name, keyed by the module's frontend route. The route
# alone is not a screen name ("assessment_score" is "Assessment & Scores"), and
# the CSV is for people who talk about the product, not the codebase.
SCREENS: dict[str, str] = {
    "academic_year_and_term": "Academic Year & Term",
    "access_roles": "Access & Roles",
    "assessment_score": "Assessment & Scores",
    "attendance": "Attendance",
    "audit_trails": "Audit Trails",
    "catalogue": "Library Catalogue",
    "categories": "Library Categories",
    "pending_requests": "Change Requests",
    "classes_and_timetables": "Classes & Timetables",
    "community": "Community",
    "config": "School Configuration",
    "dashboard": "Dashboard",
    "employee_benefit": "Employee Benefits",
    "fees": "Fees",
    "guardians": "Guardians",
    "home": "Home",
    "incidents_reporting": "Incident Reports",
    "income_and_expenses": "Income & Expenses",
    "lessons": "Lessons",
    "messages": "Messages",
    "requests_and_renewals": "Requests & Renewals",
    "school_admin_dashboard": "School Admin Dashboard (Branches)",
    "staff": "Staff",
    "staff_payroll": "Staff Payroll",
    "statistics": "Library Statistics",
    "student_assessment_score": "Student Scores",
    "student_timetables": "Student Timetables",
    "students": "Students",
    "subjects": "Subjects",
    "subject_topics": "Subject Topics",
    "syllabus": "Syllabus",
}

# The catalog records no frontend_route for these two.
ROUTE_OVERRIDES = {"syllabi": "syllabus", "exams": None}

# Why the module exists — the "so that" half of each story. Written per module
# because a generic benefit clause ("so that I can manage the system") is worth
# nothing to whoever reads this next.
PURPOSE: dict[str, str] = {
    "academic_year_and_term": "the school's terms and dates frame everything else that is recorded",
    "access_roles": "each person sees only what their job requires",
    "assessments": "coursework is defined before any marks are recorded against it",
    "attendance": "absence is recorded daily and can be corrected when it is wrong",
    "audit_trails": "there is an account of who changed what, after the fact",
    "catalogue": "the library's holdings are known and lendable",
    "categories": "the catalogue stays organised as it grows",
    "change_requests": "changes to sensitive records are reviewed before they take effect",
    "classes_and_timetables": "students and teaching time are organised into classes",
    "community": "the school can reach everyone in one place",
    "dashboard": "the day's position is visible without hunting for it",
    "employee_benefit": "staff entitlements are defined before payroll uses them",
    "exams": "formal examinations can be scheduled and marked",
    "fees": "what each family owes is defined and collectable",
    "guardians": "every student has a contactable adult on record",
    "home": "there is a landing point that reflects the person's role",
    "incidents": "safeguarding and behaviour concerns are recorded and followed up",
    "incomes_and_expenses": "money in and out of the school is accounted for",
    "lessons": "teaching is planned against the timetable",
    "messaging": "staff and families can correspond privately",
    "requests_and_renewals": "borrowing and returns are tracked to a person",
    "school_admin_dashboard": "campuses are set up and administered separately",
    "school_configuration": "the school's own identity and settings are correct",
    "staff": "employment records are complete and current",
    "staff_payroll": "staff are paid correctly and on time",
    "statistics": "library use can be seen and acted on",
    "student_scores": "attainment is recorded against each student",
    "student_timetables": "a student knows where to be and when",
    "students": "the roll is accurate and every child is accounted for",
    "subjects": "the curriculum is defined and assignable",
    "syllabi": "each subject's coverage is planned and visible",
    "topics": "a subject breaks down into teachable units",
}

ROLE_NAMES = {
    "school_admin": "school administrator",
    "teacher": "teacher",
    "student": "student",
    "guardian": "guardian",
    "accountant": "accountant",
    "super_admin": "super administrator",
}

# Steps that describe getting to the screen rather than the feature itself.
NAVIGATION = re.compile(
    r"^\s*(sign in|log in|open |choose the campus|choose the branch|select the campus|"
    r"back inside|land on|navigate|go to)",
    re.I,
)


def load_manifest(unit_id: str) -> dict | None:
    path = RAW / (re.sub(r"[^0-9a-zA-Z]+", "_", unit_id).strip("_").lower() + ".json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def substantive_steps(manifest: dict | None) -> list[str]:
    """The captions that describe the feature, minus the getting-there ones."""
    if not manifest:
        return []
    return [
        s["caption"].strip()
        for s in manifest.get("steps", [])
        if not NAVIGATION.match(s.get("caption", ""))
    ]


# "Open Assessment & Scores from the Academics menu" -> "Assessment & Scores".
# Worth reading because the screen a consuming role actually uses is often not
# their module's own screen — a guardian reads their wards from Home, not from
# the Students register.
#
# Anchored on an imperative "Open …" so it cannot match narration
# ("The register opens on their branch's headline numbers"), and the result is
# only trusted when it names a screen this file already knows. A loose version
# of this produced screens called "William Chandler's record"; a coarse-but-true
# location beats a confident wrong one.
OPENS = re.compile(r"^\s*Open\s+(?:the\s+)?(.+?)"
                   r"(?:\s+(?:from|workspace|screen|page|tab)\b|[,.—]|$)", re.I)


def screen_from_steps(manifest: dict | None, known: set[str]) -> str:
    if not manifest:
        return ""
    for step in manifest.get("steps", []):
        match = OPENS.match(step.get("caption", ""))
        if not match:
            continue
        name = match.group(1).strip(" .,—")
        for candidate in known:
            if name.lower() == candidate.lower():
                return candidate
    return ""


def feature_and_story(unit: dict, steps: list[str]) -> tuple[str, str]:
    module = unit["module"]
    intent = unit.get("intent") or "manage"
    title = unit.get("title") or module.replace("_", " ").title()
    role = ROLE_NAMES.get((unit.get("roles") or ["school_admin"])[0], "user")
    purpose = PURPOSE.get(module, f"{title.lower()} works as intended")

    if intent == "negative":
        return (
            f"{title} withheld when the plan excludes it",
            f"As a {role} whose plan does not include {title}, I want the module "
            f"to be unavailable to me, so that nobody is shown a feature the "
            f"school has not bought.",
        )

    if intent == "mandatory":
        return (
            f"{title} available on every plan",
            f"As a {role} on the most restricted plan we sell, I want {title} to "
            f"stay available, so that {purpose} no matter what the school pays for.",
        )

    # manage / view. The feature name is composed rather than lifted from the
    # subtitle: the subtitles are written role-first ("Teacher creates and
    # manages assessments"), and stripping that prefix leaves a dangling verb.
    verb, want = ("Create and manage", "set up and maintain") if intent == "manage" \
        else ("View", "follow")
    feature = f"{verb} {title.lower()} ({role})"

    # Captions keep their own capitalisation — lowercasing the first word
    # mangles the generated names the demos are full of ("Anthony Stone").
    actions = "; ".join(steps[:3]) if steps else (unit.get("subtitle") or "")

    story = f"As a {role}, I want to {want} {title.lower()}"
    if actions:
        story += f" — {actions}"
    story += f" — so that {purpose}."
    return feature, story


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "reports" / "feature_matrix.csv"))
    args = parser.parse_args()

    ledger = json.loads(LEDGER.read_text())["features"]
    covered = {
        k: v for k, v in ledger.items()
        if v.get("status") in ("video_done", "passing")
    }

    rows = []
    for unit_id, unit in sorted(covered.items()):
        module = unit["module"]
        route = ROUTE_OVERRIDES.get(module, unit.get("route"))
        screen = SCREENS.get(route or "", "")
        if route and screen:
            location = f"{screen} (/module/{route})"
        elif route:
            location = f"/module/{route}"
        else:
            location = "No screen — module is licensable but ships no UI"

        manifest = load_manifest(unit_id)
        steps = substantive_steps(manifest)
        feature, story = feature_and_story(unit, steps)

        # Prefer the screen the recording actually opens over the module's own
        # route — they differ wherever a role consumes another module's data.
        recorded = screen_from_steps(manifest, set(SCREENS.values()))
        if recorded and recorded.lower() != (screen or "").lower():
            location = f"{recorded}" + (f" (/module/{route})" if route else "")

        rows.append({
            "Screen/Location": location,
            "Module": unit.get("title") or module,
            "Feature": feature,
            "User Story": story,
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["Screen/Location", "Module", "Feature", "User Story"]
        )
        writer.writeheader()
        writer.writerows(rows)

    with_steps = sum(1 for r in rows if " — " in r["User Story"])
    print(f"{len(rows)} features → {out}")
    print(f"  {with_steps} stories written from recorded demo steps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
