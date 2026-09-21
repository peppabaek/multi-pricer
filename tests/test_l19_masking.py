# -*- coding: utf-8 -*-
"""
L19 Counterparty masking.

The desk's compliance position is that identity is stripped before a term sheet
leaves the process. That makes masking a control, not a convenience, so it is worth
testing from both sides: identity must not survive, and nothing the pricer needs may
be taken with it. A rule that eats a rate is as much a failure as one that leaks a
name - it just fails somewhere quieter.
"""
import sys

from harness import case, run_all
from server.termsheet import redact, redaction_leaks

REDACTED = "[REDACTED]"

# A confirmation with identity in every shape a real one carries it: labelled fields,
# a letterhead with no label at all, a signature block, and Korean legal names.
DOC = """                    대한투자증권 (Daehan Investment & Securities Co., Ltd.)
                              거래확인서 / TRADE CONFIRMATION

Counterparty:      우리은행 (Woori Bank), Seoul Branch
거래상대방:         한성선물 주식회사
Client:            Sunrise Global Fund II
Attention:         Mr. Jinwoo Seo, Rates Desk
Contact:           jinwoo.seo@daehan-ib.co.kr  /  +82-2-3771-9000
Reference:         DHIB-IRS-2026-4417
Account Name:      Pacific Rim Capital Markets Limited
LEI:               988400V5B6L4ZQ1S0H12
판매사:            신한자산운용 주식회사
수탁자:            국민은행

Trade Type:        KRW Interest Rate Swap
Notional:          KRW 50,000,000,000
Effective Date:    15 September 2026
Maturity Date:     15 September 2031
Fixed Rate:        2.7200%
Reference Rate:    KRW CD 91D
Reference Index:   CD 91D (3M)
Day Count:         Act/365
Payment Frequency: Quarterly
Business Day Convention: Modified Following
Business Centres:  Seoul
이자계산:          Act/365 기준, 분기 지급

Signed for and on behalf of Greenfield Merchant Bank plc
By: Alistair Crane, Managing Director
"""

IDENTITY = [
    "대한투자증권", "Daehan Investment", "우리은행", "Woori Bank", "한성선물",
    "Sunrise Global Fund", "Jinwoo Seo", "jinwoo.seo@daehan-ib.co.kr",
    "+82-2-3771-9000", "DHIB-IRS-2026-4417", "Pacific Rim Capital",
    "988400V5B6L4ZQ1S0H12", "Greenfield Merchant Bank", "Alistair Crane",
    "신한자산운용", "국민은행",
]

PRICING = [
    "50,000,000,000", "2.7200", "Act/365", "Quarterly", "KRW CD 91D",
    "CD 91D (3M)", "15 September 2026", "15 September 2031", "Seoul",
    "Modified Following", "분기 지급", "Interest Rate Swap",
]


@case("L19-1", "no counterparty identity survives a full confirmation")
def t_1():
    red, _ = redact(DOC)
    left = [n for n in IDENTITY if n in red]
    if left:
        raise AssertionError(f"identity survived masking: {left}")


@case("L19-2", "nothing the pricer needs is taken with it")
def t_2():
    red, _ = redact(DOC)
    lost = [p for p in PRICING if p not in red]
    if lost:
        raise AssertionError(f"masking destroyed pricing terms: {lost}")


@case("L19-3", "a Korean company name is caught with no label in front of it")
def t_3():
    # A letterhead carries the name alone. The English rule keys off runs of
    # capitalised words, which a Hangul name does not have.
    for name in ("대한투자증권", "신한자산운용", "미래에셋증권", "삼성생명",
                 "하나캐피탈", "한국투자신탁", "주식회사 케이비손해"):
        red, _ = redact(f"{name}\n거래확인서\n")
        if name.replace("주식회사 ", "") in red:
            raise AssertionError(f"unlabelled Korean entity survived: {name}")


@case("L19-4", "'Reference Rate' is a pricing term, not a party label")
def t_4():
    # "Reference:" carries a deal id and must go; "Reference Rate:" carries the index
    # and must stay. Treating them the same breaks one side or the other.
    red, _ = redact("Reference: DHIB-4417\nReference Rate: KRW CD 91D\n"
                    "Reference Index: CD 91D\nReference Period: 3M\n")
    if "DHIB-4417" in red:
        raise AssertionError("a deal reference survived")
    for keep in ("KRW CD 91D", "CD 91D", "3M"):
        if keep not in red:
            raise AssertionError(f"masking ate a reference pricing term: {keep}")


@case("L19-5", "a signature block is identity too")
def t_5():
    red, _ = redact("By: Alistair Crane, Managing Director\n"
                    "Signed by: 서진우\nAuthorised Signatory: Mia Chen\n")
    for name in ("Alistair Crane", "서진우", "Mia Chen"):
        if name in red:
            raise AssertionError(f"a signatory survived: {name}")


@case("L19-6", "the leak scanner agrees the text is clean")
def t_6():
    red, _ = redact(DOC)
    leaks = redaction_leaks(red)
    if leaks:
        raise AssertionError(f"scanner still finds identity patterns: {leaks}")


@case("L19-7", "masking is counted, so the trader sees how much was removed")
def t_7():
    _, counts = redact(DOC)
    if sum(counts.values()) < 10:
        raise AssertionError(f"suspiciously little removed: {counts}")


@case("L19-8", "a document with no identity is left alone")
def t_8():
    plain = ("Notional: KRW 50,000,000,000\nFixed Rate: 2.7200%\n"
             "Day Count: Act/365\nPayment Frequency: Quarterly\n")
    red, counts = redact(plain)
    if REDACTED in red or sum(counts.values()):
        raise AssertionError(f"masked a document that had nothing to mask: {red!r}")


@case("L19-9", "an amount is never mistaken for an identifier")
def t_9():
    # 18 alphanumerics then two digits is the LEI shape; a notional must not trip it.
    red, _ = redact("Notional: 50,000,000,000\nNotional: KRW 123456789012345678\n"
                    "Fixed Rate: 2.7200%\n")
    for keep in ("50,000,000,000", "2.7200"):
        if keep not in red:
            raise AssertionError(f"an amount was masked as an identifier: {keep}")


if __name__ == "__main__":
    print("\n=== L19 Counterparty masking ===")
    sys.exit(1 if run_all("L19") else 0)
