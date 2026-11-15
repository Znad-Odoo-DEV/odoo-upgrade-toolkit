"""First-pass duplicate clusters + variant families (deterministic, no judgement). Review agents decide after this.
Usage: python -I lib/cluster_pass.py <work_dir>
Edges (union-find): exact normalised name | same default_code (purchasing verdict SAME_ITEM/UNSURE) |
studio_item_mismatch SAME_ITEM | fuzzy >= FUZZ within a block of equal spec_key + unit.
Unit gate (the client 2026-11-14): both units known and different -> edge dropped (logged as unit_conflict).
One side unknown ('?') -> edge kept, cluster flagged unit_unknown (store team confirms the unit).
"""
import csv, sys, time
from collections import defaultdict, Counter
from pathlib import Path

W = Path(sys.argv[1])
sys.path.insert(0, str(W / 'lib'))
from dedup_lib import normalise, base_name, spec_key, similarity, extract_specs  # noqa: E402
from units import unit_key  # noqa: E402

FUZZ = 90
MEP = {'AUTOMATION SYSTEM', 'CCTV & Security System', 'Drainage System Items', 'Electrical Conduits & Wirings', 'Firefighting System & Materials',
       'HVAC Ducts', 'HVAC System', 'IT Works', 'LV System', 'Lift System', 'Light Fitting', 'Misc. MEP', 'Plumbing Pipes',
       'Power Sockets & Fittings', 'Sanitary Wares & Fittings', 'Sewage Water', 'Sweet Water'}
GENERAL = {'All', 'Misc. Items', 'Hand Tools', 'Power Tool', 'Consumable Tools & Equipments', 'P.P.E', 'Office & Pantry Supplies',
           'Heavy Equipements Rental', 'Heavy Machinery', 'Tower Crane', 'Cargo Transport', 'Excavation Works', 'Infrastructure Works',
           'Materials Testing', 'Waste Water & Rubbish Removal', "Vehicles' Expenses", 'Diesel/Petrol', 'All / Expenses',
           'All / Saleable / Booking Fees', 'General Payment (only for Petty Cash)', 'Pest Control', 'Repair & Maintenance Expenses'}
GENERIC_CATS = {'All', 'Misc. Items', 'All / Expenses'}
group_of = lambda cat: 'MEP' if cat in MEP else ('GENERAL' if cat in GENERAL else 'CIVIL')

P = list(csv.DictReader(open(W / 'data/products.csv', encoding='utf-8-sig')))
by = {int(r['var_id']): r for r in P}
for r in P:
    r['_norm'] = normalise(r['name'])
    r['_base'] = base_name(r['name'])
    r['_spec'] = spec_key(r['name'])
    r['_unit'] = unit_key(r['x_unit'])

parent = {v: v for v in by}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
edges = defaultdict(set)      # (a,b) -> evidence
conflicts = []

import re as _re
def _toks(r):
    t = set(r['_norm'].split())
    return {x for x in t if _re.search(r'\d', x)}, {x for x in t if not _re.search(r'\d', x)}
rejected = []
def gate(a, b, max_word_diff):
    da, wa = _toks(by[a]); db, wb = _toks(by[b])
    return da == db and len(wa ^ wb) <= max_word_diff

def edge(a, b, ev, score=100):
    if a == b or a not in by or b not in by:
        return
    if ev != 'exact_name' and not gate(a, b, 1 if ev == 'fuzzy' else 2):
        if ev != 'fuzzy':
            rejected.append({'var_a': a, 'var_b': b, 'evidence': ev, 'name_a': by[a]['name'], 'name_b': by[b]['name']})
        return
    ua, ub = by[a]['_unit'], by[b]['_unit']
    if ua != '?' and ub != '?' and ua != ub:
        conflicts.append({'var_a': a, 'var_b': b, 'evidence': ev, 'unit_a': by[a]['x_unit'], 'unit_b': by[b]['x_unit'],
                          'name_a': by[a]['name'], 'name_b': by[b]['name']})
        return
    k = (min(a, b), max(a, b))
    edges[k].add(f'{ev}:{round(score)}' if ev == 'fuzzy' else ev)
    parent[find(a)] = find(b)

t0 = time.time()
# L1 exact normalised name
idx = defaultdict(list)
for r in P:
    if r['_norm']:
        idx[r['_norm']].append(int(r['var_id']))
for ids in idx.values():
    for b in ids[1:]:
        edge(ids[0], b, 'exact_name')
# L2 / L4 purchasing evidence
for e in csv.DictReader(open(W / 'data/dup_evidence_purchasing.csv', encoding='utf-8-sig')):
    a, b = int(float(e['var_a'])), int(float(e['var_b']))
    if e['evidence'] == 'same_code' and e['verdict'] in ('SAME_ITEM', 'UNSURE'):
        # UNSURE same-code pairs only join when the specs are equal (otherwise they are variant candidates)
        if e['verdict'] == 'SAME_ITEM' or by.get(a, {}).get('_spec') == by.get(b, {}).get('_spec'):
            edge(a, b, 'same_code')
    elif e['evidence'] == 'studio_item_mismatch' and e['verdict'] == 'SAME_ITEM':
        edge(a, b, 'studio_item')
# L3 fuzzy within block (spec_key + unit); unknown unit compared inside each spec block too
blocks = defaultdict(list)
for r in P:
    blocks[r['_spec']].append(r)
pairs = 0
for spec, rows in blocks.items():
    n = len(rows)
    for i in range(n):
        a = rows[i]
        for j in range(i + 1, n):
            b = rows[j]
            if a['_unit'] != b['_unit'] and '?' not in (a['_unit'], b['_unit']):
                continue
            if not a['_base'] or not b['_base']:
                continue
            la, lb = len(a['_norm']), len(b['_norm'])
            if min(la, lb) / max(la, lb) < 0.6:
                continue
            pairs += 1
            s = similarity(a['_norm'], b['_norm'])
            if s >= FUZZ:
                edge(int(a['var_id']), int(b['var_id']), 'fuzzy', s)
print(f'fuzzy pairs compared {pairs} in {time.time() - t0:.0f}s')

clusters = defaultdict(list)
for v in by:
    clusters[find(v)].append(v)
clusters = [sorted(m) for m in clusters.values() if len(m) > 1]

def master_key(r):
    stock = float(r['qty_ssc']) + float(r['qty_mep'])
    return (r['_unit'] != '?', float(r['history_score']) + (5 if stock else 0), r['category'] not in GENERIC_CATS,
            bool(r['default_code']), -int(r['var_id']))

rows = []
for n, mem in enumerate(sorted(clusters, key=lambda m: -len(m)), 1):
    rr = [by[v] for v in mem]
    master = max(rr, key=master_key)
    cats = Counter(r['category'] for r in rr if r['category'] not in GENERIC_CATS) or Counter(r['category'] for r in rr)
    grp = group_of(cats.most_common(1)[0][0])
    flags = []
    if any(r['_unit'] == '?' for r in rr):
        flags.append('unit_unknown')
    if len({r['_spec'] for r in rr}) > 1:
        flags.append('spec_differs')
    if sum(1 for r in rr if float(r['qty_ssc']) or float(r['qty_mep'])) > 1:
        flags.append('stock_on_several')
    for r in rr:
        ev = sorted({e for (a, b), es in edges.items() if int(r['var_id']) in (a, b) for e in es})
        rows.append({'cluster_id': f'D{n:04d}', 'group': grp, 'size': len(mem), 'suggested_master': master['var_id'],
                     'is_master': int(r is master), 'var_id': r['var_id'], 'tmpl_id': r['tmpl_id'], 'name': r['name'],
                     'default_code': r['default_code'], 'category': r['category'], 'x_unit': r['x_unit'], 'unit_key': r['_unit'],
                     'spec_key': r['_spec'], 'evidence': ' '.join(ev), 'flags': ' '.join(flags), 'history_score': r['history_score'],
                     'qty_ssc': r['qty_ssc'], 'qty_mep': r['qty_mep'], 'cost_ssc': r['cost_ssc'], 'cost_mep': r['cost_mep'],
                     'moves_done': r['moves_done'], 'po_lines': r['po_lines'], 'po_open_lines': r['po_open_lines'],
                     'bill_lines_posted': r['bill_lines_posted'], 'mr_lines': r['mr_lines'], 'vendor_prices': r['vendor_prices'],
                     'moves_analysis_rows': r['moves_analysis_rows'], 'create_date': r['create_date']})
def write(name, data):
    with open(W / 'data' / name, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)
    print(name, len(data))
write('clusters_pass1.csv', rows)
write('unit_conflicts.csv', conflicts)
write('evidence_rejected.csv', rejected)

# Variant families: same base name + unit, 2+ different spec keys, spec not empty
in_dup = {int(r['var_id']) for r in rows}
fam = defaultdict(list)
for r in P:
    if r['_base'] and r['_spec']:
        fam[(r['_base'], r['_unit'])].append(r)
frows = []
n = 0
for (base, unit), rr in sorted(fam.items(), key=lambda kv: -len(kv[1])):
    if len({r['_spec'] for r in rr}) < 2:
        continue
    n += 1
    cats = Counter(r['category'] for r in rr if r['category'] not in GENERIC_CATS) or Counter(r['category'] for r in rr)
    for r in rr:
        frows.append({'family_id': f'F{n:04d}', 'group': group_of(cats.most_common(1)[0][0]), 'base_name': base, 'unit_key': unit,
                      'size': len(rr), 'var_id': r['var_id'], 'name': r['name'], 'default_code': r['default_code'], 'category': r['category'],
                      'specs': ' '.join(f'{k}={v}' for k, v in sorted(extract_specs(r['name']).items())), 'in_dup_cluster': int(int(r['var_id']) in in_dup),
                      'history_score': r['history_score'], 'qty_ssc': r['qty_ssc'], 'qty_mep': r['qty_mep']})
write('families_pass1.csv', frows)
c = Counter((r['group']) for r in rows if r['is_master'])
print('dup clusters per group', dict(c), '| members', len(rows), '| families', n, 'members', len(frows))
print('flags', Counter(f for r in rows if r['is_master'] for f in r['flags'].split()))
