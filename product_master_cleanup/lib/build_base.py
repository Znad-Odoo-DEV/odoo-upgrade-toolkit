"""Flatten data/extract.json (Phase 1, read-only extract) into per-product CSVs for the team.
Usage: python -I lib/build_base.py <work_dir>
Outputs in <work_dir>/data/: products.csv (one row per variant with usage stats), quants.csv, po_lines.csv,
supplierinfo.csv, bill_lines.csv, mr_lines.csv, product_value.csv, finder_terms.csv.
"""
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path

W = Path(sys.argv[1])
D = json.load(open(W / 'data/extract.json', encoding='utf-8'))
m2o = lambda v: v[0] if isinstance(v, list) and v else None
m2n = lambda v: v[1] if isinstance(v, list) and len(v) > 1 else ''
CO = {c['id']: c['name'] for c in D['companies']}
SHORT = {1: 'ssc', 2: 'mep', 3: 'malak', 4: 'rwdw'}


def out(name, rows, fields):
    with open(W / 'data' / name, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(name, len(rows))


tmpl = {t['id']: t for t in D['product_template']}
name_ar = {t['id']: t['name'] for t in D.get('product_template_name_ar', [])}
var = {p['id']: p for p in D['product_product']}
v2t = {p['id']: m2o(p['product_tmpl_id']) for p in D['product_product']}
t2v = defaultdict(list)
for v, t in v2t.items():
    t2v[t].append(v)
cost = {int(c): {r['id']: r['standard_price'] for r in rows} for c, rows in D['standard_price'].items()}
loc = {l['id']: l for l in D['locations']}

S = defaultdict(Counter)        # per variant counters
last = defaultdict(dict)        # per variant last dates / prices
vendors = defaultdict(set)

for q in D['quant_by_loc']:
    v, c = m2o(q['product_id']), m2o(q['company_id'])
    S[v][f'qty_{SHORT.get(c, c)}'] += q['quantity:sum']
    S[v]['quant_locations'] += 1
for m in D['move_stats']:
    v, c, st = m2o(m['product_id']), m2o(m['company_id']), m['state']
    S[v][f'moves_{st}'] += m['__count']
    if st == 'done':
        S[v][f'moves_done_{SHORT.get(c, c)}'] += m['__count']
        if m['date:max'] and m['date:max'] > last[v].get('last_move', ''):
            last[v]['last_move'] = m['date:max']
for m in D['move_line_stats']:
    S[m2o(m['product_id'])]['move_lines'] += m['__count']

xitem_mismatch = []
for l in D['po_lines']:
    v = m2o(l['product_id'])
    if not v:
        continue
    S[v]['po_lines'] += 1
    S[v][f'po_{l["state"]}'] += 1
    open_ = l['state'] in ('draft', 'sent', 'to approve') or (l['state'] == 'purchase' and l['qty_received'] < l['product_qty'])
    if open_:
        S[v]['po_open_lines'] += 1
    if l['state'] in ('purchase', 'done'):
        S[v]['po_qty_confirmed'] += l['product_qty']
        if (l['date_order'] or '') > last[v].get('last_po', ''):
            last[v].update(last_po=l['date_order'], last_po_price=l['price_unit'])
    if l.get('partner_id'):
        vendors[v].add(m2n(l['partner_id']))
    xi = m2o(l.get('x_studio_item'))
    if xi and xi != v2t.get(v):
        xitem_mismatch.append({'po_line': l['id'], 'order': m2n(l['order_id']), 'product_id': v, 'product_tmpl': v2t.get(v), 'x_studio_item': xi})
    if xi:
        S[('t', xi)]['pol_x_studio_item'] += 1

for a in D['aml']:
    v = m2o(a['product_id'])
    k = 'bill' if a['move_type'] in ('in_invoice', 'in_refund', 'in_receipt') else ('invoice' if a['move_type'].startswith('out_') else 'entry')
    S[v][f'{k}_lines_{a["parent_state"]}'] += 1
for a in D['analytic_stats']:
    v = m2o(a['product_id'])
    S[v]['analytic_lines'] += a['__count']
    S[v]['analytic_amount'] += a['amount:sum']
for l in D['mr_lines']:
    v = m2o(l['product_id'])
    S[v]['mr_lines'] += 1
    if l.get('state') in ('draft', 'to_approve'):
        S[v]['mr_open_lines'] += 1
for l in D['requisition_lines']:
    S[m2o(l['product_id'])]['agreement_lines'] += 1
for o in D['orderpoints']:
    S[m2o(o['product_id'])]['orderpoints'] += 1
for pv in D['product_value']:
    S[m2o(pv['product_id'])]['product_value_rows'] += 1
for s in D['supplierinfo']:
    t = m2o(s['product_tmpl_id'])
    S[('t', t)]['vendor_prices'] += 1
    if s.get('product_code'):
        S[('t', t)]['vendor_codes'] += 1
for g in D['moves_analysis_by_tmpl']:
    S[('t', m2o(g['x_product_template_id']))]['moves_analysis_rows'] += g['__count']
for r in D['item_list']:
    t = m2o(r.get('x_studio_item_on_item_list'))
    if t:
        S[('t', t)]['item_list_rows'] += 1
for r in D['subcontract_items']:
    S[('t', m2o(r['product_id']))]['subcontract_items'] += 1
for r in D['x_pol_d9d4d']:
    S[('t', m2o(r['x_studio_item']))]['x_pol_d9d4d'] += 1
for g in D['x_employees_payments']:
    S[('t', m2o(g['x_studio_product']))]['x_employees_payments'] += g['__count']
for r in D['approval_lines']:
    S[m2o(r['product_id'])]['approval_lines'] += 1
for r in D['project_timesheet_product']:
    S[m2o(r['timesheet_product_id'])]['project_timesheet_product'] += 1
for r in D['sale_lines']:
    S[m2o(r['product_id'])]['sale_lines'] += 1
for g in D['messages']:
    key = ('t', g['res_id']) if g['model'] == 'product.template' else g['res_id']
    S[key]['messages'] += g['__count']
xml = defaultdict(list)
for x in D['xmlids']:
    key = ('t', x['res_id']) if x['model'] == 'product.template' else x['res_id']
    xml[key].append(f"{x['module']}.{x['name']}")

COUNT_COLS = ['qty_ssc', 'qty_mep', 'qty_malak', 'qty_rwdw', 'quant_locations', 'moves_done', 'moves_done_ssc', 'moves_done_mep',
              'moves_cancel', 'move_lines', 'po_lines', 'po_open_lines', 'po_draft', 'po_sent', 'po_purchase', 'po_cancel',
              'po_qty_confirmed', 'bill_lines_posted', 'bill_lines_draft', 'bill_lines_cancel', 'invoice_lines_posted',
              'invoice_lines_draft', 'entry_lines_posted', 'analytic_lines', 'analytic_amount', 'mr_lines', 'mr_open_lines',
              'agreement_lines', 'orderpoints', 'product_value_rows', 'approval_lines', 'project_timesheet_product', 'sale_lines', 'messages']
TMPL_COLS = ['vendor_prices', 'vendor_codes', 'moves_analysis_rows', 'item_list_rows', 'pol_x_studio_item', 'subcontract_items',
             'x_pol_d9d4d', 'x_employees_payments', 'tmpl_messages']
rows = []
for v, p in sorted(var.items()):
    t = v2t[v]
    T = tmpl[t]
    r = {'var_id': v, 'tmpl_id': t, 'name': T['name'], 'name_ar': name_ar.get(t) if name_ar.get(t) != T['name'] else '',
         'default_code': T['default_code'] or '', 'barcode': T['barcode'] or '', 'categ_id': m2o(T['categ_id']), 'category': m2n(T['categ_id']),
         'uom': m2n(T['uom_id']), 'x_unit': T.get('x_unit') or '', 'type': T['type'], 'is_storable': T.get('is_storable'),
         'active': T['active'] and p['active'], 'company_id': m2o(T['company_id']) or '', 'x_item_type': T.get('x_item_type') or '',
         'x_specifications': (T.get('x_specifications') or '').replace('\n', ' ')[:300], 'x_item_serial_no': T.get('x_item_serial_no') or '',
         'create_date': T['create_date'], 'create_uid': m2n(T['create_uid']), 'variant_count': len(t2v[t]),
         'xmlid': ';'.join(xml.get(v, []) + xml.get(('t', t), []))}
    for c in sorted(cost):
        r[f'cost_{SHORT.get(c, c)}'] = cost[c].get(v, 0)
    for k in COUNT_COLS:
        r[k] = round(S[v][k], 4) if S[v][k] else 0
    for k in TMPL_COLS:
        r[k] = S[('t', t)]['messages' if k == 'tmpl_messages' else k] or 0
    r.update({k: last[v].get(k, '') for k in ('last_move', 'last_po', 'last_po_price')})
    r['vendors'] = '; '.join(sorted(vendors[v]))[:300]
    r['history_score'] = (r['moves_done'] + r['po_lines'] + r['bill_lines_posted'] + r['mr_lines'] + r['vendor_prices'] + r['analytic_lines'])
    rows.append(r)
cost_cols = [f'cost_{SHORT.get(c, c)}' for c in sorted(cost)]
fields = ['var_id', 'tmpl_id', 'name', 'name_ar', 'default_code', 'barcode', 'categ_id', 'category', 'uom', 'x_unit', 'type', 'is_storable',
          'active', 'company_id', 'x_item_type', 'x_specifications', 'x_item_serial_no', 'create_date', 'create_uid', 'variant_count', 'xmlid'] \
    + cost_cols + COUNT_COLS + TMPL_COLS + ['last_move', 'last_po', 'last_po_price', 'vendors', 'history_score']
out('products.csv', rows, fields)

flat = lambda rec: {k: (m2o(v) if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int) else v) for k, v in rec.items()}
q = [{'var_id': m2o(g['product_id']), 'company_id': m2o(g['company_id']), 'location_id': m2o(g['location_id']),
      'location': m2n(g['location_id']), 'quantity': g['quantity:sum'], 'reserved': g['reserved_quantity:sum']} for g in D['quant_by_loc']]
out('quants.csv', q, list(q[0]))
for name, key in [('po_lines.csv', 'po_lines'), ('supplierinfo.csv', 'supplierinfo'), ('mr_lines.csv', 'mr_lines'),
                  ('product_value.csv', 'product_value'), ('requisition_lines.csv', 'requisition_lines'), ('orderpoints.csv', 'orderpoints')]:
    rr = [flat(x) for x in D[key]]
    for x, o in zip(rr, D[key]):
        for k, v in o.items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int):
                x[k + '_name'] = v[1]
    out(name, rr, list(dict.fromkeys(k for x in rr for k in x)))
bl = [dict(flat(a), move_name=m2n(a['move_id']), account=m2n(a['account_id'])) for a in D['aml']]
out('bill_lines.csv', bl, list(bl[0]))
ft = [flat(x) for x in D['finder_terms']]
out('finder_terms.csv', ft, list(dict.fromkeys(k for x in ft for k in x)))
out('pol_x_studio_item_mismatch.csv', xitem_mismatch, ['po_line', 'order', 'product_id', 'product_tmpl', 'x_studio_item'])
cats = [{'id': c['id'], 'complete_name': c['complete_name'], 'parent_id': m2o(c['parent_id'])} for c in D['product_category']]
out('categories.csv', cats, ['id', 'complete_name', 'parent_id'])
