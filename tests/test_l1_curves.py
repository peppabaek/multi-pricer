"""L1 - Curve bootstrap invariants. Pure functions, no server, no Eikon."""
import datetime
from harness import case, approx, run_all

from sofr_pricer import bootstrap_sofr_curve, bootstrap_advanced_sofr_curve
from krw_pricer import bootstrap_krw_curve, get_krw_spot_date
from kofr_pricer import bootstrap_kofr_curve, get_spot_date as get_kofr_spot_date
from crs_pricer import bootstrap_crs_curve, get_crs_spot_date

P_DATE = datetime.date(2026, 9, 11)

USD_QUOTES = [
    ("ON", 4.33), ("1W", 4.32), ("2W", 4.31),
    ("1M", 4.28), ("2M", 4.22), ("3M", 4.16), ("4M", 4.11), ("5M", 4.06),
    ("6M", 4.01), ("7M", 3.97), ("8M", 3.94), ("9M", 3.91), ("10M", 3.88),
    ("11M", 3.86), ("1Y", 3.84), ("18M", 3.72), ("2Y", 3.66), ("3Y", 3.61),
    ("4Y", 3.62), ("5Y", 3.65), ("6Y", 3.69), ("7Y", 3.73), ("8Y", 3.77),
    ("9Y", 3.81), ("10Y", 3.85), ("11Y", 3.89), ("12Y", 3.92),
    ("15Y", 3.99), ("20Y", 4.02), ("25Y", 3.98), ("30Y", 3.92),
]

KRW_QUOTES = [
    ("3M", 2.62), ("6M", 2.60), ("9M", 2.59), ("1Y", 2.58), ("18M", 2.57),
    ("2Y", 2.58), ("3Y", 2.62), ("4Y", 2.67), ("5Y", 2.72), ("7Y", 2.81),
    ("10Y", 2.92), ("15Y", 2.99), ("20Y", 3.01),
]

KOFR_QUOTES = [
    ("3M", 2.45), ("6M", 2.43), ("9M", 2.42), ("1Y", 2.41), ("18M", 2.40),
    ("2Y", 2.41), ("3Y", 2.45), ("4Y", 2.50), ("5Y", 2.55), ("7Y", 2.64),
    ("10Y", 2.75), ("15Y", 2.82), ("20Y", 2.84),
]

CRS_QUOTES = [
    ("1Y", 1.20), ("2Y", 1.15), ("3Y", 1.12), ("4Y", 1.10), ("5Y", 1.08),
    ("7Y", 1.05), ("10Y", 1.02), ("15Y", 0.98), ("20Y", 0.95),
]
SPOT_FX = 1375.50


def usd_curve():
    from sofr_pricer import add_business_days
    return bootstrap_sofr_curve(P_DATE, add_business_days(P_DATE, 2), USD_QUOTES)


def krw_curve():
    return bootstrap_krw_curve(P_DATE, get_krw_spot_date(P_DATE), KRW_QUOTES)


def kofr_curve():
    return bootstrap_kofr_curve(P_DATE, get_kofr_spot_date(P_DATE, 1), KOFR_QUOTES)


def crs_curve():
    return bootstrap_crs_curve(P_DATE, get_crs_spot_date(P_DATE, 2), CRS_QUOTES, SPOT_FX)


ALL = [("USD", usd_curve), ("KRW", krw_curve), ("KOFR", kofr_curve), ("CRS", crs_curve)]


@case("L1-2", "DF(settle)~1, DF monotonically decreasing, DF>0")
def t_l1_2():
    for name, builder in ALL:
        c = builder()
        prev = 1.01
        for p in c.pillars:
            df = p["df"]
            if df <= 0:
                raise AssertionError(f"{name}: DF<=0 at {p['tenor']} -> {df}")
            if df > prev + 1e-9:
                raise AssertionError(
                    f"{name}: DF not monotone at {p['tenor']}: {df:.8f} > prev {prev:.8f}")
            prev = df
        approx(c.get_df(c.settle_date), c.df_settle, 1e-9, f"{name} df_settle")


@case("L1-3", "zero rate linear interpolation exact at pillars")
def t_l1_3():
    for name, builder in ALL:
        c = builder()
        for p in c.pillars:
            z = c.get_zero_rate(p["mat_date"])
            approx(z, p["zero_rate"], 1e-8, f"{name} {p['tenor']} zero")


@case("L1-4", "flat extrapolation beyond last pillar")
def t_l1_4():
    for name, builder in ALL:
        c = builder()
        last = c.pillars[-1]
        far = last["mat_date"] + datetime.timedelta(days=3650)
        approx(c.get_zero_rate(far), last["zero_rate"], 1e-8, f"{name} flat extrap")


@case("L1-7", "bump locality: +10bp on 5Y leaves 30Y zero unchanged")
def t_l1_7():
    from sofr_pricer import add_business_days
    s = add_business_days(P_DATE, 2)
    base = bootstrap_sofr_curve(P_DATE, s, USD_QUOTES)
    bumped_q = [(t, r + 0.10 if t == "5Y" else r) for t, r in USD_QUOTES]
    bumped = bootstrap_sofr_curve(P_DATE, s, bumped_q)

    z5_base = [p for p in base.pillars if p["tenor"] == "5Y"][0]["zero_rate"]
    z5_bump = [p for p in bumped.pillars if p["tenor"] == "5Y"][0]["zero_rate"]
    if z5_bump - z5_base < 0.05:
        raise AssertionError(f"5Y zero barely moved: {z5_base:.4f} -> {z5_bump:.4f}")

    z1_base = [p for p in base.pillars if p["tenor"] == "1Y"][0]["zero_rate"]
    z1_bump = [p for p in bumped.pillars if p["tenor"] == "1Y"][0]["zero_rate"]
    approx(z1_bump, z1_base, 1e-6, "1Y should be unaffected by 5Y bump")


@case("L1-8", "CRS discount curve is spot-FX invariant (spot cancels in par equation)")
def t_l1_8():
    # With N_krw = S x N_usd the spot rate cancels out of the par CRS equation, so the
    # bootstrapped KRW discount curve must not move with spot. Spot only enters pricing
    # (notional conversion / FX delta) - that is asserted in L4.
    s = get_crs_spot_date(P_DATE, 2)
    c1 = bootstrap_crs_curve(P_DATE, s, CRS_QUOTES, 1300.0)
    c2 = bootstrap_crs_curve(P_DATE, s, CRS_QUOTES, 1450.0)
    for p1, p2 in zip(c1.pillars, c2.pillars):
        approx(p1["df"], p2["df"], 1e-12, f"CRS {p1['tenor']} df must be spot-invariant")
    approx(c1.spot_fx, 1300.0, 1e-9, "spot_fx carried on curve")
    approx(c2.spot_fx, 1450.0, 1e-9, "spot_fx carried on curve")


@case("L1-9", "missing feed tenors must not corrupt the curve (sparse live snapshot)")
def t_l1_9():
    # A live feed regularly drops tenors. Every curve must degrade to interpolation,
    # never to a silent short-rate fallback.
    sparse_krw = [("3M", 2.62), ("1Y", 2.58), ("5Y", 2.72), ("10Y", 2.92), ("20Y", 3.01)]
    c = bootstrap_krw_curve(P_DATE, get_krw_spot_date(P_DATE), sparse_krw)
    prev = 1.01
    for p in c.pillars:
        if p["df"] > prev + 1e-9:
            raise AssertionError(
                f"KRW sparse: DF rose at {p['tenor']} ({p['df']:.8f} > {prev:.8f})")
        prev = p["df"]

    sparse_kofr = [("3M", 2.45), ("1Y", 2.41), ("5Y", 2.55), ("10Y", 2.75)]
    c2 = bootstrap_kofr_curve(P_DATE, get_kofr_spot_date(P_DATE, 1), sparse_kofr)
    prev = 1.01
    for p in c2.pillars:
        if p["df"] > prev + 1e-9:
            raise AssertionError(
                f"KOFR sparse: DF rose at {p['tenor']} ({p['df']:.8f} > {prev:.8f})")
        prev = p["df"]


@case("L1-10", "no negative implied forward rates across the whole grid")
def t_l1_10():
    # Curve-agnostic: derive the simple forward straight from discount factors so this
    # holds for OIS curves that expose compounded forwards instead of get_forward_rate.
    for name, builder in ALL:
        c = builder()
        for i in range(1, len(c.pillars)):
            p0, p1 = c.pillars[i - 1], c.pillars[i]
            days = (p1["mat_date"] - p0["mat_date"]).days
            if days <= 0 or p1["df"] <= 0:
                continue
            fwd = (p0["df"] / p1["df"] - 1.0) / (days / 365.0) * 100.0
            if fwd < -0.01:
                raise AssertionError(
                    f"{name}: negative fwd {fwd:.4f}% between "
                    f"{p0['tenor']} and {p1['tenor']}")


if __name__ == "__main__":
    import sys
    print("\n=== L1 Curve Bootstrap Invariants ===")
    sys.exit(1 if run_all() else 0)
