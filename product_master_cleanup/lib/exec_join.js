  // ---------- join one template into another as variants (paste after the executor + exec_ptav.js + exec_r8_run.js).
  // X.joinTemplate(target, src, extra): every active variant of src becomes a variant of target; extra = values that
  // tell the src variants apart (e.g. {Type: 'Cordless'} or {Pack: 'Box'}). Missing attributes become Not Specified.
  // CLASH GUARD: if a src variant would get the same combination as an existing target variant, nothing is merged and
  // {clash} is returned; check prices/stock by hand and use X.mergeIntoVariant only for real duplicates.
  // Stock, value, codes and history stay on the variant records (no record merge, variants only move template).
  const C0J = { active_test: false, lang: 'en_US' }, NSJ = 'Not Specified';
  const valsOf = async (tid) => { const X = window.__ex;
    const V = await X.call('product.product', 'search_read', [[['product_tmpl_id', '=', tid], ['active', '=', true]]], { fields: ['product_template_attribute_value_ids'], context: C0J });
    const pt = [...new Set(V.flatMap(v => v.product_template_attribute_value_ids))];
    const P = pt.length ? await X.call('product.template.attribute.value', 'read', [pt, ['attribute_id', 'name']], { context: C0J }) : [];
    const N = Object.fromEntries(P.map(p => [p.id, [p.attribute_id[1], p.name]]));
    return V.map(v => ({ id: v.id, a: Object.fromEntries(v.product_template_attribute_value_ids.map(i => N[i])) })); };
  window.__ex.joinTemplate = async (target, src, extra) => { const X = window.__ex;
    const TV = await valsOf(target), SV = await valsOf(src);
    const attrs = [...new Set([...TV.flatMap(v => Object.keys(v.a)), ...SV.flatMap(v => Object.keys(v.a)), ...Object.keys(extra)])];
    const comb = a => attrs.map(k => a[k] || NSJ).join('|');
    const have = new Set(TV.map(v => comb(v.a)));
    const items = [{ var: TV[0].id, vals: attrs.map(k => TV[0].a[k] || NSJ) }], clash = [];
    for (const v of SV) { const a = { ...v.a, ...extra }; if (have.has(comb(a))) { clash.push(v.id); continue; } have.add(comb(a)); items.push({ var: v.id, vals: attrs.map(k => a[k] || NSJ) }); }
    if (clash.length) return { target, src, clash, note: 'same combination as an existing variant - not merged' };
    const tname = (await X.call('product.template', 'read', [[target], ['name']], { context: C0J }))[0].name;
    const tp = { tk: 'T-' + target, name: tname, attrs, master: TV[0].id, items };
    await X.prepValues([tp]); await X.cleanTmplOf(TV[0].id);
    const r = await X.r5(tp); return { target, src, attrs, n: items.length - 1, errs: r.errs, converted: r.converted }; };

  // ---------- pack families: "Item", "Item (Box)", "Item (Roll)" ... become ONE template with a Pack attribute.
  // window.__packPlan(templates, skipIds) -> [{t, name, pack, mem: [[src, extra], ...]}]
  // templates: active non-service product.template rows with name, x_unit, qty_available, product_variant_count.
  // The target is the member with most variants (then most stock); it is renamed to the plain name and gets its own
  // Pack value from its qualifier or its unit text. Qualifiers that are not a pack (Draft, PI, long lists) are left
  // alone; families with an "L.m" unit (BOQ lines priced per metre) are left for the client to decide.
  const UMJ = { box: 'Box', roll: 'Roll', role: 'Roll', pkt: 'Packet', ctn: 'Carton', bundle: 'Bundle', set: 'Set', doz: 'Dozen', pair: 'Pair', kg: 'Per Kg', mtr: 'Per Metre', m: 'Per Metre', lth: 'Length', length: 'Length', nos: 'Each', 'nos.': 'Each', pcs: 'Each', drum: 'Drum', drums: 'Drum', sqm: 'Sqm', bag: 'Bag', lts: 'Litre', can: 'Can', 'mtr 500': 'Roll' };
  const QMJ = { each: 'Each', nos: 'Each', pcs: 'Each', 'per metre': 'Per Metre', metre: 'Per Metre', length: 'Length', 'length unit': 'Length', roll: 'Roll', packet: 'Packet', box: 'Box', carton: 'Carton', bag: 'Bag', bundle: 'Bundle', set: 'Set', drum: 'Drum', dozen: 'Dozen', pair: 'Pair', 'per kg': 'Per Kg', sqm: 'Sqm' };
  const TMJ = { lift: 'Lift', 'lift system': 'Lift', hvac: 'HVAC' };
  window.__packPlan = (T, skipIds) => { const skip = new Set(skipIds || []);
    const base = n => n.replace(/\s*\([^)]*\)\s*$/, '').trim(); const G = {};
    for (const t of T) { const b = base(t.name).toLowerCase(); (G[b] = G[b] || []).push(t); }
    const ext = t => { const m = t.name.match(/\(([^)]*)\)\s*$/); if (m) { const q = m[1].trim().toLowerCase(); if (QMJ[q]) return { Pack: QMJ[q] }; if (TMJ[q]) return { Type: TMJ[q] }; return null; }
      const p = UMJ[(t.x_unit || '').trim().toLowerCase()]; return p ? { Pack: p } : {}; };
    const plan = [];
    for (const a of Object.values(G)) {
      if (a.length < 2 || !a.some(t => /\)\s*$/.test(t.name)) || a.some(t => (t.x_unit || '').trim().toLowerCase() === 'l.m') || a.some(t => skip.has(t.id))) continue;
      const ok = a.map(t => [t, ext(t)]).filter(x => x[1]); const cand = ok.filter(x => !x[1].Type); if (ok.length < 2 || !cand.length) continue;
      cand.sort((x, y) => (y[0].product_variant_count - x[0].product_variant_count) || (y[0].qty_available - x[0].qty_available));
      const [tg, te] = cand[0];
      plan.push({ t: tg.id, name: /\)\s*$/.test(tg.name) ? base(tg.name) : null, pack: te.Pack || null, mem: ok.filter(x => x[0].id !== tg.id).map(([m, e]) => [m.id, e]) }); }
    return plan; };

  // ---------- run a pack plan with N parallel workers (different targets only; values created first, one by one,
  // because parallel creation makes duplicate attribute values). Progress in window.__packRun.
  // LESSON: never wrap X.moveSpec with a lock keyed on the target - joinTemplate calls moveSpec on its own target
  // (via X.r5) and would wait for itself forever.
  window.__runPackPlan = async (plan, workers) => { const X = window.__ex, R = window.__packRun = { phase: 'values', out: [], clash: [] };
    const vals = new Set(); for (const p of plan) { if (p.pack) vals.add('Pack|' + p.pack); for (const [, e] of p.mem) for (const [k, v] of Object.entries(e)) vals.add(k + '|' + v); }
    for (const v of vals) { const [a, b] = v.split('|'); await X.attrValue(a, b); }
    R.phase = 'run'; R.tot0 = await X.companyTotals(); let i = 0;
    const worker = async () => { while (i < plan.length) { const p = plan[i++]; try {
      if (p.pack) { const m = await X.moveSpec({ t: p.t, name: p.name, specs: [['Pack', p.pack]] }); if (m.skipped && p.name) await X.update([p.t, { name: p.name }]); if (m.errs && m.errs.length) { R.out.push([p.t, 'specERR ' + m.errs.join(';')]); continue; } }
      else if (p.name) await X.update([p.t, { name: p.name }]);
      for (const [s, e] of p.mem) { const r = await X.joinTemplate(p.t, s, e); R.out.push([p.t, s, r.clash ? 'CLASH ' + r.clash : (r.errs && r.errs.length ? 'ERR ' + r.errs.join(';') : 'ok ' + r.n)]); if (r.clash) R.clash.push([p.t, s, e]); if (r.errs && r.errs.length) break; }
    } catch (err) { R.out.push([p.t, 'EXC ' + err.message.slice(0, 100)]); } } };
    await Promise.all(Array.from({ length: workers || 4 }, worker)); R.tot1 = await X.companyTotals(); R.phase = 'done'; return R; };
