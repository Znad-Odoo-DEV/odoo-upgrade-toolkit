"""Apply the round-5 QA (data/r5_qa_S.csv, data/r5_qa_NT.csv) to data/r5_merge.json / r5_variants.json and write the
final plans + compact paste files. Run lib/r5_build.py first. Usage: python -I lib/r5_finalize.py <work_dir>"""
import csv, json, re, sys, functools
from collections import Counter
from pathlib import Path

W = Path(sys.argv[1])
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig'))) if Path(p).exists() else []
M = json.load(open(W / 'data/r5_merge.json', encoding='utf-8'))
V = json.load(open(W / 'data/r5_variants.json', encoding='utf-8'))
R = json.load(open(W / 'data/r5_renames.json', encoding='utf-8'))
Vk = {p['tk']: p for p in V}; Mk = {p['g']: p for p in M}
log, miss = Counter(), []
num = lambda x: int(float(x)) if (x or '').strip() else None
for q in rd(W / 'data/r5_qa_S.csv') + rd(W / 'data/r5_qa_NT.csv') + rd(W / 'data/r6_qa.csv'):
    tk, it, act = q['tk'].strip(), num(q['item']), q['action'].strip().upper()
    fld, nv = (q.get('field') or '').strip(), (q.get('new_value') or '').strip()
    if tk in Mk:
        p = Mk[tk]
        if act == 'DROP':
            if it is None or it == p['master']:
                p['dups'] = []; log['merge group dropped'] += 1
            elif it in p['dups']:
                p['dups'].remove(it); log['merge dup dropped'] += 1
        continue
    p = Vk.get(tk)
    if not p:
        miss.append(tk); continue
    if act == 'DROP':
        if it is None:
            p['items'] = []; log['template dropped'] += 1
        elif tk.startswith('T') and it == p['master']:
            log['T master kept (cannot drop)'] += 1
        else:
            n0 = len(p['items']); p['items'] = [i for i in p['items'] if i['var'] != it]; log['item dropped'] += n0 - len(p['items'])
    elif act == 'FIX_NAME' and nv and not tk.startswith('T'):
        p['name'] = nv; log['name fixed'] += 1
    elif act == 'FIX_VALUE' and nv and fld not in p['attrs'] and tk.startswith('S') and len(p['attrs']) == 1:
        p['attrs'] = [fld]; p['items'][0]['vals'] = [nv]; log['attribute replaced'] += 1  # e.g. Size -> Thickness
    elif act == 'FIX_VALUE' and nv and fld in p['attrs']:
        k = p['attrs'].index(fld)
        for i in p['items']:
            if it is None or i['var'] == it:
                i['vals'][k] = nv; log['value fixed'] += 1
    elif act == 'FIX_VALUE' and nv and tk.startswith('S') and (m := re.search(r'replace attribute ([A-Za-z ]+?) by ([A-Za-z ]+?)\b', q.get('reason') or '')) and m.group(1) in p['attrs'] and m.group(2) == fld:
        k = p['attrs'].index(m.group(1)); p['attrs'][k] = fld; p['items'][0]['vals'][k] = nv; log['attribute replaced'] += 1
    elif act == 'FIX_VALUE' and nv and fld not in p['attrs'] and it is not None and \
            (k := next((k for i in p['items'] if i['var'] == it for k, v in enumerate(i['vals']) if v.replace(' ', '').lower() == nv.replace(' ', '').lower()), None)) is not None:
        p['attrs'][k] = fld; log['attribute replaced'] += 1  # the value is right, its attribute was wrong (Weight -> Capacity ...)
    else:
        log[f'ignored {act}'] += 1; miss.append(f'{tk} {act} {fld}')
# S-/N- templates that end with the same name and attributes are one family (e.g. Backer Rod 30mm + 60mm)
fam = {}
for p in V:
    if p['tk'][0] in 'SN' and p['items']:
        k = (re.sub(r'[^a-z0-9]', '', p['name'].lower()), tuple(p['attrs']))
        if k in fam:
            f = fam[k]; f['items'] += p['items']; p['items'] = []
            if f['tk'][0] == 'S':
                f['tk'] = 'N-' + k[0][:40] + '-x'
            log['same-name templates joined'] += 1
        else:
            fam[k] = p
# lead decisions: a density is not a Weight -> the item keeps it in its name, no attribute (rename only)
for tk, nm in {'S-10320': 'Clean Liner Roll Fibreglass 24kg/m3'}.items():
    if tk in Vk:
        X_t = Vk[tk]; X_t['items'] = []; R.append([None, {'name': nm, 'var': X_t['master']}]); log['lead: attribute removed, rename only'] += 1
# clean up: separators, duplicate combinations, masters, families of one
bad = lambda s: bool(re.search(r'[|~#^]', s or ''))
VV = []
for p in V:
    seen, its = set(), []
    for i in p['items']:
        c = tuple(i['vals'])
        if c in seen or any(bad(x) for x in i['vals']):
            log['item dropped (duplicate combination or separator)'] += 1; continue
        seen.add(c); its.append(i)
    p['items'] = its
    if not its or bad(p['name']):
        continue
    if p['tk'].startswith('T'):
        if its[0]['var'] == p['master'] and len(its) > 1:
            VV.append(p)
        continue
    if p['master'] not in [i['var'] for i in its]:
        p['master'] = its[0]['var']
    if len(its) == 1 and p['tk'].startswith('N'):
        p['tk'] = f"S-{its[0]['var']}"; log['family of one -> single template'] += 1
    VV.append(p)
MM = [p for p in M if p['dups']]
in_var = {i['var'] for p in VV for i in p['items']}
MM = [p for p in MM if p['master'] not in in_var or True]
json.dump(MM, open(W / 'data/r5_final_merge.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(VV, open(W / 'data/r5_final_variants.json', 'w', encoding='utf-8'), ensure_ascii=False)
open(W / 'data/r5_c_merge.txt', 'w', encoding='utf-8').write('~'.join(f"{p['g']}|{p['master']}|{','.join(map(str, p['dups']))}|" for p in MM))
open(W / 'data/r5_c_variants.txt', 'w', encoding='utf-8').write('#'.join(f"{p['tk']}|{p['name']}|{'^'.join(p['attrs'])}|{p['master']}|" + '~'.join(f"{i['var']}^{'^'.join(i['vals'])}" for i in p['items']) for p in VV))
ck = lambda ids: (len(ids), sum(ids), functools.reduce(lambda a, b: a ^ b, ids, 0))
print('QA', dict(log), '| unknown tk', len(miss), miss[:5])
print('merges', len(MM), 'CHECK', ck([p['master'] for p in MM] + [d for p in MM for d in p['dups']]))
print('variants', len(VV), Counter(p['tk'][0] for p in VV), 'CHECK', ck([i['var'] for p in VV for i in p['items']]), 'attrs', sorted({a for p in VV for a in p['attrs']}))
print('renames', len(R), 'sizes', (W / 'data/r5_c_merge.txt').stat().st_size, (W / 'data/r5_c_variants.txt').stat().st_size)

json.dump(R, open(W / 'data/r5_final_renames.json', 'w', encoding='utf-8'), ensure_ascii=False)
