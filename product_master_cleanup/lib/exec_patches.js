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
