"""L10 endpoint - upload contract and on-disk hygiene, with the model call stubbed out."""
import sys, os
from harness import case, run_all

from fastapi.testclient import TestClient
from starlette.formparsers import MultiPartParser
import server.termsheet as tsmod
from server.app import app
from test_l10_termsheet import _MINIMAL_PDF, _fake_trade

client = TestClient(app)

# Stub the model call: this exercises the endpoint, not the extractor.
tsmod.call_extractor = _fake_trade


def upload(blob, name="termsheet.pdf", ctype="application/pdf"):
    return client.post("/api/termsheet/extract",
                       files={"file": (name, blob, ctype)})


@case("L10-E1", "a termsheet upload returns a reviewable ticket draft")
def t_e1():
    r = upload(_MINIMAL_PDF)
    if r.status_code != 200:
        raise AssertionError(f"HTTP {r.status_code}: {r.text[:300]}")
    d = r.json()["data"]
    for key in ("ticket_draft", "provenance", "warnings", "redaction",
                "inferred_fields", "unverified_fields", "doc_sha256"):
        if key not in d:
            raise AssertionError(f"response missing '{key}'")
    if d["ticket_draft"]["product"] != "KRW":
        raise AssertionError(f"wrong product: {d['ticket_draft']['product']}")


@case("L10-E2", "the response carries no counterparty identity")
def t_e2():
    body = upload(_MINIMAL_PDF).text
    for secret in ("Hanmi", "Woori Bank", "9845009F7B2CD1A3E704",
                   "jane.park", "1002-455-778901", "TRD-2026-00815"):
        if secret in body:
            raise AssertionError(f"identity leaked into the response: {secret!r}")


@case("L10-E3", "non-PDF and empty uploads are refused")
def t_e3():
    r = upload(b"hello", name="notes.txt", ctype="text/plain")
    if r.status_code != 400:
        raise AssertionError(f"txt upload -> HTTP {r.status_code}")
    r = upload(b"", name="empty.pdf")
    if r.status_code != 400:
        raise AssertionError(f"empty upload -> HTTP {r.status_code}")


@case("L10-E4", "a corrupt PDF fails as a client error, not a 500")
def t_e4():
    r = upload(b"%PDF-1.4\nnot really a pdf at all")
    if r.status_code >= 500:
        raise AssertionError(f"corrupt PDF -> HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        raise AssertionError("corrupt PDF was accepted")


@case("L10-E5", "the upload never spills to a disk temp file")
def t_e5():
    if MultiPartParser.spool_max_size < 16 * 1024 * 1024:
        raise AssertionError(
            f"spool_max_size is {MultiPartParser.spool_max_size:,} - a large "
            f"termsheet would be written to disk")

    seen = {}
    original = tsmod.process_termsheet

    def _spy(raw, extractor=None):
        import inspect
        frame = inspect.currentframe().f_back
        while frame and "file" not in frame.f_locals:
            frame = frame.f_back
        up = frame.f_locals.get("file") if frame else None
        inner = getattr(up, "file", None)
        seen["rolled"] = getattr(inner, "_rolled", None)
        seen["path"] = getattr(getattr(inner, "_file", None), "name", None)
        return original(raw, extractor=_fake_trade)

    tsmod.process_termsheet = _spy
    try:
        big = _MINIMAL_PDF + b"\n%" + b"padding " * 700_000   # ~5.6 MB
        r = client.post("/api/termsheet/extract",
                        files={"file": ("big.pdf", big, "application/pdf")})
    finally:
        tsmod.process_termsheet = original

    if seen.get("rolled"):
        raise AssertionError(f"upload spilled to disk: {seen.get('path')}")
    if r.status_code >= 500:
        raise AssertionError(f"large upload -> HTTP {r.status_code}")


@case("L10-E6", "oversized uploads are rejected with a clear limit")
def t_e6():
    huge = _MINIMAL_PDF + b"\n%" + b"x" * (21 * 1024 * 1024)
    r = upload(huge, name="huge.pdf")
    if r.status_code != 400:
        raise AssertionError(f"21MB upload -> HTTP {r.status_code}")
    if "20MB" not in r.json().get("detail", ""):
        raise AssertionError(f"limit not stated: {r.json().get('detail')}")


@case("L10-E7", "extracted terms price through the existing pricing endpoint")
def t_e7():
    draft = upload(_MINIMAL_PDF).json()["data"]["ticket_draft"]
    body = {
        "tenor": draft["customTenorInput"],
        "notional": float(draft["notionalDisplay"].replace(",", "")),
        "position": draft["position"],
        "effective_date": draft["effectiveDate"],
        "maturity_date": draft["maturityDate"],
        "fixed_coupon_pct": float(draft["coupon"]),
        "leg1_day_count": draft["leg1DayCount"],
        "leg1_payment_freq": draft["leg1PaymentFreq"],
        "leg1_business_day_conv": draft["leg1Convention"],
        "leg1_calendar": draft["leg1PayCal"],
    }
    r = client.post("/api/krw/price", json=body)
    if r.status_code != 200:
        raise AssertionError(f"pricing the extracted trade -> HTTP {r.status_code}: {r.text[:300]}")
    res = r.json()["data"]["pricing_results"]
    if not (0.0 < res["par_swap_rate_pct"] < 20.0):
        raise AssertionError(f"implausible par: {res['par_swap_rate_pct']}")
    if res["dv01"] <= 0:
        raise AssertionError(f"non-positive DV01: {res['dv01']}")


if __name__ == "__main__":
    print("\n=== L10 Termsheet endpoint ===")
    sys.exit(1 if run_all("L10-E") else 0)
