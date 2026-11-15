"""Cost impact of merging product clusters (read-only, local CSVs).
Usage: python -I lib/cost_impact.py <clusters.csv> <out.csv>
clusters.csv: cluster_id,var_id,is_master(1/0). Reads data/products.csv next to lib/.
Policy: new cost = on-hand-qty weighted average of member costs per company;
if total qty <= 0 the master's cost is used (flag MASTER_COST_NO_STOCK).
Flags: NEG_QTY, ZERO_COST_WITH_STOCK, SPREAD_GT_20PCT, MASTER_COST_NO_STOCK, NO_MASTER, UNKNOWN_VAR.
"""
import csv, os, sys
from collections import defaultdict

COMPANIES = {1: "ssc", 2: "mep", 3: "malak", 4: "rwdw"}
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def num(x):
    return 0.0 if x in ("", "False", None) else float(x)


def load_products():
    with open(os.path.join(BASE, "data", "products.csv"), encoding="utf-8-sig", newline="") as f:
        return {r["var_id"]: r for r in csv.DictReader(f)}


def analyse(clusters_path):
    prods = load_products()
    clusters = defaultdict(list)
    with open(clusters_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            clusters[r["cluster_id"]].append((r["var_id"].strip(), str(r["is_master"]).strip() in ("1", "True", "true")))
    out = []
    for cid, members in clusters.items():
        master = next((v for v, m in members if m), None)
        for c, s in COMPANIES.items():
            rows = []
            for v, _m in members:
                p = prods.get(v)
                if p:
                    rows.append((v, num(p["qty_" + s]), num(p["cost_" + s])))
            if not any(q != 0 or k != 0 for _, q, k in rows):
                continue
            flags = []
            if master is None:
                flags.append("NO_MASTER")
            if len(rows) < len(members):
                flags.append("UNKNOWN_VAR")
            total = sum(q for _, q, _ in rows)
            before = sum(q * k for _, q, k in rows)
            mcost = next((k for v, _q, k in rows if v == master), 0.0)
            if total > 0:
                new = before / total
            else:
                new = mcost
                flags.append("MASTER_COST_NO_STOCK")
            if any(q < 0 for _, q, _ in rows):
                flags.append("NEG_QTY")
            if any(q > 0 and k == 0 for _, q, k in rows):
                flags.append("ZERO_COST_WITH_STOCK")
            costs = [k for _, q, k in rows if q > 0]
            if costs and min(costs) > 0 and (max(costs) - min(costs)) / min(costs) > 0.20:
                flags.append("SPREAD_GT_20PCT")
            elif costs and min(costs) == 0 and max(costs) > 0:
                flags.append("SPREAD_GT_20PCT")
            after = total * new
            out.append({
                "cluster_id": cid, "company": s, "master": master or "",
                "member_qty": ";".join("%s:%g" % (v, q) for v, q, _ in rows),
                "member_cost": ";".join("%s:%g" % (v, k) for v, _, k in rows),
                "total_qty": round(total, 4), "master_cost": round(mcost, 4),
                "new_cost_wavg": round(new, 4), "value_before": round(before, 2),
                "value_after": round(after, 2), "delta": round(after - before, 2),
                "flags": "|".join(flags),
            })
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    rows = analyse(sys.argv[1])
    cols = ["cluster_id", "company", "master", "member_qty", "member_cost", "total_qty", "master_cost",
            "new_cost_wavg", "value_before", "value_after", "delta", "flags"]
    with open(sys.argv[2], "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(rows)
    print("rows", len(rows), "total delta", round(sum(r["delta"] for r in rows), 2))


if __name__ == "__main__":
    main()
