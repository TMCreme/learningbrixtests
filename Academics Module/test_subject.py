from playwright.sync_api import expect, Page

def test_add_subject(page: Page):
    """Add a subject."""
    page.get_by_role("button", name="Subjects").click()
    page.get_by_role("button", name="Add Subject").click()
    page.get_by_role("textbox", name="Enter name of subject").fill("Chemistry")
    page.get_by_role("textbox", name="Add additional comments").fill("One of the sciences")
    page.get_by_label("Add Subject").get_by_role("button", name="Add Subject").click()
    expect(page.get_by_text("Subject added successfully")).to_be_visible() # verify this

def test_view_subject(page: Page):
    """View subject."""
    pass

def test_edit_subject(page: Page):
    """Edit subject."""
    pass

def test_delete_subject(page: Page):
    """Delete subject."""
    pass