"""Round 7 on main without a download: a fingerprint of every id the r7 plans use, matched inside the main tab.
Usage: python -I lib/r7_keys.py <work_dir>   (reads data/r7_extract.json + data/r7_c_*.txt, writes data/r7_keys.txt)
Variant fingerprint = FNV-1a 32 of  default_code \x01 template name \x01 sorted "Attribute:Value" joined by "+".
Template = its smallest variant (rep) + FNV of its name + variant count.
Format: V<id>|<code>|<hash36>|<template name only when there is no code>~...  then  #  T<id>|<rep>|<namehash36>|<count>~...
"""
import json, sys
from collections import defaultdict
from pathlib import Path

W = Path(sys.argv[1])
X = json.load(open(W / 'data/r7_extract.json', encoding='utf-8'))
ptav = {p['id']: f"{p['attribute_id'][1]}:{p['name']}" for p in X['ptav']}
T = {t['id']: t for t in X['templates']}
V, VT = {}, defaultdict(list)
for v in X['variants']:
    V[v['id']] = v; VT[v['product_tmpl_id'][0]].append(v['id'])


def fnv(s):
    h = 0x811c9dc5
    for b in s.encode('utf-8'):
        h ^= b; h = (h * 0x01000193) & 0xffffffff
    return h


def b36(n):
    d = '0123456789abcdefghijklmnopqrstuvwxyz'; s = ''
    while True:
        n, r = divmod(n, 36); s = d[r] + s
        if not n: return s


def vkey(vid):
    v = V[vid]; t = T[v['product_tmpl_id'][0]]
    return (v['default_code'] or '') + '\x01' + t['name'] + '\x01' + '+'.join(sorted(ptav[i] for i in v['product_template_attribute_value_ids']))


rd = lambda f: (W / f'data/r7_c_{f}.txt').read_text(encoding='utf-8')
tids, vids = set(), set()
for f in ('moves', 'renames', 'cats'):
    for r in rd(f).split('~'):
        if r: tids.add(int(r.split('|', 1)[0]))
for r in rd('merges').split('~'):
    if r:
        g, m, d, _ = r.split('|'); vids.add(int(m)); vids.update(int(x) for x in d.split(','))
for b in rd('joins').split('#'):
    tk, name, attrs, master, items = b.split('|', 4)
    tids.add(int(tk[2:])); vids.add(int(master)); vids.update(int(it.split('^')[0]) for it in items.split('~'))
reps = {t: min(VT[t]) for t in tids}
vids |= set(reps.values())
miss = [i for i in vids if i not in V] + [t for t in tids if t not in T]
assert not miss, f'ids not in the extract: {miss[:20]}'
VL = []
for i in sorted(vids):
    v = V[i]; code = v['default_code'] or ''
    if any(c in code for c in '|~#'): raise SystemExit(f'separator in code {i}')
    tn = '' if code else T[v['product_tmpl_id'][0]]['name']
    VL.append(f"V{i}|{code}|{b36(fnv(vkey(i)))}|{tn}")
TL = [f"T{t}|{reps[t]}|{b36(fnv(T[t]['name']))}|{len(VT[t])}" for t in sorted(tids)]
dup = [k for k, n in __import__('collections').Counter(vkey(i) for i in vids).items() if n > 1]
assert not dup, f'two dev ids share a fingerprint: {dup[:5]}'
out = '~'.join(VL) + '#' + '~'.join(TL)
(W / 'data/r7_keys.txt').write_text(out, encoding='utf-8')
print('variants', len(VL), '| templates', len(TL), '| no code', sum(1 for l in VL if l.split('|')[1] == ''), '| chars', len(out))
print('selftest fnv("abc") =', b36(fnv('abc')))
