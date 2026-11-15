"""Build executor_prod.js = executor_r2.js + every fix of 2026-11-15 (lib/exec_*.js). Usage: python -I lib/build_exec_prod.py <work_dir>"""
import sys
from pathlib import Path

W = Path(sys.argv[1])
rd = lambda n: (W / 'lib' / n).read_text(encoding='utf-8')
s = (W / 'executor_r2.js').read_text(encoding='utf-8')
s = s.replace("// Round-2 executor (dev_0 first).", "// PRODUCTION executor (all rounds, fixes of 2026-11-15 included). Log key pc_logP.\n// Round-2 executor base.")
s = s.replace("'pc_log2'", "'pc_logP'").replace("localStorage.setItem('pc_exec'", "localStorage.setItem('pc_execP'")
a, b = s.index("  X.attr = async (name) => {"), s.index("  X.attrValue = async")
s = s[:a] + rd('exec_attr.js') + s[b:]
# supplier prices of a moved template: a template-level price gets a variant only when that template had one variant
OLD_SI = ("    for (const d of all) { const si = await call('product.supplierinfo', 'search', [[['product_tmpl_id', '=', d.oT]]], { context: CTX }); "
          "if (si.length) await call('product.supplierinfo', 'write', [si, { product_tmpl_id: mT, product_id: d.nv }], { context: CTX }); }")
assert OLD_SI in s, 'supplierinfo line not found'
s = s.replace(OLD_SI + '\n', rd('exec_si_fix.js'))
s = s.replace("  return 'pc executor ready';", rd('exec_patches.js') + rd('exec_r7.js') + "  return 'pc executor ready (production build)';")
(W / 'executor_prod.js').write_text(s, encoding='utf-8', newline='\n')
print('executor_prod.js', len(s))
