
def test_add_school_branch_admin(page):
    """Add a school branch."""
    page.click("text=New School Admin")
    page.fill("input[id='admin_name']", "Test School Admin")
    page.fill("input[id='admin_email']", "abc@gmail.com")
    page.click("text=Add Admin")
    assert page.url == "https://smsfrontend2.vercel.app/module/school_admin_dashboard"
    assert page.get_by_text("Main2")