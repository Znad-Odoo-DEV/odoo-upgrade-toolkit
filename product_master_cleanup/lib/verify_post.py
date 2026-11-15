"""Independent post-run verification. Usage: python -I lib/verify_post.py <work_dir> [post_extract_path]
Reads data/r2_extract.json (before) and data/post_extract.json (after) plus the round-2 plans.
Local files only. Writes reports/post_run_verification.md."""
import csv
import json
import os
import sys
from collections import defaultdict

W = sys.argv[1] if len(sys.argv) > 1 else '.'
POST = sys.argv[2] if len(sys.argv) > 2 else os.path.join(W, 'data', 'post_extract.json')


def J(p):
    return json.load(open(p, encoding='utf-8'))


pre = J(os.path.join(W, 'data', 'r2_extract.json'))
post = J(POST)
upd = J(os.path.join(W, 'data', 'r2_final_updates.json'))
mer = J(os.path.join(W, 'data', 'r2_final_merge.json'))
var = J(os.path.join(W, 'data', 'r2_final_variants.json'))
gar = J(os.path.join(W, 'data', 'r2_final_garbage.json'))
dev0_dups = set()
p = os.path.join(W, 'data', 'dev0_only_merges_not_for_production.csv')
if os.path.exists(p):
    for r in csv.DictReader(open(p, encoding='utf-8')):
        for x in r['dups_merged_on_dev0'].split():
            if x.isdigit():
                dev0_dups.add(int(x))


def rid(x):
    return x[0] if isinstance(x, (list, tuple)) else x


def index(ex):
    return ({t['id']: t for t in ex['templates']}, {v['id']: v for v in ex['variants']},
            {p_['id']: p_ for p_ in ex['ptav']}, {v['id']: v for v in ex['values']})


pT, pV, pPT, pVAL = index(pre)
qT, qV, qPT, qVAL = index(post)


def valname(ptid, PT, VAL):
    p_ = PT.get(ptid)
    if not p_:
        return None
    vid, disp = p_['product_attribute_value_id']
    return VAL[vid]['name'] if vid in VAL else disp.split(': ', 1)[-1]


def varvals(v, PT, VAL):
    d = {}
    for i in v['product_template_attribute_value_ids']:
        if i in PT:
            d[PT[i]['attribute_id'][1]] = valname(i, PT, VAL)
    return d


report, summary, plan_stats = [], [], {}


def out(s=''):
    report.append(s)


def section(name, results):
    c = defaultdict(int)
    for st, _ in results:
        c[st] += 1
    plan_stats[name] = dict(c)
    out(f'### {name}')
    out(' | '.join(f'{k}: {v}' for k, v in sorted(c.items())) + f' (total {len(results)})')
    bad = [m for st, m in results if st in ('MISSING', 'WRONG')]
    if bad:
        out('')
        out('First 20 problems:')
        for m in bad[:20]:
            out(f'- {m}')
    out('')
    summary.append(f'{name}: ' + ', '.join(f'{k}={v}' for k, v in sorted(c.items())))


# ---- sets used to decide what is expected
merge_dups = {d for m in mer for d in m['dups']}
var_items = {i['var'] for x in var for i in x['items']}
var_masters = {x['master'] for x in var}
var_archived = var_items - var_masters
garbage = set(gar)
upd_by = {t: u for t, u in upd}


def tmpl_of(vid):
    v = pV.get(vid) or qV.get(vid)
    return rid(v['product_tmpl_id']) if v else None


name_ok = defaultdict(set)  # tmpl -> names set by merge rename / variant plan
for m in mer:
    t = tmpl_of(m['master'])
    if t:
        name_ok[t].add(m['rename'])
for x in var:
    t = tmpl_of(x['master'])
    if t:
        name_ok[t].add(x['name'])

out('# Post-run verification')
out(f"Before: data/r2_extract.json ({pre['db']}, {pre['at']}); after: {os.path.relpath(POST, W)} ({post['db']}, {post['at']})")
out(f"Active templates {len(pT)} -> {len(qT)}; active variants {len(pV)} -> {len(qV)}.")
if pre['at'] == post['at']:
    out('NOTE: the post extract has the same timestamp as the before extract (identical state).')
out('')
out('## 1. Plans')

# updates
res = []
for t, u in upd:
    p0, q = pT.get(t), qT.get(t)
    if q is None:
        if t in garbage or any(tmpl_of(d) == t for d in merge_dups):
            res.append(('OK', ''))
        else:
            res.append(('MISSING', f'tmpl {t} [{(p0 or {}).get("name")}] absent from post (inactive), update cannot be checked'))
        continue
    for k, want in u.items():
        if k == 'categ_id':
            cur, old = rid(q['categ_id']), rid(p0['categ_id']) if p0 else None
        else:
            cur, old = q.get(k), (p0 or {}).get(k)
        if cur == want or (k == 'name' and cur in name_ok.get(t, ())):
            res.append(('OK', ''))
        else:
            res.append(('MISSING' if cur == old else 'WRONG', f'tmpl {t} {k}: want {want!r}, now {cur!r}'))
section('r2_final_updates (per field)', res)

# merge
res = []
for m in mer:
    g = m['g']
    for d in m['dups']:
        res.append(('MISSING', f'{g}: dup variant {d} still active') if d in qV else ('OK', ''))
    if m['master'] not in qV:
        res.append(('WRONG', f'{g}: master variant {m["master"]} not active'))
        continue
    res.append(('OK', ''))
    t = rid(qV[m['master']]['product_tmpl_id'])
    nm, old = qT.get(t, {}).get('name'), pT.get(t, {}).get('name')
    ok = {m['rename']} | name_ok.get(t, set())
    if t in upd_by and 'name' in upd_by[t]:
        ok.add(upd_by[t]['name'])
    if nm in ok:
        res.append(('OK', ''))
    else:
        res.append(('MISSING' if nm == old else 'WRONG', f'{g}: master tmpl {t} name {nm!r}, want {m["rename"]!r}'))
section('r2_final_merge (dups inactive, master active, rename)', res)

# variants
res = []
for x in var:
    tk, mv = x['tk'], x['master']
    if mv not in qV:
        res.append(('WRONG', f'{tk}: master variant {mv} not active'))
        continue
    res.append(('OK', ''))
    t = rid(qV[mv]['product_tmpl_id'])
    for i in x['items']:
        if i['var'] != mv:
            res.append(('MISSING', f'{tk}: variant {i["var"]} still active') if i['var'] in qV else ('OK', ''))
        want = list(i['vals'])
        found = False
        for v in qV.values():
            if rid(v['product_tmpl_id']) != t:
                continue
            d = varvals(v, qPT, qVAL)
            if len(d) == len(x['attrs']) and [d.get(a) for a in x['attrs']] == want:
                found = True
                break
        res.append(('OK', '') if found else
                   ('MISSING', f'{tk}: no active variant on tmpl {t} with {dict(zip(x["attrs"], want))}'))
    nm, old = qT.get(t, {}).get('name'), pT.get(t, {}).get('name')
    if nm == x['name']:
        res.append(('OK', ''))
    else:
        res.append(('MISSING' if nm == old else 'WRONG', f'{tk}: tmpl {t} name {nm!r}, want {x["name"]!r}'))
section('r2_final_variants (master active, others archived, combos exist, name)', res)

# garbage
refs = defaultdict(int)
for q_ in pre['quants']:
    if q_.get('quantity:sum'):
        refs[rid(q_['product_id'])] += 1
for k in ('moves', 'pol', 'mr', 'bills'):
    for r in pre[k]:
        refs[rid(r['product_id'])] += r.get('__count', 1)
trefs = defaultdict(int)
for v in pre['variants']:
    trefs[rid(v['product_tmpl_id'])] += refs.get(v['id'], 0)
for r in pre['vendor']:
    trefs[rid(r['product_tmpl_id'])] += r.get('__count', 1)
res = []
for t in gar:
    if t not in qT:
        res.append(('OK', ''))
    elif trefs.get(t):
        res.append(('OK', f'kept: {trefs[t]} references'))
    else:
        res.append(('MISSING', f'tmpl {t} [{qT[t]["name"]}] still active, no references'))
section('r2_final_garbage (inactive unless referenced)', res)

# dev0
res = [('MISSING', f'variant {d} still active') if d in qV else ('OK', '') for d in sorted(dev0_dups)]
section('dev0_only_merges (dups inactive)', res)

# ---- 2 unexpected
out('## 2. Unexpected changes')
garb_vars = {v['id'] for v in pre['variants'] if rid(v['product_tmpl_id']) in garbage}
exp_gone_v = merge_dups | dev0_dups | var_archived | garb_vars
gone_t = [t for i, t in pT.items() if i not in qT]


def tmpl_exp_gone(tid):
    if tid in garbage:
        return True
    vs = [v['id'] for v in pre['variants'] if rid(v['product_tmpl_id']) == tid]
    return bool(vs) and all(v in exp_gone_v for v in vs)


exp_gone_t = {t['id'] for t in gone_t if tmpl_exp_gone(t['id'])}
unexp_t = [t for t in gone_t if t['id'] not in exp_gone_t]
gone_v = [v for i, v in pV.items() if i not in qV]
unexp_v = [v for v in gone_v if v['id'] not in exp_gone_v and rid(v['product_tmpl_id']) not in exp_gone_t]
out(f'- Templates inactive now: {len(gone_t)}; in no plan: **{len(unexp_t)}**')
for t in unexp_t[:20]:
    out(f'  - tmpl {t["id"]} {t["name"]!r}')
out(f'- Variants inactive now: {len(gone_v)}; in no plan: **{len(unexp_v)}**')
for v in unexp_v[:20]:
    out(f'  - variant {v["id"]} {v["display_name"]!r}')
n_name, n_cat, ex_n, ex_c = [], [], 0, 0
for i, q in qT.items():
    p0 = pT.get(i)
    if not p0:
        continue
    if q['name'] != p0['name']:
        if upd_by.get(i, {}).get('name') == q['name'] or q['name'] in name_ok.get(i, ()):
            ex_n += 1
        else:
            n_name.append((i, p0['name'], q['name']))
    if rid(q['categ_id']) != rid(p0['categ_id']):
        if upd_by.get(i, {}).get('categ_id') == rid(q['categ_id']):
            ex_c += 1
        else:
            n_cat.append((i, p0['categ_id'][1], q['categ_id'][1]))
out(f'- Name changes: {ex_n} expected, **{len(n_name)} unexpected**')
for i, a, b in n_name[:20]:
    out(f'  - tmpl {i}: {a!r} -> {b!r}')
out(f'- Category changes: {ex_c} expected, **{len(n_cat)} unexpected**')
for i, a, b in n_cat[:20]:
    out(f'  - tmpl {i}: {a} -> {b}')
new_t = [i for i in qT if i not in pT]
out(f'- Active templates not in the before-extract: {len(new_t)}' + (f' (first: {new_t[:10]})' if new_t else ''))
out('')
summary.append(f'Unexpected: templates gone={len(unexp_t)}, variants gone={len(unexp_v)}, names={len(n_name)}, categories={len(n_cat)}')

# ---- 3 stock
out('## 3. Stock (quants grouped by company, as extracted)')


def bycomp(ex):
    d = defaultdict(float)
    for q_ in ex['quants']:
        d[q_['company_id'][1]] += q_.get('quantity:sum') or 0
    return d


a, b = bycomp(pre), bycomp(post)
out('| Company | Before | After | Diff |')
out('|---|---:|---:|---:|')
sdiff = 0
for c in sorted(set(a) | set(b)):
    df = b.get(c, 0) - a.get(c, 0)
    sdiff += abs(df) > 1e-6
    out(f'| {c} | {a.get(c, 0):g} | {b.get(c, 0):g} | {df:+g} |')
out(f'| Total | {sum(a.values()):g} | {sum(b.values()):g} | {sum(b.values()) - sum(a.values()):+g} |')
inact = [q_ for q_ in post['quants'] if (q_.get('quantity:sum') or 0) != 0 and rid(q_['product_id']) not in qV]
out('')
out(f'Products holding stock that are inactive (must be 0): **{len(inact)}**')
for q_ in inact[:20]:
    out(f'- {q_["product_id"][1]} ({q_["company_id"][1]}): {q_["quantity:sum"]:g}')
out('')
out('Stock VALUE cannot be computed from this extract (no costs); only quantities are compared.')
out('')
summary.append(f'Stock: companies with qty diff={sdiff}, inactive holders={len(inact)} (value not computable)')

# ---- 4 variants
out('## 4. Variants')
byt = defaultdict(list)
for v in post['variants']:
    byt[rid(v['product_tmpl_id'])].append(v)
dups = []
for t, vs in byt.items():
    seen = defaultdict(list)
    for v in vs:
        key = tuple(sorted((rid(qPT[i]['attribute_id']), qPT[i]['product_attribute_value_id'][0])
                           for i in v['product_template_attribute_value_ids'] if i in qPT))
        seen[key].append(v['id'])
    dups += [(t, ids) for ids in seen.values() if len(ids) > 1]
out(f'Duplicate attribute combinations inside a template (must be 0): **{len(dups)}**')
for t, ids in dups[:20]:
    out(f'- tmpl {t} [{qT.get(t, {}).get("name")}]: variants {ids}')
colon = [v for v in post['values'] if ': ' in v['name']]
colon_p = [p_ for p_ in post['ptav'] if ': ' in p_['product_attribute_value_id'][1].split(': ', 1)[-1]]
out(f"Attribute values containing ': ' (must be 0): **{len(colon)}** (same check on template-level value labels: {len(colon_p)})")
for v in colon[:20]:
    out(f'- value {v["id"]} {v["name"]!r} ({v["attribute_id"][1]})')
out('')
summary.append(f'Variants: duplicate combos={len(dups)}, values with ": "={len(colon)}')

problems = sum(c.get('MISSING', 0) + c.get('WRONG', 0) for c in plan_stats.values())
total = sum(sum(c.values()) for c in plan_stats.values())
oks = sum(c.get('OK', 0) for c in plan_stats.values())
out('## Verdict')
out(f'{problems} plan problems (MISSING/WRONG), {oks}/{total} OK.')
os.makedirs(os.path.join(W, 'reports'), exist_ok=True)
open(os.path.join(W, 'reports', 'post_run_verification.md'), 'w', encoding='utf-8').write('\n'.join(report) + '\n')
print('\n'.join(summary))
print(f'Plan items OK {oks}/{total}, problems {problems}. Report: reports/post_run_verification.md')
