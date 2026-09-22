"""Do the shell tools parse, and does each one define every name it uses?

    python tools/check_tools.py            checks tools/*.py
    python tools/check_tools.py path.py    checks the ones named

Runs on plain Python. It does not need Odoo, a database or a shell, which is
the point: it is meant to be run before pushing, in a second, on a laptop.

Why. A tool in this folder is fed to `odoo-bin shell` on a database with real
data on it. A missing import or a helper that was written in one tool and used
in another does not fail until it is run there - halfway through, after the
useful half of the report has already scrolled past, on a machine that is not
this one. That happened: orphan_reasons called column_exists, which existed in
the dossier tool and not in the migration one, and it was found by a person
waiting on a staging shell rather than by a check taking a second.

What it knows about the shell: env, odoo and self are handed in by odoo-bin and
are not defined by the script. And a script may reach for __file__, which is
absent when the code is exec'd from stdin - that is only reported when the
script does not guard it with `'__file__' in dir()`, because guarding it is the
correct thing to do and not a finding.
"""
import ast
import builtins
import glob
import io
import sys

# names odoo-bin shell puts into the namespace before the script runs
SHELL_NAMES = {'env', 'odoo', 'openerp', 'self'}


def defined_names(tree):
    """Every name this module binds, anywhere - including lambda arguments,
    comprehension targets, except-as names and imports."""
    names = set(dir(builtins)) | SHELL_NAMES
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split('.')[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Global):
            names.update(node.names)
    return names


def check(path):
    """A list of complaints about one file, empty when it is fine."""
    source = io.open(path, encoding='utf-8').read()
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return ["does not parse: line %s, %s" % (error.lineno, error.msg)]

    used = {node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    unknown = used - defined_names(tree)

    # reaching for __file__ is fine as long as the script checks for it first
    if '__file__' in unknown and "'__file__' in dir()" in source:
        unknown.discard('__file__')

    if unknown:
        return ["uses but never defines: %s" % ", ".join(sorted(unknown))]
    return unpacking_complaints(tree)


def unpacking_complaints(tree):
    """`for a, b in ROWS` where a row in ROWS holds three things.

    A table of constants at the top and a loop that walks it is the shape most
    of these tools are, and the two get edited months apart. Add something to
    the rows, forget the loop, and Python says nothing until it reaches the
    first one - which on a tool like this is after eight seconds of registry
    loading, on a staging shell, in front of somebody waiting.

    That is exactly how it went: check_report_fields.py carried the model name
    as a third value in each row, the loop unpacked two, and it was a person
    running it who found out rather than this file. Only tuple literals in a
    module level list are looked at, because that is the case that bites and
    the only one that can be known without running anything.
    """
    tables = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        rows = node.value.elts
        if not rows or any(not isinstance(row, (ast.Tuple, ast.List))
                           for row in rows):
            continue
        tables[target.id] = {len(row.elts) for row in rows}

    found = []

    def complain(lineno, wanted, table_name, widths):
        wrong = sorted(w for w in widths if w != wanted)
        if wrong:
            found.append(
                "line %s unpacks %s name(s) from %s, whose rows hold %s"
                % (lineno, wanted, table_name,
                   " and ".join(str(w) for w in wrong)))

    # the table walked where it stands
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.iter, ast.Name):
            continue
        widths = tables.get(node.iter.id)
        if widths and isinstance(node.target, (ast.Tuple, ast.List)):
            complain(node.lineno, len(node.target.elts), node.iter.id, widths)

    # and the table handed to a function that walks it, which is the case that
    # actually happened - the loop was three lines from the table's name, in
    # another function, and neither half looked wrong on its own
    walkers = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        parameters = [a.arg for a in node.args.args]
        for inner in ast.walk(node):
            if (isinstance(inner, ast.For)
                    and isinstance(inner.iter, ast.Name)
                    and inner.iter.id in parameters
                    and isinstance(inner.target, (ast.Tuple, ast.List))):
                walkers[node.name] = (inner.iter.id, parameters,
                                      len(inner.target.elts), inner.lineno)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        walked = walkers.get(node.func.id)
        if not walked:
            continue
        parameter, parameters, wanted, lineno = walked
        given = None
        for keyword in node.keywords:
            if keyword.arg == parameter:
                given = keyword.value
        if given is None and parameter in parameters:
            position = parameters.index(parameter)
            if position < len(node.args):
                given = node.args[position]
        if isinstance(given, ast.Name) and given.id in tables:
            complain(node.lineno, wanted, given.id, tables[given.id])
    return found


paths = sys.argv[1:] or sorted(glob.glob('tools/*.py'))
complaints = 0
for path in paths:
    for complaint in check(path):
        print("%-46s %s" % (path, complaint))
        complaints += 1

print()
print("%s tool(s) checked, %s complaint(s)" % (len(paths), complaints))
sys.exit(1 if complaints else 0)
