"""Round 2: consolidate data/r2_out/batch_*.csv into executable plans with the senior guards (DECISIONS.md).
Usage: python -I lib/r2_build.py <work_dir>
Outputs (data/): r2_plan_merge.json, r2_plan_variants.json (+ _compact.txt), r2_plan_updates.json, r2_plan_garbage.json,
r2_held.csv (every row held back and why), and prints a summary.
"""
import csv, json, re, sys
from collections import defaultdict, Counter
from pathlib import Path

W = Path(sys.argv[1])
sys.path.insert(0, str(W / 'lib'))
from units import unit_key  # noqa: E402
from dedup_lib import normalise  # noqa: E402

rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
X = json.load(open(W / 'data/r2_extract.json', encoding='utf-8'))
m2o = lambda v: v[0] if isinstance(v, list) and v else None
T = {t['id']: t for t in X['templates']}
VARS = defaultdict(list)
for v in X['variants']:
    VARS[m2o(v['product_tmpl_id'])].append(v)
cat_id = {c['complete_name']: c['id'] for c in X['categories']}
ptav = {p['id']: p for p in X['ptav']}
CAT = {r['canonical_attribute'] for r in rd(W / 'data/attribute_catalogue.csv')}
UNITS = {'Nos', 'Mtr', 'Sqm', 'Cum', 'Ltr', 'Kg', 'Ton', 'Roll', 'Box', 'Ctn', 'Pkt', 'Drum', 'Bag', 'Set', 'Pair', 'Bundle', 'L.S',
         'Length', 'Sheet', 'Can', 'Bottle', 'Dozen', 'Hour', 'Gallon', 'Trip', 'Day', 'Month'}
hist = defaultdict(float)
pv = defaultdict(float)
for q in X['quants']:
    pv[m2o(q['product_id'])] += abs(q['quantity:sum'])
for key in ('moves', 'pol', 'mr', 'bills'):
    for g in X[key]:
        hist[m2o(g['product_id'])] += g['__count']
lastprice = {m2o(g['product_id']): g.get('price_unit:max') or 0 for g in X['pol']}
vendor_t = {m2o(g['product_tmpl_id']): g['__count'] for g in X['vendor']}
P_old = {r['var_id']: r for r in rd(W / 'data/products.csv')}
digits = lambda s: set(re.findall(r'\d+(?:\.\d+)?', (s or '').lower()))

rows = []
for p in sorted(W.glob('data/r2_out/batch_*.csv')):
    rows += rd(p)
held = []
def hold(r, why):
    held.append({'tmpl_id': r['tmpl_id'], 'name': T.get(int(r['tmpl_id']), {}).get('name', ''), 'action': r.get('action'), 'why': why, 'question': r.get('question', '')})

want = {t['id'] for t in X['templates'] if not any(l for l in X['lines'] if m2o(l['product_tmpl_id']) == t['id'])}
got = Counter(int(r['tmpl_id']) for r in rows)
missing = [t for t in want if t not in got]
dupl_rows = [t for t, c in got.items() if c > 1]

single_var = lambda t: VARS[t][0]['id'] if len(VARS[t]) == 1 else None
updates, merges, garbage = {}, defaultdict(list), []
variant_rows = []
def fallback_rename(r, t):
    nn = (r.get('new_name') or '').strip() or ' '.join(x for x in [(r.get('template_name') or '').strip()] + [v.strip() for v in (r.get('attributes') or '').replace(';', '=').split('=')[1::2]] if x)
    if nn and nn != T[t]['name'] and digits(T[t]['name']) <= digits(nn):
        updates[t] = {**updates.get(t, {}), 'name': nn}
for r in rows:
    t = int(r['tmpl_id'])
    if t not in T:
        continue
    act = (r['action'] or '').strip().upper()
    act = {'R': 'RENAME', 'V': 'VARIANT', 'D': 'DUPLICATE', 'Q': 'QUESTION', 'K': 'KEEP', 'G': 'GARBAGE'}.get(act, act)
    r['action'] = act
    upd = {}
    if r.get('category', '').strip():
        c = r['category'].strip()
        if c in cat_id and cat_id[c] != m2o(T[t]['categ_id']):
            upd['categ_id'] = cat_id[c]
        elif c not in cat_id:
            hold(r, f'unknown category {c!r} (category ignored)')
    if r.get('unit', '').strip():
        u = r['unit'].strip()
        if u in UNITS and unit_key(T[t]['x_unit']) == '?':
            upd['x_unit'] = u
    if act in ('RENAME', 'KEEP', 'QUESTION', 'VARIANT') and r.get('new_name', '').strip() and act != 'VARIANT':
        nn = r['new_name'].strip()
        if nn != T[t]['name']:
            if digits(T[t]['name']) <= digits(nn):
                upd['name'] = nn
            else:
                hold(r, f'rename dropped, numbers lost: {nn!r}')
    if act == 'GARBAGE':
        v = single_var(t)
        if v and not hist[v] and not pv[v] and not vendor_t.get(t):
            garbage.append(t)
        else:
            hold(r, 'garbage name but it has history/stock: rename by hand')
    elif act == 'DUPLICATE':
        try:
            d = int(float(r['dup_of']))
        except ValueError:
            hold(r, 'duplicate without dup_of'); d = None
        if d:
            a, b = single_var(t), single_var(d) if d in T else None
            ua, ub = unit_key(T[t]['x_unit']), unit_key(T[d]['x_unit']) if d in T else '?'
            pa, pb = lastprice.get(a, 0), lastprice.get(b, 0)
            why = None
            if not a or not b:
                why = 'duplicate of a variant template or missing template (decide the variant by hand)'
            elif ua != '?' and ub != '?' and ua != ub:
                why = f'units differ {T[t]["x_unit"]} vs {T[d]["x_unit"]}'
            elif pa and pb and max(pa, pb) / min(pa, pb) > 3:
                why = f'last PO price {pa} vs {pb} (>3x)'
            if why:
                hold(r, why)
            else:
                merges[d].append(t)
    elif act == 'VARIANT':
        variant_rows.append(r)
    if upd:
        updates[t] = {**updates.get(t, {}), **upd}

# resolve duplicate chains (A->B, B->C) and pick the master with most history
parent = {}
def find(x):
    while parent.get(x, x) != x:
        x = parent[x]
    return x
for d, ts in merges.items():
    for t in ts:
        parent[find(t)] = find(d)
groups = defaultdict(set)
for x in set(parent) | set(parent.values()):
    groups[find(x)].add(x)
plan_merge = []
for root, members in groups.items():
    vs = [(single_var(t), t) for t in members]
    vs.sort(key=lambda x: -(hist[x[0]] + pv[x[0]] * 0.01))
    m, mt = vs[0]
    plan_merge.append({'g': f'R2-{mt}', 'master': m, 'dups': [v for v, _ in vs[1:]], 'rename': updates.get(mt, {}).get('name')})
merged_away = {}
for p in plan_merge:
    for v in p['dups']:
        merged_away[v] = p['master']

# variants: group by target template
def parse_attrs(s):
    out = {}
    for kv in (s or '').split(';'):
        if '=' in kv:
            a, v = kv.split('=', 1)
            out[a.strip()] = v.strip()
    return out
targets = defaultdict(list)
for r in variant_rows:
    t = int(r['tmpl_id']); v = single_var(t)
    vals = parse_attrs(r['attributes'])
    if not v:
        hold(r, 'variant row on a template that already has several variants'); continue
    if v in merged_away:
        continue
    bad = [a for a in vals if a not in CAT]
    if bad or not vals:
        hold(r, f'attributes not in catalogue: {bad or "none"}'); fallback_rename(r, t); continue
    if any('?' in x or not x for x in vals.values()):
        hold(r, 'attribute value missing'); fallback_rename(r, t); continue
    nm = set(re.findall(r'[a-z0-9.]+', normalise(T[t]['name'] + ' ' + (T[t].get('x_specifications') or ''))))
    nm |= {'grey'} if {'gray', 'gary'} & nm else set()
    missing_vals = []
    for a, x in vals.items():
        toks = re.findall(r'[a-z0-9.]+', normalise(x))
        num = [k for k in toks if re.search(r'\d', k)]
        alpha = [k for k in toks if not re.search(r'\d', k) and len(k) > 2]
        ok = (all(any(k in n or n in k for n in nm if re.search(r'\d', n)) for k in num) if num else True) and (any(k in nm for k in alpha) if alpha and not num else True)
        if not ok:
            missing_vals.append(f'{a}={x}')
    if missing_vals:
        hold(r, f'value not written in the name: {missing_vals}'); fallback_rename(r, t); continue
    k = (r['template_key'] or '').strip()
    if k.startswith('T') and k[1:].isdigit():
        key = ('T', int(k[1:]))
    else:
        key = ('N', re.sub(r'[^a-z0-9]', '', (r['template_name'] or '').lower()), unit_key(T[t]['x_unit']))
    targets[key].append((v, t, vals, (r['template_name'] or '').strip()))

attr_of_tmpl = defaultdict(set)
for l in X['lines']:
    attr_of_tmpl[m2o(l['product_tmpl_id'])].add(l['attribute_id'][1])
def var_vals(vid):
    v = next(x for x in X['variants'] if x['id'] == vid)
    return {ptav[p]['attribute_id'][1]: ptav[p]['product_attribute_value_id'][1] for p in v['product_template_attribute_value_ids'] if p in ptav}
plan_var = []
for key, items in targets.items():
    if key[0] == 'T':
        tt = key[1]
        if tt not in T:
            for v, t, vals, n in items: hold({'tmpl_id': t, 'action': 'VARIANT'}, f'target template T{tt} not found')
            continue
        attrs = sorted(attr_of_tmpl[tt])
        existing = [x['id'] for x in VARS[tt]]
        master = existing[0]
        taken = {tuple(var_vals(e).get(a) for a in attrs) for e in existing}
        name = T[tt]['name']
        base = [{'var': master, 'vals': [var_vals(master).get(a) for a in attrs]}]
    else:
        attrs = sorted({a for _, _, vals, _ in items for a in vals})
        items.sort(key=lambda x: -hist[x[0]])
        master = items[0][0]; taken = set(); base = []; name = items[0][3]
    new = []
    for v, t, vals, n in items:
        if set(vals) != set(attrs):
            hold({'tmpl_id': t, 'action': 'VARIANT'}, f'attribute set {sorted(vals)} differs from template {attrs}'); continue
        combo = tuple(vals[a] for a in attrs)
        if combo in taken:
            hold({'tmpl_id': t, 'action': 'VARIANT'}, f'same combination {combo} as another item: question'); continue
        taken.add(combo); new.append({'var': v, 'vals': list(combo)})
    if key[0] == 'N':
        if len(new) < 2:
            for it in new: hold({'tmpl_id': next(t for v, t, *_ in items if v == it['var']), 'action': 'VARIANT'}, 'template would hold one item (renamed only)')
            continue
        master = new[0]['var']
    elif not new:
        continue
    plan_var.append({'tk': f'{key[0]}-{key[1]}', 'name': name, 'attrs': attrs, 'master': master, 'items': base + new})

json.dump(plan_merge, open(W / 'data/r2_plan_merge.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(plan_var, open(W / 'data/r2_plan_variants.json', 'w', encoding='utf-8'), ensure_ascii=False)
var_tmpls = set()
for p_ in plan_var:
    for it in p_['items']:
        tt = next((t for t, vs in VARS.items() if any(x['id'] == it['var'] for x in vs)), None)
        if tt: var_tmpls.add(tt)
upd_list = [[t, u] for t, u in updates.items() if t not in var_tmpls or set(u) - {'name'}]
for t, u in upd_list:
    if t in var_tmpls:
        u.pop('name', None)
upd_list = [[t, u] for t, u in upd_list if u]
json.dump(upd_list, open(W / 'data/r2_plan_updates.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(garbage, open(W / 'data/r2_plan_garbage.json', 'w', encoding='utf-8'))
with open(W / 'data/r2_held.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['tmpl_id', 'name', 'action', 'why', 'question']); w.writeheader(); w.writerows(held)
print('rows', len(rows), '| missing', len(missing), missing[:5], '| duplicated rows', len(dupl_rows))
print('actions', Counter((r['action'] or '').upper() for r in rows))
print('merge groups', len(plan_merge), 'items archived', sum(len(p['dups']) for p in plan_merge))
print('variant templates', len(plan_var), '(existing', sum(1 for p in plan_var if p['tk'].startswith('T')), ') items added', sum(len(p['items']) - (1 if p['tk'].startswith('T') else 0) for p in plan_var))
print('updates', len(upd_list), Counter(k for _, u in upd_list for k in u), '| garbage to archive', len(garbage), '| held', len(held), Counter(h['why'].split(' ')[0] for h in held))
