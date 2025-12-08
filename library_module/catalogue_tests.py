from playwright.sync_api import expect, Page


def test_add_catalogue(page: Page):
    """Add a book."""
    page.get_by_role("button", name="Catalogue").click()
    page.get_by_role("button", name="Add Book").click()
    page.get_by_role("switch").click()
    page.get_by_role("textbox", name="ISBN number").fill("0061964360")
    page.get_by_role("textbox", name="ISBN number").press("ControlOrMeta+a")
    expect(page.get_by_text("Book information loaded")).to_be_visible()
    page.get_by_role("button", name="Add Book").click()
    expect(page.get_by_text("Book added successfully")).to_be_visible()


def test_read_catalogue(page: Page):
    """View book"""
    page.get_by_role("button", name="Catalogue").click()
    page.get_by_role("cell", name="Pride and Prejudice Complete").click()
    page.get_by_role("row", name="Pride and Prejudice Complete").get_by_role("button").click()
    page.get_by_role("link", name="View details").click()
    expect(
        page.get_by_role("heading", name="Pride and Prejudice Complete Text with Extras", exact=True)).to_be_visible()


def test_edit_catalogue(page: Page):
    """Edit book"""
    page.get_by_role("button", name="Catalogue").click()
    page.get_by_role("button", name="Edit Book").click()
    page.get_by_role("textbox", name="Type full names, separated by").fill("Jane Austen and Bernd")
    page.get_by_role("button", name="Update Book").click()
    expect(page.get_by_text("Book updated successfully"))
    expect(page.get_by_text("Jane Austen and Bernd")).to_be_visible()


def test_add_catalogue_copy(page: Page):
    """Add book copy"""
    page.get_by_role("button", name="Catalogue").click()
    page.get_by_role("row", name="Pride and Prejudice Complete").get_by_role("button").click()
    page.get_by_role("button", name="Add More Book Copies").click()
    page.get_by_placeholder("Enter number of copies").fill("10")
    page.get_by_role("textbox", name="e.g., Shelf A1, Room 201, etc.").fill("Room 201")
    page.get_by_role("combobox").click()
    page.get_by_role("option", name="Good").click()
    page.get_by_role("button", name="Add 10 Copies").click()
    expect(page.get_by_text("copies added successfully")).to_be_visible()


def test_remove_catalogue_copy(page: Page):
    """Remove book copy"""
    page.get_by_role("button", name="Catalogue").click()
    page.get_by_role("row", name="Pride and Prejudice Complete").get_by_role("button").click()
    page.get_by_role("button", name="Remove Book Copies").click()
    page.get_by_placeholder("Number of copies").fill("02")
    page.get_by_role("button", name="Remove").click()
    expect(page.get_by_text("Copies removed successfully")).to_be_visible()


def test_delete_catalogue(page: Page):
    """Delete a book"""
    page.get_by_role("button", name="Catalogue").click()
    page.get_by_role("row", name="Pride and Prejudice Complete").get_by_role("button").click()
    page.get_by_role("button", name="Delete Book").click()
    page.get_by_role("button", name="Delete").click()
    expect(page.get_by_text("Book deleted successfully")).to_be_visible()


def test_manage_catalogue(page: Page):
    test_add_catalogue(page)
    test_add_catalogue_copy(page)
    test_remove_catalogue_copy(page)
    test_read_catalogue(page)
    test_edit_catalogue(page)
    test_delete_catalogue(page)


def test_no_access_catalogue(page: Page):
    expect(page.get_by_role("button", name="Catalogue")).not_to_be_visible()
