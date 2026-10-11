"""Build mock/worker/data/customers.json from a test-customers file.

    python3 mock/make_customers.py <test-customers.json> [--out mock/worker/data/customers.json] [--id-key id] [--no-faults]

Input: a JSON list of customers (or an object keyed by id, or {"customers": [...]}) shaped like
kit/build-the-builder/public-test-set.json: id, variables, identity, products, optional faults and profile.
Output: an object keyed by customer id, keeping only what the worker reads; products get p1, p2, ... when they
carry no product_id. The key is `customer_id` if present, else --id-key (default `id`). Standard library only.
"""
import argparse, json, sys

KEEP = ("variables", "identity", "products", "faults", "profile")


def entries(doc):
    if isinstance(doc, dict) and isinstance(doc.get("customers"), list): doc = doc["customers"]
    if isinstance(doc, dict): return [{"id": k, **v} for k, v in doc.items() if isinstance(v, dict)]
    return list(doc)


def convert(doc, id_key="id", faults=True):
    out = {}
    for c in entries(doc):
        cid = str(c.get("customer_id") or c.get(id_key) or "").strip()
        if not cid: sys.exit(f"a customer has no {id_key!r}: {json.dumps(c)[:120]}")
        rec = {"id": c.get(id_key, cid), **{k: c[k] for k in KEEP if k in c}}
        if not faults: rec.pop("faults", None)
        rec["products"] = [{"product_id": p.get("product_id", f"p{i + 1}"), **{k: v for k, v in p.items() if k != "product_id"}}
                           for i, p in enumerate(rec.get("products") or [])]
        out[cid] = rec
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("--out", default="mock/worker/data/customers.json")
    ap.add_argument("--id-key", default="id")
    ap.add_argument("--no-faults", action="store_true")
    a = ap.parse_args()
    data = convert(json.load(open(a.src)), a.id_key, not a.no_faults)
    with open(a.out, "w") as f:
        json.dump(data, f, indent=1)
        f.write("\n")
    print(f"{len(data)} customers -> {a.out}: {', '.join(data)}")
