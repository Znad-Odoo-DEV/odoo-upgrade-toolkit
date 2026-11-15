"""Image review helper.
  python -I lib/img_review.py <work_dir> show <batch>            -> JS rows [[label, url], ...] for the review overlay
  python -I lib/img_review.py <work_dir> accept <batch> [rej ids] -> data/img/ua_<batch>.json [[id, url], ...] for upload
Reads data/img/oa_<batch>.csv written by the image search agents (header tmpl_id,name,image_url,source_page,...)."""
import csv, json, os, sys

W, CMD, B = sys.argv[1], sys.argv[2], sys.argv[3]
P = os.path.join(W, 'data', 'img')
rows = []
with open(os.path.join(P, f'oa_{B}.csv'), encoding='utf-8', newline='') as f:
    for r in csv.DictReader(f):
        u = (r.get('image_url') or '').strip()
        if u.startswith('http'):
            rows.append((int(r['tmpl_id']), (r.get('name') or '')[:28], u, (r.get('confidence') or '')[:1]))
if CMD == 'show':
    print(json.dumps([[f'{i} {n} {c}', u] for i, n, u, c in rows], ensure_ascii=True, separators=(',', ':')))
elif CMD == 'accept':
    rej = {int(x) for x in sys.argv[4:]}
    acc = [[i, u] for i, n, u, c in rows if i not in rej]
    json.dump(acc, open(os.path.join(P, f'ua_{B}.json'), 'w'), separators=(',', ':'))
    print(len(acc), 'accepted', len(rej), 'rejected', len(rows), 'with url')
