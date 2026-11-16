  // ---------- deep duplicate round (2026-11-16, the client said yes to all 106). Paste after executor_prod.js + lib/exec_join.js.
  // window.__ddRun(plan) with plan = data/dd/merge_plan.json: [{n, M, D, simple, mVar, dVars, extra: {tmpl: {attr: val}}, single}]
  // simple (every template one variant, no attributes): X.mergeBuckets -> X.mergeGroupSI (valuation-neutral, checked).
  // otherwise, per dup template D: every D variant whose combination (missing attributes = Not Specified, plus extra[D])
  // equals a variant already in M (or an earlier D variant) is merged into it with X.mergeIntoVariant (checked); the rest of
  // D joins M as new variants with X.joinTemplate (template references moved, D archived, checked). Image copied when M has none.
  (() => { const X = window.__ex, C0 = { active_test: false, lang: 'en_US' }, NS = 'Not Specified';
    if (!X.cleanTmplOf) X.cleanTmplOf = async (pid) => { const t = (await X.call('product.product', 'read', [[pid], ['product_tmpl_id']], { context: C0 }))[0].product_tmpl_id[0];
      return X.cleanPtav(await X.call('product.product', 'search', [[['product_tmpl_id', '=', t]]], { context: C0 })); };
    const vals = async (tid) => {
      const V = await X.call('product.product', 'search_read', [[['product_tmpl_id', '=', tid], ['active', '=', true]]], { fields: ['product_template_attribute_value_ids'], context: C0 });
      const pt = [...new Set(V.flatMap(v => v.product_template_attribute_value_ids))];
      const P = pt.length ? await X.call('product.template.attribute.value', 'read', [pt, ['attribute_id', 'name']], { context: C0 }) : [];
      const N = Object.fromEntries(P.map(p => [p.id, [p.attribute_id[1], p.name]]));
      return V.map(v => ({ id: v.id, a: Object.fromEntries(v.product_template_attribute_value_ids.map(i => N[i])) })); };
    const copyImage = async (M, D) => {
      const m = (await X.call('product.template', 'read', [[M], ['image_128']], { context: C0 }))[0]; if (m.image_128) return false;
      for (const d of D) { const r = (await X.call('product.template', 'read', [[d], ['image_1920']], { context: C0 }))[0];
        if (r.image_1920) { await X.call('product.template', 'write', [[M], { image_1920: r.image_1920 }], { context: C0 }); return d; } }
      return false; };
    X.ddGroup = async (g) => { const out = { n: g.n, M: g.M, steps: [], errs: [] };
      if (g.single) { const v = (await vals(g.M))[0]; const r = await X.singleTemplate({ tk: 'S-dd' + g.n, name: g.single.name, attrs: [g.single.attr], master: v.id, items: [{ var: v.id, vals: [g.single.val] }] });
        out.steps.push(['single', r.skipped || 'ok']); if (r.errs && r.errs.length) { out.errs.push(...r.errs); return out; } }
      for (const D of g.D) { const ex = g.extra[String(D)] || {};
        const TV = await vals(g.M), SV = await vals(D);
        if (!SV.length) { out.steps.push([D, 'no active variant (already merged?)']); continue; }
        const attrs = [...new Set([...TV.flatMap(v => Object.keys(v.a)), ...SV.flatMap(v => Object.keys(v.a)), ...Object.keys(ex)])];
        const comb = a => attrs.map(k => a[k] || NS).join('|');
        const have = {}; for (const v of TV) if (!have[comb(v.a)]) have[comb(v.a)] = v.id;
        let merged = 0;
        for (const v of SV) { const c = comb({ ...v.a, ...ex });
          if (have[c]) { const r = await X.mergeIntoVariant({ g: `dd${g.n}-${v.id}`, master: have[c], dups: [v.id] }); merged++;
            if (r.errs && r.errs.length) { out.errs.push(...r.errs); return out; } }
          else have[c] = v.id; }
        const left = await X.call('product.product', 'search_count', [[['product_tmpl_id', '=', D], ['active', '=', true]]], { context: C0 });
        let joined = 0;
        if (left) { const r = await X.joinTemplate(g.M, D, ex);
          if (r.clash) { out.errs.push(`clash ${D}: ${r.clash}`); return out; }
          if (r.errs && r.errs.length) { out.errs.push(...r.errs); return out; } joined = r.n; }
        const tA = (await X.call('product.template', 'read', [[D], ['active']], { context: C0 }))[0].active;
        if (tA) { const l2 = await X.call('product.product', 'search_count', [[['product_tmpl_id', '=', D], ['active', '=', true]]], { context: C0 });
          if (l2) { out.errs.push(`template ${D} still has ${l2} active variants`); return out; }
          for (const [m, f] of [['product.supplierinfo', 'product_tmpl_id'], ['purchase.order.line', 'x_studio_item'], ['x_purchase_order_line_d9d4d', 'x_studio_item'], ['x_item_listtt', 'x_studio_item_on_item_list'], ['x_employees_payments', 'x_studio_product'], ['ssc.subcontract.item', 'product_id'], ['x_product_template_line_d82d9', 'x_product_template_id'], ['product.pricelist.item', 'product_tmpl_id']]) {
            const rids = await X.call(m, 'search', [[[f, '=', D]]], { context: C0 }); if (rids.length) await X.call(m, 'write', [rids, { [f]: g.M }], { context: C0 }); }
          await X.call('product.template', 'write', [[D], { active: false }], { context: C0 }); }
        out.steps.push([D, { merged, joined }]); }
      out.image = await copyImage(g.M, g.D);
      X.push({ kind: 'dd', ...out }); if (out.errs.length) X.stop = true; return out; };
    window.__ddRun = async (plan, workers = 3) => { const S = window.__ddS = { phase: 'start', done: [], errs: [] }; X.stop = false;
      S.tot0 = await X.companyTotals();
      const simple = plan.filter(g => g.simple), cx = plan.filter(g => !g.simple);
      S.phase = 'simple';
      await X.mergeBuckets('ddSimple', simple.map(g => ({ g: 'dd' + g.n, master: g.mVar, dups: g.dVars })), 4);
      for (const g of simple) S.done.push(g.n);
      if (X.stop) { S.phase = 'stopped in simple'; return S; }
      for (const g of simple) { const im = await copyImage(g.M, g.D); if (im) X.push({ kind: 'dd-image', n: g.n, from: im }); }
      S.phase = 'values';
      for (const g of cx) { for (const t of [g.M, ...g.D]) for (const v of await vals(t)) for (const [a, val] of Object.entries(v.a)) { await X.attrValue(a, val); await X.attrValue(a, NS); }
        for (const ex of Object.values(g.extra)) for (const [a, val] of Object.entries(ex)) { await X.attrValue(a, val); await X.attrValue(a, NS); }
        if (g.single) { await X.attrValue(g.single.attr, g.single.val); await X.attrValue(g.single.attr, NS); } }
      S.phase = 'complex';
      const q = [...cx];
      await Promise.all(Array.from({ length: workers }, async () => { while (q.length && !X.stop) { const g = q.shift();
        try { const r = await X.ddGroup(g); if (r.errs.length) S.errs.push(r); else S.done.push(g.n); }
        catch (e) { S.errs.push({ n: g.n, errs: [String(e.message || e).slice(0, 300)] }); X.stop = true; } } }));
      S.tot1 = await X.companyTotals(); S.phase = X.stop ? 'stopped' : 'done'; return S; };
    return 'dd ready'; })();
