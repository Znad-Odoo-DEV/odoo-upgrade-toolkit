  // ---------- product images (paste after the executor). window.__setImages([[template_id, https_url], ...])
  // Odoo's own base_import downloads each URL on the server (any http/https URL, max 10 MB), so nothing is
  // downloaded on this PC. A template that already has an image is skipped. Every URL is checked by eye on a
  // contact sheet BEFORE upload (wrong item, text overlay, watermark or shop badge = rejected).
  // Some shops block the server download ("Could not retrieve URL"): find another source and retry.
  window.__setImages = async (rows) => { const X = window.__ex, C = { lang: 'en_US' }, out = [];
    const opts = { has_headers: true, separator: ',', quoting: '"', encoding: 'utf-8', import_skip_records: [], import_set_empty_fields: [], fallback_values: {}, name_create_enabled_fields: {}, limit: 2000, skip: 0 };
    for (const [t, url] of rows) {
      const had = await X.call('product.template', 'search_count', [[['id', '=', t], ['image_1920', '!=', false]]], { context: C });
      if (had) { out.push([t, 'skip: already has image']); continue; }
      const csv = '.id,image_1920\n' + t + ',"' + url.replace(/"/g, '""') + '"\n';
      try {
        const imp = await X.call('base_import.import', 'create', [{ res_model: 'product.template', file: csv, file_name: 'img.csv', file_type: 'text/csv' }], { context: C });
        const r = await X.call('base_import.import', 'execute_import', [[imp], ['.id', 'image_1920'], ['.id', 'image_1920'], opts], { dryrun: false, context: C });
        const ok = await X.call('product.template', 'search_count', [[['id', '=', t], ['image_1920', '!=', false]]], { context: C });
        out.push([t, ok ? 'ok' : 'failed: ' + ((r.messages || [])[0] || {}).message]);
      } catch (e) { out.push([t, 'error: ' + e.message.slice(0, 150)]); } }
    X.push({ kind: 'images', n: rows.length, ok: out.filter(o => o[1] === 'ok').length, out });
    return out; };
