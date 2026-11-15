"""Final client report: one row per ORIGINAL product and what happened to it.

python -I lib/final_report.py <work_dir> <before.json|csv> <after_extract.json> <out.xlsx> [log.json]
Reads only local files. work_dir holds data/*merge*.json, data/r7_plan.json, garbage lists.
"""
import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


def load_before(path):
    """-> {var_id: dict(id, tmpl, code, name, category, unit)}"""
    out = {}
    if path.lower().endswith('.csv'):
        for r in csv.DictReader(open(path, encoding='utf-8-sig')):
            out[int(r['var_id'])] = dict(
                id=int(r['var_id']), tmpl=int(r['tmpl_id'] or 0),
                code=(r['default_code'] or '').strip(), name=(r['name'] or '').strip(),
                category=r['category'] or '', unit=r['x_unit'] or r['uom'] or '')
        return out
    e = json.load(open(path, encoding='utf-8'))
    tm = {t['id']: t for t in e['product_template']}
    for v in e['product_product']:
        t = tm.get(v['product_tmpl_id'][0], {})
        out[v['id']] = dict(
            id=v['id'], tmpl=v['product_tmpl_id'][0], code=(v.get('default_code') or '').strip(),
            name=(t.get('name') or v['product_tmpl_id'][1] or '').strip(),
            category=(t.get('categ_id') or [0, ''])[1] if t.get('categ_id') else '',
            unit=(t.get('x_unit') or (t.get('uom_id') or [0, ''])[1] or ''))
    return out


def load_merges(data):
    """dup id -> [(source, master id)] from every merge file (var ids)."""
    mp = defaultdict(list)

    def add(src, groups):
        for g in groups:
            for d in g.get('dups', []):
                if d != g['master']:
                    mp[d].append((src, g['master']))
    for f in sorted(glob.glob(os.path.join(data, '*final_merge*.json'))):
        add(os.path.basename(f), json.load(open(f, encoding='utf-8')))
    f = os.path.join(data, 'plan_merge.json')
    if os.path.exists(f):
        add('plan_merge.json', json.load(open(f, encoding='utf-8')))
    f = os.path.join(data, 'r7_plan.json')
    if os.path.exists(f):
        add('r7_plan.json', json.load(open(f, encoding='utf-8')).get('merges', []))
    f = os.path.join(data, 'dev0_only_merges_not_for_production.csv')  # g=R<n>-<master>
    if os.path.exists(f):
        for r in csv.DictReader(open(f, encoding='utf-8-sig')):
            m = re.search(r'-(\d+)$', r['g'])
            if m:
                for d in re.findall(r'\d+', r['dups_merged_on_dev0']):
                    if d != m.group(1):
                        mp[int(d)].append(('dev0_only_merges', int(m.group(1))))
    for f in sorted(glob.glob(os.path.join(data, 'r*_c_merge*.txt'))):  # g|master|dup,dup
        for rec in open(f, encoding='utf-8').read().split('~'):
            p = rec.strip().split('|')
            if len(p) >= 3 and p[1].isdigit():
                for d in re.findall(r'\d+', p[2]):
                    if int(d) != int(p[1]):
                        mp[int(d)].append((os.path.basename(f), int(p[1])))
    return mp


def load_archived(data):
    ids = set()
    for f in glob.glob(os.path.join(data, 'r*_final_garbage.json')):
        try:
            x = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        for g in x:
            if isinstance(g, int):
                ids.add(g)
            elif isinstance(g, dict):
                for k in ('id', 'var', 'v'):
                    if isinstance(g.get(k), int):
                        ids.add(g[k])
                ids.update(i for i in g.get('ids', []) if isinstance(i, int))
    return ids


def log_archived_templates(log_p):
    """Template ids the executor log records as archived (kind 'garbage', key t = template id)."""
    out = set()
    for r in json.load(open(log_p, encoding='utf-8')):
        if r.get('kind') == 'garbage' and r.get('archived') and not r.get('errs') and not r.get('skipped'):
            out.add(r['t'])
    return out


def add_log(mp, log_p):
    """Executor log edges go first in each chain (preferred over the plan files)."""
    for r in json.load(open(log_p, encoding='utf-8')):
        if r.get('skipped'):  # errs are only post-checks: the action was done
            continue
        k = r.get('kind')
        if k == 'variant':
            for c in r.get('converted') or []:
                if c[0] != c[1]:
                    mp[c[0]].insert(0, ('log-conv', c[1]))
        elif k in ('merge', 'merge7'):
            for d in r.get('dups') or []:
                if d != r.get('master'):
                    mp[d].insert(0, ('log-merge', r['master']))


# Manual traces verified by hand (id -> [variant id, note]); kept in the local data folder, never in the code.
_mt = os.path.join(sys.argv[1], 'data', 'manual_trace.json')
MANUAL = {int(k): tuple(v) for k, v in json.load(open(_mt, encoding='utf-8')).items()} if os.path.exists(_mt) else {}


def main(work, before_p, after_p, out_p, log_p=None):
    data = os.path.join(work, 'data')
    before = load_before(before_p)
    A = json.load(open(after_p, encoding='utf-8'))
    av = {v['id']: v for v in A['variants']}
    at = {t['id']: t for t in A['templates']}
    ptav = {p['id']: p for p in A['ptav']}
    cats = {c['id']: c for c in A['categories']}
    qty = defaultdict(float)
    for q in A['qty']:
        if q.get('product_id'):
            qty[q['product_id'][0]] += q.get('quantity:sum') or 0
    codes = defaultdict(list)
    for v in av.values():
        if v.get('default_code'):
            codes[v['default_code'].strip()].append(v['id'])
    mp = load_merges(data)
    if log_p:
        add_log(mp, log_p)
    archived = load_archived(data)
    arch_t = log_archived_templates(log_p) if log_p else set()

    def attrs_of(v):
        parts = [(ptav[i]['attribute_id'][1], ptav[i]['name'])
                 for i in v['product_template_attribute_value_ids'] if i in ptav]
        return ', '.join('%s: %s' % p for p in sorted(parts))

    def resolve(i, seen):
        """-> (variant id|None, how) following merge chains, then default_code."""
        if i in av:
            return i, 'id'
        for src, m in mp.get(i, []):
            if m in seen:
                continue
            r, how = resolve(m, seen | {i})
            if r:
                # Merged if any edge of the chain is a duplicate merge; conversions only -> 'conv'
                if src != 'log-conv' or how in ('merge', 'merge-code'):
                    return r, 'merge'
                return r, 'conv'
        if i in MANUAL:
            return MANUAL[i][0], 'manual'
        c = before.get(i, {}).get('code', '')
        if c and len(codes.get(c, [])) == 1:
            return codes[c][0], 'code'
        if c and any(src == 'log-conv' for src, _m in mp.get(i, [])):
            # The log shows this product was converted into a new variant that was recreated later
            # (its id is gone). Among variants sharing the code, only ones that are not an original
            # product id can be that new variant; accept only if exactly one is left.
            new = [x for x in codes.get(c, []) if x not in before]
            if len(new) == 1:
                return new[0], 'code'
        return None, None

    vcount = defaultdict(int)
    for v in av.values():
        vcount[v['product_tmpl_id'][0]] += 1

    def cat_of(t):
        cid = (t.get('categ_id') or [0, ''])
        return cats.get(cid[0], {}).get('complete_name') or (cid[1] if len(cid) > 1 else '')

    rows = []
    mapped_to = defaultdict(int)
    for i in sorted(before):
        b = before[i]
        r, how = resolve(i, frozenset())
        note = ''
        if r is None:
            via_log = b['tmpl'] in arch_t
            st = 'Archived' if (i in archived or via_log) else 'Check'
            note = (('Archived on production (run log: template %s).' % b['tmpl']) if via_log and st == 'Archived'
                    else 'In the archive list.' if st == 'Archived'
                    else 'Not found after the cleanup and not traceable through the merge files.')
            rows.append([i, b['code'], b['name'], b['category'], st, None, '', '', '', None, note])
            continue
        v = av[r]
        tid = v['product_tmpl_id'][0]
        t = at.get(tid, {})
        tname = t.get('name') or v['product_tmpl_id'][1]
        attrs = attrs_of(v)
        if how == 'merge':
            st = 'Merged into another item'
            note = 'Same item as product %s; stock and history moved there.' % r
        elif vcount[tid] > 1:
            st = 'Moved into a family'
            note = 'Now a variant of "%s" (%d variants).' % (tname, vcount[tid])
        else:
            st = 'Kept'
        if how == 'manual':
            note = (note + ' ' if note else '') + MANUAL[i][1]
        if how == 'code' and r != i:
            note = (note + ' ' if note else '') + 'Matched by internal reference (product id changed to %s).' % r
        if (st != 'Merged into another item' and b['name'] and tname
                and b['name'].strip().lower() != tname.strip().lower()):
            note = (note + ' ' if note else '') + 'Renamed.'
        mapped_to[r] += 1
        rows.append([i, b['code'], b['name'], b['category'], st, r, tname, attrs, cat_of(t), qty.get(r, 0), note])

    wb = Workbook()
    ws = wb.active
    ws.title = 'Items'
    ws.append(['Original ID', 'Original code', 'Original name', 'Original category', 'Status',
               'Now: product id', 'Now: template name', 'Now: attributes', 'Now: category',
               'Stock qty', 'Notes'])
    for r in rows:
        ws.append(r)

    t2 = wb.create_sheet('Templates')
    t2.append(['Template id', 'Template name', 'Variants', 'Attributes', 'Category', 'Original items now here'])
    tattr = defaultdict(set)
    for p in A['lines']:
        tattr[p['product_tmpl_id'][0]].add(p['attribute_id'][1])
    tfrom = defaultdict(int)
    for r, n in mapped_to.items():
        tfrom[av[r]['product_tmpl_id'][0]] += n
    for t in sorted(A['templates'], key=lambda x: x['id']):
        t2.append([t['id'], t['name'], vcount.get(t['id'], 0), ', '.join(sorted(tattr.get(t['id'], []))),
                   cat_of(t), tfrom.get(t['id'], 0)])

    cnt = defaultdict(int)
    for r in rows:
        cnt[r[4]] += 1
    renamed = sum(1 for r in rows if 'Renamed.' in r[10])
    catmoves = sum(1 for r in rows if r[5] and r[3] and r[8] and r[3].strip() != r[8].strip())
    families = sum(1 for t in at if vcount.get(t, 0) > 1)
    s = wb.create_sheet('Summary')
    s.append(['Measure', 'Value'])
    summary = [
        ('Products before (templates)', len({b['tmpl'] for b in before.values()})),
        ('Products before (variants)', len(before)),
        ('Products after (templates)', len(A['templates'])),
        ('Products after (variants)', len(A['variants'])),
        ('Original items: Kept', cnt['Kept']),
        ('Original items: Moved into a family', cnt['Moved into a family']),
        ('Original items: Merged into another item', cnt['Merged into another item']),
        ('Original items: Archived', cnt['Archived']),
        ('Original items: Check (not traced)', cnt['Check']),
        ('Families (templates with 2+ variants)', families),
        ('Items renamed', renamed),
        ('Items whose category changed', catmoves),
    ]
    for k, v in summary:
        s.append([k, v])

    fill = PatternFill('solid', fgColor='DDEBF7')
    warn = PatternFill('solid', fgColor='FFF2CC')
    for w in (ws, t2, s):
        for c in w[1]:
            c.font = Font(bold=True)
            c.fill = fill
        w.freeze_panes = 'A2'
        w.auto_filter.ref = w.dimensions
        for ci in range(1, w.max_column + 1):
            m = max(len(str(c.value)) if c.value is not None else 0 for c in w[get_column_letter(ci)])
            w.column_dimensions[get_column_letter(ci)].width = min(max(10, m + 2), 60)
    for row in ws.iter_rows(min_row=2):
        if row[4].value == 'Check':
            for c in row:
                c.fill = warn
    wb.save(out_p)
    for k, v in summary:
        print('%s: %s' % (k, v))
    chk = [r for r in rows if r[4] == 'Check']
    for r in chk[:10]:
        print('Check', r[0], r[2][:50], '|', r[1])


if __name__ == '__main__':
    if len(sys.argv) not in (5, 6):
        sys.exit(__doc__)
    main(*sys.argv[1:])
