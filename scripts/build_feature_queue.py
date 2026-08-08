#!/usr/bin/env python
"""Generate config/features.yaml — the unit of work for the autonomous loop.

A "feature unit" is one module × one role × one intent. Units are derived from
config/module_catalog.py crossed with the role matrix in docs/plan.md §8, then
paired with a scenario that makes the assertion meaningful:

  * positive units run in a scenario where the module is ENABLED
  * negative units run in a scenario where the module is DISABLED

Only positive units record video — "access denied" is a correct outcome but not
something worth publishing as a feature demo.

The generated file is meant to be edited by hand afterwards: re-running this
script rewrites it, so tune the queue and then leave it alone (the ledger keeps
progress separately, so regenerating does not lose work).

    python scripts/build_feature_queue.py            # write config/features.yaml
    python scripts/build_feature_queue.py --dry-run  # print a summary instead
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from config.module_catalog import CATALOG, ModuleDef  # noqa: E402
from config.scenarios import load_scenarios  # noqa: E402
from config.settings import ROOT, get_settings  # noqa: E402


OUT_PATH = ROOT / "config" / "features.yaml"

# Roles that manage a module, and roles that merely consume it. Mirrors the
# coverage matrix in docs/plan.md §8. `manage` roles get a create/edit demo;
# `view` roles get a read-only demo.
ROLE_MATRIX: dict[str, dict[str, list[str]]] = {
    "home":                   {"manage": [],                "view": ["school_admin", "teacher", "student"]},
    "dashboard":              {"manage": [],                "view": ["school_admin", "teacher"]},
    "school_admin_dashboard": {"manage": [],                "view": ["school_admin"]},
    "students":               {"manage": ["school_admin"],  "view": ["teacher", "guardian"]},
    "staff":                  {"manage": ["school_admin"],  "view": []},
    "guardians":              {"manage": ["school_admin"],  "view": []},
    "fees":                   {"manage": ["accountant"],    "view": ["school_admin", "guardian"]},
    "incomes_and_expenses":   {"manage": ["accountant"],    "view": ["school_admin"]},
    "employee_benefit":       {"manage": ["school_admin"],  "view": ["accountant"]},
    "staff_payroll":          {"manage": ["accountant"],    "view": ["teacher"]},
    "categories":             {"manage": ["school_admin"],  "view": []},
    "catalogue":              {"manage": ["school_admin"],  "view": ["teacher", "student"]},
    "statistics":             {"manage": [],                "view": ["school_admin"]},
    "requests_and_renewals":  {"manage": ["school_admin"],  "view": ["student"]},
    "subjects":               {"manage": ["school_admin"],  "view": ["teacher"]},
    "classes_and_timetables": {"manage": ["school_admin"],  "view": ["teacher", "student"]},
    "exams":                  {"manage": ["school_admin"],  "view": ["teacher"]},
    "attendance":             {"manage": ["teacher"],       "view": ["school_admin", "guardian"]},
    "lessons":                {"manage": ["teacher"],       "view": ["student"]},
    "syllabi":                {"manage": ["teacher"],       "view": []},
    "topics":                 {"manage": ["teacher"],       "view": ["student"]},
    "assessments":            {"manage": ["teacher"],       "view": ["school_admin"]},
    "student_timetables":     {"manage": [],                "view": ["student", "guardian"]},
    "student_scores":         {"manage": ["teacher"],       "view": ["student", "guardian"]},
    "change_requests":        {"manage": ["school_admin"],  "view": ["teacher"]},
    "incidents":              {"manage": ["teacher"],       "view": ["school_admin"]},
    "school_configuration":   {"manage": ["school_admin"],  "view": []},
    "access_roles":           {"manage": ["school_admin"],  "view": []},
    "audit_trails":           {"manage": [],                "view": ["school_admin"]},
    "academic_year_and_term": {"manage": ["school_admin"],  "view": []},
    "messaging":              {"manage": ["school_admin"],  "view": ["teacher", "guardian"]},
    "community":              {"manage": ["school_admin"],  "view": ["student"]},
}

PRETTY: dict[str, str] = {
    "home": "Home",
    "dashboard": "Dashboard",
    "school_admin_dashboard": "School Admin Dashboard",
    "students": "Students",
    "staff": "Staff",
    "guardians": "Guardians",
    "fees": "Fees",
    "incomes_and_expenses": "Income & Expenses",
    "employee_benefit": "Employee Benefits",
    "staff_payroll": "Staff Payroll",
    "categories": "Library Categories",
    "catalogue": "Library Catalogue",
    "statistics": "Library Statistics",
    "requests_and_renewals": "Requests & Renewals",
    "subjects": "Subjects",
    "classes_and_timetables": "Classes & Timetables",
    "exams": "Exams",
    "attendance": "Attendance",
    "lessons": "Lessons",
    "syllabi": "Syllabi",
    "topics": "Subject Topics",
    "assessments": "Assessments",
    "student_timetables": "Student Timetables",
    "student_scores": "Student Scores",
    "change_requests": "Change Requests",
    "incidents": "Incident Reports",
    "school_configuration": "School Configuration",
    "access_roles": "Access & Roles",
    "audit_trails": "Audit Trails",
    "academic_year_and_term": "Academic Year & Term",
    "messaging": "Messaging",
    "community": "Community",
}

ROLE_LABEL = {
    "school_admin": "SchoolAdmin",
    "teacher": "Teacher",
    "student": "Student",
    "guardian": "Guardian",
    "accountant": "Accountant",
    "admin": "Admin",
    "super_admin": "SuperAdmin",
}


def test_path_for(module: ModuleDef) -> str:
    return f"tests/modules/{module.category}/test_{module.key}.py"


def build() -> list[dict]:
    settings = get_settings()
    scenarios = load_scenarios(settings.scenarios_file)

    def enabling(module_key: str) -> str | None:
        # Prefer the most specialised scenario that enables it, so demos are
        # recorded against a realistically-scoped school rather than always the
        # everything-on one.
        matches = [s for s in scenarios if module_key in s.modules]
        if not matches:
            return None
        matches.sort(key=lambda s: len(s.modules))
        return matches[0].id

    def disabling(module_key: str) -> str | None:
        matches = [s for s in scenarios if module_key not in s.modules]
        if not matches:
            return None
        matches.sort(key=lambda s: len(s.modules))
        return matches[0].id

    units: list[dict] = []
    for module in CATALOG:
        matrix = ROLE_MATRIX.get(module.key, {"manage": ["school_admin"], "view": []})
        pretty = PRETTY.get(module.key, module.key.replace("_", " ").title())
        on_scenario = enabling(module.key)
        off_scenario = disabling(module.key)
        path = test_path_for(module)

        for role in matrix["manage"]:
            if on_scenario is None:
                continue
            units.append({
                "id": f"{module.category}.{module.key}.manage.{role}",
                "module": module.key,
                "route": module.frontend_route,
                "title": pretty,
                "subtitle": f"{ROLE_LABEL.get(role, role)} creates and manages {pretty.lower()}",
                "roles": [role],
                "intent": "manage",
                "scenario": on_scenario,
                "test_path": path,
                "video": True,
            })

        for role in matrix["view"]:
            if on_scenario is None:
                continue
            units.append({
                "id": f"{module.category}.{module.key}.view.{role}",
                "module": module.key,
                "route": module.frontend_route,
                "title": pretty,
                "subtitle": f"{ROLE_LABEL.get(role, role)} views {pretty.lower()}",
                "roles": [role],
                "intent": "view",
                "scenario": on_scenario,
                "test_path": path,
                "video": True,
            })

        if off_scenario is not None:
            units.append({
                "id": f"{module.category}.{module.key}.denied",
                "module": module.key,
                "route": module.frontend_route,
                "title": pretty,
                "subtitle": f"{pretty} is hidden when the feature pack excludes it",
                "roles": ["school_admin"],
                "intent": "negative",
                "scenario": off_scenario,
                "test_path": path,
                "video": False,
            })

    return units


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    units = build()
    videos = sum(1 for u in units if u["video"])
    summary = (f"{len(units)} feature units "
               f"({videos} with video, {len(units) - videos} negative-path)")

    if args.dry_run:
        print(summary)
        for u in units[:15]:
            print(f"  {u['id']:<58} [{u['scenario']}]")
        print(f"  ... and {max(0, len(units) - 15)} more")
        return 0

    header = (
        "# Generated by scripts/build_feature_queue.py — safe to hand-edit.\n"
        "# Regenerating overwrites this file but NOT state/feature_ledger.json,\n"
        "# so progress survives a rebuild of the queue.\n"
        "#\n"
        "# One unit = one module x one role x one intent.\n"
        "#   intent: manage   -> create/edit happy path, records video\n"
        "#   intent: view     -> read-only happy path, records video\n"
        "#   intent: negative -> module disabled by the feature pack, no video\n\n"
    )
    OUT_PATH.write_text(header + yaml.safe_dump(
        {"features": units}, sort_keys=False, width=100, allow_unicode=True,
    ))
    print(f"{summary} → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
