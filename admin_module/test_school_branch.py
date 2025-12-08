from playwright.sync_api import expect


def test_add_school_branch(page):
    """Add a school branch."""
    page.click("text=Add Branch")
    page.fill("input[id='name']", "Test School Branch")
    page.fill("input[id='location']", "Kasoa")
    page.click("text=Save")
    expect(page.get_by_text("Successfully created a branch")).to_be_visible()

def test_view_school_branch(page):
    page.get_by_role("button", name="View").nth(3).click()
    expect(page.locator("span").filter(has_text="Test School branch")).to_be_visible()


def test_delete_school_branch(page):
    page.get_by_role("button", name="Delete").nth(4).click()
    page.get_by_role("button", name="Yes, Delete").click()
    expect(page.get_by_text("Successfully deleted a branch")).to_be_visible()
