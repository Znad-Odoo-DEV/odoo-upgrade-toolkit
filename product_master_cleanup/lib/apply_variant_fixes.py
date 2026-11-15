"""Apply data/qa_variant_fixes.csv to data/plan_variants.json -> data/plan_variants_final.json (+ _variant_fixes_log.csv).
EXCLUDE: item leaves the template (stays a standalone product). MOVE: item joins template new_value (same attribute set, free
combination) else excluded. VALUE "Attr=value". RENAME_TEMPLATE. Then: combos unique per template, 2+ items, master = most history.
"""
import csv, json, sys
from pathlib import Path
W = Path(sys.argv[1])
P = {r['var_id']: r for r in csv.DictReader(open(W / 'data/products.csv', encoding='utf-8-sig'))}
hist = lambda v: float(P[str(v)]['history_score'] or 0) + (5 if float(P[str(v)]['qty_ssc'] or 0) or float(P[str(v)]['qty_mep'] or 0) else 0)
plan = {t['tk']: t for t in json.load(open(W / 'data/plan_variants.json', encoding='utf-8'))}
log = []
fx = list(csv.DictReader(open(W / 'data/qa_variant_fixes.csv', encoding='utf-8-sig')))
order = {'EXCLUDE': 0, 'VALUE': 1, 'MOVE': 2, 'RENAME_TEMPLATE': 3}
for f in sorted(fx, key=lambda f: order.get(f['action'].strip(), 9)):
    tk, act, nv = f['tk'].strip(), f['action'].strip(), f['new_value'].strip()
    t = plan.get(tk)
    if not t:
        log.append({**f, 'status': 'template not in plan'}); continue
    if act == 'RENAME_TEMPLATE':
        t['name'] = nv; log.append({**f, 'status': 'applied'}); continue
    v = int(float(f['var_id'])) if f['var_id'].strip() else None
    it = next((i for i in t['items'] if i['var'] == v), None)
    if not it:
        log.append({**f, 'status': 'item not in template'}); continue
    if act == 'EXCLUDE':
        t['items'].remove(it); log.append({**f, 'status': 'applied'})
    elif act == 'VALUE':
        a, val = nv.split('=', 1)
        if a.strip() in t['attrs']:
            it['vals'][t['attrs'].index(a.strip())] = val.strip(); log.append({**f, 'status': 'applied'})
        else:
            t['items'].remove(it); log.append({**f, 'status': f'attribute {a} not in template -> excluded'})
    elif act == 'MOVE':
        dst = plan.get(nv)
        t['items'].remove(it)
        if dst and dst['attrs'] == t['attrs'] and tuple(it['vals']) not in {tuple(i['vals']) for i in dst['items']}:
            dst['items'].append(it); log.append({**f, 'status': 'applied'})
        else:
            log.append({**f, 'status': 'moved target missing/different attributes/combination taken -> excluded'})
final = []
for t in plan.values():
    seen, items = set(), []
    for i in sorted(t['items'], key=lambda i: -hist(i['var'])):
        if tuple(i['vals']) in seen:
            log.append({'tk': t['tk'], 'var_id': i['var'], 'action': 'AUTO', 'status': 'same combination after fixes -> excluded'}); continue
        seen.add(tuple(i['vals'])); items.append(i)
    if len(items) < 2:
        continue
    t['items'] = items; t['master'] = items[0]['var']
    final.append(t)
json.dump(final, open(W / 'data/plan_variants_final.json', 'w', encoding='utf-8'), ensure_ascii=False)
with open(W / 'data/_variant_fixes_log.csv', 'w', newline='', encoding='utf-8-sig') as f:
    cols = list(dict.fromkeys(k for r in log for k in r)); w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(log)
from collections import Counter
print('templates', len(final), 'items', sum(len(t['items']) for t in final), '| fixes', Counter(l['status'].split(' ')[0] for l in log))
