from playwright.sync_api import expect


def test_add_school_branch_admin(page):
    """Add a school branch."""
    page.click("text=Create Admin")
    page.fill("input[placeholder='First Name *']", "Laverne")
    page.fill("input[type='email']", "abc@gmail.com")
    page.fill("input[placeholder='Residential Address']", "123 Avenue")
    page.fill("input[placeholder='Primary Phone *']", "0208915108")
    page.fill("input[placeholder='Religion']", "Christianity")
    page.fill("input[placeholder='Password *']", "pass123@S")
    page.fill("input[placeholder='Confirm Password *']", "pass123@S")

    page.click("button[role='combobox']")
    page.click("text=Married")
    expect(page.locator("button[role='combobox'] > span")).to_have_text("Married")

    page.click("button[role='combobox']")
    page.click("text=Male")
    expect(page.locator("button[role='combobox'] > span")).to_have_text("Male")
    page.pause()
    page.click("text=Create Admin")
    assert page.url == "https://smsfrontend2.vercel.app/module/school_admin_dashboard"
    assert page.get_by_text("Main2")