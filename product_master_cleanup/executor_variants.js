// Variant conversion executor (class C). Needs executor.js loaded first (window.__ex: call, counts, stock, mergeModel).
// Template plan: {tk, name, master: var_id, attrs: [attribute names], items: [{var, vals: [values in attrs order]}]}
// Steps per template: attributes/values exist (dynamic) -> lines on the master template with the master's value only
// (Odoo writes a single-value line onto the existing variant) -> add the other values -> per other item: create the
// variant (same internal reference), Data Cleaning merge old item -> new variant (archive), its template references and
// vendor prices -> master template (vendor price pinned to the variant), cost per company = the old item's cost,
// old template archived -> rename the template -> verify qty/value per company and references.
(() => {
  const X = window.__ex, call = X.call;
  const CTX = { active_test: false, tracking_disable: true, mail_notrack: true, mail_create_nolog: true, lang: 'en_US' };
  const COMPANIES = [1, 2, 3, 4];
  const TMPL_REFS = [['purchase.order.line', 'x_studio_item'], ['x_purchase_order_line_d9d4d', 'x_studio_item'], ['x_item_listtt', 'x_studio_item_on_item_list'],
    ['x_employees_payments', 'x_studio_product'], ['ssc.subcontract.item', 'product_id'], ['x_product_template_line_d82d9', 'x_product_template_id'],
    ['product.pricelist.item', 'product_tmpl_id']];
  const COLOURS = { Black: '#000000', White: '#FFFFFF', Grey: '#808080', Orange: '#FF8C00', Red: '#D32F2F', Blue: '#1E63C4', Yellow: '#FFD600',
    Brown: '#795548', Beige: '#D8C8A8', Silver: '#C0C0C0', Green: '#2E7D32' };
  const log = (o) => X.log.push({ t: new Date().toISOString(), kind: 'variant', ...o });
  X.attrCache = X.attrCache || {};
  X.attr = async (name) => {
    if (X.attrCache[name]) return X.attrCache[name];
    let ids = await call('product.attribute', 'search', [[['name', '=ilike', name]]], { context: CTX });
    let id = ids[0];
    if (!id) id = await call('product.attribute', 'create', [{ name, create_variant: 'dynamic', display_type: name === 'Colour' ? 'color' : 'select' }], { context: CTX });
    else {
      const a = (await call('product.attribute', 'read', [[id], ['create_variant', 'name', 'attribute_line_ids']], { context: CTX }))[0];
      if (a.create_variant !== 'dynamic' && !a.attribute_line_ids.length) await call('product.attribute', 'write', [[id], { create_variant: 'dynamic', name }], { context: CTX });
      else if (a.create_variant !== 'dynamic') throw new Error(`attribute ${name} is used and not dynamic`);
    }
    const vals = await call('product.attribute.value', 'search_read', [[['attribute_id', '=', id]]], { fields: ['name'], context: CTX });
    X.attrCache[name] = { id, vals: Object.fromEntries(vals.map(v => [v.name, v.id])) };
    return X.attrCache[name];
  };
  X.attrValue = async (aname, vname) => {
    const a = await X.attr(aname);
    if (!a.vals[vname]) {
      const v = { attribute_id: a.id, name: vname };
      if (aname === 'Colour' && COLOURS[vname]) v.html_color = COLOURS[vname];
      a.vals[vname] = await call('product.attribute.value', 'create', [v], { context: CTX });
    }
    return a.vals[vname];
  };
  X.convertTemplate = async (tp) => {
    const T0 = Date.now(), errs = [], done = [];
    const items = tp.items, ids = items.map(i => i.var);
    const prods = await call('product.product', 'read', [ids, ['product_tmpl_id', 'active', 'default_code', 'product_template_attribute_value_ids']], { context: CTX });
    const byId = Object.fromEntries(prods.map(p => [p.id, p]));
    const m = byId[tp.master];
    if (!m || !m.active) throw new Error(`${tp.tk}: master ${tp.master} missing or archived`);
    const mT = m.product_tmpl_id[0];
    const todo = items.filter(i => i.var !== tp.master && byId[i.var] && byId[i.var].active && byId[i.var].product_tmpl_id[0] !== mT);
    const s0 = await X.stock(ids), tot0 = await X.companyTotals();
    // 1. attribute lines on the master template, master's own values first (single value = written on the existing variant)
    const mItem = items.find(i => i.var === tp.master);
    const lines = await call('product.template.attribute.line', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id', 'value_ids'], context: CTX });
    for (let k = 0; k < tp.attrs.length; k++) {
      const a = await X.attr(tp.attrs[k]);
      const mv = await X.attrValue(tp.attrs[k], mItem.vals[k]);
      if (!lines.find(l => l.attribute_id[0] === a.id))
        await call('product.template.attribute.line', 'create', [{ product_tmpl_id: mT, attribute_id: a.id, value_ids: [[6, 0, [mv]]] }], { context: CTX });
    }
    // 2. all values on the lines (dynamic: no variant is created by this)
    const lines2 = await call('product.template.attribute.line', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id', 'value_ids'], context: CTX });
    for (let k = 0; k < tp.attrs.length; k++) {
      const a = await X.attr(tp.attrs[k]);
      const need = []; for (const it of items) need.push(await X.attrValue(tp.attrs[k], it.vals[k]));
      const line = lines2.find(l => l.attribute_id[0] === a.id);
      const add = [...new Set(need)].filter(v => !line.value_ids.includes(v));
      if (add.length) await call('product.template.attribute.line', 'write', [[line.id], { value_ids: add.map(v => [4, v]) }], { context: CTX });
    }
    const ptav = await call('product.template.attribute.value', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id', 'product_attribute_value_id'], context: CTX });
    const ptavOf = (k, vname) => { const aid = X.attrCache[tp.attrs[k]].id, vid = X.attrCache[tp.attrs[k]].vals[vname];
      const r = ptav.find(x => x.attribute_id[0] === aid && x.product_attribute_value_id[0] === vid); if (!r) throw new Error(`${tp.tk}: no ptav ${tp.attrs[k]}=${vname}`); return r.id; };
    const mPtav = (await call('product.product', 'read', [[tp.master], ['product_template_attribute_value_ids']], { context: CTX }))[0].product_template_attribute_value_ids;
    const wantM = tp.attrs.map((a, k) => ptavOf(k, mItem.vals[k]));
    if (wantM.some(x => !mPtav.includes(x))) await call('product.product', 'write', [[tp.master], { product_template_attribute_value_ids: [[6, 0, wantM]] }], { context: CTX });
    // 3. one variant per other item, then merge the old item into it
    const mm = await X.mergeModel();
    for (const it of todo) {
      const o = byId[it.var], oT = o.product_tmpl_id[0];
      const combo = tp.attrs.map((a, k) => ptavOf(k, it.vals[k]));
      const c0 = await X.counts([it.var], [oT]);
      const nv = await call('product.product', 'create', [{ product_tmpl_id: mT, product_template_attribute_value_ids: [[6, 0, combo]], default_code: o.default_code || false }], { context: CTX });
      const gid = await call('data_merge.group', 'create', [{ model_id: mm }], { context: CTX });
      await call('data_merge.record', 'create', [[{ group_id: gid, res_id: nv, is_master: true }, { group_id: gid, res_id: it.var, is_master: false }]], { context: CTX });
      await call('data_merge.group', 'merge_records', [[gid]], { context: CTX });
      const si = await call('product.supplierinfo', 'search', [[['product_tmpl_id', '=', oT]]], { context: CTX });
      if (si.length) await call('product.supplierinfo', 'write', [si, { product_tmpl_id: mT, product_id: nv }], { context: CTX });
      for (const [mo, f] of TMPL_REFS) {
        const rids = await call(mo, 'search', [[[f, '=', oT]]], { context: CTX });
        for (let i = 0; i < rids.length; i += 2000) await call(mo, 'write', [rids.slice(i, i + 2000), { [f]: mT }], { context: CTX });
      }
      await call('product.template', 'write', [[oT], { active: false }], { context: CTX });
      for (const c of COMPANIES) {
        const want = s0.cost[`${it.var}@${c}`] || 0;
        const cur = (await call('product.product', 'read', [[nv], ['standard_price']], { context: { ...CTX, allowed_company_ids: [c] } }))[0].standard_price;
        if (Math.abs(cur - want) > 1e-6) await call('product.product', 'write', [[nv], { standard_price: want }], { context: { ...CTX, allowed_company_ids: [c] } });
      }
      const c1 = await X.counts([it.var, nv], [oT, mT]);
      for (const k of Object.keys(c0)) {
        const [mf, idp] = k.split('#');
        if (idp.startsWith('t')) { if (c1[`${mf}#t${oT}`]) errs.push(`${it.var}: ${mf} left on old template`); continue; }
        if (c1[`${mf}#${it.var}`]) errs.push(`${it.var}: ${mf} still on old item (${c1[`${mf}#${it.var}`]})`);
        if (!['stock.quant', 'product.value', 'stock.warehouse.orderpoint', 'product.supplierinfo'].includes(mf.split('.').slice(0, -1).join('.')) && c1[`${mf}#${nv}`] !== c0[k]) errs.push(`${it.var}: ${mf} new variant ${c1[`${mf}#${nv}`]} != ${c0[k]}`);
      }
      done.push({ old: it.var, nv, oT });
      if (errs.length) break;
    }
    // 4. template name
    if (tp.name) await call('product.template', 'write', [[mT], { name: tp.name }], { context: CTX });
    // 5. verify stock per company: sum over old items before == sum over master + new variants after; value identical
    const after = [tp.master, ...done.map(d => d.nv)];
    const s1 = await X.stock([...ids, ...done.map(d => d.nv)]), tot1 = await X.companyTotals();
    for (const c of COMPANIES) {
      const q0 = ids.reduce((a, id) => a + (s0.qty[`${id}@${c}`] || 0), 0), v0 = ids.reduce((a, id) => a + (s0.qty[`${id}@${c}`] || 0) * (s0.cost[`${id}@${c}`] || 0), 0);
      const q1 = after.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0), 0), v1 = after.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0) * (s1.cost[`${id}@${c}`] || 0), 0);
      const left = done.reduce((a, d) => a + (s1.qty[`${d.old}@${c}`] || 0), 0);
      if (Math.abs(q0 - q1) > 1e-6 || left) errs.push(`company ${c}: qty ${q0} -> ${q1} (left on old ${left})`);
      if (Math.abs(v0 - v1) > 0.01) errs.push(`company ${c}: value ${v0.toFixed(2)} -> ${v1.toFixed(2)}`);
      if (Math.abs((tot0[c] || 0) - (tot1[c] || 0)) > 1e-6) errs.push(`company ${c}: company total ${tot0[c]} -> ${tot1[c]}`);
    }
    const act = await call('product.product', 'read', [after, ['active']], { context: CTX });
    for (const a of act) if (!a.active) errs.push(`variant ${a.id} archived after conversion`);
    const res = { tk: tp.tk, mT, master: tp.master, converted: done, errs, ms: Date.now() - T0 };
    log(res); if (errs.length) X.stop = true; return res;
  };
  X.runVariants = async (tps) => {
    X.vbatch = { total: tps.length, done: 0, errors: 0, current: null, t0: Date.now() };
    for (const tp of tps) {
      if (X.stop) { log({ tk: tp.tk, skipped: 'stopped after an error' }); continue; }
      X.vbatch.current = tp.tk;
      try { const r = await X.convertTemplate(tp); if (r.errs.length) X.vbatch.errors++; }
      catch (e) { X.stop = true; X.vbatch.errors++; log({ tk: tp.tk, exception: e.message.slice(0, 800) }); }
      X.vbatch.done++;
    }
    X.vbatch.current = null; X.vbatch.secs = Math.round((Date.now() - X.vbatch.t0) / 1000);
    return X.vbatch;
  };
  return 'variant executor loaded';
})();
