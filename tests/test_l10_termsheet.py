"""L10 - termsheet ingestion: redaction, verification, ticket mapping, upload hygiene."""
import io
from harness import case, approx, run_all

from server.termsheet import (
    redact, redaction_leaks, extract_text, normalize_enums, verify_quotes,
    check_schedule, check_dates, to_ticket_draft, process_termsheet,
    ExtractedTrade, Provenance, SchedulePeriod, REDACTED,
)

SAMPLE = """CONFIRMATION - INTEREST RATE SWAP

Counterparty: Hanmi Global Bank Ltd.
Party A: Woori Bank
LEI: 9845009F7B2CD1A3E704
Account Number: 1002-455-778901
Contact: Jane Park
Email: jane.park@hanmiglobal.co.kr
Tel: +82 2-3456-7890
Our Ref: TRD-2026-00815

ECONOMIC TERMS
Notional Amount: KRW 50,000,000,000
Trade Date: 2026-09-11
Effective Date: 2026-09-15
Termination Date: 2031-09-15
Fixed Rate: 2.7200 per cent per annum
Fixed Rate Day Count Fraction: Act/365 Fixed
Fixed Rate Payer Payment Dates: Quarterly
Floating Rate Option: KRW-CD-91D
Business Day Convention: Modified Following
Business Centers: Seoul
"""


# ---------------------------------------------------------------- redaction
@case("L10-1", "counterparty identity and reference identifiers are removed")
def t_1():
    out, counts = redact(SAMPLE)
    for secret in ("Hanmi Global Bank", "Woori Bank", "9845009F7B2CD1A3E704",
                   "1002-455-778901", "jane.park@hanmiglobal.co.kr",
                   "Jane Park", "TRD-2026-00815"):
        if secret in out:
            raise AssertionError(f"redaction missed: {secret!r}")
    if not counts:
        raise AssertionError("no redaction counts reported")


@case("L10-2", "every pricing-relevant term survives redaction")
def t_2():
    out, _ = redact(SAMPLE)
    for keep in ("50,000,000,000", "2026-09-15", "2031-09-15", "2.7200",
                 "Act/365 Fixed", "Quarterly", "Modified Following",
                 "KRW-CD-91D", "Seoul"):
        if keep not in out:
            raise AssertionError(f"redaction destroyed a pricing term: {keep!r}")


@case("L10-3", "re-scan of redacted text reports no leaks")
def t_3():
    out, _ = redact(SAMPLE)
    leaks = redaction_leaks(out)
    if leaks:
        raise AssertionError(f"leaks remain after redaction: {leaks}")


@case("L10-4", "redaction is idempotent")
def t_4():
    once, _ = redact(SAMPLE)
    twice, counts2 = redact(once)
    if twice != once:
        raise AssertionError("second redaction pass changed the text")


# ---------------------------------------------------------------- normalisation
@case("L10-5", "convention spellings map onto the pricer vocabulary")
def t_5():
    t = ExtractedTrade(
        supported=True,
        leg1_day_count="ACT/365F", leg2_day_count="30E/360",
        leg1_payment_freq="Quarterly", leg2_payment_freq="Semi-Annual",
        leg1_business_day_conv="MF", leg1_adjust_rule="Adjusted",
    )
    unmapped = normalize_enums(t)
    if unmapped:
        raise AssertionError(f"failed to map: {unmapped}")
    approx_eq = [
        (t.leg1_day_count, "Act/365"), (t.leg2_day_count, "30/360"),
        (t.leg1_payment_freq, "3M"), (t.leg2_payment_freq, "6M"),
        (t.leg1_business_day_conv, "Modified Following"), (t.leg1_adjust_rule, "Adjust"),
    ]
    for got, want in approx_eq:
        if got != want:
            raise AssertionError(f"{got!r} != {want!r}")


@case("L10-6", "unmappable convention is dropped, not guessed")
def t_6():
    t = ExtractedTrade(supported=True, leg1_day_count="Act/252 (Brazil)",
                       leg1_calendar="Sao Paulo")
    unmapped = normalize_enums(t)
    if "leg1_day_count" not in unmapped or "leg1_calendar" not in unmapped:
        raise AssertionError(f"expected both unmapped, got {unmapped}")
    if t.leg1_day_count is not None or t.leg1_calendar is not None:
        raise AssertionError("unmappable value was not cleared")


# ---------------------------------------------------------------- provenance
@case("L10-7", "fabricated citations are caught")
def t_7():
    doc = "Fixed Rate: 2.7200 per cent per annum\nDay Count: Act/365 Fixed"
    t = ExtractedTrade(supported=True, provenance=[
        Provenance(field="fixed_coupon_pct", source="extracted", quote="Fixed Rate: 2.7200"),
        Provenance(field="leg1_day_count", source="extracted", quote="Day Count: Act/360"),
        Provenance(field="leg1_calendar", source="inferred", quote=None),
    ])
    bad = verify_quotes(t, doc)
    if bad != ["leg1_day_count"]:
        raise AssertionError(f"expected only leg1_day_count unverified, got {bad}")


@case("L10-8", "quote matching tolerates whitespace and line wrapping")
def t_8():
    doc = "Fixed  Rate\n Day Count   Fraction: Act/365 Fixed"
    t = ExtractedTrade(supported=True, provenance=[
        Provenance(field="leg1_day_count", source="extracted",
                   quote="Day Count Fraction: Act/365 Fixed"),
    ])
    if verify_quotes(t, doc):
        raise AssertionError("whitespace difference wrongly flagged as fabricated")


# ---------------------------------------------------------------- semantics
@case("L10-9", "broken schedule continuity is reported")
def t_9():
    t = ExtractedTrade(supported=True, notional=100e6, maturity_date="2030-09-15",
                       leg1_custom_schedule=[
                           SchedulePeriod(start_date="2027-09-15", end_date="2028-09-15", notional=100e6),
                           SchedulePeriod(start_date="2028-12-15", end_date="2030-09-15", notional=60e6),
                       ])
    w = check_schedule(t)
    if not any("이어지지" in x for x in w):
        raise AssertionError(f"continuity gap not reported: {w}")


@case("L10-10", "notional and maturity mismatches are reported")
def t_10():
    t = ExtractedTrade(supported=True, notional=100e6, maturity_date="2031-09-15",
                       leg1_custom_schedule=[
                           SchedulePeriod(start_date="2027-09-15", end_date="2028-09-15", notional=80e6),
                           SchedulePeriod(start_date="2028-09-15", end_date="2030-09-15", notional=60e6),
                       ])
    w = check_schedule(t)
    if len(w) < 2:
        raise AssertionError(f"expected notional and maturity warnings, got {w}")


@case("L10-11", "inverted and malformed dates are reported")
def t_11():
    if not check_dates(ExtractedTrade(supported=True, effective_date="2030-01-15",
                                      maturity_date="2027-01-15")):
        raise AssertionError("inverted dates not reported")
    if not check_dates(ExtractedTrade(supported=True, effective_date="15/01/2030")):
        raise AssertionError("malformed date not reported")


# ---------------------------------------------------------------- ticket mapping
@case("L10-12", "extracted terms map onto the dashboard ticket shape")
def t_12():
    t = ExtractedTrade(
        supported=True, currency="KRW", position="Pay Fixed", notional=5e10,
        effective_date="2026-09-15", maturity_date="2031-09-15",
        fixed_coupon_pct=2.72, leg1_day_count="Act/365", leg1_payment_freq="3M",
        leg1_business_day_conv="Modified Following", leg1_calendar="SEB",
    )
    out = to_ticket_draft(t)
    d = out["draft"]
    if d["product"] != "KRW" or d["notionalDisplay"] != "50,000,000,000":
        raise AssertionError(f"bad mapping: {d['product']} / {d['notionalDisplay']}")
    if d["coupon"] != "2.7200" or d["effectiveDate"] != "2026-09-15":
        raise AssertionError(f"bad mapping: {d['coupon']} / {d['effectiveDate']}")
    if "leg1_day_count" in out["inferred_fields"]:
        raise AssertionError("an extracted field was marked inferred")


@case("L10-13", "absent conventions fall back to defaults and are flagged as inferred")
def t_13():
    t = ExtractedTrade(supported=True, currency="USD", notional=1e8)
    out = to_ticket_draft(t)
    if out["draft"]["leg1DayCount"] != "Act/360":
        raise AssertionError("USD default day count not applied")
    for expect in ("leg1_day_count", "leg1_payment_freq", "leg1_calendar", "position"):
        if expect not in out["inferred_fields"]:
            raise AssertionError(f"{expect} not flagged as inferred: {out['inferred_fields']}")


@case("L10-14", "amortising schedule becomes rollercoaster paste text")
def t_14():
    t = ExtractedTrade(supported=True, currency="USD", notional=1e8,
                       leg1_custom_schedule=[
                           SchedulePeriod(start_date="2027-09-13", end_date="2028-09-13",
                                          notional=1e8, fixed_rate_pct=4.1),
                           SchedulePeriod(start_date="2028-09-13", end_date="2029-09-13",
                                          notional=8e7, fixed_rate_pct=4.1),
                       ])
    paste = to_ticket_draft(t)["draft"].get("rawPasteText", "")
    lines = paste.strip().splitlines()
    if len(lines) != 2 or "100000000" not in lines[0] or "80000000" not in lines[1]:
        raise AssertionError(f"schedule not rendered for the paste parser: {paste!r}")


# ---------------------------------------------------------------- pipeline
def _fake_trade(_text, **_kw):   # **_kw: call_extractor also takes `used`
    return ExtractedTrade(
        supported=True, currency="KRW", position="Pay Fixed", notional=5e10,
        effective_date="2026-09-15", maturity_date="2031-09-15", fixed_coupon_pct=2.72,
        leg1_day_count="ACT/365F", leg1_payment_freq="Quarterly",
        leg1_business_day_conv="MF", leg1_calendar="SEB",
        provenance=[
            Provenance(field="fixed_coupon_pct", source="extracted",
                       quote="Fixed Rate: 2.7200 per cent per annum"),
            Provenance(field="notional", source="extracted",
                       quote="Notional Amount: KRW 50,000,000,000"),
            Provenance(field="leg2_calendar", source="extracted",
                       quote="Business Centers: Tokyo and London"),
        ],
        open_questions=["Confirm the fixing lag"],
    )


@case("L10-15", "pipeline redacts, normalises, verifies and maps in one pass")
def t_15():
    pdf = _MINIMAL_PDF
    res = process_termsheet(pdf, extractor=_fake_trade)
    if not res["supported"]:
        raise AssertionError("supported trade was rejected")
    if res["ticket_draft"]["leg1DayCount"] != "Act/365":
        raise AssertionError("enum normalisation did not run")
    if "leg2_calendar" not in res["unverified_fields"]:
        raise AssertionError(f"fabricated quote not caught: {res['unverified_fields']}")
    if not res["doc_sha256"] or len(res["doc_sha256"]) != 64:
        raise AssertionError("document hash missing")
    if res["open_questions"] != ["Confirm the fixing lag"]:
        raise AssertionError("open questions dropped")


@case("L10-15b", "demo fallback answers can never be confirmed or priced")
def t_15b():
    def _demo(_t):
        tr = _fake_trade(_t)
        tr.demo_fallback = True
        return tr
    res = process_termsheet(_MINIMAL_PDF, extractor=_demo)
    if not res.get("demo_fallback"):
        raise AssertionError("demo result not flagged")
    draft_keys = set(res["ticket_draft"].keys())
    if not draft_keys.issubset(set(res["unverified_fields"])):
        raise AssertionError(
            "demo result left confirmable fields: "
            f"{sorted(draft_keys - set(res['unverified_fields']))}")
    if not any("데모" in w for w in res["warnings"]):
        raise AssertionError(f"no demo warning surfaced: {res['warnings']}")


@case("L10-15c", "demo fallback is off unless explicitly enabled")
def t_15c():
    import os
    from server.termsheet import demo_mode_enabled
    saved = os.environ.pop("TERMSHEET_DEMO_MODE", None)
    try:
        if demo_mode_enabled():
            raise AssertionError("demo mode is on by default")
        os.environ["TERMSHEET_DEMO_MODE"] = "1"
        if not demo_mode_enabled():
            raise AssertionError("demo mode did not enable")
    finally:
        os.environ.pop("TERMSHEET_DEMO_MODE", None)
        if saved is not None:
            os.environ["TERMSHEET_DEMO_MODE"] = saved


@case("L10-16", "unsupported products are refused, not coerced")
def t_16():
    def _unsupported(_t):
        return ExtractedTrade(supported=False,
                              unsupported_reason="Callable swap - optionality not priced here")
    res = process_termsheet(_MINIMAL_PDF, extractor=_unsupported)
    if res["supported"]:
        raise AssertionError("callable structure was accepted")
    if "ticket_draft" in res:
        raise AssertionError("a ticket was built for an unsupported product")


# A tiny valid PDF whose page text carries the sample termsheet.
def _build_minimal_pdf(text: str) -> bytes:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    stream_parts = ["BT", "/F1 9 Tf", "12 TL", "40 780 Td"]
    for ln in lines:
        esc = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream_parts.append(f"({esc}) Tj T*")
    stream_parts.append("ET")
    content = "\n".join(stream_parts).encode("latin-1", "replace")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n"
            f"{xref_at}\n%%EOF\n").encode()
    return bytes(out)


_MINIMAL_PDF = _build_minimal_pdf(SAMPLE)


@case("L10-17", "PDF text extraction reads the document in memory")
def t_17():
    text = extract_text(_MINIMAL_PDF)
    if "Notional Amount" not in text or "2.7200" not in text:
        raise AssertionError(f"text extraction failed: {text[:200]!r}")


@case("L10-18", "a PDF with no extractable text is rejected clearly")
def t_18():
    blank = _build_minimal_pdf("   ")
    try:
        process_termsheet(blank, extractor=_fake_trade)
    except ValueError as e:
        if "텍스트" not in str(e):
            raise AssertionError(f"unexpected message: {e}")
        return
    raise AssertionError("blank PDF was accepted")


if __name__ == "__main__":
    import sys
    print("\n=== L10 Termsheet ingestion ===")
    sys.exit(1 if run_all("L10") else 0)
