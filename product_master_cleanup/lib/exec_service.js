  // ---------- round 8: Product Type -> Service (the client 2026-11-15) ----------
  // Odoo refuses the change for a product with done or reserved stock move lines; a product with stock on hand is never
  // changed (its stock and valuation would be orphaned). Those are logged as svc-blocked for a human look.
  X.setService = async (t) => {
    const C0 = { active_test: false, lang: 'en_US' };
    const tp = (await X.call('product.template', 'read', [[t], ['type', 'is_storable', 'active', 'product_variant_ids', 'name']], { context: C0 }))[0];
    if (!tp || !tp.active) { X.push({ kind: 'svc', t, skipped: 'archived or missing' }); return { errs: [] }; }
    if (tp.type === 'service') { X.push({ kind: 'svc', t, skipped: 'already service' }); return { errs: [] }; }
    const v = tp.product_variant_ids, why = [];
    const done = await X.call('stock.move.line', 'search_count', [[['product_id', 'in', v], ['state', '=', 'done']]], { context: C0 });
    const resv = await X.call('stock.move.line', 'search_count', [[['product_id', 'in', v], ['state', 'in', ['partially_available', 'assigned']]]], { context: C0 });
    const q = await X.call('stock.quant', 'search_count', [[['product_id', 'in', v], ['quantity', '!=', 0]]], { context: C0 });
    if (done) why.push(`${done} done stock moves`); if (resv) why.push(`${resv} reserved`); if (q) why.push(`${q} quants`);
    if (why.length) { X.push({ kind: 'svc-blocked', t, name: tp.name, why }); return { errs: [] }; }
    await X.call('product.template', 'write', [[t], { type: 'service', is_storable: false }], { context: { lang: 'en_US', tracking_disable: true } });
    const a = (await X.call('product.template', 'read', [[t], ['type', 'purchase_method']], { context: C0 }))[0];
    const errs = a.type === 'service' ? [] : ['type not set'];
    X.push({ kind: 'svc', t, name: tp.name, from: tp.type + (tp.is_storable ? '/storable' : ''), purchase_method: a.purchase_method, errs }); if (errs.length) X.stop = true; return { errs }; };
