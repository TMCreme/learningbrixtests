from playwright.sync_api import expect


def test_add_school_branch_admin(page):
    """Add a school branch."""
    page.click("text=New School Admin")
    page.fill("input[id='admin_name']", "Test School Admin")
    page.fill("input[id='admin_email']", "abc@gmail.com")
    page.click("text=Add Admin")
    expect(page.get_by_text("Successfully created an admin")).to_be_visible()
