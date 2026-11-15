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
