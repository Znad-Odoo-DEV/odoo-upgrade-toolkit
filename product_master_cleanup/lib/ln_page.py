"""Long names -> short name + attributes: merge data/dd/lnp_*.tsv into reports/Name_Review.html (yes/no page).
Usage: python -I lib/ln_page.py <work_dir>"""
import csv, glob, json, sys
from pathlib import Path
W = Path(sys.argv[1]); D = W / 'data' / 'dd'
T = {}
for r in csv.DictReader(open(D / 'live_templates.tsv', encoding='utf-8'), delimiter='\t'):
    T[int(r['id'])] = r
drop = set()
if (D / 'ln_drop.txt').exists():
    drop = {int(l.split('#')[0]) for l in open(D / 'ln_drop.txt', encoding='utf-8') if l.split('#')[0].strip()}
props = []
for f in sorted(glob.glob(str(D / 'lnp_*.tsv'))):
    for r in csv.DictReader(open(f, encoding='utf-8', newline=''), delimiter='\t'):
        if (r.get('action') or '').strip().upper() != 'SHORTEN':
            continue
        i = int(r['id']); t = T.get(i)
        if not t or i in drop:
            continue
        attrs = [a.strip() for a in (r.get('attrs') or '').split(';') if '=' in a]
        note = ' | '.join(x for x in [(r.get('note') or '').strip(), f"same item as {r['same_as']}" if (r.get('same_as') or '').strip() else ''] if x)
        props.append(dict(tid=i, new_name=r['new_name'].strip(), attrs=[a.replace('=', ': ', 1) for a in attrs], raw_attrs=attrs,
                          same_as=(r.get('same_as') or '').strip(), reason=note,
                          items=[dict(id=i, name=t['name'], code=t['code'], categ=t['categ'], nvar=int(t['nvar']))]))
props.sort(key=lambda p: (p['items'][0]['categ'], p['items'][0]['name'].lower()))
for n, p in enumerate(props, 1):
    p['n'] = n; p['id'] = f'n{n:03d}'
data = dict(at='2026-11-16', total=len(T), proposals=props)
json.dump(data, open(D / 'name_proposals.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
tpl = (W / 'lib' / 'ln_page.tpl.html').read_text(encoding='utf-8')
(W / 'reports' / 'Name_Review.html').write_text(tpl.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\/')), encoding='utf-8')
print(len(props), 'proposals;', sum(1 for p in props if p['same_as']), 'with same_as')
