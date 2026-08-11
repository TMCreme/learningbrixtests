"""Academics → Classes & Timetables page object (/module/classes_and_timetables).

Everything that writes here — the "Add Class" trigger and the per-row action
menu — is rendered only for the "manage" permission on
``classes_and_timetables``, so for read-only roles these methods fail as a
missing-control timeout rather than as a backend rejection.

Two fields of the Add Class dialog are mandatory (the frontend keeps "Save
Class" disabled until Academic Year and Academic Term are set) yet neither is a
parameter of ``create_class``, so the values are chosen here: the active
academic year and that year's first term. The branch's first fee group is
picked too when there is one — the dropdown is filled from ``GET /fees/groups``,
which is a 403 for a school whose feature pack excludes ``fees``, and
``class.fee_group_id`` is nullable, so a class is still creatable without one.

Two flows in the plan's §7 playbook are not on this screen at all:

* **assign_teacher** — the "Add Class Teacher" modal lists teaching staff by
  display name (``first_name other_names``); no email is rendered anywhere in
  it, and the generated test addresses carry no name (``playwright+teacher-…``).
  ``teacher_email`` is therefore matched leniently and a teacher's display name
  is accepted in its place — see ``_pick_teacher``.
* **enroll_student** — this module has no enrollment UI; the class detail page
  only *lists* the students already in a class. The class assignment is written
  by ``PUT /student/{id}`` with ``class_id``, whose only UI is the student edit
  wizard under ``/module/students``, so that is what ``enroll_student`` drives
  before returning the browser here.
"""
from __future__ import annotations

import re

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError, expect

from tests.pages.base import BasePage, goto_module

PAGE_HEADING = re.compile(r"^\s*Manage Classes\s*&\s*Timetable\s*$", re.I)

# ── the read-only surface (page.tsx + ClassList.tsx), usable by any role ──────
CLASS_SEARCH_FIELD = re.compile(r"^\s*Search class by name\s*$", re.I)
RESET_FILTER_BUTTON = re.compile(r"^\s*Reset Filter\s*$", re.I)
ADVANCED_SEARCH_BUTTON = re.compile(r"^\s*Advanced Search\s*$", re.I)
# EmptyState's title/description, rendered inside the table's only row when the
# filtered list comes back empty.
NO_CLASSES_TITLE = re.compile(r"^\s*No classes found\s*$", re.I)
NO_CLASSES_DESCRIPTION = re.compile(r"^\s*Add a class to get started\.\s*$", re.I)
# src/components/common/PageError.tsx, mounted with this exact title whenever
# GET /classes/ fails — the surface every read assertion here must rule out.
LOAD_FAILURE_TITLE = re.compile(r"^\s*Failed to load classes\s*$", re.I)
# "Showing <n> class(es)" — the count strip above the table, rendered only when
# the list is non-empty.
ROW_COUNT_SUMMARY = re.compile(r"Showing\s+(\d+)\s+class(es)?", re.I)
# The Actions column header. Deliberately NOT treated as permission-gated:
# ClassList renders the <TableHead> unconditionally and gates only the cell
# beneath it — see ``expect_read_only``.
ACTIONS_COLUMN = re.compile(r"^\s*Actions\s*$", re.I)

# Cell order of ClassList's table. The sixth column ("Actions") exists only for
# the "manage" permission, so it is deliberately not indexed here — every column
# a read-only role sees comes first.
COLUMN = {
    "name": 0,
    "fee_group": 1,
    "subjects": 2,
    "class_teacher": 3,
    "date_added": 4,
}

# The dialog's title repeats the trigger's label, so one pattern serves both.
ADD_CLASS_TRIGGER = re.compile(r"^\s*Add Class\s*$", re.I)
# The label flips to "Saving..." while GET /fees/groups is still in flight.
SAVE_CLASS_BUTTON = re.compile(r"^\s*Sav(e Class|ing)", re.I)

# This modal's <label> does carry htmlFor, so get_by_label binds; the
# placeholder half is kept for the day the association is dropped.
CLASS_NAME_FIELD = re.compile(r"^\s*Class Name\s*$|^\s*Enter name of class\s*$", re.I)

# The three otherwise-identical comboboxes are told apart by their adjacent
# <Label>, not by their placeholder: all three ids initialise to 0, and a Radix
# Select whose value matches no item renders an EMPTY trigger rather than
# falling back to its placeholder, so "Select academic year" is not on screen
# on a freshly opened dialog.
ACADEMIC_YEAR_LABEL = re.compile(r"^\s*Academic Year\s*$", re.I)
ACADEMIC_TERM_LABEL = re.compile(r"^\s*Academic Term\s*$", re.I)
FEE_GROUP_LABEL = re.compile(r"^\s*Fee Group\s*$", re.I)

# Year options read "<name>  (active)" / "<name>  (inactive)".
ACTIVE_YEAR_OPTION = re.compile(r"\(\s*active\s*\)\s*$", re.I)
# Radix keeps its "nothing to pick" entries in the listbox as disabled options.
UNAVAILABLE_OPTION = re.compile(
    r"^\s*(no\b.*\b(available|found)\b|select academic year first\b|loading\b)", re.I
)

CLASS_CREATED_TOAST = re.compile(r"class successfully added", re.I)

# The row menu's "Edit Class" item and the headlessui dialog it opens. That
# dialog's <label>s carry no htmlFor (unlike the Add Class one, which is built
# from the shared <Label> component), so every field below is reached by its
# placeholder — CLASS_NAME_FIELD already carries that alternation.
EDIT_CLASS_ITEM = re.compile(r"^\s*Edit Class\s*$", re.I)
EDIT_CLASS_TITLE = re.compile(r"^\s*Edit Class\s*$", re.I)
DESCRIPTION_FIELD = re.compile(r"^\s*Add description\s*$", re.I)
# The label flips to "Saving..." while PUT /classes/{id}/ is in flight, and the
# button is disabled until GET /fees/groups has settled one way or the other.
SAVE_CHANGES_BUTTON = re.compile(r"^\s*Sav(e Changes|ing)", re.I)
CLASS_UPDATED_TOAST = re.compile(r"class successfully updated", re.I)

# SubjectMultiSelect (src/components/ui/subject-multiple-select.tsx) is a plain
# <div> with an onClick and a <ul> of <li>s — not a Radix Select — so it has no
# combobox/option roles to anchor on. Its one stable landmark is the hard-coded
# "Subject(s)" label directly above it.
SUBJECT_PICKER_LABEL = re.compile(r"^\s*Subject\(s\)\s*$", re.I)
SUBJECT_SEARCH_FIELD = re.compile(r"^\s*Search subject", re.I)

# The row menu's "View Timetable" item and the page it routes to
# (/module/classes_and_timetables/timetable/{class_id}). WeeklyTimetableView
# titles itself "<class name> Timetable" and badges the range as "Weekly View";
# a class nobody has scheduled yet renders "No Schedule Available" in the grid,
# which is a *loaded* timetable, not a failure.
VIEW_TIMETABLE_ITEM = re.compile(r"^\s*View Timetable\s*$", re.I)
TIMETABLE_URL = re.compile(r"/module/classes_and_timetables/timetable/\d+")
WEEKLY_VIEW_BADGE = re.compile(r"^\s*Weekly View\s*$", re.I)
TIMETABLE_FAILURE_TITLE = re.compile(r"^\s*Failed to load class timetable\s*$", re.I)

ADD_TEACHER_ITEM = re.compile(r"^\s*Add Class Teacher\s*$", re.I)
TEACHER_TRIGGER = re.compile(r"^\s*Select a teacher\s*$", re.I)
ASSIGN_TEACHER_BUTTON = re.compile(r"^\s*Assign Teacher\s*$", re.I)
TEACHER_ASSIGNED_TOAST = re.compile(r"class teacher assigned successfully", re.I)

STUDENTS_ROUTE = "students"
STUDENTS_HEADING = re.compile(r"^\s*Manage Students\s*$", re.I)
STUDENT_SEARCH_FIELD = re.compile(r"^\s*Search student by name\s*$", re.I)
VIEW_STUDENT_LINK = re.compile(r"^\s*View\s*$", re.I)
EDIT_STUDENT_TRIGGER = re.compile(r"^\s*Edit\s*$", re.I)
CONTINUE_BUTTON = re.compile(r"^\s*Continue\s*$", re.I)
# The wizard's step 2; its <label>s carry no htmlFor, hence the placeholder.
CONTACT_STEP_MARKER = re.compile(r"^\s*Enter residential address\s*$", re.I)
# Only the edit wizard renders this — the admission wizard submits "Add Student".
UPDATE_STUDENT_BUTTON = re.compile(r"^\s*Updat(e|ing) Student", re.I)
STUDENT_UPDATED_TOAST = re.compile(r"student updated successfully", re.I)


class ClassesPage(BasePage):
    URL = "/module/classes_and_timetables"

    def open(self) -> "ClassesPage":
        super().open()
        expect(self.page.get_by_role("heading", name=PAGE_HEADING)).to_be_visible(timeout=20_000)
        return self

    # ────────────────────────── classes ───────────────────────────

    def create_class(self, *, name: str, teacher_email: str | None = None) -> None:
        """Create a class, optionally assigning its class teacher afterwards.

        The academic year (the active one) and the term (that year's first) are
        chosen here because the dialog requires both and the caller supplies
        neither — so an active academic year with at least one term must already
        exist for the branch. The fee group is taken when the branch has one and
        skipped when it has none.

        Ends on the classes list with the new row asserted, so ``find_row`` can
        be called straight after.
        """
        trigger = self.page.get_by_role("button", name=ADD_CLASS_TRIGGER).first
        # The list renders a skeleton until GET /classes/ answers, and the
        # trigger is absent entirely without the "manage" permission.
        trigger.wait_for(state="visible", timeout=20_000)
        trigger.click()

        dialog = self.dialog()
        expect(dialog.get_by_role("heading", name=ADD_CLASS_TRIGGER)).to_be_visible(timeout=15_000)

        self.fill_labeled(CLASS_NAME_FIELD, name, in_dialog=True)
        self._select_available(
            ACADEMIC_YEAR_LABEL, field="academic year", prefer=ACTIVE_YEAR_OPTION
        )
        # Both dependent dropdowns stay disabled until their fetch settles, so
        # Playwright's actionability wait doubles as the wait for each list.
        self._select_available(ACADEMIC_TERM_LABEL, field="academic term")
        # A school whose feature pack excludes `fees` is answered 403 by
        # GET /fees/groups, so its branches can never have a fee group. The
        # column is nullable and the dialog leaves the key out when unset, so a
        # class is still creatable — the dropdown simply offers nothing.
        self._select_available(FEE_GROUP_LABEL, field="fee group", required=False)

        save = dialog.get_by_role("button", name=SAVE_CLASS_BUTTON).first
        # Save is disabled until year, term and fee group are all set, so this
        # doubles as the assertion that every dropdown took a value.
        expect(save).to_be_enabled(timeout=20_000)
        save.click()

        self.expect_toast(CLASS_CREATED_TOAST, timeout_ms=30_000)
        expect(self.find_row(name)).to_be_visible(timeout=20_000)

        if teacher_email:
            self.assign_teacher(class_name=name, teacher_email=teacher_email)

    def assign_teacher(self, *, class_name: str, teacher_email: str) -> None:
        """Set ``class_name``'s class teacher.

        The picker lists teaching staff by display name only, so
        ``teacher_email`` may equally be the teacher's full name — whichever
        identifies exactly one option. The teacher must already exist as
        teaching staff for the branch (``GET /teacher/`` feeds the list).
        """
        self._open_row_menu(class_name)
        self.page.get_by_role("menuitem", name=ADD_TEACHER_ITEM).first.click()

        combobox = self.page.get_by_role("combobox").filter(has_text=TEACHER_TRIGGER).first
        combobox.wait_for(state="visible", timeout=20_000)
        combobox.click()
        self._pick_teacher(teacher_email)

        assign = self.page.get_by_role("button", name=ASSIGN_TEACHER_BUTTON).first
        # The button is disabled until a teacher is selected.
        expect(assign).to_be_enabled(timeout=10_000)
        assign.click()

        self.expect_toast(TEACHER_ASSIGNED_TOAST, timeout_ms=20_000)

    def edit_class(
        self,
        *,
        class_name: str,
        new_name: str | None = None,
        description: str | None = None,
        subjects: list[str] | None = None,
    ) -> None:
        """Change an existing class through the row menu's "Edit Class" dialog.

        Only the arguments that are given are touched; everything else keeps the
        value the dialog prefilled from the class. ``subjects`` *replaces* the
        class's subject list, because that is what ``PUT /classes/{id}`` does
        with ``subject_ids``.

        Unlike the Add Class dialog this one is a headlessui ``Dialog`` whose
        ``<label>``s carry no ``htmlFor``, so each field is reached by its
        placeholder (see the EDIT_ constants). Its submit stays disabled until
        ``GET /fees/groups`` has settled — which for a school whose pack excludes
        ``fees`` means until that request has been *refused* — hence the explicit
        enabled-wait rather than an immediate click.

        Ends back on the classes list with the (possibly renamed) row asserted.
        """
        self._open_row_menu(class_name)
        self.page.get_by_role("menuitem", name=EDIT_CLASS_ITEM).first.click()

        # Scoped by its own title: the delete dialog is a sibling of this one in
        # page.tsx and both mount as role="dialog" once a class is selected.
        dialog = self.page.get_by_role("dialog").filter(
            has=self.page.get_by_role("heading", name=EDIT_CLASS_TITLE)
        ).first
        # Open/closed is asserted on the panel heading, NOT on the role=dialog
        # element: this modal is a headlessui <Dialog className="relative z-100">
        # whose children are every one of them `fixed`, so the dialog element
        # itself has an empty bounding box and Playwright calls it hidden however
        # open it is. The heading is what is really painted on screen. (The same
        # trap, on this same modal, is documented in
        # tests/pages/academics/subjects.py::_attach_to_class.)
        title = dialog.get_by_role("heading", name=EDIT_CLASS_TITLE).first
        expect(title).to_be_visible(timeout=15_000)

        if new_name is not None:
            dialog.get_by_placeholder(CLASS_NAME_FIELD).first.fill(new_name)

        if subjects:
            self._pick_subjects(dialog, subjects)

        if description is not None:
            dialog.get_by_placeholder(DESCRIPTION_FIELD).first.fill(description)

        save = dialog.get_by_role("button", name=SAVE_CHANGES_BUTTON).first
        expect(save).to_be_enabled(timeout=20_000)
        save.click()

        self.expect_toast(CLASS_UPDATED_TOAST, timeout_ms=30_000)
        # The Transition unmounts the whole dialog on close, so the heading
        # disappearing is the modal closing — see the note above for why the
        # role=dialog element is not what is asserted on.
        expect(title).to_be_hidden(timeout=15_000)
        expect(self.find_row(new_name or class_name)).to_be_visible(timeout=20_000)

    def open_timetable(self, class_name: str) -> None:
        """Follow the row menu's "View Timetable" through to the weekly grid.

        The grid itself may well be empty — a class nobody has scheduled renders
        "No Schedule Available" — so what is asserted is that the timetable
        *loaded*: its own title, the "Weekly View" badge, and no PageError.
        """
        self._open_row_menu(class_name)
        self.page.get_by_role("menuitem", name=VIEW_TIMETABLE_ITEM).first.click()

        self.page.wait_for_url(TIMETABLE_URL, timeout=20_000)
        expect(
            self.page.get_by_role("heading", name=_exact(f"{class_name} Timetable"))
        ).to_be_visible(timeout=30_000)
        expect(self.page.get_by_text(WEEKLY_VIEW_BADGE).first).to_be_visible()
        expect(self.page.get_by_text(TIMETABLE_FAILURE_TITLE)).to_have_count(0)

    def enroll_student(self, *, class_name: str, student_name: str) -> None:
        """Put an already-admitted student into ``class_name``.

        Runs through the student edit wizard under ``/module/students`` (the
        only UI that writes a class assignment for an existing student), then
        reopens the classes list so the rest of this page object still applies.

        ``student_name`` is the student's displayed name
        (``first_name other_names``); the search box matches it server-side
        against either name part or the concatenation of both.
        """
        goto_module(self.page, self.frontend_base_url, STUDENTS_ROUTE)
        expect(self.page.get_by_role("heading", name=STUDENTS_HEADING)).to_be_visible(
            timeout=20_000
        )

        self.fill_labeled(STUDENT_SEARCH_FIELD, student_name)
        row = self.page.get_by_role("row").filter(
            has=self.page.get_by_text(_exact(student_name))
        ).first
        expect(row).to_be_visible(timeout=20_000)
        # The row's "View" link only renders for an active student.
        row.get_by_role("link", name=VIEW_STUDENT_LINK).first.click()

        self.click_button(EDIT_STUDENT_TRIGGER)
        self._advance_to_admission_step()
        self._select_class_on_admission_step(class_name)

        self.page.get_by_role("button", name=UPDATE_STUDENT_BUTTON).first.click()
        self.expect_toast(STUDENT_UPDATED_TOAST, timeout_ms=30_000)

        self.open()

    # ──────────────────────── reading the list ────────────────────

    def search(self, term: str) -> None:
        """Type into "Search class by name".

        The filter is client-side over the already-fetched list (page.tsx's
        ``filteredClasses``), so no request is made and no wait is needed.
        """
        self.fill_labeled(CLASS_SEARCH_FIELD, term)

    def reset_filters(self) -> None:
        """Press "Reset Filter" — clears the search box and refetches the list."""
        self.click_button(RESET_FILTER_BUTTON)

    def cell(self, class_name: str, column: str) -> Locator:
        """One cell of a class's row, addressed by :data:`COLUMN` key."""
        return self.find_row(class_name).get_by_role("cell").nth(COLUMN[column])

    def expect_no_load_failure(self) -> None:
        """Assert the page is showing the register, not ``PageError``.

        Worth asserting after every read: a refused ``GET /classes/`` replaces
        the whole workspace with the error panel, and a "row is absent" check
        would otherwise pass on it for the wrong reason.
        """
        expect(self.page.get_by_text(LOAD_FAILURE_TITLE)).to_have_count(0)

    def expect_empty(self) -> None:
        """Assert the table is showing its EmptyState rather than any class."""
        expect(self.page.get_by_text(NO_CLASSES_TITLE).first).to_be_visible(timeout=15_000)
        expect(self.page.get_by_text(NO_CLASSES_DESCRIPTION).first).to_be_visible()

    def expect_read_only(self, class_name: str | None = None) -> None:
        """Assert none of the "manage" controls is on the page.

        Two controls are gated on
        ``usePermission("classes_and_timetables", name === "manage")``: the
        "Add Class" trigger on page.tsx, and — in ClassList — the *contents* of
        each row's Actions cell.

        The Actions column **header** is not one of them. ClassList declares
        ``<TableHead>Actions</TableHead>`` unconditionally and switches only the
        cell: ``isManage ? <ClassActions/> : <ViewTimetableAction/>``. So a
        read-only role still sees the column, and inside it a plain "View
        Timetable" button — a read — where the "…" menu that edits, deletes and
        re-staffs the class would otherwise be. Asserting the header away would
        fail on a correct app.

        Passing ``class_name`` makes the check specific: that row must expose
        exactly one control, and it must be the read.
        """
        expect(self.page.get_by_role("button", name=ADD_CLASS_TRIGGER)).to_have_count(0)
        if class_name is None:
            return
        buttons = self.find_row(class_name).get_by_role("button")
        expect(buttons).to_have_count(1)
        expect(buttons.first).to_have_text(VIEW_TIMETABLE_ITEM)

    def find_row(self, name: str) -> Locator:
        """Row in the Classes table.

        The list is fetched whole (``limit=100``) and filtered client-side, so
        no search is needed first. The match is on the name cell's exact text —
        ``has_text`` alone would let "Grade 1" find "Grade 10".
        """
        return self.page.get_by_role("row").filter(has=self.page.get_by_text(_exact(name))).first

    # ───────────────────────── internals ──────────────────────────

    def _open_row_menu(self, class_name: str) -> None:
        row = self.find_row(class_name)
        expect(row).to_be_visible(timeout=20_000)
        # The only button in the row is the actions trigger, and it is rendered
        # for the "manage" permission alone.
        row.get_by_role("button").last.click()

    def _select_available(
        self,
        label: re.Pattern[str],
        *,
        field: str,
        prefer: re.Pattern[str] | None = None,
        required: bool = True,
    ) -> None:
        """Pick an option out of a Radix Select the caller gave no value for.

        The combobox is found through its adjacent ``<Label>`` — which carries
        no htmlFor, so the label's parent ``<div>`` is what scopes the search —
        rather than through its placeholder, which an untouched trigger does not
        render (see the LABEL constants above).

        Takes the first option matching ``prefer``, else the first selectable
        one. Disabled placeholder entries ("No terms available for selected
        year" and friends) are still real options in the listbox, so they are
        skipped by text.
        """
        group = self.dialog().get_by_text(label).first.locator("xpath=..")
        combobox = group.get_by_role("combobox").first
        # The fee-group field renders a loading placeholder in place of the
        # Select until GET /fees/groups answers, so the combobox may not exist
        # yet; and each dependent trigger stays disabled until its own fetch
        # settles, which Playwright's actionability wait absorbs on click.
        combobox.wait_for(state="visible", timeout=20_000)
        combobox.click()

        options = self.page.get_by_role("option")
        usable = _usable_options(options)

        if not usable:
            self.page.keyboard.press("Escape")
            if not required:
                # The dialog does not demand this one, so an empty listbox is a
                # legitimate state — leave it unset and carry on.
                return
            raise AssertionError(
                f"The {field} dropdown of the Add Class dialog offered nothing selectable — "
                f"the branch has no {field} yet, so create one before creating a class."
            )

        index = usable[0][0]
        if prefer is not None:
            preferred = _match_index(usable, prefer)
            if preferred is not None:
                index = preferred

        options.nth(index).click()

    def _pick_subjects(self, dialog: Locator, subjects: list[str]) -> None:
        """Tick each named subject in the dialog's SubjectMultiSelect.

        That control is hand-rolled: a clickable ``<div>`` with a ``<ul>`` of
        ``<li>``s, so there is no combobox/option role and no listbox to filter.
        It is anchored on its hard-coded "Subject(s)" label, whose next sibling
        is the wrapper holding the trigger.

        The panel is toggled shut again afterwards — it is absolutely positioned
        and would otherwise sit over "Save Changes".
        """
        trigger = dialog.get_by_text(SUBJECT_PICKER_LABEL).first.locator(
            "xpath=following-sibling::div[1]/div[1]"
        )
        trigger.click()

        search = dialog.get_by_placeholder(SUBJECT_SEARCH_FIELD).first
        search.wait_for(state="visible", timeout=15_000)

        for subject in subjects:
            # Typing narrows the list client-side, which keeps the click off a
            # near-identically named sibling ("Mathematics" / "Further Maths").
            search.fill(subject)
            option = dialog.get_by_role("listitem").filter(has_text=_exact(subject)).first
            try:
                option.wait_for(state="visible", timeout=15_000)
            except PlaywrightTimeoutError as exc:
                trigger.click()
                raise AssertionError(
                    f"No subject named {subject!r} in the Edit Class subject picker — "
                    "it lists the subjects of the active branch, so the subject must "
                    "exist there first."
                ) from exc
            option.click()

        search.fill("")
        trigger.click()

    def _pick_teacher(self, teacher_email: str) -> None:
        """Choose a teacher from the open "Select a teacher" listbox.

        The options carry display names only, so an address is matched first
        literally (in case one is ever rendered), then against the name-ish
        tokens of its local part — which only bites when the address was derived
        from the teacher's name, never for ``playwright+teacher-…`` ones. A
        branch with a single teaching staff member is unambiguous either way.
        """
        options = self.page.get_by_role("option")
        usable = _usable_options(options)

        identifier = teacher_email.strip()
        index = _match_index(usable, re.compile(re.escape(identifier), re.I))

        if index is None:
            tokens = [
                token
                for token in re.split(r"[^A-Za-z]+", identifier.split("@")[0])
                if len(token) > 2
            ]
            index = next(
                (
                    candidate
                    for candidate, text in usable
                    if tokens
                    and all(re.search(rf"\b{re.escape(t)}\b", text, re.I) for t in tokens)
                ),
                None,
            )

        if index is None and len(usable) == 1:
            index = usable[0][0]

        if index is None:
            self.page.keyboard.press("Escape")
            raise AssertionError(
                f"No teacher matching {identifier!r} in the 'Select a teacher' dropdown. "
                f"It lists teaching staff by display name only — pass that name instead. "
                f"Available: {[text for _, text in usable]!r}"
            )

        options.nth(index).click()

    def _advance_to_admission_step(self) -> None:
        """Walk the student edit wizard to its Admission Information step.

        Both earlier steps keep "Continue" disabled until their starred fields
        are filled — already true for an existing student — and both render the
        same label, so each transition is asserted before the next click.
        """
        self.click_button(CONTINUE_BUTTON)
        expect(self.page.get_by_placeholder(CONTACT_STEP_MARKER).first).to_be_visible(
            timeout=20_000
        )
        self.click_button(CONTINUE_BUTTON)
        expect(self.page.get_by_role("button", name=UPDATE_STUDENT_BUTTON).first).to_be_visible(
            timeout=20_000
        )

    def _select_class_on_admission_step(self, class_name: str) -> None:
        """Pick the class on the wizard's Admission Information step.

        Its trigger cannot be found by placeholder — the student's current class
        is already displayed there — nor by label, since the "Class" label has no
        htmlFor and Radix gives the trigger no id. It is however the step's first
        combobox (the admission date above it is an antd DatePicker textbox).
        """
        combobox = self.page.get_by_role("combobox").first
        combobox.click()

        option = self.page.get_by_role("option", name=_exact(class_name)).first
        try:
            option.wait_for(state="visible", timeout=20_000)
        except PlaywrightTimeoutError as exc:
            self.page.keyboard.press("Escape")
            raise AssertionError(
                f"No class named {class_name!r} in the student wizard's class dropdown — "
                "it lists the classes of the student's own branch, so the class must exist "
                "there first."
            ) from exc

        option.click()


def _match_index(options: list[tuple[int, str]], pattern: re.Pattern[str]) -> int | None:
    return next((index for index, text in options if pattern.search(text)), None)


def _usable_options(options: Locator) -> list[tuple[int, str]]:
    """Index and text of every option of an open listbox worth clicking."""
    options.first.wait_for(state="visible", timeout=20_000)
    texts = [(options.nth(index).inner_text() or "").strip() for index in range(options.count())]
    return [
        (index, text)
        for index, text in enumerate(texts)
        if text and not UNAVAILABLE_OPTION.search(text)
    ]


def _exact(value: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
