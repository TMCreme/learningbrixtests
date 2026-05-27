

def extract_all_permissions(roles):
    for role in roles:
        if role["name"] == "Admin":
            return {p["module_name"] for p in role["permissions"]}
    raise RuntimeError("Admin role missing")


def group_permissions_by_module(all_permissions):
    modules = {}
    for perm in all_permissions:
        action, module = perm.split("_", 1)
        modules.setdefault(module, []).append(perm)
    return modules


def get_role_permissions(role):
    return {p["module_name"] for p in role["permissions"]}
