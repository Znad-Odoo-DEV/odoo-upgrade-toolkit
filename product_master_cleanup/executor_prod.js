// PRODUCTION executor (all rounds, fixes of 2026-11-15 included). Log key pc_logP.
// Round-2 executor base. Paste once into a tab on <db>/robots.txt; it saves itself in localStorage:
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
  try { X.log = JSON.parse(localStorage.getItem('pc_logP') || '[]'); } catch (e) { X.log = []; }
  X.push = (o) => { X.log.push({ t: new Date().toISOString(), ...o }); try { localStorage.setItem('pc_logP', JSON.stringify(X.log)); } catch (e) {} };
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
      if (Math.abs(value0[c] - v1) > 0.01 + q1 * 0.00005) errs.push(`company ${c}: value ${value0[c].toFixed(2)} -> ${v1.toFixed(2)}`);
      if (Math.abs((tot0[c] || 0) - (tot1[c] || 0)) > 1e-6) errs.push(`company ${c}: total ${tot0[c]} -> ${tot1[c]}`); }
    const still = (await call('product.product', 'read', [p.dups, ['active']], { context: CTX })).filter(r => r.active).map(r => r.id); if (still.length) errs.push(`dups still active ${still}`);
    const res = { kind: 'merge', g: p.g, master: p.master, dups: p.dups, errs, ms: Date.now() - T0 }; X.push(res); if (errs.length) X.stop = true; return res;
  };
  // ---------- variants (resumable v3) ----------
  X.attrCache = {};
  const ADEF = { 'Pipe Size': ['select', 10], 'Thread Size': ['radio', 20], 'Angle': ['radio', 30], 'Material': ['pills', 40], 'Type': ['select', 50], 'Brand': ['pills', 60], 'Junction Type': ['pills', 70], 'Air Type': ['pills', 80], 'Cores': ['radio', 90], 'Cable Size': ['select', 100], 'Size': ['select', 110], 'Diameter': ['select', 120], 'Rebar Diameter': ['select', 130], 'Length': ['select', 140], 'Width': ['select', 150], 'Thickness': ['select', 160], 'Capacity': ['radio', 170], 'Grade': ['pills', 180], 'Temperature': ['radio', 190], 'Colour': ['color', 200], 'Model': ['select', 210], 'Pack': ['select', 220], 'Power': ['select', 230], 'Steps': ['select', 240], 'Weight': ['select', 250], 'Volume': ['select', 260], 'Voltage': ['select', 270], 'IP Rating': ['select', 280], 'Finish': ['select', 290] };
  // an attribute missing on this database is created as dynamic (never 'always': that would generate variants by itself)
  X.attr = async (name) => { if (X.attrCache[name]) return X.attrCache[name];
    let a = (await call('product.attribute', 'search_read', [[['name', '=ilike', name]]], { fields: ['create_variant'], context: CTX }))[0];
    if (!a) { if (!ADEF[name]) throw new Error(`attribute ${name} not in the catalogue`);
      a = { id: await call('product.attribute', 'create', [{ name, create_variant: 'dynamic', display_type: ADEF[name][0], sequence: ADEF[name][1] }], { context: CTX }), create_variant: 'dynamic' };
      X.push({ kind: 'attribute created', name, id: a.id }); }
    if (a.create_variant !== 'dynamic') throw new Error(`attribute ${name} is ${a.create_variant}, must be dynamic`);
    const vals = await call('product.attribute.value', 'search_read', [[['attribute_id', '=', a.id]]], { fields: ['name'], context: CTX });
    return (X.attrCache[name] = { id: a.id, vals: Object.fromEntries(vals.map(v => [v.name, v.id])) }); };
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
    { const byT = {}; for (const d of all) (byT[d.oT] = byT[d.oT] || []).push(d);
      for (const oT of Object.keys(byT)) { const si = await call('product.supplierinfo', 'search_read', [[['product_tmpl_id', '=', +oT]]], { fields: ['product_id'], context: CTX });
        for (const s of si) { const v = { product_tmpl_id: mT }; if (!s.product_id && byT[oT].length === 1) v.product_id = byT[oT][0].nv; await call('product.supplierinfo', 'write', [[s.id], v], { context: CTX }); } } }
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
      if (pre.length === 0 && Math.abs(v0 - v1) > 0.01 + q1 * 0.00005) errs.push(`company ${c}: value ${v0.toFixed(2)} -> ${v1.toFixed(2)}`);
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
  // ---------- 2026-11-15 additions ----------
  // merge + the supplier price gets its variant when the master template has several variants
  X.mergeGroupSI = async (p) => {
    const pr = await call('product.product', 'read', [[p.master, ...p.dups], ['product_tmpl_id']], { context: CTX });
    const mT = pr.find(r => r.id === p.master).product_tmpl_id[0];
    const dT = [...new Set(pr.filter(r => r.id !== p.master).map(r => r.product_tmpl_id[0]))].filter(t => t !== mT);
    const si0 = dT.length ? await call('product.supplierinfo', 'search', [[['product_tmpl_id', 'in', dT], ['product_id', '=', false]]], { context: CTX }) : [];
    const r = await X.mergeGroup(p);
    if (si0.length && !(r.errs && r.errs.length) && !r.skipped) {
      const vc = (await call('product.template', 'read', [[mT], ['product_variant_count']], { context: CTX }))[0].product_variant_count;
      if (vc > 1) { await call('product.supplierinfo', 'write', [si0, { product_id: p.master }], { context: CTX }); X.push({ kind: 'si_fix', g: p.g, si: si0, product_id: p.master }); } }
    return r; };
  // merge groups that share a template run one after the other (their checks count the same template)
  X.mergeBuckets = async (name, groups, workers = 4) => {
    const ids = [...new Set(groups.flatMap(p => [p.master, ...p.dups]))]; const t = {};
    for (let i = 0; i < ids.length; i += 500) for (const r of await call('product.product', 'read', [ids.slice(i, i + 500), ['product_tmpl_id']], { context: CTX })) t[r.id] = r.product_tmpl_id[0];
    const par = {}; const f = x => { while (par[x] !== undefined && par[x] !== x) x = par[x]; return x; };
    for (const p of groups) { const ts = [p.master, ...p.dups].map(i => t[i]).filter(Boolean); ts.forEach(x => { if (par[x] === undefined) par[x] = x; }); for (const x of ts.slice(1)) par[f(x)] = f(ts[0]); }
    const B = {}; for (const p of groups) { const k = f(t[p.master]); (B[k] = B[k] || []).push(p); }
    return X.run(name, Object.values(B), async (b) => { let last = { errs: [] }; for (const p of b) { last = await X.mergeGroupSI(p); if (X.stop) break; } return last; }, workers); };
  // ONE item becomes its own template with attribute values; the product keeps its id, nothing moves
  X.singleTemplate = async (tp) => {
    const T0 = Date.now(), errs = [], it = tp.items[0], id = tp.master;
    if (tp.items.length !== 1 || it.var !== id) throw new Error(`${tp.tk}: not a single-item entry`);
    const p = (await call('product.product', 'read', [[id], ['product_tmpl_id', 'active', 'product_template_attribute_value_ids']], { context: CTX }))[0];
    if (!p || !p.active) throw new Error(`${tp.tk}: ${id} missing or archived`);
    const mT = p.product_tmpl_id[0];
    const t0 = (await call('product.template', 'read', [[mT], ['product_variant_count', 'name']], { context: CTX }))[0];
    if (t0.product_variant_count !== 1) { const r = { kind: 'single', tk: tp.tk, skipped: `template ${mT} has ${t0.product_variant_count} variants`, errs: [] }; X.push(r); return r; }
    const s0 = await X.stock([id]);
    const lines = await call('product.template.attribute.line', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id', 'value_ids'], context: CTX });
    for (let k = 0; k < tp.attrs.length; k++) {
      const a = await X.attr(tp.attrs[k]); const v = await X.attrValue(tp.attrs[k], it.vals[k]); const l = lines.find(x => x.attribute_id[0] === a.id);
      if (!l) await call('product.template.attribute.line', 'create', [{ product_tmpl_id: mT, attribute_id: a.id, value_ids: [[6, 0, [v]]] }], { context: CTX });
      else if (!l.value_ids.includes(v)) await call('product.template.attribute.line', 'write', [[l.id], { value_ids: [[4, v]] }], { context: CTX }); }
    const ptav = await call('product.template.attribute.value', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id', 'product_attribute_value_id'], context: CTX });
    const want = tp.attrs.map((a, k) => { const aid = X.attrCache[a].id, vid = X.attrCache[a].vals[it.vals[k]];
      const r = ptav.find(x => x.attribute_id[0] === aid && x.product_attribute_value_id[0] === vid); if (!r) throw new Error(`${tp.tk}: no ptav ${a}=${it.vals[k]}`); return r.id; });
    const key = a => [...a].sort((x, y) => x - y).join(',');
    if (key(p.product_template_attribute_value_ids) !== key(want)) await call('product.product', 'write', [[id], { product_template_attribute_value_ids: [[6, 0, want]] }], { context: CTX });
    if (tp.name && tp.name !== t0.name) await call('product.template', 'write', [[mT], { name: tp.name }], { context: CTX });
    const [p1, t1, s1] = await Promise.all([call('product.product', 'read', [[id], ['product_tmpl_id', 'active', 'product_template_attribute_value_ids']], { context: CTX }),
      call('product.template', 'read', [[mT], ['product_variant_count', 'name']], { context: CTX }), X.stock([id])]);
    if (!p1[0].active || p1[0].product_tmpl_id[0] !== mT) errs.push('product moved or archived');
    if (key(p1[0].product_template_attribute_value_ids) !== key(want)) errs.push('values not set');
    if (t1[0].product_variant_count !== 1) errs.push(`template now has ${t1[0].product_variant_count} variants`);
    if (tp.name && t1[0].name !== tp.name) errs.push('name not set');
    for (const k of new Set([...Object.keys(s0.qty), ...Object.keys(s1.qty)])) if (Math.abs((s0.qty[k] || 0) - (s1.qty[k] || 0)) > 1e-6) errs.push(`qty ${k}`);
    for (const k of new Set([...Object.keys(s0.cost), ...Object.keys(s1.cost)])) if (Math.abs((s0.cost[k] || 0) - (s1.cost[k] || 0)) > 1e-6) errs.push(`cost ${k}`);
    const r = { kind: 'single', tk: tp.tk, mT, id, old: t0.name, name: tp.name, errs, ms: Date.now() - T0 }; X.push(r); if (errs.length) X.stop = true; return r; };
  // a spec in a variant template's NAME becomes one attribute value on every variant ({t, name, specs: [[attr, value]]})
  X.moveSpec = async (m) => {
    const T0 = Date.now(), errs = [];
    const t0 = (await call('product.template', 'read', [[m.t], ['name', 'product_variant_ids', 'active']], { context: CTX }))[0];
    if (!t0 || !t0.active) throw new Error(`T${m.t} missing or archived`);
    const vids = t0.product_variant_ids; const s0 = await X.stock(vids);
    const lines = await call('product.template.attribute.line', 'search_read', [[['product_tmpl_id', '=', m.t]]], { fields: ['attribute_id'], context: CTX });
    for (const [an] of m.specs) { const a = await X.attr(an);
      if (lines.find(l => l.attribute_id[0] === a.id)) { const r = { kind: 'movespec', t: m.t, skipped: `attribute ${an} already on the template`, errs: [] }; X.push(r); return r; } }
    const add = [];
    for (const [an, vn] of m.specs) { const a = await X.attr(an); const v = await X.attrValue(an, vn);
      await call('product.template.attribute.line', 'create', [{ product_tmpl_id: m.t, attribute_id: a.id, value_ids: [[6, 0, [v]]] }], { context: CTX });
      const p = await call('product.template.attribute.value', 'search', [[['product_tmpl_id', '=', m.t], ['attribute_id', '=', a.id], ['product_attribute_value_id', '=', v]]], { context: CTX });
      if (p.length !== 1) throw new Error(`T${m.t}: ptav ${an}=${vn} not found`); add.push(p[0]); }
    for (const v of await call('product.product', 'read', [vids, ['product_template_attribute_value_ids']], { context: CTX })) {
      const want = [...new Set([...v.product_template_attribute_value_ids, ...add])];
      if (want.length !== v.product_template_attribute_value_ids.length) await call('product.product', 'write', [[v.id], { product_template_attribute_value_ids: [[6, 0, want]] }], { context: CTX }); }
    if (m.name) await call('product.template', 'write', [[m.t], { name: m.name }], { context: CTX });
    const [t1, V1, s1] = await Promise.all([call('product.template', 'read', [[m.t], ['name', 'product_variant_ids']], { context: CTX }),
      call('product.product', 'read', [vids, ['product_template_attribute_value_ids', 'active']], { context: CTX }), X.stock(vids)]);
    if (t1[0].product_variant_ids.length !== vids.length) errs.push('variants changed');
    for (const v of V1) { if (!v.active) errs.push(`${v.id} archived`); for (const p of add) if (!v.product_template_attribute_value_ids.includes(p)) errs.push(`${v.id} missing value`); }
    if (m.name && t1[0].name !== m.name) errs.push('name not set');
    for (const k of new Set([...Object.keys(s0.qty), ...Object.keys(s1.qty)])) if (Math.abs((s0.qty[k] || 0) - (s1.qty[k] || 0)) > 1e-6) errs.push(`qty ${k}`);
    const r = { kind: 'movespec', t: m.t, old: t0.name, name: m.name, specs: m.specs, variants: vids.length, errs, ms: Date.now() - T0 }; X.push(r); if (errs.length) X.stop = true; return r; };
  // rounds 5-6: S- single template, T- existing template (missing attributes added as Not Specified first), N- new family
  X.r5 = async (tp) => {
    if (tp.tk.startsWith('S')) return X.singleTemplate(tp);
    if (tp.tk.startsWith('T')) {
      const mT = (await call('product.product', 'read', [[tp.master], ['product_tmpl_id']], { context: CTX }))[0].product_tmpl_id[0];
      const have = new Set((await call('product.template.attribute.line', 'search_read', [[['product_tmpl_id', '=', mT]]], { fields: ['attribute_id'], context: CTX })).map(l => l.attribute_id[1]));
      const miss = tp.attrs.filter(a => !have.has(a));
      if (miss.length) { const r = await X.moveSpec({ t: mT, name: null, specs: miss.map(a => [a, 'Not Specified']) }); if (r.skipped || r.errs.length) return r; } }
    return X.convertTemplate(tp); };
  // every attribute value first, one by one (parallel creation would make duplicates)
  X.prepValues = async (plan) => { let n = 0; for (const tp of plan) for (let k = 0; k < tp.attrs.length; k++) for (const it of tp.items) { await X.attrValue(tp.attrs[k], it.vals[k]); n++; } return n; };
  // compact plan strings -> objects (separators never occur inside fields)
  X.parseVariants = (S) => S.split('#').map(b => { const [tk, name, attrs, master, items] = b.split('|');
    return { tk, name, attrs: attrs.split('^'), master: +master, items: items.split('~').map(x => { const p = x.split('^'); return { var: +p[0], vals: p.slice(1) }; }) }; });
  X.parseMerges = (S) => S.split('~').filter(Boolean).map(b => { const [g, master, dups, rename] = b.split('|'); return { g, master: +master, dups: dups.split(',').map(Number), rename: rename || null }; });
  X.check = (ids) => ({ n: ids.length, sum: ids.reduce((a, b) => a + b, 0), xor: ids.reduce((a, b) => a ^ b, 0) });
  // supplier prices on a multi-variant template with no variant: plan (read only), then apply
  X.siPlan = async () => {
    const SI = await call('product.supplierinfo', 'search_read', [[['product_id', '=', false]]], { fields: ['product_tmpl_id', 'partner_id', 'price'], context: CTX });
    const TV = await call('product.template', 'read', [[...new Set(SI.map(s => s.product_tmpl_id[0]))], ['product_variant_count', 'product_variant_ids']], { context: CTX });
    const multi = Object.fromEntries(TV.filter(t => t.product_variant_count > 1).map(t => [t.id, t.product_variant_ids]));
    const mt = Object.keys(multi).map(Number);
    const L = await call('product.template.attribute.line', 'search_read', [[['product_tmpl_id', 'in', mt]]], { fields: ['product_tmpl_id', 'create_date'], context: CTX });
    const first = {}; for (const l of L) { const t = l.product_tmpl_id[0]; if (!first[t] || l.create_date < first[t]) first[t] = l.create_date; }
    const all = mt.flatMap(t => multi[t]); const POL = [];
    for (let i = 0; i < all.length; i += 400) POL.push(...await call('purchase.order.line', 'search_read', [[['product_id', 'in', all.slice(i, i + 400)]]], { fields: ['product_id', 'partner_id', 'price_unit'], context: CTX }));
    const plan = [], left = [];
    for (const s of SI.filter(s => multi[s.product_tmpl_id[0]])) {
      const t = s.product_tmpl_id[0], vars = multi[t];
      const pl = POL.filter(l => l.partner_id && l.partner_id[0] === s.partner_id[0] && vars.includes(l.product_id[0]));
      const byP = [...new Set(pl.filter(l => Math.abs(l.price_unit - s.price) < 0.005).map(l => l.product_id[0]))], byV = [...new Set(pl.map(l => l.product_id[0]))];
      if (byP.length === 1) plan.push({ si: s.id, v: byP[0], how: 'po-price' });
      else if (byV.length === 1) plan.push({ si: s.id, v: byV[0], how: 'po-vendor' });
      else if (first[t] >= '2026-11-14') plan.push({ si: s.id, v: Math.min(...vars), how: 'original item' });
      else left.push({ si: s.id, t }); }
    return { plan, left }; };
  X.siApply = async (plan) => { for (const p of plan) await call('product.supplierinfo', 'write', [[p.si], { product_id: p.v }], { context: CTX }); X.push({ kind: 'si_variant', n: plan.length }); return plan.length; };
  // network drop: re-run the WHOLE item (only for steps that re-read their state first: convertTemplate, singleTemplate, r5, moveSpec, update)
  X.retryNet = (fn) => async (it) => { for (let k = 0; ; k++) { try { return await fn(it); } catch (e) {
    if (k < 4 && /Failed to fetch|NetworkError|502|503|504/.test(e.message)) { X.push({ kind: 'net-retry', item: (it.tk || it.g || ''), k }); await new Promise(r => setTimeout(r, 4000 * (k + 1))); continue; } throw e; } } };
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
  // ---------- 2026-11-15 round 7 fix: data_merge unions the attribute values of the merged product into the master ----------
  // A value of ANOTHER template on a variant makes its combination invalid, and Odoo archives that variant at the next
  // attribute-line change of its template (14593 on dev_0). Every merge path now strips foreign values right after merging.
  X.cleanPtav = async (pids) => { pids = [...new Set(pids)].filter(Boolean); if (!pids.length) return 0;
    const P = await call('product.product', 'read', [pids, ['product_tmpl_id', 'product_template_attribute_value_ids']], { context: CTX });
    const all = [...new Set(P.flatMap(p => p.product_template_attribute_value_ids))]; if (!all.length) return 0;
    const T = Object.fromEntries((await call('product.template.attribute.value', 'read', [all, ['product_tmpl_id']], { context: CTX })).map(x => [x.id, x.product_tmpl_id[0]]));
    let n = 0; for (const p of P) { const own = p.product_template_attribute_value_ids.filter(i => T[i] === p.product_tmpl_id[0]);
      if (own.length !== p.product_template_attribute_value_ids.length) { await call('product.product', 'write', [[p.id], { product_template_attribute_value_ids: [[6, 0, own]] }], { context: CTX }); n++; } }
    if (n) X.push({ kind: 'ptav-clean', ids: pids, n }); return n; };
  { const ct = X.convertTemplate; X.convertTemplate = async (tp) => { const r = await ct(tp); await X.cleanPtav([tp.master, ...(r.converted || []).map(c => c[1])]); return r; }; }
  { const mi = X.mergeIntoVariant; X.mergeIntoVariant = async (p) => { const r = await mi(p); await X.cleanPtav([p.master]); return r; }; }
  { const mg = X.mergeGroup; X.mergeGroup = async (p) => { const r = await mg(p); if (!r.skipped) await X.cleanPtav([p.master]); return r; }; }
  return 'pc executor ready (production build)';
}
try { localStorage.setItem('pc_execP', '(' + __pcInit.toString() + ')()'); } catch (e) {}
__pcInit();
