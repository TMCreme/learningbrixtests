from playwright.sync_api import expect


def test_audit_trails(page):
    """Verifying and validating the audit trail."""
    page.get_by_role("button", name="Audit Trails").click()
    page.get_by_text("Create", exact=True).click()
    page.get_by_role("button", name="Close").click()
    expect(page.get_by_text("{ \"id\": 1384, \"book_id\": 68"))