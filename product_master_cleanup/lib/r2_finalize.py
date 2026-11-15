"""Apply round-2 QA (data/r2_qa_drop.csv, data/r2_qa_updates.csv) to the plans; write final JSON + compact paste files.
Usage: python -I lib/r2_finalize.py <work_dir>
Compact formats (fields never contain the separators; checked):
  merges   g|master|dup,dup|rename            joined by '~'
  variants tk|name|attr^attr|master|var^v^v~var^v^v   joined by '#'
  updates  tmpl|name|categ_id|x_unit          joined by '~'   (empty field = no change)
  garbage  tmpl,tmpl
"""
import csv, json, re, sys, functools
from collections import Counter
from pathlib import Path

W = Path(sys.argv[1])
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig'))) if Path(p).exists() else []
M = json.load(open(W / 'data/r2_plan_merge.json', encoding='utf-8'))
V = json.load(open(W / 'data/r2_plan_variants.json', encoding='utf-8'))
U = {t: u for t, u in json.load(open(W / 'data/r2_plan_updates.json', encoding='utf-8'))}
G = json.load(open(W / 'data/r2_plan_garbage.json', encoding='utf-8'))
X = json.load(open(W / 'data/r2_extract.json', encoding='utf-8'))
v2t = {v['id']: v['product_tmpl_id'][0] for v in X['variants']}
tname = {t['id']: t['name'] for t in X['templates']}
digits = lambda s: set(re.findall(r'\d+(?:\.\d+)?', (s or '').lower()))
log = Counter()

for d in rd(W / 'data/r2_qa_drop.csv'):
    plan, key, item = d['plan'].strip(), d['key'].strip(), d['item'].strip()
    it = int(float(item)) if item else None
    if plan == 'merge':
        for p in M:
            if p['g'] == key or (not key and it in p['dups']):
                if it and it in p['dups']: p['dups'].remove(it); log['merge item dropped'] += 1
                elif it == p['master'] or not it: p['dups'] = []; log['merge group dropped'] += 1
    elif plan == 'variant':
        for p in V:
            if p['tk'] == key:
                if it is None:
                    p['items'] = []; log['variant template dropped'] += 1
                else:
                    gone = [i for i in p['items'] if i['var'] == it]
                    for i in gone:
                        p['items'].remove(i); log['variant item dropped'] += 1
                        t = v2t.get(it)
                        nn = f"{p['name']} {' '.join(i['vals'])}".strip()
                        if t and digits(tname.get(t, '')) <= digits(nn) and t not in U:
                            U[t] = {'name': nn}
    elif plan == 'garbage' and it in G:
        G.remove(it); log['garbage dropped'] += 1
M = [p for p in M if p['dups']]
VV = []
for p in V:
    is_t = p['tk'].startswith('T')
    if is_t:
        if p['items'] and p['items'][0]['var'] == p['master'] and len(p['items']) > 1:
            VV.append(p)
    else:
        if len(p['items']) >= 2:
            if p['master'] not in [i['var'] for i in p['items']]:
                p['master'] = p['items'][0]['var']
            VV.append(p)
for q in rd(W / 'data/r2_qa_updates.csv'):
    t = int(float(q['tmpl_id'])); f = q['field'].strip(); a = q['action'].strip().upper()
    if t not in U:
        continue
    if a == 'DROP':
        U[t].pop(f, None); log[f'update {f} dropped'] += 1
    elif a == 'FIX' and q['new_value'].strip():
        U[t][f] = int(float(q['new_value'])) if f == 'categ_id' else q['new_value'].strip(); log[f'update {f} fixed'] += 1
NOISE = {'mm', 'in', 'deg', 'cm', 'grey', 'gray', 'orange', 'black', 'white', 'red', 'blue', 'yellow', 'green', 'brown', 'silver',
         'beige', 'nos', 'pcs', 'mtr', 'with', 'and', 'for', 'per', 'the', 'type', 'size', 'x'}
def has_item_word(n):
    return any(len(w) >= 3 and w not in NOISE for w in re.findall(r'[a-z]+', (n or '').lower()) if not re.search(r'\d', w))
for t, u in U.items():
    if 'name' in u and not has_item_word(u['name']):
        u.pop('name'); log['update name dropped (no item word)'] += 1
UU = [[t, u] for t, u in U.items() if u]

for name, obj in (('r2_final_merge.json', M), ('r2_final_variants.json', VV), ('r2_final_updates.json', UU), ('r2_final_garbage.json', G)):
    json.dump(obj, open(W / 'data' / name, 'w', encoding='utf-8'), ensure_ascii=False)
bad = lambda s, seps: any(c in (s or '') for c in seps)
assert not any(bad(p.get('rename'), '|~') for p in M)
assert not any(bad(p['name'], '|#^~') or any(bad(v, '|#^~') for i in p['items'] for v in i['vals']) for p in VV)
assert not any(bad(u.get('name'), '|~') or bad(u.get('x_unit'), '|~') for _, u in UU)
cm = '~'.join(f"{p['g']}|{p['master']}|{','.join(map(str, p['dups']))}|{p.get('rename') or ''}" for p in M)
cv = '#'.join(f"{p['tk']}|{p['name']}|{'^'.join(p['attrs'])}|{p['master']}|" + '~'.join(f"{i['var']}^{'^'.join(i['vals'])}" for i in p['items']) for p in VV)
cu = '~'.join(f"{t}|{u.get('name', '')}|{u.get('categ_id', '')}|{u.get('x_unit', '')}" for t, u in UU)
for n, s in (('r2_c_merge.txt', cm), ('r2_c_variants.txt', cv), ('r2_c_updates.txt', cu), ('r2_c_garbage.txt', ','.join(map(str, G)))):
    open(W / 'data' / n, 'w', encoding='utf-8').write(s)
ck = lambda ids: (len(ids), sum(ids), functools.reduce(lambda a, b: a ^ b, ids, 0))
print('QA applied', dict(log))
print('merges', len(M), 'CHECK', ck([p['master'] for p in M] + [d for p in M for d in p['dups']]))
print('variants', len(VV), 'items', sum(len(p['items']) for p in VV), 'CHECK', ck([i['var'] for p in VV for i in p['items']]))
print('updates', len(UU), Counter(k for _, u in UU for k in u), 'CHECK', ck([t for t, _ in UU]))
print('garbage', len(G), 'sizes', len(cm), len(cv), len(cu))
