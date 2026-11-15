"""Round 7 inputs: every active template of dev_0 (data/r7_extract.json), grouped by item type so a whole family lands in one batch.
Usage: python -I lib/r7_prep.py <work_dir> [batches]
Writes data/r7_in/batch_<N>.txt (one template per line) and data/r7_in/categories.txt.
Line: T<id> | name | unit | category | attributes | variant_id=code=values=qty ; ...
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

W = Path(sys.argv[1]); NB = int(sys.argv[2]) if len(sys.argv) > 2 else 8
X = json.load(open(W / 'data/r7_extract.json', encoding='utf-8'))
m2o = lambda v: v[0] if isinstance(v, list) and v else None
cats = {c['id']: c['complete_name'] for c in X['categories']}
ptav = {p['id']: (p['attribute_id'][1], p['name']) for p in X['ptav']}
qty = {m2o(g['product_id']): round(g['quantity:sum'], 2) for g in X['qty']}
lines = defaultdict(list)
for l in X['lines']:
    lines[m2o(l['product_tmpl_id'])].append(l['attribute_id'][1])
vars_ = defaultdict(list)
for v in X['variants']:
    vals = ', '.join(sorted(f'{a}:{n}' for a, n in (ptav[i] for i in v['product_template_attribute_value_ids'] if i in ptav)))
    vars_[m2o(v['product_tmpl_id'])].append(f"{v['id']}={v['default_code'] or ''}={vals}={qty.get(v['id'], 0)}")
DROP = {'ppr', 'upvc', 'pvc', 'hp', 'gi', 'ms', 'ss', 'hdpe', 'pex', 'cpvc', 'brass', 'copper', 'skolon', 'soundproof', 'drainage',
        'grey', 'gray', 'orange', 'black', 'white', 'red', 'blue', 'yellow', 'green', 'silver', 'rr', 'sch', 'each', 'box', 'roll',
        'packet', 'per', 'metre', 'length', 'with', 'and', 'for', 'the', 'of', 'mute', 'heavy', 'duty', 'electrical', 'ele', 'pressure',
        'high', 'fire', 'fighting', 'mm', 'in', 'cm', 'm', 'x', 'nos', 'pcs'}


def key(name):
    w = [x for x in re.findall(r'[a-z]+', name.lower()) if x not in DROP and len(x) > 1]
    return ' '.join(sorted(w[:2])) if w else name.lower()


rows = []
for t in X['templates']:
    rows.append((key(t['name']), t['name'].lower(),
                 f"T{t['id']} | {t['name']} | {t['x_unit'] or ''} | {cats.get(m2o(t['categ_id']), '')} | {', '.join(lines.get(t['id'], []))} | " + ' ; '.join(vars_.get(t['id'], []))))
groups = defaultdict(list)
for k, n, line in rows:
    groups[k].append((n, line))
order = sorted(groups, key=lambda k: k)
target = -(-len(rows) // NB)
batches, cur = [], []
for k in order:
    g = sorted(groups[k])
    if cur and len(cur) + len(g) > target * 1.15:
        batches.append(cur); cur = []
    cur += [line for _, line in g]
if cur:
    batches.append(cur)
(W / 'data/r7_in').mkdir(exist_ok=True)
for i, b in enumerate(batches, 1):
    (W / f'data/r7_in/batch_{i}.txt').write_text('\n'.join(b) + '\n', encoding='utf-8')
(W / 'data/r7_in/categories.txt').write_text('\n'.join(sorted(set(cats.values()))) + '\n', encoding='utf-8')
print('templates', len(rows), 'groups', len(groups), 'batches', [len(b) for b in batches])
