// Phase 1 extract - READ ONLY (search_read / formatted_read_group / fields_get / search_count only).
// Runs in the logged-in <db>.odoo.com tab. Sequential calls, 500 rows per page, short pause between calls.
// Start:  window.__ph1 = runPhase1();   Poll: window.__ph1_progress   Result: downloads ssc_phase1_extract_<ts>.json
(() => {
  const PAGE = 500, PAUSE = 150;
  const CTX = { active_test: false, lang: 'en_US' };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const prog = window.__ph1_progress = { step: 'start', calls: 0, errors: [], done: false, t0: Date.now() };
  const rpc = async (model, method, args = [], kwargs = {}) => {
    prog.calls++;
    const r = await fetch(`/web/dataset/call_kw/${model}/${method}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs } }),
    }).then(r => r.json());
    await sleep(PAUSE);
    if (r.error) throw new Error(`${model}.${method}: ${r.error.data?.message || r.error.message}`);
    return r.result;
  };
  const FG = {};
  const fieldsOf = async model => FG[model] || (FG[model] = await rpc(model, 'fields_get', [], { attributes: ['type', 'store', 'relation', 'string', 'company_dependent'] }));
  const pick = async (model, wanted) => { const f = await fieldsOf(model); return wanted.filter(n => f[n]); };
  const SKIP = /^(message_|activity_|website_|__|access_|avatar_|image_)/;
  const generic = async model => {
    const f = await fieldsOf(model);
    return Object.keys(f).filter(n => f[n].store && !SKIP.test(n) && !['binary', 'one2many', 'html', 'properties', 'properties_definition', 'json'].includes(f[n].type));
  };
  const readAll = async (model, domain, fields, ctx = {}) => {
    const out = []; let offset = 0;
    for (;;) {
      prog.step = `${model} search_read @${offset}`;
      const rows = await rpc(model, 'search_read', [], { domain, fields, offset, limit: PAGE, order: 'id', context: { ...CTX, ...ctx } });
      out.push(...rows); offset += rows.length;
      if (rows.length < PAGE) return out;
    }
  };
  const group = async (model, domain, groupby, aggregates = ['__count'], ctx = {}) => {
    prog.step = `${model} group ${groupby}`;
    return rpc(model, 'formatted_read_group', [], { domain, groupby, aggregates, context: { ...CTX, ...ctx } });
  };
  const safe = async (key, fn, D) => { try { D[key] = await fn(); } catch (e) { prog.errors.push(`${key}: ${e.message}`); D[key] = { error: e.message }; } };

  window.runPhase1 = async () => {
    const D = { meta: { started: new Date().toISOString(), host: location.host } };
    try {
      await safe('companies', () => rpc('res.company', 'search_read', [], { fields: ['id', 'name'], context: CTX }), D);
      const cids = (D.companies || []).map(c => c.id);
      await safe('langs', () => rpc('res.lang', 'search_read', [[['active', '=', true]]], { fields: ['code', 'name'] }), D);

      // 1. Product master
      const tmplF = await pick('product.template', ['id', 'name', 'default_code', 'barcode', 'categ_id', 'uom_id', 'type', 'is_storable',
        'active', 'company_id', 'purchase_ok', 'sale_ok', 'purchase_method', 'description_purchase', 'create_date', 'write_date', 'create_uid',
        'x_unit', 'x_specifications', 'x_item_type', 'x_item_serial_no', 'x_quantifiable', 'x_item_notes', 'x_studio_avg_of_price', 'x_studio_item',
        'product_variant_count', 'tracking', 'list_price']);
      await safe('product_template', () => readAll('product.template', [], tmplF), D);
      const arLang = (D.langs || []).find?.(l => l.code.startsWith('ar'));
      if (arLang) await safe('product_template_name_ar', () => readAll('product.template', [], ['id', 'name'], { lang: arLang.code }), D);
      await safe('product_product', async () => readAll('product.product', [],
        await pick('product.product', ['id', 'product_tmpl_id', 'default_code', 'barcode', 'active', 'display_name', 'combination_indices', 'create_date'])), D);
      D.standard_price = {};
      for (const c of cids) await safe(String(c), () => readAll('product.product', [], ['id', 'standard_price'], { allowed_company_ids: [c] }), D.standard_price);
      await safe('product_category', () => readAll('product.category', [], ['id', 'name', 'complete_name', 'parent_id']), D);
      await safe('uom', () => readAll('uom.uom', [], ['id', 'name', 'active', 'relative_uom_id', 'relative_factor']), D);
      await safe('attributes', async () => readAll('product.attribute', [], await generic('product.attribute')), D);

      // 2. Stock
      await safe('locations', () => readAll('stock.location', [], ['id', 'complete_name', 'usage', 'company_id', 'warehouse_id', 'active']), D);
      await safe('warehouses', () => readAll('stock.warehouse', [], ['id', 'name', 'code', 'company_id', 'lot_stock_id', 'active']), D);
      await safe('quant_by_loc', () => group('stock.quant', [['location_id.usage', '=', 'internal']], ['product_id', 'company_id', 'location_id'], ['__count', 'quantity:sum', 'reserved_quantity:sum']), D);
      await safe('move_stats', () => group('stock.move', [], ['product_id', 'company_id', 'state'], ['__count', 'product_uom_qty:sum', 'date:max', 'date:min']), D);
      await safe('move_line_stats', () => group('stock.move.line', [], ['product_id', 'company_id'], ['__count']), D);
      await safe('product_value', async () => readAll('product.value', [], await generic('product.value')), D);
      await safe('orderpoints', async () => readAll('stock.warehouse.orderpoint', [], await generic('stock.warehouse.orderpoint')), D);

      // 3. Purchase / accounting
      await safe('po_lines', async () => readAll('purchase.order.line', [], await pick('purchase.order.line', ['id', 'order_id', 'product_id', 'x_studio_item',
        'company_id', 'state', 'name', 'product_qty', 'qty_received', 'qty_invoiced', 'price_unit', 'price_subtotal', 'product_uom', 'product_uom_id',
        'date_order', 'date_planned', 'partner_id', 'currency_id', 'display_type'])), D);
      await safe('supplierinfo', async () => readAll('product.supplierinfo', [], await generic('product.supplierinfo')), D);
      await safe('requisition_lines', async () => readAll('purchase.requisition.line', [], await generic('purchase.requisition.line')), D);
      await safe('aml', async () => readAll('account.move.line', [['product_id', '!=', false]], await pick('account.move.line', ['id', 'move_id', 'product_id',
        'company_id', 'parent_state', 'move_type', 'date', 'quantity', 'price_unit', 'balance', 'account_id', 'partner_id', 'purchase_line_id', 'display_type'])), D);
      await safe('analytic_stats', () => group('account.analytic.line', [['product_id', '!=', false]], ['product_id', 'company_id'], ['__count', 'amount:sum', 'unit_amount:sum']), D);
      await safe('sale_lines', async () => readAll('sale.order.line', [['product_id', '!=', false]], ['id', 'order_id', 'product_id', 'company_id', 'state']), D);

      // 4. Custom ssc_* and Studio references
      await safe('mr_lines', async () => readAll('ssc.request.material.line', [], await generic('ssc.request.material.line')), D);
      await safe('subcontract_items', async () => readAll('ssc.subcontract.item', [['product_id', '!=', false]], await generic('ssc.subcontract.item')), D);
      await safe('boq_lines_with_product', () => rpc('ssc.boq.line', 'search_count', [[['product_id', '!=', false]]], { context: CTX }), D);
      await safe('item_list', async () => readAll('x_item_listtt', [], await generic('x_item_listtt')), D);
      await safe('x_pol_d9d4d', async () => readAll('x_purchase_order_line_d9d4d', [['x_studio_item', '!=', false]], await generic('x_purchase_order_line_d9d4d')), D);
      await safe('x_employees_payments', () => group('x_employees_payments', [['x_studio_product', '!=', false]], ['x_studio_product'], ['__count']), D);
      await safe('moves_analysis_by_tmpl', () => group('x_product_template_line_d82d9', [], ['x_product_template_id'], ['__count']), D);
      await safe('moves_analysis_fields', () => fieldsOf('x_product_template_line_d82d9'), D);
      await safe('approval_lines', () => readAll('approval.product.line', [], ['id', 'product_id', 'approval_request_id', 'quantity']), D);
      await safe('project_timesheet_product', () => readAll('project.project', [['timesheet_product_id', '!=', false]], ['id', 'name', 'timesheet_product_id', 'company_id']), D);
      await safe('pricelist_items', () => readAll('product.pricelist.item', [['product_tmpl_id', '!=', false]], ['id', 'pricelist_id', 'product_tmpl_id', 'product_id']), D);
      await safe('appointment_types', () => readAll('appointment.type', [['product_id', '!=', false]], ['id', 'name', 'product_id']), D);
      await safe('routes_with_products', () => readAll('stock.route', [['product_ids', '!=', false]], ['id', 'name', 'product_ids']), D);
      await safe('finder_terms', async () => readAll('ssc.finder.term', [], await generic('ssc.finder.term')), D);

      // 5. Who fills Studio "Moves Analysis" (x_product_template_line_d82d9)
      await safe('who_fills_moves_analysis', async () => {
        const m = await rpc('ir.model', 'search_read', [[['model', '=', 'x_product_template_line_d82d9']]], { fields: ['id', 'name', 'state', 'modules'] });
        const mid = m[0]?.id;
        const code = [['code', 'ilike', 'x_product_template_line_d82d9']];
        return {
          model: m,
          server_actions: await rpc('ir.actions.server', 'search_read', [['|', ['model_id', '=', mid], ...code]], { fields: ['id', 'name', 'state', 'model_id', 'code', 'usage'], context: CTX }),
          crons: await rpc('ir.cron', 'search_read', [['|', ['model_id', '=', mid], ...code]], { fields: ['id', 'name', 'active', 'model_id', 'interval_number', 'interval_type', 'nextcall', 'lastcall'], context: CTX }),
          automations: await rpc('base.automation', 'search_read', [[['model_id', '=', mid]]], { fields: ['id', 'name', 'active', 'trigger'], context: CTX }),
          product_tmpl_field: await rpc('ir.model.fields', 'search_read', [[['model', '=', 'product.template'], ['name', '=', 'x_studio_moves_analysis_1']]], { fields: ['id', 'name', 'ttype', 'relation', 'relation_field', 'compute', 'store'] }),
          created_by_month: await group('x_product_template_line_d82d9', [], ['create_date:month'], ['__count']),
          created_by_user: await group('x_product_template_line_d82d9', [], ['create_uid'], ['__count']),
        };
      }, D);

      // 6. Chatter / attachments on products
      await safe('messages', () => group('mail.message', [['model', 'in', ['product.template', 'product.product']]], ['model', 'res_id'], ['__count']), D);
      await safe('attachments', () => group('ir.attachment', [['res_model', 'in', ['product.template', 'product.product']]], ['res_model', 'res_id'], ['__count']), D);
      await safe('xmlids', () => readAll('ir.model.data', [['model', 'in', ['product.template', 'product.product']]], ['id', 'module', 'name', 'model', 'res_id']), D);
    } catch (e) { prog.errors.push(`fatal: ${e.message}`); }
    D.meta.finished = new Date().toISOString(); D.meta.calls = prog.calls; D.meta.errors = prog.errors;
    const ts = D.meta.finished.replace(/[-:T]/g, '').slice(0, 12);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(D)], { type: 'application/json' }));
    a.download = `ssc_phase1_extract_${ts}.json`; document.body.appendChild(a); a.click(); a.remove();
    prog.step = 'downloaded ' + a.download; prog.done = true; prog.secs = Math.round((Date.now() - prog.t0) / 1000);
    window.__ph1_data = D;
    return prog;
  };
  return 'loaded';
})();
