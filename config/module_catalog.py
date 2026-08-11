"""Canonical list of gatable modules, mirroring the backend's feature_pack_service.

Used to validate feature_scenarios.yaml — any module name in a scenario must
appear here, and the loader warns if a module is never enabled by any scenario
(i.e., never positively tested).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleDef:
    key: str           # canonical key used in feature packs
    category: str      # backend grouping
    frontend_route: str | None  # /module/<route>, None if no direct page


# Mirrors services/feature_pack_service.py module groups in newschoolapp.
# Keep in sync if backend adds/renames modules.
CATALOG: tuple[ModuleDef, ...] = (
    # people
    ModuleDef("home",                       "people",            "home"),
    ModuleDef("dashboard",                  "people",            "dashboard"),
    ModuleDef("students",                   "people",            "students"),
    ModuleDef("staff",                      "people",            "staff"),
    ModuleDef("guardians",                  "people",            "guardians"),

    # account
    ModuleDef("fees",                       "account",           "fees"),
    ModuleDef("incomes_and_expenses",       "account",           "income_and_expenses"),

    # payroll
    ModuleDef("employee_benefit",           "payroll",           "employee_benefit"),
    ModuleDef("staff_payroll",              "payroll",           "staff_payroll"),

    # library
    ModuleDef("categories",                 "library",           "categories"),
    ModuleDef("catalogue",                  "library",           "catalogue"),
    ModuleDef("statistics",                 "library",           "statistics"),
    ModuleDef("requests_and_renewals",      "library",           "requests_and_renewals"),

    # academics
    ModuleDef("subjects",                   "academics",         "subjects"),
    ModuleDef("classes_and_timetables",     "academics",         "classes_and_timetables"),
    ModuleDef("exams",                      "academics",         None),
    ModuleDef("attendance",                 "academics",         "attendance"),
    ModuleDef("lessons",                    "academics",         "lessons"),
    ModuleDef("syllabi",                    "academics",         None),
    ModuleDef("topics",                     "academics",         "subject_topics"),
    ModuleDef("assessments",                "academics",         "assessment_score"),
    ModuleDef("student_timetables",         "academics",         "student_timetables"),
    ModuleDef("student_scores",             "academics",         "student_assessment_score"),

    # change requests / incidents
    # "pending_requests" is the approver-facing page and the only one of the two
    # change-request routes a SchoolAdmin is offered; the requester-facing
    # "/module/change_request" excludes Admin and SchoolAdmin in nav-config.
    ModuleDef("change_requests",            "change_requests",   "pending_requests"),
    ModuleDef("incidents",                  "incident_reports",  "incidents_reporting"),

    # governance
    ModuleDef("school_admin_dashboard",     "governance",        "school_admin_dashboard"),
    ModuleDef("school_configuration",       "governance",        "config"),
    ModuleDef("access_roles",               "governance",        "access_roles"),
    ModuleDef("audit_trails",               "governance",        "audit_trails"),
    ModuleDef("academic_year_and_term",     "governance",        "academic_year_and_term"),

    # general
    ModuleDef("messaging",                  "general",           "messages"),
    ModuleDef("community",                  "general",           "community"),
)


KNOWN_MODULES: frozenset[str] = frozenset(m.key for m in CATALOG)


def get(key: str) -> ModuleDef:
    for m in CATALOG:
        if m.key == key:
            return m
    raise KeyError(f"Unknown module: {key!r}. Add it to config/module_catalog.py "
                   f"if the backend supports it.")


def by_category(category: str) -> tuple[ModuleDef, ...]:
    return tuple(m for m in CATALOG if m.category == category)


# Modules no feature pack can exclude. The pack builder locks the "people" and
# "governance" groups into every pack (BASIC_GROUPS in
# smsfrontend/src/app/module/feature_flag/{create,edit}/page.tsx), with only
# `guardians` and `families` optional inside them. Confirmed intended on
# 2026-08-09: governance is core and always on.
#
# These therefore have no denial path. The queue gives them an
# `always_licensed` unit instead of a `denied` one, and coverage_warnings()
# must not report them as "never negatively tested" — that is the design.
MANDATORY_MODULES: frozenset[str] = frozenset({
    "home",
    "dashboard",
    "students",
    "staff",
    "school_admin_dashboard",
    "school_configuration",
    "access_roles",
    "audit_trails",
    "academic_year_and_term",
})
