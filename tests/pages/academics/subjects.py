"""Academics → Subjects page object (/module/subjects).

The route renders one screen with two tabs ("Subjects" and "Topics"); this page
object only drives the Subjects tab.

Two things the plan's ``create_subject(name, classes, teacher)`` signature
implies are *not* on this screen, because the create payload is only
``{name, description}``:

* **classes** — a subject is attached to a class from the Edit Class modal on
  ``/module/classes_and_timetables`` (its "Subject(s)" multi-select is the only
  UI that writes ``subject_ids``). ``create_subject`` drives that modal itself
  rather than leaving the argument a silent no-op, so a provisioned class really
  does end up carrying the subject.
* **teacher_email** — the (teacher, subject, class) association is written by
  the teaching-staff form's "Assigned Subject(s)" field under ``/module/staff``,
  and its options are derived from the classes already selected on that same
  form. There is no path to it from here, so passing ``teacher_email`` raises
  instead of quietly doing nothing.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, expect

from tests.pages.base import BasePage, goto_module

PAGE_HEADING = re.compile(r"^\s*Manage Subjects\s*&\s*Topics\s*$", re.I)

# The sidebar entry for this module (SideNavigation/nav-config.tsx). The
# "Academics Module" section's ``branchOnly`` flag is a SchoolAdmin-only concept,
# so a teacher is offered the link straight after login.
NAV_SUBJECTS = re.compile(r"^\s*Subject\s*&\s*Topic\s*$", re.I)

SUBJECTS_TAB = re.compile(r"^\s*Subjects\s*$", re.I)
SEARCH_FIELD = re.compile(r"^\s*Search subject by name\s*$", re.I)

# The panel the Subjects tab renders its table in, and the second line of the
# EmptyState it shows instead when the (server-side, scope-filtered) list comes
# back with nothing. Its title is ``EMPTY_TITLE``, below.
SUBJECTS_PANEL = re.compile(r"^\s*All Subjects\s*$", re.I)
EMPTY_DESCRIPTION = re.compile(r"^\s*Try adjusting your search criteria\s*$", re.I)

# The other write affordance on the Subjects tab, beside "Add Subject" and the
# row menu: like them it is gated on ``usePermission("subjects", "manage")``, so
# a read-only role must be offered none of the three.
ASSIGN_SUBJECTS_BUTTON = re.compile(r"^\s*Assign Subjects\s*$", re.I)

# Offered only to a Teacher — page.tsx checks the role name directly rather than
# a permission — and it is the way into /module/subjects/my-subject-summary.
MY_SUBJECT_SUMMARY_BUTTON = re.compile(r"^\s*My Subject Summary\s*$", re.I)

ADD_SUBJECT_TRIGGER = re.compile(r"^\s*Add Subject\s*$", re.I)
ADD_SUBJECT_MODAL = re.compile(r"Add Subject", re.I)
# antd swaps the OK label to "Adding..." while the POST is in flight.
ADD_SUBJECT_SUBMIT = re.compile(r"^\s*Add(ing)?\b", re.I)

# The modal's <label>s carry no htmlFor, so both patterns also spell the
# placeholder that BasePage.fill_labeled falls back to.
NAME_FIELD = re.compile(r"^\s*Subject Name\s*\*?\s*$|^\s*Enter name of subject\s*$", re.I)
DESCRIPTION_FIELD = re.compile(r"^\s*Description\s*\*?\s*$|^\s*Add additional comments\s*$", re.I)

SUBJECT_CREATED_TOAST = re.compile(r"subject added successfully", re.I)

# Row menu (Radix DropdownMenu) — rendered only for a role holding
# ("manage", "subjects"); the trigger carries an icon and no accessible name, so
# it is reached as the row's last button.
EDIT_SUBJECT_ITEM = re.compile(r"^\s*Edit subject\s*$", re.I)
DELETE_SUBJECT_ITEM = re.compile(r"^\s*Delete subject\s*$", re.I)

EDIT_SUBJECT_MODAL = re.compile(r"Edit Subject", re.I)
# antd swaps the OK label to "Saving..." while the PUT is in flight.
EDIT_SUBJECT_SUBMIT = re.compile(r"^\s*Sav(e Changes|ing)", re.I)
SUBJECT_EDITED_TOAST = re.compile(r"subject edited successfully", re.I)

DELETE_SUBJECT_MODAL = re.compile(r"Delete Subject", re.I)
DELETE_SUBJECT_CONFIRM = re.compile(r"^\s*(Yes, Delete|Deleting)", re.I)
SUBJECT_DELETED_TOAST = re.compile(r"subject deleted successfully", re.I)

# EmptyState / PageError, both mounted by page.tsx with these exact strings.
EMPTY_TITLE = re.compile(r"^\s*No subjects found\s*$", re.I)
LOAD_FAILURE_TITLE = re.compile(r"^\s*Failed to load subjects data\s*$", re.I)

# The Subjects table's columns, in render order (page.tsx <TableHeader>). The
# fourth is the actions cell and carries no data.
SUBJECT_COLUMNS = {"name": 0, "date_added": 1, "description": 2}

CLASSES_ROUTE = "classes_and_timetables"
EDIT_CLASS_ITEM = re.compile(r"^\s*Edit Class\s*$", re.I)
EDIT_CLASS_MODAL = re.compile(r"Edit Class", re.I)
CLASS_SUBJECT_SEARCH_FIELD = re.compile(r"^\s*Search subject\.\.\.\s*$", re.I)
SAVE_CHANGES_BUTTON = re.compile(r"^\s*Sav(e Changes|ing)", re.I)
CLASS_UPDATED_TOAST = re.compile(r"class successfully updated", re.I)

# The subject multi-select is a bare <div onClick> with no role and no
# htmlFor on its "Subject(s)" label, so its trigger is reached structurally
# from that label — the only stable text anchor the widget offers.
SUBJECT_PICKER = (
    "xpath=.//label[normalize-space()='Subject(s)']/following-sibling::div[1]/div[1]"
)


class SubjectsPage(BasePage):
    URL = "/module/subjects"

    def open(self) -> "SubjectsPage":
        super().open()
        self.expect_loaded()
        return self

    def open_from_nav(self) -> "SubjectsPage":
        """Reach the screen the way a user does — the sidebar entry.

        A demo video has to show how someone gets to the module, not teleport
        there, so this is what the recorded tests navigate with; ``open`` stays
        the deep link for everything else.
        """
        self.page.get_by_role("link", name=NAV_SUBJECTS).first.click()
        self.expect_loaded()
        return self

    def expect_loaded(self) -> None:
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        # The heading also renders in the pre-hydration skeleton; the search box
        # only appears once the module/permission guards have let the page through.
        expect(self.page.get_by_placeholder(SEARCH_FIELD).first).to_be_visible(timeout=20_000)

    # ────────────────────────── subjects ───────────────────────────

    def create_subject(
        self,
        *,
        name: str,
        classes: list[str],
        teacher_email: str | None = None,
        description: str | None = None,
    ) -> None:
        """Create a subject and attach it to every class in ``classes``.

        The description is required by the form (the OK button stays disabled
        without it) but not by the caller, so one is derived from ``name`` when
        none is given.

        Each class in ``classes`` must already exist — the Edit Class modal's
        "Subject(s)" picker lists the branch's classes, not creates them. Ends
        back on ``/module/subjects`` with ``name`` searched for, so ``find_row``
        can be called straight after.
        """
        if teacher_email:
            raise NotImplementedError(
                "SubjectsPage cannot assign a teacher: /module/subjects has no teacher "
                "field (the create payload is name + description only). The "
                "(teacher, subject, class) association is written from the teaching-staff "
                "form's 'Assigned Subject(s)' field under /module/staff, whose options come "
                "from the classes selected on that same form — so assign the subject to the "
                "class first, then set it on the teacher there."
            )

        self.show_subjects()
        self.click_button(ADD_SUBJECT_TRIGGER)

        modal = self._modal(ADD_SUBJECT_MODAL)
        expect(modal).to_be_visible(timeout=10_000)
        self._fill_in(modal, NAME_FIELD, name)
        self._fill_in(
            modal, DESCRIPTION_FIELD, description or f"{name} (integration test suite)"
        )

        submit = modal.get_by_role("button", name=ADD_SUBJECT_SUBMIT).first
        # antd keeps OK disabled until both fields are non-empty, so this
        # doubles as the assertion that the form took each value.
        expect(submit).to_be_enabled(timeout=10_000)
        submit.click()

        self.expect_toast(SUBJECT_CREATED_TOAST, timeout_ms=20_000)
        expect(modal).to_be_hidden(timeout=10_000)

        self.search(name)
        expect(self.find_row(name)).to_be_visible(timeout=20_000)

        for class_name in classes:
            self._attach_to_class(subject_name=name, class_name=class_name)

        if classes:
            self.open()
            self.search(name)

    def find_row(self, name: str) -> Locator:
        """Row in the Subjects table.

        The list is server-paginated at 10 rows and filtered server-side by the
        "Search subject by name" box, so a subject outside the current page will
        not be matched by this locator alone — call ``search`` first.
        """
        return self.page.get_by_role("row").filter(has=self.page.get_by_text(_exact(name))).first

    def search(self, query: str) -> None:
        """Type into the search box. Debounced 500ms, then refetched server-side."""
        self.page.get_by_placeholder(SEARCH_FIELD).first.fill(query)

    def show_subjects(self) -> None:
        """Select the Subjects tab.

        Every write on this page object starts here: the route opens on Subjects
        but the two tabs share one screen, and a caller that has been reading
        Topics would otherwise drive the wrong table.
        """
        self.click_button(SUBJECTS_TAB)

    def edit_subject(
        self,
        *,
        name: str,
        new_name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Rename a subject and/or rewrite its description from the row menu.

        Both fields are required by the form — antd keeps "Save Changes"
        disabled while either is empty — but the modal opens pre-filled from the
        row, so a caller may change just one of them.
        """
        self.show_subjects()
        self._open_row_menu(name)
        self.page.get_by_role("menuitem", name=EDIT_SUBJECT_ITEM).first.click()

        modal = self._modal(EDIT_SUBJECT_MODAL)
        expect(modal).to_be_visible(timeout=10_000)
        if new_name is not None:
            self._fill_in(modal, NAME_FIELD, new_name)
        if description is not None:
            self._fill_in(modal, DESCRIPTION_FIELD, description)

        submit = modal.get_by_role("button", name=EDIT_SUBJECT_SUBMIT).first
        expect(submit).to_be_enabled(timeout=10_000)
        submit.click()

        self.expect_toast(SUBJECT_EDITED_TOAST, timeout_ms=20_000)
        expect(modal).to_be_hidden(timeout=10_000)

    def delete_subject(self, *, name: str) -> None:
        """Delete a subject from the row menu, confirming the modal.

        The confirmation names the subject it is about to remove, so that is
        asserted before confirming — the dialog is driven from ``selectedSubject``
        state that a mis-aimed row menu would have left pointing elsewhere.
        Ends with the row gone from the register.
        """
        self.show_subjects()
        self._open_row_menu(name)
        self.page.get_by_role("menuitem", name=DELETE_SUBJECT_ITEM).first.click()

        modal = self._modal(DELETE_SUBJECT_MODAL)
        expect(modal).to_be_visible(timeout=10_000)
        expect(modal.get_by_text(_exact(name)).first).to_be_visible(timeout=10_000)

        modal.get_by_role("button", name=DELETE_SUBJECT_CONFIRM).first.click()

        self.expect_toast(SUBJECT_DELETED_TOAST, timeout_ms=20_000)
        expect(modal).to_be_hidden(timeout=10_000)
        expect(self.find_row(name)).to_have_count(0)

    def cell(self, name: str, column: str) -> Locator:
        """One cell of a subject's row, by column key (``SUBJECT_COLUMNS``)."""
        return self.find_row(name).get_by_role("cell").nth(SUBJECT_COLUMNS[column])

    def expect_no_load_failure(self) -> None:
        """Fail loudly when the screen is showing PageError instead of the table.

        Without this a "no row for X" assertion passes just as happily on a
        workspace whose GET /subjects/ was refused (a SchoolAdmin with no branch
        selected gets a 400) as on one that genuinely holds no such subject.
        """
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)

    # ────────────────────────── internals ──────────────────────────

    def _modal(self, title: re.Pattern[str]) -> Locator:
        """Scope to one antd Modal — all of them stay mounted once opened."""
        return self.page.get_by_role("dialog").filter(has_text=title).first

    def _fill_in(self, modal: Locator, field: re.Pattern[str], value: str) -> None:
        """Fill a field inside one specific modal.

        Deliberately not ``BasePage.fill_labeled(..., in_dialog=True)``: that
        scopes to ``get_by_role("dialog")`` — *every* mounted dialog — and antd
        leaves each modal in the DOM once it has been opened. On this screen the
        Add, Edit and Delete modals all carry the same "Enter name of subject"
        placeholder, and Add is first in DOM order, so ``.first`` resolves to the
        hidden Add modal as soon as the Edit modal is being driven.

        The labels here carry no ``htmlFor``, so ``get_by_label`` never binds and
        the placeholder alternation in each field pattern is what actually
        matches.
        """
        loc = modal.get_by_label(field).first
        if loc.count() == 0:
            loc = modal.get_by_placeholder(field).first
        loc.fill(value)

    def _open_row_menu(self, name: str) -> None:
        """Open the per-row actions menu for ``name``.

        The trigger is a bare ``<button>`` wrapping a lucide ``MoreVertical``
        icon — no accessible name at all — and it is the only button in the row,
        so it is reached positionally.
        """
        row = self.find_row(name)
        expect(row).to_be_visible(timeout=20_000)
        row.get_by_role("button").last.click()

    def _attach_to_class(self, *, subject_name: str, class_name: str) -> None:
        """Add ``subject_name`` to ``class_name``'s curriculum via Edit Class."""
        goto_module(self.page, self.frontend_base_url, CLASSES_ROUTE)

        row = self.page.get_by_role("row").filter(
            has=self.page.get_by_text(_exact(class_name))
        ).first
        expect(row).to_be_visible(timeout=20_000)
        row.get_by_role("button").last.click()
        self.page.get_by_role("menuitem", name=EDIT_CLASS_ITEM).first.click()

        modal = self.page.get_by_role("dialog").filter(has_text=EDIT_CLASS_MODAL).first
        # Unlike the antd modals on this screen, Edit Class is a headlessui
        # <Dialog className="relative z-100"> whose children are all `fixed`, so
        # the role=dialog element itself has an empty bounding box and Playwright
        # calls it hidden however open it is. Its panel heading is what is
        # actually on screen, so that is what open/closed is asserted on.
        title = modal.get_by_role("heading", name=EDIT_CLASS_MODAL).first
        expect(title).to_be_visible(timeout=10_000)

        save = modal.get_by_role("button", name=SAVE_CHANGES_BUTTON).first
        # Save stays disabled until GET /fees/groups has answered, which is
        # after the modal has mirrored the class into its form — so waiting on
        # Save is also the wait for the class's existing subjects to be
        # selected.
        expect(save).to_be_enabled(timeout=20_000)

        picker = modal.locator(SUBJECT_PICKER).first
        if picker.get_by_text(_exact(subject_name)).count() == 0:
            picker.click()
            modal.get_by_placeholder(CLASS_SUBJECT_SEARCH_FIELD).first.fill(subject_name)
            option = modal.get_by_role("listitem").filter(
                has_text=_exact(subject_name)
            ).first
            expect(option).to_be_visible(timeout=15_000)
            option.click()
            # Clicking an option toggles it, so the dropdown stays open over the
            # rest of the form; close it before reaching for Save.
            picker.click()
            expect(picker.get_by_text(_exact(subject_name)).first).to_be_visible(timeout=10_000)

        save.click()
        self.expect_toast(CLASS_UPDATED_TOAST, timeout_ms=20_000)
        expect(title).to_be_hidden(timeout=10_000)


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
