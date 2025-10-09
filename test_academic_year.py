from playwright.async_api import expect


def test_create_academic_year(page):
    """Create an academic year."""
    page.get_by_role("button", name="Academic Year & Term").click()
    page.get_by_role("button", name="Create Academic Year").click()
    page.get_by_role("textbox", name="Name*").click()
    page.get_by_role("textbox", name="Name*").fill("2028/2029")
    page.get_by_role("textbox", name="Start date").click()
    page.get_by_role("button", name="super-next-year").click()
    page.get_by_role("button", name="super-next-year").click()
    page.get_by_role("button", name="super-next-year").click()
    page.get_by_title("-10-18").click()
    page.get_by_role("button", name="super-next-year").click()
    page.get_by_role("button", name="super-next-year").click()
    page.get_by_role("button", name="super-next-year").click()
    page.get_by_title("-10-15").locator("div").click()
    page.get_by_role("combobox").click()
    page.get_by_role("option", name="None").click()
    page.get_by_role("switch", name="Active").click()
    page.get_by_role("button", name="Create", exact=True).click()
    expect(page.locator("body")).to_match_aria_snapshot("- status: Academic year created created")


def test_update_academic_year(page):
    """Update academic year."""
    page.get_by_role("button", name="Academic Year & Term").click()
    page.get_by_role("cell", name="/2020").click()
    page.get_by_role("row", name="2019/2020 Active May 13, 2019").locator("span").click()
    page.get_by_role("cell", name="May 13,").click()
    page.get_by_role("cell", name="Aug 30,").click()
    page.get_by_role("cell", name="Oct 9, 2025, 8:52:32 PM").first.click()
    page.get_by_role("cell", name="Oct 9, 2025, 8:52:32 PM").nth(1).click()
    page.get_by_role("cell", name="/2020").click()
    page.get_by_role("row", name="2019/2020 Active May 13, 2019").get_by_role("button").click()
    page.locator("html").click()
    page.get_by_role("row", name="2019/2020 Active May 13, 2019").get_by_role("button").click()
    page.get_by_role("menuitem", name="Edit").click()
    page.get_by_role("textbox", name="End date").click()
    page.get_by_title("-08-31").click()
    page.get_by_role("button", name="Update").click()
    expect(page.locator("body")).to_match_aria_snapshot("- status: Academic year updated")


def test_deactivate_academic_year(page):
    """Deactivate academic year."""
    page.get_by_role("button", name="Academic Year & Term").click()
    page.get_by_role("row", name="2019/2020 Active May 13, 2019").get_by_role("button").click()
    page.get_by_role("menuitem", name="Deactivate").click()
    expect(page.locator("body")).to_match_aria_snapshot("- status: Academic year deactivated")


def test_delete_academic_year(page):
    """Delete academic year."""
    page.get_by_role("button", name="Academic Year & Term").click()
    page.get_by_role("row", name="2024/2025 Inactive Sep 2,").get_by_role("button").click()
    page.get_by_role("menuitem", name="Delete").click()
    page.get_by_role("button", name="Delete").click()
    expect(page.locator("body")).to_match_aria_snapshot("- status: Academic year deleted")
