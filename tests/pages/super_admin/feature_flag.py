"""SuperAdmin → Feature Flag Management page object."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import ClassVar, Literal

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage

TabName = Literal["Packs", "Schools", "Modules"]


class FeatureFlagPage(BasePage):
    URL = "/module/feature_flag"
    CREATE_URL: ClassVar[str] = "/module/feature_flag/create"

    # Tab buttons render "<icon><label><count>", so the count is part of the
    # accessible name — match on the label only.
    TABS: ClassVar[dict[str, re.Pattern[str]]] = {
        "Packs": re.compile(r"Feature Packs", re.I),
        "Schools": re.compile(r"School Assignment", re.I),
        "Modules": re.compile(r"System Modules", re.I),
    }

    def open(self) -> "FeatureFlagPage":
        super().open()
        expect(self.page.get_by_role("heading", name=re.compile(r"Feature Flag Management", re.I))
               ).to_be_visible(timeout=15_000)
        return self

    # ─────────────────────────── tabs ────────────────────────────

    def switch_tab(self, name: TabName) -> None:
        try:
            pattern = self.TABS[name]
        except KeyError:
            raise ValueError(f"Unknown tab {name!r}; expected one of {sorted(self.TABS)}") from None
        self.page.get_by_role("button", name=pattern).first.click()

    # ─────────────────────────── packs ───────────────────────────

    def create_pack(self, *, name: str, description: str = "", modules: Iterable[str]) -> None:
        self.switch_tab("Packs")
        self.click_button(re.compile(r"^\s*Create Pack\s*$", re.I))
        expect(self.page.get_by_role("heading", name=re.compile(r"^\s*Create Feature Pack\s*$", re.I))
               ).to_be_visible(timeout=15_000)

        self.fill_labeled(re.compile(r"Pack Name|e\.g\. Standard Plan", re.I), name)
        if description:
            self.fill_labeled(
                re.compile(r"^Description$|Brief description of what this pack includes", re.I),
                description,
            )

        # "Clear All" resets to only the locked basic modules, so every
        # subsequent click toggles a module ON rather than flipping its state.
        self.click_button(re.compile(r"^\s*Clear All\s*$", re.I))
        for module in modules:
            self._check_module(module)

        self.click_button(re.compile(r"^\s*Save and Exit\s*$", re.I))
        self.expect_toast(r"Feature pack created successfully")
        self.page.wait_for_url(re.compile(r"/module/feature_flag/?$"), timeout=15_000)

    def delete_pack(self, name: str) -> None:
        self.switch_tab("Packs")
        row = self.pack_row(name)
        expect(row).to_be_visible(timeout=15_000)
        # The row's only button is the unlabeled "⋮" dropdown trigger.
        row.get_by_role("button").last.click()
        self.page.get_by_role("menuitem", name=re.compile(r"^\s*Delete Pack\s*$", re.I)).click()
        self.page.get_by_role("button", name=re.compile(r"^\s*Delete Pack\s*$", re.I)).click()
        self.expect_toast(r"Feature pack deleted")

    def pack_row(self, name: str) -> Locator:
        return self.page.get_by_role("row").filter(has_text=re.compile(re.escape(name), re.I)).first

    # ────────────────────── school assignment ────────────────────

    def assign_pack_to_school(self, *, school_name: str, pack_name: str) -> None:
        self.switch_tab("Schools")
        row = self.school_row(school_name)
        expect(row).to_be_visible(timeout=15_000)
        # "Assign" becomes "Change" once a pack is already attached; anchor the
        # pattern so it never matches the neighbouring "Unassign" button.
        row.get_by_role("button", name=re.compile(r"^\s*(Assign|Change)\s*$", re.I)).click()

        dialog = self.dialog()
        expect(dialog.get_by_text(re.compile(r"Assign Feature Pack", re.I))).to_be_visible(timeout=10_000)
        # The radio input is sr-only; clicking its wrapping <label> selects it.
        # has_text runs against raw text content, and the sibling badges ("Custom",
        # "3 modules") abut the name with no separator — so anchor the start only.
        dialog.locator("label").filter(
            has_text=re.compile(rf"^\s*{re.escape(pack_name)}", re.I)
        ).first.click()
        dialog.get_by_role("button", name=re.compile(r"^\s*Assign Pack\s*$", re.I)).click()
        self.expect_toast(r"Feature pack assigned successfully")

    def school_row(self, school_name: str) -> Locator:
        return self.page.get_by_role("row").filter(
            has_text=re.compile(re.escape(school_name), re.I)
        ).first

    # ────────────────────────── internals ────────────────────────

    def _check_module(self, module: str) -> None:
        """Tick one module on the create form.

        Module rows are <label>s with no <input>, so the click has to land on
        the styled checkbox div; the label itself is inert. Locked "basic"
        modules (People/Governance) ignore the click, which keeps this idempotent.

        The "Required"/"Optional" badge is a sibling <span> rendered with no
        whitespace between it and the module name, so the label's text content
        reads "academic year and termRequired" — the badge must be allowed to
        follow the name directly.
        """
        display = re.escape(module.replace("_", " "))
        row = self.page.locator("label").filter(
            has_text=re.compile(rf"^\s*{display}\s*(Required|Optional)?\s*$", re.I)
        ).first
        expect(row).to_be_visible(timeout=10_000)
        row.locator("xpath=./div[1]").click()
