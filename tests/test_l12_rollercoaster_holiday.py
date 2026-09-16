"""
L12 - term sheets whose terms move over the life of the trade, plus holiday handling.

Covers the three ways a real term sheet departs from a bullet swap - notional steps,
irregular dates, coupon steps - and every combination of them, end to end from PDF
through extraction to a priced schedule.
"""
import sys, datetime
from harness import case, approx, run_all

from fastapi.testclient import TestClient
import server.termsheet as tsmod
from server.app import app
from server.termsheet import process_termsheet, ExtractedTrade, SchedulePeriod, Provenance
from sample_termsheets import build_pdf
from test_l2_pricing import freeze_market

freeze_market()
client = TestClient(app)


# ---------------------------------------------------------------- documents
def _ts(title, rows_header, rows, extra=""):
    return f"""TERM SHEET - {title}

Counterparty: Meridian Capital Partners
Trade ID: MCP-2026-{abs(hash(title)) % 9000 + 1000}

Trade Date:                 11 September 2026
Effective Date:             15 September 2026
Termination Date:           15 September 2031
Currency:                   KRW
Floating Rate Option:       KRW-CD-91D
Day Count:                  Act/365 Fixed
Payment Frequency:          Quarterly
Business Day Convention:    Modified Following
Business Centres:           Seoul
{extra}
SCHEDULE
{rows_header}
{rows}
"""


AMORT = _ts("AMORTISING KRW IRS",
            "Period  From          To            Notional (KRW)      Rate",
            "\n".join(f"{i+1:<7} {a}   {b}   {n:>14,}      2.7200"
                      for i, (a, b, n) in enumerate([
                          ("2026-09-15", "2027-09-15", 50_000_000_000),
                          ("2027-09-15", "2028-09-15", 40_000_000_000),
                          ("2028-09-15", "2029-09-15", 30_000_000_000),
                          ("2029-09-15", "2030-09-15", 20_000_000_000),
                          ("2030-09-15", "2031-09-15", 10_000_000_000)])))

STEPUP = _ts("STEP-UP COUPON KRW IRS",
             "Period  From          To            Notional (KRW)      Rate",
             "\n".join(f"{i+1:<7} {a}   {b}   50,000,000,000      {r:.4f}"
                       for i, (a, b, r) in enumerate([
                           ("2026-09-15", "2027-09-15", 2.30),
                           ("2027-09-15", "2028-09-15", 2.55),
                           ("2028-09-15", "2029-09-15", 2.80),
                           ("2029-09-15", "2030-09-15", 3.05),
                           ("2030-09-15", "2031-09-15", 3.30)])))

IRREGULAR = _ts("IRREGULAR SCHEDULE KRW IRS",
                "Period  From          To            Notional (KRW)      Rate",
                "\n".join(f"{i+1:<7} {a}   {b}   {n:>14,}      2.7200"
                          for i, (a, b, n) in enumerate([
                              ("2026-09-15", "2026-11-30", 50_000_000_000),
                              ("2026-11-30", "2027-04-17", 125_000_000_000),
                              ("2027-04-17", "2027-05-04", 8_000_000_000),
                              ("2027-05-04", "2029-12-31", 87_500_000_000),
                              ("2029-12-31", "2031-09-15", 20_000_000_000)])))

ALL_VARY = _ts("ROLLERCOASTER KRW IRS",
               "Period  From          To            Notional (KRW)      Rate",
               "\n".join(f"{i+1:<7} {a}   {b}   {n:>14,}      {r:.4f}"
                         for i, (a, b, n, r) in enumerate([
                             ("2026-09-15", "2026-12-14", 50_000_000_000, 2.10),
                             ("2026-12-14", "2027-07-31", 90_000_000_000, 2.45),
                             ("2027-07-31", "2028-02-29", 35_000_000_000, 2.90),
                             ("2028-02-29", "2030-05-15", 120_000_000_000, 3.15),
                             ("2030-05-15", "2031-09-15", 15_000_000_000, 2.60)])))


def _periods(rows):
    return [SchedulePeriod(start_date=a, end_date=b, notional=n, fixed_rate_pct=r)
            for a, b, n, r in rows]


def _stub(rows, coupon=2.72):
    def make(_text, **_kw):
        return ExtractedTrade(
            supported=True, currency="KRW", position="Pay Fixed",
            notional=rows[0][2], effective_date=rows[0][0], maturity_date=rows[-1][1],
            fixed_coupon_pct=coupon, tenor="5Y",
            leg1_day_count="Act/365 Fixed", leg1_payment_freq="Quarterly",
            leg1_business_day_conv="Modified Following", leg1_calendar="SEB",
            leg2_day_count="Act/365 Fixed", leg2_payment_freq="Quarterly",
            leg2_calendar="SEB",
            leg1_custom_schedule=_periods(rows),
            provenance=[Provenance(field="leg1_calendar", source="extracted",
                                   quote="Business Centres:           Seoul")],
            open_questions=[])
    return make


AMORT_ROWS = [("2026-09-15", "2027-09-15", 5e10, 2.72), ("2027-09-15", "2028-09-15", 4e10, 2.72),
              ("2028-09-15", "2029-09-15", 3e10, 2.72), ("2029-09-15", "2030-09-15", 2e10, 2.72),
              ("2030-09-15", "2031-09-15", 1e10, 2.72)]
STEPUP_ROWS = [("2026-09-15", "2027-09-15", 5e10, 2.30), ("2027-09-15", "2028-09-15", 5e10, 2.55),
               ("2028-09-15", "2029-09-15", 5e10, 2.80), ("2029-09-15", "2030-09-15", 5e10, 3.05),
               ("2030-09-15", "2031-09-15", 5e10, 3.30)]
IRREG_ROWS = [("2026-09-15", "2026-11-30", 5e10, 2.72), ("2026-11-30", "2027-04-17", 1.25e11, 2.72),
              ("2027-04-17", "2027-05-04", 8e9, 2.72), ("2027-05-04", "2029-12-31", 8.75e10, 2.72),
              ("2029-12-31", "2031-09-15", 2e10, 2.72)]
ALLVARY_ROWS = [("2026-09-15", "2026-12-14", 5e10, 2.10), ("2026-12-14", "2027-07-31", 9e10, 2.45),
                ("2027-07-31", "2028-02-29", 3.5e10, 2.90), ("2028-02-29", "2030-05-15", 1.2e11, 3.15),
                ("2030-05-15", "2031-09-15", 1.5e10, 2.60)]

CASES = {
    "amortising":  (AMORT, AMORT_ROWS),
    "step-up":     (STEPUP, STEPUP_ROWS),
    "irregular":   (IRREGULAR, IRREG_ROWS),
    "all-varying": (ALL_VARY, ALLVARY_ROWS),
}


def run_doc(name):
    doc, rows = CASES[name]
    tsmod.call_extractor = _stub(rows)
    r = client.post("/api/termsheet/extract",
                    files={"file": (f"{name}.pdf", build_pdf(doc), "application/pdf")})
    if r.status_code != 200:
        raise AssertionError(f"{name}: HTTP {r.status_code}: {r.text[:250]}")
    return r.json()["data"], rows


def price(draft, **extra):
    body = {
        "tenor": draft["customTenorInput"],
        "notional": float(str(draft["notionalDisplay"]).replace(",", "")),
        "position": draft["position"],
        "effective_date": draft["effectiveDate"],
        "maturity_date": draft["maturityDate"],
        "fixed_coupon_pct": float(draft["coupon"]) if draft.get("coupon") else None,
        "leg1_day_count": draft["leg1DayCount"],
        "leg1_payment_freq": draft["leg1PaymentFreq"],
        "leg1_business_day_conv": draft["leg1Convention"],
        "leg1_calendar": draft["leg1PayCal"],
        "leg2_day_count": draft["leg2DayCount"],
        "leg2_payment_freq": draft["leg2PaymentFreq"],
        "leg2_calendar": draft["leg2Cal"],
    }
    body.update(extra)
    resp = client.post("/api/krw/price", json=body)
    if resp.status_code != 200:
        raise AssertionError(f"pricing -> HTTP {resp.status_code}: {resp.text[:280]}")
    return resp.json()["data"]


# ---------------------------------------------------------------- schedule fidelity
@case("L12-1", "every varying-term document survives upload and yields a schedule")
def t_1():
    for name in CASES:
        data, rows = run_doc(name)
        paste = data["ticket_draft"].get("rawPasteText", "")
        got = [l for l in paste.splitlines() if l.strip()]
        if len(got) != len(rows):
            raise AssertionError(f"{name}: expected {len(rows)} periods, got {len(got)}")


@case("L12-2", "notional steps reach the pricer unchanged")
def t_2():
    data, rows = run_doc("amortising")
    res = price(data["ticket_draft"], raw_paste_text=data["ticket_draft"]["rawPasteText"])
    sched = res["schedules"]["leg1_fixed"]
    got = [round(p["notional"]) for p in sched]
    want = [round(n) for _, _, n, _ in rows]
    if got != want:
        raise AssertionError(f"notional steps lost: {got} != {want}")


@case("L12-3", "coupon steps are applied period by period")
def t_3():
    data, rows = run_doc("step-up")
    res = price(data["ticket_draft"], raw_paste_text=data["ticket_draft"]["rawPasteText"])
    got = [round(p["fixed_rate_pct"], 4) for p in res["schedules"]["leg1_fixed"]]
    want = [r for _, _, _, r in rows]
    if got != want:
        raise AssertionError(f"coupon steps lost: {got} != {want}")


@case("L12-4", "irregular period boundaries are preserved exactly")
def t_4():
    data, rows = run_doc("irregular")
    res = price(data["ticket_draft"], raw_paste_text=data["ticket_draft"]["rawPasteText"])
    sched = res["schedules"]["leg1_fixed"]
    for i, (a, b, _, _) in enumerate(rows):
        if sched[i]["start_date"] != a or sched[i]["end_date"] != b:
            raise AssertionError(
                f"period {i+1}: got {sched[i]['start_date']}..{sched[i]['end_date']} want {a}..{b}")


@case("L12-5", "notional, dates and rates all varying at once still prices")
def t_5():
    data, rows = run_doc("all-varying")
    res = price(data["ticket_draft"], raw_paste_text=data["ticket_draft"]["rawPasteText"])
    sched = res["schedules"]["leg1_fixed"]
    if len(sched) != len(rows):
        raise AssertionError(f"expected {len(rows)} periods, got {len(sched)}")
    for i, (a, b, n, r) in enumerate(rows):
        p = sched[i]
        if p["start_date"] != a or p["end_date"] != b:
            raise AssertionError(f"p{i+1} dates: {p['start_date']}..{p['end_date']} != {a}..{b}")
        approx(p["notional"], n, 1.0, f"p{i+1} notional")
        approx(p["fixed_rate_pct"], r, 1e-6, f"p{i+1} rate")
    pr = res["pricing_results"]
    if pr["dv01"] <= 0:
        raise AssertionError(f"non-positive DV01: {pr['dv01']}")


@case("L12-6", "cashflow equals notional x rate x accrual for every varying period")
def t_6():
    data, rows = run_doc("all-varying")
    res = price(data["ticket_draft"], raw_paste_text=data["ticket_draft"]["rawPasteText"])
    for p in res["schedules"]["leg1_fixed"]:
        expect = p["notional"] * (p["fixed_rate_pct"] / 100.0) * p["day_count_fraction"]
        # day_count_fraction is reported to 6dp, so recomputing from it carries up to
        # notional x rate x 5e-7 of rounding noise - the tolerance has to cover that.
        tol = p["notional"] * (p["fixed_rate_pct"] / 100.0) * 5e-7 + 1.0
        approx(p["cash_flow"], expect, tol, f"period {p['period_no']} cashflow")


@case("L12-7", "a leap-day boundary is carried through")
def t_7():
    data, _ = run_doc("all-varying")
    res = price(data["ticket_draft"], raw_paste_text=data["ticket_draft"]["rawPasteText"])
    ends = [p["end_date"] for p in res["schedules"]["leg1_fixed"]]
    if "2028-02-29" not in ends:
        raise AssertionError(f"leap-day period boundary lost: {ends}")


@case("L12-8", "risk scales with the notional profile, not just the headline")
def t_8():
    amort, rows = run_doc("amortising")
    draft = amort["ticket_draft"]
    bullet = price(draft)["pricing_results"]
    stepped = price(draft, raw_paste_text=draft["rawPasteText"])["pricing_results"]
    if stepped["dv01"] >= bullet["dv01"]:
        raise AssertionError(
            f"amortising DV01 {stepped['dv01']:,.0f} not below bullet {bullet['dv01']:,.0f}")


# ---------------------------------------------------------------- holidays
def _cal(code):
    r = client.get(f"/api/calendar/status")
    return r


@case("L12-9", "pay dates never land on a Seoul holiday or weekend")
def t_9():
    from server.calendar_manager import is_business_day
    data, _ = run_doc("all-varying")
    res = price(data["ticket_draft"], raw_paste_text=data["ticket_draft"]["rawPasteText"])
    bad = []
    for p in res["schedules"]["leg1_fixed"]:
        d = datetime.date.fromisoformat(p["pay_date"])
        if not is_business_day(d, "SEB"):
            bad.append(p["pay_date"])
    if bad:
        raise AssertionError(f"pay dates on non-business days: {bad}")


@case("L12-10", "a newly added holiday moves the affected pay date")
def t_10():
    from server.calendar_manager import is_business_day, add_holiday, get_calendar_holidays

    probe = client.post("/api/krw/price", json={
        "notional": 1e10, "effective_date": "2026-09-15", "maturity_date": "2027-09-15",
        "fixed_coupon_pct": 2.6, "leg1_payment_freq": "3M", "leg1_calendar": "SEB",
        "leg1_business_day_conv": "Modified Following",
    })
    if probe.status_code != 200:
        raise AssertionError(f"probe HTTP {probe.status_code}: {probe.text[:200]}")
    before = [p["pay_date"] for p in probe.json()["data"]["schedules"]["leg1_fixed"]]

    target = next((d for d in before if is_business_day(datetime.date.fromisoformat(d), "SEB")), None)
    if not target:
        raise AssertionError("no business-day pay date to test against")

    added = add_holiday("SEB", target, persist=False)
    if not added:
        raise AssertionError(f"could not register {target} as a SEB holiday")
    try:
        if is_business_day(datetime.date.fromisoformat(target), "SEB"):
            raise AssertionError(f"{target} still reads as a business day after add_holiday")

        after = client.post("/api/krw/price", json={
            "notional": 1e10, "effective_date": "2026-09-15", "maturity_date": "2027-09-15",
            "fixed_coupon_pct": 2.6, "leg1_payment_freq": "3M", "leg1_calendar": "SEB",
            "leg1_business_day_conv": "Modified Following",
        }).json()["data"]["schedules"]["leg1_fixed"]
        moved = [p["pay_date"] for p in after]
        if target in moved:
            raise AssertionError(f"{target} is now a holiday but is still a pay date")
    finally:
        hol = get_calendar_holidays("SEB")
        hol.discard(target)


@case("L12-11", "business day convention changes the rolled pay date")
def t_11():
    out = {}
    for conv in ("Modified Following", "Following", "Preceding"):
        r = client.post("/api/krw/price", json={
            "notional": 1e10, "effective_date": "2026-09-15", "maturity_date": "2028-09-15",
            "fixed_coupon_pct": 2.6, "leg1_payment_freq": "3M", "leg1_calendar": "SEB",
            "leg1_business_day_conv": conv,
        })
        if r.status_code != 200:
            raise AssertionError(f"{conv}: HTTP {r.status_code}")
        out[conv] = [p["pay_date"] for p in r.json()["data"]["schedules"]["leg1_fixed"]]
    if out["Following"] == out["Preceding"]:
        raise AssertionError("Following and Preceding produced identical pay dates")


@case("L12-12", "SEB and NYB calendars roll differently")
def t_12():
    got = {}
    for cal in ("SEB", "NYB"):
        r = client.post("/api/price", json={
            "notional": 1e8, "effective_date": "2026-09-15", "maturity_date": "2028-09-15",
            "fixed_coupon_pct": 4.0, "leg1_payment_freq": "3M", "leg1_calendar": cal,
        })
        if r.status_code != 200:
            raise AssertionError(f"{cal}: HTTP {r.status_code}: {r.text[:200]}")
        got[cal] = [p["pay_date"] for p in r.json()["data"]["schedules"]["leg1_fixed"]]
    if got["SEB"] == got["NYB"]:
        raise AssertionError("Seoul and New York calendars gave identical pay dates")


if __name__ == "__main__":
    print("\n=== L12 Varying-term term sheets + holidays ===")
    sys.exit(1 if run_all("L12") else 0)
