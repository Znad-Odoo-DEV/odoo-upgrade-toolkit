"""Build the executable duplicate-merge plan from the reviewed files, with the senior guards of DECISIONS.md.
Usage: python -I lib/build_plan.py <work_dir> [review_dir=review_final]
Outputs: data/plan_merge.json (list of {g, master, dups, rename, cls}), data/plan_excluded.csv (why a row was held back),
reports/zero_cost_for_accountant.csv.
"""
import csv, json, re, sys
from collections import defaultdict
from pathlib import Path

W = Path(sys.argv[1])
REV = sys.argv[2] if len(sys.argv) > 2 else 'review_final'
sys.path.insert(0, str(W / 'lib'))
from units import unit_key  # noqa: E402

rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
P = {r['var_id']: r for r in rd(W / 'data/products.csv')}
num = lambda x: 0.0 if x in ('', 'False', None) else float(x)
digits = lambda s: set(re.findall(r'\d+(?:\.\d+)?', (s or '').lower()))

groups = defaultdict(list)
for g in ('MEP', 'CIVIL', 'GENERAL'):
    for r in rd(W / f'data/{REV}/dup_{g}.csv'):
        if r['decision'] in ('MASTER', 'MERGE'):
            groups[r['group_key']].append(r)

plan, excluded, zero = [], [], []
for gk, rr in sorted(groups.items()):
    masters = [r for r in rr if r['decision'] == 'MASTER']
    if len(masters) != 1:
        excluded += [{'group': gk, 'var_id': r['var_id'], 'why': f'{len(masters)} masters'} for r in rr]; continue
    m = masters[0]['var_id']; M = P[m]
    dups = []
    for r in rr:
        v = r['var_id']
        if v == m:
            continue
        D = P[v]
        ku, km = unit_key(D['x_unit']), unit_key(M['x_unit'])
        why = None
        if ku != '?' and km != '?' and ku != km:
            why = f'unit {D["x_unit"]} vs {M["x_unit"]}'
        pa, pb = num(D['last_po_price']), num(M['last_po_price'])
        if not why and pa > 0 and pb > 0 and max(pa, pb) / min(pa, pb) > 3:
            why = f'last PO price {pa} vs {pb} (>3x)'
        for c in ('ssc', 'mep'):
            ca, cb = num(D[f'cost_{c}']), num(M[f'cost_{c}'])
            if not why and ca > 0 and cb > 0 and max(ca, cb) / min(ca, cb) > 3:
                why = f'cost {c} {ca} vs {cb} (>3x)'
        if why:
            excluded.append({'group': gk, 'var_id': v, 'name': D['name'], 'master': m, 'master_name': M['name'], 'why': why})
        else:
            dups.append(int(v))
    if not dups:
        continue
    rename = masters[0].get('new_name') or None
    if rename and not digits(M['name']) <= digits(rename):
        excluded.append({'group': gk, 'var_id': m, 'name': M['name'], 'why': f'rename dropped (numbers lost): {rename}'}); rename = None
    cls = 'A' if all(r['class'] == 'A' for r in rr if r['decision'] == 'MERGE') else 'B'
    plan.append({'g': gk, 'master': int(m), 'dups': dups, 'rename': rename, 'cls': cls,
                 'stock': any(num(P[str(x)]['qty_ssc']) or num(P[str(x)]['qty_mep']) for x in [int(m)] + dups)})
    for c in ('ssc', 'mep'):
        members = [int(m)] + dups
        known = [num(P[str(x)][f'cost_{c}']) for x in members if num(P[str(x)][f'cost_{c}']) > 0]
        zq = sum(num(P[str(x)][f'qty_{c}']) for x in members if num(P[str(x)][f'cost_{c}']) == 0 and num(P[str(x)][f'qty_{c}']) > 0)
        if known and zq:
            zero.append({'group': gk, 'company': c, 'master': m, 'master_name': M['name'], 'qty_at_zero_cost': zq,
                         'known_cost_min': min(known), 'known_cost_max': max(known), 'value_if_priced_at_min': round(zq * min(known), 2)})

# order: class A without stock, class B without stock, then with stock (one company), then both
plan.sort(key=lambda p: (p['cls'] != 'A', p['stock'], p['g']))
json.dump(plan, open(W / 'data/plan_merge.json', 'w', encoding='utf-8'), ensure_ascii=False)
def out(path, rows):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        cols = list(dict.fromkeys(k for r in rows for k in r)) or ['none']
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
out(W / 'data/plan_excluded.csv', excluded)
out(W / 'reports/zero_cost_for_accountant.csv', zero)
print('groups', len(plan), 'items archived', sum(len(p['dups']) for p in plan), 'class A', sum(p['cls'] == 'A' for p in plan),
      'with stock', sum(p['stock'] for p in plan), 'renames', sum(bool(p['rename']) for p in plan))
print('excluded rows', len(excluded), '| zero-cost lines for accountant', len(zero), 'value if priced',
      round(sum(z['value_if_priced_at_min'] for z in zero), 2))
