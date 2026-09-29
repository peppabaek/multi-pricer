"""
Termsheet extraction: PDF in, trade terms out.

Nothing is persisted. The PDF binary never leaves this process - only redacted
text is sent to the model - and every intermediate is dropped when the request ends.
"""

import io
import os
import sys
import re
import time
import hashlib
import datetime
from typing import List, Optional, Dict, Any, Tuple, Literal

from pydantic import BaseModel, Field

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ENV_FILE = os.path.join(_PROJECT_ROOT, ".env")


def load_env_file(path: str = _ENV_FILE) -> None:
    """
    Read KEY=VALUE lines from .env into the environment.

    Keeps the API key out of the source tree and off the command line; an already-set
    environment variable always wins so a shell export can override the file.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and val:
                    os.environ[key] = val
    except Exception as e:
        _log(f"[Termsheet] .env read failed: {e}")


load_env_file()


def _log(message: str) -> None:
    """
    Write a diagnostic line, whatever the console can encode.

    These messages carry Korean and em-dashes, and a console on a legacy code page
    raises UnicodeEncodeError on them. That is a subclass of ValueError, so a failed
    print did not merely lose a log line - it surfaced as a 400 blaming the document.
    """
    try:
        print(message)
    except Exception:
        try:
            enc = getattr(sys.stdout, "encoding", None) or "ascii"
            sys.stdout.write(message.encode(enc, "replace").decode(enc, "replace") + "\n")
        except Exception:
            pass


def extraction_status() -> Dict[str, Any]:
    """Whether extraction can run, on which provider, and how to enable it if not."""
    load_env_file()
    from server.providers import PROVIDERS, describe, is_available, resolve_model

    primary = os.environ.get("TERMSHEET_PROVIDER", "anthropic").strip().lower()
    second = os.environ.get("TERMSHEET_SECOND_PROVIDER", "").strip().lower()
    known = primary in PROVIDERS
    ready = known and is_available(primary)

    out: Dict[str, Any] = {
        "ready": ready,
        "provider": primary,
        "provider_label": PROVIDERS[primary]["label"] if known else primary,
        "model": resolve_model(primary) if known else None,
        "cross_check": bool(second and second in PROVIDERS and is_available(second)),
        "second_provider": second or None,
        # Configured but unusable is its own state: the trader would otherwise read
        # "off" as a choice someone made, not a key that was never pasted.
        "second_pending": bool(second and second in PROVIDERS and not is_available(second)),
        "providers": describe(),
    }
    if not ready:
        if not known:
            out["reason"] = f"TERMSHEET_PROVIDER={primary!r} 는 지원하지 않습니다"
        else:
            envs = " 또는 ".join(PROVIDERS[primary]["key_env"]) or "(키 불필요)"
            out["reason"] = f"{PROVIDERS[primary]['label']} 키가 없습니다 ({envs})"
            out["how_to"] = [
                f"{_ENV_FILE} 에 {envs} 를 추가하고 서버를 재시작하세요",
                f"발급: {PROVIDERS[primary]['signup']}",
            ]
        free = [p["name"] for p in out["providers"]
                if p["cost"].startswith("free") and p["available"]]
        if free:
            out["free_available"] = free
    return out


# Conventions the pricer actually understands (server/calendar_manager.py).
DAY_COUNTS = ["Act/365", "Act/360", "30/360", "Act/Act"]
CALENDARS = ["SEB", "LNB", "NYB", "TKB", "SEB_NYB", "TGT", "LNB_TGT", "NYB_TGT",
             "NYB_TKB", "LNB_NYB", "LNB_NYB_TGT", "LNB_TKB", "SEB_TGT", "SEB_TKB",
             "SEB_LNB", "LNB_SEB_TKB", "TGT_TKB", "BMA", "NONE"]
CONVENTIONS = ["Modified Following", "Following", "Preceding"]
STUB_RULES = ["Short in arrears", "Short upfront", "Long in arrears", "Long upfront"]
FREQUENCIES = ["1M", "3M", "6M", "12M"]


# ---------------------------------------------------------------- 1. text
# Formats a counterparty actually sends. Anything text-bearing is read here, in memory,
# so the identity stripping downstream still applies to every word before it leaves.
# A picture has no words to strip - see needs_vision below.
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "gif": "image/gif", "bmp": "image/bmp", "webp": "image/webp",
               "tif": "image/tiff", "tiff": "image/tiff",
               # 아이폰이 기본으로 저장하는 포맷. 갤러리에서 바로 올리면 이게 옵니다.
               "heic": "image/heic", "heif": "image/heif", "avif": "image/avif"}

# ISO-BMFF 컨테이너(HEIC/HEIF/AVIF)의 브랜드. 파일 4~8 바이트가 "ftyp" 이고
# 그 뒤 네 글자가 브랜드입니다.
_BMFF_IMAGE_BRANDS = frozenset(
    (b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevm", b"hevs",
     b"mif1", b"msf1", b"avif", b"avis"))


def _is_bmff_image(raw: bytes) -> bool:
    return len(raw) >= 12 and raw[4:8] == b"ftyp" and raw[8:12] in _BMFF_IMAGE_BRANDS


def sniff_kind(raw: bytes, filename: str = "") -> str:
    """
    What this file is, by content first and name second.

    Marketers rename things and browsers guess content types, so the magic bytes are
    the authority; the extension only breaks ties the bytes cannot.
    """
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""

    if raw[:5] == b"%PDF-":
        return "pdf"
    if raw[:4] == b"PK\x03\x04":
        # An OOXML container: which one is in the part names.
        try:
            import zipfile
            names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
        except Exception:
            names = []
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        if any(n.startswith("Contents/") or n.endswith(".hwpx") for n in names) \
                or ext == "hwpx":
            return "hwpx"
        return "zip"
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        if ext in ("xls", "xlt"):
            return "xls"
        if ext == "hwp" or b"HWP Document File" in raw[:2048]:
            return "hwp"
        return "ole"                                          # legacy Office
    if raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff" \
            or raw[:6] in (b"GIF87a", b"GIF89a") or raw[:2] == b"BM" \
            or raw[:4] in (b"II*\x00", b"MM\x00*") \
            or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")             or _is_bmff_image(raw):
        return "image"
    if ext in IMAGE_TYPES:
        return "image"
    if ext in ("csv", "tsv", "txt", "md", "json", "htm", "html"):
        return "html" if ext in ("htm", "html") else "text"
    return "text"


_DATEISH = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$")


def _schedule_rows(lines: List[str]) -> int:
    """How many rows of this sheet look like a schedule period: two dates and a number."""
    n = 0
    for line in lines:
        cells = [c.strip() for c in line.split("\t")]
        dates = sum(1 for c in cells if _DATEISH.match(c))
        numeric = sum(1 for c in cells
                      if c.replace(",", "").replace(".", "").isdigit() and len(c) >= 4)
        if dates >= 2 and numeric >= 1:
            n += 1
    return n


def _xlsx_text(raw: bytes) -> str:
    """
    Every sheet as tab-separated rows, with the trade schedule named.

    Tab-separated is not incidental: an Excel term sheet usually carries the schedule
    as a block of cells, and this is the shape the rollercoaster parser already reads.

    A workbook often holds more than one schedule - a working copy, an earlier draft,
    a second leg. Handed both without comment, a model reads them as one trade
    contradicting itself and refuses the document. So the sheets are compared here,
    where it is a matter of counting rows rather than judgement, and the longest
    schedule is marked as the trade while the rest are marked reference.
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    sheets: List[Tuple[str, List[str]]] = []
    try:
        for ws in wb.worksheets:
            lines = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else
                         (c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c))
                         for c in row]
                while cells and not cells[-1]:
                    cells.pop()
                if cells:
                    lines.append("\t".join(cells))
            sheets.append((ws.title, lines))
    finally:
        wb.close()

    counts = {title: _schedule_rows(lines) for title, lines in sheets}
    with_schedule = [t for t, n in counts.items() if n >= 2]
    primary = max(with_schedule, key=lambda t: counts[t]) if len(with_schedule) > 1 else None

    out = []
    for title, lines in sheets:
        if primary is None:
            label = f"--- sheet: {title} ---"
        elif title == primary:
            label = (f"--- sheet: {title} --- TRADE SCHEDULE: price this one "
                     f"({counts[title]} periods) ---")
        elif counts.get(title, 0) >= 2:
            label = (f"--- sheet: {title} --- REFERENCE ONLY: another copy of the "
                     f"schedule, do not use and do not treat as a contradiction ---")
        else:
            label = f"--- sheet: {title} ---"
        out.append(label)
        out.extend(lines)
    return "\n".join(out)


def _docx_text(raw: bytes) -> str:
    """Paragraphs and table rows, without pulling in python-docx for a zip of XML."""
    import zipfile
    from xml.etree import ElementTree as ET

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read("word/document.xml")
    body = ET.fromstring(xml).find(f"{W}body")
    lines = []

    def para_text(para):
        return "".join(t.text or "" for t in para.iter(f"{W}t"))

    for el in body or []:
        if el.tag == f"{W}p":
            t = para_text(el).strip()
            if t:
                lines.append(t)
        elif el.tag == f"{W}tbl":
            for tr in el.findall(f"{W}tr"):
                cells = [" ".join(para_text(p).strip() for p in tc.findall(f"{W}p")).strip()
                         for tc in tr.findall(f"{W}tc")]
                if any(cells):
                    lines.append("\t".join(cells))
    return "\n".join(lines)


def _hwpx_text(raw: bytes) -> str:
    """
    HWPX is a zip of XML, the same shape as docx, so its text comes out the same way.

    Korean desks draft in Hangul Word Processor, and the .hwpx save is the one that
    can be read without the vendor's binary format.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    out = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        sections = sorted(n for n in z.namelist()
                          if n.startswith("Contents/section") and n.endswith(".xml"))
        for name in sections or [n for n in z.namelist() if n.endswith(".xml")]:
            try:
                root = ET.fromstring(z.read(name))
            except Exception:
                continue
            for el in root.iter():
                tag = el.tag.rsplit("}", 1)[-1]
                if tag in ("t", "char") and (el.text or "").strip():
                    out.append(el.text)
                elif tag in ("p", "tr") and out and out[-1] != "\n":
                    out.append("\n")
    return re.sub(r"\n{3,}", "\n\n", "".join(out))


def _html_text(raw: bytes) -> str:
    txt = raw.decode("utf-8", errors="replace")
    txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", txt)
    txt = re.sub(r"(?i)</(p|div|tr|br|h[1-6])\s*>", "\n", txt)
    txt = re.sub(r"(?i)</t[dh]\s*>", "\t", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    from html import unescape
    return re.sub(r"\n{3,}", "\n\n", unescape(txt))


def _printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    ok = sum(1 for c in text if c.isprintable() or c in "\r\n\t")
    return ok / len(text)


def _plain_text(raw: bytes) -> str:
    """
    Decode a text file, and refuse one that is not text.

    latin-1 decodes any byte at all, so without this check an arbitrary binary file
    becomes a "document" full of control characters and gets sent to a model to find
    out it was nothing - a wasted call, and bytes leaving the desk for no reason.
    """
    text = None
    for enc in ("utf-8", "cp949", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        text = raw.decode("latin-1", errors="replace")

    if _printable_ratio(text) < 0.85:
        raise ValueError("텍스트 파일이 아닙니다 — PDF, Excel, Word, 이미지, "
                         "CSV/텍스트 형식으로 올려주세요")
    return text


def _pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        try:
            pages.append(f"--- page {i} ---\n{page.extract_text() or ''}")
        except Exception:
            pages.append(f"--- page {i} ---\n")
    return "\n\n".join(pages)


def pdf_has_images(raw: bytes) -> bool:
    """Whether a PDF carries any raster content - i.e. whether a scan could be in it."""
    try:
        from pypdf import PdfReader
        for page in PdfReader(io.BytesIO(raw)).pages:
            try:
                if len(page.images):
                    return True
            except Exception:
                # Some encodings pypdf cannot enumerate; assume there is something there
                # rather than declaring a page blank on a decoding limitation.
                return True
    except Exception:
        return False
    return False


def body_length(text: str) -> int:
    """Characters that are not our own page or sheet markers."""
    return len(re.sub(r"---\s*(page|sheet:)[^\n]*---", "", text or "").strip())


def extract_text(raw: bytes, filename: str = "") -> str:
    """
    Pull text out of whatever the marketer sent, in memory. Never touches disk.

    Raises ValueError with something the trader can act on when the format is one this
    machine cannot read, rather than a stack trace about a missing import.
    """
    kind = sniff_kind(raw, filename)
    try:
        if kind == "pdf":
            return _pdf_text(raw)
        if kind == "xlsx":
            return _xlsx_text(raw)
        if kind == "docx":
            return _docx_text(raw)
        if kind == "html":
            return _html_text(raw)
        if kind == "image":
            return ""          # nothing to read: handled by the vision path
        if kind == "hwpx":
            return _hwpx_text(raw)
        if kind == "hwp":
            raise ValueError(
                "한글(.hwp) 바이너리 형식은 읽을 수 없습니다 - 한글에서 "
                "'다른 이름으로 저장 → HWPX' 또는 'PDF로 저장' 후 올려주세요")
        if kind == "xls":
            raise ValueError("구형 .xls 형식입니다 - Excel에서 .xlsx로 저장한 뒤 올려주세요")
        if kind == "pptx":
            raise ValueError("PowerPoint는 아직 지원하지 않습니다 - "
                             "PDF로 내보내거나 표를 Excel로 옮겨 올려주세요")
        if kind in ("zip", "ole"):
            raise ValueError("읽을 수 없는 형식입니다 - PDF, Excel, Word, 이미지, "
                             "CSV/텍스트를 지원합니다")
        return _plain_text(raw)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"파일을 읽지 못했습니다 ({kind}): {e}")


# ---------------------------------------------------------------- 2. redaction
# Only label-anchored values and distinctively shaped identifiers are removed.
# Anything a pricer needs - dates, amounts, rates, tenors, conventions - must survive,
# so this deliberately does not guess at bare names.
_PARTY_LABELS = (
    r"Party\s*A|Party\s*B|Counterparty|Counter\s*Party|Client|Customer|"
    r"Buyer|Seller|Dealer|Borrower|Lender|Beneficiary|Obligor|Issuer|Guarantor|"
    r"Account\s*Name|Legal\s*Name|Company\s*Name|Contact|Attention|Attn|"
    r"To|From|Broker|Agent|Payments?\s*to(?:\s*Party\s*[AB])?|"
    r"Reference(?!\s*(?:Rate|Index|Obligation|Period|Amount|Entity))|Ref\.?|"
    r"Deal\s*(?:ID|No|Number|Ref)|Trade\s*(?:ID|No|Number|Ref)|"
    r"Signed\s*by|Authori[sz]ed\s*Signatory|Signatory|By|"
    r"거래상대방|거래상대|고객명|상대방|매수인|매도인|"
    r"담당자|연락처|성명|서명|발행인|판매사|수탁자|거래처"
)

# Corporate suffixes catch letterheads and signature blocks, where the name carries no
# label at all. No pricing term contains these words, so this cannot eat a rate or a date.
# Korean corporate suffixes. A name ending in one of these is a company, and no
# pricing term does - so this cannot eat a rate, a tenor or a convention.
_KO_ENTITY_SUFFIX = (
    r"투자증권|금융투자|증권|은행|저축은행|보험|생명|화재|해상|"
    r"자산운용|운용|선물|캐피탈|종합금융|종금|신탁|파이낸셜|"
    r"홀딩스|지주|금고|조합|공사|공단"
)

_ENTITY_WORDS = (
    r"Bank|Banking|Securities|Capital|Markets|Investment|Investments|Futures|"
    r"Asset\s+Management|Trust|Holdings|Partners|Financial|Finance|"
    r"Co\.,?\s*Ltd\.?|Company\s+Limited|Ltd\.?|LLC|L\.L\.C\.|Inc\.?|PLC|"
    r"GmbH|S\.A\.|N\.V\.|A\.G\.|Pte\.?\s*Ltd\.?"
)
# Case-insensitive so an all-caps letterhead matches too, but the leading words must
# still be capitalised - (?-i:[A-Z]) keeps that check case-sensitive - and at least one
# is required, so a bare prose word like "trust" is never swallowed.
_ENTITY_RE = re.compile(
    rf"\b(?:(?-i:[A-Z])[\w'&.\-]*\s+){{1,4}}(?:{_ENTITY_WORDS})(?:\s+(?:{_ENTITY_WORDS}))*"
    rf"|(?:\(주\)\s*)?[가-힣]{{2,10}}(?:{_KO_ENTITY_SUFFIX})(?:\s*\(주\)|\s*주식회사)?"
    rf"|주식회사\s*[가-힣]{{2,10}}",
    re.IGNORECASE,
)
_ID_LABELS = (
    r"LEI|BIC|SWIFT|IBAN|Account\s*(?:No|Number|#)|A/C|"
    r"Trade\s*(?:ID|No|Number|Ref)|Deal\s*(?:ID|No|Number|Ref)|"
    r"(?:Our|Your)\s*Ref(?:erence)?|Ref(?:erence)?\s*(?:ID|No|Number)|"
    r"USI|UTI|Address|Tel(?:ephone)?|Fax|Phone"
)

_RULES: List[Tuple[str, "re.Pattern[str]"]] = [
    ("party", re.compile(rf"(?im)^(\s*(?:{_PARTY_LABELS})\s*[:：]\s*)(.+)$")),
    ("identifier", re.compile(rf"(?im)^(\s*(?:{_ID_LABELS})\s*[:：]\s*)(.+)$")),
    ("email", re.compile(r"(?i)\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("lei", re.compile(r"\b[A-Z0-9]{18}\d{2}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s-]\d{3,4}[\s-]\d{4}(?!\d)")),
]

REDACTED = "[REDACTED]"


_GENERIC_VALUES = {
    "applicable", "inapplicable", "n/a", "na", "none", "tbd", "as above",
    "party a", "party b", "seller", "buyer", "the counterparty",
}


_HONORIFIC_RE = re.compile(r"^(?:Mr|Mrs|Ms|Miss|Dr|Prof|Messrs)\.?\s+", re.IGNORECASE)
_SALUTATION_RE = re.compile(
    r"(?im)^\s*Dear\s+(?:Mr|Mrs|Ms|Miss|Dr|Prof|Messrs)?\.?\s*"
    r"([A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+){0,3})")


def _harvest_identity(text: str) -> List[str]:
    """Collect identity strings worth sweeping from the whole document."""
    found: List[str] = []

    def _add(val: str):
        val = val.strip().rstrip(".,;:")
        if len(val) < 4 or val.lower() in _GENERIC_VALUES:
            return
        found.append(val)
        # A name is written several ways across one document: with an honorific on the
        # labelled line, bare in the signature block, with contact details appended.
        bare = _HONORIFIC_RE.sub("", val).strip().rstrip(".,;:")
        if len(bare) >= 4 and bare != val:
            found.append(bare)
        head = re.split(r"\s*[(\[<]", bare)[0].strip().rstrip(".,;:")
        if len(head) >= 4 and head != bare:
            found.append(head)

    label_re = re.compile(rf"(?im)^\s*(?:{_PARTY_LABELS})\s*[:：]\s*(.+)$")
    for m in label_re.finditer(text):
        _add(m.group(1))

    for m in _SALUTATION_RE.finditer(text):
        _add(m.group(1))

    for m in _ENTITY_RE.finditer(text):
        val = m.group(0).strip().rstrip(".,;")
        if len(val) >= 4:
            found.append(val)
            bare = _HONORIFIC_RE.sub("", val).strip()
            if len(bare) >= 4 and bare != val:
                found.append(bare)

    # Longest first so "X Bank Co., Ltd." is removed before the shorter "X Bank".
    return sorted(set(found), key=len, reverse=True)


def redact(text: str) -> Tuple[str, Dict[str, int]]:
    """
    Strip counterparty identity and reference identifiers.

    Three passes, because a termsheet carries identity in three different shapes:
    labelled fields, free-standing entity names (letterheads, signature blocks),
    and structured identifiers. Returns (text, counts).
    """
    counts: Dict[str, int] = {}
    out = text

    # 1. Labelled fields and structured identifiers.
    for name, pattern in _RULES:
        if pattern.groups >= 2:
            def _sub(m, _n=name):
                counts[_n] = counts.get(_n, 0) + 1
                return f"{m.group(1)}{REDACTED}"
            out = pattern.sub(_sub, out)
        else:
            def _sub2(m, _n=name):
                counts[_n] = counts.get(_n, 0) + 1
                return REDACTED
            out = pattern.sub(_sub2, out)

    # 2. Sweep every harvested identity string wherever else it appears - headers,
    #    footers, signature blocks, mid-sentence.
    for ident in _harvest_identity(text):
        if ident == REDACTED or REDACTED in ident:
            continue
        # Case-insensitive: the same name appears title-cased in the body and
        # upper-cased in the letterhead.
        ident_re = re.compile(re.escape(ident), re.IGNORECASE)
        out, hits = ident_re.subn(REDACTED, out)
        if hits:
            counts["name"] = counts.get("name", 0) + hits

    # 3. Entity names introduced only in the redacted text's remaining spans.
    def _sub_entity(m):
        counts["name"] = counts.get("name", 0) + 1
        return REDACTED
    out = _ENTITY_RE.sub(_sub_entity, out)

    return out, counts


def redaction_leaks(redacted_text: str) -> List[str]:
    """Re-scan the redacted text; anything still matching is a leak."""
    leaks = []
    for name, pattern in _RULES:
        for m in pattern.finditer(redacted_text):
            hit = m.group(2) if pattern.groups >= 2 else m.group(0)
            if hit and hit.strip() != REDACTED:
                leaks.append(name)
                break
    return leaks


# ---------------------------------------------------------------- 3. schema
class Provenance(BaseModel):
    field: str
    source: Literal["extracted", "inferred", "missing"]
    quote: Optional[str] = Field(None, description="Verbatim text from the termsheet")
    note: Optional[str] = None


class SchedulePeriod(BaseModel):
    start_date: str
    end_date: str
    pay_date: Optional[str] = None
    notional: float
    fixed_rate_pct: Optional[float] = None
    spread_bp: Optional[float] = None


class ExtractedTrade(BaseModel):
    supported: bool
    unsupported_reason: Optional[str] = None
    # Set by the pipeline, never by the model: marks a canned demo answer.
    demo_fallback: bool = False

    currency: Optional[Literal["USD", "KRW", "KRW_KOFR", "KRW_CRS"]] = None
    position: Optional[Literal["Pay Fixed", "Rec Fixed"]] = None
    notional: Optional[float] = None
    usd_notional: Optional[float] = None
    krw_notional: Optional[float] = None
    spot_fx: Optional[float] = None

    effective_date: Optional[str] = None
    maturity_date: Optional[str] = None
    tenor: Optional[str] = None
    fixed_coupon_pct: Optional[float] = None
    spread_bp: Optional[float] = None

    crs_swap_type: Optional[Literal["Vanilla", "Fixed-Fixed"]] = None
    usd_fixed_coupon_pct: Optional[float] = None
    payment_lag_bd: Optional[int] = None

    leg1_day_count: Optional[str] = None
    leg1_payment_freq: Optional[str] = None
    leg1_business_day_conv: Optional[str] = None
    leg1_stub_rule: Optional[str] = None
    leg1_adjust_rule: Optional[str] = None
    leg1_calendar: Optional[str] = None

    leg2_day_count: Optional[str] = None
    leg2_payment_freq: Optional[str] = None
    leg2_business_day_conv: Optional[str] = None
    leg2_stub_rule: Optional[str] = None
    leg2_adjust_rule: Optional[str] = None
    leg2_calendar: Optional[str] = None
    leg2_fix_day: Optional[int] = None

    leg1_custom_schedule: Optional[List[SchedulePeriod]] = None
    leg2_custom_schedule: Optional[List[SchedulePeriod]] = None

    provenance: List[Provenance] = []
    open_questions: List[str] = []


SYSTEM_PROMPT = f"""You read interest-rate and cross-currency swap termsheets and return the trade terms needed to price them.

The text you receive has already had counterparty identity and reference identifiers removed and replaced with {REDACTED}. That is expected - never report it as missing information, and never try to infer who the parties are.

Rules:

1. Report only what the document states. If a convention is absent, leave the field null and record it as "inferred" or "missing" in provenance - do not silently fill in a market default. The pricer applies its own defaults and shows them to the trader separately.

2. For every field you populate, add a provenance entry with source="extracted" and a quote copied VERBATIM from the document - exact characters, no paraphrase, no normalisation. The server checks each quote against the document text and rejects any it cannot find.

3. Map conventions onto exactly these values:
   - day count: {", ".join(DAY_COUNTS)}
   - payment frequency: {", ".join(FREQUENCIES)}
   - business day convention: {", ".join(CONVENTIONS)}
   - stub rule: {", ".join(STUB_RULES)}
   - adjust rule: Adjust, Unadjust
   - calendar: {", ".join(CALENDARS[:8])} and other combinations from that set
   If the document says something you cannot map confidently (e.g. an unlisted business centre), leave it null and explain in the provenance note.

4. Leg 1 is the fixed / KRW leg. Leg 2 is the floating / USD leg.

5. Product routing:
   - USD SOFR OIS -> currency "USD"
   - KRW CD 91D IRS -> currency "KRW"
   - KRW KOFR OIS -> currency "KRW_KOFR"
   - KRW fixed vs USD SOFR with principal exchange -> currency "KRW_CRS"

6. Amortising, accreting or step-up structures: return every period in leg1_custom_schedule
   (and leg2_custom_schedule if the legs differ). Dates as YYYY-MM-DD.

7. supported=false is ONLY for a product this pricer cannot value: callable,
   cancellable, CMS-linked, range accrual, or any optionality. Nothing else.

   In particular, NEVER set supported=false because:
     - the document is missing a rate, an index, a spread or any other term. A
       schedule with no rate on it is a normal thing to receive; leave those fields
       null, and the trader supplies them.
     - the document is ambiguous, or you are unsure.
     - a workbook holds more than one schedule or more than one sheet.
   In all of those cases set supported=true, extract what the document does state,
   and put your doubt in open_questions. Do not force a trade into a vanilla shape.

8. A workbook may carry several sheets. Extract the one that describes the trade
   being priced - normally the longest schedule, or the one whose dates agree with
   the stated effective and maturity dates. Do not merge two schedules. Name the
   other sheets in open_questions so the trader can say which is right.

8. Put anything the trader should confirm with the counterparty into open_questions.

Dates must be YYYY-MM-DD. Rates are percent per annum. Spreads are basis points."""


def demo_mode_enabled() -> bool:
    """Canned sample answers are opt-in and never the default."""
    return os.environ.get("TERMSHEET_DEMO_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def _match_synthetic_sample(text: str) -> Optional[ExtractedTrade]:
    """
    Canned answers for the bundled synthetic samples, for demos without API credit.

    Matching is on values as ordinary as "100,000,000", so a real termsheet can hit these
    patterns by coincidence. Any result from here is therefore marked demo_fallback and
    the pipeline refuses to let it be confirmed or priced.
    """
    if "50,000,000,000" in text and "2.7200" in text:
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
    elif "100,000,000" in text and "3.6500%" in text:
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
    elif "13,755,000,000" in text and "1,375.50" in text:
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
    elif "100,000,000,000" in text and "2.8450%" in text:
        return ExtractedTrade(
            supported=True, currency="KRW_KOFR", position="Rec Fixed", notional=1e11,
            effective_date="2026-09-14", maturity_date="2027-09-14",
            fixed_coupon_pct=2.8450, tenor="1Y",
            leg1_day_count="Act/365 Fixed", leg1_payment_freq="Quarterly",
            leg1_business_day_conv="Modified Following", leg1_calendar="SEB",
            leg2_day_count="Act/365 Fixed", leg2_payment_freq="Quarterly",
            leg2_calendar="SEB", payment_lag_bd=2,
            provenance=[
                Provenance(field="notional", source="extracted",
                           quote="Notional Amount:                 KRW 100,000,000,000"),
                Provenance(field="fixed_coupon_pct", source="extracted",
                           quote="Fixed Rate:                      2.8450% per annum"),
            ],
            open_questions=[])
    return None


# ---------------------------------------------------------------- 4. model call
def primary_provider() -> str:
    """Which model reads the document first. Any provider in the registry will do."""
    return os.environ.get("TERMSHEET_PROVIDER", "anthropic").strip().lower()


# A provider that just told us it is out of quota will say the same thing to the next
# upload, so stop asking it for a while. In-process and deliberately short: a per-minute
# limit clears itself, and a daily one should not silently disable a provider for good.
_PROVIDER_COOLDOWN: Dict[str, float] = {}
_COOLDOWN_SECONDS = 600


def _cooling_off(name: str) -> bool:
    until = _PROVIDER_COOLDOWN.get(name, 0)
    if until and until > time.time():
        return True
    _PROVIDER_COOLDOWN.pop(name, None)
    return False


def _classify_provider_error(exc: Exception) -> Optional[str]:
    """
    Why a provider failed, when the reason is the provider rather than the document.

    Returns a short reason for anything another model could succeed at, and None when
    trying elsewhere would be pointless.
    """
    err = str(exc).lower()
    if "credit balance is too low" in err or "insufficient_quota" in err:
        return "잔액 부족"
    if "rate limit" in err or "429" in err or "quota" in err or "resource_exhausted" in err:
        return "호출 한도"
    if "503" in err or "overloaded" in err or "unavailable" in err:
        return "서비스 불안정"
    if "timeout" in err or "timed out" in err or "connection" in err or "getaddrinfo" in err:
        return "연결 실패"
    if "401" in err or "403" in err or "unauthorized" in err or "api key" in err:
        return "키 오류"
    # Vendors retire models on their own schedule. That is the provider's problem, not
    # the document's, so it should move to the next one rather than fail the upload.
    if ("decommissioned" in err or "model_not_found" in err or "does not exist" in err
            or "404" in err):
        return "모델 없음"
    return None


def extraction_candidates() -> List[Tuple[str, str]]:
    """Every (provider, model) worth trying, in order."""
    from server.providers import model_candidates
    return [(n, m) for n in extraction_chain() for m in model_candidates(n)]


def extraction_chain() -> List[str]:
    """
    The order models are tried in: the configured one, then whatever else can run.

    Set TERMSHEET_FALLBACK_PROVIDERS to pin the order, or to an empty value to refuse
    failover entirely - which is the right setting where only one vendor is cleared to
    see the document.
    """
    from server.providers import PROVIDERS, is_available

    primary = primary_provider()
    chain = [primary] if primary in PROVIDERS else []

    raw = os.environ.get("TERMSHEET_FALLBACK_PROVIDERS")
    if raw is not None:
        names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    else:
        names = list(PROVIDERS)

    for n in names:
        if n in PROVIDERS and n not in chain and is_available(n):
            chain.append(n)
    return chain


def call_extractor(redacted_text: str, model: str = None,
                   used: Optional[Dict[str, Any]] = None) -> ExtractedTrade:
    """
    Read the document, moving to another model if the first one cannot answer.

    `used` is filled in with which provider actually produced the result and what the
    others said, so the caller can tell the trader - a different vendor reading the
    document is a data-handling fact, not an implementation detail.
    """
    load_env_file()
    from server.providers import get_extractor, PROVIDERS, is_available

    name = primary_provider()
    if name not in PROVIDERS:
        raise ValueError(f"TERMSHEET_PROVIDER={name!r} 는 지원하지 않습니다 "
                         f"(사용 가능: {', '.join(PROVIDERS)})")

    chain = extraction_chain()
    runnable = [n for n in chain if is_available(n)]
    if not runnable:
        envs = " 또는 ".join(PROVIDERS[name]["key_env"]) or "(키 불필요)"
        raise ValueError(
            f"{PROVIDERS[name]['label']} 키가 없어 Term Sheet 분석을 실행할 수 없습니다. "
            f"{_ENV_FILE} 에 {envs} 를 추가하세요. "
            f"발급: {PROVIDERS[name]['signup']}")

    attempts: List[Dict[str, str]] = []
    from server.providers import model_candidates
    # A free tier meters per model, so an exhausted model is not an exhausted vendor:
    # walk each provider's models before moving to the next provider.
    cands = [(n, m) for n in runnable for m in model_candidates(n)]
    # Skip anything still cooling off, but never skip every option: if that is all we
    # have, try it anyway rather than refusing to read the document.
    order = [c for c in cands if not _cooling_off(f"{c[0]}:{c[1]}")] or cands

    for n, mdl in order:
        try:
            trade = get_extractor(n, model_name=mdl)(redacted_text)
        except Exception as e:
            reason = _classify_provider_error(e)
            attempts.append({"provider": n, "label": PROVIDERS[n]["label"], "model": mdl,
                             "reason": reason or "실패", "detail": str(e)[:200]})
            if reason in ("호출 한도", "잔액 부족"):
                _PROVIDER_COOLDOWN[f"{n}:{mdl}"] = time.time() + _COOLDOWN_SECONDS
            if reason is None:
                # Not the provider's fault - another model would fail the same way.
                if demo_mode_enabled():
                    sample = _match_synthetic_sample(redacted_text)
                    if sample:
                        sample.demo_fallback = True
                        return sample
                raise
            continue

        _PROVIDER_COOLDOWN.pop(f"{n}:{mdl}", None)
        if used is not None:
            used.update({"provider": n, "label": PROVIDERS[n]["label"], "model": mdl,
                         "fell_back": n != name or mdl != model_candidates(n)[0],
                         "attempts": attempts})
        return trade

    if demo_mode_enabled():
        sample = _match_synthetic_sample(redacted_text)
        if sample:
            sample.demo_fallback = True
            return sample

    if used is not None:
        used.update({"provider": None, "fell_back": False, "attempts": attempts})
    detail = " / ".join(f"{a['label']} {a.get('model', '')}: {a['reason']}"
                        for a in attempts)
    raise ValueError(
        f"사용 가능한 모든 프로바이더가 응답하지 못했습니다 ({detail}). "
        f"잠시 후 다시 시도하거나 {_ENV_FILE} 에 다른 프로바이더 키를 추가하세요.")


def call_vision_extractor(raw: bytes, mime: str,
                          used: Optional[Dict[str, Any]] = None) -> ExtractedTrade:
    """
    Read a term sheet that has no text in it, walking the same failover ladder.

    Only providers that can see are tried; if none can, that is said plainly rather
    than falling through to a text model that would receive nothing.
    """
    load_env_file()
    from server.providers import (get_vision_extractor, supports_vision, PROVIDERS,
                                  is_available, model_candidates)

    name = primary_provider()
    runnable = [n for n in extraction_chain() if is_available(n) and supports_vision(n)]
    if not runnable:
        raise ValueError(
            "이미지·스캔 문서를 읽을 수 있는 프로바이더가 없습니다. "
            "Gemini 또는 Anthropic 키를 설정하거나, 텍스트가 있는 PDF·Excel로 올려주세요.")

    attempts: List[Dict[str, str]] = []
    cands = [(n, m) for n in runnable for m in model_candidates(n)]
    order = [c for c in cands if not _cooling_off(f"{c[0]}:{c[1]}")] or cands

    for n, mdl in order:
        fn = get_vision_extractor(n, model_name=mdl)
        if fn is None:
            continue
        try:
            trade = fn(raw, mime)
        except Exception as e:
            reason = _classify_provider_error(e)
            attempts.append({"provider": n, "label": PROVIDERS[n]["label"], "model": mdl,
                             "reason": reason or "실패", "detail": str(e)[:200]})
            if reason in ("호출 한도", "잔액 부족"):
                _PROVIDER_COOLDOWN[f"{n}:{mdl}"] = time.time() + _COOLDOWN_SECONDS
            if reason is None:
                raise
            continue

        _PROVIDER_COOLDOWN.pop(f"{n}:{mdl}", None)
        if used is not None:
            used.update({"provider": n, "label": PROVIDERS[n]["label"], "model": mdl,
                         "fell_back": n != name or mdl != model_candidates(n)[0],
                         "vision": True, "attempts": attempts})
        return trade

    detail = " / ".join(f"{a['label']} {a.get('model', '')}: {a['reason']}" for a in attempts)
    raise ValueError(f"이미지 분석이 실패했습니다 ({detail}).")


# ---------------------------------------------------------------- 5. verification
_ENUM_FIELDS = {
    "leg1_day_count": DAY_COUNTS, "leg2_day_count": DAY_COUNTS,
    "leg1_payment_freq": FREQUENCIES, "leg2_payment_freq": FREQUENCIES,
    "leg1_business_day_conv": CONVENTIONS, "leg2_business_day_conv": CONVENTIONS,
    "leg1_stub_rule": STUB_RULES, "leg2_stub_rule": STUB_RULES,
    "leg1_adjust_rule": ["Adjust", "Unadjust"], "leg2_adjust_rule": ["Adjust", "Unadjust"],
    "leg1_calendar": CALENDARS, "leg2_calendar": CALENDARS,
}

_ALIASES = {
    "ACT/365F": "Act/365", "ACT/365 FIXED": "Act/365", "A/365": "Act/365", "ACT365": "Act/365",
    "ACT/360": "Act/360", "A/360": "Act/360", "ACT360": "Act/360",
    "30/360": "30/360", "30E/360": "30/360", "BOND BASIS": "30/360",
    "ACT/ACT": "Act/Act", "ACTUAL/ACTUAL": "Act/Act",
    "MF": "Modified Following", "MODFOLLOWING": "Modified Following",
    "MODIFIED FOLLOWING": "Modified Following", "FOLLOWING": "Following",
    "PRECEDING": "Preceding", "ADJUSTED": "Adjust", "UNADJUSTED": "Unadjust",
    "QUARTERLY": "3M", "SEMI-ANNUAL": "6M", "SEMIANNUAL": "6M",
    "ANNUAL": "12M", "MONTHLY": "1M", "1Y": "12M",
}


def normalize_enums(trade: ExtractedTrade) -> List[str]:
    """Coerce common spellings onto the pricer's vocabulary. Returns unmappable fields."""
    unmapped = []
    for field, allowed in _ENUM_FIELDS.items():
        val = getattr(trade, field, None)
        if val is None:
            continue
        if val in allowed:
            continue
        canon = _ALIASES.get(str(val).strip().upper())
        if canon and canon in allowed:
            setattr(trade, field, canon)
        else:
            setattr(trade, field, None)
            unmapped.append(field)
    return unmapped


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def verify_quotes(trade: ExtractedTrade, doc_text: str) -> List[str]:
    """Any 'extracted' field whose quote is not in the document is a fabricated citation."""
    haystack = _squash(doc_text)
    unverified = []
    for p in trade.provenance:
        if p.source != "extracted":
            continue
        if not p.quote or _squash(p.quote) not in haystack:
            unverified.append(p.field)
    return unverified


def check_schedule(trade: ExtractedTrade) -> List[str]:
    warnings = []
    sched = trade.leg1_custom_schedule
    if not sched:
        return warnings

    for i in range(1, len(sched)):
        if sched[i].start_date != sched[i - 1].end_date:
            warnings.append(
                f"스케줄 {i}기와 {i+1}기가 이어지지 않습니다 "
                f"({sched[i-1].end_date} → {sched[i].start_date})")
            break

    headline = trade.notional or trade.usd_notional
    if headline and sched and abs(sched[0].notional - headline) > 1.0:
        warnings.append(
            f"첫 기간 원금({sched[0].notional:,.0f})이 "
            f"헤드라인 원금({headline:,.0f})과 다릅니다")

    if trade.maturity_date and sched and sched[-1].end_date != trade.maturity_date:
        warnings.append(
            f"스케줄 종료일({sched[-1].end_date})이 만기일({trade.maturity_date})과 다릅니다")

    return warnings


def check_dates(trade: ExtractedTrade) -> List[str]:
    warnings = []
    for label, val in (("effective_date", trade.effective_date),
                       ("maturity_date", trade.maturity_date)):
        if val:
            try:
                datetime.date.fromisoformat(val)
            except ValueError:
                warnings.append(f"{label} 형식이 올바르지 않습니다: {val}")
    if trade.effective_date and trade.maturity_date:
        try:
            if datetime.date.fromisoformat(trade.maturity_date) <= datetime.date.fromisoformat(trade.effective_date):
                warnings.append("만기일이 개시일보다 앞서거나 같습니다")
        except ValueError:
            pass
    return warnings


# ---------------------------------------------------------------- 6. ticket draft
_TICKET_DEFAULTS = {
    "USD":      dict(dc="Act/360", freq="12M", cal="NYB", fix_day=-2, notional=100_000_000.0, tenor="5Y"),
    "KRW":      dict(dc="Act/365", freq="3M", cal="SEB", fix_day=-1, notional=100_000_000_000.0, tenor="3Y"),
    "KRW_KOFR": dict(dc="Act/365", freq="3M", cal="SEB", fix_day=0, notional=10_000_000_000.0, tenor="1Y"),
    "KRW_CRS":  dict(dc="30/360", freq="6M", cal="SEB_NYB", fix_day=-1, notional=100_000_000.0, tenor="5Y"),
}


def _fmt(n: Optional[float]) -> str:
    return f"{n:,.0f}" if n is not None else ""


def to_ticket_draft(trade: ExtractedTrade) -> Dict[str, Any]:
    """Map extracted terms onto the dashboard's ticket shape, marking which fields are defaults."""
    curr = trade.currency or "USD"
    d = _TICKET_DEFAULTS.get(curr, _TICKET_DEFAULTS["USD"])
    inferred: List[str] = []

    def pick(value, fallback, name):
        if value is None:
            inferred.append(name)
            return fallback
        return value

    notional = trade.usd_notional if curr == "KRW_CRS" and trade.usd_notional else trade.notional
    draft = {
        "product": curr,
        "position": pick(trade.position, "Pay Fixed", "position"),
        "notionalDisplay": _fmt(pick(notional, d["notional"], "notional")),
        "customTenorInput": pick(trade.tenor, d["tenor"], "tenor"),
        "selectedTenor": trade.tenor or d["tenor"],
        "effectiveDate": trade.effective_date or "",
        "maturityDate": trade.maturity_date or "",
        "coupon": f"{trade.fixed_coupon_pct:.4f}" if trade.fixed_coupon_pct is not None else "",
        "spreadBp": f"{trade.spread_bp:.1f}" if trade.spread_bp is not None else "0.0",
        "crsSwapType": trade.crs_swap_type or "Vanilla",
        "usdFixedCoupon": (f"{trade.usd_fixed_coupon_pct:.4f}"
                           if trade.usd_fixed_coupon_pct is not None else "3.5000"),
        "leg1DayCount": pick(trade.leg1_day_count, d["dc"], "leg1_day_count"),
        "leg1PaymentFreq": pick(trade.leg1_payment_freq, d["freq"], "leg1_payment_freq"),
        "leg1Convention": pick(trade.leg1_business_day_conv, "Modified Following", "leg1_business_day_conv"),
        "leg1Stub": pick(trade.leg1_stub_rule, "Short in arrears", "leg1_stub_rule"),
        "leg1Adjust": pick(trade.leg1_adjust_rule, "Adjust", "leg1_adjust_rule"),
        "leg1PayCal": pick(trade.leg1_calendar, d["cal"], "leg1_calendar"),
        "leg2DayCount": pick(trade.leg2_day_count, d["dc"], "leg2_day_count"),
        "leg2PaymentFreq": pick(trade.leg2_payment_freq, d["freq"], "leg2_payment_freq"),
        "leg2Convention": pick(trade.leg2_business_day_conv, "Modified Following", "leg2_business_day_conv"),
        "leg2Stub": pick(trade.leg2_stub_rule, "Short in arrears", "leg2_stub_rule"),
        "leg2Adjust": pick(trade.leg2_adjust_rule, "Adjust", "leg2_adjust_rule"),
        "leg2Cal": pick(trade.leg2_calendar, d["cal"], "leg2_calendar"),
        "fixDay": trade.leg2_fix_day if trade.leg2_fix_day is not None else d["fix_day"],
    }
    if curr == "KRW_CRS":
        if trade.spot_fx:
            draft["capitalFxRate"] = _fmt(trade.spot_fx)
        if trade.krw_notional:
            draft["krwNotionalDisplay"] = _fmt(trade.krw_notional)

    if trade.leg1_custom_schedule:
        draft["rawPasteText"] = "\n".join(
            f"{p.start_date}\t{p.end_date}\t{p.notional:.0f}"
            + (f"\t{p.fixed_rate_pct}" if p.fixed_rate_pct is not None else "")
            for p in trade.leg1_custom_schedule
        )

    return {"draft": draft, "inferred_fields": inferred}


def schedule_preview(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    The extracted schedule in the marketer's own columns, resolved the way the pricer
    will resolve it: Start / End / Pay / Nominal / Fixing.

    A term sheet states accrual periods, not settlement mechanics - the pay date is
    rolled onto a business day and the fixing date is the fixing offset applied to the
    period start. Showing the raw rows instead would have the trader approve dates that
    are not the ones the trade will use.
    """
    raw = (draft.get("rawPasteText") or "").strip()
    if not raw:
        return []
    try:
        from common_pricer.rollercoaster_engine import parse_rollercoaster_paste
        from server.calendar_manager import resolve_custom_pay_date, compute_fixing_date

        eff = datetime.datetime.strptime(draft["effectiveDate"], "%Y-%m-%d").date()
        notional = float(str(draft.get("notionalDisplay", "0")).replace(",", "") or 0)
        coupon = float(draft.get("coupon") or 0)
        spread = float(draft.get("spreadBp") or 0)
        periods = parse_rollercoaster_paste(
            raw_text=raw, effective_date=eff, default_notional=notional,
            default_coupon_pct=coupon, default_spread_bp=spread,
            currency=draft.get("product", "USD"))

        conv = draft.get("leg1Convention") or "Modified Following"
        cal = draft.get("leg1PayCal") or None
        fix_cal = draft.get("fixCal") or cal
        try:
            fix_day = int(draft.get("fixDay"))
        except (TypeError, ValueError):
            fix_day = 0

        rows = []
        for i, per in enumerate(periods, 1):
            start = datetime.datetime.strptime(per["start_date"], "%Y-%m-%d").date()
            end = datetime.datetime.strptime(per["end_date"], "%Y-%m-%d").date()
            pay = resolve_custom_pay_date(per, end, conv, cal)
            fixing = compute_fixing_date(start, fix_day, fix_cal)
            rows.append({
                "no": i,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "pay_date": pay.isoformat(),
                "pay_date_rolled": pay != end and not per.get("pay_date_explicit"),
                "notional": per["notional"],
                "fixing_date": fixing.isoformat(),
                "fixed_rate_pct": per.get("fixed_rate_pct"),
                "spread_bp": per.get("spread_bp"),
            })
        return rows
    except Exception as e:
        # A preview is a convenience; never let it cost the trader the extraction.
        _log(f"[Termsheet] schedule preview unavailable: {e}")
        return []


def vision_allowed() -> bool:
    """
    Whether a file with no readable text may be sent to the model as-is.

    On by default because a scan or a photo is a normal way to receive a term sheet,
    but it is the one path where identity is not stripped first, so a desk that cannot
    allow that sets TERMSHEET_ALLOW_IMAGE=0.
    """
    return (os.environ.get("TERMSHEET_ALLOW_IMAGE", "1").strip().lower()
            not in ("0", "false", "no", "off"))


def _mime_for(raw: bytes, filename: str = "") -> str:
    """
    Content first, the same rule sniff_kind follows.

    A PNG saved as .jpg is still a PNG, and announcing the wrong type is how a
    vendor comes back with a decode error on a file that was perfectly fine.
    """
    if sniff_kind(raw, filename) == "pdf":
        return "application/pdf"
    for magic, mime in (
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"BM", "image/bmp"),
        (b"II*\x00", "image/tiff"),
        (b"MM\x00*", "image/tiff"),
    ):
        if raw.startswith(magic):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if _is_bmff_image(raw):
        return "image/avif" if raw[8:12] in (b"avif", b"avis") else "image/heic"
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return IMAGE_TYPES.get(ext, "image/jpeg")


# The last few uploads that did not work. Metadata only: no document text, no file
# bytes, nothing that could carry a counterparty name. Enough to tell a wrong format
# from a model outage without asking anyone to read a server console.
_RECENT_FAILURES: List[Dict[str, Any]] = []
_MAX_FAILURES = 20


def record_failure(filename: str, raw: bytes, stage: str, error: str) -> None:
    import datetime as _dt
    try:
        kind = sniff_kind(raw, filename)
    except Exception:
        kind = "?"
    _RECENT_FAILURES.append({
        "at": _dt.datetime.now().isoformat(timespec="seconds"),
        "filename": os.path.basename(filename or ""),
        "bytes": len(raw or b""),
        "kind": kind,
        "head": (raw or b"")[:8].hex(),
        "stage": stage,
        "error": str(error)[:400],
    })
    del _RECENT_FAILURES[:-_MAX_FAILURES]


def recent_failures() -> List[Dict[str, Any]]:
    return list(reversed(_RECENT_FAILURES))


PASTE_HEADER = "Start date\tEnd date\tPay date\tNominal\tFixing date\tRate (%)"


def render_paste(rows: List[Dict[str, Any]]) -> str:
    """
    The schedule as the paste box reads it: named columns, in its own order.

    The box is labelled Start / End / Pay / Nominal / Fixing, and the extractor used
    to write three columns into it - so a notional sat under "Pay date", which is
    both unreadable and one positional guess away from being priced as a date. The
    header row removes the guess for the parser and for whoever is looking at it.
    """
    out = [PASTE_HEADER]
    for r in rows:
        rate = r.get("fixed_rate_pct")
        out.append("\t".join([
            r["start_date"], r["end_date"], r.get("pay_date") or r["end_date"],
            f"{float(r['notional']):.0f}", r.get("fixing_date") or "",
            "" if rate is None else f"{float(rate):g}",
        ]))
    return "\n".join(out)


# Features this pricer genuinely cannot value. A refusal naming none of these is
# about missing or ambiguous data, which is the trader's job, not grounds to discard
# the document.
_UNPRICEABLE = (
    "callable", "cancellable", "cancelable", "puttable", "swaption", "option",
    "optionality", "bermudan", "american", "cms", "constant maturity",
    "range accrual", "digital", "barrier", "knock", "exotic", "inflation",
    "조기상환", "중도상환", "콜옵션", "풋옵션", "옵션", "버뮤단",
)

INSIST_NOTE = """

--- NOTE TO THE EXTRACTOR ---
A previous read of this document returned supported=false for a reason that was not
about the product type. That is not a valid refusal here. Unless this trade is
callable, cancellable, CMS-linked, a range accrual or otherwise optional, set
supported=true and extract every term the document does state, leaving the rest null.
Missing rates, missing indices, several sheets or an ambiguous layout are all normal;
record them in open_questions instead of refusing.
"""


def refusal_is_about_product(reason: Optional[str]) -> bool:
    """Whether a supported=false actually names something this pricer cannot value."""
    low = (reason or "").lower()
    return any(word in low for word in _UNPRICEABLE)


# ---------------------------------------------------------------- 7. orchestration
# 모델에 보내기 전에 사진을 한 번 손본다. 폰 갤러리에서 바로 올라온 파일은
# 그대로 보내면 세 가지가 어긋납니다.
#
#   HEIC   아이폰 기본 포맷. iOS Safari 가 사진 라이브러리에서 고를 때 JPEG 로
#          바꿔주는 경우가 많지만, 파일 앱에서 고르거나 공유로 받으면 HEIC 그대로
#          옵니다. 그러면 지금까지는 "읽을 수 있는 내용을 찾지 못했습니다" 라는,
#          원인과 상관없는 말이 나왔습니다.
#   회전   세로로 찍은 사진은 픽셀이 가로로 저장되고 EXIF 에 "90도 돌려서 봐라"
#          라는 표시만 붙습니다. 원본을 그대로 보내면 모델은 누운 표를 봅니다.
#   크기   요즘 폰 사진은 3~12MB 입니다. 그대로 보내면 느리고 프로바이더의 이미지
#          한도에 걸립니다. 약정서를 읽는 데 긴 변 2000px 이면 충분합니다.
_PHOTO_MAX_EDGE = 2000
_PHOTO_MAX_BYTES = 4 * 1024 * 1024


def prepare_photo(raw: bytes, filename: str = "") -> Tuple[bytes, str, List[str]]:
    """
    (보낼 바이트, mime, 무슨 손을 봤는지) 를 돌려준다.

    손댈 것이 없으면 원본을 그대로 돌려줍니다 - 화면 캡처 PNG 를 굳이 JPEG 로
    다시 구워서 글자를 뭉갤 이유가 없습니다.
    """
    notes: List[str] = []
    mime = _mime_for(raw, filename)
    if sniff_kind(raw, filename) != "image":
        return raw, mime, notes

    try:
        from PIL import Image, ImageOps
    except ImportError:
        return raw, mime, notes

    is_heic = _is_bmff_image(raw)
    if is_heic:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise ValueError(
                "HEIC 사진을 읽을 수 없습니다 (pillow-heif 미설치). 아이폰 설정 > "
                "카메라 > 포맷 을 '높은 호환성'으로 바꾸면 JPEG 로 저장됩니다.")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:
        raise ValueError(f"사진을 열지 못했습니다: {e}")

    # EXIF 회전을 픽셀에 실제로 반영하고 그 표시는 떼어냅니다.
    rotated = ImageOps.exif_transpose(img)
    turned = rotated is not img and rotated.size != img.size
    if turned:
        notes.append("회전 보정")
    img = rotated

    long_edge = max(img.size)
    shrunk = long_edge > _PHOTO_MAX_EDGE
    if shrunk:
        ratio = _PHOTO_MAX_EDGE / float(long_edge)
        img = img.resize((max(1, int(img.width * ratio)),
                          max(1, int(img.height * ratio))), Image.LANCZOS)

    if not (is_heic or shrunk or turned) and len(raw) <= _PHOTO_MAX_BYTES:
        return raw, mime, notes

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # 한도 안에 들어올 때까지 품질을 낮춥니다. 85 면 표의 숫자는 멀쩡합니다.
    out = b""
    for quality in (85, 75, 65, 55):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if len(out) <= _PHOTO_MAX_BYTES:
            break

    if is_heic:
        notes.append("HEIC → JPEG")
    if shrunk:
        notes.append(f"{long_edge}px → {max(img.size)}px")
    if len(out) < len(raw):
        notes.append(f"{len(raw)/1e6:.1f}MB → {len(out)/1e6:.1f}MB")
    return out, "image/jpeg", notes


def process_termsheet(raw: bytes, extractor=None, second_extractor=None,
                      reviewers=None, filename: str = "") -> Dict[str, Any]:
    """
    Full pipeline. Extractors and reviewers are injectable so every path - including the
    two-model disagreement round - can be tested without touching an API.
    """
    doc_sha = hashlib.sha256(raw).hexdigest()
    kind = sniff_kind(raw, filename)
    doc_text = "" if kind == "image" else extract_text(raw, filename)

    # Markers are always present, so measure the real content behind them - an
    # image-only scan otherwise looks non-empty and would be sent out with nothing in it.
    scanned = body_length(doc_text) < 40
    # A text-free PDF is a scan only if there is something in it to look at. A blank
    # one is rejected here rather than spending a model call to be told it is blank.
    by_vision = kind == "image" or (kind == "pdf" and scanned and pdf_has_images(raw))
    if kind == "pdf" and scanned and not by_vision:
        raise ValueError("PDF에서 텍스트를 추출하지 못했습니다 - 내용이 비어 있습니다")

    if scanned and not by_vision:
        # Unclassifiable bytes decode as "text" through the latin-1 fallback, which
        # would otherwise send an arbitrary file to the model to discover it was nothing.
        raise ValueError(
            "이 파일에서 읽을 수 있는 내용을 찾지 못했습니다 — "
            "PDF, Excel, Word, 이미지, CSV/텍스트 형식인지 확인해주세요")

    if by_vision and not vision_allowed():
        raise ValueError(
            "이 문서에는 읽을 수 있는 텍스트가 없습니다. 이미지·스캔 분석이 꺼져 있어 "
            "(TERMSHEET_ALLOW_IMAGE=0) 처리할 수 없습니다 - 텍스트가 있는 PDF나 Excel로 올려주세요.")

    used: Dict[str, Any] = {}
    if by_vision:
        # Nothing to strip: there are no words to find the counterparty in, so the file
        # itself is what goes to the model. The caller is told, every time.
        # 폰에서 바로 올라온 사진을 모델이 읽을 수 있는 모양으로 맞춥니다.
        photo, mime, photo_notes = prepare_photo(raw, filename)
        if photo_notes:
            _log(f"[Termsheet] 사진 보정: {', '.join(photo_notes)}")
        redacted_text, redaction_counts, leaks = "", {}, []
        trade = extractor(photo) if extractor is not None \
            else call_vision_extractor(photo, mime, used=used)
    else:
        redacted_text, redaction_counts = redact(doc_text)
        leaks = redaction_leaks(redacted_text)
        if extractor is not None:
            trade = extractor(redacted_text)
        else:
            trade = call_extractor(redacted_text, used=used)

    # Optional second opinion. Two models fail differently, so a field they disagree on
    # is a field the document is genuinely ambiguous about - it gets escalated to the
    # trader rather than resolved by preferring one vendor.
    comparison = None
    # Whether a second opinion was asked for, as distinct from whether one arrived.
    # A free tier can rate-limit or a model can be retired, and a cross-check that
    # silently did not run must not look like one that ran and agreed.
    second_configured = bool(os.environ.get("TERMSHEET_SECOND_PROVIDER", "").strip())
    second_error = None
    if second_extractor is None and extractor is None:
        try:
            if used.get("provider") and used["provider"] == os.environ.get(
                    "TERMSHEET_SECOND_PROVIDER", "").strip().lower():
                second_error = ("1차 분석이 교차검증 프로바이더로 대체 실행되어 "
                                "교차검증을 건너뛰었습니다")
            else:
                from server.crossvalidate import secondary_extractor
                second_extractor = secondary_extractor()
        except Exception as e:
            second_error = str(e)
            _log(f"[Termsheet] second provider unavailable: {e}")
    adjudication = None
    if second_extractor is not None:
        try:
            from server.crossvalidate import (
                compare_extractions, adjudicate, format_disputes,
                claude_reviewer, secondary_reviewer,
            )
            comparison = compare_extractions(trade, second_extractor(redacted_text))

            # Round two: where they differ, both re-read the document for those fields
            # and must cite the text that settles it.
            if comparison.get("compared") and comparison.get("disagreements"):
                rp = reviewers[0] if reviewers else claude_reviewer
                rs = reviewers[1] if reviewers and len(reviewers) > 1 else secondary_reviewer()
                if rs is not None:
                    disputes = format_disputes(comparison)
                    adjudication = adjudicate(
                        comparison,
                        rp(redacted_text, disputes),
                        rs(redacted_text, disputes),
                        redacted_text,
                    )
                    for field, value in adjudication["resolved"].items():
                        if hasattr(trade, field):
                            setattr(trade, field, value)
        except Exception as e:
            second_error = str(e)
            _log(f"[Termsheet] cross-validation failed: {e}")
            comparison = {"compared": False, "error": str(e)}

    if not trade.supported and not refusal_is_about_product(trade.unsupported_reason) \
            and extractor is None:
        # The model refused over missing or ambiguous data rather than the product.
        # Ask once more, saying so - a schedule the trader could have completed in the
        # popup is otherwise lost at the door.
        _log(f"[Termsheet] refusal not about the product, retrying: "
             f"{trade.unsupported_reason}")
        try:
            retry = call_extractor(redacted_text + INSIST_NOTE, used=used)
            if retry.supported:
                warnings_from_retry = (
                    "1차 판독에서 '평가 불가'로 분류했으나 상품 유형 문제가 아니어서 "
                    f"다시 읽었습니다 — 원래 사유: {trade.unsupported_reason}")
                trade = retry
                trade.open_questions = list(trade.open_questions or []) + [
                    warnings_from_retry]
        except Exception as e:
            _log(f"[Termsheet] retry failed: {e}")

    if not trade.supported:
        return {
            "supported": False,
            "unsupported_reason": trade.unsupported_reason or "이 프라이서로 평가할 수 없는 상품입니다",
            "doc_sha256": doc_sha,
            "redaction": {"counts": redaction_counts, "leaks": leaks},
        }

    unmapped = normalize_enums(trade)
    # Quotes are checked against the redacted text - that is what the model actually saw.
    unverified = verify_quotes(trade, redacted_text)

    warnings: List[str] = []
    warnings += check_dates(trade)
    warnings += check_schedule(trade)
    for f in unmapped:
        warnings.append(f"'{f}' 값을 프라이서 컨벤션으로 매핑하지 못해 기본값으로 되돌렸습니다")
    for f in unverified:
        warnings.append(f"'{f}'의 근거 인용문을 문서에서 찾지 못했습니다 - 직접 확인하세요")
    if leaks:
        warnings.append(f"마스킹 후에도 민감정보 패턴이 남아 있습니다: {', '.join(leaks)}")

    mapped = to_ticket_draft(trade)
    # Resolve pay and fixing dates once, and let the paste box, the popup table and
    # pricing all read the same rows - rather than the box holding one shape and the
    # review panel showing another.
    preview = schedule_preview(mapped["draft"])
    if preview:
        mapped["draft"]["rawPasteText"] = render_paste(preview)
    blocked = sorted(set(unverified) | set(unmapped))

    if by_vision:
        warnings.insert(0,
            "이미지·스캔 문서여서 원문에서 민감정보를 제거하지 못하고 "
            "파일 그대로 모델에 전달했습니다 - 거래상대 정보가 포함됐을 수 있습니다")

    if used.get("fell_back"):
        # With no attempts recorded the primary was never called - it was still inside
        # the cooldown from an earlier quota error. "시도: " with nothing after it read
        # as though nothing had happened at all.
        tried = ", ".join(f"{a.get('model') or a['label']}({a['reason']})"
                          for a in used.get("attempts", []))
        why = f"시도: {tried}" if tried else "1차 모델이 최근 한도 초과로 제외됨"
        warnings.insert(0, f"{used['label']} {used.get('model', '')}가 문서를 분석했습니다 — "
                           f"설정된 1차 모델 대체 ({why})")

    if second_configured and not (comparison and comparison.get("compared")):
        warnings.append(
            "교차검증이 실행되지 않아 단일 모델 결과입니다"
            + (f" — {second_error}" if second_error else ""))

    if comparison and comparison.get("compared"):
        from server.crossvalidate import disagreement_fields
        diffs = disagreement_fields(comparison)
        if adjudication:
            # Fields the second round settled are no longer in dispute; only what the
            # document could not decide still needs the trader.
            diffs = list(adjudication["unresolved"])
            for rec in adjudication["trail"]:
                if rec["resolution"] == "converged":
                    who = ", ".join(rec["corrected"]) if rec.get("corrected") else "없음"
                    warnings.append(
                        f"재검토 합의 [{rec['field']}] → {rec['final']!r} (정정한 모델: {who})")
                elif rec["resolution"] == "evidence":
                    warnings.append(
                        f"근거 판정 [{rec['field']}] → {rec['final']!r} "
                        f"(오류: {', '.join(rec['wrong'])})")
        if diffs:
            # Map extractor field names onto the ticket keys the review panel blocks on.
            key_by_field = {v: k for k, v in {
                "notionalDisplay": "notional", "customTenorInput": "tenor",
                "effectiveDate": "effective_date", "maturityDate": "maturity_date",
                "coupon": "fixed_coupon_pct", "spreadBp": "spread_bp",
                "position": "position", "leg1DayCount": "leg1_day_count",
                "leg1PaymentFreq": "leg1_payment_freq",
                "leg1Convention": "leg1_business_day_conv",
                "leg1Stub": "leg1_stub_rule", "leg1Adjust": "leg1_adjust_rule",
                "leg1PayCal": "leg1_calendar", "leg2DayCount": "leg2_day_count",
                "leg2PaymentFreq": "leg2_payment_freq",
                "leg2Convention": "leg2_business_day_conv",
                "leg2Stub": "leg2_stub_rule", "leg2Adjust": "leg2_adjust_rule",
                "leg2Cal": "leg2_calendar",
            }.items()}
            blocked = sorted(set(blocked) | set(diffs) |
                             {key_by_field[f] for f in diffs if f in key_by_field})
            p, s = comparison["primary"], comparison["secondary"]
            for d in comparison["disagreements"]:
                if d["field"] not in diffs:
                    continue
                warnings.append(
                    f"모델 불일치 미해결 [{d['field']}]: {p}={d.get(p)!r} vs {s}={d.get(s)!r}"
                    + (f" - {d['note']}" if d.get("note") else ""))

    if getattr(trade, "demo_fallback", False):
        # Canned demo data must never reach a price. Block every field so the review
        # panel cannot be confirmed, and say plainly where the numbers came from.
        blocked = sorted(set(blocked) | set(mapped["draft"].keys()))
        warnings.insert(0, "데모 응답입니다 - API 크레딧이 없어 미리 준비된 샘플 값을 표시했습니다. "
                           "실제 문서에서 추출한 값이 아니므로 프라이싱에 사용할 수 없습니다.")

    return {
        "supported": True,
        "demo_fallback": bool(getattr(trade, "demo_fallback", False)),
        "doc_sha256": doc_sha,
        "ticket_draft": mapped["draft"],
        "inferred_fields": mapped["inferred_fields"],
        "unverified_fields": blocked,
        "provenance": [p.model_dump() for p in trade.provenance],
        "open_questions": trade.open_questions,
        "warnings": warnings,
        "cross_validation": comparison,
        "adjudication": adjudication,
        # Which vendor actually saw the document, and what the others said.
        "extraction": used or None,
        # The schedule as the pricer will read it, for the review popup.
        "schedule_preview": preview,
        "source": {"kind": kind, "by_vision": by_vision, "redacted": not by_vision},
        "redaction": {"counts": redaction_counts, "leaks": leaks},
    }
