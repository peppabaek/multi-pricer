# -*- coding: utf-8 -*-
"""
L16 File formats.

A marketer sends whatever they have: a PDF, the Excel they built the schedule in, a
Word draft, a photo of a signed page. All of it has to reach the pricer, and the one
path where identity cannot be stripped first has to say so.
"""
import sys, os, io
from harness import case, run_all

import server.termsheet as tsmod
from server.termsheet import (
    sniff_kind, extract_text, body_length, process_termsheet, vision_allowed,
    _mime_for,
)
from sample_formats import (
    BUILDERS, xlsx_bytes, docx_bytes, csv_bytes, html_bytes, png_bytes,
    scanned_pdf_bytes, as_text,
)
from test_l10_termsheet import _MINIMAL_PDF, _fake_trade

NAMES = {"xlsx": "ts.xlsx", "docx": "ts.docx", "csv": "ts.csv", "html": "ts.html",
         "txt": "ts.txt", "png": "ts.png", "scanpdf": "ts.pdf"}
NOTIONALS = ("100000000", "80000000", "60000000", "40000000", "20000000")


def _anything(arg, **_kw):
    """Stands in for the model on both paths: text in, or raw bytes in."""
    return _fake_trade("")


@case("L16-1", "each format is identified by its bytes, not its name")
def t_1():
    # Deliberately mislabelled: marketers rename attachments all the time.
    checks = [(xlsx_bytes(), "termsheet.pdf", "xlsx"),
              (docx_bytes(), "deal.txt", "docx"),
              (png_bytes(), "scan.pdf", "image"),
              (_MINIMAL_PDF, "sheet.xlsx", "pdf")]
    for raw, name, want in checks:
        got = sniff_kind(raw, name)
        if got != want:
            raise AssertionError(f"{name} read as {got!r}, expected {want!r}")


@case("L16-2", "every text-bearing format yields the terms")
def t_2():
    for key in ("xlsx", "docx", "csv", "html", "txt"):
        txt = extract_text(BUILDERS[key](), NAMES[key])
        for term in ("3.6500", "2026-09-15", "Act/360"):
            if term not in txt.replace("15-Sep-2026", "2026-09-15"):
                raise AssertionError(f"{key}: {term!r} did not survive extraction")


@case("L16-3", "every text-bearing format yields the amortising schedule")
def t_3():
    for key in ("xlsx", "docx", "csv", "html", "txt"):
        flat = extract_text(BUILDERS[key](), NAMES[key]).replace(",", "")
        missing = [n for n in NOTIONALS if n not in flat]
        if missing:
            raise AssertionError(f"{key}: lost notionals {missing}")


@case("L16-4", "an Excel schedule keeps its columns as tabs the paste parser reads")
def t_4():
    from common_pricer.rollercoaster_engine import parse_rollercoaster_paste
    import datetime
    txt = extract_text(xlsx_bytes(), "ts.xlsx")
    block = "\n".join(l for l in txt.splitlines() if l.startswith("2026-")
                      or l.startswith("2027-") or l.startswith("2028-")
                      or l.startswith("2029-") or l.startswith("2030-"))
    periods = parse_rollercoaster_paste(block, datetime.date(2026, 9, 15),
                                        default_notional=1e8)
    if len(periods) != 5:
        raise AssertionError(f"parsed {len(periods)} periods from the Excel block")
    if [int(p["notional"]) for p in periods] != [int(n) for n in NOTIONALS]:
        raise AssertionError(f"notionals wrong: {[p['notional'] for p in periods]}")


@case("L16-5", "an image and an image-only PDF have no text and take the vision path")
def t_5():
    for raw, name in ((png_bytes(), "ts.png"), (scanned_pdf_bytes(), "ts.pdf")):
        if body_length(extract_text(raw, name)) >= 40:
            raise AssertionError(f"{name}: an image was treated as readable text")


@case("L16-6", "the vision path is declared, and the redacted path is not confused with it")
def t_6():
    img = process_termsheet(png_bytes(), extractor=_anything, filename="ts.png")
    src = img.get("source") or {}
    if not src.get("by_vision") or src.get("redacted"):
        raise AssertionError(f"image path not declared: {src}")
    if not any("민감정보를 제거하지 못하고" in w for w in img["warnings"]):
        raise AssertionError(f"unredacted send left unsaid: {img['warnings']}")

    xls = process_termsheet(xlsx_bytes(), extractor=_anything, filename="ts.xlsx")
    src2 = xls.get("source") or {}
    if src2.get("by_vision") or not src2.get("redacted"):
        raise AssertionError(f"text path mislabelled: {src2}")
    if any("민감정보를 제거하지 못하고" in w for w in xls["warnings"]):
        raise AssertionError("a redacted read claimed it was not redacted")


@case("L16-7", "redaction still runs on the formats that have words in them")
def t_7():
    body = as_text().replace("TERM SHEET", "Counterparty: Acme Capital Markets Ltd\nTERM SHEET")
    res = process_termsheet(body.encode("utf-8"), extractor=_anything, filename="ts.txt")
    counts = (res.get("redaction") or {}).get("counts") or {}
    if not sum(counts.values()):
        raise AssertionError(f"counterparty survived a text upload: {counts}")


@case("L16-8", "a desk that cannot send images can turn the path off")
def t_8():
    saved = os.environ.get("TERMSHEET_ALLOW_IMAGE")
    os.environ["TERMSHEET_ALLOW_IMAGE"] = "0"
    try:
        if vision_allowed():
            raise AssertionError("the switch did not take")
        try:
            process_termsheet(png_bytes(), extractor=_anything, filename="ts.png")
        except ValueError as e:
            if "TERMSHEET_ALLOW_IMAGE" not in str(e):
                raise AssertionError(f"error does not say how to change it: {e}")
        else:
            raise AssertionError("an image was sent although the path was off")
    finally:
        if saved is None:
            os.environ.pop("TERMSHEET_ALLOW_IMAGE", None)
        else:
            os.environ["TERMSHEET_ALLOW_IMAGE"] = saved


@case("L16-9", "a format this machine cannot read says what to do instead")
def t_9():
    legacy = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
    try:
        extract_text(legacy, "old.xls")
    except ValueError as e:
        if ".xlsx" not in str(e):
            raise AssertionError(f"no way forward offered: {e}")
    else:
        raise AssertionError("a legacy .xls was accepted silently")


@case("L16-10", "the mime type sent with a file matches what it is")
def t_10():
    pairs = [(png_bytes(), "ts.png", "image/png"),
             (scanned_pdf_bytes(), "ts.pdf", "application/pdf"),
             (png_bytes(), "photo.jpg", "image/png")]   # bytes win over the name
    for raw, name, want in pairs:
        got = _mime_for(raw, name)
        if got != want:
            raise AssertionError(f"{name}: sent as {got!r}, expected {want!r}")


@case("L16-11", "the upload endpoint takes every format, not just PDF")
def t_11():
    from fastapi.testclient import TestClient
    from server.app import app
    saved = tsmod.call_extractor
    tsmod.call_extractor = _anything
    try:
        client = TestClient(app)
        for key in ("xlsx", "docx", "csv", "html", "txt"):
            r = client.post("/api/termsheet/extract",
                            files={"file": (NAMES[key], BUILDERS[key](),
                                            "application/octet-stream")})
            if r.status_code != 200:
                raise AssertionError(f"{key}: HTTP {r.status_code} {r.text[:200]}")
            if not r.json()["data"].get("supported"):
                raise AssertionError(f"{key}: not supported")
    finally:
        tsmod.call_extractor = saved


@case("L16-12", "an unreadable file is a client error with an explanation")
def t_12():
    from fastapi.testclient import TestClient
    from server.app import app
    saved = tsmod.call_extractor
    # Stubbed so that a junk upload reaching the model would show up as a failure here
    # rather than as a silent live call.
    tsmod.call_extractor = _anything
    try:
        client = TestClient(app)
        r = client.post("/api/termsheet/extract",
                        files={"file": ("junk.bin", b"\x00\x01\x02" * 50,
                                        "application/octet-stream")})
    finally:
        tsmod.call_extractor = saved
    if r.status_code // 100 != 4:
        raise AssertionError(f"expected a 4xx, got {r.status_code}: {r.text[:200]}")
    if "형식" not in r.json().get("detail", ""):
        raise AssertionError(f"no guidance in the error: {r.json()}")


if __name__ == "__main__":
    print("\n=== L16 File formats ===")
    sys.exit(1 if run_all("L16") else 0)
