  // ---------- round 7 ----------
  // merge one variant into another of the family; the dup's template is kept while it still has other active variants
  X.mergeIntoVariant = async (p) => {
    const T0 = Date.now(), errs = [], ids = [p.master, ...p.dups];
    const pr = await call('product.product', 'read', [ids, ['product_tmpl_id', 'active']], { context: CTX });
    if (!pr.find(r => r.id === p.master).active) throw new Error(`${p.g}: master ${p.master} is archived`);
    if (pr.filter(r => r.id !== p.master).every(r => !r.active)) { const r = { kind: 'merge7', g: p.g, skipped: 'already merged', errs: [] }; X.push(r); return r; }
    const mT = pr.find(r => r.id === p.master).product_tmpl_id[0], dT = [...new Set(pr.filter(r => r.id !== p.master).map(r => r.product_tmpl_id[0]))];
    const [s0, tot0] = await Promise.all([X.stock(ids), X.companyTotals()]);
    const newCost = {}, value0 = {};
    for (const c of COMPANIES) { let q = 0, v = 0; for (const id of ids) { const qq = s0.qty[`${id}@${c}`] || 0, cc = s0.cost[`${id}@${c}`] || 0; q += qq; v += qq * cc; }
      value0[c] = v; const known = ids.map(id => s0.cost[`${id}@${c}`] || 0).filter(x => x > 0);
      newCost[c] = Math.round((q > 0 && v > 0 ? v / q : q > 0 ? 0 : (s0.cost[`${p.master}@${c}`] || (known.length ? known[0] : 0))) * 10000) / 10000; }
    const mm = await X.mergeModel();
    const gid = await call('data_merge.group', 'create', [{ model_id: mm }], { context: CTX });
    await call('data_merge.record', 'create', [ids.map(id => ({ group_id: gid, res_id: id, is_master: id === p.master }))], { context: CTX });
    await call('data_merge.group', 'merge_records', [[gid]], { context: CTX });
    for (const c of COMPANIES) { const cur = (await call('product.product', 'read', [[p.master], ['standard_price']], { context: { ...CTX, allowed_company_ids: [c] } }))[0].standard_price;
      if (Math.abs(cur - newCost[c]) > 1e-6) await call('product.product', 'write', [[p.master], { standard_price: newCost[c] }], { context: { ...CTX, allowed_company_ids: [c] } }); }
    const emptied = [];
    for (const t of dT.filter(t => t !== mT)) { const left = await call('product.product', 'search_count', [[['product_tmpl_id', '=', t], ['active', '=', true]]], { context: CTX });
      if (!left) { for (const [m, f] of ALL_TREF) { const rids = await call(m, 'search', [[[f, '=', t]]], { context: CTX }); if (rids.length) await call(m, 'write', [rids, { [f]: mT }], { context: CTX }); }
        await call('product.template', 'write', [[t], { active: false }], { context: CTX }); emptied.push(t); } }
    const [s1, tot1] = await Promise.all([X.stock(ids), X.companyTotals()]);
    for (const c of COMPANIES) { const q0 = ids.reduce((a, id) => a + (s0.qty[`${id}@${c}`] || 0), 0), q1 = ids.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0), 0), qm = s1.qty[`${p.master}@${c}`] || 0;
      const v1 = ids.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0) * (s1.cost[`${id}@${c}`] || 0), 0);
      if (Math.abs(q0 - q1) > 1e-6 || Math.abs(qm - q1) > 1e-6) errs.push(`company ${c}: qty ${q0} -> ${q1}, master ${qm}`);
      if (Math.abs(value0[c] - v1) > 0.01 + q1 * 0.00005) errs.push(`company ${c}: value ${value0[c].toFixed(2)} -> ${v1.toFixed(2)}`);
      if (Math.abs((tot0[c] || 0) - (tot1[c] || 0)) > 1e-6) errs.push(`company ${c}: total ${tot0[c]} -> ${tot1[c]}`); }
    const still = (await call('product.product', 'read', [p.dups, ['active']], { context: CTX })).filter(r => r.active).map(r => r.id); if (still.length) errs.push(`dups still active ${still}`);
    const r = { kind: 'merge7', g: p.g, master: p.master, dups: p.dups, emptied, errs, ms: Date.now() - T0 }; X.push(r); if (errs.length) X.stop = true; return r; };
  // category by complete name; "<existing> / <Group>" is created under its parent with the parent's accounts for every company
  const CATF = ['property_account_income_categ_id', 'property_account_expense_categ_id', 'property_valuation', 'property_cost_method', 'property_stock_journal',
    'property_stock_valuation_account_id', 'property_price_difference_account_id', 'account_stock_variation_id', 'property_stock_account_production_cost_id'];
  X.catCache = {};
  X.category = async (path) => { if (X.catCache[path]) return X.catCache[path];
    const f = await call('product.category', 'search_read', [[['complete_name', '=', path]]], { fields: ['id'], context: CTX }); if (f.length) return (X.catCache[path] = f[0].id);
    const i = path.lastIndexOf(' / '); if (i < 0) throw new Error(`category ${path} missing`);
    const parent = await X.category(path.slice(0, i));
    const id = await call('product.category', 'create', [{ name: path.slice(i + 3), parent_id: parent }], { context: CTX });
    const fields = Object.keys(await call('product.category', 'fields_get', [CATF], { attributes: ['type'] }));
    for (const c of COMPANIES) { const p = (await call('product.category', 'read', [[parent], fields], { context: { ...CTX, allowed_company_ids: [c] } }))[0]; const v = {};
      for (const k of fields) v[k] = Array.isArray(p[k]) ? p[k][0] : p[k];
      await call('product.category', 'write', [[id], v], { context: { ...CTX, allowed_company_ids: [c] } }); }
    X.push({ kind: 'category created', path, id, parent }); return (X.catCache[path] = id); };
  X.setCategory = async ([t, path]) => { const id = await X.category(path);
    const t0 = (await call('product.template', 'read', [[t], ['categ_id', 'active']], { context: CTX }))[0]; if (!t0.active) { X.push({ kind: 'cat', t, skipped: 'template archived' }); return { errs: [] }; }
    if (t0.categ_id && t0.categ_id[0] === id) return { errs: [] };
    const acc = {}; for (const c of [1, 2]) { const r = await call('product.category', 'read', [[t0.categ_id[0], id], ['property_account_expense_categ_id']], { context: { ...CTX, allowed_company_ids: [c] } });
      acc[c] = r.map(x => x.property_account_expense_categ_id && x.property_account_expense_categ_id[0]); }
    await call('product.template', 'write', [[t], { categ_id: id }], { context: CTX });
    const change = [1, 2].filter(c => acc[c][0] !== acc[c][1]);
    X.push({ kind: 'cat', t, from: t0.categ_id && t0.categ_id[1], to: path, expenseAccountChanged: change }); return { errs: [] }; };
