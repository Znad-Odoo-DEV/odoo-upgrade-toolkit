// READ-ONLY preflight for the product merge. Paste in the logged-in Odoo 19 tab, then:
//   const r = await window.runPreflight(planMerge, planVariants, tmplOf); console.log(JSON.stringify(r));
// Uses only search_read / read / search_count / formatted_read_group / fields_get. Sequential calls.
(() => {
  window.runPreflight = async function (planMerge, planVariants, tmplOf) {
    const SINCE = '2026-11-14 12:20:00';
    const CTX = { active_test: false, lang: 'en_US' };
    const PAGE = 500, PAUSE = 100;
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    let calls = 0;
    const call = async (model, method, args = [], kwargs = {}) => {
      calls++;
      const r = await fetch(`/web/dataset/call_kw/${model}/${method}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs: { context: CTX, ...kwargs } } }),
      }).then(r => r.json());
      await sleep(PAUSE);
      if (r.error) throw new Error(`${model}.${method}: ${r.error.data?.message || r.error.message}`);
      return r.result;
    };
    const errors = [];
    const safe = async (label, fn) => { try { return await fn(); } catch (e) { errors.push(`${label}: ${e.message}`); return null; } };
    const chunks = (a, n = PAGE) => { const o = []; for (let i = 0; i < a.length; i += n) o.push(a.slice(i, i + n)); return o; };
    const norm = s => String(s || '').toLowerCase().replace(/\s+/g, ' ').trim();
    tmplOf = tmplOf || {};

    const planIds = new Set();
    for (const g of planMerge || []) { planIds.add(g.master); (g.dups || []).forEach(d => planIds.add(d)); }
    const itemNames = new Set();
    for (const t of planVariants || []) {
      itemNames.add(norm(t.name));
      planIds.add(t.master);
      (t.items || []).forEach(i => planIds.add(i.var));
    }
    const ids = [...planIds].filter(x => Number.isInteger(x));

    const rep = { extract_time: SINCE, plan_product_ids: ids.length };

    // 1. existence / active / template
    rep.check1 = await safe('check1', async () => {
      const found = {};
      for (const c of chunks(ids)) {
        const rows = await call('product.product', 'search_read', [[['id', 'in', c]]], { fields: ['id', 'active', 'product_tmpl_id'] });
        rows.forEach(r => { found[r.id] = r; });
      }
      const missing = [], inactive = [], tmplChanged = [], noTmplInfo = [];
      for (const id of ids) {
        const r = found[id];
        if (!r) { missing.push(id); continue; }
        if (!r.active) inactive.push(id);
        const exp = tmplOf[id];
        if (exp === undefined) noTmplInfo.push(id);
        else if (r.product_tmpl_id && r.product_tmpl_id[0] !== exp) tmplChanged.push({ id, was: exp, now: r.product_tmpl_id[0] });
      }
      return { ok: !missing.length && !inactive.length && !tmplChanged.length, missing, inactive, tmplChanged, noTmplInfo };
    });

    // 2. new products with same normalised name as a plan item
    rep.check2_new_possible_dups = await safe('check2', async () => {
      const rows = await call('product.product', 'search_read', [[['create_date', '>', SINCE]]], { fields: ['id', 'name', 'default_code', 'active', 'create_date'], limit: 5000 });
      const hits = rows.filter(r => itemNames.has(norm(r.name))).map(r => ({ id: r.id, name: r.name, code: r.default_code, active: r.active, created: r.create_date }));
      return { created_since: rows.length, same_name_as_plan_item: hits };
    });

    // 3. activity since the extract, per product
    const act = {};
    const actDefs = [
      ['stock.move', 'product_id'], ['purchase.order.line', 'product_id'],
      ['ssc.request.material.line', 'product_id'], ['account.move.line', 'product_id'],
    ];
    for (const [model, field] of actDefs) {
      act[model] = await safe('act ' + model, async () => {
        const per = {};
        for (const c of chunks(ids)) {
          const dom = [[field, 'in', c], '|', ['create_date', '>', SINCE], ['write_date', '>', SINCE]];
          const rows = await call(model, 'formatted_read_group', [dom, [field], ['__count']], {});
          rows.forEach(g => { const v = g[field]; const id = Array.isArray(v) ? v[0] : (v && v.id) || v; if (id) per[id] = (per[id] || 0) + g.__count; });
        }
        return per;
      });
    }
    const changed = new Set();
    for (const m in act) if (act[m]) Object.keys(act[m]).forEach(k => changed.add(+k));
    const totals = {};
    for (const m in act) totals[m] = act[m] ? Object.keys(act[m]).length : null;
    rep.check3_activity_since_extract = { products_with_activity_per_model: totals, products_changed: [...changed].sort((a, b) => a - b), per_model: act };
    const groupsChanged = [];
    for (const g of planMerge || []) if ([g.master, ...(g.dups || [])].some(i => changed.has(i))) groupsChanged.push(g.g);
    const tkChanged = [];
    for (const t of planVariants || []) if ((t.items || []).some(i => changed.has(i.var))) tkChanged.push(t.tk);
    rep.check3_groups_changed = { merge_groups: groupsChanged, variant_templates: tkChanged };

    // 4. open documents on plan items
    rep.check4_open_docs = await safe('check4', async () => {
      const perRfq = {}, perBill = {};
      for (const c of chunks(ids)) {
        let rows = await call('purchase.order.line', 'formatted_read_group', [[['product_id', 'in', c], ['order_id.state', 'in', ['draft', 'sent']]], ['product_id'], ['__count']], {});
        rows.forEach(g => { const id = g.product_id && g.product_id[0]; if (id) perRfq[id] = (perRfq[id] || 0) + g.__count; });
        rows = await call('account.move.line', 'formatted_read_group', [[['product_id', 'in', c], ['move_id.state', '=', 'draft'], ['move_id.move_type', 'in', ['in_invoice', 'in_refund']]], ['product_id'], ['__count']], {});
        rows.forEach(g => { const id = g.product_id && g.product_id[0]; if (id) perBill[id] = (perBill[id] || 0) + g.__count; });
      }
      const sum = o => Object.values(o).reduce((a, b) => a + b, 0);
      return { rfq_lines: sum(perRfq), rfq_products: Object.keys(perRfq).length, draft_bill_lines: sum(perBill), draft_bill_products: Object.keys(perBill).length, rfq_by_product: perRfq, draft_bill_by_product: perBill };
    });

    // 5. company stock totals (extract: SSC 150764.6, Royal Arrow 196877)
    rep.check5_stock_by_company = await safe('check5', async () => {
      const rows = await call('stock.quant', 'formatted_read_group', [[['location_id.usage', '=', 'internal']], ['company_id'], ['quantity:sum']], {});
      return { now: rows.map(g => ({ company: g.company_id && g.company_id[1], id: g.company_id && g.company_id[0], qty: g['quantity:sum'] })), extract: { SSC: 150764.6, 'Royal Arrow': 196877 } };
    });

    // 6. modules and attributes
    rep.check6_modules = await safe('check6 mod', async () => {
      const rows = await call('ir.module.module', 'search_read', [[['name', 'in', ['data_cleaning', 'data_merge', 'data_recycle']]]], { fields: ['name', 'state'] });
      return rows.map(r => ({ name: r.name, state: r.state }));
    });
    const ATTRS = ['Pipe Size', 'Size', 'Colour', 'Length', 'Diameter', 'Thickness', 'Angle', 'Material', 'Type', 'Brand', 'Cable Size', 'Cores', 'Rebar Diameter', 'Width', 'Capacity', 'Grade', 'Air Type', 'Junction Type', 'Thread Size', 'Temperature'];
    const planned = new Set(); for (const t of planVariants || []) (t.attrs || []).forEach(a => planned.add(a));
    rep.check6_attributes = await safe('check6 attr', async () => {
      const all = await call('product.attribute', 'search_read', [[]], { fields: ['id', 'name', 'create_variant', 'create_date'] });
      const want = new Set([...ATTRS, ...planned].map(norm));
      const hits = all.filter(a => want.has(norm(a.name)));
      const out = [];
      for (const a of hits) {
        const lines = await call('product.template.attribute.line', 'search_count', [[['attribute_id', '=', a.id]]], {});
        const vals = await call('product.attribute.value', 'search_count', [[['attribute_id', '=', a.id]]], {});
        out.push({ id: a.id, name: a.name, create_variant: a.create_variant, values: vals, lines, created: a.create_date });
      }
      const found = new Set(hits.map(a => norm(a.name)));
      return { existing: out, planned_not_existing: [...planned].filter(p => !found.has(norm(p))) };
    });

    rep.errors = errors;
    rep.calls = calls;
    return rep;
  };
})();
