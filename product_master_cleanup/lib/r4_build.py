"""Round 4 (every remaining single product): consolidate data/r4_out/batch_*.csv into plans with guards.
Usage: python -I lib/r4_build.py <work_dir>
Outputs: data/r4_merge.json, data/r4_variants.json, data/r4_renames.json, data/r4_held.csv, compact files data/r4_c_*.txt
"""
import csv, json, re, sys, functools, difflib
from collections import defaultdict, Counter
from pathlib import Path

W = Path(sys.argv[1])
sys.path.insert(0, str(W / 'lib'))
from units import unit_key  # noqa: E402
from dedup_lib import normalise  # noqa: E402

rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
X = json.load(open(W / 'data/r4_extract.json', encoding='utf-8'))
m2o = lambda v: v[0] if isinstance(v, list) and v else None
T = {t['id']: t for t in X['templates']}
V = {v['id']: v for v in X['variants']}
v2t = {v['id']: m2o(v['product_tmpl_id']) for v in X['variants']}
ptav = {p['id']: p for p in X['ptav']}
lastprice = {m2o(g['product_id']): g.get('price_unit:max') or 0 for g in X['pol']}
hist = defaultdict(int)
for k in ('moves', 'pol', 'mr', 'bills'):
    for g in X[k]:
        hist[m2o(g['product_id'])] += g['__count']
CAT = {r['canonical_attribute'] for r in rd(W / 'data/attribute_catalogue.csv')} | {'Steps', 'Model', 'Power', 'Volume', 'Weight', 'Pack'}
NS = 'Not Specified'
attrs_of_t = defaultdict(set)
for l in X['lines']:
    attrs_of_t[m2o(l['product_tmpl_id'])].add(l['attribute_id'][1])

def vals_of(vid):
    out = {}
    for p in V[vid]['product_template_attribute_value_ids']:
        if p in ptav:
            a = ptav[p]['attribute_id'][1]; x = ptav[p]['product_attribute_value_id'][1]
            out[a] = x.split(': ', 1)[1] if x.startswith(a + ': ') else x
    return out
variants_of_t = defaultdict(list)
for v in X['variants']:
    variants_of_t[m2o(v['product_tmpl_id'])].append(v['id'])

def parse(s):
    out = {}
    for kv in (s or '').split(';'):
        if '=' in kv:
            a, v = kv.split('=', 1); out[a.strip()] = v.strip()
    return out

def _nums(s):
    s = re.sub(r'(\d)\.(\d+/\d+)', lambda m: m.group(1) + ' ' + m.group(2), s.lower())
    out = set()
    for a, b in re.findall(r'(\d+)\s*/\s*(\d+)', s):
        out.add(round(int(a) / int(b), 4))
    for x in re.findall(r'\d+(?:\.\d+)?', s):
        out.add(round(float(x), 4))
    return out

def written(name, val):
    if val == NS:
        return True
    nm_nums = _nums(name)
    v_nums = _nums(val)
    if v_nums:
        return v_nums <= nm_nums
    nm = set(re.findall(r'[a-z]+', normalise(name)))
    if {'gray', 'gary'} & nm: nm.add('grey')
    alpha = [k for k in re.findall(r'[a-z]+', normalise(val)) if len(k) > 2]
    return any(k in nm for k in alpha) if alpha else True

digits = lambda s: sorted(re.findall(r'\d+(?:\.\d+)?', re.sub(r'(\d)\.(\d+/\d+)', lambda m: m.group(1) + '-' + m.group(2), s.lower())))

rows = []
for p in sorted(W.glob('data/r4_out/batch_*.csv')):
    rows += rd(p)
held = []
def hold(r, why):
    held.append({'var_id': r.get('var_id'), 'name': T.get(int(float(r['tmpl_id'])), {}).get('name', '') if r.get('tmpl_id') else '', 'action': r.get('action'), 'why': why})

singles = {int(float(r['var_id'])) for r in rows}
parent = {}
def find(x):
    while parent.get(x, x) != x:
        x = parent[x]
    return x
def link(a, b):  # a merged into b
    parent[find(a)] = find(b)

renames, joins, news = {}, defaultdict(list), defaultdict(list)
ns_log = []
for r in rows:
    act = (r['action'] or '').strip().upper()[:1]
    act = {'J': 'JOIN', 'N': 'NEW', 'M': 'MERGE', 'K': 'KEEP'}.get(act, act)
    v = int(float(r['var_id'])); t = int(float(r['tmpl_id']))
    if v not in V:
        continue
    nm = T[t]['name']
    if act == 'KEEP':
        nn = (r.get('new_name') or '').strip()
        if nn and nn != nm and digits(nn) == digits(nm):
            renames[t] = nn
        continue
    if act == 'MERGE':
        try:
            d = int(float(r['dup_of']))
        except (ValueError, TypeError):
            hold(r, 'merge without dup_of'); continue
        if d not in V or d == v:
            hold(r, f'dup_of {d} unknown or itself'); continue
        ua, ub = unit_key(T[t]['x_unit']), unit_key(T[v2t[d]]['x_unit'])
        pa, pb = lastprice.get(v, 0), lastprice.get(d, 0)
        if ua != '?' and ub != '?' and ua != ub:
            hold(r, f'units differ {T[t]["x_unit"]} vs {T[v2t[d]]["x_unit"]}'); continue
        if pa and pb and max(pa, pb) / min(pa, pb) > 3:
            hold(r, f'last PO price {pa} vs {pb} (>3x)'); continue
        link(v, d); continue
    vals = parse(r.get('attributes'))
    if not vals or any(a not in CAT for a in vals):
        hold(r, f'attributes not usable: {list(vals)}'); continue
    for a, x in list(vals.items()):
        if not written(nm, x):
            ns_log.append({'var_id': v, 'name': nm, 'attribute': a, 'agent_value': x}); vals[a] = NS
    k = (r['template_key'] or '').strip()
    if act == 'JOIN' and k.startswith('T') and k[1:].isdigit() and int(k[1:]) in T:
        tt = int(k[1:])
        if set(vals) != attrs_of_t[tt]:
            hold(r, f'attributes {sorted(vals)} != template {sorted(attrs_of_t[tt])}'); continue
        joins[tt].append((v, vals))
    elif act in ('NEW', 'JOIN'):
        key = (re.sub(r'[^a-z0-9]', '', (r.get('template_name') or '').lower()), unit_key(T[t]['x_unit']))
        if not key[0]:
            hold(r, 'new template without name'); continue
        news[key].append((v, vals, (r.get('template_name') or '').strip()))
    else:
        hold(r, f'unknown action {act}')

# JOIN: an item whose combination equals an existing variant (or another joining item) is the same item -> merge
plan_var = []
for tt, items in joins.items():
    attrs = sorted(attrs_of_t[tt])
    exist = {tuple(vals_of(e).get(a) for a in attrs): e for e in variants_of_t[tt]}
    master = variants_of_t[tt][0]
    base = {'var': master, 'vals': [vals_of(master).get(a) for a in attrs]}
    new_items = []
    for v, vals in items:
        combo = tuple(vals[a] for a in attrs)
        if combo in exist:
            link(v, exist[combo]); continue
        exist[combo] = v
        new_items.append({'var': v, 'vals': list(combo)})
    if new_items:
        plan_var.append({'tk': f'T-{tt}', 'name': T[tt]['name'], 'attrs': attrs, 'master': master, 'items': [base] + new_items})
for key, items in news.items():
    attrs = sorted({a for _, vals, _ in items for a in vals})
    items.sort(key=lambda x: -hist[x[0]])
    seen, its = {}, []
    for v, vals, n in items:
        if set(vals) != set(attrs):
            hold({'var_id': v, 'tmpl_id': v2t[v], 'action': 'NEW'}, f'attribute set {sorted(vals)} differs from {attrs}'); continue
        combo = tuple(vals[a] for a in attrs)
        if combo in seen:
            link(v, seen[combo]); continue
        seen[combo] = v; its.append({'var': v, 'vals': list(combo)})
    if len(its) >= 2:
        plan_var.append({'tk': f'N-{key[0][:40]}-{key[1]}', 'name': items[0][2], 'attrs': attrs, 'master': its[0]['var'], 'items': its})
    else:
        for it in its:
            hold({'var_id': it['var'], 'tmpl_id': v2t[it['var']], 'action': 'NEW'}, 'new template would hold one item')

# merge groups from the union-find; master = the root (an existing variant or the target single)
groups = defaultdict(list)
for x in list(parent):
    r_ = find(x)
    if x != r_:
        groups[r_].append(x)
merged_away = {d for ds in groups.values() for d in ds}
plan_merge = [{'g': f'R4-{m}', 'master': m, 'dups': sorted(ds), 'rename': None} for m, ds in groups.items()]
# a merged-away item must not also be a variant item
for p in plan_var:
    p['items'] = [i for i in p['items'] if i['var'] not in merged_away or i['var'] == p['master']]
plan_var = [p for p in plan_var if len(p['items']) >= 2 and p['master'] not in merged_away]
renames = {t: n for t, n in renames.items() if T[t] and variants_of_t[t][0] not in merged_away}

json.dump(plan_merge, open(W / 'data/r4_merge.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(plan_var, open(W / 'data/r4_variants.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump([[t, {'name': n}] for t, n in renames.items()], open(W / 'data/r4_renames.json', 'w', encoding='utf-8'), ensure_ascii=False)
with open(W / 'data/r4_held.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['var_id', 'name', 'action', 'why']); w.writeheader(); w.writerows(held)
sep_bad = lambda s: any(c in (s or '') for c in '|~#^')
assert not any(sep_bad(p['name']) or any(sep_bad(x) for i in p['items'] for x in i['vals']) for p in plan_var), 'separator in variant plan'
open(W / 'data/r4_c_merge.txt', 'w', encoding='utf-8').write('~'.join(f"{p['g']}|{p['master']}|{','.join(map(str, p['dups']))}|" for p in plan_merge))
open(W / 'data/r4_c_variants.txt', 'w', encoding='utf-8').write('#'.join(f"{p['tk']}|{p['name']}|{'^'.join(p['attrs'])}|{p['master']}|" + '~'.join(f"{i['var']}^{'^'.join(i['vals'])}" for i in p['items']) for p in plan_var))
open(W / 'data/r4_c_renames.txt', 'w', encoding='utf-8').write('~'.join(f"{t}|{n}||" for t, n in renames.items() if not sep_bad(n)))
ck = lambda ids: (len(ids), sum(ids), functools.reduce(lambda a, b: a ^ b, ids, 0))
print('rows', len(rows), 'of', len(singles), '| actions', Counter((r['action'] or '').strip().upper()[:1] for r in rows))
print('merge groups', len(plan_merge), 'items merged', len(merged_away), 'CHECK', ck([p['master'] for p in plan_merge] + [d for p in plan_merge for d in p['dups']]))
print('variant templates', len(plan_var), '(existing', sum(p['tk'].startswith('T') for p in plan_var), ') items', sum(len(p['items']) for p in plan_var), 'CHECK', ck([i['var'] for p in plan_var for i in p['items']]))
print('renames', len(renames), 'CHECK', ck(list(renames)), '| held', len(held), Counter(h['why'].split(' ')[0] for h in held))
json.dump(ns_log, open(W / 'data/r4_ns_log.json', 'w', encoding='utf-8'), ensure_ascii=False)
print('agent values replaced by Not Specified', len(ns_log))
print('values Not Specified', sum(1 for p in plan_var for i in p['items'] for x in i['vals'] if x == NS))
