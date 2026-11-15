"""Build executor_prod.js = executor_r2.js + every fix of 2026-11-15 (lib/exec_patches.js). Usage: python -I lib/build_exec_prod.py <work_dir>"""
import sys
from pathlib import Path

W = Path(sys.argv[1])
s = (W / 'executor_r2.js').read_text(encoding='utf-8')
s = s.replace("// Round-2 executor (dev_0 first).", "// PRODUCTION executor (all rounds, fixes of 2026-11-15 included). Log key pc_logP.\n// Round-2 executor base.")
s = s.replace("'pc_log2'", "'pc_logP'").replace("localStorage.setItem('pc_exec'", "localStorage.setItem('pc_execP'")
a, b = s.index("  X.attr = async (name) => {"), s.index("  X.attrValue = async")
s = s[:a] + (W / 'lib/exec_attr.js').read_text(encoding='utf-8') + s[b:]
s = s.replace("  return 'pc executor ready';", (W / 'lib/exec_patches.js').read_text(encoding='utf-8') + "  return 'pc executor ready (production build)';")
(W / 'executor_prod.js').write_text(s, encoding='utf-8', newline='\n')
print('executor_prod.js', len(s))
