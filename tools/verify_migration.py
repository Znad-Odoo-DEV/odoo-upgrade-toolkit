"""What the migration actually produced, and what is still empty.

    odoo-bin shell --no-http --shell-interface=python < tools/verify_migration.py

Reads only.

An import that reports "776 items written" has said nothing about whether the
bill is usable. A bill of 776 items where every rate is nought is a written
import and a worthless one. So this counts what came across, and then asks the
questions somebody would ask before trusting it:

  does every bill have a value, or did the rates arrive as zero
  do the items say which trade they are, or did the classification stay behind
  do the packages hold any items, or are they names with nothing in them
  do the programme activities have dates and money, or only names
  has any of it been split by zone, which is what progress is measured against

Each of those is a way the import can be complete and useless at the same time,
and the only honest way to find out is to count.
"""
from collections import Counter

Boq = env['ssc.boq'].sudo()                                      # noqa: F821
Section = env['ssc.boq.section'].sudo()                          # noqa: F821
Line = env['ssc.boq.line'].sudo()                                # noqa: F821
Split = env['ssc.boq.line.zone'].sudo()                          # noqa: F821
Package = env['ssc.boq.package'].sudo()                          # noqa: F821
Zone = env['ssc.project.zone'].sudo()                            # noqa: F821
Work = env['ssc.work.type'].sudo()                               # noqa: F821
Programme = env['ssc.programme'].sudo()                          # noqa: F821
Activity = env['ssc.programme.activity'].sudo()                  # noqa: F821
Project = env['project.project'].sudo()                          # noqa: F821

gaps = []


def say(line=''):
    print(line)


def title(text):
    say()
    say("=" * 92)
    say(text)
    say("=" * 92)


def gap(what):
    gaps.append(what)


title("what came across")

carried = Line.search([('studio_ref_id', '!=', 0)])
say("  %-38s %6s   %s of them from Studio"
    % ('work types', Work.search_count([]),
       Work.search_count([('studio_ref_id', '!=', 0)])))
say("  %-38s %6s   %s of them from Studio"
    % ('zones', Zone.search_count([]),
       Zone.search_count([('studio_ref_id', '!=', 0)])))
say("  %-38s %6s" % ('bills of quantities', Boq.search_count([])))
say("  %-38s %6s" % ('bill sections', Section.search_count([])))
say("  %-38s %6s   %s of them from Studio"
    % ('bill items', Line.search_count([]), len(carried)))
say("  %-38s %6s" % ('work packages', Package.search_count([])))
say("  %-38s %6s" % ('programmes', Programme.search_count([])))
say("  %-38s %6s" % ('programme activities', Activity.search_count([])))
say("  %-38s %6s" % ('quantities split by zone', Split.search_count([])))


title("is the money there")

for boq in Boq.search([]):
    priced = boq.line_ids.filtered(lambda line: line.unit_price)
    say("  %-34s %-22s %5s items %5s priced  %14.2f"
        % (boq.name, (boq.project_id.display_name or '')[:22],
           len(boq.line_ids), len(priced), boq.amount_total))
say()
unpriced = Line.search_count([('unit_price', '=', 0),
                              ('display_type', '=', False)])
say("  %s item(s) have no rate at all" % unpriced)
if unpriced:
    gap("%s bill items came across with no rate. Check one against the Studio "
        "row before trusting any total." % unpriced)

no_quantity = Line.search_count([('quantity', '=', 0),
                                 ('display_type', '=', False)])
say("  %s item(s) have no quantity" % no_quantity)

total = sum(Boq.search([]).mapped('amount_total'))
say("  %.2f is what the six bills come to together" % total)
if Boq.search_count([]) and not total:
    gap("Every bill totals nothing. The rate column was read from the wrong "
        "field.")


title("do the items know what they are")

untyped = Line.search_count([('work_type_id', '=', False)])
say("  %s of %s bill items have no work type"
    % (untyped, Line.search_count([])))
say("  %s of %s sections have no work type"
    % (Section.search_count([('work_type_id', '=', False)]),
       Section.search_count([])))
if untyped:
    gap("%s bill items carry no work type, so nothing can be grouped by trade "
        "and a package cannot be built by discipline. The hundred and five "
        "specifications came across as work types, but no bill line was "
        "pointed at one - Studio never linked them either." % untyped)


title("do the packages hold anything")

empty = Package.search([('line_ids', '=', False)])
say("  %s of %s packages hold no items"
    % (len(empty), Package.search_count([])))
worth = sum(Package.search([]).mapped('amount_total'))
say("  %.2f is what all the packages come to" % worth)
if empty:
    gap("%s of %s packages hold no bill items and are therefore worth nothing. "
        "x_boq_scope had no link to a bill line - it was a name and a project "
        "and nothing else - so there was nothing to carry. Until items are put "
        "in them, a programme activity built from a package is worth nought "
        "too." % (len(empty), Package.search_count([])))


title("can the programme be used")

for programme in Programme.search([]):
    dated = programme.activity_ids.filtered(
        lambda a: a.date_start and a.date_finish)
    say("  %-30s %-24s %4s activities %4s dated  %12.2f"
        % (programme.name, (programme.project_id.display_name or '')[:24],
           len(programme.activity_ids), len(dated), programme.amount_planned))
undated = Activity.search_count(['|', ('date_start', '=', False),
                                 ('date_finish', '=', False)])
say()
say("  %s of %s activities have no dates"
    % (undated, Activity.search_count([])))
say("  %s of %s activities have no package"
    % (Activity.search_count([('package_id', '=', False)]),
       Activity.search_count([])))
if undated == Activity.search_count([]) and undated:
    gap("No activity has dates, so no programme can be baselined and nothing "
        "can be measured against one. Either the Studio line model held no "
        "dates or they are in a column the import did not recognise.")


title("what state is it all in")

by_state = Counter(Boq.search([]).mapped('state'))
say("  bills        %s" % dict(by_state))
if Boq.search_count([]) and not Boq.search_count([('state', '=', 'approved')]):
    gap("No bill is approved, so no project has a live bill, and every figure "
        "that reads through project.ssc_boq_id is nought until one is. "
        "Approving is a decision, not a migration step.")

say("  programmes   %s" % dict(Counter(Programme.search([]).mapped('state'))))
say("  projects marked as construction   %s"
    % Project.search_count([('ssc_is_construction', '=', True)]))

if Line.search_count([]) and not Split.search_count([]):
    gap("Nothing has been split by zone. That split is what turns a "
        "measurement on a floor into money, so progress cannot be recorded "
        "against any of this yet. It lives in the Studio sectors-and-works "
        "rows, which this import did not touch.")


title("what is still missing")
if not gaps:
    say("  Nothing. Every figure the application needs is populated.")
for number, what in enumerate(gaps, start=1):
    say()
    say("  %s. %s" % (number, what))

say()
say("  %s thing(s) between this import and a usable application." % len(gaps))

env.cr.rollback()                                                # noqa: F821
