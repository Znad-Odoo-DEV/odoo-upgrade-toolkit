"""Merge the review outputs into the mapping workbook (Phase 2 deliverable, read only on local files).
Usage: python -I lib/consolidate.py <work_dir>
Inputs: data/products.csv, data/review_out/dup_*.csv, data/review_out/fam_*.csv, data/purchasing_open.csv,
data/unit_conflicts.csv, data/evidence_rejected.csv, reports/attributes_*.md. Uses lib/cost_impact.py (weighted average).
Output: reports/SSC_Product_Mapping_Workbook.xlsx and data/merge_groups.csv (group_key, var_id, is_master).
"""
import csv, sys
from collections import Counter, defaultdict
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

W = Path(sys.argv[1])
REV = sys.argv[2] if len(sys.argv) > 2 else 'review_out'   # review_final after QA fixes
sys.path.insert(0, str(W / 'lib'))
import cost_impact  # noqa: E402
from units import same_unit, unit_key  # noqa: E402

rd = lambda p: list(csv.DictReader(open(p, encoding='utf-8-sig')))
P = {r['var_id']: r for r in rd(W / 'data/products.csv')}
OPEN = {r['var_id']: r for r in rd(W / 'data/purchasing_open.csv')}
num = lambda x: 0.0 if x in ('', 'False', None) else float(x)

dup, fam = [], []
for g in ('MEP', 'CIVIL', 'GENERAL'):
    for r in rd(W / f'data/{REV}/dup_{g}.csv'):
        r['group'] = g; dup.append(r)
    for r in rd(W / f'data/{REV}/fam_{g}.csv'):
        r['group'] = g; fam.append(r)

# ---- consistency checks (lead review) ----
issues = []
for name, rows, src in (('dup', dup, 'clusters_pass1.csv'), ('fam', fam, 'families_pass1.csv')):
    want = Counter(r['var_id'] for r in rd(W / 'data' / src))
    got = Counter(r['var_id'] for r in rows)
    miss = set(want) - set(got)
    if miss:
        issues.append(f'{name}: {len(miss)} input rows missing in review output, e.g. {sorted(miss)[:5]}')
groups = defaultdict(list)
for r in dup:
    if r['decision'] in ('MASTER', 'MERGE'):
        groups[r['group_key']].append(r)
merge_rows = []
for gk, rr in groups.items():
    masters = [r for r in rr if r['decision'] == 'MASTER']
    if len(masters) != 1:
        issues.append(f'group {gk}: {len(masters)} MASTER rows'); continue
    m = masters[0]['var_id']
    if len(rr) < 2:
        continue
    for r in rr:
        a, b = P[r['var_id']]['x_unit'], P[m]['x_unit']
        if unit_key(a) != '?' and unit_key(b) != '?' and not same_unit(a, b):
            issues.append(f'group {gk}: unit {a!r} vs master {b!r} (var {r["var_id"]}) -> breaks the x_unit rule')
        merge_rows.append({'cluster_id': gk, 'var_id': r['var_id'], 'is_master': int(r['var_id'] == m)})
in_two = [v for v, c in Counter(r['var_id'] for r in merge_rows).items() if c > 1]
if in_two:
    issues.append(f'{len(in_two)} items sit in two merge groups: {in_two[:5]}')
with open(W / 'data/merge_groups.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['cluster_id', 'var_id', 'is_master']); w.writeheader(); w.writerows(merge_rows)
cost = cost_impact.analyse(str(W / 'data/merge_groups.csv'))
cost_by = defaultdict(dict)
for c in cost:
    cost_by[c['cluster_id']][c['company']] = c

master_of = {r['var_id']: [x for x in groups[r['group_key']] if x['decision'] == 'MASTER'][0]['var_id']
             for r in dup if r['decision'] == 'MERGE' and r['group_key'] in groups and any(x['decision'] == 'MASTER' for x in groups[r['group_key']])}

def usage(v):
    p, o = P[v], OPEN.get(v, {})
    return {'qty_ssc': num(p['qty_ssc']), 'qty_mep': num(p['qty_mep']), 'cost_ssc': num(p['cost_ssc']), 'cost_mep': num(p['cost_mep']),
            'moves_done': int(num(p['moves_done'])), 'po_lines': int(num(p['po_lines'])), 'open_rfq': o.get('open_rfq_lines', ''),
            'open_po': o.get('open_po_lines', ''), 'bills_posted': int(num(p['bill_lines_posted'])), 'mr_lines': int(num(p['mr_lines'])),
            'vendor_prices': int(num(p['vendor_prices'])), 'moves_analysis': int(num(p['moves_analysis_rows']))}

M = []
for r in sorted(dup, key=lambda r: (r['group'], r['group_key'], r['decision'] != 'MASTER')):
    v = r['var_id']; p = P[v]; tgt = master_of.get(v, v if r['decision'] == 'MASTER' else '')
    cb = cost_by.get(r['group_key'], {})
    M.append({'group': r['group'], 'merge_group': r['group_key'], 'class': r['class'], 'decision': r['decision'], 'var_id': v,
              'internal_ref': p['default_code'], 'current_name': p['name'], 'unit_as_written': p['x_unit'], 'category': p['category'],
              'target_var_id': tgt, 'target_name': P[tgt]['name'] if tgt else '', 'new_name': r.get('new_name', ''),
              'unit_check': r.get('unit_check', ''), **usage(v),
              'new_cost_ssc': cb.get('ssc', {}).get('new_cost_wavg', ''), 'new_cost_mep': cb.get('mep', {}).get('new_cost_wavg', ''),
              'cost_flags': ' '.join(sorted({f for c in cb.values() for f in str(c.get('flags', '')).replace('|', ' ').split() if f})),
              'reason': r.get('reason', ''), 'question': r.get('question', ''), 'qa_note': r.get('qa_note', ''), 'suggested_category': r.get('suggested_category', ''),
              'store_OK (Y/N/comment)': '', 'purchasing_OK (Y/N/comment)': ''})
V = []
for r in sorted(fam, key=lambda r: (r['group'], r.get('template_key', ''), r['var_id'])):
    v = r['var_id']; p = P[v]
    V.append({'group': r['group'], 'family': r['family_id'], 'decision': r['decision'], 'template_key': r.get('template_key', ''),
              'template_name': r.get('template_name', ''), 'attributes': r.get('attributes', ''), 'var_id': v, 'internal_ref': p['default_code'],
              'current_name': p['name'], 'unit_as_written': p['x_unit'], 'template_master_var_id': r.get('template_master_var_id', ''),
              'dup_in_family': r.get('dup_in_family', ''), 'merged_first_into': master_of.get(v, ''), **usage(v),
              'reason': r.get('reason', ''), 'qa_note': r.get('qa_note', ''), 'store_OK (Y/N/comment)': ''})
Q = [{'source': 'duplicates', 'group': m['group'], 'ref': m['merge_group'], 'var_id': m['var_id'], 'name': m['current_name'],
      'question': m['question'] or ('Confirm the unit: no unit is written on this item' if str(m['unit_check']) == '1' else '')}
     for m in M if m['question'] or (str(m['unit_check']) == '1' and m['decision'] in ('MASTER', 'MERGE'))]
Q += [{'source': 'variants', 'group': x['group'], 'ref': x['family'], 'var_id': x['var_id'], 'name': x['current_name'], 'question': x['reason']}
      for x in V if x['decision'] == 'UNSURE']
C = [{'merge_group': c['cluster_id'], 'company': c['company'], 'master': c['master'], 'member_qty': c['member_qty'], 'member_cost': c['member_cost'],
      'total_qty': c['total_qty'], 'master_cost': c['master_cost'], 'new_cost_wavg': c['new_cost_wavg'], 'value_before': c['value_before'],
      'value_after': c['value_after'], 'delta': c['delta'], 'flags': c['flags']} for c in cost if num(c['total_qty']) or num(c['master_cost'])]

S = []
cls = Counter((m['group'], m['class']) for m in M if m['decision'] == 'MASTER' or m['class'] in ('D', 'E'))
for g in ('MEP', 'CIVIL', 'GENERAL'):
    S.append({'item': f'{g}: merge groups (masters)', 'value': sum(1 for m in M if m['group'] == g and m['decision'] == 'MASTER' and m['merge_group'] in groups and len(groups[m['merge_group']]) > 1)})
    S.append({'item': f'{g}: items merged away (archived after merge)', 'value': sum(1 for m in M if m['group'] == g and m['decision'] == 'MERGE')})
    S.append({'item': f'{g}: kept as different (D) / unclear (E/UNSURE)', 'value': f"{sum(1 for m in M if m['group'] == g and m['decision'] == 'KEEP')} / {sum(1 for m in M if m['group'] == g and m['decision'] == 'UNSURE')}"})
    S.append({'item': f'{g}: new templates / items becoming variants', 'value': f"{len({x['template_key'] for x in V if x['group'] == g and x['decision'] == 'VARIANT'})} / {sum(1 for x in V if x['group'] == g and x['decision'] == 'VARIANT')}"})
for comp in ('ssc', 'mep'):
    rows = [c for c in cost if c['company'] == comp]
    S.append({'item': f'{comp.upper()}: stock value of merged groups before / after (weighted average) / delta',
              'value': f"{sum(num(c['value_before']) for c in rows):,.2f} / {sum(num(c['value_after']) for c in rows):,.2f} / {sum(num(c['delta']) for c in rows):,.2f}"})
    S.append({'item': f'{comp.upper()}: merge groups where stock sits on a zero-cost item (cost policy question)',
              'value': sum(1 for c in rows if 'ZERO_COST_WITH_STOCK' in str(c['flags']))})
S.append({'item': 'Questions for store / purchasing', 'value': len(Q)})
S += [{'item': 'LEAD CHECK', 'value': i} for i in issues] or [{'item': 'LEAD CHECK', 'value': 'all consistency checks passed'}]

wb = Workbook()
def sheet(title, rows, widths=None):
    ws = wb.create_sheet(title)
    if not rows:
        ws.append(['(none)']); return
    cols = list(rows[0])
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, '') for c in cols])
    for i, c in enumerate(cols, 1):
        ws.cell(1, i).font = Font(bold=True, color='FFFFFF')
        ws.cell(1, i).fill = PatternFill('solid', fgColor='1F4E78')
        ws.cell(1, i).alignment = Alignment(wrap_text=True, vertical='top')
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(c, 38 if 'name' in c or c in ('reason', 'question', 'attributes') else 12)
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
wb.remove(wb.active)
readme = [
    {'line': 'SSC group - product master clean-up - mapping workbook (DRAFT for review). Source: production read 2026-11-14 12:20 UTC, nothing changed in Odoo.'},
    {'line': 'Summary: totals per group and the valuation effect per company. Merge_Map: one row per item in a duplicate group.'},
    {'line': 'decision: MASTER = the item we keep; MERGE = merged into target_var_id then archived; KEEP = not a duplicate; UNSURE = question.'},
    {'line': 'class: A = duplicate without history (archive), B = duplicate with history (merge), D = looks alike but different (keep), E = unclear.'},
    {'line': 'Variant_Map: items that become variants of one template (template_name + attributes). merged_first_into = it is merged as a duplicate first.'},
    {'line': 'Rules: items with a different unit are never merged; unit_check = 1 means no unit is written, the store team confirms it.'},
    {'line': 'Cost policy (the client 2026-11-14): weighted average by on-hand quantity per company; total value stays identical when all quantities are positive.'},
    {'line': 'Please fill store_OK / purchasing_OK with Y, N or a comment. Questions sheet: one line per open question.'},
]
sheet('README', readme, {'line': 150})
sheet('Summary', S, {'item': 80, 'value': 60})
sheet('Merge_Map', M)
sheet('Variant_Map', V)
sheet('Questions', Q)
sheet('Cost_Impact', C)
sheet('Unit_Conflicts', rd(W / 'data/unit_conflicts.csv'))
sheet('Evidence_Rejected', rd(W / 'data/evidence_rejected.csv'))
cat = []
for g in ('MEP', 'CIVIL', 'GENERAL'):
    p = W / f'reports/attributes_{g}.md'
    if p.exists():
        cat += [{'group': g, 'line': l} for l in p.read_text(encoding='utf-8').splitlines()]
sheet('Attribute_Catalogue', cat, {'line': 140})
out = W / 'reports/SSC_Product_Mapping_Workbook.xlsx'
wb.save(out)
print('saved', out)
for s in S:
    print(f"{s['item']}: {s['value']}")
