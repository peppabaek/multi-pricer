# -*- coding: utf-8 -*-
"""
L17 Amortising schedules with stub ("짜투리") periods.

When a payment date is rolled past the accrual end, the principal repaid on the end
date keeps accruing over the gap. Desks book that as an extra one- or two-day row with
no period number, which overlaps the row that follows it - so the block is no longer a
simple sequence, and the sheet carries its own header with the columns in desk order.

The trade in these tests is the one from the desk's own sheet: 2.5bn KRW amortising
monthly over 18 months, with six stub rows.
"""
import sys, datetime
from harness import case, run_all

from common_pricer.rollercoaster_engine import parse_rollercoaster_paste
from fastapi.testclient import TestClient
from server.app import app

client = TestClient(app)

HEADER = ("회차\t변동금리결정일\t시작일(포함)\t만기일(불포함)\t"
          "이자교환일\t일수\t명목 금액\t원금 상환액")

# fixing, start, end, pay, days, notional
PHASE1 = [
    ("2026-09-17", "2026-09-18", "2026-10-18", "2026-10-19", 30, 2500000000),
    ("2026-09-17", "2026-10-18", "2026-11-18", "2026-11-18", 31, 2361096000),
    ("2026-09-17", "2026-11-18", "2026-12-18", "2026-12-18", 30, 2222208000),
    ("2026-12-17", "2026-12-18", "2027-01-18", "2027-01-18", 31, 2083320000),
    ("2026-12-17", "2027-01-18", "2027-02-18", "2027-02-18", 31, 1944432000),
    ("2026-12-17", "2027-02-18", "2027-03-18", "2027-03-18", 28, 1805544000),
    ("2027-03-17", "2027-03-18", "2027-04-18", "2027-04-19", 31, 1666656000),
    ("2027-03-17", "2027-04-18", "2027-05-18", "2027-05-18", 30, 1527768000),
    ("2027-03-17", "2027-05-18", "2027-06-18", "2027-06-18", 31, 1388880000),
    ("2027-06-17", "2027-06-18", "2027-07-18", "2027-07-20", 30, 1249992000),
    ("2027-06-17", "2027-07-18", "2027-08-18", "2027-08-18", 31, 1111104000),
    ("2027-06-17", "2027-08-18", "2027-09-18", "2027-09-20", 31, 972216000),
    ("2027-09-17", "2027-09-18", "2027-10-18", "2027-10-18", 30, 833328000),
    ("2027-09-17", "2027-10-18", "2027-11-18", "2027-11-18", 31, 694440000),
    ("2027-09-17", "2027-11-18", "2027-12-18", "2027-12-20", 30, 555552000),
    ("2027-12-17", "2027-12-18", "2028-01-18", "2028-01-18", 31, 416664000),
    ("2027-12-17", "2028-01-18", "2028-02-18", "2028-02-18", 31, 277776000),
    ("2027-12-17", "2028-02-18", "2028-03-18", "2028-03-20", 29, 138888000),
]
PHASE2 = [
    ("2026-09-17", "2026-10-18", "2026-10-19", "2026-10-19", 1, 138904000),
    ("2027-03-17", "2027-04-18", "2027-04-19", "2027-04-19", 1, 138888000),
    ("2027-06-17", "2027-07-18", "2027-07-20", "2027-07-20", 2, 138888000),
    ("2027-09-17", "2027-09-18", "2027-09-20", "2027-09-20", 2, 138888000),
    ("2027-12-17", "2027-12-18", "2027-12-20", "2027-12-20", 2, 138888000),
    ("2028-03-17", "2028-03-18", "2028-03-20", "2028-03-20", 2, 138888000),
]


def sheet(rows, numbered=True, header=HEADER):
    """What copying the block out of Excel gives you, blank cells and all."""
    out = [header] if header else []
    for i, (f, s, e, p, d, n) in enumerate(rows, 1):
        out.append(f"{i if numbered else ''}\t{f}\t{s}\t{e}\t{p}\t{d}\t{n:,}\t")
    return "\n".join(out)


def whole_sheet():
    merged = sorted(PHASE1 + PHASE2, key=lambda r: (r[1], r[2]))
    out, n = [HEADER], 0
    for row in merged:
        f, s, e, p, d, notl = row
        if row in PHASE1:
            n += 1
            out.append(f"{n}\t{f}\t{s}\t{e}\t{p}\t{d}\t{notl:,}\t")
        else:
            out.append(f"\t{f}\t{s}\t{e}\t{p}\t{d}\t{notl:,}\t")
    return "\n".join(out)


def parse(text):
    return parse_rollercoaster_paste(text, datetime.date(2026, 9, 18),
                                     default_notional=2.5e9, default_coupon_pct=3.0)


def price(text):
    r = client.post("/api/krw/price", json={
        "notional": 2500000000, "tenor": "18M",
        "effective_date": "2026-09-18", "maturity_date": "2028-03-18",
        "fixed_coupon_pct": 3.0, "position": "Pay Fixed",
        "leg1_payment_freq": "1M", "leg2_payment_freq": "1M",
        "leg1_day_count": "Act/365", "leg1_calendar": "SEB",
        "leg1_raw_paste_text": text, "leg2_raw_paste_text": text,
    })
    if r.status_code != 200:
        raise AssertionError(f"HTTP {r.status_code}: {r.text[:300]}")
    d = r.json()["data"]
    n = len(d["schedules"].get("leg1_fixed") or d["schedules"].get("leg1_schedule") or [])
    return d["pricing_results"], n


@case("L17-1", "the desk's own sheet parses to every row, stubs included")
def t_1():
    periods = parse(whole_sheet())
    if len(periods) != 24:
        raise AssertionError(f"parsed {len(periods)} of 24 rows")


@case("L17-2", "a blank period number does not shift the columns after it")
def t_2():
    by_start = {p["start_date"]: p for p in parse(whole_sheet())}
    stub = by_start.get("2026-10-18")
    # Two rows start on 2026-10-18: the stub and period 2. Find the one-day one.
    stubs = [p for p in parse(whole_sheet()) if p["end_date"] == "2026-10-19"]
    if not stubs:
        raise AssertionError("the one-day stub row was dropped")
    if abs(stubs[0]["notional"] - 138904000) > 1:
        raise AssertionError(f"stub notional read as {stubs[0]['notional']:,.0f}, "
                             f"expected 138,904,000")


@case("L17-3", "the day-count column is not mistaken for a rate")
def t_3():
    for p in parse(whole_sheet()):
        # 일수 is 1, 2 or 28-31; a coupon of 1% or 30% would both come from that column.
        if p["fixed_rate_pct"] not in (3.0,):
            raise AssertionError(
                f"{p['start_date']}: rate {p['fixed_rate_pct']} - a non-rate column "
                f"was read as the coupon")


@case("L17-4", "every amortising notional survives in the right period")
def t_4():
    got = {(p["start_date"], p["end_date"]): round(p["notional"]) for p in parse(whole_sheet())}
    for f, s, e, pay, d, n in PHASE1 + PHASE2:
        if got.get((s, e)) != n:
            raise AssertionError(f"{s}~{e}: notional {got.get((s, e))}, expected {n:,}")


@case("L17-5", "a pay date the sheet states is used as stated")
def t_5():
    got = {(p["start_date"], p["end_date"]): p["pay_date"] for p in parse(whole_sheet())}
    for f, s, e, pay, d, n in PHASE1 + PHASE2:
        if got.get((s, e)) != pay:
            raise AssertionError(f"{s}~{e}: pay {got.get((s, e))}, expected {pay}")


@case("L17-6", "fixing dates are carried through")
def t_6():
    got = {(p["start_date"], p["end_date"]): p.get("fixing_date")
           for p in parse(whole_sheet())}
    for f, s, e, pay, d, n in PHASE1 + PHASE2:
        if got.get((s, e)) != f:
            raise AssertionError(f"{s}~{e}: fixing {got.get((s, e))}, expected {f}")


@case("L17-7", "the whole sheet prices in one go")
def t_7():
    pr, n = price(whole_sheet())
    if n != 24:
        raise AssertionError(f"priced {n} periods, expected 24")
    if not pr.get("dv01") or pr["dv01"] <= 0:
        raise AssertionError(f"no risk on a live trade: {pr.get('dv01')}")


@case("L17-8", "one go equals the trader's Phase 1 / Phase 2 split")
def t_8():
    p1, _ = price(sheet(PHASE1))
    p2, _ = price(sheet(PHASE2, numbered=False))
    whole, _ = price(whole_sheet())

    # dv01 is reported rounded to the cent, so three reported figures can
    # disagree by a cent and a half on quantisation alone. A split that really
    # lost a period would be out by thousands - L17-9 measures that.
    for key in ("dv01",):
        split = p1[key] + p2[key]
        if abs(whole[key] - split) > max(0.015, abs(split) * 1e-9):
            raise AssertionError(f"{key}: whole {whole[key]:,.4f} vs split {split:,.4f}")

    npv_key = next((k for k in ("net_present_value", "npv", "deal_npv") if k in p1), None)
    if npv_key:
        split = p1[npv_key] + p2[npv_key]
        if abs(whole[npv_key] - split) > max(1e-4, abs(split) * 1e-9):
            raise AssertionError(
                f"NPV: whole {whole[npv_key]:,.2f} vs split {split:,.2f}")


@case("L17-9", "the stub rows carry real risk, so dropping them would be a silent error")
def t_9():
    p1, _ = price(sheet(PHASE1))
    whole, _ = price(whole_sheet())
    if abs(whole["dv01"] - p1["dv01"]) < 1.0:
        raise AssertionError("the stub rows contributed nothing - they were ignored")


@case("L17-10", "column order does not matter when the sheet names its columns")
def t_10():
    reordered = ["명목 금액\t이자교환일\t만기일(불포함)\t시작일(포함)\t회차"]
    for i, (f, s, e, p, d, n) in enumerate(PHASE1, 1):
        reordered.append(f"{n:,}\t{p}\t{e}\t{s}\t{i}")
    periods = parse("\n".join(reordered))
    if len(periods) != 18:
        raise AssertionError(f"parsed {len(periods)} of 18 reordered rows")
    if round(periods[0]["notional"]) != 2500000000:
        raise AssertionError(f"notional {periods[0]['notional']:,.0f} after reordering")
    if periods[0]["start_date"] != "2026-09-18":
        raise AssertionError(f"start {periods[0]['start_date']} after reordering")


@case("L17-11", "a headerless block still reads the way it always did")
def t_11():
    plain = "\n".join(f"{s}\t{e}\t{p}\t{n}" for f, s, e, p, d, n in PHASE1)
    periods = parse(plain)
    if len(periods) != 18:
        raise AssertionError(f"positional parsing regressed: {len(periods)} of 18")
    if round(periods[0]["notional"]) != 2500000000:
        raise AssertionError(f"positional notional wrong: {periods[0]['notional']:,.0f}")


@case("L17-12", "rows that are not periods are skipped, not guessed at")
def t_12():
    text = whole_sheet().replace(
        "1\t2026-09-17", "합계\t\t\t\t\t\t2,500,000,000\t\n1\t2026-09-17", 1)
    periods = parse(text)
    if len(periods) != 24:
        raise AssertionError(f"a subtotal row became a period: {len(periods)}")


if __name__ == "__main__":
    print("\n=== L17 Stub periods in an amortising schedule ===")
    sys.exit(1 if run_all("L17") else 0)
