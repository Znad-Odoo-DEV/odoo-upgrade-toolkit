"""Build the list of products still without an image and split it into batches for the image search.
Inputs (data/): main_final/main_final_extract.json (names, categories, attributes), img/rem_ids.json (ids still
without an image, decoded from the page), img/rem_diffnames.txt (current name|category of templates renamed since the
extract), img/list_*.txt (items already searched in earlier batches, not searched again).
Output: img/list_all.txt and img/ba_<n>.txt (20 lines each: id|name|category|hints).
Usage: python -I lib/img_list.py <work_dir>"""
import glob, json, os, sys

os.chdir(os.path.join(sys.argv[1], 'data'))
R = json.load(open('img/rem_ids.json'))
d = json.load(open('main_final/main_final_extract.json', encoding='utf-8'))
T = {t['id']: t for t in d['templates']}
AV = {v['id']: v['name'] for v in d['attr_values']}
A = {}
for l in d['lines']:
    vs = [AV.get(i) for i in l['value_ids']]
    vs = [v for v in vs if v and v != 'Not Specified']
    if vs:
        A.setdefault(l['product_tmpl_id'][0], []).append(l['attribute_id'][1] + ': ' + '/'.join(vs[:8]))
DN = {}
for x in open('img/rem_diffnames.txt', encoding='utf-8').read().strip().split('\n'):
    p = x.split('|'); DN[int(p[0])] = p[1:]
tried = set()
for f in sorted(glob.glob('img/list_[0-9]*.txt')):
    for ln in open(f, encoding='utf-8'):
        if ln.strip():
            tried.add(int(ln.split('|')[0]))
rows = []
for i in R['ids']:
    if i in tried:
        continue
    t = T[i]
    if i in DN:
        nm, cat = DN[i]
        hint = ('was: ' + t['name'] + '; ') if t['name'] != nm else ''
    else:
        nm = t['name'].replace('|', ' ').replace('\n', ' ')
        cat = t['categ_id'][1].split('/')[-1].strip()
        hint = ''
    rows.append(f"{i}|{nm}|{cat}|{(hint + '; '.join(A.get(i, [])))[:220]}")
rows.sort(key=lambda r: r.split('|')[1].lower())
open('img/list_all.txt', 'w', encoding='utf-8').write('\n'.join(rows) + '\n')
for k in range(0, len(rows), 20):
    open(f'img/ba_{k // 20 + 1}.txt', 'w', encoding='utf-8').write('\n'.join(rows[k:k + 20]) + '\n')
print('no image', len(R['ids']), 'searched before', len(tried & set(R['ids'])), 'to search', len(rows), 'batches', (len(rows) + 19) // 20)
