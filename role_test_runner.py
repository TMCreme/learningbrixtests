from permission_registry import PERMISSION_TESTS, NO_ACCESS_TESTS
from permission_utils import (
    extract_all_permissions,
    group_permissions_by_module,
    get_role_permissions,
)

def run_tests_for_role(page, role, all_permissions):
    role_perms = get_role_permissions(role)
    modules = group_permissions_by_module(all_permissions)

    print(f"\n==============================")
    print(f"TESTING ROLE: {role['name']}")
    print("==============================")

    for module, perms in modules.items():

        read_perm = f"read_{module}"
        manage_perm = f"manage_{module}"

        has_read = read_perm in role_perms
        has_manage = manage_perm in role_perms

        # No test module registered then skip
        if module not in NO_ACCESS_TESTS:
            continue

        if has_manage:
            print(f"{role['name']} MANAGE → {module}")
            PERMISSION_TESTS[manage_perm](page)

        elif has_read:
            print(f"{role['name']} READ → {module}")
            PERMISSION_TESTS[read_perm](page)

        else:
            print(f"✘ {role['name']} NO ACCESS → {module}")
            NO_ACCESS_TESTS[module](page)
