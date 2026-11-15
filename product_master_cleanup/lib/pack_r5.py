"""Rounds 5-6 production pack: steps 12-15. Usage: python -I lib/pack_r5.py <work_dir>"""
import json, os, re, shutil, sys

LIMIT = 30000
B, E = "<!-- r5 begin -->", "<!-- r5 end -->"


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
        print("usage: python -I lib/pack_r5.py <work_dir>"); return 1
    w = sys.argv[1]
    d = os.path.join(w, "data")
    names = ("r5_final_merge.json", "r5_final_variants.json", "r5_final_renames.json", "r6_c_movespec.txt")
    need = [os.path.join(d, n) for n in names]
    miss = [p for p in need if not os.path.exists(p)]
    if miss:
        print("REFUSED: missing " + ", ".join(miss)); return 1
    merge, variants, renames = (json.load(open(p, encoding="utf-8")) for p in need[:3])
    move = open(need[3], encoding="utf-8").read()
    pk = os.path.join(w, "prod_pack")
    os.makedirs(pk, exist_ok=True)
    for f in os.listdir(pk):  # stale parts from an earlier run
        if re.match(r"13_variants_r5(_p\d+)?\.txt$", f):
            os.remove(os.path.join(pk, f))

    files = []

    def write(name, text, rows, ids):
        open(os.path.join(pk, name), "w", encoding="utf-8", newline="\n").write(text)
        files.append((name, rows, ids, len(text.encode("utf-8"))))

    m_rows = ["%s|%s|%s|" % (g["g"], g["master"], ",".join(map(str, g["dups"]))) for g in merge]
    m_ids = [x for g in merge for x in [g["master"]] + list(g["dups"])]
    write("12_merge_r5.txt", "~".join(m_rows), len(m_rows), m_ids)

    v_rows, v_ids = [], []
    for t in variants:
        items = "~".join("^".join([str(i["var"])] + list(i["vals"])) for i in t["items"])
        v_rows.append("%s|%s|%s|%s|%s" % (t["tk"], t["name"], "^".join(t["attrs"]), t["master"], items))
        v_ids.append([i["var"] for i in t["items"]])
    parts, cur, cur_ids, size = [], [], [], 0
    for row, ids in zip(v_rows, v_ids):
        n = len(row.encode("utf-8")) + 1
        if cur and size + n > LIMIT:
            parts.append((cur, cur_ids)); cur, cur_ids, size = [], [], 0
        cur.append(row); cur_ids += ids; size += n
    if cur:
        parts.append((cur, cur_ids))
    vn = []
    for k, (rows, ids) in enumerate(parts, 1):
        name = "13_variants_r5.txt" if len(parts) == 1 else "13_variants_r5_p%d.txt" % k
        vn.append(name)
        write(name, "#".join(rows), len(rows), ids)

    mv = move.rstrip("\n")
    mv_rows = [r for r in mv.split("~") if r]
    write("14_movespec_r6.txt", mv, len(mv_rows), [int(r.split("|", 1)[0]) for r in mv_rows])

    r_rows = ["%s|%s" % (v["var"], v["name"]) for _, v in renames]
    write("15_renames_r5.txt", "~".join(r_rows), len(r_rows), [v["var"] for _, v in renames])

    lines = ["", "## Steps 12-15 (rounds 5-6)", "| file | rows | ids | sum of ids | xor of ids | bytes |", "|--|--|--|--|--|--|"]
    for name, rows, ids, b in files:
        c, s, x = stats(ids)
        lines.append("| %s | %d | %d | %d | %d | %d |" % (name, rows, c, s, x, b))
    lines.append("(12 ids = masters + dups; 13 ids = product ids of all variants; 14 ids = template ids; 15 ids = product ids)")
    put_section(os.path.join(pk, "CHECKSUMS.md"), "\n".join(lines))

    readme = ["", "## Steps 12-15 (rounds 5-6)",
              "Run after step 11, in this order, one executor batch per file (or part):",
              "12. 12_merge_r5.txt: round 5 merges (%d groups, %d dups). Format g|master|dups|, groups joined by '~'. X.mergeBuckets." % (len(merge), sum(len(g["dups"]) for g in merge)),
              "13. %s: round 5 variants (%d templates, %d products). Format tk|name|attr^attr|master|var^v^v~..., templates joined by '#'. X.r5, with X.retryNet after X.prepValues." % (
                  ", ".join(vn), len(variants), sum(len(i) for i in v_ids)),
              "14. 14_movespec_r6.txt: round 6 moves (%d). Format tmpl|new_name|Attr=Value^Attr=Value, joined by '~'. X.moveSpec, only when the new name is not used by another active template." % len(mv_rows),
              "15. 15_renames_r5.txt: round 5 renames (%d). Format product id|new name, joined by '~'. Rename the template of that product." % len(r_rows),
              "Checksums for these files are in CHECKSUMS.md (section Steps 12-15)."]
    put_section(os.path.join(pk, "README.md"), "\n".join(readme))
    print("OK", [(n, r, len(i), sum(i), stats(i)[2], b) for n, r, i, b in files])
    return 0


if __name__ == "__main__":
    sys.exit(main())
