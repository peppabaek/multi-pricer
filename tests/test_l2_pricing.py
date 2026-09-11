"""L2 - Swap pricing invariants, exercised through the real dashboard API path."""
import datetime
from harness import case, approx, run_all

from fastapi.testclient import TestClient
from server.app import app
from server.tradition_feed import tradition_feed
from server.krw_feed import krw_feed
from server.kofr_feed import kofr_feed
from server.crs_feed import crs_feed

from test_l1_curves import USD_QUOTES, KRW_QUOTES, KOFR_QUOTES, CRS_QUOTES

client = TestClient(app)


def freeze_market():
    """Pin every feed to a deterministic snapshot - no Eikon needed."""
    for t, r in USD_QUOTES:
        tradition_feed.update_quote(t, r)
    for t, r in KRW_QUOTES:
        krw_feed.update_quote(t, r)
    for t, r in KOFR_QUOTES:
        kofr_feed.update_quote(t, r)
    for t, r in CRS_QUOTES:
        crs_feed.update_quote_manually(t, r)


freeze_market()

PRODUCTS = [
    ("USD", "/api/price", 100_000_000.0),
    ("KRW", "/api/krw/price", 10_000_000_000.0),
    ("KRW_KOFR", "/api/kofr/price", 10_000_000_000.0),
]


def price(endpoint, **kw):
    body = {"tenor": "5Y"}
    body.update(kw)
    r = client.post(endpoint, json=body)
    if r.status_code != 200:
        raise AssertionError(f"{endpoint} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["data"]


def pr(endpoint, **kw):
    return price(endpoint, **kw)["pricing_results"]


@case("L2-1", "coupon = par  =>  NPV == 0")
def t_l2_1():
    for name, ep, notional in PRODUCTS:
        par = pr(ep, notional=notional)["par_swap_rate_pct"]
        res = pr(ep, notional=notional, fixed_coupon_pct=par)
        approx(res["deal_npv"], 0.0, 1e-6, f"{name} NPV at par")


@case("L2-3", "Pay Fixed with coupon < par  =>  NPV > 0")
def t_l2_3():
    for name, ep, notional in PRODUCTS:
        par = pr(ep, notional=notional)["par_swap_rate_pct"]
        res = pr(ep, notional=notional, position="Pay Fixed", fixed_coupon_pct=par - 0.25)
        if res["deal_npv"] <= 0:
            raise AssertionError(
                f"{name}: pay-fixed below par should be positive NPV, got {res['deal_npv']}")


@case("L2-4", "Pay/Rec antisymmetry: NPV_pay(c) == -NPV_rec(c)")
def t_l2_4():
    for name, ep, notional in PRODUCTS:
        par = pr(ep, notional=notional)["par_swap_rate_pct"]
        c = par - 0.25
        pay = pr(ep, notional=notional, position="Pay Fixed", fixed_coupon_pct=c)["deal_npv"]
        rec = pr(ep, notional=notional, position="Rec Fixed", fixed_coupon_pct=c)["deal_npv"]
        approx(pay, -rec, abs(pay) * 1e-9 + 1e-6, f"{name} pay/rec antisymmetry")


@case("L2-5", "notional linearity: doubling notional doubles NPV and DV01")
def t_l2_5():
    for name, ep, notional in PRODUCTS:
        par = pr(ep, notional=notional)["par_swap_rate_pct"]
        c = par - 0.25
        a = pr(ep, notional=notional, fixed_coupon_pct=c)
        b = pr(ep, notional=notional * 2, fixed_coupon_pct=c)
        approx(b["deal_npv"], a["deal_npv"] * 2, abs(a["deal_npv"]) * 1e-6 + 1e-3,
               f"{name} NPV linearity")
        approx(b["dv01"], a["dv01"] * 2, abs(a["dv01"]) * 1e-6 + 1e-2,
               f"{name} DV01 linearity")


@case("L2-6", "analytic DV01 vs finite-difference reprice")
def t_l2_6():
    for name, ep, notional in PRODUCTS:
        par = pr(ep, notional=notional)["par_swap_rate_pct"]
        base = pr(ep, notional=notional, position="Pay Fixed", fixed_coupon_pct=par)
        up = pr(ep, notional=notional, position="Pay Fixed", fixed_coupon_pct=par + 0.01)
        fd = abs(up["deal_npv"] - base["deal_npv"])
        analytic = base["dv01"]
        rel = abs(fd - analytic) / max(abs(analytic), 1.0)
        if rel > 0.01:
            raise AssertionError(
                f"{name}: analytic DV01 {analytic:,.2f} vs finite-diff {fd:,.2f} "
                f"(rel err {rel:.2%})")


@case("L2-7", "sum of key rate deltas reconciles to DV01")
def t_l2_7():
    for name, ep, notional in PRODUCTS:
        res = price(ep, notional=notional, tenor="5Y")
        buckets = res.get("delta_bucketing") or res.get("key_rate_deltas") or []
        if not buckets:
            raise AssertionError(f"{name}: no key rate deltas returned")
        total = sum(b.get("dv01", 0.0) for b in buckets)
        dv01 = res["pricing_results"]["dv01"]
        rel = abs(abs(total) - abs(dv01)) / max(abs(dv01), 1.0)
        if rel > 0.05:
            raise AssertionError(
                f"{name}: sum(KRD) {total:,.2f} vs DV01 {dv01:,.2f} (rel err {rel:.2%})")


@case("L2-8", "DV01 increases monotonically with maturity")
def t_l2_8():
    for name, ep, notional in PRODUCTS:
        prev = -1.0
        for tenor in ("1Y", "2Y", "3Y", "5Y", "10Y"):
            d = pr(ep, notional=notional, tenor=tenor)["dv01"]
            if d < prev:
                raise AssertionError(f"{name}: DV01 fell at {tenor}: {d:,.2f} < {prev:,.2f}")
            prev = d


@case("L2-9", "schedule internal consistency: net_cf and net_pv")
def t_l2_9():
    # net_cf is signed from the holder's perspective: pay-fixed receives float, so
    # net_cf = float - fixed. Rec-fixed flips it.
    for name, ep, notional in PRODUCTS:
        for position, sign in (("Pay Fixed", 1.0), ("Rec Fixed", -1.0)):
            res = price(ep, notional=notional, tenor="3Y", position=position)
            rows = res["schedules"]["dual_comparison"]
            if not rows:
                raise AssertionError(f"{name}: empty dual_comparison")
            for r in rows:
                approx(r["net_cf"], sign * (r["float_cf"] - r["fixed_cf"]),
                       abs(r["fixed_cf"]) * 1e-6 + 1e-3,
                       f"{name} {position} net_cf p{r['period_no']}")
                # Each leg discounts on its own pay date, so net_pv is the PV difference
                # rather than net_cf times the row's (leg 1) discount factor.
                approx(r["net_pv"], sign * (r["float_pv"] - r["fixed_pv"]),
                       abs(r["fixed_pv"]) * 1e-6 + 1e-3,
                       f"{name} {position} net_pv p{r['period_no']}")


@case("L2-10", "leg PV totals reconcile to schedule rows")
def t_l2_10():
    for name, ep, notional in PRODUCTS:
        res = price(ep, notional=notional, tenor="3Y")
        rows = res["schedules"]["dual_comparison"]
        pres = res["pricing_results"]
        approx(sum(r["fixed_pv"] for r in rows), pres["fixed_leg_pv"],
               abs(pres["fixed_leg_pv"]) * 1e-5 + 1e-2, f"{name} fixed leg PV")
        approx(sum(r["float_pv"] for r in rows), pres["float_leg_pv"],
               abs(pres["float_leg_pv"]) * 1e-5 + 1e-2, f"{name} float leg PV")


if __name__ == "__main__":
    import sys
    print("\n=== L2 Swap Pricing Invariants ===")
    sys.exit(1 if run_all("L2") else 0)
