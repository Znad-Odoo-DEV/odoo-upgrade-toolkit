// Product merge executor (runs in a logged-in Odoo 19 tab: dev_0 staging first, production only after sign-off).
// Plan item: {g: group_key, master: var_id, dups: [var_id...], rename: 'new name' | null}
// Per group: snapshot -> weighted-average cost on master per company -> Data Cleaning merge (archive) ->
// template-level references repointed by ORM -> duplicate templates archived -> rename -> verify (stop on mismatch).
(() => {
  const CTX = { active_test: false, tracking_disable: true, mail_notrack: true, mail_create_nolog: true };
  const COMPANIES = [1, 2, 3, 4];
  const call = async (model, method, args = [], kwargs = {}) => {
    const r = await fetch(`/web/dataset/call_kw/${model}/${method}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs } }) }).then(r => r.json());
    if (r.error) throw new Error(`${model}.${method}: ${r.error.data?.message || r.error.message}`);
    return r.result;
  };
  // live reference fields (stored, non-report). [model, field, level]
  const VAR_REFS = [['stock.move', 'product_id'], ['stock.move.line', 'product_id'], ['stock.quant', 'product_id'], ['account.analytic.line', 'product_id'],
    ['purchase.order.line', 'product_id'], ['ssc.request.material.line', 'product_id'], ['account.move.line', 'product_id'], ['product.supplierinfo', 'product_id'],
    ['product.value', 'product_id'], ['purchase.requisition.line', 'product_id'], ['project.project', 'timesheet_product_id'],
    ['stock.warehouse.orderpoint', 'product_id'], ['approval.product.line', 'product_id'], ['sale.order.line', 'product_id'],
    ['product.pricelist.item', 'product_id'], ['ssc.boq.line', 'product_id']];
  const TMPL_REFS = [['product.supplierinfo', 'product_tmpl_id'], ['purchase.order.line', 'x_studio_item'], ['x_purchase_order_line_d9d4d', 'x_studio_item'],
    ['x_item_listtt', 'x_studio_item_on_item_list'], ['x_employees_payments', 'x_studio_product'], ['ssc.subcontract.item', 'product_id'],
    ['x_product_template_line_d82d9', 'x_product_template_id'], ['product.pricelist.item', 'product_tmpl_id']];
  const X = window.__ex = { log: [], call, stop: false };
  const log = (o) => { X.log.push({ t: new Date().toISOString(), ...o }); };

  X.counts = async (varIds, tmplIds) => {   // one grouped count per model and field
    const out = {};
    const one = async (m, f, ids, pre) => {
      for (const i of ids) out[`${m}.${f}#${pre}${i}`] = 0;
      const g = await call(m, 'formatted_read_group', [], { domain: [[f, 'in', ids]], groupby: [f], aggregates: ['__count'], context: CTX });
      for (const r of g) if (r[f]) out[`${m}.${f}#${pre}${r[f][0]}`] = r.__count;
    };
    for (const [m, f] of VAR_REFS) await one(m, f, varIds, '');
    for (const [m, f] of TMPL_REFS) await one(m, f, tmplIds, 't');
    return out;
  };
  X.stock = async (varIds) => {   // internal qty per company per product + standard_price per company
    const g = await call('stock.quant', 'formatted_read_group', [], { domain: [['product_id', 'in', varIds], ['location_id.usage', '=', 'internal']],
      groupby: ['product_id', 'company_id'], aggregates: ['quantity:sum'], context: CTX });
    const qty = {}; for (const r of g) qty[`${r.product_id[0]}@${r.company_id[0]}`] = r['quantity:sum'];
    const cost = {};
    for (const c of COMPANIES) for (const p of await call('product.product', 'read', [varIds, ['standard_price']], { context: { ...CTX, allowed_company_ids: [c] } })) cost[`${p.id}@${c}`] = p.standard_price;
    return { qty, cost };
  };
  X.companyTotals = async () => {
    const g = await call('stock.quant', 'formatted_read_group', [], { domain: [['location_id.usage', '=', 'internal']], groupby: ['company_id'], aggregates: ['quantity:sum'], context: CTX });
    return Object.fromEntries(g.map(r => [r.company_id[0], Math.round(r['quantity:sum'] * 1000) / 1000]));
  };
  X.mergeModel = async () => {
    if (X.mmid) return X.mmid;
    const found = await call('data_merge.model', 'search', [[['name', '=', 'Product cleanup 2026-11 (manual)']]], { context: CTX });
    if (found.length) return (X.mmid = found[0]);
    const im = await call('ir.model', 'search', [[['model', '=', 'product.product']]]);
    X.mmid = await call('data_merge.model', 'create', [{ name: 'Product cleanup 2026-11 (manual)', res_model_id: im[0], removal_mode: 'archive', merge_mode: 'manual' }], { context: CTX });
    return X.mmid;
  };

  X.mergeGroup = async (p, opts = {}) => {
    const ids = [p.master, ...p.dups];
    const prods = await call('product.product', 'read', [ids, ['product_tmpl_id', 'active', 'display_name']], { context: CTX });
    if (prods.length !== ids.length) throw new Error(`${p.g}: missing products ${ids}`);
    const tmplOf = Object.fromEntries(prods.map(r => [r.id, r.product_tmpl_id[0]]));
    const mT = tmplOf[p.master], dT = [...new Set(p.dups.map(d => tmplOf[d]))].filter(t => t !== mT);
    const tot0 = await X.companyTotals();
    const c0 = await X.counts(ids, [mT, ...dT]);
    const s0 = await X.stock(ids);
    // 1. weighted-average cost per company (the client 2026-11-14), zero-cost rule decided by the lead (see DECISIONS.md)
    const newCost = {}, value0 = {};
    for (const c of COMPANIES) {
      let q = 0, v = 0, qKnown = 0, vKnown = 0;
      for (const id of ids) {
        const qq = s0.qty[`${id}@${c}`] || 0, cc = s0.cost[`${id}@${c}`] || 0;
        q += qq; v += qq * cc; if (cc > 0) { qKnown += Math.max(qq, 0); vKnown += Math.max(qq, 0) * cc; }
      }
      value0[c] = v;
      const known = ids.map(id => s0.cost[`${id}@${c}`] || 0).filter(x => x > 0);
      let nc;
      if (q > 0 && v > 0) nc = v / q;                                   // normal weighted average (value identical)
      else if (q > 0 && v === 0) nc = 0;                                // all stock at zero cost: keep 0, value identical
      else nc = s0.cost[`${p.master}@${c}`] || (known.length ? known[0] : 0); // no stock: keep master cost, else a known one
      newCost[c] = Math.round(nc * 10000) / 10000;
    }
    const plan = { g: p.g, master: p.master, dups: p.dups, mT, dT, newCost, value0 };
    if (opts.dry) return { plan, c0, s0, tot0 };
    // 2. Data Cleaning merge (archive). The duplicates' product.value rows move to the master too, so the cost is
    //    written AFTER the merge: it becomes the master's latest cost record.
    const mm = await X.mergeModel();
    const gid = await call('data_merge.group', 'create', [{ model_id: mm }], { context: CTX });
    for (const id of ids) await call('data_merge.record', 'create', [{ group_id: gid, res_id: id, is_master: id === p.master }], { context: CTX });
    const mres = await call('data_merge.group', 'merge_records', [[gid]], { context: CTX });
    for (const c of COMPANIES) {
      const cur = (await call('product.product', 'read', [[p.master], ['standard_price']], { context: { ...CTX, allowed_company_ids: [c] } }))[0].standard_price;
      if (Math.abs(cur - newCost[c]) > 1e-6)
        await call('product.product', 'write', [[p.master], { standard_price: newCost[c] }], { context: { ...CTX, allowed_company_ids: [c] } });
    }
    // 3. template-level references -> master template
    const moved = {};
    for (const [m, f] of TMPL_REFS) for (const t of dT) {
      const rids = await call(m, 'search', [[[f, '=', t]]], { context: CTX });
      for (let i = 0; i < rids.length; i += 2000) await call(m, 'write', [rids.slice(i, i + 2000), { [f]: mT }], { context: CTX });
      if (rids.length) moved[`${m}.${f}`] = (moved[`${m}.${f}`] || 0) + rids.length;
    }
    // 4. archive duplicate templates, rename master, keep a unit on the master
    const tm = await call('product.template', 'read', [[mT, ...dT], ['active', 'x_unit', 'name']], { context: CTX });
    const dTactive = tm.filter(r => r.id !== mT && r.active).map(r => r.id);
    if (dTactive.length) await call('product.template', 'write', [dTactive, { active: false }], { context: CTX });
    const mVals = {};
    if (p.rename && p.rename !== tm.find(r => r.id === mT).name) mVals.name = p.rename;
    if (!tm.find(r => r.id === mT).x_unit) { const u = tm.find(r => r.id !== mT && r.x_unit); if (u) mVals.x_unit = u.x_unit; }
    if (Object.keys(mVals).length) await call('product.template', 'write', [[mT], mVals], { context: CTX });
    // 5. verify
    const c1 = await X.counts(ids, [mT, ...dT]);
    const s1 = await X.stock(ids);
    const tot1 = await X.companyTotals();
    const errs = [];
    for (const [m, f] of VAR_REFS) {
      const before = ids.reduce((a, id) => a + c0[`${m}.${f}#${id}`], 0);
      const after = c1[`${m}.${f}#${p.master}`];
      for (const d of p.dups) if (c1[`${m}.${f}#${d}`] !== 0 && m !== 'stock.quant') errs.push(`${m}.${f} still on dup ${d}: ${c1[`${m}.${f}#${d}`]}`);
      if (after !== before && !['stock.quant', 'stock.warehouse.orderpoint', 'product.value'].includes(m)) errs.push(`${m}.${f} master ${after} != before ${before}`);
    }
    for (const [m, f] of TMPL_REFS) {
      const before = [mT, ...dT].reduce((a, t) => a + c0[`${m}.${f}#t${t}`], 0);
      if (c1[`${m}.${f}#t${mT}`] !== before) errs.push(`${m}.${f} master tmpl ${c1[`${m}.${f}#t${mT}`]} != ${before}`);
    }
    const value1 = {};
    for (const c of COMPANIES) {
      const q0 = ids.reduce((a, id) => a + (s0.qty[`${id}@${c}`] || 0), 0);
      const q1 = ids.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0), 0);
      const qm = s1.qty[`${p.master}@${c}`] || 0;
      value1[c] = ids.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0) * (s1.cost[`${id}@${c}`] || 0), 0);
      if (Math.abs(q0 - q1) > 1e-6) errs.push(`company ${c}: qty ${q0} -> ${q1}`);
      if (Math.abs(qm - q1) > 1e-6) errs.push(`company ${c}: qty left on duplicates ${q1 - qm}`);
      if (Math.abs(value0[c] - value1[c]) > 0.01) errs.push(`company ${c}: value ${value0[c].toFixed(2)} -> ${value1[c].toFixed(2)}`);
      if (Math.abs((tot0[c] || 0) - (tot1[c] || 0)) > 1e-6) errs.push(`company ${c}: company total qty ${tot0[c]} -> ${tot1[c]}`);
    }
    const dupsActive = (await call('product.product', 'read', [p.dups, ['active']], { context: CTX })).filter(r => r.active).map(r => r.id);
    if (dupsActive.length) errs.push(`duplicates still active: ${dupsActive}`);
    const res = { ...plan, gid, mres: JSON.stringify(mres).slice(0, 200), moved, renamed: mVals, value1, errs };
    log(res);
    if (errs.length) { X.stop = true; }
    return res;
  };

  X.runBatch = async (items) => {
    X.batch = { total: items.length, done: 0, errors: 0, current: null };
    for (const p of items) {
      if (X.stop) { log({ g: p.g, skipped: 'stopped after an error' }); continue; }
      X.batch.current = p.g;
      try { const r = await X.mergeGroup(p); if (r.errs.length) X.batch.errors++; }
      catch (e) { X.stop = true; X.batch.errors++; log({ g: p.g, exception: e.message }); }
      X.batch.done++;
    }
    X.batch.current = null;
    return X.batch;
  };
  X.download = (name) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(X.log, null, 1)], { type: 'application/json' }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
  };
  return 'executor loaded';
})();
