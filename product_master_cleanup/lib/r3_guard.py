"""Strict guard for the final clean-rename pass. Usage: python -I lib/r3_guard.py <work_dir>
Accept a new name only when: same numbers as the old name; every new word is an old word, a unit word, or a spelling fix
(similar to an old word); no material/colour/system word that the old name does not have; an item word is present.
"1.1/2" in an old name means 1-1/2 and "H.P" means HP (normalised before comparing).
Writes data/r3_final_updates.json ([[tmpl_id, {"name": ...}]]), data/r3_rejected.csv and data/r3_c_updates.txt.
"""
import csv, json, re, sys, difflib, functools
from pathlib import Path

W = Path(sys.argv[1])
UNITS = {'mm', 'in', 'm', 'cm', 'mm2', 'deg', 'kg', 'l', 'ltr', 'x', 'and', 'with', 'for', 'of', 'the', 'per'}
GUARDED = {'ppr', 'upvc', 'pvc', 'gi', 'ms', 'ss', 'hp', 'hdpe', 'brass', 'copper', 'grey', 'gray', 'orange', 'black', 'white', 'red',
           'blue', 'yellow', 'green', 'silver', 'male', 'female', 'threaded', 'socket', 'elbow', 'tee', 'reducer', 'bush', 'rr', 'sch80', 'sch40'}
FRACTION = re.compile(r'(\d)\.(\d+/\d+)')
HP = re.compile(r'\bh\.p\b')


def norm(s):
    s = HP.sub('hp', s.lower())
    return FRACTION.sub(lambda m: m.group(1) + '-' + m.group(2), s)


def num(s):
    return sorted(re.findall(r'\d+(?:\.\d+)?', norm(s)))


def words(s):
    return re.findall(r'[a-z]+', norm(s))


def ok(old, new):
    if not new or new.strip() == old.strip():
        return False, 'unchanged'
    if num(old) != num(new):
        return False, f'numbers differ {num(old)} vs {num(new)}'
    ow = set(words(old))
    for w in set(words(new)) - ow:
        if w in UNITS:
            continue
        if w in GUARDED:
            if any(difflib.SequenceMatcher(None, w, o).ratio() >= 0.8 for o in ow):
                continue  # spelling fix of a word that is there (SOKCET -> Socket, ORANG -> Orange)
            return False, f'adds "{w}"'
        if not any(difflib.SequenceMatcher(None, w, o).ratio() >= 0.75 for o in ow):
            return False, f'new word "{w}"'
    if not any(len(w) >= 3 and w not in UNITS for w in words(new)):
        return False, 'no item word'
    return True, ''


rows, rej = [], []
for i in (1, 2):
    src = {r['tmpl_id']: r['name'] for r in csv.DictReader(open(W / f'data/r3_in_{i}.csv', encoding='utf-8-sig'))}
    for r in csv.DictReader(open(W / f'data/r3_out_{i}.csv', encoding='utf-8-sig')):
        t = r['tmpl_id'].strip(); old = src.get(t)
        if old is None:
            continue
        good, why = ok(old, r['new_name'])
        if good and not re.search(r'[|~]', r['new_name']):
            rows.append([int(t), {'name': r['new_name'].strip()}])
        elif why != 'unchanged':
            rej.append({'tmpl_id': t, 'old': old, 'new': r['new_name'], 'why': why})
json.dump(rows, open(W / 'data/r3_final_updates.json', 'w', encoding='utf-8'), ensure_ascii=False)
with open(W / 'data/r3_rejected.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['tmpl_id', 'old', 'new', 'why']); w.writeheader(); w.writerows(rej)
s = '~'.join(f"{t}|{u['name']}||" for t, u in rows)
open(W / 'data/r3_c_updates.txt', 'w', encoding='utf-8').write(s)
ids = [t for t, _ in rows]
print('accepted', len(rows), 'rejected', len(rej), 'CHECK', len(ids), sum(ids), functools.reduce(lambda a, b: a ^ b, ids, 0), 'size', len(s))
