"""Move the project, zone, trade, bill, package and programme data across.

    SSC_WRITE=1        actually write; without it nothing is created
    SSC_STEPS=zones,boq   run only some steps (default: all, in order)
    SSC_OUT=~/migration.md

Dry by default, and the dry run is the point: it says what it found, what it
matched, and what it cannot place, so the shape of the import is agreed before
a single row is written.

Every record it makes carries studio_ref_id, so running it twice updates rather
than duplicates, and so a figure in the new system can always be traced back to
the row it came from.

The steps, in the order they have to happen:

  trades     x_type_of_work        -> ssc.work.type      matched by name against
                                     what ssc_project seeded, and only what does
                                     not match is created
  zones      x_sectorss            -> ssc.project.zone
  boq        x_boq_s + its line    -> ssc.boq / .section / .line
             models                  ONE SECTION PER ONE2MANY FIELD: the field's
                                     label on x_boq_s is the bill's name, which
                                     is where those twenty-nine models kept the
                                     only thing that differed between them
  packages   x_boq_scope           -> ssc.boq.package
  programme  x_project_time_schedul-> ssc.programme / .activity
  splits     the sectors-and-works  -> ssc.boq.line.zone   how much of an
             rows                      item is in which zone, which is the
                                       only thing progress can be measured
                                       against

The bill step discovers the line models rather than listing them, because a
list written today is a list that is wrong the first time somebody adds a
thirtieth trade in Studio. It reads the one2many fields off x_boq_s, and on
each line model it finds the description, quantity and rate columns by looking
at what they are called and what they hold - and it prints what it decided, so
a wrong guess is caught in the dry run rather than in the totals.
"""
import os
import re

WRITE = os.environ.get('SSC_WRITE') == '1'
STEPS = [s.strip() for s in (os.environ.get('SSC_STEPS')
                             or 'trades,zones,boq,packages,programme,splits').split(',')
         if s.strip()]
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/migration.md')

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821

# The far side has to exist before anything can be carried to it. Without this
# the first step dies on a KeyError from the registry, which says the model is
# missing but not that the application was never installed.
NEEDED = ('ssc.work.type', 'ssc.project.zone', 'ssc.boq', 'ssc.boq.section',
          'ssc.boq.line', 'ssc.boq.package', 'ssc.programme',
          'ssc.programme.activity')
absent = [name for name in NEEDED if env.get(name) is None]      # noqa: F821
if absent:
    raise SystemExit("\n".join([
        "The application is not installed on this database.",
        "Missing: %s" % ", ".join(absent),
        "",
        "Install it from Apps, or from a shell:",
        "    module = env['ir.module.module'].search(",
        "        [('name', '=', 'ssc_progress_planning')])",
        "    module.button_immediate_install()",
        "    env.cr.commit()",
    ]))

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


def source(name):
    """The Studio model, or None if this database has already lost it."""
    model = env.get(name)                                        # noqa: F821
    if model is None:
        return None
    cr.execute("SELECT to_regclass(%s)", (model._table,))
    return model.sudo() if cr.fetchone()[0] else None


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""",
               (table, column))
    return bool(cr.fetchone())


def field_names(model_name):
    return set(IrField.search([('model', '=', model_name)]).mapped('name'))


def pick(names, wanted, avoid=()):
    """The first field whose name contains one of the words we want.

    Studio names columns after whatever the person typed into the label, so
    x_studio_unit_price_aedunit and x_studio_rate are the same column on two
    different models. Guessing is unavoidable; printing the guess is not.
    """
    for word in wanted:
        for name in sorted(names):
            if word in name and not any(bad in name for bad in avoid):
                return name
    return None


def normalise(text):
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


made, updated, skipped = {}, {}, {}


def note(step, kind):
    box = {'made': made, 'updated': updated, 'skipped': skipped}[kind]
    box[step] = box.get(step, 0) + 1


def upsert(step, model_name, ref, values, also=()):
    """Create or update by studio_ref_id, so the import can be run again.

    `also` adds to the key. It has to exist because a studio_ref_id is only
    unique within ONE Studio model, and the bill lines come from twenty-nine of
    them, each with its own id sequence. Row five of Block works and row five
    of Electrical are both five. Keyed on the number alone, the second one
    found overwrote the first: seven hundred and seventy-six lines went in as
    two hundred and sixty, each one written over five hundred and twenty-two
    times, and the only sign of it was an import saying it had updated things
    on a database where it had never run.
    """
    Model = env[model_name].sudo()                               # noqa: F821
    existing = Model.search([('studio_ref_id', '=', ref)] + list(also), limit=1)
    if not WRITE:
        note(step, 'updated' if existing else 'made')
        return existing or Model.browse()
    if existing:
        existing.write(values)
        note(step, 'updated')
        return existing
    record = Model.create(dict(values, studio_ref_id=ref))
    note(step, 'made')
    return record


# =============================================================== the trades ===

work_by_studio = {}

# x_type_of_work is not a list of trades. It is a catalogue of specification
# items - "200mm Thermal Blocks for External Walls", "Ceramic Tiles for Rooms
# and Dry areas, PC RATE: 25Dhs/m2" - and none of the hundred and five matched
# a trade by name, because none of them is one. Each belongs UNDER a trade, and
# the words in the description are what say which.
#
# Order matters: the first phrase found wins, so the specific ones come first.
# Ceilings Paint is painting, not ceilings; epoxy flooring is flooring, but
# epoxy paint is paint.
TRADE_WORDS = [
    ('work_fin_flooring', ('epoxy floor', 'epoxy fl', 'special floor')),
    ('work_fin_paint', ('paint', 'multi-coated spray')),
    ('work_sub_excavation', ('excavation', 'backfill', 'road base',
                             'polythene', 'bitumen', 'pcc', 'shoring',
                             'soil')),
    ('work_sub_waterproofing', ('waterproof', 'water proof', 'damp proof',
                                'water stopper', 'protection board',
                                'roof combo', 'membrane')),
    ('work_arc_block', ('block work', 'blocks', 'block')),
    ('work_arc_plaster', ('plaster', 'render')),
    ('work_arc_glazing', ('aluminum', 'aluminium', 'alum', 'glass', 'glazz',
                          'glazing', 'window', 'curtain wall', 'acp',
                          'louver', 'shower enclosure', 'facade',
                          'façade')),
    ('work_arc_doors', ('wooden door', 'door')),
    ('work_arc_metal', ('railing', 'handrail', 'balustrade', 'metal',
                        'stainless steel', 'cooker hood')),
    ('work_arc_kitchen', ('kitchen sink', 'kitchen cabinet', 'joinery')),
    ('work_fin_ceramic', ('ceramic', 'porcelain')),
    ('work_fin_marble', ('granite', 'marble')),
    ('work_fin_ceiling', ('gypsum', 'false ceiling', 'ceiling', 'bulkhead')),
    ('work_fin_wall', ('cladding', 'stone', 'decorative panel')),
    ('work_mec_lpg', ('lpg',)),
    ('work_mechanical', ('hvac', 'air condition', 'ducting')),
    ('work_plm_drainage', ('upvc', 'drainage', 'plumbing', 'sanitary')),
    ('work_electrical', ('electrical', 'lighting', 'cable')),
    ('work_fire', ('civil defense', 'fire', 'sprinkler')),
]


def trade_for(name, misc):
    """The seeded trade whose words appear in this specification's name."""
    text = normalise(name)
    for xmlid, words in TRADE_WORDS:
        if any(word in text for word in words):
            return env.ref('ssc_project.%s' % xmlid)             # noqa: F821
    return misc


def step_trades():
    title("trades   x_type_of_work -> ssc.work.type")
    old = source('x_type_of_work')
    if old is None:
        say("  x_type_of_work is not on this database. Nothing to do.")
        return
    WorkType = env['ssc.work.type'].sudo()                       # noqa: F821
    seeded = {normalise(w.name): w for w in WorkType.search([])}
    fallback = env.ref('ssc_project.work_misc')                  # noqa: F821

    rows = old.search([])
    say("  %s row(s) in Studio, %s work types already in the new tree"
        % (len(rows), len(seeded)))
    say()
    say("  %-46s %s" % ('Studio name', 'matched to'))

    matched = filed = homeless = 0
    for row in rows:
        name = row.display_name or ''
        hit = seeded.get(normalise(name))
        if hit:
            matched += 1
            work_by_studio[row.id] = hit
            if WRITE and not hit.studio_ref_id:
                hit.studio_ref_id = row.id
            say("  %-46s is %s" % (name[:46], hit.display_name))
            continue
        parent = trade_for(name, fallback)
        if parent == fallback:
            homeless += 1
        else:
            filed += 1
        new = upsert('trades', 'ssc.work.type', row.id, {
            'name': name[:120],
            'parent_id': parent.id,
        })
        work_by_studio[row.id] = new or parent
        say("  %-46s under %s" % (name[:46], parent.name))
    say()
    say("  %s were already a trade by name" % matched)
    say("  %s filed under the trade their description names" % filed)
    say("  %s could not be placed and went under %s"
        % (homeless, fallback.name))
    if homeless:
        say()
        say("  Read those %s. A specification the words do not place is one to"
            % homeless)
        say("  file by hand, or a word to add to TRADE_WORDS in this tool.")


# ================================================================ the zones ===

zone_by_studio = {}


def step_zones():
    title("zones   x_sectorss -> ssc.project.zone")
    old = source('x_sectorss')
    if old is None:
        say("  x_sectorss is not on this database. Nothing to do.")
        return
    names = field_names('x_sectorss')
    project_field = pick(names, ('project',))
    say("  project is read from   %s" % (project_field or "NOTHING - "
        "there is no project on a sector, so every zone would be homeless"))
    if not project_field:
        say("  Stopping this step: a zone without a project cannot be created.")
        return

    rows = old.search([])
    say("  %s sector(s)" % len(rows))
    placed = homeless = 0
    for row in rows:
        project = row[project_field]
        if not project:
            homeless += 1
            note('zones', 'skipped')
            continue
        if WRITE and not project.ssc_is_construction:
            project.ssc_is_construction = True
        zone = upsert('zones', 'ssc.project.zone', row.id, {
            'name': (row.display_name or '')[:120],
            'project_id': project.id,
            'kind': 'area',
        })
        zone_by_studio[row.id] = zone
        placed += 1
    say("  %s placed on a project, %s with no project at all" % (placed, homeless))


# ================================================================== the bill ===

def bill_sections(old_boq):
    """The one2many fields of x_boq_s, which are its bills.

    Twenty-nine models holding identical columns, told apart only by the label
    of the field that points at them. That label is the bill name, and it is
    the single piece of information those models carried.
    """
    found = []
    for field in IrField.search([('model', '=', 'x_boq_s'),
                                 ('ttype', '=', 'one2many')], order='id'):
        # A bill is a x_boq_s_line_* model and nothing else. Taking every
        # one2many on the model swept in the chatter - followers, messages,
        # ratings, activities - and read a quarter of a million mail rows as
        # though they were priced items.
        if not field.relation or not field.relation.startswith('x_boq_s_line'):
            continue
        line_model = source(field.relation)
        if line_model is None:
            continue
        names = field_names(field.relation)
        parent = pick(names, ('boq', 'x_studio_bill'), avoid=('_line',))
        found.append({
            'field': field.name,
            'label': field.field_description or field.name,
            'model': field.relation,
            'parent': parent,
            'description': pick(names, ('x_name', 'description', 'item')),
            'quantity': pick(names, ('quantity', 'qty')),
            'rate': pick(names, ('unit_price', 'rate', 'price'),
                         avoid=('total',)),
            # BOTH total columns. Some lines carry a typed total instead of a
            # rate - a lump sum - and reading only the rate multiplied those
            # lines by their quantity. On the two priced bills that came to
            # 1,165,085 and 378,325 too much, which is exactly what the second
            # column holds. A bill that disagrees with the old one by a million
            # is worse than a bill that is empty.
            'total_aed': pick(names, ('total_price_aed', 'total_amount_aed')),
            'total': pick(names, ('total_price', 'total_amount', 'amount'),
                          avoid=('_aed',)),
            'rows': len(line_model.search([])),
            'table': line_model._table,
            # the column holding the parent id, straight from the field
            # definition rather than guessed from its name
            'inverse': field.relation_field,
        })
    return found


def money_of(line, section):
    """The quantity and the rate to give a bill item, and how they were got.

    Studio's own total is the fact. It is what was invoiced from and what the
    old system printed, so where it disagrees with quantity times rate - a
    lump sum, a line somebody totalled by hand - the total wins and the rate
    is worked back out of it. The alternative is a bill that adds up to more
    than the one it replaced, which nobody would ever trust again.

    Returns (quantity, rate, how):

        typed     quantity times rate already came to the total
        derived   the total was different, so the rate is total over quantity
        lump      there is a total and no quantity: one of it, at that price
    """
    quantity = (line[section['quantity']] if section['quantity'] else 0.0) or 0.0
    rate = (line[section['rate']] if section['rate'] else 0.0) or 0.0
    total = 0.0
    for column in (section['total_aed'], section['total']):
        if column and line[column]:
            total = line[column]
            break

    if not total:
        return quantity, rate, 'typed'
    if quantity and abs(quantity * rate - total) > 0.01:
        return quantity, total / quantity, 'derived'
    if not quantity:
        return 1.0, total, 'lump'
    return quantity, rate, 'typed'


def orphan_reasons(sections, boq_table):
    """Of the lines that hang off no bill, how many never did, and how many
    hung off one that has since been deleted.

    The difference matters before anything is deleted. Never attached is an
    import that went wrong; attached to a bill that is gone is somebody having
    thrown away the bills and left the lines behind, and that is the whole of
    what was priced, still sitting there.
    """
    never = missing_parent = 0
    for section in sections:
        column = section['inverse']
        if not column or not column_exists(section['table'], column):
            continue
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NULL'
                   % (section['table'], column))
        never += cr.fetchone()[0]
        cr.execute('SELECT COUNT(*) FROM "%s" line WHERE line."%s" IS NOT NULL'
                   '  AND NOT EXISTS (SELECT 1 FROM "%s" boq'
                   '                   WHERE boq.id = line."%s")'
                   % (section['table'], column, boq_table, column))
        missing_parent += cr.fetchone()[0]
    return never, missing_parent


def step_boq():
    title("bill of quantities   x_boq_s -> ssc.boq / .section / .line")
    old = source('x_boq_s')
    if old is None:
        say("  x_boq_s is not on this database. Nothing to do.")
        return
    names = field_names('x_boq_s')
    project_field = pick(names, ('project',))
    say("  project is read from   %s" % (project_field or "NOTHING"))

    sections = bill_sections(old)
    say()
    say("  %s bill section(s) discovered, and what each line model looks like:"
        % len(sections))
    say()
    # how many of each model's rows are actually reachable from a bill: a line
    # that hangs off nothing cannot be carried anywhere, and the difference
    # between the two numbers is the part of the old bill that was already lost
    reachable = {section['model']: 0 for section in sections}
    for row in old.search([]):
        for section in sections:
            reachable[section['model']] += len(row[section['field']])

    say("  %-34s %-28s %7s %7s  %s"
        % ('bill (the field label)', 'line model', 'rows', 'on a bill',
           'columns it will read'))
    for section in sections:
        loose = section['rows'] - reachable[section['model']]
        say("  %-34s %-28s %7s %7s%s  qty=%s rate=%s desc=%s"
            % (section['label'][:34], section['model'][:28], section['rows'],
               reachable[section['model']],
               ' !' if loose else '  ',
               section['quantity'], section['rate'], section['description']))
    orphans = sum(s['rows'] for s in sections) - sum(reachable.values())
    if orphans:
        never, deleted_parent = orphan_reasons(sections, old._table)
        say()
        say("  %s line(s) marked ! hang off no bill at all and cannot be "
            "carried anywhere:" % orphans)
        say("      %6s were never attached to one" % never)
        say("      %6s point at a bill that has since been deleted" % deleted_parent)
        if deleted_parent:
            say()
            say("  Those %s are a priced bill whose header somebody threw away."
                % deleted_parent)
            say("  The lines are still here and still carry their rates. If any")
            say("  of it matters, say so before x_boq_s is deleted, because")
            say("  after that there is nothing left to attach them to.")
    bad = [s for s in sections if not s['quantity'] or not s['rate']]
    if bad:
        say()
        say("  %s section(s) have no quantity or no rate column that could be "
            "found. Their items would come across at nought:" % len(bad))
        for section in bad:
            say("      %-40s %s" % (section['label'][:40], section['model']))

    if not project_field:
        say()
        say("  Stopping: without a project on x_boq_s the bills are homeless.")
        return

    total_lines = derived = lumps = typed = 0
    checked = []
    Work = env['ssc.work.type'].sudo()                           # noqa: F821
    trades_by_name = {normalise(w.name): w for w in Work.search([])}
    specs_by_name = {normalise(w.name): w
                     for w in Work.search([('studio_ref_id', '!=', 0)])}
    for row in old.search([]):
        project = row[project_field]
        if not project:
            note('boq', 'skipped')
            continue
        if WRITE and not project.ssc_is_construction:
            project.ssc_is_construction = True
        boq = upsert('boq', 'ssc.boq', row.id, {
            'project_id': project.id,
            'purpose': 'contract',
            'state': 'draft',
        })
        for order, section in enumerate(sections, start=1):
            lines = row[section['field']]
            if not lines:
                continue
            if not WRITE:
                total_lines += len(lines)
                continue
            new_section = env['ssc.boq.section'].sudo().search([  # noqa: F821
                ('boq_id', '=', boq.id), ('code', '=', str(order))], limit=1)
            # forty of the bill names ARE a trade - Block works, Electrical,
            # HVAC, Plumbing - so the section can say what it is, and every
            # item in it reads the trade down from there
            trade = trades_by_name.get(normalise(section['label']))
            if not new_section:
                new_section = env['ssc.boq.section'].sudo().create({  # noqa: F821
                    'boq_id': boq.id,
                    'code': str(order),
                    'name': section['label'][:120],
                    'sequence': order * 10,
                    'work_type_id': trade.id if trade else False,
                })
            elif trade and not new_section.work_type_id:
                new_section.work_type_id = trade
            for position, line in enumerate(lines, start=1):
                quantity, rate, kind = money_of(line, section)
                if kind == 'derived':
                    derived += 1
                elif kind == 'lump':
                    lumps += 1
                values = {
                    'section_id': new_section.id,
                    'sequence': position * 10,
                    'name': (line[section['description']]
                             if section['description'] else '') or '/',
                    'quantity': quantity,
                    'unit_price': rate,
                    'studio_model': section['model'],
                }
                # two hundred and eighty-four descriptions are word for word a
                # specification carried over from x_type_of_work, and that is
                # more precise than the trade of the bill they sit in
                spec = specs_by_name.get(normalise(values['name']))
                if spec:
                    values['work_type_id'] = spec.id
                    typed += 1
                # the Studio model is part of the key, not just a note on the
                # record: twenty-nine line models, twenty-nine id sequences
                upsert('boq', 'ssc.boq.line', line.id, values,
                       also=[('studio_model', '=', section['model'])])
                total_lines += 1
        # what Studio itself says this bill comes to, so the two can be
        # put side by side rather than trusted
        studio_total = 0.0
        for section in sections:
            for line in row[section['field']]:
                for column in (section['total_aed'], section['total']):
                    if column and line[column]:
                        studio_total += line[column]
                        break
        checked.append((row.id, studio_total))

    say()
    say("  %s item(s) across %s bill(s)" % (total_lines, len(old.search([]))))
    say("  %s item(s) named a specification and took its trade; the rest "
        "take the trade of the bill they sit in" % typed)
    say("  %s line(s) had a total that was not quantity times rate: "
        "%s got the rate worked back out of it, %s are a lump sum"
        % (derived + lumps, derived, lumps))
    say()
    say("  %-16s %-30s %18s %18s %12s"
        % ('bill', 'project', 'Studio says', 'we made it', 'difference'))
    Boq = env['ssc.boq'].sudo()                                  # noqa: F821
    for ref, studio_total in checked:
        boq = Boq.search([('studio_ref_id', '=', ref)], limit=1)
        if not boq:
            say("  %-16s not written yet (dry run)" % ref)
            continue
        difference = boq.amount_total - studio_total
        say("  %-16s %-30s %18.2f %18.2f %12.2f%s"
            % (boq.name, (boq.project_id.display_name or '')[:30],
               studio_total, boq.amount_total, difference,
               '' if abs(difference) < 1.0 else '   <-- LOOK'))


# ============================================================== the packages ===

def step_packages():
    title("packages   x_boq_scope -> ssc.boq.package")
    old = source('x_boq_scope')
    if old is None:
        say("  x_boq_scope is not on this database. Nothing to do.")
        return
    names = field_names('x_boq_scope')
    project_field = pick(names, ('project',))
    boq_field = pick(names, ('boq',))
    say("  project from %s, bill from %s" % (project_field, boq_field))

    rows = old.search([])
    say("  %s scope(s)" % len(rows))
    Boq = env['ssc.boq'].sudo()                                   # noqa: F821

    # In a dry run no bill has been made yet, so looking for one in the new
    # system finds nothing and every package reads as unplaceable - which is
    # not true, it is only early. Ask the Studio side the same question
    # instead, and the dry run says what the real run will do.
    old_boq = source('x_boq_s')
    boq_project_field = pick(field_names('x_boq_s'), ('project',)) \
        if old_boq is not None else None

    def bill_for(row):
        if boq_field and row[boq_field]:
            found = Boq.search([('studio_ref_id', '=', row[boq_field].id)],
                               limit=1)
            if found:
                return found
        if not project_field or not row[project_field]:
            return None
        found = Boq.search([('project_id', '=', row[project_field].id)],
                           limit=1)
        if found:
            return found
        if WRITE or old_boq is None or not boq_project_field:
            return None
        # would there be one, once the bill step has run?
        return old_boq.search([(boq_project_field, '=', row[project_field].id)],
                              limit=1) or None

    for row in rows:
        boq = bill_for(row)
        if not boq:
            note('packages', 'skipped')
            continue
        if not WRITE:
            note('packages', 'made')
            continue
        upsert('packages', 'ssc.boq.package', row.id, {
            'boq_id': boq.id,
            'name': (row.display_name or '')[:120],
        })
    say("  %s made, %s updated, %s could not be put on any bill"
        % (made.get('packages', 0), updated.get('packages', 0),
           skipped.get('packages', 0)))


# ============================================================= the programme ===

def step_programme():
    title("programme   x_project_time_schedul -> ssc.programme / .activity")
    old = source('x_project_time_schedul')
    if old is None:
        say("  x_project_time_schedul is not on this database. Nothing to do.")
        return
    names = field_names('x_project_time_schedul')
    project_field = pick(names, ('project',))
    say("  project from %s" % project_field)

    # Studio's own line models only. Every model carries chatter, and reading
    # activity_ids and message_ids as programme activities counted a quarter of
    # a million mail rows as work.
    line_fields = IrField.search([
        ('model', '=', 'x_project_time_schedul'),
        ('ttype', '=', 'one2many'),
        ('relation', 'like', 'x_project_time_schedul_line%'),
    ])
    say("  activity lines come from %s"
        % (", ".join("%s (%s)" % (f.name, f.relation) for f in line_fields)
           or "NOTHING - this schedule has no line model of its own"))

    if not project_field:
        say("  Stopping: a programme with no project cannot be created.")
        return

    Package = env['ssc.boq.package'].sudo()                      # noqa: F821
    position_note, linked = {}, {'count': 0}
    for row in old.search([]):
        project = row[project_field]
        if not project:
            note('programme', 'skipped')
            continue
        programme = upsert('programme', 'ssc.programme', row.id, {
            'project_id': project.id,
            'purpose': 'baseline',
            'state': 'draft',
        })
        for field in line_fields:
            line_names = field_names(field.relation)
            start = pick(line_names, ('start', 'from', 'date_1'))
            finish = pick(line_names, ('finish', 'end', 'to'))
            cost = pick(line_names, ('cost', 'amount', 'value', 'price'))
            # the activity says which scope of work it delivers, and a scope
            # is a package. Studio held the link and this import was ignoring
            # it, which is why every activity came across worth nothing that
            # could be checked against a bill
            scope = None
            for candidate in IrField.search([('model', '=', field.relation),
                                             ('ttype', '=', 'many2one'),
                                             ('relation', '=', 'x_boq_scope')]):
                scope = candidate.name
                break
            if position_note.get(field.relation) is None:
                position_note[field.relation] = True
                say("      dates from %s / %s, cost from %s, package from %s"
                    % (start or 'NOTHING', finish or 'NOTHING',
                       cost or 'NOTHING', scope or 'NOTHING'))
            for position, line in enumerate(row[field.name], start=1):
                package = False
                if scope and line[scope]:
                    found = Package.search(
                        [('studio_ref_id', '=', line[scope].id)], limit=1)
                    package = found.id if found else False
                    if found:
                        linked['count'] += 1
                if not WRITE:
                    note('programme', 'made')
                    continue
                upsert('programme', 'ssc.programme.activity', line.id, {
                    'programme_id': programme.id,
                    'name': (line.display_name or '')[:120],
                    'sequence': position * 10,
                    'date_start': line[start] if start else False,
                    'date_finish': line[finish] if finish else False,
                    'amount_planned': (line[cost] if cost else 0.0) or 0.0,
                    'package_id': package,
                })
    say("  %s made, %s updated, %s skipped"
        % (made.get('programme', 0), updated.get('programme', 0),
           skipped.get('programme', 0)))
    say("  %s activity(ies) were matched to the package they deliver"
        % linked['count'])


# ===================================================================== run ===

def step_splits():
    """How much of each item is in which zone - what progress is measured on.

    Studio held this as a quantity against a sector and a work type, in the
    grandchildren of x_detailed_quantity: 2,522 rows, of which 578 carry a
    quantity at all. There is no bill item on them, so the item has to be found
    - the one line of that project's bill that is the same work type. Where
    there is exactly one, the split can be made. Where there are several, the
    row says a quantity of blockwork on the second floor and the bill has four
    blockwork items, and only somebody who knows the job can say which.

    Nothing is guessed. The ambiguous ones are counted and left.
    """
    title("split by zone   x_detailed_quantity ... -> ssc.boq.line.zone")
    old = source('x_detailed_quantity_line_f60e2_line_368c6')
    if old is None:
        say("  The sectors-and-works rows are not on this database.")
        return
    parent_model = source('x_detailed_quantity_line_f60e2')
    names = field_names('x_detailed_quantity_line_f60e2_line_368c6')
    quantity_field = pick(names, ('sector_quantity', 'quantity', 'qty'))
    work_field = pick(names, ('work_description', 'work'))
    parent_field = pick(names, ('_f60e2_id',))
    parent_names = (field_names('x_detailed_quantity_line_f60e2')
                    if parent_model is not None else set())
    sector_field = pick(parent_names, ('sector',), avoid=('_main',))
    sector_alternate = pick(parent_names, ('sector_main',))

    say("  quantity from %s, work type from %s" % (quantity_field, work_field))
    say("  the sector is on the parent row, in %s, or failing that %s"
        % (sector_field, sector_alternate))
    if not (quantity_field and work_field and parent_field and sector_field):
        say("  Stopping: without all four there is nothing to join on.")
        return

    Zone = env['ssc.project.zone'].sudo()                        # noqa: F821
    Work = env['ssc.work.type'].sudo()                           # noqa: F821
    Line = env['ssc.boq.line'].sudo()                            # noqa: F821

    rows = old.search([])
    no_quantity = no_zone = no_work = ambiguous = nothing = 0
    contributing = 0
    # Several take-off rows land on the same item in the same zone, and they
    # ADD UP - two hundred and ninety-three of three hundred and twenty-two did.
    # Writing them one at a time left the last one standing and threw the rest
    # away, which is a quantity that is wrong rather than one that is missing.
    gathered = {}
    for row in rows:
        quantity = row[quantity_field] or 0.0
        if not quantity:
            no_quantity += 1
            continue
        parent = row[parent_field]
        # the fuller of the two sector columns first: x_studio_sector is on
        # fifty-two of the parent rows and x_studio_sector_main on thirty-two,
        # and taking the smaller one lost ninety-six rows for no reason
        sector = False
        for column in (sector_field, sector_alternate):
            if column and parent and parent[column]:
                sector = parent[column]
                break
        zone = Zone.search([('studio_ref_id', '=', sector.id)],
                           limit=1) if sector else Zone.browse()
        if not zone:
            no_zone += 1
            continue
        specification = row[work_field]
        work = Work.search([('studio_ref_id', '=', specification.id)],
                           limit=1) if specification else Work.browse()
        if not work:
            no_work += 1
            continue
        candidates = Line.search([
            ('project_id', '=', zone.project_id.id),
            ('work_type_id', '=', work.id),
            ('display_type', '=', False),
        ])
        if len(candidates) > 1:
            ambiguous += 1
            continue
        if not candidates:
            nothing += 1
            continue
        # keyed on what it is - this item, in this zone - because a split has
        # no studio_ref_id of its own and does not need one: the pair is the
        # identity, and the model refuses a second row for it anyway
        key = (candidates.id, zone.id)
        gathered[key] = gathered.get(key, 0.0) + quantity
        contributing += 1

    for (line_id, zone_id), quantity in gathered.items():
        _split(Line.browse(line_id), Zone.browse(zone_id), quantity)

    say()
    say("  %s row(s) in Studio" % len(rows))
    say("      %6s carry no quantity and say nothing" % no_quantity)
    say("      %6s have no sector we could place" % no_zone)
    say("      %6s have no work type we could place" % no_work)
    say("      %6s name a work type the bill has several items of - only "
        "somebody who knows the job can say which" % ambiguous)
    say("      %6s name a work type this project's bill does not have"
        % nothing)
    say("      %6s row(s) survived all of that, and add up to %s "
        "quantities - an item in a zone measured twice is one quantity, "
        "not the second measurement" % (contributing, len(gathered)))
    say("      %6s made, %s updated"
        % (made.get('splits', 0), updated.get('splits', 0)))


def _split(line, zone, quantity):
    """Make or correct the quantity of one item in one zone."""
    Split = env['ssc.boq.line.zone'].sudo()                      # noqa: F821
    existing = Split.search([('line_id', '=', line.id),
                             ('zone_id', '=', zone.id)], limit=1)
    if not WRITE:
        note('splits', 'updated' if existing else 'made')
        return existing
    if existing:
        existing.quantity = quantity
        note('splits', 'updated')
        return existing
    note('splits', 'made')
    return Split.create({'line_id': line.id, 'zone_id': zone.id,
                         'quantity': quantity})


STEP_FUNCTIONS = {
    'trades': step_trades,
    'zones': step_zones,
    'boq': step_boq,
    'packages': step_packages,
    'programme': step_programme,
    'splits': step_splits,
}

title("DRY RUN - nothing is written" if not WRITE
      else "WRITING - records are being created")

for step in STEPS:
    function = STEP_FUNCTIONS.get(step)
    if not function:
        say("  no step called %s" % step)
        continue
    function()

title("what it came to")
for step in STEPS:
    say("  %-12s made %-6s updated %-6s skipped %s"
        % (step, made.get(step, 0), updated.get(step, 0), skipped.get(step, 0)))

if not WRITE:
    say()
    say("  Nothing was written. Read the columns each bill section would be")
    say("  read from - a wrong guess there is a bill of quantities that comes")
    say("  across at nought - and then run it again with SSC_WRITE=1.")
    env.cr.rollback()                                            # noqa: F821
else:
    env.cr.commit()                                              # noqa: F821
    say()
    say("  Committed.")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)
