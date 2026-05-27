from academics_module.subjects_tests import *
from people_module.students_tests import *
from people_module.staff_tests import *
from people_module.guardians_tests import *
from account_module.fees_tests import *
from account_module.incomes_and_expenses_tests import *
from payroll_module.payslips_tests import *
from payroll_module.payroll_tests import *
from library_module.categories_tests import *
from library_module.catalogue_tests import *
from library_module.statistics_tests import *
from library_module.request_and_renewals_tests import *
from academics_module.classes_tests import *
from academics_module.exams_tests import *
from academics_module.attendance_tests import *
from admin_module.employee_benefit_tests import *
from admin_module.access_roles_tests import *
from admin_module.school_configuration_tests import *


# -----------------------------
#  FULL PERMISSION TEST REGISTRY
# -----------------------------
PERMISSION_TESTS = {
    "read_subjects": test_read_subjects,
    "manage_subjects": test_manage_subject,

    "read_students": test_read_students,
    "manage_students": test_manage_students,

    "read_staff": test_read_staff,
    "manage_staff": test_manage_staff,

    "read_guardians": test_read_guardians,
    "manage_guardians": test_manage_guardians,

    "read_fees": test_read_fees,
    "manage_fees": test_manage_fees,

    "read_incomes_and_expenses": test_read_incomes_and_expenses,
    "manage_incomes_and_expenses": test_manage_incomes_and_expenses,

    "read_payslips": test_read_payslips,
    "manage_payslips": test_manage_payslips,

    "read_staff_payroll": test_read_payroll,
    "manage_staff_payroll": test_manage_payroll,

    "read_categories": test_read_categories,
    "manage_categories": test_manage_categories,

    "read_catalogue": test_read_catalogue,
    "manage_catalogue": test_manage_catalogue,

    "read_statistics": test_read_statistics,
    "manage_statistics": test_manage_statistics,

    "read_requests_and_renewals": test_read_requests,
    "manage_requests_and_renewals": test_manage_requests,

    "read_classes_and_timetables": test_read_classes,
    "manage_classes_and_timetables": test_manage_classes,

    "read_exams": test_read_exams,
    "manage_exams": test_manage_exams,

    "read_attendance": test_read_attendance,
    "manage_attendance": test_manage_attendance,

    "read_employee_benefit": test_read_employee_benefit,
    "manage_employee_benefit": test_manage_employee_benefit,

    "read_access_roles": test_read_access_roles,
    "manage_access_roles": test_manage_access_roles,

    "read_school_configuration": test_read_school_configuration,
    "manage_school_configuration": test_manage_school_configuration,
}

# MODULE → NO ACCESS TEST
NO_ACCESS_TESTS = {
    "subjects": test_no_access_subjects,
    "students": test_no_access_students,
    "staff": test_no_access_staff,
    "guardians": test_no_access_guardians,
    "fees": test_no_access_fees,
    "incomes_and_expenses": test_no_access_incomes_and_expenses,
    "payslips": test_no_access_payslips,
    "staff_payroll": test_no_access_payroll,
    "categories": test_no_access_categories,
    "catalogue": test_no_access_catalogue,
    "statistics": test_no_access_statistics,
    "requests_and_renewals": test_no_access_requests,
    "classes_and_timetables": test_no_access_classes,
    "exams": test_no_access_exams,
    "attendance": test_no_access_attendance,
    "employee_benefit": test_no_access_employee_benefit,
    "access_roles": test_no_access_access_roles,
    "school_configuration": test_no_access_school_configuration,
}
