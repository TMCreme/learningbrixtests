from playwright.sync_api import expect, Page

def test_add_category(page: Page):
    """Add book category"""
    page.get_by_role("button", name="Book Categories").click()
    page.get_by_role("button", name="Add Category").click()
    page.get_by_role("textbox", name="Category").fill("Lost and Found")
    page.get_by_role("textbox", name="Description").click()
    page.get_by_role("textbox", name="Description").fill("N/A")
    page.get_by_role("button", name="Save Data").click()
    expect(page.locator("div").filter(has_text="Category added successfully").nth(2)).to_be_visible()


def test_view_category(page: Page):
    """View book category"""
    page.get_by_role("button", name="Book Categories").click()
    expect(page.get_by_role("cell", name="Lost and found")).to_be_visible()

def test_edit_category(page: Page):
    """Edit book category"""
    page.get_by_role("button", name="Book Categories").click()
    page.get_by_role("row", name="Lost and found October 29,").get_by_role("button").click() # edit date part to be dynamic
    page.get_by_role("button", name="Edit category").click()
    page.get_by_role("textbox", name="Description").click()
    page.get_by_role("textbox", name="Description").fill("N/A and more")
    page.get_by_role("button", name="Save Data").click()
    expect(page.get_by_text("Category updated successfully")).to_be_visible()


def test_delete_category(page: Page):
    """Delete book category"""
    page.get_by_role("button", name="Book Categories").click()
    page.get_by_role("row", name="Lost and found October 29,").get_by_role("button").click()
    page.get_by_role("button", name="Delete category").click()
    page.get_by_role("button", name="Delete").click()
    expect(page.get_by_text("Category deleted successfully")).to_be_visible()
