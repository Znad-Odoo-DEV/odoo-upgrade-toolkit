"""Round 8 builder: data/r8_out/batch_*.csv (+ fix_*.csv, read last, wins) + data/main_final/main_final_extract.json -> executable plans.
Usage: python -I lib/r8_build.py <work_dir>
Order to run: 1 moves (family targets + CLEAN: name + Material/spec values on all variants), 2 variant merges (same item twice:
merged first, source template kept while it has other variants), 3 joins (other templates' variants move into the family
template, missing attributes "Not Specified"), 4 categories.
"""
import csv, json, re, sys, functools
from collections import defaultdict, Counter
from pathlib import Path

W = Path(sys.argv[1])
sys.path.insert(0, str(W / 'lib'))
from units import unit_key  # noqa: E402

X = json.load(open(W / 'data/main_final/main_final_extract.json', encoding='utf-8'))
m2o = lambda v: v[0] if isinstance(v, list) and v else None
T = {t['id']: t for t in X['templates']}
cats = {c['complete_name']: c['id'] for c in X['categories']}
ptav = {p['id']: (p['attribute_id'][1], p['name']) for p in X['ptav']}
qty = {m2o(g['product_id']): g['quantity:sum'] for g in X['qty']}
price = {m2o(g['product_id']): g.get('price_unit:max') or 0 for g in X['pol']}
hist = {m2o(g['product_id']): g['__count'] for g in X['pol']}
attrs_of = defaultdict(list)
for l in X['lines']:
    attrs_of[m2o(l['product_tmpl_id'])].append(l['attribute_id'][1])
VARS = defaultdict(list)
for v in X['variants']:
    VARS[m2o(v['product_tmpl_id'])].append({'id': v['id'], 'code': v['default_code'] or '',
                                            'vals': dict(ptav[i] for i in v['product_template_attribute_value_ids'] if i in ptav)})
CAT_ATTR = {r['canonical_attribute'] for r in csv.DictReader(open(W / 'data/attribute_catalogue.csv', encoding='utf-8-sig'))} | \
    {'Steps', 'Model', 'Power', 'Volume', 'Weight', 'Pack', 'Material', 'Voltage', 'IP Rating', 'Finish'}
ATTR_MAP = {'Damper': 'Type', 'Class': 'Grade', 'Plies': 'Type', 'Ply': 'Type', 'Rating': 'IP Rating', 'IP': 'IP Rating'}
NS = 'Not Specified'
MAT = {'ppr': 'PPR', 'upvc': 'uPVC', 'pvc': 'PVC', 'hp': 'HP PVC', 'hp pvc': 'HP PVC', 'hppvc': 'HP PVC', 'gi': 'GI', 'g.i': 'GI',
       'ms': 'MS', 'ss': 'SS', 'hdg': 'HDG', 'brass': 'Brass', 'copper': 'Copper', 'cu': 'Copper', 'hdpe': 'HDPE', 'pex': 'PEX',
       'cpvc': 'CPVC', 'skolon': 'Skolon', 'soundproof': 'Soundproof', 'ductile iron': 'Ductile Iron', 'aluminium': 'Aluminium',
       'aluminum': 'Aluminium', 'steel': 'Steel', 'cast iron': 'Cast Iron', 'rubber': 'Rubber', 'not specified': NS, '': ''}


def norm_mat(m):
    k = (m or '').strip().lower()
    return MAT.get(k, (m or '').strip())


def nums(s):
    s = re.sub(r'(\d)\.(\d+/\d+)', lambda m: m.group(1) + ' ' + m.group(2), (s or '').lower())
    out = {round(int(a) / int(b), 4) for a, b in re.findall(r'(\d+)\s*/\s*(\d+)', s) if int(b)}
    return out | {round(float(x), 4) for x in re.findall(r'\d+(?:\.\d+)?', s)}


def written(name, val):
    if val in (NS, ''):
        return True
    vn = nums(val)
    if vn:
        return vn <= nums(name)
    nm = set(re.findall(r'[a-z]+', name.lower().replace('gray', 'grey')))
    if 'hp' in val.lower() and 'hp' in nm:
        return True
    words = [w for w in re.findall(r'[a-z]+', val.lower().replace('gray', 'grey')) if len(w) > 1]
    return any(w in nm for w in words) if words else True


def parse(s):
    out = {}
    for kv in (s or '').split(';'):
        if '=' in kv:
            a, v = kv.split('=', 1)
            if a.strip() and v.strip():
                out[a.strip()] = v.strip()
    return out


rows = {}
for p in sorted(W.glob('data/r8_out/batch_*.csv')) + sorted(W.glob('data/r8_out/fix_*.csv')):
    for r in csv.DictReader(open(p, encoding='utf-8-sig')):
        t = int(re.sub(r'\D', '', r['tmpl_id'] or '0') or 0)
        if t in T:
            rows[t] = r
log, held = Counter(), []
fam = defaultdict(list)
moves, renames, catw = [], [], {}
for t, r in rows.items():
    act = (r['action'] or '').strip().upper()
    name = T[t]['name']
    specs = {ATTR_MAP.get(a, a): v for a, v in parse(r.get('specs')).items()}
    bad = [a for a in specs if a not in CAT_ATTR]
    for a in bad:
        held.append((t, name, f'attribute {a} not in catalogue')); specs.pop(a)
    for a, v in list(specs.items()):
        if not written(name, v):
            held.append((t, name, f'spec {a}={v} not written in the name')); specs.pop(a)
    mat = norm_mat(r.get('material'))
    if mat and mat != NS and not written(name, mat):
        held.append((t, name, f'material {mat} not written in the name')); mat = NS
    if r.get('category', '').strip():
        catw[t] = r['category'].strip()
    if act == 'FAMILY' and (r.get('family_key') or '').strip():
        fam[r['family_key'].strip()].append({'t': t, 'name': (r.get('family_name') or '').strip(), 'mat': mat or NS, 'specs': specs})
    elif act == 'CLEAN':
        nn = (r.get('new_name') or '').strip()
        if mat and mat != NS:
            specs['Material'] = mat
        if not nn or re.search(r'[|~#^]', nn):
            held.append((t, name, 'clean without a usable name')); continue
        lost = nums(name) - nums(nn) - set().union(*[nums(v) for v in specs.values()]) if specs else nums(name) - nums(nn)
        if lost:
            held.append((t, name, f'numbers {sorted(lost)} lost by "{nn}"')); continue
        existing = set(attrs_of.get(t, []))
        specs = {a: v for a, v in specs.items() if a not in existing}
        if specs:
            moves.append({'t': t, 'name': nn, 'specs': specs})
        elif nn != name:
            renames.append((t, nn))
        log['clean'] += 1
    else:
        log['keep'] += 1

# the same family made in two batches (same name, unit family and system) is one family
uni = {}
for k in list(fam):
    ms = fam[k]
    nm = Counter(m['name'] for m in ms if m['name']).most_common(1)
    if not nm:
        continue
    root = Counter((catw.get(m['t']) or '').split(' / ')[0] for m in ms).most_common(1)[0][0]
    unit = Counter(unit_key(T[m['t']]['x_unit']) for m in ms if m['t'] in T).most_common(1)[0][0]
    key2 = (re.sub(r'[^a-z0-9]', '', nm[0][0].lower()), unit, root)
    if key2 in uni and uni[key2] != k:
        fam[uni[key2]] += fam.pop(k); log['families joined across batches'] += 1
    else:
        uni[key2] = k

# families -> target move + variant merges + joins
merges, joins = [], []
joined_gone = set()  # members merged into their family target (the target chosen AFTER sorting)
for k, members in fam.items():
    members = [m for m in members if T.get(m['t'])]
    FAMU = {'RAW:pvc': 'EA', 'RAW:trip': 'EA', 'SHEET': 'EA'}  # 'PVC' typed as a unit, a trip, a sheet = one piece
    units = {FAMU.get(unit_key(T[m['t']]['x_unit']), unit_key(T[m['t']]['x_unit'])) for m in members} - {'?'}
    if len(members) < 2 or len(units) > 1:
        for m in members:
            held.append((m['t'], T[m['t']]['name'], f'family {k}: ' + ('one template' if len(members) < 2 else f'units {sorted(units)}')))
        continue
    fname = Counter(m['name'] for m in members if m['name']).most_common(1)[0][0]
    members.sort(key=lambda m: (-len(VARS[m['t']]), -sum(qty.get(v['id'], 0) for v in VARS[m['t']])))
    tgt = members[0]
    has_mat = {m['t']: 'Material' in attrs_of.get(m['t'], []) for m in members}
    # attributes of the final template
    all_attrs = []
    for m in members:
        for a in list(attrs_of.get(m['t'], [])) + list(m['specs']) + ['Material']:
            if a not in all_attrs:
                all_attrs.append(a)
    tspecs = dict(tgt['specs'])
    if not has_mat[tgt['t']]:
        tspecs['Material'] = tgt['mat'] or NS
    tspecs = {a: v for a, v in tspecs.items() if a not in attrs_of.get(tgt['t'], [])}
    moves.append({'t': tgt['t'], 'name': fname, 'specs': tspecs, 'family': k})

    def vals_of(m, v):
        d = dict(v['vals'])
        for a, x in m['specs'].items():
            d.setdefault(a, x)
        if 'Material' not in d:
            d['Material'] = m['mat'] or NS
        return tuple(re.sub(r'[|~#^]', '/', str(d.get(a, NS))) for a in all_attrs)
    tv = VARS[tgt['t']]
    combos = {vals_of(tgt, v): v['id'] for v in tv}
    items = [{'var': tv[0]['id'], 'vals': list(vals_of(tgt, tv[0]))}]
    for m in members[1:]:
        for v in VARS[m['t']]:
            c = vals_of(m, v)
            if c in combos:
                a, b = v['id'], combos[c]
                pa, pb = price.get(a, 0), price.get(b, 0)
                if pa and pb and min(pa, pb) >= 0.01 and max(pa, pb) / min(pa, pb) > 3:
                    held.append((m['t'], T[m['t']]['name'], f'variant {a} equals {b} but PO price {pa} vs {pb}')); continue
                merges.append({'g': f'R8-{b}-{a}', 'master': b, 'dups': [a]}); log['variant merges'] += 1
                continue
            combos[c] = v['id']
            items.append({'var': v['id'], 'vals': list(c)})
    if len(items) > 1:
        joins.append({'tk': f'T-{tgt["t"]}', 'name': fname, 'attrs': all_attrs, 'master': tv[0]['id'], 'items': items, 'family': k})
    log['families'] += 1
    for m in members:
        catw.setdefault(tgt['t'], catw.get(m['t'], ''))
    fcats = Counter(catw.get(m['t']) for m in members if catw.get(m['t']))
    if fcats:
        catw[tgt['t']] = fcats.most_common(1)[0][0]
    for m in members[1:]:
        catw.pop(m['t'], None)
    joined_gone |= {m['t'] for m in members[1:]}

# names: a final name used by another remaining template -> held (no duplicate names)
final_names = Counter()
gone = joined_gone
named = {mv['t']: mv['name'] for mv in moves} | {t: n for t, n in renames}
for t, tr in T.items():
    if t not in gone:
        final_names[(named.get(t, tr['name']).lower(), unit_key(tr['x_unit']))] += 1
dupnames = {k for k, n in final_names.items() if n > 1}
for lst in (moves, renames):
    for x in list(lst):
        t, n = (x['t'], x['name']) if isinstance(x, dict) else x
        if (n.lower(), unit_key(T[t]['x_unit'])) in dupnames and not (isinstance(x, dict) and x.get('family')):
            held.append((t, T[t]['name'], f'final name "{n}" used by another template with the same unit')); lst.remove(x)
cat_new = sorted({c for c in catw.values() if c and c not in cats})
cat_plan = [(t, c) for t, c in catw.items() if c and c != (T[t]['categ_id'][1] if T[t]['categ_id'] else '') and t not in gone]

sep = lambda s: bool(re.search(r'[|~#^]', s or ''))
json.dump({'moves': moves, 'renames': renames, 'merges': merges, 'joins': joins, 'categories': cat_plan, 'new_categories': cat_new},
          open(W / 'data/r8_plan.json', 'w', encoding='utf-8'), ensure_ascii=False)
open(W / 'data/r8_c_moves.txt', 'w', encoding='utf-8').write('~'.join(f"{m['t']}|{m['name']}|" + '^'.join(f'{a}={v}' for a, v in m['specs'].items()) for m in moves if not sep(m['name'])))
open(W / 'data/r8_c_renames.txt', 'w', encoding='utf-8').write('~'.join(f'{t}|{n}' for t, n in renames))
open(W / 'data/r8_c_merges.txt', 'w', encoding='utf-8').write('~'.join(f"{m['g']}|{m['master']}|{','.join(map(str, m['dups']))}|" for m in merges))
open(W / 'data/r8_c_joins.txt', 'w', encoding='utf-8').write('#'.join(f"{p['tk']}|{p['name']}|{'^'.join(p['attrs'])}|{p['master']}|" + '~'.join(f"{i['var']}^{'^'.join(i['vals'])}" for i in p['items']) for p in joins))
open(W / 'data/r8_c_cats.txt', 'w', encoding='utf-8').write('~'.join(f'{t}|{c}' for t, c in cat_plan))
with open(W / 'data/r8_held.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f); w.writerow(['tmpl_id', 'name', 'why']); w.writerows(held)
ck = lambda ids: (len(ids), sum(ids), functools.reduce(lambda a, b: a ^ b, ids, 0))
print('rows', len(rows), 'of', len(T), dict(log))
print('moves', len(moves), '| renames', len(renames), '| variant merges', len(merges), '| joins', len(joins), 'items', sum(len(p['items']) for p in joins),
      'CHECK', ck([i['var'] for p in joins for i in p['items']]))
print('categories to set', len(cat_plan), '| new sub-categories', len(cat_new), cat_new[:12])
print('held', len(held), Counter(h[2].split(' ')[0] for h in held))

# review file for the QA: every family (members, material, values), every clean (old -> new + values), merges, held
with open(W / 'data/r8_review.txt', 'w', encoding='utf-8') as f:
    vname = lambda t: T[t]['name'] if t in T else '?'
    f.write('# FAMILIES: family_key | final name | target T | members: T<id> "old name" [unit] material=... specs=...\n')
    for k, ms in fam.items():
        f.write(f"{k} | {Counter(m['name'] for m in ms).most_common(1)[0][0] if ms else ''}\n")
        for m in ms:
            f.write(f"    T{m['t']} \"{vname(m['t'])}\" [{T[m['t']]['x_unit'] if m['t'] in T else ''}] material={m['mat']} specs={m['specs']} variants={[v['vals'] for v in VARS[m['t']]][:6]}\n")
    f.write('\n# CLEAN (one template): T<id> "old" -> "new" + values on all its variants\n')
    for mv in moves:
        if not mv.get('family'):
            f.write(f"T{mv['t']} \"{vname(mv['t'])}\" -> \"{mv['name']}\" {mv['specs']}\n")
    for t, n in renames:
        f.write(f"T{t} \"{vname(t)}\" -> \"{n}\"\n")
    f.write('\n# VARIANT MERGES (same item twice in a family)\n')
    for m in merges:
        f.write(f"{m['g']}: keep {m['master']} <- {m['dups']}\n")
    f.write('\n# CATEGORY changes: T<id> "name" : old -> new\n')
    for t, c in cat_plan:
        f.write(f"T{t} \"{vname(t)}\" : {T[t]['categ_id'][1] if T[t]['categ_id'] else ''} -> {c}\n")
