# -*- coding: utf-8 -*-
"""
The same amortising term sheet in every format a marketer might send it in.

Built rather than checked in, so the fixtures cannot drift from the sample the rest
of the suite uses, and so no real counterparty document sits in the repository.
"""
import io, zipfile

TERMS = [
    ("Trade Type", "Interest Rate Swap"),
    ("Currency", "USD"),
    ("Notional Amount", "USD 100,000,000"),
    ("Effective Date", "15-Sep-2026"),
    ("Maturity Date", "15-Sep-2031"),
    ("Fixed Rate", "3.6500%"),
    ("Fixed Day Count", "Act/360"),
    ("Fixed Payment Frequency", "Annual"),
    ("Floating Index", "USD SOFR (Compounded)"),
    ("Floating Spread", "0 bp"),
    ("Business Day Convention", "Modified Following"),
    ("Business Centres", "New York"),
    ("Client pays", "Fixed"),
]

SCHEDULE = [
    ("2026-09-15", "2027-09-15", "100,000,000"),
    ("2027-09-15", "2028-09-15", "80,000,000"),
    ("2028-09-15", "2029-09-15", "60,000,000"),
    ("2029-09-15", "2030-09-15", "40,000,000"),
    ("2030-09-15", "2031-09-15", "20,000,000"),
]


def as_text() -> str:
    lines = ["TERM SHEET - Amortising Interest Rate Swap", ""]
    lines += [f"{k}: {v}" for k, v in TERMS]
    lines += ["", "Amortisation Schedule", "Start Date\tEnd Date\tNotional"]
    lines += ["\t".join(r) for r in SCHEDULE]
    return "\n".join(lines)


def csv_bytes() -> bytes:
    rows = [f"{k},{v}" for k, v in TERMS]
    rows += ["", "Start Date,End Date,Notional"]
    rows += [",".join(r).replace(",", "") if False else
             f"{a},{b},{n.replace(',', '')}" for a, b, n in SCHEDULE]
    return ("\n".join(rows)).encode("utf-8")


def xlsx_bytes() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Term Sheet"
    ws.append(["TERM SHEET - Amortising Interest Rate Swap"])
    ws.append([])
    for k, v in TERMS:
        ws.append([k, v])

    sh = wb.create_sheet("Schedule")
    sh.append(["Start Date", "End Date", "Notional"])
    for a, b, n in SCHEDULE:
        sh.append([a, b, float(n.replace(",", ""))])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def docx_bytes() -> bytes:
    """A minimal but genuine .docx: paragraphs plus a table of the schedule."""
    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def para(text):
        return f"<w:p><w:r><w:t xml:space='preserve'>{esc(text)}</w:t></w:r></w:p>"

    def cell(text):
        return f"<w:tc><w:tcPr/>{para(text)}</w:tc>"

    rows = "".join("<w:tr>" + "".join(cell(c) for c in r) + "</w:tr>"
                   for r in [("Start Date", "End Date", "Notional")] + SCHEDULE)
    body = (para("TERM SHEET - Amortising Interest Rate Swap")
            + "".join(para(f"{k}: {v}") for k, v in TERMS)
            + para("Amortisation Schedule")
            + f"<w:tbl><w:tblPr/>{rows}</w:tbl>")

    doc = ("<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
           "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
           f"<w:body>{body}</w:body></w:document>")
    ctypes = ("<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
              "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
              "<Default Extension='rels' ContentType="
              "'application/vnd.openxmlformats-package.relationships+xml'/>"
              "<Default Extension='xml' ContentType='application/xml'/>"
              "<Override PartName='/word/document.xml' ContentType="
              "'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>"
              "</Types>")
    rels = ("<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
            "<Relationships xmlns="
            "'http://schemas.openxmlformats.org/package/2006/relationships'>"
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/"
            "officeDocument/2006/relationships/officeDocument' Target='word/document.xml'/>"
            "</Relationships>")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def html_bytes() -> bytes:
    rows = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{n}</td></tr>" for a, b, n in SCHEDULE)
    terms = "".join(f"<p>{k}: {v}</p>" for k, v in TERMS)
    return (f"<html><head><style>p{{margin:0}}</style>"
            f"<script>var x=1;</script></head><body>"
            f"<h1>TERM SHEET - Amortising Interest Rate Swap</h1>{terms}"
            f"<table><tr><th>Start Date</th><th>End Date</th><th>Notional</th></tr>"
            f"{rows}</table></body></html>").encode("utf-8")


def hwpx_bytes() -> bytes:
    """
    A Hangul Word Processor document, the .hwpx (zip of XML) save.

    Korean desks draft term sheets in HWP, so this is what actually lands in the
    upload box - and the labels come in Korean, which is the point of the fixture.
    """
    NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    KO = [("거래종류", "이자율스왑"), ("통화", "USD"),
          ("명목금액", "USD 100,000,000"),
          ("개시일", "2026-09-15"), ("만기일", "2031-09-15"),
          ("고정금리", "3.6500%"), ("이자계산", "Act/360"),
          ("지급주기", "연 1회"), ("변동지표", "USD SOFR (Compounded)"),
          ("영업일규칙", "Modified Following"), ("영업지역", "New York"),
          ("고객 지급", "고정금리")]

    def para(text):
        text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"

    lines = [para("거래확인서 - 상각형 이자율스왑")]
    lines += [para(f"{k}: {v}") for k, v in KO]
    lines.append(para("상각 스케줄"))
    lines.append(para("시작일\t만기일\t명목금액"))
    lines += [para(f"{a}\t{b}\t{n}") for a, b, n in SCHEDULE]

    xml = (f"<?xml version='1.0' encoding='UTF-8'?>"
           f"<hp:sec xmlns:hp='{NS}'>{''.join(lines)}</hp:sec>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", xml)
    return buf.getvalue()


def png_bytes(width=1400, height=900) -> bytes:
    """The term sheet rendered as a picture - the scan / phone-photo case."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    y = 24
    d.text((24, y), "TERM SHEET - Amortising Interest Rate Swap", fill="black")
    y += 28
    for k, v in TERMS:
        d.text((24, y), f"{k}: {v}", fill="black")
        y += 20
    y += 16
    d.text((24, y), "Amortisation Schedule", fill="black")
    y += 22
    d.text((24, y), "Start Date      End Date        Notional", fill="black")
    y += 20
    for a, b, n in SCHEDULE:
        d.text((24, y), f"{a}      {b}      {n}", fill="black")
        y += 20
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def scanned_pdf_bytes() -> bytes:
    """A PDF whose only content is an image - no extractable text."""
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes())).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


BUILDERS = {
    "hwpx": hwpx_bytes,
    "xlsx": xlsx_bytes, "docx": docx_bytes, "csv": csv_bytes,
    "html": html_bytes, "txt": lambda: as_text().encode("utf-8"),
    "png": png_bytes, "scanpdf": scanned_pdf_bytes,
}
