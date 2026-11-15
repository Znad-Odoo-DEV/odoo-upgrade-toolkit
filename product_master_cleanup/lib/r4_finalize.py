"""Apply round-4 QA drops and write the final compact plans. Usage: python -I lib/r4_finalize.py <work_dir>"""
import csv, json, sys, functools
from pathlib import Path

W = Path(sys.argv[1])
rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig'))) if Path(p).exists() else []
M = json.load(open(W / 'data/r4_merge.json', encoding='utf-8'))
V = json.load(open(W / 'data/r4_variants.json', encoding='utf-8'))
R = json.load(open(W / 'data/r4_renames.json', encoding='utf-8'))
log = {'merge items dropped': 0, 'merge groups dropped': 0, 'variant items dropped': 0, 'variant templates dropped': 0}
for d in rd(W / 'data/r4_qa_merge_drop.csv'):
    for p in M:
        if p['g'] == d['g'].strip():
            it = int(float(d['item'])) if d['item'].strip() else None
            if it is None or it == p['master']:
                p['dups'] = []; log['merge groups dropped'] += 1
            elif it in p['dups']:
                p['dups'].remove(it); log['merge items dropped'] += 1
for d in rd(W / 'data/r4_qa_variant_drop.csv'):
    for p in V:
        if p['tk'] == d['tk'].strip():
            it = int(float(d['item'])) if d['item'].strip() else None
            if it is None:
                p['items'] = []; log['variant templates dropped'] += 1
            else:
                before = len(p['items'])
                p['items'] = [i for i in p['items'] if i['var'] != it or (p['tk'].startswith('T') and i['var'] == p['master'])]
                log['variant items dropped'] += before - len(p['items'])
NAMEFIX = {'N-sandingpaper-BOX': 'Sanding Paper (Box)', 'N-interlockpaverroughcurledcoated-M2': 'Interlock Paver Coloured Rough Curled Coated',
           'N-msshsx6m-EA': 'MS SHS (6m Length)', 'N-tile-M2': 'Tile (Sqm)'}
for p in V:
    if p['tk'] in NAMEFIX:
        p['name'] = NAMEFIX[p['tk']]
M = [p for p in M if p['dups']]
VV = []
for p in V:
    if p['tk'].startswith('T'):
        if len(p['items']) > 1:
            VV.append(p)
    elif len(p['items']) >= 2:
        if p['master'] not in [i['var'] for i in p['items']]:
            p['master'] = p['items'][0]['var']
        VV.append(p)
json.dump(M, open(W / 'data/r4_final_merge.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(VV, open(W / 'data/r4_final_variants.json', 'w', encoding='utf-8'), ensure_ascii=False)
open(W / 'data/r4_c_merge.txt', 'w', encoding='utf-8').write('~'.join(f"{p['g']}|{p['master']}|{','.join(map(str, p['dups']))}|" for p in M))
open(W / 'data/r4_c_variants.txt', 'w', encoding='utf-8').write('#'.join(f"{p['tk']}|{p['name']}|{'^'.join(p['attrs'])}|{p['master']}|" + '~'.join(f"{i['var']}^{'^'.join(i['vals'])}" for i in p['items']) for p in VV))
ck = lambda ids: (len(ids), sum(ids), functools.reduce(lambda a, b: a ^ b, ids, 0))
print('QA', log)
print('merges', len(M), 'CHECK', ck([p['master'] for p in M] + [d for p in M for d in p['dups']]))
print('variants', len(VV), 'CHECK', ck([i['var'] for p in VV for i in p['items']]), 'attr names', sorted({a for p in VV for a in p['attrs']}))
print('renames', len(R), 'sizes', (W / 'data/r4_c_merge.txt').stat().st_size, (W / 'data/r4_c_variants.txt').stat().st_size)
