import json
import pytest
from role_test_runner import run_tests_for_role
from permission_utils import extract_all_permissions


# Load roles JSON
with open("module_permissions.json") as f:
    ROLES = json.load(f)


# Run each role through the dynamic permission system
@pytest.mark.parametrize("role", ROLES)
def test_permissions_for_role(page, login_as, role):
    # Login automatically per role
    login_as(role["name"])

    # Admin establishes full permission list
    all_permissions = extract_all_permissions(ROLES)

    # Execute dynamic tests
    run_tests_for_role(page, role, all_permissions)
