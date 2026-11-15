"""Round 5 inputs: every single item that round 4 kept, held or QA-dropped, plus the variant templates after round 4.
Usage: python -I lib/r5_prep.py <work_dir> [batches]
Writes data/r5_in/batch_<N>.csv and data/r5_in/templates.txt.
"""
import csv, glob, json, re, sys
from collections import defaultdict
from pathlib import Path

W = Path(sys.argv[1]); NB = int(sys.argv[2]) if len(sys.argv) > 2 else 12
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
X = json.load(open(W / 'data/r4_extract.json', encoding='utf-8'))
m2o = lambda v: v[0] if isinstance(v, list) and v else None
v2t = {v['id']: m2o(v['product_tmpl_id']) for v in X['variants']}
src = {}
for p in sorted(glob.glob(str(W / 'data/r4_in/batch_*.csv'))):
    for r in rd(p):
        src[int(float(r['var_id']))] = r
out = {}
for p in sorted(glob.glob(str(W / 'data/r4_out/batch_*.csv'))):
    for r in rd(p):
        out[int(float(r['var_id']))] = r
held = {int(float(r['var_id'])): r['why'] for r in rd(W / 'data/r4_held.csv') if r['var_id']}
M = json.load(open(W / 'data/r4_final_merge.json', encoding='utf-8'))
V = json.load(open(W / 'data/r4_final_variants.json', encoding='utf-8'))
M0 = json.load(open(W / 'data/r4_merge.json', encoding='utf-8'))
V0 = json.load(open(W / 'data/r4_variants.json', encoding='utf-8'))
done = {d for p in M for d in [p['master']] + p['dups']} | {i['var'] for p in V for i in p['items']}
qa = {}
for d in rd(W / 'data/r4_qa_variant_drop.csv'):
    tk, it = d['tk'].strip(), d['item'].strip()
    for p in V0:
        if p['tk'] == tk:
            for i in p['items']:
                if not it or int(float(it)) == i['var']:
                    qa[i['var']] = 'QA dropped from ' + p['name'] + ': ' + d['reason']
for d in rd(W / 'data/r4_qa_merge_drop.csv'):
    for p in M0:
        if p['g'] == d['g'].strip():
            for i in [p['master']] + p['dups']:
                if not d['item'].strip() or int(float(d['item'])) == i:
                    qa.setdefault(i, 'QA dropped merge: ' + d['reason'])

items = []
for v, r in src.items():
    if v in done:
        continue
    o = out.get(v, {})
    prior = qa.get(v) or ('held: ' + held[v] if v in held else 'round 4 kept it: ' + (o.get('reason') or ''))
    items.append({**{k: r[k] for k in ('tmpl_id', 'var_id', 'name', 'default_code', 'category', 'x_unit', 'unit_key', 'qty', 'history', 'last_po_price')}, 'prior': prior[:160]})

def family(n):
    w = [x for x in re.findall(r'[a-z]+', n.lower()) if len(x) > 2 and x not in {'pvc', 'upvc', 'with', 'and', 'for', 'the'}]
    return ' '.join(w[:2])
items.sort(key=lambda r: (family(r['name']), r['name'].lower()))
(W / 'data/r5_in').mkdir(exist_ok=True)
size = -(-len(items) // NB)
for k in range(NB):
    part = items[k * size:(k + 1) * size]
    if not part:
        continue
    with open(W / f'data/r5_in/batch_{k + 1}.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(part[0])); w.writeheader(); w.writerows(part)

# variant templates after round 4: T<tmpl_id> | name | unit | attrs | var=val/val; ...
tm = {}
for r in rd(W / 'data/r4_in/existing_variant_templates.csv'):
    t = int(r['tmpl_id'])
    e = tm.setdefault(t, {'name': r['template_name'], 'unit': r['x_unit'], 'attrs': r['attributes'].replace(' | ', ', '), 'vars': []})
    vals = '/'.join(x.split('=', 1)[1].strip() for x in r['variant_values'].split(';') if '=' in x)
    e['vars'].append(f"{r['variant_id']}={vals}")
for p in V:
    t = int(p['tk'][2:]) if p['tk'].startswith('T-') else v2t[p['master']]
    e = tm.setdefault(t, {'name': p['name'], 'unit': src.get(p['master'], {}).get('x_unit', ''), 'attrs': ', '.join(p['attrs']), 'vars': []})
    e['name'] = p['name']
    have = {x.split('=')[0] for x in e['vars']}
    for i in p['items']:
        if str(i['var']) not in have:
            e['vars'].append(f"{i['var']}={'/'.join(i['vals'])}")
with open(W / 'data/r5_in/templates.txt', 'w', encoding='utf-8') as f:
    f.write('# T<tmpl_id> | template name | unit | attributes (order of the values) | variant_id=values; ...\n')
    for t, e in sorted(tm.items(), key=lambda x: x[1]['name'].lower()):
        f.write(f"T{t} | {e['name']} | {e['unit']} | {e['attrs']} | {'; '.join(e['vars'])}\n")
print('items', len(items), 'batches', NB, 'size', size, 'templates', len(tm),
      'qa', sum(1 for i in items if i['prior'].startswith('QA')), 'held', sum(1 for i in items if i['prior'].startswith('held')))
