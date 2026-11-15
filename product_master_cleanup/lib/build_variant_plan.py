"""Variant plan (class C) from the harmonised targets, after the QA decisions and the duplicate merges.
Usage: python -I lib/build_variant_plan.py <work_dir>
Rules (DECISIONS.md 3): a variant conversion never merges two items. Items merged away as duplicates are represented by
their master. Two remaining items on the same combination: the one with more history becomes the variant, the other stays
a standalone product (question list). A template needs 2+ items. The template master = the item with the most history.
Outputs: data/plan_variants.json, data/plan_variants_skipped.csv, data/plan_attributes.json (attributes and values used).
"""
import csv, json, sys
from collections import defaultdict, Counter
from pathlib import Path

W = Path(sys.argv[1])
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
P = {r['var_id']: r for r in rd(W / 'data/products.csv')}
hist = lambda v: float(P[v]['history_score'] or 0) + (5 if float(P[v]['qty_ssc'] or 0) or float(P[v]['qty_mep'] or 0) else 0)

qa_decision = {}
for g in ('MEP', 'CIVIL', 'GENERAL'):
    for r in rd(W / f'data/review_final/fam_{g}.csv'):
        qa_decision[r['var_id']] = r['decision']
merged_into = {}
for p in json.load(open(W / 'data/plan_merge.json', encoding='utf-8')):
    for d in p['dups']:
        merged_into[str(d)] = str(p['master'])
cat = {r['canonical_attribute']: r for r in rd(W / 'data/attribute_catalogue.csv')}
seq = {a: int(float(r['sequence'] or 0)) for a, r in cat.items()}

T = defaultdict(list)
skipped = []
for r in rd(W / 'data/variant_targets.csv'):
    v = r['var_id']
    if qa_decision.get(v) != 'VARIANT':
        skipped.append({'var_id': v, 'template': r['canonical_template_key'], 'why': f'QA decision {qa_decision.get(v)}'}); continue
    if v in merged_into:
        skipped.append({'var_id': v, 'template': r['canonical_template_key'], 'why': f'merged as duplicate into {merged_into[v]}'}); continue
    vals = {}
    for kv in r['canonical_attributes'].split(';'):
        if '=' in kv:
            a, val = kv.split('=', 1)
            vals[a.strip()] = val.strip()
    T[(r['canonical_template_key'], r['canonical_template_name'])].append((v, vals))

plan, attrs_used = [], defaultdict(set)
for (tk, tname), items in sorted(T.items()):
    # all items of a template must carry the same attribute set
    keys = Counter(tuple(sorted(vals)) for _, vals in items)
    main_keys = keys.most_common(1)[0][0]
    ok = []
    for v, vals in items:
        if tuple(sorted(vals)) != main_keys or not vals:
            skipped.append({'var_id': v, 'template': tk, 'why': f'attribute set {sorted(vals)} differs from {list(main_keys)}'})
        else:
            ok.append((v, vals))
    by_combo = defaultdict(list)
    for v, vals in ok:
        by_combo[tuple(vals[a] for a in main_keys)].append(v)
    final = []
    for combo, vs in by_combo.items():
        vs.sort(key=lambda x: -hist(x))
        final.append((vs[0], dict(zip(main_keys, combo))))
        for o in vs[1:]:
            skipped.append({'var_id': o, 'template': tk, 'why': f'same combination as {vs[0]} (stays standalone, question)'})
    if len(final) < 2:
        for v, _ in final:
            skipped.append({'var_id': v, 'template': tk, 'why': 'template would hold one item'})
        continue
    units = {P[v]['x_unit'].strip().lower() for v, _ in final if P[v]['x_unit'].strip()}
    master = max(final, key=lambda x: hist(x[0]))[0]
    order = sorted(main_keys, key=lambda a: seq.get(a, 999))
    for v, vals in final:
        for a in order:
            attrs_used[a].add(vals[a])
    plan.append({'tk': tk, 'name': tname, 'master': int(master), 'attrs': order, 'units': sorted(units),
                 'items': [{'var': int(v), 'vals': [vals[a] for a in order]} for v, vals in sorted(final, key=lambda x: x[0] != master)]})

json.dump(plan, open(W / 'data/plan_variants.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump({a: sorted(vs) for a, vs in attrs_used.items()}, open(W / 'data/plan_attributes.json', 'w', encoding='utf-8'), ensure_ascii=False)
with open(W / 'data/plan_variants_skipped.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['var_id', 'template', 'why']); w.writeheader(); w.writerows(skipped)
multi_unit = [p['tk'] for p in plan if len({u.rstrip('.').rstrip('s') for u in p['units']}) > 1]
print('templates', len(plan), 'items becoming variants', sum(len(p['items']) for p in plan),
      '(of which masters', len(plan), ') | skipped', len(skipped), Counter(s['why'].split(' ')[0] for s in skipped))
print('attributes', len(attrs_used), {a: len(v) for a, v in attrs_used.items()})
print('templates whose items show different unit spellings (check):', len(multi_unit), multi_unit[:10])
