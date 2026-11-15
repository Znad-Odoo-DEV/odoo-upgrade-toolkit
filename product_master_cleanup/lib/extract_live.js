// Round 7 live extract - READ ONLY (search_read / formatted_read_group only). No download.
// Paste into the console of a logged-in Odoo 19 tab on /robots.txt (same origin, no page load needed), then:
//   await window.__extract_run();        // builds window.__extract, progress in window.__extract_progress
//   window.__chunk(0)                    // 900-character pieces of JSON.stringify(window.__extract); window.__chunk_count()
// Same structure as data/r7_extract.json: templates, variants, ptav, lines, categories, attributes, attr_values, qty, pol.
// Active records only (default active_test true), as in the dev extract: templates 'active' only, variants of active
// templates. Pause between calls is short, 500 rows per page.
(() => {
  const PAGE = 500, PAUSE = 100, CH = 900;
  const CTX = { active_test: true, lang: 'en_US' };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const prog = window.__extract_progress = { step: 'idle', calls: 0, done: false };
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
  const readAll = async (model, domain, fields) => {
    const out = []; let offset = 0;
    for (;;) {
      prog.step = `${model} @${offset}`;
      const rows = await rpc(model, 'search_read', [], { domain, fields, offset, limit: PAGE, order: 'id', context: CTX });
      out.push(...rows); offset += rows.length;
      if (rows.length < PAGE) return out;
    }
  };
  const group = async (model, domain, groupby, aggregates) => {
    prog.step = `${model} group`;
    return rpc(model, 'formatted_read_group', [], { domain, groupby, aggregates, context: CTX });
  };
  window.__extract_run = async () => {
    prog.done = false; prog.calls = 0;
    const X = {};
    X.templates = await readAll('product.template', [], ['id', 'name', 'x_unit', 'categ_id', 'default_code', 'product_variant_count']);
    X.variants = await readAll('product.product', [], ['id', 'product_tmpl_id', 'default_code', 'product_template_attribute_value_ids']);
    X.ptav = await readAll('product.template.attribute.value', [], ['id', 'attribute_id', 'name', 'product_tmpl_id']);
    X.lines = await readAll('product.template.attribute.line', [], ['id', 'product_tmpl_id', 'attribute_id', 'value_ids']);
    X.categories = await readAll('product.category', [], ['id', 'name', 'complete_name', 'parent_id']);
    X.attributes = await readAll('product.attribute', [], ['id', 'name', 'create_variant', 'display_type']);
    X.attr_values = await readAll('product.attribute.value', [], ['id', 'attribute_id', 'name']);
    X.qty = await group('stock.quant', [['location_id.usage', '=', 'internal']], ['product_id'], ['quantity:sum']);
    X.pol = await group('purchase.order.line', [], ['product_id'], ['__count', 'price_unit:max']);
    window.__extract = X;
    window.__extract_str = JSON.stringify(X);
    prog.step = 'done'; prog.done = true;
    return Object.fromEntries(Object.entries(X).map(([k, v]) => [k, v.length])) && { chunks: Math.ceil(window.__extract_str.length / CH), chars: window.__extract_str.length };
  };
  window.__chunk_count = () => Math.ceil((window.__extract_str || '').length / CH);
  window.__chunk = i => (window.__extract_str || '').slice(i * CH, (i + 1) * CH);
})();
