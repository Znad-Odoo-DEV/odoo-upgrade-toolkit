"""Which of our modules are on this database, and which are only on disk.

    odoo-bin shell --no-http --shell-interface=python < tools/ssc_module_states.py

    SSC_INSTALL=1   install everything that is uninstalled and installable
    SSC_UPGRADE=1   upgrade everything already installed

Reads only unless one of those is set.

The Apps screen filters to applications, and half of what we build is not one -
the bridges have application off on purpose, because a bridge is not something
somebody chooses from a list. So a module can be pushed, built, present on
disk and entirely invisible on that screen, and the first sign of it is a
report saying a field is missing when the module holding it was simply never
switched on.

Three states worth telling apart:

  installed        it is on, and its fields exist
  uninstalled      it is on disk and switched off - one click, or SSC_INSTALL=1
  not on disk      the build has not picked the commit up. Rebuild first;
                   installing is not the problem and will not be the fix.
"""
import os

INSTALL = os.environ.get('SSC_INSTALL') == '1'
UPGRADE = os.environ.get('SSC_UPGRADE') == '1'

Module = env['ir.module.module'].sudo()                          # noqa: F821

# what the repository holds, in the order they depend on each other
EXPECTED = [
    'ssc_payroll',
    'ssc_attendance',
    'ssc_requests',
    'ssc_requests_payroll',
    'ssc_subcontract',
    'ssc_requests_subcontract',
    'ssc_project',
    'ssc_boq',
    'ssc_planning',
    'ssc_progress',
    'ssc_subcontract_boq',
    'ssc_subcontract_order',
    'ssc_progress_planning',
]


def say(line=''):
    print(line)


say("=" * 88)
say("our modules on this database")
say("=" * 88)
say("  %-28s %-14s %-6s %-5s %s"
    % ('module', 'state', 'app', 'auto', 'depends'))

known = {module.name: module for module in Module.search([('name', 'in', EXPECTED)])}
missing_from_disk, uninstalled, installed = [], [], []

for name in EXPECTED:
    module = known.get(name)
    if module is None:
        missing_from_disk.append(name)
        say("  %-28s %-14s" % (name, "NOT ON DISK"))
        continue
    if module.state == 'installed':
        installed.append(module)
    elif module.state in ('uninstalled', 'to install'):
        uninstalled.append(module)
    say("  %-28s %-14s %-6s %-5s %s"
        % (name, module.state,
           'yes' if module.application else '',
           'yes' if module.auto_install else '',
           ", ".join(module.dependencies_id.mapped('name'))[:40]))

say()
say("  %s installed, %s on disk but switched off, %s not on disk at all"
    % (len(installed), len(uninstalled), len(missing_from_disk)))

if missing_from_disk:
    say()
    say("  " + "-" * 84)
    say("  NOT ON DISK - the build has not picked up the commit that adds them:")
    for name in missing_from_disk:
        say("      %s" % name)
    say()
    say("  Installing is not the problem and will not be the fix. Rebuild the")
    say("  branch, then run this again. If Update Apps List has not been run")
    say("  since the build, run that first - a module on disk that Odoo has")
    say("  never listed reads exactly the same as one that is not there.")

if uninstalled and not INSTALL:
    say()
    say("  " + "-" * 84)
    say("  ON DISK, SWITCHED OFF:")
    for module in uninstalled:
        if module.auto_install:
            why = ("a bridge - never on the Apps screen, and it switches "
                   "itself on once both sides are installed")
        elif not module.application:
            why = "not an application - the Apps screen filters it out"
        else:
            why = ""
        say("      %-28s %s" % (module.name, why))
    say()
    say("  Run again with SSC_INSTALL=1 to switch them on.")

if INSTALL and uninstalled:
    say()
    say("  installing %s..." % ", ".join(m.name for m in uninstalled))
    Module.browse([m.id for m in uninstalled]).button_immediate_install()
    env.cr.commit()                                              # noqa: F821
    say("  done. Run this again to see the new states.")
elif UPGRADE and installed:
    say()
    say("  upgrading %s module(s)..." % len(installed))
    Module.browse([m.id for m in installed]).button_immediate_upgrade()
    env.cr.commit()                                              # noqa: F821
    say("  done.")
else:
    env.cr.rollback()                                            # noqa: F821
