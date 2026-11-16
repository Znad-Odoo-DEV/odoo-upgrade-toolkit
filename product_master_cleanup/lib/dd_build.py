"""Deep duplicate study, step 1: one summary row per active template + a wide fuzzy net of candidate pairs.
Input: data/dd/main_tmpl_t.json, main_tmpl_v.json, use_*.json (read-only extract of main, 2026-11-16).
Out: data/dd/templates.tsv, data/dd/fuzzy_pairs.tsv.  Usage: python -I lib/dd_build.py <work_dir>"""
import json, re, sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

W = Path(sys.argv[1]); D = W / 'data' / 'dd'
T = json.loads((D / 'main_tmpl_t.json').read_text(encoding='utf-8')).split('\n')
V = json.loads((D / 'main_tmpl_v.json').read_text(encoding='utf-8')).split('\n')
use = {k: json.loads((D / f'use_{k}.json').read_text()) for k in ('quant', 'pol', 'move', 'mr')}
v2t, attrs = {}, defaultdict(lambda: defaultdict(set))
for line in V:
    vid, tid, code, vals = line.split('|', 3)
    v2t[int(vid)] = int(tid)
    for pair in filter(None, vals.split(';')):
        a, _, v = pair.partition(':'); attrs[int(tid)][a.strip()].add(v.strip())
u = defaultdict(lambda: [0.0, 0.0, 0, 0, 0])
for pid, q, val in use['quant']:
    if pid in v2t: u[v2t[pid]][0] += q or 0; u[v2t[pid]][1] += val or 0
for k, i in (('pol', 2), ('move', 3), ('mr', 4)):
    for pid, n in use[k]:
        if pid in v2t: u[v2t[pid]][i] += n
rows = []
for line in T:
    tid, name, code, categ, uom, typ, nvar, comp = line.split('|')
    tid = int(tid)
    at = '; '.join(f"{a}={','.join(sorted(vs))[:90]}" for a, vs in sorted(attrs[tid].items()))
    q, val, pol, mv, mr = u[tid]
    rows.append(dict(id=tid, name=name.strip(), code=code, categ=categ, uom=uom, type=typ, nvar=int(nvar), attrs=at,
                     qty=round(q, 2), value=round(val, 2), pol=pol, moves=mv, mr=mr))
cols = list(rows[0])
with open(D / 'templates.tsv', 'w', encoding='utf-8') as f:
    f.write('\t'.join(cols) + '\n')
    for r in sorted(rows, key=lambda r: r['name'].lower()):
        f.write('\t'.join(str(r[c]).replace('\t', ' ') for c in cols) + '\n')

STOP = {'for', 'of', 'the', 'and', 'with', 'w', 'type', 'pcs', 'pc', 'nos', 'item', 'items', 'new', 'a', 'set', 'per'}
def norm(s):
    s = s.lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9.]+', ' ', s)
    toks = []
    for t in s.split():
        if t in STOP: continue
        if len(t) > 3 and t.endswith('es') and not t.endswith('ses'): t = t[:-2]
        elif len(t) > 3 and t.endswith('s') and not t.endswith('ss'): t = t[:-1]
        toks.append(t)
    return toks
N = {r['id']: norm(r['name']) for r in rows}
byid = {r['id']: r for r in rows}
pairs = []
ids = sorted(N)
for i, a in enumerate(ids):
    ta, sa = N[a], ' '.join(sorted(N[a]))
    for b in ids[i + 1:]:
        tb = N[b]
        if not ta or not tb: continue
        inter = len(set(ta) & set(tb))
        if inter == 0 and SequenceMatcher(None, ''.join(ta), ''.join(tb)).quick_ratio() < 0.8: continue
        sb = ' '.join(sorted(tb))
        r1 = SequenceMatcher(None, sa, sb).ratio()
        r2 = SequenceMatcher(None, ''.join(ta), ''.join(tb)).ratio()
        jac = inter / len(set(ta) | set(tb))
        sub = set(ta) <= set(tb) or set(tb) <= set(ta)
        score = max(r1, r2, jac + (0.25 if sub else 0))
        if score >= 0.78:
            pairs.append((round(score, 3), a, b))
pairs.sort(reverse=True)
with open(D / 'fuzzy_pairs.tsv', 'w', encoding='utf-8') as f:
    f.write('score\tid_a\tname_a\tcateg_a\tuom_a\tid_b\tname_b\tcateg_b\tuom_b\n')
    for s, a, b in pairs:
        A, B = byid[a], byid[b]
        f.write(f"{s}\t{a}\t{A['name']}\t{A['categ']}\t{A['uom']}\t{b}\t{B['name']}\t{B['categ']}\t{B['uom']}\n")
print(len(rows), 'templates;', len(pairs), 'fuzzy pairs')
