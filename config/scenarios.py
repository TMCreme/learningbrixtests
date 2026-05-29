"""Load and validate config/feature_scenarios.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from config.module_catalog import KNOWN_MODULES


REQUIRED_PER_SCENARIO = frozenset({"school_configuration"})


@dataclass(frozen=True)
class Scenario:
    id: str
    school_name: str
    feature_pack_name: str
    modules: frozenset[str] = field(default_factory=frozenset)

    def has(self, module: str) -> bool:
        return module in self.modules


class ScenarioConfigError(Exception):
    pass


def load_scenarios(path: str | Path) -> tuple[Scenario, ...]:
    path = Path(path)
    if not path.exists():
        raise ScenarioConfigError(f"Scenarios file not found: {path}")

    with path.open() as f:
        raw = yaml.safe_load(f) or {}

    items = raw.get("scenarios") or []
    if not items:
        raise ScenarioConfigError(
            f"No scenarios defined in {path}. Add at least one under `scenarios:`."
        )

    scenarios: list[Scenario] = []
    seen_ids: set[str] = set()

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ScenarioConfigError(f"Scenario #{i} is not a mapping: {item!r}")

        for required in ("id", "school_name", "feature_pack_name", "modules"):
            if required not in item:
                raise ScenarioConfigError(
                    f"Scenario #{i} missing required key {required!r}"
                )

        sid = str(item["id"])
        if sid in seen_ids:
            raise ScenarioConfigError(f"Duplicate scenario id: {sid!r}")
        seen_ids.add(sid)

        modules = frozenset(item["modules"])
        unknown = modules - KNOWN_MODULES
        if unknown:
            raise ScenarioConfigError(
                f"Scenario {sid!r} references unknown modules: "
                f"{sorted(unknown)}. Add them to config/module_catalog.py "
                f"or fix the scenario."
            )

        missing_required = REQUIRED_PER_SCENARIO - modules
        if missing_required:
            raise ScenarioConfigError(
                f"Scenario {sid!r} must include {sorted(missing_required)} "
                f"(otherwise SchoolAdmin can't complete provisioning)."
            )

        scenarios.append(
            Scenario(
                id=sid,
                school_name=str(item["school_name"]),
                feature_pack_name=str(item["feature_pack_name"]),
                modules=modules,
            )
        )

    return tuple(scenarios)


def coverage_warnings(scenarios: tuple[Scenario, ...]) -> list[str]:
    """Return a list of warnings for modules never enabled / never disabled.

    Not fatal — these are heuristics to encourage good scenario design.
    """
    union: set[str] = set()
    for s in scenarios:
        union |= set(s.modules)

    never_on = sorted(KNOWN_MODULES - union)
    never_off = sorted(
        m for m in KNOWN_MODULES
        if all(m in s.modules for s in scenarios)
    )

    warnings: list[str] = []
    if never_on:
        warnings.append(
            "Modules never enabled by any scenario "
            f"(never positively tested): {never_on}"
        )
    if never_off:
        warnings.append(
            "Modules enabled by every scenario "
            f"(never negatively tested): {never_off}"
        )
    return warnings
