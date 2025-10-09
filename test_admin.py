from playwright.sync_api import expect


def test_add_school_branch_admin(page):
    """Add a school branch."""
    page.click("text=Create Admin")
    page.get_by_role("combobox").filter(has_text="Select a branch").click()
    page.get_by_role("option", name="Test branch 2 - Ashaiman").click()
    page.fill("input[placeholder='First Name *']", "Laverne")
    page.fill("input[type='email']", "abcd@gmail.com")
    page.fill("input[placeholder='Residential Address']", "123 Avenue")
    page.fill("input[placeholder='Primary Phone *']", "0208915108")
    page.fill("input[placeholder='Religion']", "Christianity")
    page.fill("input[placeholder='Password *']", "pass123@S")
    page.fill("input[placeholder='Confirm Password *']", "pass123@S")

    page.get_by_role("combobox").filter(has_text="Select marital status").click()
    page.get_by_role("option", name="Single").click()

    page.get_by_role("combobox").filter(has_text="Select gender").click()
    page.get_by_role("option", name="Male", exact=True).click()

    page.get_by_role("button", name="Create Admin").click()
    expect(page.get_by_text("Successfully created an admin")).to_be_visible()
