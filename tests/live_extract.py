# -*- coding: utf-8 -*-
"""
Live extraction against the real model. Costs money - run deliberately.

    python live_extract.py TS-A
    python live_extract.py all
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from sample_termsheets import pdf, SAMPLES, SECRETS, MUST_KEEP
from server.termsheet import process_termsheet, extraction_status

EXPECTED = {
    "TS-A": dict(currency="KRW", notional=5e10, coupon=2.72,
                 eff="2026-09-15", mat="2031-09-15", dc="Act/365", freq="3M"),
    "TS-B": dict(currency="USD", notional=1e8, coupon=3.65,
                 eff="2026-09-15", mat="2031-09-15", dc="Act/360", freq="12M"),
    "TS-C": dict(currency="KRW_CRS", notional=1e7, coupon=1.08,
                 eff="2026-09-15", mat="2031-09-15", dc="30/360", freq="6M"),
    "TS-D": dict(unsupported=True),
    "TS-E": dict(currency="KRW", notional=2e10, coupon=2.61,
                 eff="2026-09-15", mat="2029-09-15", dc="Act/365", freq="3M"),
}


def check(key):
    desc = SAMPLES[key][0]
    print(f"\n{'='*66}\n  {key}  {desc}\n{'='*66}")
    t0 = time.time()
    try:
        r = process_termsheet(pdf(key))
    except Exception as e:
        print(f"  EXTRACTION FAILED: {type(e).__name__}: {e}")
        return False
    dt = time.time() - t0
    exp = EXPECTED[key]
    ok = True

    if exp.get("unsupported"):
        if r.get("supported"):
            print("  FAIL  unsupported product was accepted"); ok = False
        else:
            print(f"  PASS  refused: {r['unsupported_reason']}")
        print(f"  ({dt:.1f}s)")
        return ok

    if not r.get("supported"):
        print(f"  FAIL  refused a supported product: {r.get('unsupported_reason')}")
        return False

    d = r["ticket_draft"]
    got = {
        "currency": d["product"],
        "notional": float(str(d["notionalDisplay"]).replace(",", "") or 0),
        "coupon": float(d["coupon"]) if d.get("coupon") else None,
        "eff": d.get("effectiveDate"),
        "mat": d.get("maturityDate"),
        "dc": d.get("leg1DayCount"),
        "freq": d.get("leg1PaymentFreq"),
    }
    for field in ("currency", "eff", "mat", "dc", "freq"):
        mark = "PASS" if got[field] == exp[field] else "FAIL"
        if mark == "FAIL":
            ok = False
        print(f"  {mark}  {field:9s} got={got[field]!r:24s} want={exp[field]!r}")
    for field in ("notional", "coupon"):
        g, w = got[field], exp[field]
        good = g is not None and abs(g - w) < max(1.0, abs(w) * 1e-6)
        if not good:
            ok = False
        print(f"  {'PASS' if good else 'FAIL'}  {field:9s} got={g!r:24s} want={w!r}")

    # Redaction must still hold on the live path.
    blob = json.dumps(r, ensure_ascii=False).lower()
    for secret in SECRETS[key]:
        if secret.lower() in blob:
            print(f"  FAIL  identity leaked into the result: {secret!r}"); ok = False

    print(f"  --  inferred={len(r['inferred_fields'])} "
          f"unverified={r['unverified_fields']} "
          f"warnings={len(r['warnings'])} ({dt:.1f}s)")
    for w in r["warnings"]:
        print(f"      warn: {w}")
    for q in r["open_questions"]:
        print(f"      ask : {q}")
    if d.get("rawPasteText"):
        print(f"      schedule periods: {len(d['rawPasteText'].splitlines())}")
    return ok


if __name__ == "__main__":
    st = extraction_status()
    print(f"model={st['model']}  ready={st['ready']}")
    if not st["ready"]:
        print(st.get("reason")); sys.exit(1)

    arg = (sys.argv[1] if len(sys.argv) > 1 else "TS-A").upper()
    keys = list(SAMPLES) if arg == "ALL" else [arg]
    results = {k: check(k) for k in keys}
    print(f"\n{'='*66}")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    sys.exit(0 if all(results.values()) else 1)
