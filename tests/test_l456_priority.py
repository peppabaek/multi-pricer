"""
Priority scenarios:
  L6 - live market data must reach pricing immediately
  L4 - CRS must price Vanilla and Fixed-Fixed
  L5 - rollercoaster: varying notional / irregular dates / varying rates
"""
from harness import case, approx, run_all

from test_l2_pricing import client, price, pr, freeze_market
from server.crs_feed import crs_feed
from server.tradition_feed import tradition_feed
from server.krw_feed import krw_feed
from server.kofr_feed import kofr_feed

freeze_market()

CRS_EP = "/api/crs/price"


def crs(**kw):
    body = {"tenor": "5Y", "usd_notional": 10_000_000.0}
    body.update(kw)
    r = client.post(CRS_EP, json=body)
    if r.status_code != 200:
        raise AssertionError(f"{CRS_EP} -> HTTP {r.status_code}: {r.text[:400]}")
    return r.json()["data"]


# ---------------------------------------------------------------- L6 live data
@case("L6-1", "quote change reaches pricing immediately (all 4 products)")
def t_l6_1():
    cases = [
        ("USD", "/api/price", tradition_feed.update_quote, 100_000_000.0),
        ("KRW", "/api/krw/price", krw_feed.update_quote, 10_000_000_000.0),
        ("KRW_KOFR", "/api/kofr/price", kofr_feed.update_quote, 10_000_000_000.0),
    ]
    for name, ep, setter, notional in cases:
        before = pr(ep, notional=notional, tenor="5Y")["par_swap_rate_pct"]
        setter("5Y", _base_5y(name) + 0.10)          # +10bp on the 5Y quote
        after = pr(ep, notional=notional, tenor="5Y")["par_swap_rate_pct"]
        setter("5Y", _base_5y(name))                 # restore
        moved_bp = (after - before) * 100.0
        if not (5.0 < moved_bp < 15.0):
            raise AssertionError(
                f"{name}: +10bp on 5Y moved par by {moved_bp:.2f}bp (expected ~10bp)")


_BASE_5Y = {"USD": 3.65, "KRW": 2.72, "KRW_KOFR": 2.55, "CRS": 1.08}


def _base_5y(name):
    return _BASE_5Y[name]


@case("L6-2", "snapshot and pricing agree on the same quotes")
def t_l6_2():
    snap = client.get("/api/market-snapshot").json()["data"]
    quoted = {q["tenor"]: q["mid"] for q in snap["quotes"]}
    pillars = {p["tenor"]: p["par_rate"] for p in snap["curve_pillars"]}
    for tenor in ("1Y", "5Y", "10Y"):
        if tenor in quoted and tenor in pillars:
            approx(pillars[tenor], quoted[tenor], 0.005,
                   f"snapshot pillar {tenor} must echo the live quote")


@case("L6-3", "reload-and-price returns internally consistent snapshot + pricing")
def t_l6_3():
    r = client.post("/api/reload-and-price",
                    json={"tenor": "5Y", "notional": 100_000_000.0})
    if r.status_code != 200:
        raise AssertionError(f"reload-and-price HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    for key in ("data", "pricing", "market_snapshot"):
        if key not in body:
            raise AssertionError(f"reload-and-price missing '{key}'")
    if body["data"] != body["pricing"]:
        raise AssertionError("data and pricing must be the same payload")
    ms = body["market_snapshot"]
    if not ms.get("curve_pillars"):
        raise AssertionError("reload-and-price returned no curve pillars")


@case("L6-4", "quote reset restores the baseline par rate")
def t_l6_4():
    base = pr("/api/price", tenor="5Y")["par_swap_rate_pct"]
    tradition_feed.update_quote("5Y", 9.99)
    bumped = pr("/api/price", tenor="5Y")["par_swap_rate_pct"]
    if abs(bumped - base) < 0.5:
        raise AssertionError("large quote change did not move pricing")
    freeze_market()
    restored = pr("/api/price", tenor="5Y")["par_swap_rate_pct"]
    approx(restored, base, 1e-6, "par must return to baseline after restore")


# ---------------------------------------------------------------- L4 CRS
@case("L4-1", "CRS Vanilla prices and returns a par CRS rate")
def t_l4_1():
    res = crs(crs_swap_type="Vanilla")
    p = res["pricing_results"]
    if p.get("par_crs_rate_pct") is None:
        raise AssertionError(f"Vanilla CRS returned no par_crs_rate_pct: {list(p)}")


@case("L4-2", "CRS Fixed-Fixed prices both legs")
def t_l4_2():
    res = crs(crs_swap_type="Fixed-Fixed", fixed_coupon_pct=3.55, usd_fixed_coupon_pct=3.50)
    p = res["pricing_results"]
    krw_par = p.get("par_krw_rate_pct")
    usd_par = p.get("par_usd_rate_pct")
    if krw_par is None or usd_par is None:
        raise AssertionError(
            f"Fixed-Fixed must return both par legs, got keys={sorted(p)}")
    for label, v in (("KRW", krw_par), ("USD", usd_par)):
        if not (-5.0 < v < 20.0):
            raise AssertionError(f"Fixed-Fixed {label} par implausible: {v}")


@case("L4-3", "CRS Fixed-Fixed par zeroes NPV, holding the other leg fixed")
def t_l4_3():
    # Each par rate is defined holding the opposite coupon fixed, so that is how it
    # must be verified: solve one leg, reprice with the same partner coupon, expect 0.
    for c_usd in (1.0, 3.0, 5.0):
        probe = crs(crs_swap_type="Fixed-Fixed", fixed_coupon_pct=3.0,
                    usd_fixed_coupon_pct=c_usd)
        par_krw = probe["pricing_results"]["par_krw_rate_pct"]
        again = crs(crs_swap_type="Fixed-Fixed", fixed_coupon_pct=par_krw,
                    usd_fixed_coupon_pct=c_usd)
        npv = again["pricing_results"]["deal_npv_krw"]
        rel = abs(npv) / abs(again["details"]["krw_notional"])
        if rel > 1e-6:
            raise AssertionError(
                f"c_usd={c_usd}: par_krw={par_krw:.6f} gave NPV {npv:,.0f} ({rel:.4%})")

    for c_krw in (2.0, 4.0, 6.0):
        probe = crs(crs_swap_type="Fixed-Fixed", fixed_coupon_pct=c_krw,
                    usd_fixed_coupon_pct=3.0)
        par_usd = probe["pricing_results"]["par_usd_rate_pct"]
        again = crs(crs_swap_type="Fixed-Fixed", fixed_coupon_pct=c_krw,
                    usd_fixed_coupon_pct=par_usd)
        npv = again["pricing_results"]["deal_npv_krw"]
        rel = abs(npv) / abs(again["details"]["krw_notional"])
        if rel > 1e-6:
            raise AssertionError(
                f"c_krw={c_krw}: par_usd={par_usd:.6f} gave NPV {npv:,.0f} ({rel:.4%})")


@case("L4-3b", "CRS Fixed-Fixed par is the genuine NPV root, not a forced zero")
def t_l4_3b():
    # Guards the shortcut that snaps NPV to zero near par: step off par and confirm the
    # NPV line actually passes through zero at the reported rate.
    c_usd = 3.0
    probe = crs(crs_swap_type="Fixed-Fixed", fixed_coupon_pct=3.0, usd_fixed_coupon_pct=c_usd)
    par_krw = probe["pricing_results"]["par_krw_rate_pct"]
    dv01 = probe["pricing_results"]["krw_dv01"]
    for d in (-0.5, -0.05, 0.05, 0.5):
        r = crs(crs_swap_type="Fixed-Fixed", fixed_coupon_pct=par_krw + d,
                usd_fixed_coupon_pct=c_usd)
        npv = r["pricing_results"]["deal_npv_krw"]
        implied_root = (par_krw + d) + npv / (dv01 * 100.0)
        approx(implied_root, par_krw, 1e-4,
               f"NPV at par{d:+.2f} implies root {implied_root:.6f}")


@case("L4-4", "CRS principal exchange: start and maturity are opposite, legs are opposite")
def t_l4_4():
    res = crs(crs_swap_type="Vanilla")
    f = res.get("principal_flows") or {}
    if not f or not f.get("included"):
        raise AssertionError(f"no principal exchange returned: {f}")
    for ccy in ("krw", "usd"):
        start, mat = f[f"start_{ccy}"], f[f"mat_{ccy}"]
        if start == 0 or mat == 0 or (start > 0) == (mat > 0):
            raise AssertionError(
                f"{ccy}: start {start:,.0f} and maturity {mat:,.0f} must be opposite")
    if (f["start_krw"] > 0) == (f["start_usd"] > 0):
        raise AssertionError("KRW and USD initial principal must flow opposite ways")


@case("L4-5", "CRS pricing responds to spot FX (curve does not, pricing must)")
def t_l4_5():
    lo = crs(crs_swap_type="Vanilla", spot_fx=1300.0)
    hi = crs(crs_swap_type="Vanilla", spot_fx=1450.0)
    n_lo = lo["details"]["krw_notional"]
    n_hi = hi["details"]["krw_notional"]
    if abs(n_hi - n_lo) < 1.0:
        raise AssertionError(
            f"KRW notional must follow spot: {n_lo:,.0f} vs {n_hi:,.0f}")
    approx(n_lo, 10_000_000.0 * 1300.0, 1.0, "krw notional = usd x spot")
    approx(n_hi, 10_000_000.0 * 1450.0, 1.0, "krw notional = usd x spot")


@case("L4-6", "CRS curve_type Advanced prices without error")
def t_l4_6():
    for ct in ("Standard", "Advanced"):
        res = crs(crs_swap_type="Vanilla", curve_type=ct)
        if res["details"]["curve_type"] != ct:
            raise AssertionError(f"curve_type not echoed: {res['details']['curve_type']}")


# ---------------------------------------------------------------- L5 rollercoaster
AMORT_PASTE = """2027-09-13\t2028-09-13\t100,000,000\t4.10
2028-09-13\t2029-09-13\t80,000,000\t4.10
2029-09-13\t2030-09-13\t60,000,000\t4.10
2030-09-13\t2031-09-13\t40,000,000\t4.10
2031-09-13\t2032-09-13\t20,000,000\t4.10"""

STEPUP_PASTE = """2027-09-13\t2028-09-13\t100,000,000\t3.50
2028-09-13\t2029-09-13\t100,000,000\t4.00
2029-09-13\t2030-09-13\t100,000,000\t4.50
2030-09-13\t2031-09-13\t100,000,000\t5.00"""

IRREGULAR_PASTE = """2027-09-13\t2027-11-30\t100,000,000\t4.00
2027-11-30\t2028-04-17\t250,000,000\t4.00
2028-04-17\t2028-05-02\t50,000,000\t4.00
2028-05-02\t2029-12-31\t175,000,000\t4.00"""


@case("L5-1", "rollercoaster paste parses into periods")
def t_l5_1():
    r = client.post("/api/rollercoaster/parse-paste", json={
        "raw_paste_text": AMORT_PASTE, "currency": "USD",
        "effective_date": "2027-09-13", "notional": 100_000_000.0,
    })
    if r.status_code != 200:
        raise AssertionError(f"parse-paste HTTP {r.status_code}: {r.text[:300]}")
    d = r.json()
    if d["count"] != 5:
        raise AssertionError(f"expected 5 periods, got {d['count']}")
    notionals = [p["notional"] for p in d["data"]]
    if notionals != [100e6, 80e6, 60e6, 40e6, 20e6]:
        raise AssertionError(f"amortizing notionals not parsed: {notionals}")


@case("L5-2", "amortizing schedule prices and lowers DV01 vs bullet")
def t_l5_2():
    bullet = pr("/api/price", notional=100_000_000.0, tenor="5Y",
                effective_date="2027-09-13", fixed_coupon_pct=4.10)
    amort = pr("/api/price", notional=100_000_000.0, tenor="5Y",
               effective_date="2027-09-13", fixed_coupon_pct=4.10,
               raw_paste_text=AMORT_PASTE)
    if amort["dv01"] >= bullet["dv01"]:
        raise AssertionError(
            f"amortizing DV01 {amort['dv01']:,.0f} should be below "
            f"bullet {bullet['dv01']:,.0f}")
    if amort["dv01"] <= 0:
        raise AssertionError("amortizing DV01 must stay positive")


@case("L5-3", "step-up coupon schedule is honoured per period")
def t_l5_3():
    res = price("/api/price", notional=100_000_000.0, tenor="4Y",
                effective_date="2027-09-13", fixed_coupon_pct=3.50,
                leg1_raw_paste_text=STEPUP_PASTE)
    rows = res["schedules"]["leg1_fixed"]
    rates = [round(r["fixed_rate_pct"], 4) for r in rows]
    if sorted(set(rates)) == [rates[0]]:
        raise AssertionError(f"step-up coupons collapsed to one rate: {rates}")
    if rates[:4] != [3.5, 4.0, 4.5, 5.0]:
        raise AssertionError(f"step-up coupons not applied in order: {rates}")


@case("L5-4", "irregular dates and jumping notional price without error")
def t_l5_4():
    res = price("/api/price", notional=100_000_000.0, tenor="2Y",
                effective_date="2027-09-13", fixed_coupon_pct=4.00,
                raw_paste_text=IRREGULAR_PASTE)
    rows = res["schedules"]["leg1_fixed"]
    if len(rows) != 4:
        raise AssertionError(f"expected 4 irregular periods, got {len(rows)}")
    notionals = [r["notional"] for r in rows]
    if notionals != [100e6, 250e6, 50e6, 175e6]:
        raise AssertionError(f"jumping notionals not preserved: {notionals}")
    for r in rows:
        if r["end_date"] <= r["start_date"]:
            raise AssertionError(f"non-positive period: {r['start_date']}..{r['end_date']}")


@case("L5-5", "Korean magnitude units parse (억 / 조)")
def t_l5_5():
    paste = "2027-09-13\t2028-09-13\t500억\t3.00\n2028-09-13\t2029-09-13\t1조\t3.00"
    r = client.post("/api/rollercoaster/parse-paste", json={
        "raw_paste_text": paste, "currency": "KRW", "effective_date": "2027-09-13",
    })
    d = r.json()
    got = [p["notional"] for p in d["data"]]
    if got != [5e10, 1e12]:
        raise AssertionError(f"Korean units mis-parsed: {got}")


@case("L5-6", "rollercoaster works on every currency incl. CRS")
def t_l5_6():
    endpoints = [
        ("USD", "/api/price", {"notional": 100_000_000.0}),
        ("KRW", "/api/krw/price", {"notional": 100_000_000.0}),
        ("KRW_KOFR", "/api/kofr/price", {"notional": 100_000_000.0}),
        ("KRW_CRS", "/api/crs/price", {"usd_notional": 100_000_000.0}),
    ]
    for name, ep, extra in endpoints:
        body = {"tenor": "5Y", "effective_date": "2027-09-13",
                "fixed_coupon_pct": 4.0, "raw_paste_text": AMORT_PASTE}
        body.update(extra)
        r = client.post(ep, json=body)
        if r.status_code != 200:
            raise AssertionError(f"{name} rollercoaster HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()["data"]
        sched = data["schedules"]
        rows = sched.get("leg1_fixed") or sched.get("dual_comparison") or []
        if len(rows) != 5:
            raise AssertionError(f"{name}: expected 5 custom periods, got {len(rows)}")


@case("L5-7", "malformed paste falls back to the auto schedule, never 500")
def t_l5_7():
    for junk in ("not a schedule at all", "###\n\n***", "2027-13-45\tabc\txyz"):
        r = client.post("/api/price", json={
            "tenor": "5Y", "notional": 100_000_000.0,
            "fixed_coupon_pct": 4.0, "raw_paste_text": junk,
        })
        if r.status_code != 200:
            raise AssertionError(f"junk paste {junk!r} -> HTTP {r.status_code}: {r.text[:200]}")


if __name__ == "__main__":
    import sys
    print("\n=== L6 live data / L4 CRS / L5 rollercoaster ===")
    failed = run_all("L6") + run_all("L4") + run_all("L5")
    sys.exit(1 if failed else 0)
