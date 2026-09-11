"""
L11 - end-to-end termsheet scenarios on synthetic sample documents.

What is genuinely exercised here: PDF parsing, redaction, enum normalisation, quote
verification, semantic checks, ticket mapping, and pricing the result through the live
pricing endpoints. The model call itself is stubbed - accuracy of the extractor against
real termsheets needs an API key and real samples, and is not claimed by these tests.
"""
import sys
from harness import case, approx, run_all

from fastapi.testclient import TestClient
import server.termsheet as tsmod
from server.app import app
from server.termsheet import (
    extract_text, redact, redaction_leaks, process_termsheet,
    ExtractedTrade, Provenance, SchedulePeriod,
)
from sample_termsheets import pdf, SAMPLES, SECRETS, MUST_KEEP
from test_l2_pricing import freeze_market

freeze_market()
client = TestClient(app)


# ---------------------------------------------------------------- redaction
@case("L11-1", "identity is stripped from every sample, in any casing")
def t_1():
    for key in SAMPLES:
        text = extract_text(pdf(key))
        out, counts = redact(text)
        lowered = out.lower()
        for secret in SECRETS[key]:
            # Case-insensitive: letterheads repeat the name in upper case.
            if secret.lower() in lowered:
                raise AssertionError(f"{key}: identity survived redaction - {secret!r}")
        if not counts:
            raise AssertionError(f"{key}: nothing was redacted at all")


@case("L11-2", "no pricing term is lost to redaction in any sample")
def t_2():
    for key in SAMPLES:
        out, _ = redact(extract_text(pdf(key)))
        for keep in MUST_KEEP[key]:
            if keep not in out:
                raise AssertionError(f"{key}: redaction destroyed {keep!r}")


@case("L11-3", "scattered identity (headers, signature blocks, inline) is caught")
def t_3():
    out, counts = redact(extract_text(pdf("TS-E")))
    leaks = redaction_leaks(out)
    if leaks:
        raise AssertionError(f"TS-E leaks after redaction: {leaks}")
    if sum(counts.values()) < 8:
        raise AssertionError(f"TS-E: only {sum(counts.values())} redactions on a document "
                             f"carrying identity in 10+ places: {counts}")


@case("L11-4", "redaction report tells the trader how much was removed")
def t_4():
    for key in SAMPLES:
        _, counts = redact(extract_text(pdf(key)))
        total = sum(counts.values())
        if total < len(SECRETS[key]):
            raise AssertionError(
                f"{key}: {total} redactions for {len(SECRETS[key])} known secrets: {counts}")
        if "party" not in counts and "name" not in counts:
            raise AssertionError(f"{key}: no identity category reported: {counts}")


# ---------------------------------------------------------------- stubs
def _stub(key):
    """Stand in for the model: what a correct extraction of each sample looks like."""
    def make(_text):
        if key == "TS-A":
            return ExtractedTrade(
                supported=True, currency="KRW", position="Rec Fixed", notional=5e10,
                effective_date="2026-09-15", maturity_date="2031-09-15",
                fixed_coupon_pct=2.72, tenor="5Y",
                leg1_day_count="Act/365 Fixed", leg1_payment_freq="Quarterly",
                leg1_business_day_conv="Modified Following", leg1_adjust_rule="Adjusted",
                leg1_calendar="SEB", leg2_day_count="Act/365 Fixed",
                leg2_payment_freq="Quarterly", leg2_calendar="SEB",
                provenance=[
                    Provenance(field="notional", source="extracted",
                               quote="Notional Amount:                 KRW 50,000,000,000"),
                    Provenance(field="fixed_coupon_pct", source="extracted",
                               quote="Fixed Rate:                      2.7200 per cent per annum"),
                    Provenance(field="leg1_day_count", source="extracted",
                               quote="Fixed Rate Day Count Fraction:   Act/365 Fixed"),
                    Provenance(field="leg1_business_day_conv", source="extracted",
                               quote="Business Day Convention:         Modified Following"),
                ],
                open_questions=[])
        if key == "TS-B":
            rows = [("2026-09-15", "2027-09-15", 1e8), ("2027-09-15", "2028-09-15", 8e7),
                    ("2028-09-15", "2029-09-15", 6e7), ("2029-09-15", "2030-09-15", 4e7),
                    ("2030-09-15", "2031-09-15", 2e7)]
            return ExtractedTrade(
                supported=True, currency="USD", position="Pay Fixed", notional=1e8,
                effective_date="2026-09-15", maturity_date="2031-09-15",
                fixed_coupon_pct=3.65, tenor="5Y",
                leg1_day_count="Act/360", leg1_payment_freq="Annual",
                leg1_business_day_conv="Modified Following", leg1_calendar="NYB",
                leg2_day_count="Act/360", leg2_payment_freq="Annual", leg2_calendar="NYB",
                payment_lag_bd=2,
                leg1_custom_schedule=[SchedulePeriod(start_date=a, end_date=b, notional=n)
                                      for a, b, n in rows],
                provenance=[
                    Provenance(field="fixed_coupon_pct", source="extracted",
                               quote="Fixed Rate:                 3.6500%"),
                    Provenance(field="leg1_day_count", source="extracted",
                               quote="Day Count:                  Act/360"),
                ],
                open_questions=["Confirm the SOFR observation shift"])
        if key == "TS-C":
            return ExtractedTrade(
                supported=True, currency="KRW_CRS", position="Pay Fixed",
                usd_notional=1e7, krw_notional=1.3755e10, spot_fx=1375.50,
                effective_date="2026-09-15", maturity_date="2031-09-15",
                fixed_coupon_pct=1.08, tenor="5Y", crs_swap_type="Vanilla",
                payment_lag_bd=2,
                leg1_day_count="30/360", leg1_payment_freq="Semi-annual",
                leg1_calendar="SEB_NYB", leg1_business_day_conv="Modified Following",
                leg2_day_count="Act/360", leg2_payment_freq="Semi-annual",
                leg2_calendar="SEB_NYB",
                provenance=[
                    Provenance(field="spot_fx", source="extracted",
                               quote="Spot FX Rate (USD/KRW):     1,375.50"),
                    Provenance(field="fixed_coupon_pct", source="extracted",
                               quote="Fixed Rate:                 1.0800 per cent per annum"),
                ],
                open_questions=[])
        if key == "TS-D":
            return ExtractedTrade(
                supported=False,
                unsupported_reason="Bermudan issuer call - optionality is not priced here")
        if key == "TS-E":
            return ExtractedTrade(
                supported=True, currency="KRW", position="Pay Fixed", notional=2e10,
                effective_date="2026-09-15", maturity_date="2029-09-15",
                fixed_coupon_pct=2.61, tenor="3Y",
                leg1_day_count="Act/365 Fixed", leg1_payment_freq="Quarterly",
                leg1_business_day_conv="Modified Following", leg1_calendar="SEB",
                provenance=[
                    Provenance(field="fixed_coupon_pct", source="extracted",
                               quote="Fixed Rate:                 2.6100 per cent per annum"),
                    # Deliberately fabricated: this line is not in the document.
                    Provenance(field="leg2_calendar", source="extracted",
                               quote="Floating Business Centres: Tokyo"),
                ],
                open_questions=["Confirm the floating leg business centres"])
        raise KeyError(key)
    return make


def run(key):
    return process_termsheet(pdf(key), extractor=_stub(key))


# ---------------------------------------------------------------- scenarios
@case("L11-5", "TS-A vanilla KRW IRS maps to a KRW ticket with normalised conventions")
def t_5():
    r = run("TS-A")
    d = r["ticket_draft"]
    if d["product"] != "KRW":
        raise AssertionError(f"product={d['product']}")
    if d["leg1DayCount"] != "Act/365":
        raise AssertionError(f"'Act/365 Fixed' not normalised: {d['leg1DayCount']}")
    if d["leg1PaymentFreq"] != "3M":
        raise AssertionError(f"'Quarterly' not normalised: {d['leg1PaymentFreq']}")
    if d["leg1Adjust"] != "Adjust":
        raise AssertionError(f"'Adjusted' not normalised: {d['leg1Adjust']}")
    if d["notionalDisplay"] != "50,000,000,000":
        raise AssertionError(f"notional={d['notionalDisplay']}")
    if r["unverified_fields"]:
        raise AssertionError(f"clean document reported unverified: {r['unverified_fields']}")


@case("L11-6", "TS-B amortising schedule reaches the rollercoaster parser")
def t_6():
    r = run("TS-B")
    paste = r["ticket_draft"].get("rawPasteText", "")
    lines = [l for l in paste.splitlines() if l.strip()]
    if len(lines) != 5:
        raise AssertionError(f"expected 5 periods, got {len(lines)}: {paste!r}")
    parsed = client.post("/api/rollercoaster/parse-paste", json={
        "raw_paste_text": paste, "currency": "USD", "effective_date": "2026-09-15",
    }).json()
    got = [p["notional"] for p in parsed["data"]]
    if got != [1e8, 8e7, 6e7, 4e7, 2e7]:
        raise AssertionError(f"amortisation lost in translation: {got}")


@case("L11-7", "TS-C CRS carries both notionals and the spot rate")
def t_7():
    d = run("TS-C")["ticket_draft"]
    if d["product"] != "KRW_CRS":
        raise AssertionError(f"product={d['product']}")
    if d.get("capitalFxRate") != "1,376":
        raise AssertionError(f"spot not carried: {d.get('capitalFxRate')}")
    if d.get("krwNotionalDisplay") != "13,755,000,000":
        raise AssertionError(f"KRW notional not carried: {d.get('krwNotionalDisplay')}")
    if d["leg1DayCount"] != "30/360" or d["leg1PaymentFreq"] != "6M":
        raise AssertionError(f"CRS leg1 conventions wrong: {d['leg1DayCount']} {d['leg1PaymentFreq']}")


@case("L11-8", "TS-D callable structure is refused, no ticket is built")
def t_8():
    r = run("TS-D")
    if r["supported"]:
        raise AssertionError("callable swap was accepted")
    if "ticket_draft" in r:
        raise AssertionError("a ticket was built for an unsupported product")
    if "call" not in r["unsupported_reason"].lower():
        raise AssertionError(f"reason unclear: {r['unsupported_reason']}")


@case("L11-9", "TS-E fabricated citation is caught and blocks confirmation")
def t_9():
    r = run("TS-E")
    if "leg2_calendar" not in r["unverified_fields"]:
        raise AssertionError(f"fabricated quote not caught: {r['unverified_fields']}")
    if not any("근거" in w for w in r["warnings"]):
        raise AssertionError(f"no warning raised: {r['warnings']}")


@case("L11-10", "absent conventions are flagged inferred, never silently defaulted")
def t_10():
    r = run("TS-B")
    inferred = set(r["inferred_fields"])
    if "leg1_stub_rule" not in inferred:
        raise AssertionError(f"stub rule not flagged as inferred: {sorted(inferred)}")
    if r["ticket_draft"]["leg1Stub"] != "Short in arrears":
        raise AssertionError("default stub not applied")


# ---------------------------------------------------------------- pricing
def _price(endpoint, draft, **extra):
    body = {
        "tenor": draft["customTenorInput"],
        "position": draft["position"],
        "effective_date": draft["effectiveDate"],
        "maturity_date": draft["maturityDate"],
        "leg1_day_count": draft["leg1DayCount"],
        "leg1_payment_freq": draft["leg1PaymentFreq"],
        "leg1_business_day_conv": draft["leg1Convention"],
        "leg1_stub_rule": draft["leg1Stub"],
        "leg1_adjust_rule": draft["leg1Adjust"],
        "leg1_calendar": draft["leg1PayCal"],
        "leg2_day_count": draft["leg2DayCount"],
        "leg2_payment_freq": draft["leg2PaymentFreq"],
        "leg2_calendar": draft["leg2Cal"],
    }
    if draft.get("coupon"):
        body["fixed_coupon_pct"] = float(draft["coupon"])
    body.update(extra)
    r = client.post(endpoint, json=body)
    if r.status_code != 200:
        raise AssertionError(f"{endpoint} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["data"]


@case("L11-11", "TS-A prices end to end through the KRW pricer")
def t_11():
    d = run("TS-A")["ticket_draft"]
    res = _price("/api/krw/price", d,
                 notional=float(d["notionalDisplay"].replace(",", "")))
    p = res["pricing_results"]
    if not (0.5 < p["par_swap_rate_pct"] < 10.0):
        raise AssertionError(f"implausible par: {p['par_swap_rate_pct']}")
    if p["dv01"] <= 0:
        raise AssertionError(f"non-positive DV01: {p['dv01']}")
    periods = len(res["schedules"]["leg1_fixed"])
    if periods != 20:
        raise AssertionError(f"5Y quarterly should be 20 periods, got {periods}")


@case("L11-12", "TS-B amortising trade prices with a lower DV01 than its bullet")
def t_12():
    d = run("TS-B")["ticket_draft"]
    bullet = _price("/api/price", d, notional=1e8)["pricing_results"]
    amort = _price("/api/price", d, notional=1e8,
                   raw_paste_text=d["rawPasteText"])["pricing_results"]
    if amort["dv01"] >= bullet["dv01"]:
        raise AssertionError(
            f"amortising DV01 {amort['dv01']:,.0f} not below bullet {bullet['dv01']:,.0f}")
    if amort["dv01"] <= 0:
        raise AssertionError("amortising DV01 must stay positive")


@case("L11-13", "TS-C CRS prices with principal exchange and KRW risk buckets")
def t_13():
    d = run("TS-C")["ticket_draft"]
    res = _price("/api/crs/price", d, usd_notional=1e7,
                 spot_fx=float(d["capitalFxRate"].replace(",", "")),
                 crs_swap_type="Vanilla")
    p = res["pricing_results"]
    if p.get("krw_dv01", 0) <= 0:
        raise AssertionError(f"no KRW DV01: {p.get('krw_dv01')}")
    flows = res.get("principal_flows") or {}
    if not flows.get("included"):
        raise AssertionError("principal exchange missing")
    krd = res.get("krw_key_rate_deltas") or []
    if not krd or abs(sum(x.get("dv01", 0) for x in krd)) < 1:
        raise AssertionError("CRS reported no KRW curve risk")


@case("L11-14", "coupon far from market is flagged by the par cross-check")
def t_14():
    d = run("TS-A")["ticket_draft"]
    notional = float(d["notionalDisplay"].replace(",", ""))
    par = _price("/api/krw/price", {**d, "coupon": ""},
                 notional=notional)["pricing_results"]["par_swap_rate_pct"]
    # A decimal slip: 2.72 read as 27.2
    slipped = _price("/api/krw/price", {**d, "coupon": "27.2000"},
                     notional=notional)["pricing_results"]
    gap_bp = abs(27.2 - par) * 100.0
    if gap_bp < 100.0:
        raise AssertionError(f"decimal slip only {gap_bp:.0f}bp from par - check would miss it")
    if slipped["deal_npv"] == 0:
        raise AssertionError("a far off-market coupon should not produce zero NPV")


@case("L11-15", "every sample survives the full upload endpoint")
def t_15():
    for key in SAMPLES:
        tsmod.call_extractor = _stub(key)
        r = client.post("/api/termsheet/extract",
                        files={"file": (f"{key}.pdf", pdf(key), "application/pdf")})
        if r.status_code != 200:
            raise AssertionError(f"{key} -> HTTP {r.status_code}: {r.text[:200]}")
        body = r.text
        for secret in SECRETS[key]:
            if secret in body:
                raise AssertionError(f"{key}: {secret!r} leaked through the endpoint")


if __name__ == "__main__":
    print("\n=== L11 Termsheet scenarios (sample documents) ===")
    sys.exit(1 if run_all("L11") else 0)
