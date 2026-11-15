"""Round 7: map the r7_c_* plans from dev_0 ids to main ids by CONTENT, never by id alone.
Usage: python -I lib/r7_main_map.py <work_dir> <dev_extract.json> <main_extract.json>
Reads  data/r7_c_{moves,renames,merges,joins,cats}.txt
Writes data/r7m_c_*.txt (same formats, ids replaced) and data/r7m_checksums.txt.
Variant key  = (default_code, template name, sorted "Attribute:Value" of its PTAVs).
Template key = sorted tuple of its variants' keys; if main has an extra/missing variant in that template (a user created it),
the template is still accepted when ALL its dev variants map to variants of ONE main template with the same name
(templates without variants: name + default_code must be unique). Anything else, or any id with 0 or >1 candidates -> refuse
(exit 1, nothing written). Never guesses.
"""
import functools, json, re, sys
from collections import defaultdict
from pathlib import Path

W = Path(sys.argv[1])
FILES = ['moves', 'renames', 'merges', 'joins', 'cats']


def load(p):
    X = json.load(open(p, encoding='utf-8'))
    ptav = {p['id']: f"{p['attribute_id'][1]}:{p['name']}" for p in X['ptav']}
    T = {t['id']: t for t in X['templates']}
    V = {}
    for v in X['variants']:
        tid = v['product_tmpl_id'][0]
        tname = T[tid]['name'] if tid in T else v['product_tmpl_id'][1]
        V[v['id']] = {'tid': tid, 'key': (v['default_code'] or '', tname,
                                          tuple(sorted(ptav.get(i, f'?{i}') for i in v['product_template_attribute_value_ids'])))}
    VT = defaultdict(list)
    for vid, v in V.items():
        VT[v['tid']].append(vid)
    return T, V, VT


dT, dV, dVT = load(sys.argv[2])
mT, mV, mVT = load(sys.argv[3])
m_vkey, d_vkey, m_tkey, m_tname = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
for vid, v in mV.items():
    m_vkey[v['key']].append(vid)
for vid, v in dV.items():
    d_vkey[v['key']].append(vid)
for tid, vs in mVT.items():
    m_tkey[tuple(sorted(mV[v]['key'] for v in vs))].append(tid)
for tid, t in mT.items():
    m_tname[(t['name'], t.get('default_code') or '')].append(tid)

# ---- parse the plans, collect ids
txt = {f: (W / f'data/r7_c_{f}.txt').read_text(encoding='utf-8') for f in FILES}
split = lambda s, sep: s.split(sep) if s else []
P = {
    'moves': [r.split('|', 2) for r in split(txt['moves'], '~')],
    'renames': [r.split('|', 1) for r in split(txt['renames'], '~')],
    'merges': [r.split('|') for r in split(txt['merges'], '~')],
    'cats': [r.split('|', 1) for r in split(txt['cats'], '~')],
    'joins': [b.split('|', 4) for b in split(txt['joins'], '#')],
}
errs = []
for f, n in (('moves', 3), ('renames', 2), ('cats', 2), ('joins', 5), ('merges', 4)):
    for r in P[f]:
        if len(r) != n:
            errs.append(f'{f}: malformed record {r[:2]}')
if errs:
    print('REFUSED (format):', *errs[:20], sep='\n  ')
    sys.exit(1)
tids, vids = set(), set()
for r in P['moves'] + P['renames'] + P['cats']:
    tids.add(int(r[0]))
for r in P['merges']:
    vids.add(int(r[1]))
    vids.update(int(x) for x in r[2].split(',') if x)
for r in P['joins']:
    tids.add(int(r[0][2:]))
    vids.add(int(r[3]))
    for it in r[4].split('~'):
        vids.add(int(it.split('^')[0]))

# ---- map
vmap, tmap = {}, {}
same_v = diff_v = same_t = diff_t = 0
for v in sorted(vids):
    if v not in dV:
        errs.append(f'variant {v}: not in dev extract')
        continue
    k = dV[v]['key']
    c = m_vkey.get(k, [])
    if len(d_vkey[k]) > 1:
        errs.append(f'variant {v}: key {k} is not unique on dev ({len(d_vkey[k])}) - ambiguous')
    elif len(c) != 1:
        errs.append(f'variant {v}: {len(c)} matches on main for {k}')
    else:
        vmap[v] = c[0]
        same_v += c[0] == v
        diff_v += c[0] != v
for t in sorted(tids):
    if t not in dT:
        errs.append(f'template {t}: not in dev extract')
        continue
    vs = dVT.get(t, [])
    if vs:
        c = m_tkey.get(tuple(sorted(dV[v]['key'] for v in vs)), [])
        if len(c) != 1:  # fall back: every dev variant maps to a variant of ONE main template with the same name
            ms = [m_vkey.get(dV[v]['key'], []) for v in vs]
            if all(len(m) == 1 for m in ms):
                ts = {mV[m[0]]['tid'] for m in ms}
                c = [x for x in ts if mT[x]['name'] == dT[t]['name']] if len(ts) == 1 else []
            else:
                c = []
    else:
        c = m_tname.get((dT[t]['name'], dT[t].get('default_code') or ''), [])
    if len(c) != 1:
        errs.append(f'template {t} ({dT[t]["name"]}): {len(c)} matches on main')
        continue
    tmap[t] = c[0]
    same_t += c[0] == t
    diff_t += c[0] != t
if len(set(tmap.values())) != len(tmap):
    errs.append('two dev templates map to the same main template')
if len(set(vmap.values())) != len(vmap):
    errs.append('two dev variants map to the same main variant')
if errs:
    print(f'REFUSED: {len(errs)} problem(s), nothing written')
    for e in errs[:200]:
        print('  ', e)
    sys.exit(1)
print(f'templates: {len(tmap)} mapped ({same_t} same id, {diff_t} different id); '
      f'variants: {len(vmap)} mapped ({same_v} same id, {diff_v} different id)')
for a, b in sorted(tmap.items()):
    if a != b:
        print('  template', a, '->', b)
for a, b in sorted(vmap.items()):
    if a != b:
        print('  variant', a, '->', b)

# ---- write
T_ = lambda i: str(tmap[int(i)])
V_ = lambda i: str(vmap[int(i)])
out = {}
out['moves'] = '~'.join(f'{T_(a)}|{b}|{c}' for a, b, c in P['moves'])
out['renames'] = '~'.join(f'{T_(a)}|{b}' for a, b in P['renames'])
out['cats'] = '~'.join(f'{T_(a)}|{b}' for a, b in P['cats'])
mg = []
for g, m, d, e in P['merges']:
    mm = re.fullmatch(r'R7-(\d+)-(\d+)', g)
    ng = f'R7-{V_(mm.group(1))}-{V_(mm.group(2))}' if mm else g
    mg.append(f"{ng}|{V_(m)}|{','.join(V_(x) for x in d.split(',') if x)}|{e}")
out['merges'] = '~'.join(mg)
jb = []
for tk, name, attrs, master, items in P['joins']:
    its = []
    for it in items.split('~'):
        p = it.split('^')
        its.append('^'.join([V_(p[0])] + p[1:]))
    jb.append(f'T-{T_(tk[2:])}|{name}|{attrs}|{V_(master)}|' + '~'.join(its))
out['joins'] = '#'.join(jb)

ck = lambda ids: (len(ids), sum(ids), functools.reduce(lambda a, b: a ^ b, ids, 0))
lines = []
for f in FILES:
    (W / f'data/r7m_c_{f}.txt').write_text(out[f], encoding='utf-8', newline='')
    recs = [r for r in out[f].split('#' if f == 'joins' else '~') if r]
    if f == 'merges':
        v = [int(x) for r in recs for x in [r.split('|')[1]] + r.split('|')[2].split(',') if x]
        lines.append(f'r7m_c_merges.txt variants CHECK {ck(v)}')
    elif f == 'joins':
        t = [int(r.split('|')[0][2:]) for r in recs]
        v = [int(i.split('^')[0]) for r in recs for i in r.split('|', 4)[4].split('~')]
        lines.append(f'r7m_c_joins.txt templates CHECK {ck(t)}')
        lines.append(f'r7m_c_joins.txt variants CHECK {ck(v)}')
    else:
        lines.append(f'r7m_c_{f}.txt templates CHECK {ck([int(r.split("|")[0]) for r in recs])}')
(W / 'data/r7m_checksums.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(*lines, sep='\n')
