

def test_add_school_branch(page):
    """Add a school branch."""
    page.click("text=Add Branch")
    page.fill("input[id='name']", "Test School Branch")
    page.fill("input[id='location']", "Kasoa")
    page.click("text=Save")
    assert page.url == "https://smsfrontend2.vercel.app/module/school_admin_dashboard"
    assert page.get_by_text("Test School Branch")