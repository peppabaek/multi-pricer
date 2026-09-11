"""
L9 - Advanced hybrid curve (flat-forward <2Y + log-cubic >2Y) and Hedge curve Greeks,
for USD SOFR OIS and KRW FX SOFR CRS.
"""
import datetime
from harness import case, approx, run_all

from test_l1_curves import USD_QUOTES, P_DATE
from test_l2_pricing import client, freeze_market
from sofr_pricer import (add_business_days, bootstrap_sofr_curve,
                         bootstrap_advanced_sofr_curve, CompositeSOFRCurve,
                         create_hedge_composite_curve, USDSOFRSwapPricer)

freeze_market()

SETTLE = add_business_days(P_DATE, 2)
QUOTE_MAP = {t.upper(): r for t, r in USD_QUOTES}

# Tenors the Advanced curve actually calibrates to (see bootstrap_advanced_sofr_curve).
BENCH_LONG = {"ON", "1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y",
              "18M", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y"}

_std = bootstrap_sofr_curve(P_DATE, SETTLE, USD_QUOTES)
_adv = bootstrap_advanced_sofr_curve(P_DATE, SETTLE, USD_QUOTES)


def usd(**kw):
    body = {"tenor": "5Y", "notional": 100_000_000.0}
    body.update(kw)
    r = client.post("/api/price", json=body)
    if r.status_code != 200:
        raise AssertionError(f"/api/price -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["data"]


def crs(**kw):
    body = {"tenor": "5Y", "usd_notional": 10_000_000.0}
    body.update(kw)
    r = client.post("/api/crs/price", json=body)
    if r.status_code != 200:
        raise AssertionError(f"/api/crs/price -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["data"]


def bucket_sum(rows):
    return sum(x.get("dv01", 0.0) for x in (rows or []))


# ------------------------------------------------- A. Advanced hybrid construction
@case("L9-A1", "Advanced curve is built by QuantLib, not silently falling back")
def t_a1():
    if _adv.ql_curve is None:
        raise AssertionError("ql_curve is None - bootstrap fell back to the standard curve")
    if _adv.curve_type != "Advanced":
        raise AssertionError(f"curve_type={_adv.curve_type}")


@case("L9-A2", "calibrated benchmark pillars reprice to the market quote")
def t_a2():
    pricer = USDSOFRSwapPricer(_adv)
    worst = 0.0
    for p in _adv.pillars:
        t = p["tenor"]
        if t in ("ON", "1W", "2W") or t not in BENCH_LONG or QUOTE_MAP.get(t) is None:
            continue
        par = pricer.price_swap(notional=1e8, tenor_str=t,
                                calculate_greeks=False)["pricing_results"]["par_swap_rate_pct"]
        worst = max(worst, abs(par - QUOTE_MAP[t]) * 100.0)
    if worst > 0.25:
        raise AssertionError(f"benchmark repricing error {worst:.4f}bp exceeds 0.25bp")


@case("L9-A3", "non-calibrated pillars stay within a stated interpolation tolerance")
def t_a3():
    # The hybrid deliberately calibrates to liquid benchmarks only, so the remaining
    # Murex pillars are interpolated. Bound the drift so a regression is visible.
    pricer = USDSOFRSwapPricer(_adv)
    worst, worst_t = 0.0, ""
    for p in _adv.pillars:
        t = p["tenor"]
        if t in ("ON", "1W", "2W") or t in BENCH_LONG or QUOTE_MAP.get(t) is None:
            continue
        par = pricer.price_swap(notional=1e8, tenor_str=t,
                                calculate_greeks=False)["pricing_results"]["par_swap_rate_pct"]
        err = abs(par - QUOTE_MAP[t]) * 100.0
        if err > worst:
            worst, worst_t = err, t
    if worst > 3.0:
        raise AssertionError(f"interpolated pillar {worst_t} off by {worst:.4f}bp (limit 3bp)")


@case("L9-A4", "2Y junction: discount factors are continuous across the blend")
def t_a4():
    prev = None
    for off in range(-150, 151, 5):
        d = SETTLE + datetime.timedelta(days=730 + off)
        df = _adv.get_df(d)
        if prev is not None:
            if df > prev + 1e-12:
                raise AssertionError(f"DF rose at 2Y{off:+d}d: {df:.10f} > {prev:.10f}")
            if abs(df - prev) > 5e-4:
                raise AssertionError(f"DF jump at 2Y{off:+d}d: {abs(df - prev):.2e}")
        prev = df


@case("L9-A5", "2Y junction: no forward-rate kink inside the 120-day transition")
def t_a5():
    fwds = []
    for off in range(-120, 1, 10):
        d0 = SETTLE + datetime.timedelta(days=730 + off)
        d1 = d0 + datetime.timedelta(days=30)
        fwds.append(_adv.get_forward_rate(d0, d1, "Act/360") * 100.0)
    for i in range(1, len(fwds)):
        step = abs(fwds[i] - fwds[i - 1])
        if step > 0.10:
            raise AssertionError(
                f"forward kink of {step*100:.2f}bp inside the junction window: {fwds}")


@case("L9-A6", "long end is smooth: no cubic-spline oscillation beyond 2Y")
def t_a6():
    fwds = []
    for m in range(24, 361, 6):
        d0 = SETTLE + datetime.timedelta(days=int(m * 30.44))
        d1 = d0 + datetime.timedelta(days=180)
        fwds.append(_adv.get_forward_rate(d0, d1, "Act/360") * 100.0)
    flips = 0
    for i in range(2, len(fwds)):
        d1_ = fwds[i - 1] - fwds[i - 2]
        d2_ = fwds[i] - fwds[i - 1]
        if d1_ * d2_ < 0 and min(abs(d1_), abs(d2_)) > 0.02:
            flips += 1
    if flips > 4:
        raise AssertionError(f"long end oscillates: {flips} significant direction flips")


@case("L9-A7", "Advanced and Standard agree at benchmarks, differ between them")
def t_a7():
    for p in _adv.pillars:
        if p["tenor"] in ("5Y", "10Y", "20Y"):
            z_adv = _adv.get_zero_rate(p["mat_date"])
            z_std = _std.get_zero_rate(p["mat_date"])
            if abs(z_adv - z_std) > 0.05:
                raise AssertionError(
                    f"{p['tenor']}: adv {z_adv:.4f} vs std {z_std:.4f} differ too much")
    d_mid = SETTLE + datetime.timedelta(days=int(4.5 * 365))
    if abs(_adv.get_zero_rate(d_mid) - _std.get_zero_rate(d_mid)) < 1e-9:
        raise AssertionError("Advanced is identical to Standard between pillars")


@case("L9-A8", "Advanced curve has no negative implied forwards")
def t_a8():
    for i in range(1, len(_adv.pillars)):
        p0, p1 = _adv.pillars[i - 1], _adv.pillars[i]
        days = (p1["mat_date"] - p0["mat_date"]).days
        if days <= 0:
            continue
        fwd = (p0["df"] / p1["df"] - 1.0) / (days / 365.0) * 100.0
        if fwd < -0.01:
            raise AssertionError(f"negative fwd {fwd:.4f}% at {p1['tenor']}")


# ------------------------------------------------- B. Hedge curve (composite)
@case("L9-B1", "unbumped composite reproduces the Advanced curve exactly (Z^H = 0)")
def t_b1():
    comp = CompositeSOFRCurve(_adv)
    for p in _adv.pillars:
        approx(comp.get_df(p["mat_date"]), _adv.get_df(p["mat_date"]), 1e-15,
               f"{p['tenor']} DF")
        approx(comp.get_zero_rate(p["mat_date"]), _adv.get_zero_rate(p["mat_date"]), 1e-12,
               f"{p['tenor']} zero")


@case("L9-B2", "hedge tent is strictly local to its neighbouring pillars")
def t_b2():
    bumped = create_hedge_composite_curve(_adv, bumped_tenor="5Y", bump_bp=0.0001)
    for p in _adv.pillars:
        t = p["tenor"]
        dz = (bumped.get_zero_rate(p["mat_date"]) - _adv.get_zero_rate(p["mat_date"])) * 100.0
        if t in ("5Y",):
            if not (0.9 < dz < 1.1):
                raise AssertionError(f"5Y bump moved zero by {dz:.4f}bp (want ~1bp)")
        elif t in ("6Y", "7Y", "8Y", "9Y", "10Y", "15Y", "20Y", "30Y",
                   "1Y", "2Y", "3Y", "18M"):
            if abs(dz) > 0.05:
                raise AssertionError(f"{t} moved {dz:.4f}bp - tent is not local")


@case("L9-B3", "every hedge pillar bump is reproducible and localised")
def t_b3():
    for tenor in ("2Y", "5Y", "10Y", "20Y"):
        bumped = create_hedge_composite_curve(_adv, bumped_tenor=tenor, bump_bp=0.0001)
        hit = None
        for p in _adv.pillars:
            if p["tenor"] == tenor:
                hit = (bumped.get_zero_rate(p["mat_date"]) - _adv.get_zero_rate(p["mat_date"])) * 100.0
        if hit is None or not (0.85 < hit < 1.15):
            raise AssertionError(f"{tenor}: bump produced {hit}bp at its own pillar")


@case("L9-B4", "USD Advanced returns both standard and hedge bucketings")
def t_b4():
    d = usd(curve_type="Advanced")
    if not d.get("delta_bucketing"):
        raise AssertionError("Advanced returned no delta_bucketing")
    if not d.get("hedge_delta_bucketing"):
        raise AssertionError("Advanced returned no hedge_delta_bucketing")


@case("L9-B5", "hedge bucket deltas reconcile to DV01")
def t_b5():
    for ct in ("Advanced", "HedgeCurve"):
        d = usd(curve_type=ct)
        dv01 = d["pricing_results"]["dv01"]
        rows = d.get("hedge_delta_bucketing") or d.get("delta_bucketing")
        total = bucket_sum(rows)
        rel = abs(abs(total) - abs(dv01)) / abs(dv01)
        if rel > 0.02:
            raise AssertionError(
                f"{ct}: sum(hedge KRD) {total:,.2f} vs DV01 {dv01:,.2f} ({rel:.2%})")


@case("L9-B6", "hedge deltas vanish beyond the trade maturity (strict localness)")
def t_b6():
    d = usd(curve_type="HedgeCurve", tenor="5Y")
    for row in (d.get("delta_bucketing") or []):
        t = row.get("tenor", "")
        if t in ("7Y", "10Y", "15Y", "20Y", "30Y") and abs(row.get("dv01", 0.0)) > 1.0:
            raise AssertionError(f"5Y trade shows {row['dv01']:,.2f} risk at {t}")


@case("L9-B7", "hedge risk concentrates at the trade maturity bucket")
def t_b7():
    for tenor in ("2Y", "5Y", "10Y"):
        d = usd(curve_type="HedgeCurve", tenor=tenor)
        rows = d.get("delta_bucketing") or []
        peak = max(rows, key=lambda r: abs(r.get("dv01", 0.0)))
        if peak.get("tenor") != tenor:
            raise AssertionError(
                f"{tenor} trade peaks at {peak.get('tenor')} ({peak.get('dv01'):,.2f})")


@case("L9-B8", "Advanced and HedgeCurve price the same trade identically")
def t_b8():
    a = usd(curve_type="Advanced")["pricing_results"]
    h = usd(curve_type="HedgeCurve")["pricing_results"]
    approx(h["par_swap_rate_pct"], a["par_swap_rate_pct"], 1e-6, "par must match")
    approx(h["dv01"], a["dv01"], abs(a["dv01"]) * 1e-9 + 1e-6, "DV01 must match")


# ------------------------------------------------- C. CRS on the Advanced / hedge curve
@case("L9-C1", "CRS prices on Standard, Advanced and HedgeCurve alike")
def t_c1():
    base = crs(curve_type="Standard")["pricing_results"]["par_crs_rate_pct"]
    for ct in ("Advanced", "HedgeCurve"):
        p = crs(curve_type=ct)["pricing_results"]["par_crs_rate_pct"]
        if abs(p - base) * 100.0 > 1.0:
            raise AssertionError(f"CRS par moved {abs(p-base)*100:.3f}bp under {ct}")


@case("L9-C2", "CRS reports KRW-curve key rate deltas that reconcile to krw_dv01")
def t_c2():
    for ct in ("Standard", "Advanced", "HedgeCurve"):
        d = crs(curve_type=ct)
        rows = d.get("krw_key_rate_deltas") or []
        if not rows:
            raise AssertionError(f"{ct}: no krw_key_rate_deltas returned")
        total = bucket_sum(rows)
        dv01 = d["pricing_results"]["krw_dv01"]
        rel = abs(abs(total) - abs(dv01)) / abs(dv01)
        if rel > 0.02:
            raise AssertionError(
                f"{ct}: sum(KRW KRD) {total:,.0f} vs krw_dv01 {dv01:,.0f} ({rel:.2%})")


@case("L9-C3", "CRS KRW risk concentrates at the trade maturity")
def t_c3():
    for tenor in ("3Y", "5Y", "10Y"):
        d = crs(tenor=tenor, curve_type="Advanced")
        rows = d.get("krw_key_rate_deltas") or []
        peak = max(rows, key=lambda r: abs(r.get("dv01", 0.0)))
        if peak.get("tenor") != tenor:
            raise AssertionError(
                f"{tenor} CRS peaks at {peak.get('tenor')} ({peak.get('dv01'):,.0f})")


@case("L9-C4", "CRS Fixed-Fixed on Advanced produces non-zero USD key rate deltas")
def t_c4():
    d = crs(curve_type="Advanced", crs_swap_type="Fixed-Fixed",
            fixed_coupon_pct=3.0, usd_fixed_coupon_pct=3.0)
    usd_rows = d.get("key_rate_deltas") or []
    if abs(bucket_sum(usd_rows)) < 1.0:
        raise AssertionError("Fixed-Fixed USD key rate deltas are all zero")
    hedge_rows = d.get("hedge_key_rate_deltas") or []
    if not hedge_rows or abs(bucket_sum(hedge_rows)) < 1.0:
        raise AssertionError("Fixed-Fixed hedge key rate deltas are all zero")


@case("L9-C5", "CRS Vanilla par carries the USD basis spread")
def t_c5():
    p0 = crs(curve_type="Standard", spread_bp=0.0)["pricing_results"]["par_crs_rate_pct"]
    p25 = crs(curve_type="Standard", spread_bp=25.0)["pricing_results"]["par_crs_rate_pct"]
    moved = (p25 - p0) * 100.0
    if not (15.0 < moved < 30.0):
        raise AssertionError(
            f"25bp USD spread moved the CRS par by {moved:.2f}bp (expected ~20-25bp)")


@case("L9-C6", "CRS KRW deltas stay sane with a basis spread applied")
def t_c6():
    d = crs(curve_type="Standard", spread_bp=25.0)
    total = bucket_sum(d.get("krw_key_rate_deltas"))
    dv01 = d["pricing_results"]["krw_dv01"]
    rel = abs(abs(total) - abs(dv01)) / abs(dv01)
    if rel > 0.05:
        raise AssertionError(
            f"with spread: sum(KRW KRD) {total:,.0f} vs krw_dv01 {dv01:,.0f} ({rel:.2%})")


if __name__ == "__main__":
    import sys
    print("\n=== L9 Advanced hybrid curve + Hedge curve Greeks ===")
    sys.exit(1 if run_all("L9") else 0)
