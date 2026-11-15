"""Round 5 (last pass): consolidate data/r5_out/batch_*.csv into plans with guards.
Usage: python -I lib/r5_build.py <work_dir>
Actions: JOIN T<id> / NEW N-<slug> / SINGLE / MERGE / KEEP (see reports/R5_RULES.md).
Guards: units, PO price ratio, values written in the name (else Not Specified), no material/system word from the template that
the item name lacks, every number of the old name kept in the template name or a value, catalogue attributes only.
Outputs: data/r5_merge.json, data/r5_variants.json, data/r5_renames.json, data/r5_held.csv, data/r5_ns_log.json,
compact data/r5_c_merge.txt, data/r5_c_variants.txt, data/r5_c_renames.txt
"""
import csv, json, re, sys, functools
from collections import defaultdict, Counter
from pathlib import Path

W = Path(sys.argv[1])
sys.path.insert(0, str(W / 'lib'))
from units import unit_key  # noqa: E402
from dedup_lib import normalise  # noqa: E402

rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
X = json.load(open(W / 'data/r4_extract.json', encoding='utf-8'))
m2o = lambda v: v[0] if isinstance(v, list) and v else None
T = {t['id']: t for t in X['templates']}
V = {v['id']: v for v in X['variants']}
v2t = {v['id']: m2o(v['product_tmpl_id']) for v in X['variants']}
lastprice = {m2o(g['product_id']): g.get('price_unit:max') or 0 for g in X['pol']}
hist = defaultdict(int)
for k in ('moves', 'pol', 'mr', 'bills'):
    for g in X[k]:
        hist[m2o(g['product_id'])] += g['__count']
CAT = {r['canonical_attribute'] for r in rd(W / 'data/attribute_catalogue.csv')} | {'Steps', 'Model', 'Power', 'Volume', 'Weight', 'Pack'}
NS = 'Not Specified'
MAT = {'upvc', 'ppr', 'hp', 'gi', 'ms', 'ss', 'brass', 'copper', 'skolon', 'soundproof', 'hdpe', 'pex', 'cpvc', 'pvc', 'aluminium',
       'steel', 'galvanized', 'cu', 'xlpe', 'swa', 'fire', 'drainage'}

# variant templates after round 4 (data/r5_in/templates.txt)
TT = {}
for ln in open(W / 'data/r5_in/templates.txt', encoding='utf-8'):
    if ln.startswith('#') or not ln.strip():
        continue
    tk, name, unit, attrs, vars_ = [x.strip() for x in ln.split(' | ', 4)]
    attrs = [a.strip() for a in attrs.split(',')]
    ex = {}
    for e in vars_.split('; '):
        if '=' in e:
            v, vals = e.split('=', 1); ex[tuple(vals.split('/'))] = int(v)
    TT[int(tk[1:])] = {'name': name, 'unit': unit, 'attrs': attrs, 'exist': ex}


def parse(s):
    out = {}
    for kv in (s or '').split(';'):
        if '=' in kv:
            a, v = kv.split('=', 1); out[a.strip()] = v.strip()
    return out


def _nums(s):
    s = re.sub(r'(\d)\.(\d+/\d+)', lambda m: m.group(1) + ' ' + m.group(2), (s or '').lower())
    out = set()
    for a, b in re.findall(r'(\d+)\s*/\s*(\d+)', s):
        if int(b):
            out.add(round(int(a) / int(b), 4))
    for x in re.findall(r'\d+(?:\.\d+)?', s):
        out.add(round(float(x), 4))
    return out


def written(name, val):
    if val == NS:
        return True
    v_nums = _nums(val)
    if v_nums:
        return v_nums <= _nums(name)
    nm = set(re.findall(r'[a-z]+', normalise(name)))
    if {'gray', 'gary'} & nm: nm.add('grey')
    alpha = [k for k in re.findall(r'[a-z]+', normalise(val)) if len(k) > 2]
    return any(k in nm for k in alpha) if alpha else True


def kept(old, tname, vals):
    """every number of the old name appears in the new template name or a value"""
    return _nums(old) <= (_nums(tname) | set().union(*[_nums(x) for x in vals.values()]) if vals else _nums(tname))


KEYW = MAT | {'grey', 'gray', 'orange', 'black', 'white', 'red', 'blue', 'yellow', 'green', 'silver', 'brown', 'beige', 'clear',
               'male', 'female', 'threaded', 'socket', 'reducer', 'reducing', 'equal', 'bush', 'cordless', 'corded', 'rental',
               'daily', 'monthly', 'hourly', 'weekly', 'overtime', 'rr', 'ss', 'sch', 'flexible', 'rigid', 'single', 'double', 'twin'}


def words_lost(old, tname, vals):
    """material/colour/function words of the old name that appear nowhere in the template name or values"""
    w = lambda s: set(re.findall(r'[a-z]+', normalise(s or '').replace('gray', 'grey')))
    have = w(tname) | set().union(*[w(x) for x in vals.values()]) if vals else w(tname)
    return sorted((w(old) & KEYW) - have)


def mat_ok(item, tname):
    words = lambda s: set(re.findall(r'[a-z]+', normalise(s)))
    return not ((words(tname) & MAT) - words(item))


rows = []
for p in sorted(W.glob('data/r5_out/batch_*.csv')) + sorted(W.glob('data/r5_out/fix_*.csv')):
    rows += rd(p)
_last = {}
for r in rows:  # a QA correction (fix_*.csv, read last) replaces the batch row of the same item
    _last[(r.get('var_id') or '').strip()] = r
rows = list(_last.values())
held = []
def hold(v, act, why):
    held.append({'var_id': v, 'name': T[v2t[v]]['name'] if v in v2t else '', 'action': act, 'why': why})

parent = {}
def find(x):
    while parent.get(x, x) != x:
        x = parent[x]
    return x
def link(a, b):
    parent[find(a)] = find(b)

renames, joins, news, ns_log = {}, defaultdict(list), defaultdict(list), []
seen_v = set()
for r in rows:
    act = (r['action'] or '').strip().upper()
    act = {'J': 'JOIN', 'N': 'NEW', 'M': 'MERGE', 'K': 'KEEP', 'S': 'SINGLE'}.get(act[:1], act)
    try:
        v = int(float(r['var_id']))
    except ValueError:
        continue
    if v not in V or v in seen_v:
        continue
    seen_v.add(v)
    t = v2t[v]; nm = T[t]['name']
    if act == 'KEEP':
        nn = (r.get('new_name') or '').strip()
        if nn and nn != nm and _nums(nn) == _nums(nm):
            renames[t] = nn
        continue
    if act == 'MERGE':
        try:
            d = int(float(r['dup_of']))
        except (ValueError, TypeError):
            hold(v, act, 'merge without dup_of'); continue
        if d not in V or d == v:
            hold(v, act, f'dup_of {d} unknown or itself'); continue
        ua, ub = unit_key(T[t]['x_unit']), unit_key(T[v2t[d]]['x_unit'])
        pa, pb = lastprice.get(v, 0), lastprice.get(d, 0)
        if ua != '?' and ub != '?' and ua != ub:
            hold(v, act, f'units differ {T[t]["x_unit"]} vs {T[v2t[d]]["x_unit"]}'); continue
        if pa and pb and min(pa, pb) >= 0.01 and max(pa, pb) / min(pa, pb) > 3:  # 0.0001 = placeholder price, not a price
            hold(v, act, f'last PO price {pa} vs {pb} (>3x)'); continue
        tgt = TT.get(v2t[d])
        if tgt and not mat_ok(nm, tgt['name']):
            hold(v, act, f'material of "{tgt["name"]}" not written in the name'); continue
        link(v, d); continue
    vals = parse(r.get('attributes'))
    if not vals or any(a not in CAT for a in vals) or any(re.search(r'[|~#^;=]', x) for x in vals.values()):
        hold(v, act, f'attributes not usable: {r.get("attributes")}'); continue
    for a, x in list(vals.items()):
        if not written(nm, x):
            ns_log.append({'var_id': v, 'name': nm, 'attribute': a, 'agent_value': x}); vals[a] = NS
    k = (r['template_key'] or '').strip()
    if act == 'JOIN' and k[:1] == 'T' and k[1:].isdigit() and int(k[1:]) in TT:
        tt = int(k[1:]); tp = TT[tt]
        if set(vals) != set(tp['attrs']):
            hold(v, act, f'attributes {sorted(vals)} != template {tp["attrs"]}'); continue
        if not mat_ok(nm, tp['name']):
            hold(v, act, f'material of "{tp["name"]}" not written in the name'); continue
        lw = words_lost(nm, tp['name'], vals)
        if lw:
            hold(v, act, f'words lost {lw}'); continue
        if not kept(nm, tp['name'], vals):
            hold(v, act, f'numbers {sorted(_nums(nm))} not all in "{tp["name"]}" + values'); continue
        uk, ut = unit_key(T[t]['x_unit']), unit_key(tp['unit'])
        if uk != '?' and ut != '?' and uk != ut:
            hold(v, act, f'unit {T[t]["x_unit"]} vs template {tp["unit"]}'); continue
        joins[tt].append((v, vals))
    elif act in ('NEW', 'JOIN', 'SINGLE'):
        tn = (r.get('template_name') or '').strip()
        if not tn or re.search(r'[|~#^]', tn):
            hold(v, act, 'template without usable name'); continue
        lw = words_lost(nm, tn, vals)
        if lw:
            hold(v, act, f'words lost {lw}'); continue
        if not kept(nm, tn, vals):
            hold(v, act, f'numbers {sorted(_nums(nm))} not all in "{tn}" + values'); continue
        if not mat_ok(nm, tn):
            hold(v, act, f'template name "{tn}" adds a material'); continue
        key = (re.sub(r'[^a-z0-9]', '', tn.lower()), unit_key(T[t]['x_unit']))  # SINGLEs with the same name+unit form one family
        news[key].append((v, vals, tn))
    else:
        hold(v, act, f'unknown action {act}')

# a new template named like an existing variant template: join it when the attributes match, else hold
tt_by = defaultdict(list)
for tt, tp in TT.items():
    tt_by[re.sub(r'[^a-z0-9]', '', tp['name'].lower())].append(tt)
for key in list(news):
    for tt in tt_by.get(key[0], []):
        tp = TT[tt]; ut = unit_key(tp['unit'])
        if key[1] != '?' and ut != '?' and key[1] != ut:
            continue
        items = news.pop(key)
        # one template per item type: the existing template gets the missing attributes ("Not Specified" on its variants)
        extra = sorted({a for _, vals, _ in items for a in vals} - set(tp['attrs']))
        if extra:
            tp['attrs'] = tp['attrs'] + extra
            tp['exist'] = {c + (NS,) * len(extra): i for c, i in tp['exist'].items()}
            tp.setdefault('extend', []).extend(extra)
        for v, vals, n in items:
            joins[tt].append((v, {a: vals.get(a, NS) for a in tp['attrs']}))
        break

plan_var = []
for tt, items in joins.items():
    tp = TT[tt]; attrs = tp['attrs']
    exist = dict(tp['exist'])
    master = next(iter(exist.values()))
    new_items = []
    for v, vals in items:
        combo = tuple(vals[a] for a in attrs)
        if combo in exist:
            link(v, exist[combo]); continue
        exist[combo] = v; new_items.append({'var': v, 'vals': list(combo)})
    if new_items:
        mvals = next(c for c, i in tp['exist'].items() if i == master)
        plan_var.append({'tk': f'T-{tt}', 'name': tp['name'], 'attrs': attrs, 'master': master, 'items': [{'var': master, 'vals': list(mvals)}] + new_items})
for key, items in news.items():
    attrs = sorted({a for _, vals, _ in items for a in vals})
    items.sort(key=lambda x: -hist[x[0]])
    seen, its = {}, []
    for v, vals, n in items:
        vv = {a: vals.get(a, NS) for a in attrs}
        if set(vals) != set(attrs):
            missing = set(attrs) - set(vals)
            ns_log.append({'var_id': v, 'name': T[v2t[v]]['name'], 'attribute': ','.join(sorted(missing)), 'agent_value': '(missing)'})
        combo = tuple(vv[a] for a in attrs)
        if combo in seen:
            link(v, seen[combo]); continue
        seen[combo] = v; its.append({'var': v, 'vals': list(combo)})
    # a NEW family of one item becomes a SINGLE template (the spec still leaves the name)
    tk = f'N-{key[0][:40]}-{key[1]}' if len(its) > 1 else f'S-{its[0]["var"]}'
    plan_var.append({'tk': tk, 'name': items[0][2], 'attrs': attrs, 'master': its[0]['var'], 'items': its})

# a new template name already used by another template (other unit): add the unit, e.g. "Black Tape (Box)"
ULAB = {'EA': 'Each', 'M': 'Per Metre', 'M2': 'Sqm', 'M3': 'Cum', 'L': 'Litre', 'GAL': 'Gallon', 'KG': 'Per Kg', 'TON': 'Ton',
        'ROLL': 'Roll', 'BOX': 'Box', 'CTN': 'Carton', 'PKT': 'Packet', 'DRUM': 'Drum', 'BAG': 'Bag', 'SET': 'Set', 'PAIR': 'Pair',
        'BUNDLE': 'Bundle', 'LS': 'Lump Sum', 'LENGTH': 'Length', 'SHEET': 'Sheet', 'CAN': 'Can', 'BOTTLE': 'Bottle',
        'DOZEN': 'Dozen', 'HOUR': 'Hourly'}
nkey = lambda n: re.sub(r'[^a-z0-9]', '', n.lower())
plan_tmpl = {v2t[i['var']] for p in plan_var for i in p['items'] if i['var'] in v2t} | {v2t[x] for x in parent if x in v2t}
others = defaultdict(set)  # name -> unit keys of templates that stay as they are or already exist
for tt, tp in TT.items():
    others[nkey(tp['name'])].add(unit_key(tp['unit']))
for tid, tr in T.items():
    if tid not in plan_tmpl and tr.get('active', True):
        others[nkey(tr['name'])].add(unit_key(tr['x_unit']))
cnt = Counter(nkey(p['name']) for p in plan_var if p['tk'][0] != 'T')
for p in plan_var:
    if p['tk'][0] == 'T':
        continue
    k = nkey(p['name']); uk = unit_key(T[v2t[p['master']]]['x_unit'])
    if (others.get(k) and others[k] != {uk}) or cnt[k] > 1:
        lab = ULAB.get(uk, '')  # odd units (RAW:...) get no suffix; the QA sees the clash list
        if lab and not p['name'].endswith(f'({lab})'):
            p['name'] = f"{p['name']} ({lab})"

groups = defaultdict(list)
for x in list(parent):
    r_ = find(x)
    if x != r_:
        groups[r_].append(x)
merged_away = {d for ds in groups.values() for d in ds}
plan_merge = [{'g': f'R5-{m}', 'master': m, 'dups': sorted(ds), 'rename': None} for m, ds in groups.items()]
for p in plan_var:
    p['items'] = [i for i in p['items'] if i['var'] not in merged_away or i['var'] == p['master']]
plan_var = [p for p in plan_var if p['master'] not in merged_away and (len(p['items']) >= 2 or p['tk'][0] == 'S')]
in_plan = {v2t[d] for d in merged_away} | {v2t[i['var']] for p in plan_var for i in p['items'] if i['var'] in v2t}
renames = {t: n for t, n in renames.items() if t in T and t not in in_plan and not re.search(r'[|~]', n)}

json.dump(plan_merge, open(W / 'data/r5_merge.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(plan_var, open(W / 'data/r5_variants.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump([[t, {'name': n}] for t, n in renames.items()], open(W / 'data/r5_renames.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(ns_log, open(W / 'data/r5_ns_log.json', 'w', encoding='utf-8'), ensure_ascii=False)
with open(W / 'data/r5_held.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['var_id', 'name', 'action', 'why']); w.writeheader(); w.writerows(held)
open(W / 'data/r5_c_merge.txt', 'w', encoding='utf-8').write('~'.join(f"{p['g']}|{p['master']}|{','.join(map(str, p['dups']))}|" for p in plan_merge))
open(W / 'data/r5_c_variants.txt', 'w', encoding='utf-8').write('#'.join(f"{p['tk']}|{p['name']}|{'^'.join(p['attrs'])}|{p['master']}|" + '~'.join(f"{i['var']}^{'^'.join(i['vals'])}" for i in p['items']) for p in plan_var))
open(W / 'data/r5_c_renames.txt', 'w', encoding='utf-8').write('~'.join(f"{t}|{n}||" for t, n in renames.items()))
ck = lambda ids: (len(ids), sum(ids), functools.reduce(lambda a, b: a ^ b, ids, 0))
print('rows', len(rows), 'unique', len(seen_v), '| actions', Counter((r['action'] or '').strip().upper()[:1] for r in rows))
print('merge groups', len(plan_merge), 'items merged', len(merged_away), 'CHECK', ck([p['master'] for p in plan_merge] + [d for p in plan_merge for d in p['dups']]))
print('variant templates', len(plan_var), Counter(p['tk'][0] for p in plan_var), 'items', sum(len(p['items']) for p in plan_var), 'CHECK', ck([i['var'] for p in plan_var for i in p['items']]))
print('renames', len(renames), '| held', len(held), Counter(h['why'].split(' ')[0] for h in held), '| Not Specified replacements', len(ns_log))

nm_of = lambda v: T[v2t[v]]['name'] if v in v2t else '?'
un_of = lambda v: T[v2t[v]]['x_unit'] if v in v2t else '?'
with open(W / 'data/r5_review_S.txt', 'w', encoding='utf-8') as fs, open(W / 'data/r5_review_NT.txt', 'w', encoding='utf-8') as fn:
    fs.write('# tk | NEW template name | attributes | item var_id: OLD NAME [unit] -> values\n')
    fn.write('# tk | template name | attributes | item var_id: OLD NAME [unit] -> values (T-: first item = existing master)\n')
    for p in plan_var:
        f = fs if p['tk'][0] == 'S' else fn
        f.write(f"{p['tk']} | {p['name']} | {', '.join(p['attrs'])}\n")
        for i in p['items']:
            f.write(f"    {i['var']}: {nm_of(i['var'])} [{un_of(i['var'])}] -> {' / '.join(i['vals'])}\n")
    fn.write('\n# MERGES: group | master: name [unit] <- dup: name [unit]\n')
    for p in plan_merge:
        fn.write(f"{p['g']} | {p['master']}: {nm_of(p['master'])} [{un_of(p['master'])}] <- " + '; '.join(f"{d}: {nm_of(d)} [{un_of(d)}]" for d in p['dups']) + '\n')
