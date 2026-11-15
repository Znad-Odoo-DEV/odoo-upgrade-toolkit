"""Contact sheets for eye review of image candidates (no browser needed).
Downloads every candidate URL with curl (user agent of the Odoo server's python-requests, same as the real upload),
then draws sheets of up to 21 images with "id name conf" under each.
Usage: python -I lib/img_sheet.py <work_dir> <tag> <batch> [<batch> ...]
Out: data/img/rv/<id>.img (downloads, untrusted - only opened by PIL), data/img/sheet_<tag>_<n>.png
Needs Pillow."""
import csv, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw

W, TAG, BATCHES = sys.argv[1], sys.argv[2], sys.argv[3:]
P = os.path.join(W, 'data', 'img'); RV = os.path.join(P, 'rv'); os.makedirs(RV, exist_ok=True)
rows = []
for b in BATCHES:
    with open(os.path.join(P, f'oa_{b}.csv'), encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            u = (r.get('image_url') or '').strip()
            if u.startswith('http'):
                rows.append((int(r['tmpl_id']), (r.get('name') or '')[:26], u, (r.get('confidence') or '')[:1]))


def fetch(row):
    i, n, u, c = row
    out = os.path.join(RV, f'{i}.img')
    r = subprocess.run(['curl', '-sL', '--max-time', '40', '-A', 'python-requests/2.31.0', '-o', out, '-w', '%{http_code}', u],
                       capture_output=True, text=True)
    return i, r.stdout.strip()


with ThreadPoolExecutor(8) as ex:
    codes = dict(ex.map(fetch, rows))
CW, CH, COLS = 220, 230, 7
for s in range(0, len(rows), 21):
    part = rows[s:s + 21]
    sheet = Image.new('RGB', (CW * COLS, CH * ((len(part) + COLS - 1) // COLS)), 'white')
    d = ImageDraw.Draw(sheet)
    for k, (i, n, u, c) in enumerate(part):
        x, y = (k % COLS) * CW, (k // COLS) * CH
        try:
            im = Image.open(os.path.join(RV, f'{i}.img')); im.load(); im = im.convert('RGB'); im.thumbnail((CW - 10, CH - 30))
            sheet.paste(im, (x + 5 + (CW - 10 - im.width) // 2, y + 2))
        except Exception:
            d.text((x + 10, y + 90), f'NO IMAGE http {codes.get(i)}', fill='red')
        d.text((x + 4, y + CH - 26), f'{i} {n} {c}', fill='black')
    out = os.path.join(P, f'sheet_{TAG}_{s // 21 + 1}.png'); sheet.save(out)
    print(out, len(part))
print('rows', len(rows), 'bad http', [i for i, c in codes.items() if c != '200'])
