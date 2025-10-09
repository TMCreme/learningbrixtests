import re

from playwright.sync_api import expect


def test_add_access_role(page):
    page.get_by_role("button", name="Add Access Role").click()
    page.get_by_role("textbox", name="Enter role name").click()
    page.get_by_role("textbox", name="Enter role name").fill("New Role")
    page.locator(
        "div:nth-child(5) > .space-y-4 > div:nth-child(4) > .flex.items-center.gap-4 > label:nth-child(2) > .px-3").click()
    page.get_by_role("button", name="Save and Exit").click()
    expect(page.locator("body")).to_match_aria_snapshot("- status: Role successfully created")

def test_preview_access_role(page):
    page.locator("div").filter(has_text=re.compile(r"^Page 1 of 2$")).get_by_role("button").nth(1).click()
    page.get_by_role("cell", name="New Role 2").click()
    page.get_by_role("row", name="New Role 2 October 9, 2025 at").get_by_role("button").click()
    page.get_by_role("link", name="Preview Role").click()
    page.get_by_role("textbox", name="Enter role name").click()
    page.locator("div").filter(has_text=re.compile(r"^Access role$")).click()

def test_edit_access_role(page):
    page.locator("div").filter(has_text=re.compile(r"^Page 1 of 2$")).get_by_role("button").nth(1).click()
    page.get_by_role("row", name="New Role October 9, 2025 at").get_by_role("button").click()
    page.get_by_role("link", name="Edit role").click()
    page.locator("div:nth-child(2) > .flex.items-center.gap-4 > label:nth-child(2) > .px-3").first.click()
    page.locator(
        "div:nth-child(4) > .space-y-4 > div:nth-child(2) > .flex.items-center.gap-4 > label:nth-child(2) > .px-3").click()
    page.locator(
        "div:nth-child(5) > .space-y-4 > div:nth-child(2) > .flex.items-center.gap-4 > label:nth-child(3) > .px-3").click()
    page.get_by_role("button", name="Save Changes").click()
    expect(page.locator("body")).to_match_aria_snapshot("- status: Role updated successfully")



def test_delete_access_role(page):
    page.locator("div").filter(has_text=re.compile(r"^Page 1 of 2$")).get_by_role("button").nth(1).click()
    page.get_by_role("row", name="New Role October 9, 2025 at").get_by_role("button").click()
    page.get_by_role("menuitem", name="Delete role").click()
    page.get_by_role("button", name="Delete Role").click()
    page.get_by_text("Role successfully deleted").click()
    expect(page.locator("body")).to_match_aria_snapshot("- status: Role successfully deleted")
