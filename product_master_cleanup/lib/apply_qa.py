"""Apply data/qa_fixes.csv to data/review_out/*.csv -> data/review_final/*.csv (review_out is never changed).
Usage: python -I lib/apply_qa.py <work_dir>   Writes data/review_final/_applied.csv (every fix: applied or why not).
"""
import csv, shutil, sys
from pathlib import Path

W = Path(sys.argv[1])
src, dst = W / 'data/review_out', W / 'data/review_final'
dst.mkdir(exist_ok=True)
files = {}
for p in src.glob('*.csv'):
    with open(p, encoding='utf-8-sig') as f:
        r = csv.DictReader(f)
        files[p.stem] = (list(r.fieldnames), list(r))
log = []
for fx in csv.DictReader(open(W / 'data/qa_fixes.csv', encoding='utf-8-sig')):
    name = fx['file'].strip().replace('.csv', '')
    if name not in files:
        log.append({**fx, 'status': 'unknown file'}); continue
    cols, rows = files[name]
    hit = [r for r in rows if r['var_id'].strip() == fx['var_id'].strip()]
    if not hit and 'new row' in fx['reason'].lower():
        new = {c: '' for c in cols}; new['var_id'] = fx['var_id'].strip(); rows.append(new); hit = [new]
    if not hit:
        log.append({**fx, 'status': 'var_id not in file'}); continue
    field = fx['field'].strip()
    if field not in cols:
        cols.append(field)
        for r in rows:
            r.setdefault(field, '')
    for r in hit:
        r[field] = fx['new_value']
        r['qa_note'] = (r.get('qa_note', '') + f" [{fx['severity']}] {field}: {fx['reason']}").strip()
    if 'qa_note' not in cols:
        cols.append('qa_note')
    log.append({**fx, 'status': 'applied'})
for name, (cols, rows) in files.items():
    with open(dst / f'{name}.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows([{c: r.get(c, '') for c in cols} for r in rows])
with open(dst / '_applied.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=list(log[0]) if log else ['status'])
    w.writeheader()
    w.writerows(log)
from collections import Counter
print('fixes', len(log), Counter(l['status'] for l in log))
