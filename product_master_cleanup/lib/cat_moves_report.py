"""Build the category-moves workbook for the accountant.

Reads data/main_final/main_run_log.json (kind 'cat' and 'category created')
and data/main_final/main_final_extract.json (templates, variants, qty).
Writes reports/Category_Moves_For_Accountant.xlsx with three sheets:
Moves, New sub-categories, Summary.

Run: python -I lib/cat_moves_report.py
"""
import json
import os
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(ROOT, "data", "main_final", "main_run_log.json")
EXTRACT_PATH = os.path.join(ROOT, "data", "main_final", "main_final_extract.json")
OUT_PATH = os.path.join(ROOT, "reports", "Category_Moves_For_Accountant.xlsx")

SSC_ID = 1
MEP_ID = 2

EXPECTED_MOVES = 217
EXPECTED_ACCOUNT_CHANGED = 142
EXPECTED_NEW_CATEGORIES = 23


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def m2o_id(value):
    """Many2one values come as [id, name] or False."""
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return None


def stock_by_template(extract):
    """Sum quantity:sum of every variant under each template."""
    tmpl_of_variant = {}
    for var in extract["variants"]:
        tmpl_id = m2o_id(var.get("product_tmpl_id"))
        if tmpl_id is not None:
            tmpl_of_variant[var["id"]] = tmpl_id

    qty_by_variant = defaultdict(float)
    for row in extract["qty"]:
        variant_id = m2o_id(row.get("product_id"))
        qty = row.get("quantity:sum") or 0
        qty_by_variant[variant_id] += qty

    qty_by_tmpl = defaultdict(float)
    for variant_id, qty in qty_by_variant.items():
        tmpl_id = tmpl_of_variant.get(variant_id)
        if tmpl_id is not None:
            qty_by_tmpl[tmpl_id] += qty
    return qty_by_tmpl


def build_rows(log, extract):
    templates = {t["id"]: t for t in extract["templates"]}
    qty_by_tmpl = stock_by_template(extract)

    moves = []
    for rec in log:
        if rec.get("kind") != "cat":
            continue
        tmpl_id = rec["t"]
        tmpl = templates.get(tmpl_id)
        if tmpl is None:
            raise SystemExit(f"Template {tmpl_id} is in the log but not in the extract")
        changed = set(rec.get("expenseAccountChanged") or [])
        moves.append({
            "template_id": tmpl_id,
            "name": tmpl.get("name") or "",
            "internal_ref": tmpl.get("default_code") or "",
            "from": rec.get("from") or "",
            "to": rec.get("to") or "",
            "ssc": SSC_ID in changed,
            "mep": MEP_ID in changed,
            "stock": qty_by_tmpl.get(tmpl_id, 0),
        })

    # Rows with any expense account change first; then by template id.
    moves.sort(key=lambda m: (not (m["ssc"] or m["mep"]), m["template_id"]))

    new_cats = [
        {"path": rec["path"], "id": rec["id"], "parent": rec.get("parent")}
        for rec in log if rec.get("kind") == "category created"
    ]
    new_cats.sort(key=lambda c: c["id"])
    return moves, new_cats


def yes_no(flag):
    return "Yes" if flag else "No"


def write_workbook(moves, new_cats, summary):
    wb = Workbook()
    bold = Font(bold=True)

    def write_sheet(ws, headers, rows, widths):
        ws.append(headers)
        for cell in ws[1]:
            cell.font = bold
        for row in rows:
            ws.append(row)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for idx, width in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = width

    ws_moves = wb.active
    ws_moves.title = "Moves"
    write_sheet(
        ws_moves,
        ["Template ID", "Template name", "Internal ref", "From category",
         "To category", "Expense account changed for SSC",
         "Expense account changed for MEP", "Stock qty now"],
        [
            [m["template_id"], m["name"], m["internal_ref"], m["from"], m["to"],
             yes_no(m["ssc"]), yes_no(m["mep"]), m["stock"]]
            for m in moves
        ],
        [12, 40, 18, 32, 44, 18, 18, 14],
    )

    ws_new = wb.create_sheet("New sub-categories")
    write_sheet(
        ws_new,
        ["Path", "ID", "Parent ID"],
        [[c["path"], c["id"], c["parent"]] for c in new_cats],
        [60, 10, 12],
    )

    ws_sum = wb.create_sheet("Summary")
    write_sheet(
        ws_sum,
        ["Item", "Value"],
        summary,
        [45, 14],
    )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    wb.save(OUT_PATH)


def main():
    log = load_json(LOG_PATH)
    extract = load_json(EXTRACT_PATH)
    moves, new_cats = build_rows(log, extract)

    total = len(moves)
    changed = sum(1 for m in moves if m["ssc"] or m["mep"])
    ssc = sum(1 for m in moves if m["ssc"])
    mep = sum(1 for m in moves if m["mep"])
    summary = [
        ["Total moves", total],
        ["Moves changing the expense account (any company)", changed],
        ["Moves changing the expense account for SSC", ssc],
        ["Moves changing the expense account for MEP", mep],
        ["Moves with no expense account change", total - changed],
        ["New sub-categories", len(new_cats)],
    ]

    checks = [
        (total, EXPECTED_MOVES, "total moves"),
        (changed, EXPECTED_ACCOUNT_CHANGED, "moves changing the expense account"),
        (len(new_cats), EXPECTED_NEW_CATEGORIES, "new sub-categories"),
    ]
    for got, expected, label in checks:
        if got != expected:
            raise SystemExit(f"Check failed for {label}: got {got}, expected {expected}")

    write_workbook(moves, new_cats, summary)
    for label, value in summary:
        print(f"{label}: {value}")
    print(f"Written: {OUT_PATH}")


if __name__ == "__main__":
    main()
