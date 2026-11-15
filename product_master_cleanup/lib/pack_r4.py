"""Round 4 production pack: steps 09-11. Usage: python -I lib/pack_r4.py <work_dir>"""
import json, os, re, sys

LIMIT = 30000
B, E = "<!-- r4 begin -->", "<!-- r4 end -->"


def stats(ids):
    x = 0
    for i in ids:
        x ^= i
    return len(ids), sum(ids), x


def put_section(path, body):
    txt = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    txt = re.sub(re.escape(B) + r".*?" + re.escape(E) + r"\n?", "", txt, flags=re.S)
    if txt and not txt.endswith("\n"):
        txt += "\n"
    open(path, "w", encoding="utf-8", newline="\n").write(txt + B + "\n" + body.rstrip("\n") + "\n" + E + "\n")


def main():
    if len(sys.argv) != 2:
        print("usage: python -I lib/pack_r4.py <work_dir>"); return 1
    w = sys.argv[1]
    d = os.path.join(w, "data")
    need = [os.path.join(d, n) for n in ("r4_final_merge.json", "r4_final_variants.json", "r4_renames.json")]
    miss = [p for p in need if not os.path.exists(p)]
    if miss:
        print("REFUSED: missing " + ", ".join(miss)); return 1
    merge, variants, renames = (json.load(open(p, encoding="utf-8")) for p in need)
    pk = os.path.join(w, "prod_pack")
    os.makedirs(pk, exist_ok=True)

    m_rows = ["%s|%s|%s|%s" % (g["g"], g["master"], ",".join(map(str, g["dups"])), g.get("rename") or "") for g in merge]
    m_ids = [x for g in merge for x in [g["master"]] + list(g["dups"])]
    v_rows, v_ids = [], []
    for t in variants:
        items = "~".join("^".join([str(i["var"])] + list(i["vals"])) for i in t["items"])
        v_rows.append("%s|%s|%s|%s|%s" % (t["tk"], t["name"], "^".join(t["attrs"]), t["master"], items))
        v_ids += [i["var"] for i in t["items"]]
    r_rows = ["%s|%s|%s|%s" % (t, v.get("name", ""), v.get("categ_id", "") or "", v.get("x_unit", "") or "") for t, v in renames]
    r_ids = [t for t, _ in renames]

    files = []  # (name, rows, ids, bytes)

    def write(name, text, rows, ids):
        open(os.path.join(pk, name), "w", encoding="utf-8", newline="\n").write(text)
        files.append((name, rows, ids, len(text.encode("utf-8"))))

    write("09_merge_r4.txt", "~".join(m_rows), len(m_rows), m_ids)
    # variants: split on '#' into parts under LIMIT bytes
    parts, cur, cur_ids, size = [], [], [], 0
    for row, t in zip(v_rows, variants):
        ids = [i["var"] for i in t["items"]]
        n = len(row.encode("utf-8")) + 1
        if cur and size + n > LIMIT:
            parts.append((cur, cur_ids)); cur, cur_ids, size = [], [], 0
        cur.append(row); cur_ids += ids; size += n
    if cur:
        parts.append((cur, cur_ids))
    for k, (rows, ids) in enumerate(parts, 1):
        name = "10_variants_r4.txt" if len(parts) == 1 else "10_variants_r4_p%d.txt" % k
        write(name, "#".join(rows), len(rows), ids)
    # renames: parts too
    rparts, cur, cur_ids, size = [], [], [], 0
    for row, t in zip(r_rows, r_ids):
        n = len(row.encode("utf-8")) + 1
        if cur and size + n > LIMIT:
            rparts.append((cur, cur_ids)); cur, cur_ids, size = [], [], 0
        cur.append(row); cur_ids.append(t); size += n
    if cur or not rparts:
        rparts.append((cur, cur_ids))
    for k, (rows, ids) in enumerate(rparts, 1):
        name = "11_renames_r4.txt" if len(rparts) == 1 else "11_renames_r4_p%d.txt" % k
        write(name, "~".join(rows), len(rows), ids)

    lines = ["", "## Steps 09-11 (round 4)", "| file | rows | ids | sum of ids | xor of ids | bytes |", "|--|--|--|--|--|--|"]
    for name, rows, ids, b in files:
        c, s, x = stats(ids)
        lines.append("| %s | %d | %d | %d | %d | %d |" % (name, rows, c, s, x, b))
    lines.append("(09 ids = masters + dups; 10 ids = product ids of all variants; 11 ids = template ids)")
    put_section(os.path.join(pk, "CHECKSUMS.md"), "\n".join(lines))

    vn = [f for f in files if f[0].startswith("10_")]
    rn = [f for f in files if f[0].startswith("11_")]
    readme = ["", "## Steps 09-11 (round 4)",
              "Run after step 08, in this order, one executor batch per file (or part):",
              "9. 09_merge_r4.txt: round 4 merges (%d groups, %d dups). Same format as step 1; X.merge." % (len(merge), sum(len(g["dups"]) for g in merge)),
              "10. %s: round 4 variants (%d templates, %d products). Same format as step 2; X.variants." % (
                  ", ".join(f[0] for f in vn), len(variants), len(v_ids)),
              "11. %s: round 4 template renames (%d). Same format as step 8; X.update." % (
                  ", ".join(f[0] for f in rn), len(renames)),
              "Notes:",
              "- Round 4 creates NEW attributes: Steps, Model, Power, Volume, Weight, Pack, and the new value \"Not Specified\" (used where an item has no value for an attribute of its template).",
              "- Items equal to an existing variant (same attribute values on the same template) are merged into that variant, not created twice.",
              "- Checksums for these files are in CHECKSUMS.md (section Steps 09-11)."]
    put_section(os.path.join(pk, "README.md"), "\n".join(readme))
    print("OK", [(n, r, len(i), b) for n, r, i, b in files])
    return 0


if __name__ == "__main__":
    sys.exit(main())
