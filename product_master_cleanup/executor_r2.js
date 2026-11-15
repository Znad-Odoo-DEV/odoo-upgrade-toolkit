// Round-2 executor (dev_0 first). Paste once into a tab on <db>/robots.txt; it saves itself in localStorage:
// after a reload: re-paste this file (preferred). The copy kept in localStorage is our own code on the dev_0 origin; eval it only in that tab.
function __pcInit() {
  const CTX = { active_test: false, tracking_disable: true, mail_notrack: true, mail_create_nolog: true, lang: 'en_US' };
  const COMPANIES = [1, 2, 3, 4];
  const READ = /^(search_read|read|search|search_count|formatted_read_group|fields_get)$/;
  const call = async (model, method, args = [], kwargs = {}) => {
    for (let i = 0; ; i++) {
      try {
        const r = await fetch(`/web/dataset/call_kw/${model}/${method}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs } }) }).then(r => r.json());
        if (r.error) throw Object.assign(new Error(`${model}.${method}: ${r.error.data?.message || r.error.message}`), { rpc: true });
        return r.result;
      } catch (e) { if (e.rpc || !READ.test(method) || i >= 4) throw e; await new Promise(r => setTimeout(r, 1500 * (i + 1))); }
    }
  };
  const X = window.__ex = { call, stop: false, log: [] };
  try { X.log = JSON.parse(localStorage.getItem('pc_log2') || '[]'); } catch (e) { X.log = []; }
  X.push = (o) => { X.log.push({ t: new Date().toISOString(), ...o }); try { localStorage.setItem('pc_log2', JSON.stringify(X.log)); } catch (e) {} };
  const VAR_REFS = [['stock.move','product_id'],['stock.move.line','product_id'],['stock.quant','product_id'],['account.analytic.line','product_id'],['purchase.order.line','product_id'],['ssc.request.material.line','product_id'],['account.move.line','product_id'],['product.supplierinfo','product_id'],['product.value','product_id'],['purchase.requisition.line','product_id'],['project.project','timesheet_product_id'],['stock.warehouse.orderpoint','product_id'],['approval.product.line','product_id'],['sale.order.line','product_id'],['product.pricelist.item','product_id'],['ssc.boq.line','product_id']];
  const TREF = [['purchase.order.line','x_studio_item'],['x_purchase_order_line_d9d4d','x_studio_item'],['x_item_listtt','x_studio_item_on_item_list'],['x_employees_payments','x_studio_product'],['ssc.subcontract.item','product_id'],['x_product_template_line_d82d9','x_product_template_id'],['product.pricelist.item','product_tmpl_id']];
  const ALL_TREF = [['product.supplierinfo','product_tmpl_id'], ...TREF];
  const SKIPCMP = ['stock.quant', 'product.value', 'stock.warehouse.orderpoint', 'product.supplierinfo'];
  X.counts = async (varIds, tmplIds) => {
    const out = {}; const jobs = [];
    for (const [m, f] of VAR_REFS) if (varIds.length) jobs.push([m, f, varIds, '']);
    for (const [m, f] of ALL_TREF) if (tmplIds.length) jobs.push([m, f, tmplIds, 't']);
    for (const [m, f, ids, pre] of jobs) for (const i of ids) out[`${m}.${f}#${pre}${i}`] = 0;
    for (let k = 0; k < jobs.length; k += 6) await Promise.all(jobs.slice(k, k + 6).map(async ([m, f, ids, pre]) => {
      const g = await call(m, 'formatted_read_group', [], { domain: [[f, 'in', ids]], groupby: [f], aggregates: ['__count'], context: CTX });
      for (const r of g) if (r[f]) out[`${m}.${f}#${pre}${r[f][0]}`] = r.__count; }));
    return out;
  };
  X.stock = async (varIds) => {
    const g = await call('stock.quant', 'formatted_read_group', [], { domain: [['product_id', 'in', varIds], ['location_id.usage', '=', 'internal']], groupby: ['product_id', 'company_id'], aggregates: ['quantity:sum'], context: CTX });
    const qty = {}; for (const r of g) qty[`${r.product_id[0]}@${r.company_id[0]}`] = r['quantity:sum'];
    const cost = {}; for (const c of COMPANIES) for (const p of await call('product.product', 'read', [varIds, ['standard_price']], { context: { ...CTX, allowed_company_ids: [c] } })) cost[`${p.id}@${c}`] = p.standard_price;
    return { qty, cost };
  };
  X.companyTotals = async () => { const g = await call('stock.quant', 'formatted_read_group', [], { domain: [['location_id.usage', '=', 'internal']], groupby: ['company_id'], aggregates: ['quantity:sum'], context: CTX }); return Object.fromEntries(g.map(r => [r.company_id[0], Math.round(r['quantity:sum'] * 1000) / 1000])); };
  X.mergeModel = async () => { if (X.mmid) return X.mmid; const f = await call('data_merge.model', 'search', [[['name', '=', 'Product cleanup 2026-11 (manual)']]], { context: CTX });
    if (f.length) return (X.mmid = f[0]); const im = await call('ir.model', 'search', [[['model', '=', 'product.product']]]);
    return (X.mmid = await call('data_merge.model', 'create', [{ name: 'Product cleanup 2026-11 (manual)', res_model_id: im[0], removal_mode: 'archive', merge_mode: 'manual' }], { context: CTX })); };
  // ---------- duplicate merge (weighted-average cost written after the merge) ----------
  X.mergeGroup = async (p) => {
    const T0 = Date.now(); const ids = [p.master, ...p.dups];
    const prods = await call('product.product', 'read', [ids, ['product_tmpl_id', 'active']], { context: CTX });
    if (prods.length !== ids.length) throw new Error(`${p.g}: missing products`);
    if (!prods.find(r => r.id === p.master).active) throw new Error(`${p.g}: master ${p.master} is archived`);
    if (prods.filter(r => r.id !== p.master).every(r => !r.active)) { const r = { kind: 'merge', g: p.g, skipped: 'already merged', errs: [] }; X.push(r); return r; }
    const tmplOf = Object.fromEntries(prods.map(r => [r.id, r.product_tmpl_id[0]]));
    const mT = tmplOf[p.master], dT = [...new Set(p.dups.map(d => tmplOf[d]))].filter(t => t !== mT);
    const [tot0, c0, s0] = await Promise.all([X.companyTotals(), X.counts(ids, [mT, ...dT]), X.stock(ids)]);
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
    if (dT.length) { for (const [m, f] of ALL_TREF) { const rids = await call(m, 'search', [[[f, 'in', dT]]], { context: CTX }); for (let i = 0; i < rids.length; i += 2000) await call(m, 'write', [rids.slice(i, i + 2000), { [f]: mT }], { context: CTX }); }
      const act = (await call('product.template', 'read', [dT, ['active']], { context: CTX })).filter(r => r.active).map(r => r.id); if (act.length) await call('product.template', 'write', [act, { active: false }], { context: CTX }); }
    if (p.rename) await call('product.template', 'write', [[mT], { name: p.rename }], { context: CTX });
    const [c1, s1, tot1] = await Promise.all([X.counts(ids, [mT, ...dT]), X.stock(ids), X.companyTotals()]);
    const errs = [];
    for (const [m, f] of VAR_REFS) { const k = `${m}.${f}`; const before = ids.reduce((a, id) => a + c0[`${k}#${id}`], 0);
      for (const d of p.dups) if (c1[`${k}#${d}`] && m !== 'stock.quant') errs.push(`${k} still on dup ${d}`);
      if (c1[`${k}#${p.master}`] !== before && !SKIPCMP.includes(m)) errs.push(`${k} master ${c1[`${k}#${p.master}`]} != ${before}`); }
    for (const [m, f] of ALL_TREF) { const before = [mT, ...dT].reduce((a, t) => a + c0[`${m}.${f}#t${t}`], 0); if (c1[`${m}.${f}#t${mT}`] !== before) errs.push(`${m}.${f} master tmpl ${c1[`${m}.${f}#t${mT}`]} != ${before}`); }
    for (const c of COMPANIES) { const q0 = ids.reduce((a, id) => a + (s0.qty[`${id}@${c}`] || 0), 0), q1 = ids.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0), 0), qm = s1.qty[`${p.master}@${c}`] || 0;
      const v1 = ids.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0) * (s1.cost[`${id}@${c}`] || 0), 0);
      if (Math.abs(q0 - q1) > 1e-6 || Math.abs(qm - q1) > 1e-6) errs.push(`company ${c}: qty ${q0} -> ${q1}, master ${qm}`);
      if (Math.abs(value0[c] - v1) > 0.01) errs.push(`company ${c}: value ${value0[c].toFixed(2)} -> ${v1.toFixed(2)}`);
      if (Math.abs((tot0[c] || 0) - (tot1[c] || 0)) > 1e-6) errs.push(`company ${c}: total ${tot0[c]} -> ${tot1[c]}`); }
    const still = (await call('product.product', 'read', [p.dups, ['active']], { context: CTX })).filter(r => r.active).map(r => r.id); if (still.length) errs.push(`dups still active ${still}`);
    const res = { kind: 'merge', g: p.g, master: p.master, dups: p.dups, errs, ms: Date.now() - T0 }; X.push(res); if (errs.length) X.stop = true; return res;
  };
  // ---------- variants (resumable v3) ----------
  X.attrCache = {};
  X.attr = async (name) => { if (X.attrCache[name]) return X.attrCache[name];
    const id = (await call('product.attribute', 'search', [[['name', '=ilike', name]]], { context: CTX }))[0]; if (!id) throw new Error(`attribute ${name} missing`);
    const vals = await call('product.attribute.value', 'search_read', [[['attribute_id', '=', id]]], { fields: ['name'], context: CTX });
    return (X.attrCache[name] = { id, vals: Object.fromEntries(vals.map(v => [v.name, v.id])) }); };
  X.attrValue = async (aname, vname) => { const a = await X.attr(aname); if (!a.vals[vname]) a.vals[vname] = await call('product.attribute.value', 'create', [{ attribute_id: a.id, name: vname }], { context: CTX }); return a.vals[vname]; };
  X.convertTemplate = async (tp) => {
    const T0 = Date.now(), errs = [], done = [], pre = [];
    const ids = tp.items.map(i => i.var);
    const prods = await call('product.product', 'read', [ids, ['product_tmpl_id', 'active', 'default_code']], { context: CTX });
    const byId = Object.fromEntries(prods.map(p => [p.id, p]));
    const m = byId[tp.master]; if (!m || !m.active) throw new Error(`${tp.tk}: master ${tp.master} missing or archived`);
    const mT = m.product_tmpl_id[0]; const mItem = tp.items.find(i => i.var === tp.master);
    const lines = await call('product.template.attribute.line', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id', 'value_ids'], context: CTX });
    for (let k = 0; k < tp.attrs.length; k++) { const a = await X.attr(tp.attrs[k]); const mv = await X.attrValue(tp.attrs[k], mItem.vals[k]);
      if (!lines.find(l => l.attribute_id[0] === a.id)) await call('product.template.attribute.line', 'create', [{ product_tmpl_id: mT, attribute_id: a.id, value_ids: [[6, 0, [mv]]] }], { context: CTX }); }
    const lines2 = await call('product.template.attribute.line', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id', 'value_ids'], context: CTX });
    for (let k = 0; k < tp.attrs.length; k++) { const a = await X.attr(tp.attrs[k]); const need = []; for (const it of tp.items) need.push(await X.attrValue(tp.attrs[k], it.vals[k]));
      const line = lines2.find(l => l.attribute_id[0] === a.id); const add = [...new Set(need)].filter(v => !line.value_ids.includes(v));
      if (add.length) await call('product.template.attribute.line', 'write', [[line.id], { value_ids: add.map(v => [4, v]) }], { context: CTX }); }
    const ptav = await call('product.template.attribute.value', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id', 'product_attribute_value_id'], context: CTX });
    const ptavOf = (k, vname) => { const aid = X.attrCache[tp.attrs[k]].id, vid = X.attrCache[tp.attrs[k]].vals[vname]; const r = ptav.find(x => x.attribute_id[0] === aid && x.product_attribute_value_id[0] === vid); if (!r) throw new Error(`${tp.tk}: no ptav ${tp.attrs[k]}=${vname}`); return r.id; };
    const key = (arr) => [...arr].sort((a, b) => a - b).join(',');
    const wantM = tp.attrs.map((a, k) => ptavOf(k, mItem.vals[k]));
    const mPtav = (await call('product.product', 'read', [[tp.master], ['product_template_attribute_value_ids']], { context: CTX }))[0].product_template_attribute_value_ids;
    if (key(mPtav) !== key(wantM)) await call('product.product', 'write', [[tp.master], { product_template_attribute_value_ids: [[6, 0, wantM]] }], { context: CTX });
    const exist = await call('product.product', 'search_read', [[['product_tmpl_id', '=', mT], ['active', '=', true]]], { fields: ['product_template_attribute_value_ids'], context: CTX });
    const byKey = Object.fromEntries(exist.map(v => [key(v.product_template_attribute_value_ids), v.id]));
    const todo = [];
    for (const it of tp.items) { if (it.var === tp.master) continue; const o = byId[it.var]; if (!o) { errs.push(`${it.var} missing`); continue; }
      const combo = tp.attrs.map((a, k) => ptavOf(k, it.vals[k])); const nvExist = byKey[key(combo)];
      if (o.active && o.product_tmpl_id[0] !== mT) todo.push({ it, o, oT: o.product_tmpl_id[0], combo, reuse: nvExist && nvExist !== it.var ? nvExist : null });
      else if (!o.active) { if (nvExist) pre.push({ old: it.var, nv: nvExist, oT: o.product_tmpl_id[0] }); else errs.push(`${it.var} archived but no variant for its combination`); } }
    const preNv = pre.map(d => d.nv).concat(todo.filter(t => t.reuse).map(t => t.reuse));
    const [s0, tot0, c0] = await Promise.all([X.stock([...ids, ...preNv]), X.companyTotals(), todo.length ? X.counts(todo.map(t => t.it.var), [...new Set(todo.map(t => t.oT))]) : {}]);
    const mm = await X.mergeModel();
    for (const t of todo) {
      const nv = t.reuse || await call('product.product', 'create', [{ product_tmpl_id: mT, product_template_attribute_value_ids: [[6, 0, t.combo]], default_code: t.o.default_code || false }], { context: CTX });
      const gid = await call('data_merge.group', 'create', [{ model_id: mm }], { context: CTX });
      await call('data_merge.record', 'create', [[{ group_id: gid, res_id: nv, is_master: true }, { group_id: gid, res_id: t.it.var, is_master: false }]], { context: CTX });
      await call('data_merge.group', 'merge_records', [[gid]], { context: CTX });
      done.push({ old: t.it.var, nv, oT: t.oT, reused: !!t.reuse });
    }
    const all = [...pre, ...done]; const oTs = [...new Set(all.map(d => d.oT))].filter(t => t !== mT);
    for (const d of all) { const si = await call('product.supplierinfo', 'search', [[['product_tmpl_id', '=', d.oT]]], { context: CTX }); if (si.length) await call('product.supplierinfo', 'write', [si, { product_tmpl_id: mT, product_id: d.nv }], { context: CTX }); }
    if (oTs.length) { for (const [mo, f] of TREF) { const rids = await call(mo, 'search', [[[f, 'in', oTs]]], { context: CTX }); for (let i = 0; i < rids.length; i += 2000) await call(mo, 'write', [rids.slice(i, i + 2000), { [f]: mT }], { context: CTX }); }
      const act = (await call('product.template', 'read', [oTs, ['active']], { context: CTX })).filter(r => r.active).map(r => r.id); if (act.length) await call('product.template', 'write', [act, { active: false }], { context: CTX }); }
    if (all.length) for (const c of COMPANIES) { const cur = await call('product.product', 'read', [all.map(d => d.nv), ['standard_price']], { context: { ...CTX, allowed_company_ids: [c] } });
      for (const r of cur) { const d = all.find(x => x.nv === r.id); const want = s0.cost[`${d.old}@${c}`] || 0; if (Math.abs(r.standard_price - want) > 1e-6) await call('product.product', 'write', [[r.id], { standard_price: want }], { context: { ...CTX, allowed_company_ids: [c] } }); } }
    if (tp.name) await call('product.template', 'write', [[mT], { name: tp.name }], { context: CTX });
    const after = [tp.master, ...all.map(d => d.nv)];
    const [c1, s1, tot1] = await Promise.all([all.length ? X.counts([...all.map(d => d.old), ...all.map(d => d.nv)], [...oTs, mT]) : {}, X.stock([...ids, ...all.map(d => d.nv)]), X.companyTotals()]);
    for (const d of all) for (const [m, f] of VAR_REFS) { const k = `${m}.${f}`; if (c1[`${k}#${d.old}`]) errs.push(`${d.old}: ${k} still on old item`);
      if (c0[`${k}#${d.old}`] !== undefined && !SKIPCMP.includes(m) && c1[`${k}#${d.nv}`] !== c0[`${k}#${d.old}`]) errs.push(`${d.old}: ${k} new variant ${c1[`${k}#${d.nv}`]} != ${c0[`${k}#${d.old}`]}`); }
    for (const t of oTs) for (const [m, f] of ALL_TREF) if (c1[`${m}.${f}#t${t}`]) errs.push(`${m}.${f} left on old template ${t}`);
    const before = [...ids, ...preNv];
    for (const c of COMPANIES) {
      const q0 = before.reduce((a, id) => a + (s0.qty[`${id}@${c}`] || 0), 0), v0 = before.reduce((a, id) => a + (s0.qty[`${id}@${c}`] || 0) * (s0.cost[`${id}@${c}`] || 0), 0);
      const q1 = after.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0), 0), v1 = after.reduce((a, id) => a + (s1.qty[`${id}@${c}`] || 0) * (s1.cost[`${id}@${c}`] || 0), 0);
      const left = all.reduce((a, d) => a + (s1.qty[`${d.old}@${c}`] || 0), 0);
      if (Math.abs(q0 - q1) > 1e-6 || left) errs.push(`company ${c}: qty ${q0} -> ${q1} (left on old ${left})`);
      if (pre.length === 0 && Math.abs(v0 - v1) > 0.01) errs.push(`company ${c}: value ${v0.toFixed(2)} -> ${v1.toFixed(2)}`);
      if (Math.abs((tot0[c] || 0) - (tot1[c] || 0)) > 1e-6) errs.push(`company ${c}: company total ${tot0[c]} -> ${tot1[c]}`); }
    const act = await call('product.product', 'read', [after, ['active']], { context: CTX }); for (const a of act) if (!a.active) errs.push(`variant ${a.id} archived after conversion`);
    const res = { kind: 'variant', tk: tp.tk, mT, master: tp.master, converted: done.map(d => [d.old, d.nv, d.reused ? 1 : 0]), already: pre.length, errs, ms: Date.now() - T0 };
    X.push(res); if (errs.length) X.stop = true; return res;
  };
  // ---------- simple template updates (name / category / unit) and garbage archive ----------
  X.update = async ([t, vals]) => { await call('product.template', 'write', [[t], vals], { context: CTX }); X.push({ kind: 'update', t, vals }); return { errs: [] }; };
  X.archiveGarbage = async (t) => { const v = await call('product.product', 'search', [[['product_tmpl_id', '=', t]]], { context: CTX });
    const c = await X.counts(v, [t]); const used = Object.entries(c).filter(([k, n]) => n).map(([k]) => k);
    if (used.length) { X.push({ kind: 'garbage', t, skipped: used }); return { errs: [] }; }
    await call('product.template', 'write', [[t], { active: false }], { context: CTX }); X.push({ kind: 'garbage', t, archived: true }); return { errs: [] }; };
  // ---------- generic parallel runner ----------
  X.run = async (name, items, fn, workers = 6) => { const queue = [...items]; const st = X[name] = { total: items.length, done: 0, errors: 0, t0: Date.now() };
    const w = async () => { while (queue.length && !X.stop) { const it = queue.shift();
      try { const r = await fn(it); if (r && r.errs && r.errs.length) st.errors++; } catch (e) { X.stop = true; st.errors++; X.push({ kind: name, item: JSON.stringify(it).slice(0, 200), exception: e.message.slice(0, 600) }); }
      st.done++; } };
    await Promise.all(Array.from({ length: workers }, w)); st.finished = true; st.secs = Math.round((Date.now() - st.t0) / 1000); return st; };
  return 'pc executor ready';
}
try { localStorage.setItem('pc_exec', '(' + __pcInit.toString() + ')()'); } catch (e) {}
__pcInit();
