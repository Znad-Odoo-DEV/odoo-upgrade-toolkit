"""Deep duplicate study, step 2: merge the reviewers' proposals (data/dd/prop_*.tsv) into one numbered list and
write the yes/no review page reports/Duplicate_Review.html (+ data/dd/proposals.json).
SAME proposals that share a template are joined (union-find); FAMILY proposals likewise; a reviewer-level drop list
data/dd/drop.txt (one proposal key per line: sorted ids joined by '-') removes proposals judged wrong by the lead.
Usage: python -I lib/dd_page.py <work_dir>"""
import csv, glob, json, os, sys
from pathlib import Path

W = Path(sys.argv[1]); D = W / 'data' / 'dd'
T = {int(r['id']): r for r in csv.DictReader(open(D / 'templates.tsv', encoding='utf-8'), delimiter='\t')}
drop = set()
if (D / 'drop.txt').exists():
    drop = {l.split('#')[0].strip() for l in open(D / 'drop.txt', encoding='utf-8') if l.split('#')[0].strip()}
# data/dd/lead_remove.txt: '<template id>  # why' -> that template is taken out of every proposal (lead review)
rm = set()
if (D / 'lead_remove.txt').exists():
    rm = {int(l.split('#')[0]) for l in open(D / 'lead_remove.txt', encoding='utf-8') if l.split('#')[0].strip()}
raw = []
for f in sorted(glob.glob(str(D / 'prop_*.tsv'))):
    src = Path(f).stem[-1]
    with open(f, encoding='utf-8', newline='') as fh:
        for r in csv.DictReader(fh, delimiter='\t'):
            try:
                ids = sorted({int(x) for x in str(r.get('ids') or '').replace(' ', '').split(',') if x})
            except ValueError:
                continue
            ids = [i for i in ids if i in T and i not in rm]
            if len(ids) < 2:
                continue
            kind = 'FAMILY' if (r.get('kind') or '').strip().upper() == 'FAMILY' else 'SAME'
            try:
                m = int(r.get('master_id') or 0)
            except ValueError:
                m = 0
            raw.append(dict(kind=kind, ids=ids, master=m, reason=(r.get('reason') or '').strip(),
                            conf='HIGH' if (r.get('confidence') or '').strip().upper() == 'HIGH' else 'MEDIUM', src=src))
groups = []
for kind in ('SAME', 'FAMILY'):
    par = {}
    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    props = [p for p in raw if p['kind'] == kind]
    for p in props:
        for i in p['ids'][1:]:
            par[find(i)] = find(p['ids'][0])
    by = {}
    for p in props:
        by.setdefault(find(p['ids'][0]), []).append(p)
    for ps in by.values():
        ids = sorted({i for p in ps for i in p['ids']})
        key = '-'.join(map(str, ids))
        if key in drop:
            continue
        def use(i):
            t = T[i]; return (float(t['qty'] or 0) != 0, int(t['pol'] or 0) + int(t['moves'] or 0) + int(t['mr'] or 0), -i)
        votes = [p['master'] for p in ps if p['master'] in ids]
        master = max(set(votes), key=votes.count) if votes else max(ids, key=use)
        reasons = []
        for p in ps:
            if p['reason'] and p['reason'] not in reasons:
                reasons.append(p['reason'])
        groups.append(dict(kind=kind, key=key, ids=ids, master=master,
                           conf='HIGH' if any(p['conf'] == 'HIGH' for p in ps) else 'MEDIUM',
                           reason=' | '.join(reasons)[:600], src=''.join(sorted({p['src'] for p in ps}))))
groups.sort(key=lambda g: (g['kind'] != 'SAME', g['conf'] != 'HIGH', T[g['master']]['categ'], T[g['master']]['name'].lower()))
out = []
for n, g in enumerate(groups, 1):
    items = []
    for i in sorted(g['ids'], key=lambda i: (i != g['master'], T[i]['name'].lower())):
        t = T[i]
        items.append(dict(id=i, name=t['name'], code=t['code'], categ=t['categ'], uom=t['uom'], qty=float(t['qty'] or 0),
                          pol=int(t['pol'] or 0), moves=int(t['moves'] or 0), nvar=int(t['nvar'] or 1), attrs=t['attrs']))
    out.append(dict(id=f'p{n:03d}', n=n, key=g['key'], kind=g['kind'], conf=g['conf'], master=g['master'],
                    reason=g['reason'], src=g['src'], items=items))
data = dict(at='2026-11-16', total=len(T), proposals=out)
json.dump(data, open(D / 'proposals.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
tpl = (W / 'lib' / 'dd_page.tpl.html').read_text(encoding='utf-8')
js = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
(W / 'reports').mkdir(exist_ok=True)
(W / 'reports' / 'Duplicate_Review.html').write_text(tpl.replace('__DATA__', js), encoding='utf-8')
from collections import Counter
print(len(raw), 'raw proposals ->', len(out), 'groups', dict(Counter((g['kind'], g['conf']) for g in out)),
      'items', sum(len(g['items']) for g in out), 'dropped', len(drop))
