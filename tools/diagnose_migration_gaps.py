"""The four questions the verification raised, asked of the Studio data itself.

    odoo-bin shell --no-http --shell-interface=python < tools/diagnose_migration_gaps.py

Reads only.

The verification said what is empty. It could not say why, and the difference
between "the import read the wrong column" and "the column was always empty" is
the difference between a bug and a fact about the business. Each of these is
answered by looking at the Studio rows rather than by reasoning about them:

  1. four bills came across with no rates. Are the rates somewhere else on the
     Studio line, or were those bills never priced?

  2. the programme activities got their money and not their dates. What columns
     does that line model actually have, and which of them hold dates?

  3. no bill item says which trade it is. Studio never linked them - but the
     specification names and the item descriptions may be the same words, and
     if they are, the link can be made after the fact.

  4. progress needs a quantity per zone. Which Studio model holds sector by
     work type, and how much of it is there?
"""
import re

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def say(line=''):
    print(line)


def title(text):
    say()
    say("=" * 96)
    say(text)
    say("=" * 96)


def source(name):
    model = env.get(name)                                        # noqa: F821
    if model is None:
        return None
    cr.execute("SELECT to_regclass(%s)", (model._table,))
    return model.sudo() if cr.fetchone()[0] else None


def fields_of(model_name, kinds=None):
    domain = [('model', '=', model_name)]
    if kinds:
        domain.append(('ttype', 'in', list(kinds)))
    return IrField.search(domain, order='name')


def held(model, field):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""",
               (model._table, field.name))
    if not cr.fetchone():
        return None
    cr.execute('SELECT COUNT("%s") FROM "%s"' % (field.name, model._table))
    return cr.fetchone()[0]


def normalise(text):
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


# --- 1. were those bills ever priced -----------------------------------------

title("1. the four bills with no rates - were they ever priced")

Boq = env['ssc.boq'].sudo()                                      # noqa: F821
old_boq = source('x_boq_s')
if old_boq is None:
    say("  x_boq_s is gone from this database.")
else:
    for boq in Boq.search([], order='name'):
        row = old_boq.browse(boq.studio_ref_id).exists()
        if not row:
            say("  %-16s its Studio row is gone" % boq.name)
            continue
        # every numeric column on every line of this bill, summed
        totals = {}
        for field in IrField.search([('model', '=', 'x_boq_s'),
                                     ('ttype', '=', 'one2many')]):
            if not (field.relation or '').startswith('x_boq_s_line'):
                continue
            lines = row[field.name]
            if not lines:
                continue
            for column in fields_of(field.relation, ('float', 'monetary',
                                                     'integer')):
                if column.name in ('id',):
                    continue
                values = [line[column.name] or 0.0 for line in lines]
                if any(values):
                    totals[column.name] = totals.get(column.name, 0.0) \
                        + sum(values)
        say()
        say("  %-16s %-30s   what its Studio lines add up to:"
            % (boq.name, (boq.project_id.display_name or '')[:30]))
        if not totals:
            say("      every numeric column on every line is zero - this bill "
                "was never priced in Studio either")
        for column, value in sorted(totals.items(), key=lambda kv: -abs(kv[1])):
            say("      %-46s %18.2f" % (column, value))


# --- 2. what the programme lines actually hold -------------------------------

title("2. the programme line model - every column, and what fills it")

line_model = source('x_project_time_schedul_line_0ecc8')
if line_model is None:
    say("  x_project_time_schedul_line_0ecc8 is not on this database.")
else:
    total = len(line_model.search([]))
    say("  %s row(s)" % total)
    say()
    say("  %-46s %-12s %8s" % ('column', 'type', 'filled'))
    for field in fields_of('x_project_time_schedul_line_0ecc8'):
        count = held(line_model, field)
        if count is None:
            continue
        say("  %-46s %-12s %8s   %s"
            % (field.name[:46], field.ttype, count,
               field.field_description or ''))
    say()
    say("  a row, in full:")
    for row in line_model.search([], limit=2):
        say()
        for field in fields_of('x_project_time_schedul_line_0ecc8'):
            try:
                value = row[field.name]
            except Exception:
                continue
            if not value or field.ttype in ('one2many', 'many2many', 'binary'):
                continue
            if field.ttype == 'many2one':
                value = value.display_name
            say("      %-42s %s" % (field.name[:42], str(value)[:60]))


# --- 3. can the trades be linked after the fact ------------------------------

title("3. do the bill items and the specifications use the same words")

Work = env['ssc.work.type'].sudo()                               # noqa: F821
Line = env['ssc.boq.line'].sudo()                                # noqa: F821
by_name = {}
for work in Work.search([('studio_ref_id', '!=', 0)]):
    by_name.setdefault(normalise(work.name), work)

lines = Line.search([('display_type', '=', False)])
exact = [line for line in lines if normalise(line.name) in by_name]
say("  %s bill item(s), %s specification(s) carried from Studio"
    % (len(lines), len(by_name)))
say("  %s item(s) have a description that is exactly a specification name"
    % len(exact))
if exact:
    say()
    say("  the first few:")
    for line in exact[:8]:
        say("      %-58s -> %s"
            % ((line.name or '').replace('\n', ' ')[:58],
               by_name[normalise(line.name)].display_name[:60]))
else:
    say()
    say("  None match exactly. The item descriptions and the specification")
    say("  names are different text, so a trade cannot be attached by name")
    say("  and would have to be attached by hand or by the bill it sits in.")

# the fallback: every item in a section can take the section's trade, and the
# section name is a trade name - Block works, Electrical, HVAC, Plumbing
Section = env['ssc.boq.section'].sudo()                          # noqa: F821
seeded = {normalise(work.name): work for work in Work.search([])}
matched_sections = [s for s in Section.search([])
                    if normalise(s.name) in seeded]
say()
say("  %s of %s bill sections are named after a trade that exists"
    % (len(matched_sections), Section.search_count([])))
if matched_sections:
    say("  so the trade can be set on the section and read down onto its items")


# --- 4. where the quantity per zone lives ------------------------------------

title("4. the sectors-and-works rows, which progress needs")

for name in ('x_detailed_quantity_line_f60e2_line_368c6',
             'x_detailed_quantity_line_f60e2',
             'x_sectors_of_work',
             'x_sc_sectors'):
    model = source(name)
    if model is None:
        say("  %-46s not on this database" % name)
        continue
    say()
    say("  %-46s %s row(s)" % (name, len(model.search([]))))
    for field in fields_of(name, ('many2one', 'float', 'monetary', 'integer')):
        count = held(model, field)
        if not count:
            continue
        say("      %-42s %-12s %8s   %s"
            % (field.name[:42], field.ttype, count,
               (field.relation or field.field_description or '')[:30]))


title("what to do with this")
say("""  Section 1 settles whether four empty bills are a bug or a fact. If every
  numeric column on their lines is zero, they were opened and never priced,
  and there is nothing to fix.

  Section 2 names the date columns, if there are any. The money came across
  and the dates did not, so either they are called something the import did
  not look for, or nobody ever dated a programme.

  Section 3 says whether a trade can be attached to seven hundred and
  seventy-six items after the fact. The section names are the better bet:
  Block works, Electrical, HVAC and Plumbing are trades, and an item takes
  its section's trade unless it says otherwise.

  Section 4 is what progress is measured against, and until it is carried
  the application can price and programme a job but not measure one.""")

env.cr.rollback()                                                # noqa: F821
