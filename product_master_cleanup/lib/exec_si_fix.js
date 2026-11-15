    { const byT = {}; for (const d of all) (byT[d.oT] = byT[d.oT] || []).push(d);
      for (const oT of Object.keys(byT)) { const si = await call('product.supplierinfo', 'search_read', [[['product_tmpl_id', '=', +oT]]], { fields: ['product_id'], context: CTX });
        for (const s of si) { const v = { product_tmpl_id: mT }; if (!s.product_id && byT[oT].length === 1) v.product_id = byT[oT][0].nv; await call('product.supplierinfo', 'write', [[s.id], v], { context: CTX }); } } }
