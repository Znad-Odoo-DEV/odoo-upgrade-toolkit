"""Round-4 post-run verification. Usage: python -I lib/verify_r4.py <work_dir> <post_extract.json>
BEFORE = data/r4_extract.json, AFTER = given file. Plans: r4_final_merge / r4_final_variants (fallback r4_merge /
r4_variants) and r4_renames. Local files only. Writes reports/verify_r4.md."""
import json
import os
import sys
from collections import defaultdict

W = sys.argv[1] if len(sys.argv) > 1 else '.'
POST = sys.argv[2] if len(sys.argv) > 2 else os.path.join(W, 'data', 'post_extract.json')
D = os.path.join(W, 'data')


def J(p):
    return json.load(open(p, encoding='utf-8'))


def plan(*names):
    for n in names:
        p = os.path.join(D, n)
        if os.path.exists(p):
            return J(p), n
    return [], '(none)'


def rid(x):
    return x[0] if isinstance(x, (list, tuple)) else x


pre = J(os.path.join(D, 'r4_extract.json'))
post = J(POST)
mer, mer_n = plan('r4_final_merge.json', 'r4_merge.json')
var, var_n = plan('r4_final_variants.json', 'r4_variants.json')
ren, ren_n = plan('r4_renames.json')

pT, pV = {t['id']: t for t in pre['templates']}, {v['id']: v for v in pre['variants']}
qT, qV = {t['id']: t for t in post['templates']}, {v['id']: v for v in post['variants']}
qPT, qVAL = {p['id']: p for p in post['ptav']}, {v['id']: v for v in post['values']}


def varvals(v, PT, VAL):
    d = {}
    for i in v['product_template_attribute_value_ids']:
        p = PT.get(i)
        if p:
            vid, disp = p['product_attribute_value_id']
            d[p['attribute_id'][1]] = VAL[vid]['name'] if vid in VAL else disp.split(': ', 1)[-1]
    return d


def tmpl_of(vid):
    v = pV.get(vid) or qV.get(vid)
    return rid(v['product_tmpl_id']) if v else None


report, summary, stats = [], [], {}
out = report.append


def section(name, res):
    c = defaultdict(int)
    for st, _ in res:
        c[st] += 1
    stats[name] = dict(c)
    out(f'### {name}')
    out(' | '.join(f'{k}: {v}' for k, v in sorted(c.items())) + f' (total {len(res)})')
    bad = [m for st, m in res if st in ('MISSING', 'WRONG')]
    if bad:
        out('')
        out('First 20 problems:')
        out('\n'.join(f'- {m}' for m in bad[:20]))
    out('')
    summary.append(f'{name}: ' + ', '.join(f'{k}={v}' for k, v in sorted(c.items())))


merge_dups = {d for m in mer for d in m['dups']}
var_masters = {x['master'] for x in var}
var_arch = {i['var'] for x in var for i in x['items']} - var_masters
var_names = defaultdict(set)
for x in var:
    t = tmpl_of(x['master'])
    if t:
        var_names[t].add(x['name'])
ren_by = {t: n['name'] for t, n in ren}

out('# Round 4 verification')
out(f"Before: data/r4_extract.json ({pre['db']}, {pre['at']}); after: {os.path.relpath(POST, W)} ({post['db']}, {post['at']})")
out(f'Plans used: merge={mer_n}, variants={var_n}, renames={ren_n}')
out(f'Active templates {len(pT)} -> {len(qT)}; active variants {len(pV)} -> {len(qV)}.')
if pre['at'] == post['at']:
    out('NOTE: the after extract has the same timestamp as the before extract (identical state).')
out('')
out('## 1. Plans')

# merge
res = []
q_codes = defaultdict(list)
for v in qV.values():
    if v.get('default_code'):
        q_codes[v['default_code']].append(v['id'])
for m in mer:
    g, ms = m['g'], m['master']
    for d in m['dups']:
        res.append(('MISSING', f'{g}: dup {d} still active') if d in qV else ('OK', ''))
    if ms in qV:
        res.append(('OK', ''))
    else:
        code = (pV.get(ms) or {}).get('default_code')
        if code and any(i != ms for i in q_codes.get(code, [])):
            res.append(('OK', ''))
        else:
            res.append(('WRONG', f'{g}: master {ms} not active and no variant with its old reference {code!r}'))
section(f'{mer_n} (dups inactive, master active or converted)', res)

# variants
res = []
for x in var:
    tk, mv = x['tk'], x['master']
    t = tmpl_of(mv)
    if t is None:
        res.append(('WRONG', f'{tk}: master {mv} unknown in both extracts'))
        continue
    for i in x['items']:
        if i['var'] != mv:
            res.append(('MISSING', f'{tk}: item {i["var"]} still active') if i['var'] in qV else ('OK', ''))
        d_want = dict(zip(x['attrs'], i['vals']))
        found = any(rid(v['product_tmpl_id']) == t and varvals(v, qPT, qVAL) == d_want for v in qV.values())
        res.append(('OK', '') if found else ('MISSING', f'{tk}: no active variant on tmpl {t} with {d_want}'))
    nm, old = qT.get(t, {}).get('name'), pT.get(t, {}).get('name')
    res.append(('OK', '') if nm == x['name'] else
               ('MISSING' if nm == old else 'WRONG', f'{tk}: tmpl {t} name {nm!r}, want {x["name"]!r}'))
section(f'{var_n} (items archived, combos exist, name)', res)

# renames
res = []
for t, n in ren:
    want, q = n['name'], qT.get(t)
    if q is None:
        res.append(('MISSING', f'tmpl {t} not active in after extract'))
    elif q['name'] == want or q['name'] in var_names.get(t, ()):
        res.append(('OK', ''))
    else:
        res.append(('MISSING' if q['name'] == (pT.get(t) or {}).get('name') else 'WRONG',
                    f'tmpl {t}: want {want!r}, now {q["name"]!r}'))
section(f'{ren_n} (template name)', res)

# unexpected
out('## 2. Unexpected deactivations')
exp_gone_v = merge_dups | var_arch | {m['master'] for m in mer} | var_masters
gone_v = [v for i, v in pV.items() if i not in qV]
unexp_v = [v for v in gone_v if v['id'] not in exp_gone_v]
gone_t = [t for i, t in pT.items() if i not in qT]
vs_by_t = defaultdict(list)
for v in pre['variants']:
    vs_by_t[rid(v['product_tmpl_id'])].append(v['id'])
unexp_t = [t for t in gone_t if not (vs_by_t.get(t['id']) and all(v in exp_gone_v for v in vs_by_t[t['id']]))]
out(f'- Templates inactive now: {len(gone_t)}; in no plan: **{len(unexp_t)}**')
out('\n'.join(f'  - tmpl {t["id"]} {t["name"]!r}' for t in unexp_t[:20]))
out(f'- Variants inactive now: {len(gone_v)}; in no plan: **{len(unexp_v)}**')
out('\n'.join(f'  - variant {v["id"]} {v["display_name"]!r}' for v in unexp_v[:20]))
n_name = [(i, pT[i]['name'], q['name']) for i, q in qT.items() if i in pT and q['name'] != pT[i]['name']
          and q['name'] != ren_by.get(i) and q['name'] not in var_names.get(i, ())]
out(f'- Name changes not in any plan: **{len(n_name)}**')
out('\n'.join(f'  - tmpl {i}: {a!r} -> {b!r}' for i, a, b in n_name[:20]))
out('')
summary.append(f'Unexpected: templates gone={len(unexp_t)}, variants gone={len(unexp_v)}, names={len(n_name)}')

# stock
out('## 3. Stock (quantity per company)')


def bycomp(ex):
    d = defaultdict(float)
    for q in ex['quants']:
        d[q['company_id'][1]] += q.get('quantity:sum') or 0
    return d


a, b = bycomp(pre), bycomp(post)
out('| Company | Before | After | Diff |')
out('|---|---:|---:|---:|')
sd = 0
for c in sorted(set(a) | set(b)):
    df = b.get(c, 0) - a.get(c, 0)
    sd += abs(df) > 1e-6
    out(f'| {c} | {a.get(c, 0):g} | {b.get(c, 0):g} | {df:+g} |')
out(f'| Total | {sum(a.values()):g} | {sum(b.values()):g} | {sum(b.values()) - sum(a.values()):+g} |')
inact = [q for q in post['quants'] if (q.get('quantity:sum') or 0) != 0 and rid(q['product_id']) not in qV]
out('')
out(f'Inactive products holding stock (must be 0): **{len(inact)}**')
out('\n'.join(f'- {q["product_id"][1]} ({q["company_id"][1]}): {q["quantity:sum"]:g}' for q in inact[:20]))
out('')
summary.append(f'Stock: companies with qty diff={sd}, inactive holders={len(inact)}')

# variants
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
out('\n'.join(f'- tmpl {t} [{qT.get(t, {}).get("name")}]: variants {ids}' for t, ids in dups[:20]))
colon = [v for v in post['values'] if ': ' in v['name']]
out(f"Attribute values containing ': ' (must be 0): **{len(colon)}**")
out('\n'.join(f'- value {v["id"]} {v["name"]!r} ({v["attribute_id"][1]})' for v in colon[:20]))
out('')
summary.append(f'Variants: duplicate combos={len(dups)}, values with ": "={len(colon)}')

problems = sum(c.get('MISSING', 0) + c.get('WRONG', 0) for c in stats.values())
total = sum(sum(c.values()) for c in stats.values())
oks = sum(c.get('OK', 0) for c in stats.values())
out('## Verdict')
out(f'{problems} plan problems (MISSING/WRONG), {oks}/{total} OK.')
os.makedirs(os.path.join(W, 'reports'), exist_ok=True)
open(os.path.join(W, 'reports', 'verify_r4.md'), 'w', encoding='utf-8').write('\n'.join(report) + '\n')
print('\n'.join(summary))
print(f'Plan items OK {oks}/{total}, problems {problems}. Report: reports/verify_r4.md')
