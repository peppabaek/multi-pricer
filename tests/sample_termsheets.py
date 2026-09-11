"""Synthetic termsheets for scenario testing. All names and identifiers are invented."""


def build_pdf(text: str) -> bytes:
    """Render text into a minimal multi-page PDF (no external dependency)."""
    raw_lines = text.splitlines()
    per_page = 58
    pages = [raw_lines[i:i + per_page] for i in range(0, len(raw_lines), per_page)] or [[""]]

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        None,  # pages, filled in below
    ]
    kids, page_objs, content_objs = [], [], []
    next_id = 3
    for lines in pages:
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        kids.append(f"{page_id} 0 R")
        parts = ["BT", "/F1 9 Tf", "12 TL", "36 760 Td"]
        for ln in lines:
            esc = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            parts.append(f"({esc}) Tj T*")
        parts.append("ET")
        content = "\n".join(parts).encode("latin-1", "replace")
        page_objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {next_id + len(pages) * 0} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode())
        content_objs.append(
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")

    font_id = next_id
    page_objs = [p.replace(f"/F1 {next_id + 0} 0 R".encode(), f"/F1 {font_id} 0 R".encode())
                 for p in page_objs]

    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
    body = [objs[0], objs[1]]
    for p, c in zip(page_objs, content_objs):
        body.append(p)
        body.append(c)
    body.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(body, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(body)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(body)+1} /Root 1 0 R >>\nstartxref\n"
            f"{xref_at}\n%%EOF\n").encode()
    return bytes(out)


# ------------------------------------------------------------------ TS-A
TS_A_KRW_IRS = """CONFIRMATION
INTEREST RATE SWAP TRANSACTION

Date: 11 September 2026
To: Daehan Investment Bank Co., Ltd.
Attention: Mr. Jinwoo Seo, Fixed Income Desk
Email: jinwoo.seo@daehan-ib.co.kr
Tel: +82 2-6789-1234
Our Reference: WRB-IRS-2026-1180

Party A: Woori Bank
Party B: Daehan Investment Bank Co., Ltd.
LEI: 9845009F7B2CD1A3E704
Account Number: 1002-455-778901

The purpose of this letter is to confirm the terms and conditions of the
Transaction entered into between us on the Trade Date specified below.

1. GENERAL TERMS
Trade Date:                      11 September 2026
Effective Date:                  15 September 2026
Termination Date:                15 September 2031
Notional Amount:                 KRW 50,000,000,000
Business Days:                   Seoul
Business Day Convention:         Modified Following

2. FIXED AMOUNTS
Fixed Rate Payer:                Party B
Fixed Rate:                      2.7200 per cent per annum
Fixed Rate Day Count Fraction:   Act/365 Fixed
Fixed Rate Payer Payment Dates:  Quarterly, commencing 15 December 2026
Fixed Rate Payer Period End Dates: Adjusted

3. FLOATING AMOUNTS
Floating Rate Payer:             Party A
Floating Rate Option:            KRW-CD-91D
Designated Maturity:             3 months
Floating Rate Day Count Fraction: Act/365 Fixed
Floating Rate Payer Payment Dates: Quarterly
Reset Dates:                     First day of each Calculation Period
Compounding:                     Inapplicable

4. ACCOUNT DETAILS
Payments to Party B: Daehan Investment Bank Co., Ltd.
IBAN: KR29 0020 1234 5678 9012

Yours faithfully,
For and on behalf of Woori Bank
"""

# ------------------------------------------------------------------ TS-B
TS_B_USD_AMORT = """TERM SHEET - USD SOFR OVERNIGHT INDEX SWAP (AMORTISING)

Counterparty: Pacific Rim Capital Markets LLC
Contact: Sarah Whitfield
Email: s.whitfield@pacificrimcm.com
Trade ID: PRCM-OIS-88213

Trade Date:                 11-Sep-2026
Effective Date:             15-Sep-2026
Maturity Date:              15-Sep-2031
Initial Notional:           USD 100,000,000
Currency:                   USD
Direction:                  Client pays fixed

FIXED LEG
Fixed Rate:                 3.6500%
Day Count:                  Act/360
Payment Frequency:          Annual
Business Day Convention:    Modified Following
Business Centres:           New York
Roll Convention:            Adjusted

FLOATING LEG
Index:                      USD-SOFR (compounded in arrears)
Day Count:                  Act/360
Payment Frequency:          Annual
Payment Delay:              2 business days
Business Centres:           New York

AMORTISATION SCHEDULE
Period    From          To            Notional (USD)
1         15-Sep-2026   15-Sep-2027   100,000,000
2         15-Sep-2027   15-Sep-2028    80,000,000
3         15-Sep-2028   15-Sep-2029    60,000,000
4         15-Sep-2029   15-Sep-2030    40,000,000
5         15-Sep-2030   15-Sep-2031    20,000,000

This term sheet is indicative only and does not constitute an offer.
"""

# ------------------------------------------------------------------ TS-C
TS_C_CRS = """CROSS CURRENCY SWAP - TERM SHEET

Counterparty:               Sunrise Asset Management
Beneficiary:                Sunrise Global Fund II
Our Ref: SAM-CRS-2026-0442
Contact Telephone: 02-778-9900

Trade Date:                 11 September 2026
Effective Date:             15 September 2026
Termination Date:           15 September 2031
Spot FX Rate (USD/KRW):     1,375.50

USD LEG (Party A pays)
Notional:                   USD 10,000,000
Rate:                       USD-SOFR compounded
Day Count:                  Act/360
Payment Frequency:          Semi-annual
Business Centres:           Seoul and New York

KRW LEG (Party A receives)
Notional:                   KRW 13,755,000,000
Fixed Rate:                 1.0800 per cent per annum
Day Count:                  30/360
Payment Frequency:          Semi-annual
Business Centres:           Seoul and New York

PRINCIPAL EXCHANGE
Initial Exchange:           Applicable, on the Effective Date
Final Exchange:             Applicable, on the Termination Date

Business Day Convention:    Modified Following
Payment Lag:                2 business days
"""

# ------------------------------------------------------------------ TS-D
TS_D_CALLABLE = """TERM SHEET - CALLABLE INTEREST RATE SWAP

Counterparty: Northbridge Securities
Trade ID: NBS-CALL-4417

Trade Date:                 11 September 2026
Effective Date:             15 September 2026
Final Maturity:             15 September 2036
Notional:                   KRW 30,000,000,000
Fixed Rate:                 3.1500 per cent per annum
Day Count:                  Act/365
Payment Frequency:          Quarterly

OPTIONALITY
Issuer Call Option:         Party A may terminate the Transaction in whole
                            on any Payment Date falling on or after
                            15 September 2031, on 5 business days notice.
Call Price:                 Par, plus accrued but unpaid amounts.
Exercise Style:             Bermudan

The valuation of the embedded option is not covered by this term sheet.
"""

# ------------------------------------------------------------------ TS-E
TS_E_SCATTERED = """                    GREENFIELD MERCHANT BANK
              15 Finsbury Circus, London EC2M 7EB
        Tel: +44 20 7946 0812  |  Fax: +44 20 7946 0813

SWAP CONFIRMATION - Ref: GMB/2026/SW/0731

Dear Mr. Alistair Crane,

We confirm the following Transaction with Greenfield Merchant Bank
(LEI 213800WAVVOPS85N2205), acting through its Seoul branch.

Counter Party: Hanseong Futures Co., Ltd.
Client: Hanseong Futures Co., Ltd.
Legal Name: Hanseong Futures Company Limited
Company Name: Hanseong Futures Co., Ltd.
Address: 24F Gangnam Finance Center, Seoul
Contact: Ms. Yuna Ahn (yuna.ahn@hanseong-futures.kr)
Phone: 02-3450-7788
A/C: 110-9988-77665

TRANSACTION TERMS
Notional Amount:            KRW 20,000,000,000
Effective Date:             15 September 2026
Termination Date:           15 September 2029
Fixed Rate:                 2.6100 per cent per annum
Fixed Day Count:            Act/365 Fixed
Floating Rate Option:       KRW-CD-91D
Payment Frequency:          Quarterly
Business Day Convention:    Modified Following
Business Centres:           Seoul

Please confirm by signing below.

For Greenfield Merchant Bank        For Hanseong Futures Co., Ltd.
_______________________             _______________________
Alistair Crane, Managing Director    Yuna Ahn, Head of Treasury
Email: a.crane@greenfieldmb.com      Email: yuna.ahn@hanseong-futures.kr
"""

SAMPLES = {
    "TS-A": ("KRW CD 91D IRS (vanilla)", TS_A_KRW_IRS),
    "TS-B": ("USD SOFR OIS (amortising)", TS_B_USD_AMORT),
    "TS-C": ("KRW FX SOFR CRS (dual leg)", TS_C_CRS),
    "TS-D": ("Callable IRS (unsupported)", TS_D_CALLABLE),
    "TS-E": ("Identity scattered throughout", TS_E_SCATTERED),
}

# Identity that must never survive redaction, per sample.
SECRETS = {
    "TS-A": ["Daehan Investment Bank", "Jinwoo Seo", "jinwoo.seo@daehan-ib.co.kr",
             "+82 2-6789-1234", "WRB-IRS-2026-1180", "9845009F7B2CD1A3E704",
             "1002-455-778901"],
    "TS-B": ["Pacific Rim Capital", "Sarah Whitfield", "s.whitfield@pacificrimcm.com",
             "PRCM-OIS-88213"],
    "TS-C": ["Sunrise Asset Management", "Sunrise Global Fund II",
             "SAM-CRS-2026-0442", "02-778-9900"],
    "TS-D": ["Northbridge Securities", "NBS-CALL-4417"],
    "TS-E": ["Hanseong Futures", "Yuna Ahn", "Alistair Crane", "Greenfield Merchant Bank",
             "yuna.ahn@hanseong-futures.kr", "a.crane@greenfieldmb.com",
             "110-9988-77665", "213800WAVVOPS85N2205",
             "02-3450-7788", "24F Gangnam Finance Center"],
}

# Pricing terms that must survive redaction, per sample.
MUST_KEEP = {
    "TS-A": ["50,000,000,000", "15 September 2026", "15 September 2031", "2.7200",
             "Act/365 Fixed", "Quarterly", "Modified Following", "KRW-CD-91D", "Seoul"],
    "TS-B": ["100,000,000", "80,000,000", "20,000,000", "3.6500%", "Act/360",
             "Annual", "USD-SOFR", "New York", "15-Sep-2031"],
    "TS-C": ["10,000,000", "13,755,000,000", "1,375.50", "1.0800", "30/360",
             "Act/360", "Semi-annual", "Initial Exchange", "Final Exchange"],
    "TS-D": ["30,000,000,000", "3.1500", "Bermudan", "Call Option"],
    "TS-E": ["20,000,000,000", "2.6100", "Act/365 Fixed", "Quarterly",
             "Modified Following", "Seoul", "KRW-CD-91D"],
}


def pdf(key: str) -> bytes:
    return build_pdf(SAMPLES[key][1])
