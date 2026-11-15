"""Fingerprints of the variant ids used by a round's plans, so another database can map them by content.
Usage: python -I lib/r8_keys.py <work_dir> <extract.json> <prefix: r8> <max original product id: 13789>
Writes data/<prefix>_hikeys.txt (id|code|tmpl|hash36 of sorted "Attribute:Value" - ids created during the cleanup) and
data/<prefix>_lokeys.txt (id|tmpl - original ids, same on both databases, checked by template)."""
import json, sys
from pathlib import Path

W, EXT, PFX, MAXO = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
X = json.load(open(W / EXT, encoding='utf-8'))
V = {v['id']: v for v in X['variants']}
ptav = {p['id']: f"{p['attribute_id'][1]}:{p['name']}" for p in X['ptav']}
rd = lambda f: (W / f'data/{PFX}_c_{f}.txt').read_text(encoding='utf-8')
vids = set()
for r in rd('merges').split('~'):
    if r:
        g, m, d, _ = r.split('|'); vids.add(int(m)); vids.update(int(x) for x in d.split(','))
for b in rd('joins').split('#'):
    if b:
        tk, name, attrs, master, items = b.split('|', 4); vids.add(int(master)); vids.update(int(it.split('^')[0]) for it in items.split('~'))


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


miss = [i for i in vids if i not in V]
assert not miss, f'ids not in the extract: {miss[:20]}'
hi = sorted(i for i in vids if i > MAXO); lo = sorted(i for i in vids if i <= MAXO)
H = '~'.join(f"{i}|{V[i]['default_code'] or ''}|{V[i]['product_tmpl_id'][0]}|{b36(fnv('+'.join(sorted(ptav[p] for p in V[i]['product_template_attribute_value_ids']))))}" for i in hi)
L = '~'.join(f"{i}|{V[i]['product_tmpl_id'][0]}" for i in lo)
(W / f'data/{PFX}_hikeys.txt').write_text(H, encoding='utf-8'); (W / f'data/{PFX}_lokeys.txt').write_text(L, encoding='utf-8')
print('variants', len(vids), 'hi', len(hi), 'lo', len(lo), 'chars', len(H) + len(L))
