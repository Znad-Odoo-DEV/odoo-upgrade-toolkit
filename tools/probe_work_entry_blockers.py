"""Why generate_work_entries returns having created nothing.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_work_entry_blockers.py

Fifty four payslips rebuilt with force=True and not one day count moved,
including the three that hold no work entry at all for August. force was the
right suspect for the marker check and it is not the whole story.

_generate_work_entries walks each version and skips it before force is ever
considered:

    version_start = tz.localize(version.date_start)...
    version_stop  = tz.localize(version.date_end or date_stop)...
    if date_start > version_stop or date_stop < version_start:
        continue

Those are the VERSION's own dates, not the contract's. A version that starts
after the pay period covers none of it and generates nothing, whatever force
says. date_version on some Royal Arrow versions is 2026-08-26 - a day after
this run ends - so the shape fits, and that is exactly why it needs checking
rather than believing.

WHAT IT PRINTS, PER EMPLOYEE

  every hr.version they have, with date_version, date_start, date_end, the
  contract dates, active, and whether the payslip points at it; the work
  entries that exist in the period; the working schedule, since a version with
  no resource_calendar_id generates nothing either; and then it calls
  _generate_work_entries inside a savepoint and reports how many records came
  back, which is the only answer that settles it.

Read-only: the generation is rolled back.
"""
import os
from datetime import datetime

WIDTH = 112
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
NAMES = [n.strip().lower() for n in (os.environ.get('SSC_EMPLOYEE') or
         'Parfait Uwanshuti,Kamlesh Ramkaran,Ahmad Ali Sameu,Shakir Valiyil'
         ).split(',') if n.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


Employee = env['hr.employee'].sudo()
Version = env['hr.version'].sudo()
Payslip = env['hr.payslip'].sudo()
WorkEntry = env['hr.work.entry'].sudo()

for wanted in NAMES:
    employees = Employee.search([]).filtered(
        lambda e: wanted in (e.name or '').lower())
    if not employees:
        print("no employee matching %r" % wanted)
        continue
    employee = employees[0]
    slips = Payslip.search([('employee_id', '=', employee.id)]).filtered(
        lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
        and str(s.date_from.year) == str(YEAR))
    slip = slips[0] if slips else None

    title("%s   -   %s" % (employee.name or '?', employee.company_id.name or '-'))
    if slip:
        print("  payslip [%s]  %s .. %s  state=%s  version [%s]"
              % (slip.id, slip.date_from, slip.date_to, slip.state,
                 slip.version_id.id if 'version_id' in slip._fields else '?'))
    else:
        print("  no %s-%s payslip" % (MONTH, YEAR))
        continue

    print("")
    print("  every version this employee has:")
    print("      %-6s %-12s %-12s %-12s %-12s %-12s %-7s %s"
          % ("id", "date_version", "date_start", "date_end",
             "contract from", "contract to", "active", "on the payslip"))
    for version in Version.search([('employee_id', '=', employee.id)],
                                  order='date_version'):
        print("      %-6s %-12s %-12s %-12s %-12s %-12s %-7s %s"
              % (version.id, version.date_version,
                 version.date_start if 'date_start' in version._fields else '-',
                 version.date_end if 'date_end' in version._fields else '-',
                 version.contract_date_start or '-',
                 version.contract_date_end or '-', version.active,
                 "yes" if version.id == slip.version_id.id else ""))

    version = slip.version_id
    print("")
    print("  the payslip's version in detail:")
    print("      resource_calendar_id   %s"
          % (version.resource_calendar_id.name
             if version.resource_calendar_id else "NONE - generates nothing"))
    for field in ('date_generated_from', 'date_generated_to',
                  'last_generation_date', 'work_entry_source', 'schedule_pay'):
        if field in version._fields:
            print("      %-22s %s" % (field, version[field]))

    entries = WorkEntry.search([('employee_id', '=', employee.id),
                                ('date', '>=', str(slip.date_from)),
                                ('date', '<=', str(slip.date_to))])
    print("")
    print("  %s work entry(ies) in the period" % len(entries))
    by_type = {}
    for entry in entries:
        key = (entry.work_entry_type_id.name or '?', entry.state)
        by_type[key] = by_type.get(key, 0) + 1
    for (name, state), count in sorted(by_type.items()):
        print("      %-40s %-12s %s" % (name[:40], state, count))

    # The only answer that settles it: call it and count what comes back.
    print("")
    print("  calling _generate_work_entries(force=True) inside a savepoint:")
    try:
        with env.cr.savepoint():
            start = datetime.combine(slip.date_from, datetime.min.time())
            stop = datetime.combine(slip.date_to, datetime.max.time())
            created = version._generate_work_entries(start, stop, force=True)
            print("      it created %s entry(ies)" % len(created))
            for entry in created[:6]:
                print("          %s  %s  %s"
                      % (entry.date, entry.work_entry_type_id.name or '?',
                         entry.duration if 'duration' in entry._fields else ''))
            raise RuntimeError('discard')
    except RuntimeError as error:
        if str(error) != 'discard':
            raise
    except Exception as error:  # noqa: BLE001
        print("      it raised %s: %s"
              % (type(error).__name__, str(error).strip().splitlines()[0]))

env.cr.rollback()
title("read only - the transaction was rolled back")
