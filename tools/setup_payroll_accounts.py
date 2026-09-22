"""Fill in which account each payroll leg posts to, per company.

    odoo-bin shell -d <database> --no-http < tools/setup_payroll_accounts.py

Dry run by default. Prefix the command with APPLY=1 to write:

    APPLY=1 odoo-bin shell -d <database> --no-http < tools/setup_payroll_accounts.py

An environment variable rather than a line to edit, because the
Odoo.sh worktree is read only: there is nowhere to change a flag.

The map comes from reading each company's own chart, not from a rule: no two
of these charts agree on a number, and the same number is a different account
in two of them - 400007 is Overtime Allowance in SAUD and Leave Salary in MALAK
and ROYAL WOODEN. That is exactly the trap the Studio rule fell into, so every
entry here names the account code AND the name it must have. A code whose
account is called something else is refused rather than written: a wrong
account is found by an auditor, and this is the moment to not create one.

Nothing is overwritten. A leg somebody has already configured stays as it is.
"""
import os
import logging

APPLY = os.environ.get('APPLY') == '1'

_logger = logging.getLogger(__name__)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

# company name -> {expense code: (account code, the name that account must have)}
#
# Decisions taken with the accountant, 2026-09-02:
#   - the net is credited to the salary payable, not to Accounts Payable. The
#     Studio bill credited 201002 because it was a bill to the WPS agent, which
#     is why 203003 has been idle and payroll sat among the real suppliers.
#   - ROYAL ARROW posts on its 400003-400019 direct-cost layer, matching SSC's
#     numbering, rather than the parallel 41xxxxx one Studio used.
#   - a fine deducted from an employee is a recovery, not an expense, so
#     penalties and salary deductions share Salary Deduction.
MAP = {
    'SAUD SHEHATHA CONSTRUCTION L.L.C': {
        'basic': ('400003', 'Basic Salary'),
        'housing': ('400004', 'Housing Allowance'),
        'transport': ('400005', 'Transportation Allowance'),
        'other': ('400006', 'Other Allowances'),
        'overtime': ('400007', 'Overtime Allowance'),
        'salary_payable': ('203003', 'Salary Payable'),
        'leave_allowance': ('400012', 'Leave Salary'),
        'advance': ('103003', 'Advance Salary'),
        'staff_loan': ('103003', 'Advance Salary'),
        'salary_addition': ('400011', 'Salary Additions'),
        'adjustment': ('400011', 'Salary Additions'),
        'phone_bill': ('400010', 'Phone Bill Reimbursement'),
        'bonus': ('400013', 'Salary Bonus'),
        'sick_leave': ('400014', 'Sick Leave Reimbursement'),
        'medical_bill': ('400015', 'Medical Bill Reimbursement'),
        'air_ticket': ('400016', 'Air Ticket Reimbursement'),
        'gratuity': ('400017', 'End of Service & Gratuity'),
        'salary_deduction': ('400020', 'Salary Deduction'),
        'penalty': ('400020', 'Salary Deduction'),
    },
    'ROYAL ARROW ELECTROMECHANICAL CONT.': {
        'basic': ('400003', 'Basic Salary'),
        'housing': ('400004', 'Housing Allowance'),
        'transport': ('400005', 'Transportation Allowance'),
        'other': ('400006', 'Other Allowances'),
        'overtime': ('400007', 'Overtime Allowance'),
        'salary_payable': ('2101001', 'Salary Payable'),
        'leave_allowance': ('400012', 'Leave Salary'),
        'advance': ('1201002', 'Advance to Employees'),
        'staff_loan': ('1201002', 'Advance to Employees'),
        'salary_addition': ('400011', 'Salary Additions'),
        'adjustment': ('400011', 'Salary Additions'),
        'phone_bill': ('400010', 'Phone Bill Reimbursement'),
        'bonus': ('400013', 'Salary Bonus'),
        'sick_leave': ('400014', 'Sick Leave Reimbursement'),
        'medical_bill': ('400015', 'Medical Bill Reimbursement'),
        'air_ticket': ('400016', 'Air Ticket Reimbursement'),
        'gratuity': ('400017', 'End of Service & Gratuity'),
        # This chart has no 400020. 4101009 is the only Salary Deduction it
        # carries, so the deduction legs cross to the other layer here.
        'salary_deduction': ('4101009', 'Salary Deduction'),
        'penalty': ('4101009', 'Salary Deduction'),
    },
    # MALAK and ROYAL WOODEN carry the staff chart only. They have no account
    # for a bonus, a sick leave, a medical bill, a penalty, a salary deduction,
    # a salary addition or an employee advance - so those legs are left empty
    # here rather than pointed at something that nearly fits. A batch carrying
    # one of them will refuse to post and name the leg, which is the right
    # moment to open the chart and add the account.
    'MALAK AL REEM Properties Development.': {
        'basic': ('400003', 'Basic Salary'),
        'housing': ('400004', 'Housing Allowance'),
        'transport': ('400005', 'Transportation Allowance'),
        'other': ('400012', 'Staff Other Allowances'),
        'overtime': ('400072', 'Over Time Allowance'),
        'salary_payable': ('201004', 'Accrued - Salaries'),
        'leave_allowance': ('400007', 'Leave Salary'),
        'air_ticket': ('400024', 'Air tickets'),
        'gratuity': ('400008', 'End Of Service Indemnity'),
        'phone_bill': ('400020', 'Telephone'),
    },
    'ROYAL WOODEN DOORS AND WINDOWS L.L.C': {
        'basic': ('400003', 'Basic Salary'),
        'housing': ('400004', 'Housing Allowance'),
        'transport': ('400005', 'Transportation Allowance'),
        'other': ('400012', 'Staff Other Allowances'),
        'overtime': ('400072', 'Over Time Allowance'),
        'salary_payable': ('201004', 'Accrued - Salaries'),
        'leave_allowance': ('400007', 'Leave Salary'),
        'air_ticket': ('400024', 'Air tickets'),
        'gratuity': ('400008', 'End Of Service Indemnity'),
        'phone_bill': ('400020', 'Telephone'),
    },
}

# The general journal each company's salary entry is posted in.
JOURNAL_CODE = 'SLR'

Company = env['res.company']
Account = env['account.account']
Journal = env['account.journal']
ExpenseType = env['ssc.expense.type']
Line = env['ssc.expense.type.account']

written = skipped = 0
refused = []
gaps = []

for company_name, legs in MAP.items():
    company = Company.search([('name', '=', company_name)], limit=1)
    if not company:
        refused.append("no company named %r" % company_name)
        continue
    print()
    print("=" * 96)
    print(company.display_name)
    print("=" * 96)

    journal = Journal.with_company(company).search(
        [('code', '=', JOURNAL_CODE), ('company_id', '=', company.id)], limit=1)
    if not journal:
        refused.append("%s has no %s journal" % (company_name, JOURNAL_CODE))
    elif company.ssc_salary_journal_id:
        print("  journal        already set: %s" % company.ssc_salary_journal_id.code)
    else:
        print("  journal        -> %s %r" % (journal.code, journal.name))
        if APPLY:
            company.ssc_salary_journal_id = journal

    for code in sorted(legs):
        account_code, expected_name = legs[code]
        expense_type = ExpenseType._for_code(code)
        if not expense_type:
            refused.append("%s: no expense type with code %r" % (company_name, code))
            continue
        if expense_type._line_for(company):
            existing = expense_type._line_for(company).account_id
            print("  %-17s already set: %s %s"
                  % (code, existing.code or '-', existing.name))
            skipped += 1
            continue
        account = Account.with_company(company).search(
            [('code', '=', account_code), ('company_ids', 'in', company.id)], limit=1)
        if not account:
            refused.append("%s: no account %s in this chart (%s)"
                           % (company_name, account_code, code))
            continue
        # The whole point: a code alone is not an identity here.
        if (account.name or '').strip().lower() != expected_name.strip().lower():
            refused.append(
                "%s: %s is %r, expected %r - REFUSED for %s"
                % (company_name, account_code, account.name, expected_name, code))
            continue
        print("  %-17s -> %s %s" % (code, account_code, account.name))
        if APPLY:
            Line.create({
                'expense_type_id': expense_type.id,
                'company_id': company.id,
                'account_id': account.id,
            })
        written += 1

    for expense_type in ExpenseType.search([]):
        if expense_type.code not in legs and not expense_type._line_for(company):
            gaps.append("%s: %s" % (company_name, expense_type.code))

print()
print("=" * 96)
print("%s line(s) %s, %s already set."
      % (written, "written" if APPLY else "to write", skipped))
if refused:
    print()
    print("REFUSED - nothing written for these:")
    for item in refused:
        print("   ", item)
if gaps:
    print()
    print("Legs with no account in that company's chart. A batch carrying one")
    print("will refuse to post and name it, rather than post it somewhere near:")
    for item in gaps:
        print("   ", item)

if APPLY:
    env.cr.commit()
    print("\nCommitted.")
else:
    env.cr.rollback()
    print("\nDRY RUN - nothing was written. Re-run with APPLY=1 to apply.")
