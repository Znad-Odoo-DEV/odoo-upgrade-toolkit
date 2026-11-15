  // ---------- round 8 run (paste after the executor; plan strings in window.__r8moves/__r8cats/__r8ren/__r8merges/__r8joins,
  // fingerprints in window.__r8hi/__r8lo, extra categories in window.__r7missed). window.__r8run(devMode):
  // devMode=true maps ids by fingerprint and skips what is absent (staging); false refuses unless every id maps (production).
  // Order: moves -> variant merges -> joins (bucketed by shared template; each join cleans foreign values first) -> renames
  // -> categories. LESSON: a join that gives an existing variant a new distinguishing value must run BEFORE any join that
  // adds an item with the variant's OLD combination, or convertTemplate reuses (merges into) that variant.
  const fnv = s => { let h = 0x811c9dc5; for (const b of new TextEncoder().encode(s)) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; } return h; };
  window.__r8run = async (devMode) => { const X = window.__ex, S = window.__r8st = { phase: 'resolve' }, C0 = { active_test: false, lang: 'en_US' }, h36 = s => fnv(s).toString(36);
    X.stop = false;
    try {
      if (!X.cleanTmplOf) X.cleanTmplOf = async (pid) => { const t = (await X.call('product.product', 'read', [[pid], ['product_tmpl_id']], { context: C0 }))[0].product_tmpl_id[0]; return X.cleanPtav(await X.call('product.product', 'search', [[['product_tmpl_id', '=', t]]], { context: C0 })); };
      const lo = window.__r8lo.split('~').map(x => x.split('|').map(Number)), hi = window.__r8hi.split('~').map(x => { const [i, code, t, h] = x.split('|'); return { id: +i, code, t: +t, h }; });
      const map = {}, skip = [];
      const L = await X.call('product.product', 'read', [lo.map(r => r[0]), ['active', 'product_tmpl_id']], { context: C0 }); const LB = Object.fromEntries(L.map(r => [r.id, r]));
      for (const [i, t] of lo) { const r = LB[i]; if (r && r.active && r.product_tmpl_id[0] === t) map[i] = i; else skip.push(['lo', i, r ? r.product_tmpl_id[0] : null, r ? r.active : null]); }
      const P = await X.call('product.product', 'search_read', [[['product_tmpl_id', 'in', [...new Set(hi.map(h => h.t))]], ['active', '=', true]]], { fields: ['default_code', 'product_tmpl_id', 'product_template_attribute_value_ids'], context: C0 });
      const pt = [...new Set(P.flatMap(p => p.product_template_attribute_value_ids))], PT = {}; if (pt.length) for (const x of await X.call('product.template.attribute.value', 'read', [pt, ['attribute_id', 'name']], { context: C0 })) PT[x.id] = x.attribute_id[1] + ':' + x.name;
      for (const h of hi) { const c = P.filter(p => p.product_tmpl_id[0] === h.t && (p.default_code || '') === h.code && h36(p.product_template_attribute_value_ids.map(i => PT[i]).sort().join('+')) === h.h); if (c.length === 1) map[h.id] = c[0].id; else skip.push(['hi', h.id, c.length]); }
      S.skip = skip; S.mapped = Object.keys(map).length; S.diff = Object.entries(map).filter(([a, b]) => +a !== b).length;
      if (!devMode && skip.length) throw new Error('production: ids not found ' + JSON.stringify(skip).slice(0, 300));
      const J = []; for (const t of X.parseVariants(window.__r8joins)) { if (!map[t.master]) { S.dropJ = (S.dropJ || []).concat(t.tk); continue; } const items = t.items.filter(i => map[i.var]).map(i => ({ var: map[i.var], vals: i.vals })); if (items.length < t.items.length) S.dropJ = (S.dropJ || []).concat(t.tk + ':few'); if (!items.length) continue; J.push({ ...t, master: map[t.master], items }); }
      const G = X.parseMerges(window.__r8merges).filter(g => map[g.master] && g.dups.every(d => map[d])).map(g => ({ ...g, master: map[g.master], dups: g.dups.map(d => map[d]) }));
      const M0 = window.__r8moves.split('~').map(b => { const [t, name, sp] = b.split('|'); return { t: +t, name: name || null, specs: sp ? sp.split('^').map(x => { const i = x.indexOf('='); return [x.slice(0, i), x.slice(i + 1)]; }) : [] }; });
      const TA = Object.fromEntries((await X.call('product.template', 'read', [M0.map(m => m.t), ['active']], { context: C0 })).map(t => [t.id, t.active]));
      const M = M0.filter(m => TA[m.t]); S.dropM = M0.filter(m => !TA[m.t]).map(m => m.t);
      if (!devMode && (S.dropM.length || (S.dropJ || []).length)) throw new Error('production: plan not complete ' + S.dropM + ' ' + S.dropJ);
      const R = window.__r8ren.split('~').map(b => { const [t, n] = b.split('|'); return [+t, { name: n }]; });
      const CT = [...window.__r8cats.split('~'), ...(window.__r7missed || '').split('~').filter(Boolean)].map(b => { const i = b.indexOf('|'); return [+b.slice(0, i), b.slice(i + 1)]; });
      S.tot0 = await X.companyTotals();
      S.phase = 'prep'; for (const m of M) for (const [a, v] of m.specs) await X.attrValue(a, v); await X.prepValues(J);
      S.phase = 'moves'; S.m = await X.run('m8', M, X.retryNet(X.moveSpec), 6); if (X.stop) throw new Error('stopped in moves');
      const mskip = X.log.filter(r => r.kind === 'movespec' && r.skipped && M.some(m => m.t === r.t && m.name)).map(r => r.t); S.mskip = mskip;
      for (const t of mskip) { const m = M.find(x => x.t === t); await X.update([t, { name: m.name }]); }
      S.phase = 'merges'; for (const g of G) { const r = await X.mergeIntoVariant(g); if (r.errs && r.errs.length) throw new Error('merge ' + g.g + ' ' + r.errs.join(';')); } S.merges = G.length;
      const ids = [...new Set(J.flatMap(t => [t.master, ...t.items.map(i => i.var)]))];
      const tm = Object.fromEntries((await X.call('product.product', 'read', [ids, ['product_tmpl_id']], { context: C0 })).map(r => [r.id, r.product_tmpl_id[0]]));
      const par = {}; const f = x => par[x] === undefined || par[x] === x ? (par[x] = x) : (par[x] = f(par[x]));
      J.forEach((t, k) => { [t.master, ...t.items.map(i => i.var)].map(v => 'T' + tm[v]).forEach(x => { par[f(x)] = f('J' + k); }); });
      const B = {}; J.forEach((t, k) => (B[f('J' + k)] = B[f('J' + k)] || []).push(t));
      S.phase = 'joins'; const jf = X.retryNet(async (t) => { await X.cleanTmplOf(t.master); return X.r5(t); });
      S.j = await X.run('j8', Object.values(B), async (b) => { let errs = []; for (const t of b) { if (X.stop) break; const r = await jf(t); if (r && r.errs && r.errs.length) { errs = r.errs; X.stop = true; break; } } return { errs }; }, 6);
      if (X.stop) throw new Error('stopped in joins');
      S.phase = 'renames'; await X.run('r8', R, X.update, 2);
      S.phase = 'cats'; S.c = await X.run('c8', CT, X.setCategory, 1); if (X.stop) throw new Error('stopped in categories');
      S.tot1 = await X.companyTotals(); S.phase = 'done';
    } catch (e) { S.error = e.message.slice(0, 400); S.phase += ' FAILED'; } };
