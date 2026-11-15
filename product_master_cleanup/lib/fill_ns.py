"""Build the storekeeper sheet of items whose attribute value is "Not Specified".

Usage: python -I lib/fill_ns.py <work_dir>
Reads data/r4_final_variants.json (else data/r4_variants.json) and data/r4_extract.json,
writes reports/Fill_Not_Specified.xlsx. Read-only on Odoo: no network, no Odoo calls.
"""
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

NOT_SPECIFIED = "Not Specified"
HEADERS = [
    "Template", "Item", "Internal ref", "Attribute", "Value now",
    "Other values used in this template", "Correct value", "Comment",
]
README_LINES = [
    "These items were put under their family with \"Not Specified\" where the item name does not say the value.",
    "For each row, write the right value in the \"Correct value\" column.",
    "Nothing is guessed: if you do not know the value, leave the cell empty.",
    "هذه الأصناف وُضعت تحت عائلتها بقيمة \"Not Specified\" حيث لا يذكر اسم الصنف القيمة.",
    "لكل سطر، اكتب القيمة الصحيحة في عمود \"Correct value\".",
    "لا يتم تخمين أي شيء: إذا لم تعرف القيمة، اترك الخلية فارغة.",
]


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def variant_index(extract):
    """Map variant id -> (product name, internal ref) from the extract."""
    index = {}
    for v in extract.get("variants", []):
        tmpl = v.get("product_tmpl_id")
        tmpl_name = tmpl[1] if isinstance(tmpl, list) and len(tmpl) > 1 else ""
        name = v.get("display_name") or tmpl_name
        ref = v.get("default_code") or ""
        index[v["id"]] = (name, ref)
    return index


def build_rows(templates, index):
    rows = []
    missing = 0
    for tpl in templates:
        attrs = tpl.get("attrs", [])
        items = tpl.get("items", [])
        for pos, attr in enumerate(attrs):
            # Values of this attribute used by the other items of the template,
            # without the placeholder itself, in order of first appearance.
            others = []
            for it in items:
                val = it["vals"][pos] if pos < len(it["vals"]) else ""
                if val and val != NOT_SPECIFIED and val not in others:
                    others.append(val)
            for it in items:
                vals = it["vals"]
                if pos >= len(vals) or vals[pos] != NOT_SPECIFIED:
                    continue
                if it["var"] in index:
                    item_name, ref = index[it["var"]]
                else:
                    item_name, ref = "", ""
                    missing += 1
                rows.append([
                    tpl.get("name", ""),
                    item_name,
                    ref,
                    attr,
                    NOT_SPECIFIED,
                    ", ".join(others),
                    "",
                    "",
                ])
    rows.sort(key=lambda r: (r[0].lower(), r[1].lower(), r[3].lower()))
    return rows, missing


def write_workbook(rows, out_path):
    wb = Workbook()
    readme = wb.active
    readme.title = "README"
    for line_no, text in enumerate(README_LINES, start=1):
        cell = readme.cell(row=line_no, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    readme.column_dimensions["A"].width = 110

    sheet = wb.create_sheet("To_Fill")
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row in rows:
        sheet.append(row)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    widths = [34, 46, 16, 22, 16, 36, 22, 30]
    for col, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(ord("A") + col - 1)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:H{max(sheet.max_row, 1)}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def main():
    work = Path(sys.argv[1])
    final = work / "data" / "r4_final_variants.json"
    source = final if final.exists() else work / "data" / "r4_variants.json"
    templates = load_json(source)
    extract = load_json(work / "data" / "r4_extract.json")
    index = variant_index(extract)
    rows, missing = build_rows(templates, index)
    out_path = work / "reports" / "Fill_Not_Specified.xlsx"
    write_workbook(rows, out_path)
    print(f"source: {source.name}")
    print(f"rows: {len(rows)}")
    print(f"items not found in extract: {missing}")
    print(f"written: {out_path}")


if __name__ == "__main__":
    main()
