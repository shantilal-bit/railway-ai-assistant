"""PDF Validation, R2/Google Drive Download, Digital + Bilingual OCR Extraction, and Rule-Aware Chunking Pipeline."""

from __future__ import annotations

import hashlib
import html
import io
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import fitz  # PyMuPDF
import httpx
import pytesseract
from PIL import Image

MAX_PDF_UPLOAD_BYTES = int(os.getenv("MAX_PDF_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MIN_NATIVE_TEXT_CHARS = 40

CHAPTER_HEADER_PATTERN = re.compile(
    r"(?:^|\n)\s*((?:CHAPTER|Chapter|अध्याय|SECTION|Section|PART|Part)\s+[IVXLCDM0-9A-Z]+[^\n]{0,90})",
    re.MULTILINE,
)

# Strict line-anchored / whitespace-bounded pattern exported for compatibility;
# structural parsing uses _parse_rule_heading_line() + normalize_rule_label().
RULE_HEADER_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:"
    r"(?:G\.?\s*R\.?|S\.?\s*R\.?|GR/SR|SR/GR)\s*(?:No\.?)?(?:\s+|(?=\d))\d{1,3}(?:\.\d{1,3})+(?:[A-Z])?(?:-\d+)?(?:\([0-9a-zA-Z]+\))*(?:-\d+)?"
    r"|"
    r"(?:Rule|Para|Paragraph|Clause|Sub-rule|RBE|Circular|नियम|पैरा)\s*(?:No\.?|सं\.?)?(?:\s+|(?=\d))[A-Z0-9][A-Z0-9./()-]{0,28}"
    r")(?=$|[\s.,:;—–-])",
    re.MULTILINE,
)

DRIVE_FILE_ID_PATTERNS = [
    re.compile(r"/file/d/([a-zA-Z0-9_-]{10,})"),
    re.compile(r"/d/([a-zA-Z0-9_-]{10,})"),
]

TOP_MARGIN_MAX_RATIO = 0.14
BOTTOM_MARGIN_MIN_RATIO = 0.86

KNOWN_FALSE_POSITIVE_RULE_WORDS = {
    "rule",
    "rules",
    "green",
    "granted",
    "great",
    "gradients",
    "gradient",
    "group",
    "grade",
    "ground",
    "para",
    "paragraph",
    "clause",
    "sub-rule",
    "subrule",
    "circular",
    "section",
    "chapter",
    "part",
    "note",
    "notes",
    "sr",
    "gr",
    "rbe",
    "general",
    "subsidiary",
}

_FALSE_PREFIX_WITH_DIGITS_RE = re.compile(
    r"^(?:rules|green|granted|great|gradients?|group|grade|ground|general|subsidiary)\b",
    re.IGNORECASE,
)
_GLUED_LOWER_SUFFIX_RE = re.compile(r"(?:\d|\))[a-z]{2,}$")
_TRAILING_LABEL_NOISE_RE = re.compile(r"[.,:;/-]+$")

_SUBCLAUSE_PAREN_GROUP = r"(?:\s*\((?:\d{1,3}|[a-zA-Z]{1,2}|i{1,3}|iv|vi{0,3}|ix|x)\))*"
_RULE_NUM_CORE = (
    r"(?P<num>\d{1,3}(?:\.\d{1,3})+(?:[A-Z])?(?:-\d+)?"
    + _SUBCLAUSE_PAREN_GROUP
    + r"(?:-\d+)?)"
)

_EXPLICIT_GR_LINE_RE = re.compile(
    r"^\s*(?:[gG]\.?\s*[rR]\.?|[gG]eneral\s+[rR]ule)\s*(?:[nN]o\.?\s*)?(?:\s+|(?=\d))"
    + _RULE_NUM_CORE
    + r"(?=$|[\s.,:;—–-])",
)

_EXPLICIT_SR_LINE_RE = re.compile(
    r"^\s*(?:[sS]\.?\s*[rR]\.?|[sS]ubsidiary\s+[rR]ule)\s*(?:[nN]o\.?\s*)?(?:\s+|(?=\d))"
    + _RULE_NUM_CORE
    + r"(?=$|[\s.,:;—–-])",
)

_EXPLICIT_GR_SR_LINE_RE = re.compile(
    r"^\s*(?:[gG]\.?\s*[rR]\.?/[sS]\.?\s*[rR]\.?|[sS]\.?\s*[rR]\.?/[gG]\.?\s*[rR]\.?)\s*(?:[nN]o\.?\s*)?(?:\s+|(?=\d))"
    + _RULE_NUM_CORE
    + r"(?=$|[\s.,:;—–-])",
)

_EXPLICIT_OTHER_LINE_RE = re.compile(
    r"^\s*(?P<prefix>Rule|Para|Paragraph|Clause|Sub-rule|Subrule|RBE|Circular|JPO|नियम|पैरा)\s*(?:No\.?|सं\.?)?\s*"
    r"(?P<num>(?:\d{1,4}(?:\.\d{1,3})*(?:[-]?[A-Z])?(?:\([0-9a-zA-Z]+\))*)|(?:[A-Z0-9]+(?:[/-][A-Z0-9]+)+))"
    r"(?=$|[\s.,:;—–-])",
    re.IGNORECASE,
)

# Unprefixed numbered G&SR heading (e.g. "5.13. Duties of Pointsman.—")
_UNPREFIXED_GSR_LINE_RE = re.compile(
    r"^\s*(?P<num>\d{1,2}\.\d{2}(?:\([0-9a-zA-Z]+\))*)"
    r"(?=[.\s—–:-]|$)(?P<sep>[.\s—–:-]*)(?P<rest>.*)$",
)

# Standalone rule-number token on its own line/block before heading text on next line or to the right
_STANDALONE_RULE_NUM_LINE_RE = re.compile(
    r"^\s*(?:"
    r"(?:[gG]\.?\s*[rR]\.?|[sS]\.?\s*[rR]\.?|[gG]\.?\s*[rR]\.?/[sS]\.?\s*[rR]\.?|[sS]\.?\s*[rR]\.?/[gG]\.?\s*[rR]\.?|Rule|Para|नियम)\s*(?:No\.?\s*)?"
    r")?\d{1,3}(?:\.\d{1,3})+(?:[A-Z])?(?:-\d+)?"
    + _SUBCLAUSE_PAREN_GROUP
    + r"(?:-\d+)?[.:—–-]?\s*$",
)

_HEADING_NEXT_LINE_START_RE = re.compile(
    r"^(?:[A-Z\u0900-\u097F]|\((?:\d{1,3}|[a-zA-Z]{1,2}|i{1,3}|iv|vi{0,3}|ix|x)\))"
)

_MEASUREMENT_UNIT_START_RE = re.compile(
    r"^(?:m|metre|metres|meter|meters|km|kmph|k\.m\.|mph|km/h|cm|mm|kg|tonnes?|hrs?|hours?|mins?|minutes?|secs?|seconds?|%|percent|per|times?|fold|lakhs?|crores?|rs\.?|rupees?|days?|months?|years?|litres?|liters?|gms?|grams?|volts?|amps?|watts?|hz|degrees?)\b",
    re.IGNORECASE,
)

_INLINE_CROSS_REF_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?:G\.?\s*R\.?|S\.?\s*R\.?|Rule|Para|RBE|Circular)\s*(?:No\.?)?\s*"
    r"(?:\d{1,4}(?:\.\d{1,3})+(?:[A-Z])?(?:-\d+)?(?:\([0-9a-zA-Z]+\))*|\d{1,4}/\d{2,4})"
    r"(?=$|[\s.,;:)])",
)

# Detect line endings that introduce an inline cross-reference wrapping onto the next line
_PREV_LINE_REF_INTRO_RE = re.compile(
    r"(?:\b(?:see|refer(?:\s+to)?|vide|under|as\s+per|prescribed\s+in|laid\s+down\s+in|provisions?\s+of|read\s+with|in\s+terms\s+of|of|in|to|by|and|or)|[,(])\s*$",
    re.IGNORECASE,
)

_RUNNING_MARGIN_LINE_RE = re.compile(
    r"^(?:"
    r"general\s*(?:and|&)\s*subsidiary\s*rules(?:\s*[-–—].*)?"
    r"|g\s*&\s*s\s*r(?:\s*[-–—].*)?"
    r"|indian\s+railways?(?:\s+general\s*(?:and|&)\s*subsidiary\s*rules)?"
    r"|western\s+railway(?:\s*[-–—].*)?"
    r"|central\s+railway(?:\s*[-–—].*)?"
    r"|northern\s+railway(?:\s*[-–—].*)?"
    r"|southern\s+railway(?:\s*[-–—].*)?"
    r"|eastern\s+railway(?:\s*[-–—].*)?"
    r"|south\s+(?:central|eastern|western)\s+railway(?:\s*[-–—].*)?"
    r"|corrected\s*(?:up\s*to|upto)\s*c\.?\s*s\.?.*"
    r"|correction\s+slip\s*(?:no\.?)?.*"
    r")$",
    re.IGNORECASE,
)


class PdfPipelineError(ValueError):
    """Raised when PDF validation, download, or text/OCR extraction fails."""


@dataclass(frozen=True)
class PageLineInfo:
    text: str
    is_bold: bool | None = None
    bbox: tuple[float, float, float, float] | None = None
    leading_is_bold: bool | None = None
    heading_prefix_is_bold: bool | None = None
    is_running_margin: bool = False


@dataclass
class ExtractedPage:
    physical_page_number: int
    text: str
    printed_page_candidate: int | None = None
    printed_page_status: str = "NO_MARGIN_CANDIDATE"
    used_ocr: bool = False
    typography_available: bool = False
    lines: tuple[PageLineInfo, ...] = ()
    removed_margin_lines: tuple[str, ...] = ()


@dataclass
class ExtractedChunk:
    chunk_index: int
    page_number: int
    rule_number: str | None
    chapter: str | None
    section_title: str | None
    content: str
    token_count: int
    physical_page_number: int | None = None
    printed_page_candidate: int | None = None
    printed_page_status: str = "UNAVAILABLE"
    rule_kind: str | None = None
    parent_rule: str | None = None
    contained_rules: tuple[str, ...] = ()
    cross_references: tuple[str, ...] = ()
    is_continuation: bool = False
    continued_from_rule: str | None = None
    classification_confidence: str = "NONE"
    source_start_offset: int | None = None
    source_end_offset: int | None = None

    def __post_init__(self) -> None:
        if self.physical_page_number is None:
            self.physical_page_number = self.page_number


@dataclass(frozen=True)
class _ParsedHeading:
    label: str
    base_label: str
    base_digits: str
    rule_kind: str
    confidence: str
    parent_rule: str | None = None



def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_pdf_bytes(pdf_bytes: bytes, max_bytes: int = MAX_PDF_UPLOAD_BYTES) -> None:
    if not pdf_bytes:
        raise PdfPipelineError("PDF file is empty.")
    if len(pdf_bytes) > max_bytes:
        mb = max_bytes / (1024 * 1024)
        raise PdfPipelineError(f"PDF exceeds maximum allowed size of {mb:.0f} MB.")
    header_window = pdf_bytes[:1024]
    if b"%PDF-" not in header_window:
        raise PdfPipelineError("Invalid file format: missing PDF header signature.")


def download_pdf_from_r2(r2_client: Any, bucket_name: str, object_key: str) -> bytes:
    """Downloads an official PDF from the private Cloudflare R2 bucket and validates it."""
    response = r2_client.get_object(Bucket=bucket_name, Key=object_key)
    body = response["Body"].read()
    validate_pdf_bytes(body)
    return body


def upload_pdf_to_r2(r2_client: Any, bucket_name: str, object_key: str, pdf_bytes: bytes) -> None:
    validate_pdf_bytes(pdf_bytes)
    r2_client.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )


def extract_google_drive_file_id(share_url: str) -> str:
    """Validates a public Google Drive URL and extracts the file ID (SSRF-safe)."""
    cleaned = (share_url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {
        "drive.google.com",
        "docs.google.com",
        "drive.usercontent.google.com",
    }:
        raise PdfPipelineError("Only HTTPS Google Drive share URLs are permitted.")

    for pattern in DRIVE_FILE_ID_PATTERNS:
        m = pattern.search(parsed.path)
        if m:
            return m.group(1)

    qs = parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        candidate = qs["id"][0].strip()
        if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", candidate):
            return candidate

    raise PdfPipelineError("Could not parse a valid Google Drive file ID from URL.")


async def download_public_google_drive_pdf(
    share_url: str,
    max_bytes: int = MAX_PDF_UPLOAD_BYTES,
    client: httpx.AsyncClient | None = None,
) -> tuple[bytes, str]:
    """Downloads a publicly shared Google Drive PDF, handling virus-scan confirmation forms safely."""
    file_id = extract_google_drive_file_id(share_url)
    initial_url = f"https://drive.google.com/uc?export=download&id={file_id}"

    async def _fetch(c: httpx.AsyncClient) -> tuple[bytes, str]:
        resp = await c.get(initial_url, follow_redirects=True)
        resp.raise_for_status()
        data = resp.content
        filename = _filename_from_headers(resp.headers) or f"drive_{file_id}.pdf"

        if b"%PDF-" not in data[:1024]:
            content_type = resp.headers.get("content-type", "").lower()
            if "text/html" in content_type or b"<html" in data[:2048].lower():
                confirm_url = _extract_drive_confirm_url(data.decode("utf-8", errors="ignore"), file_id)
                if not confirm_url:
                    raise PdfPipelineError(
                        "Google Drive file is not publicly downloadable as a PDF. "
                        "Ensure sharing is set to 'Anyone with the link'."
                    )
                resp2 = await c.get(confirm_url, follow_redirects=True)
                resp2.raise_for_status()
                data = resp2.content
                filename = _filename_from_headers(resp2.headers) or filename

        validate_pdf_bytes(data, max_bytes=max_bytes)
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        return data, filename

    if client is not None:
        return await _fetch(client)

    async with httpx.AsyncClient(timeout=90.0) as owned_client:
        return await _fetch(owned_client)


def _filename_from_headers(headers: httpx.Headers) -> str | None:
    cd = headers.get("content-disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]+)"?', cd, re.IGNORECASE)
    if m:
        name = os.path.basename(m.group(1).strip())
        return re.sub(r"[^a-zA-Z0-9._-]", "_", name) or None
    return None


def _extract_drive_confirm_url(html_text: str, file_id: str) -> str | None:
    action_match = re.search(r'action="(https://drive\.usercontent\.google\.com/download[^"]*)"', html_text)
    if action_match:
        base = html.unescape(action_match.group(1))
        params = dict(re.findall(r'name="([^"]+)"\s+value="([^"]*)"', html_text))
        query = "&".join(f"{k}={html.unescape(v)}" for k, v in params.items())
        return f"{base}?{query}" if "?" not in base and query else base

    confirm_match = re.search(r'confirm=([a-zA-Z0-9_-]+)', html_text)
    if confirm_match:
        token = confirm_match.group(1)
        return f"https://drive.google.com/uc?export=download&confirm={token}&id={file_id}"
    return None


def normalize_rule_label(candidate: str | None) -> str | None:
    """Normalizes S.R./SR, G.R./GR, and sub-clause spacing cleanly before validation."""
    raw = re.sub(r"\s+", " ", (candidate or "").replace("\x00", " ")).strip()
    if not raw:
        return None
    raw = re.sub(r"^(?:G\.?\s*R\.?\s*/\s*S\.?\s*R\.?|S\.?\s*R\.?\s*/\s*G\.?\s*R\.?)\s*(?:No\.?\s*)?", "GR/SR ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^(?:G\.?\s*R\.?|General\s+Rule)\s*(?:No\.?\s*)?(?=\d)", "GR ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^(?:S\.?\s*R\.?|Subsidiary\s+Rule)\s*(?:No\.?\s*)?(?=\d)", "SR ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"(\d(?:[A-Z])?(?:-\d+)?)\s+(?=\([0-9a-zA-Z]+\))", r"\1", raw)
    raw = re.sub(r"\)\s+(?=\([0-9a-zA-Z]+\))", ")", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return validate_rule_label(raw)


def validate_rule_label(candidate: str | None) -> str | None:
    """Validates and normalizes a rule number label, rejecting false-positive prose words and glued suffixes."""
    raw = re.sub(r"\s+", " ", (candidate or "").replace("\x00", " ")).strip()
    if not raw:
        return None
    cleaned = _TRAILING_LABEL_NOISE_RE.sub("", raw).strip()
    if not cleaned or cleaned.lower() in KNOWN_FALSE_POSITIVE_RULE_WORDS:
        return None
    if not any(ch.isdigit() for ch in cleaned):
        return None
    if _FALSE_PREFIX_WITH_DIGITS_RE.match(cleaned):
        return None
    if cleaned.count("(") != cleaned.count(")"):
        return None
    if _GLUED_LOWER_SUFFIX_RE.search(cleaned):
        return None
    return cleaned[:80]


def _extract_base_digits(num_str: str) -> str:
    m = re.match(r"(\d+(?:\.\d+)*)", num_str.strip())
    return m.group(1) if m else num_str.strip()


def _compute_rule_hierarchy(rule_kind: str, norm_num: str, prefix_display: str) -> tuple[str, str, str | None]:
    """Computes (base_digits, base_label, parent_rule) handling dotted SR 5.13.1/5.13.2 and paren sub-rules."""
    cleaned_num = norm_num.strip()
    if rule_kind == "SR":
        # Dotted SR sub-rule under 2-level G&SR parent (e.g. SR 5.13.1, SR 5.13.2(a) -> parent SR 5.13)
        m_dotted = re.match(r"^(\d{1,2}\.\d{2})\.(\d+)(.*)$", cleaned_num)
        if m_dotted:
            parent_digits = m_dotted.group(1)
            parent_label = f"SR {parent_digits}"
            return parent_digits, parent_label, parent_label
        # Dash or parenthesized SR sub-rule (e.g. SR 5.13(1), SR 5.13-1(a) -> parent SR 5.13)
        m_sub = re.match(r"^(\d{1,2}\.\d{2}[A-Z]?)(?:\(|-\d+)", cleaned_num)
        if m_sub:
            parent_digits = _extract_base_digits(m_sub.group(1))
            parent_label = f"SR {parent_digits}"
            return parent_digits, parent_label, parent_label

    if rule_kind in {"GR", "GR_SR"}:
        m_sub = re.match(r"^(\d{1,2}\.\d{2}[A-Z]?)(?:\(|-\d+)", cleaned_num)
        if m_sub:
            parent_digits = _extract_base_digits(m_sub.group(1))
            parent_label = f"{prefix_display} {parent_digits}"
            return parent_digits, parent_label, parent_label

    base_digits = _extract_base_digits(cleaned_num)
    base_label = f"{prefix_display} {base_digits}"
    if rule_kind == "RULE" and ("(" in cleaned_num or "-" in cleaned_num):
        return base_digits, base_label, base_label
    return base_digits, base_label, None


def _parse_rule_heading_line(
    line_text: str,
    is_bold: bool | None = None,
    typography_available: bool = False,
    leading_is_bold: bool | None = None,
    heading_prefix_is_bold: bool | None = None,
) -> _ParsedHeading | None:
    """Identifies structural GR/SR/Rule headings at line start without matching mid-sentence words."""
    line = (line_text or "").strip()
    if not line:
        return None

    m_gr_sr = _EXPLICIT_GR_SR_LINE_RE.match(line)
    if m_gr_sr:
        num = re.sub(r"\s+", "", m_gr_sr.group("num"))
        label = normalize_rule_label(f"GR/SR {num}")
        if label:
            norm_num = label.split(" ", 1)[1] if " " in label else num
            base, base_label, parent_rule = _compute_rule_hierarchy("GR_SR", norm_num, "GR/SR")
            return _ParsedHeading(
                label=label,
                base_label=base_label,
                base_digits=base,
                rule_kind="GR_SR",
                confidence="HIGH",
                parent_rule=parent_rule,
            )

    m_gr = _EXPLICIT_GR_LINE_RE.match(line)
    if m_gr:
        num = re.sub(r"\s+", "", m_gr.group("num"))
        label = normalize_rule_label(f"GR {num}")
        if label:
            norm_num = label.split(" ", 1)[1] if " " in label else num
            base, base_label, parent_rule = _compute_rule_hierarchy("GR", norm_num, "GR")
            return _ParsedHeading(
                label=label,
                base_label=base_label,
                base_digits=base,
                rule_kind="GR",
                confidence="HIGH",
                parent_rule=parent_rule,
            )

    m_sr = _EXPLICIT_SR_LINE_RE.match(line)
    if m_sr:
        num = re.sub(r"\s+", "", m_sr.group("num"))
        label = normalize_rule_label(f"SR {num}")
        if label:
            norm_num = label.split(" ", 1)[1] if " " in label else num
            base, base_label, parent_rule = _compute_rule_hierarchy("SR", norm_num, "SR")
            return _ParsedHeading(
                label=label,
                base_label=base_label,
                base_digits=base,
                rule_kind="SR",
                confidence="HIGH",
                parent_rule=parent_rule,
            )

    m_other = _EXPLICIT_OTHER_LINE_RE.match(line)
    if m_other:
        raw_prefix = m_other.group("prefix").strip()
        num = m_other.group("num").strip()
        prefix_norm_map = {
            "rule": "Rule",
            "para": "Para",
            "paragraph": "Para",
            "clause": "Clause",
            "sub-rule": "Sub-rule",
            "subrule": "Sub-rule",
            "rbe": "RBE",
            "circular": "Circular",
            "jpo": "JPO",
            "नियम": "नियम",
            "पैरा": "पैरा",
        }
        prefix = prefix_norm_map.get(raw_prefix.lower(), raw_prefix)
        label = normalize_rule_label(f"{prefix} {num}")
        if label:
            kind = prefix.upper() if prefix.upper() in {"RBE", "CIRCULAR", "JPO", "PARA"} else "RULE"
            norm_num = label.split(" ", 1)[1] if " " in label else num
            base, base_label, parent_rule = _compute_rule_hierarchy(kind, norm_num, prefix)
            return _ParsedHeading(
                label=label,
                base_label=base_label,
                base_digits=base,
                rule_kind=kind,
                confidence="HIGH",
                parent_rule=parent_rule,
            )

    # Unprefixed numbered G&SR heading (e.g. "5.13. Duties of Pointsman.—")
    m_unpref = _UNPREFIXED_GSR_LINE_RE.match(line)
    if m_unpref:
        num = m_unpref.group("num")
        rest = (m_unpref.group("rest") or "").strip()
        # Reject quantities/measurements like "5.13 metres" or "12.00 hours" and require substantive heading text
        if not rest or _MEASUREMENT_UNIT_START_RE.match(rest):
            return None
        if not _HEADING_NEXT_LINE_START_RE.match(rest):
            return None
        has_bold_rule_num = (
            leading_is_bold is True
            or heading_prefix_is_bold is True
            or is_bold is True
        )
        if typography_available and has_bold_rule_num:
            label = normalize_rule_label(f"GR {num}")
            if label:
                norm_num = label.split(" ", 1)[1] if " " in label else num
                base, base_label, parent_rule = _compute_rule_hierarchy("GR", norm_num, "GR")
                return _ParsedHeading(
                    label=label,
                    base_label=base_label,
                    base_digits=base,
                    rule_kind="GR",
                    confidence="HIGH",
                    parent_rule=parent_rule,
                )
        # On OCR pages or non-bold/uncertain typography, preserve unclassified RULE identity without guessing GR/SR
        label = normalize_rule_label(f"Rule {num}")
        if label:
            norm_num = label.split(" ", 1)[1] if " " in label else num
            base, base_label, parent_rule = _compute_rule_hierarchy("RULE", norm_num, "Rule")
            return _ParsedHeading(
                label=label,
                base_label=base_label,
                base_digits=base,
                rule_kind="RULE",
                confidence="UNCLASSIFIED",
                parent_rule=parent_rule,
            )

    return None


def _extract_inline_cross_references(text: str, exclude_labels: set[str]) -> tuple[str, ...]:
    refs: list[str] = []
    seen: set[str] = set()
    for lbl in exclude_labels:
        norm = normalize_rule_label(lbl)
        if norm:
            seen.add(norm.lower())
        seen.add(lbl.lower())
    for m in _INLINE_CROSS_REF_RE.finditer(text or ""):
        cand = normalize_rule_label(m.group(0))
        if cand and cand.lower() not in seen:
            seen.add(cand.lower())
            refs.append(cand)
    return tuple(refs)


def _span_is_bold(span: dict[str, Any]) -> tuple[bool, bool]:
    """Returns (has_font_metadata, is_bold) for a PyMuPDF span dict."""
    font_name = str(span.get("font") or "")
    flags = int(span.get("flags") or 0)
    has_meta = bool(font_name.strip()) or (flags != 0)
    sp_bold = bool(flags & 16) or any(
        k in font_name.lower() for k in ("bold", "black", "heavy", "demi", "semibold")
    )
    return has_meta, sp_bold


def _compute_line_typography(spans: list[dict[str, Any]]) -> tuple[str, bool | None, bool | None, bool | None, bool]:
    """Computes clean line text plus (is_bold, leading_is_bold, heading_prefix_is_bold, any_font_meta)."""
    stream: list[tuple[str, bool, bool]] = []
    prev_was_space = True
    for sp in spans:
        raw_txt = str(sp.get("text") or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
        has_meta, sp_bold = _span_is_bold(sp)
        for ch in raw_txt:
            if ch == " ":
                if not prev_was_space:
                    stream.append((" ", False, False))
                    prev_was_space = True
            else:
                stream.append((ch, has_meta, sp_bold))
                prev_was_space = False

    while stream and stream[-1][0] == " ":
        stream.pop()

    clean_text = "".join(c[0] for c in stream)
    if not clean_text:
        return "", None, None, None, False

    any_meta = any(c[1] for c in stream if c[0] != " ")
    if not any_meta:
        return clean_text, None, None, None, False

    def _ratio_flag(slice_items: list[tuple[str, bool, bool]], true_thresh: float = 0.70, false_thresh: float = 0.30) -> bool | None:
        meta_chars = [item for item in slice_items if item[0] != " " and item[1]]
        if not meta_chars:
            return None
        bold_cnt = sum(1 for item in meta_chars if item[2])
        ratio = bold_cnt / len(meta_chars)
        if ratio >= true_thresh:
            return True
        if ratio <= false_thresh:
            return False
        return None

    line_is_bold = _ratio_flag(stream)

    # Leading rule-number span (e.g. "5.13." or "G.R. 5.13(1)")
    m_lead = re.match(
        r"^\s*(?:(?:[gG]\.?\s*[rR]\.?|[sS]\.?\s*[rR]\.?|[gG]\.?\s*[rR]\.?/[sS]\.?\s*[rR]\.?|Rule|Para|Clause)\s*(?:No\.?\s*)?)?"
        r"\d{1,3}(?:\.\d{1,3})+(?:[A-Z])?(?:-\d+)?"
        + _SUBCLAUSE_PAREN_GROUP
        + r"[.:—–-]?",
        clean_text,
    )
    if m_lead:
        leading_is_bold = _ratio_flag(stream[: m_lead.end()], true_thresh=0.75, false_thresh=0.25)
    else:
        leading_is_bold = line_is_bold

    # Heading prefix up to separator dash (— / – / :-) or first 65 chars
    m_delim = re.search(r"[—–]|:-", clean_text)
    prefix_end = m_delim.start() if (m_delim and 4 <= m_delim.start() <= 90) else min(len(stream), 65)
    heading_prefix_is_bold = _ratio_flag(stream[:prefix_end], true_thresh=0.70, false_thresh=0.30)

    return clean_text, line_is_bold, leading_is_bold, heading_prefix_is_bold, True


def _merge_same_row_fragments(items: list[dict[str, Any]], eff_width: float) -> list[dict[str, Any]]:
    """Merges side-by-side fragments belonging to the same visual row (e.g. left-margin rule number + heading)."""
    if len(items) <= 1:
        return items

    sorted_items = sorted(
        items,
        key=lambda it: (round(it["bbox"][1], 1), it["bbox"][0], it["orig_idx"]),
    )
    merged: list[dict[str, Any]] = []
    for curr in sorted_items:
        if not merged:
            merged.append(curr)
            continue
        prev = merged[-1]
        pb = prev["bbox"]
        cb = curr["bbox"]
        h_min = max(1.0, min(pb[3] - pb[1], cb[3] - cb[1]))
        y_overlap = min(pb[3], cb[3]) - max(pb[1], cb[1])
        yc_diff = abs((pb[1] + pb[3]) * 0.5 - (cb[1] + cb[3]) * 0.5)
        same_row = (y_overlap >= 0.40 * h_min) or (yc_diff <= 5.0)
        left_to_right = pb[2] <= cb[0] + 25.0
        horiz_gap = cb[0] - pb[2]
        prev_is_rule_num = bool(_STANDALONE_RULE_NUM_LINE_RE.match(prev["text"]))
        should_merge = same_row and left_to_right and (
            horiz_gap <= max(36.0, eff_width * 0.12)
            or (prev_is_rule_num and horiz_gap <= eff_width * 0.35)
        )
        if should_merge:
            prev["spans"] = [*prev["spans"], {"text": " ", "font": "", "flags": 0}, *curr["spans"]]
            prev["text"] = f"{prev['text']} {curr['text']}".strip()
            prev["bbox"] = (min(pb[0], cb[0]), min(pb[1], cb[1]), max(pb[2], cb[2]), max(pb[3], cb[3]))
        else:
            merged.append(curr)
    return merged


def _order_and_merge_page_lines(raw_items: list[dict[str, Any]], page_width: float) -> list[dict[str, Any]]:
    """Orders PyMuPDF body lines in visual reading order, handling multi-column layouts and split same-row lines."""
    if not raw_items:
        return []
    if not all(it.get("bbox") is not None for it in raw_items):
        return raw_items

    eff_width = page_width if page_width > 0 else max(it["bbox"][2] for it in raw_items)
    if eff_width <= 0:
        return sorted(raw_items, key=lambda it: it["orig_idx"])

    mid_x = eff_width * 0.5
    left_wide = [
        it for it in raw_items
        if it["bbox"][2] <= mid_x - 4.0 and (it["bbox"][2] - it["bbox"][0]) >= eff_width * 0.14
    ]
    right_wide = [
        it for it in raw_items
        if it["bbox"][0] >= mid_x + 4.0 and (it["bbox"][2] - it["bbox"][0]) >= eff_width * 0.14
    ]

    overlap_pairs = 0
    for lw in left_wide:
        lb = lw["bbox"]
        if any((min(lb[3], rw["bbox"][3]) - max(lb[1], rw["bbox"][1])) >= 2.0 for rw in right_wide):
            overlap_pairs += 1

    is_multi_column = (len(left_wide) >= 2) and (len(right_wide) >= 2) and (overlap_pairs >= 2)
    if not is_multi_column:
        return _merge_same_row_fragments(list(raw_items), eff_width)

    spanning = sorted(
        [
            it for it in raw_items
            if it["bbox"][0] < mid_x - 15.0 and it["bbox"][2] > mid_x + 15.0
        ],
        key=lambda it: (round(it["bbox"][1], 1), it["bbox"][0], it["orig_idx"]),
    )
    spanning_ids = {id(it) for it in spanning}
    col_items = [it for it in raw_items if id(it) not in spanning_ids]

    ordered_result: list[dict[str, Any]] = []
    prev_band_y = float("-inf")

    def _emit_column_band(y_min: float, y_max: float) -> None:
        band = [
            it for it in col_items
            if y_min <= (it["bbox"][1] + it["bbox"][3]) * 0.5 < y_max
        ]
        if not band:
            return
        left_band = [
            it for it in band
            if ((it["bbox"][0] + it["bbox"][2]) * 0.5 <= mid_x and it["bbox"][0] < mid_x + 4.0)
            or it["bbox"][2] <= mid_x
        ]
        left_ids = {id(it) for it in left_band}
        right_band = [it for it in band if id(it) not in left_ids]
        ordered_result.extend(_merge_same_row_fragments(left_band, eff_width))
        ordered_result.extend(_merge_same_row_fragments(right_band, eff_width))

    for sp_item in spanning:
        sp_yc = (sp_item["bbox"][1] + sp_item["bbox"][3]) * 0.5
        _emit_column_band(prev_band_y, sp_yc)
        ordered_result.append(sp_item)
        prev_band_y = sp_yc

    _emit_column_band(prev_band_y, float("inf"))
    return ordered_result


def _extract_page_structure_from_dict(page: Any) -> tuple[int | None, str, tuple[PageLineInfo, ...], bool, tuple[str, ...]]:
    """Extracts margin printed page candidate, running margins, line bold flags, and visual-order body lines."""
    try:
        raw_dict = page.get_text("dict")
    except Exception:
        return None, "NO_MARGIN_CANDIDATE", (), False, ()

    if not isinstance(raw_dict, dict) or "blocks" not in raw_dict:
        return None, "NO_MARGIN_CANDIDATE", (), False, ()

    rect = getattr(page, "rect", None)
    page_height = float(getattr(rect, "height", 0.0) or 0.0)
    page_width = float(getattr(rect, "width", 0.0) or 0.0)
    top_limit = page_height * TOP_MARGIN_MAX_RATIO if page_height > 0 else 0.0
    bottom_limit = page_height * BOTTOM_MARGIN_MIN_RATIO if page_height > 0 else float("inf")

    margin_candidates: set[int] = set()
    removed_margins: list[str] = []
    raw_body_items: list[dict[str, Any]] = []
    orig_counter = 0

    for block in raw_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans") or []
            line_text = re.sub(r"[ \t]+", " ", "".join(str(s.get("text") or "") for s in spans)).strip()
            if not line_text:
                continue

            bbox_raw = line.get("bbox")
            bbox: tuple[float, float, float, float] | None = None
            in_margin = False
            if bbox_raw and len(bbox_raw) == 4:
                bbox = (float(bbox_raw[0]), float(bbox_raw[1]), float(bbox_raw[2]), float(bbox_raw[3]))
                if page_height > 0:
                    in_margin = (bbox[3] <= top_limit) or (bbox[1] >= bottom_limit)

            if in_margin:
                m_plain = re.fullmatch(r"[\[\(\s\-–—]*(\d{1,4})[\]\)\s\-–—]*", line_text)
                m_pref = re.fullmatch(r"(?:page|p\.?|पृष्ठ)\s*[-:.]?\s*(\d{1,4})", line_text, re.IGNORECASE)
                m_page = m_plain or m_pref
                if m_page:
                    margin_candidates.add(int(m_page.group(1)))
                    removed_margins.append(line_text)
                    continue

                # Exclude known running header/footer phrases strictly inside margin bands
                # without ever dropping an actual rule heading
                if (
                    len(line_text) <= 95
                    and _RUNNING_MARGIN_LINE_RE.match(line_text)
                    and _parse_rule_heading_line(line_text) is None
                ):
                    removed_margins.append(line_text)
                    continue

            raw_body_items.append(
                {
                    "text": line_text,
                    "bbox": bbox,
                    "spans": list(spans),
                    "orig_idx": orig_counter,
                }
            )
            orig_counter += 1

    ordered_items = _order_and_merge_page_lines(raw_body_items, page_width=page_width)
    body_lines: list[PageLineInfo] = []
    page_has_font_meta = False

    for item in ordered_items:
        clean_text, line_bold, lead_bold, prefix_bold, has_meta = _compute_line_typography(item["spans"])
        if not clean_text:
            clean_text = item["text"]
        if has_meta:
            page_has_font_meta = True
        body_lines.append(
            PageLineInfo(
                text=clean_text,
                is_bold=line_bold,
                bbox=item.get("bbox"),
                leading_is_bold=lead_bold,
                heading_prefix_is_bold=prefix_bold,
            )
        )

    if len(margin_candidates) == 1:
        printed_cand = next(iter(margin_candidates))
        printed_status = "MARGIN_CANDIDATE"
    elif len(margin_candidates) > 1:
        printed_cand = None
        printed_status = "AMBIGUOUS_MARGIN_CANDIDATES"
    else:
        printed_cand = None
        printed_status = "NO_MARGIN_CANDIDATE"

    return printed_cand, printed_status, tuple(body_lines), page_has_font_meta, tuple(removed_margins)


def extract_pdf_pages_detailed(
    pdf_bytes: bytes,
    force_ocr: bool = False,
) -> tuple[list[ExtractedPage], bool]:
    """Extracts physical page text, optional typography/margin candidates, and OCR fallback stats."""
    validate_pdf_bytes(pdf_bytes)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[ExtractedPage] = []
    any_ocr = False

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            phys_num = page_idx + 1
            raw_text = _normalize_page_text(page.get_text("text") or "")
            non_space_len = len(re.sub(r"\s+", "", raw_text))
            needs_ocr = force_ocr or non_space_len < MIN_NATIVE_TEXT_CHARS

            if needs_ocr:
                pix = page.get_pixmap(dpi=250)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr_text = pytesseract.image_to_string(img, lang="eng+hin")
                cleaned_ocr = _normalize_page_text(ocr_text)
                if cleaned_ocr or force_ocr:
                    raw_text = cleaned_ocr
                    any_ocr = True
                lines = tuple(PageLineInfo(text=ln.strip(), is_bold=None) for ln in raw_text.splitlines() if ln.strip())
                pages.append(
                    ExtractedPage(
                        physical_page_number=phys_num,
                        text=raw_text,
                        printed_page_candidate=None,
                        printed_page_status="OCR_PAGE",
                        used_ocr=True,
                        typography_available=False,
                        lines=lines,
                    )
                )
            else:
                printed_cand, printed_status, dict_lines, typo_ok, removed_margins = _extract_page_structure_from_dict(page)
                if dict_lines:
                    body_text = _normalize_page_text("\n".join(ln.text for ln in dict_lines))
                    pages.append(
                        ExtractedPage(
                            physical_page_number=phys_num,
                            text=body_text,
                            printed_page_candidate=printed_cand,
                            printed_page_status=printed_status,
                            used_ocr=False,
                            typography_available=typo_ok,
                            lines=dict_lines,
                            removed_margin_lines=removed_margins,
                        )
                    )
                else:
                    lines = tuple(
                        PageLineInfo(text=ln.strip(), is_bold=None) for ln in raw_text.splitlines() if ln.strip()
                    )
                    pages.append(
                        ExtractedPage(
                            physical_page_number=phys_num,
                            text=raw_text,
                            printed_page_candidate=printed_cand,
                            printed_page_status=printed_status,
                            used_ocr=False,
                            typography_available=False,
                            lines=lines,
                            removed_margin_lines=removed_margins,
                        )
                    )
    finally:
        doc.close()

    return pages, any_ocr


def extract_pdf_pages_with_stats(
    pdf_bytes: bytes,
    force_ocr: bool = False,
) -> tuple[list[tuple[int, str]], bool]:
    """Extracts text page-by-page using PyMuPDF, falling back to English+Hindi Tesseract OCR for scanned pages."""
    detailed_pages, used_ocr = extract_pdf_pages_detailed(pdf_bytes, force_ocr=force_ocr)
    return [(p.physical_page_number, p.text) for p in detailed_pages], used_ocr


def extract_pdf_pages(pdf_bytes: bytes, force_ocr: bool = False) -> list[tuple[int, str]]:
    """Backward-compatible wrapper returning [(page_number, text), ...]."""
    pages, _ = extract_pdf_pages_with_stats(pdf_bytes, force_ocr=force_ocr)
    return pages


def _normalize_page_text(text: str) -> str:
    text = text.replace("\x00", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    collapsed = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


def _margin_signature(line_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (line_text or "").strip().lower())
    return re.sub(r"\d+", "<n>", cleaned)


def _detect_repeated_margin_signatures(parsed_pages: list[dict[str, Any]]) -> set[str]:
    """Detects running headers/footers repeating in top/bottom 2 lines across >= 3 pages without catching rule headings."""
    if len(parsed_pages) < 3:
        return set()

    counts: dict[str, int] = {}
    for pdata in parsed_pages:
        lines = [ln.text.strip() for ln in pdata["lines"] if ln.text.strip()]
        if len(lines) <= 2:
            candidates = lines
        else:
            candidates = [*lines[:2], *lines[-2:]]

        page_sigs: set[str] = set()
        for ln in candidates:
            if len(ln) > 95:
                continue
            if _parse_rule_heading_line(ln) is not None:
                continue
            # Avoid filtering genuine prose sentences that happen to appear near top/bottom
            if ". " in ln and len(ln.split()) > 8:
                continue
            sig = _margin_signature(ln)
            if sig and sig != "<n>":
                page_sigs.add(sig)

        for sig in page_sigs:
            counts[sig] = counts.get(sig, 0) + 1

    threshold = max(3, int(len(parsed_pages) * 0.4 + 0.5)) if len(parsed_pages) >= 5 else 3
    return {sig for sig, cnt in counts.items() if cnt >= threshold}


def _merge_vertical_split_rule_lines(lines: tuple[PageLineInfo, ...]) -> tuple[PageLineInfo, ...]:
    """Rejoins a standalone rule-number line (e.g. '5.13.' or 'S.R. 5.13.1') with its heading on the immediate next line."""
    if len(lines) <= 1:
        return lines

    merged: list[PageLineInfo] = []
    idx = 0
    while idx < len(lines):
        curr = lines[idx]
        curr_txt = curr.text.strip()
        if (
            idx + 1 < len(lines)
            and _STANDALONE_RULE_NUM_LINE_RE.match(curr_txt)
        ):
            nxt = lines[idx + 1]
            nxt_txt = nxt.text.strip()
            if (
                nxt_txt
                and not CHAPTER_HEADER_PATTERN.match(nxt_txt)
                and not _STANDALONE_RULE_NUM_LINE_RE.match(nxt_txt)
                and not _MEASUREMENT_UNIT_START_RE.match(nxt_txt)
                and _HEADING_NEXT_LINE_START_RE.match(nxt_txt)
            ):
                lead_bold = curr.leading_is_bold if curr.leading_is_bold is not None else curr.is_bold
                merged.append(
                    PageLineInfo(
                        text=f"{curr_txt} {nxt_txt}".strip(),
                        is_bold=curr.is_bold if curr.is_bold is not None else nxt.is_bold,
                        bbox=curr.bbox or nxt.bbox,
                        leading_is_bold=lead_bold,
                        heading_prefix_is_bold=(
                            curr.heading_prefix_is_bold
                            if curr.heading_prefix_is_bold is not None
                            else lead_bold
                        ),
                    )
                )
                idx += 2
                continue
        merged.append(curr)
        idx += 1
    return tuple(merged)


def _find_split_point(text: str, start: int, max_chars: int, min_chars: int) -> int:
    limit = min(len(text), start + max_chars)
    if limit == len(text):
        return limit

    search_floor = min(limit, start + min_chars)
    window = text[search_floor:limit]

    split_pos = limit
    for sep in ("\n\n", "\n", ". ", "। ", "; ", " "):
        idx = window.rfind(sep)
        if idx != -1:
            split_pos = search_floor + idx + len(sep)
            break

    # Prevent tiny trailing tail fragments when splitting a long rule block
    min_tail = min(320, max(160, min_chars // 4))
    remaining = len(text) - split_pos
    if 0 < remaining < min_tail:
        target_end = len(text) - min_tail
        if target_end >= start + min_chars:
            adj_window = text[start + min_chars : target_end + 1]
            for sep in ("\n\n", "\n", ". ", "। ", "; ", " "):
                idx = adj_window.rfind(sep)
                if idx != -1:
                    return start + min_chars + idx + len(sep)
    return split_pos


@dataclass
class _RuleBlock:
    chapter: str | None
    rule_label: str | None
    rule_kind: str | None
    base_key: tuple[str, str] | None
    parent_rule: str | None
    confidence: str
    is_continuation: bool
    continued_from_rule: str | None
    contained_rules: list[str]
    lines: list[str]
    line_owners: list[str | None]
    start_offset: int
    end_offset: int


def chunk_pages_with_metadata(
    pages: list[tuple[int, str]] | list[ExtractedPage],
    min_chars: int = 1000,
    max_chars: int = 1400,
    overlap_chars: int = 200,
) -> list[ExtractedChunk]:
    """Splits page text cleanly at GR/SR/Rule boundaries without false-positive words or cross-rule bleed."""
    normalized_pages: list[dict[str, Any]] = []
    for raw_page in pages:
        if isinstance(raw_page, ExtractedPage):
            cleaned_text = _normalize_page_text(raw_page.text)
            if not cleaned_text or not raw_page.lines:
                continue
            normalized_pages.append(
                {
                    "page_number": raw_page.physical_page_number,
                    "printed_cand": raw_page.printed_page_candidate,
                    "printed_status": raw_page.printed_page_status,
                    "typo_available": raw_page.typography_available,
                    "lines": raw_page.lines,
                }
            )
        else:
            page_number, raw_text = raw_page
            cleaned_text = _normalize_page_text(raw_text)
            if not cleaned_text:
                continue
            page_lines = tuple(
                PageLineInfo(text=ln.strip(), is_bold=None)
                for ln in cleaned_text.splitlines()
                if ln.strip()
            )
            if not page_lines:
                continue
            normalized_pages.append(
                {
                    "page_number": page_number,
                    "printed_cand": None,
                    "printed_status": "UNAVAILABLE",
                    "typo_available": False,
                    "lines": page_lines,
                }
            )

    repeated_margin_sigs = _detect_repeated_margin_signatures(normalized_pages)

    chunks: list[ExtractedChunk] = []
    chunk_idx = 0
    active_chapter: str | None = None
    active_rule_label: str | None = None
    active_last_subrule_label: str | None = None
    active_rule_kind: str | None = None
    active_base_key: tuple[str, str] | None = None
    active_parent_rule: str | None = None
    active_confidence: str = "NONE"
    last_rule_page: int | None = None

    for pdata in normalized_pages:
        page_number = pdata["page_number"]
        printed_cand = pdata["printed_cand"]
        printed_status = pdata["printed_status"]
        typo_available = pdata["typo_available"]

        # Filter confirmed cross-page repeated running headers/footers on first/last 2 margin positions
        raw_page_lines = list(pdata["lines"])
        if repeated_margin_sigs:
            total_p_lines = len(raw_page_lines)
            filtered_lines: list[PageLineInfo] = []
            for idx_ln, ln_info in enumerate(raw_page_lines):
                is_edge_pos = (idx_ln < 2) or (idx_ln >= total_p_lines - 2)
                if (
                    is_edge_pos
                    and _margin_signature(ln_info.text) in repeated_margin_sigs
                    and _parse_rule_heading_line(ln_info.text) is None
                ):
                    continue
                filtered_lines.append(ln_info)
            raw_page_lines = filtered_lines

        page_lines = _merge_vertical_split_rule_lines(tuple(raw_page_lines))
        if not page_lines:
            continue

        # Reset continuation if pages are non-consecutive (e.g. skipped blank/divider page)
        if last_rule_page is not None and (page_number - last_rule_page) > 1:
            active_rule_label = None
            active_last_subrule_label = None
            active_rule_kind = None
            active_base_key = None
            active_parent_rule = None
            active_confidence = "NONE"

        blocks: list[_RuleBlock] = []
        current_block: _RuleBlock | None = None
        pending_header_lines: list[str] = []
        pending_start_offset: int | None = None
        cursor = 0
        prev_body_line_text = ""

        for line_idx, line_info in enumerate(page_lines):
            ln = line_info.text.strip()
            if not ln:
                continue
            line_start = cursor
            line_end = cursor + len(ln)
            cursor = line_end + 1  # +1 for newline join

            # 1. Detect chapter headers and clear previous rule carry-over on true chapter transitions
            chap_m = CHAPTER_HEADER_PATTERN.match(ln)
            heading = _parse_rule_heading_line(
                ln,
                is_bold=line_info.is_bold,
                typography_available=typo_available,
                leading_is_bold=line_info.leading_is_bold,
                heading_prefix_is_bold=line_info.heading_prefix_is_bold,
            )

            # Guard against wrapped inline cross-references (e.g. "...for details see\nRule 3.39 of this book.")
            if (
                heading is not None
                and prev_body_line_text
                and _PREV_LINE_REF_INTRO_RE.search(prev_body_line_text)
                and not (line_info.leading_is_bold is True or line_info.is_bold is True)
            ):
                heading = None

            if chap_m and heading is None:
                new_chap = chap_m.group(1).strip()[:120]
                # If a running header at the top of a continuation page merely repeats the active chapter, skip duplicating it
                is_repeated_top_chapter = (
                    line_idx < 2
                    and current_block is None
                    and new_chap == active_chapter
                    and active_rule_label is not None
                )
                if is_repeated_top_chapter:
                    continue

                if new_chap != active_chapter or current_block is not None:
                    active_chapter = new_chap
                    active_rule_label = None
                    active_last_subrule_label = None
                    active_rule_kind = None
                    active_base_key = None
                    active_parent_rule = None
                    active_confidence = "NONE"
                    current_block = None
                if pending_start_offset is None:
                    pending_start_offset = line_start
                pending_header_lines.append(ln)
                prev_body_line_text = ln
                continue

            if heading is not None:
                heading_base_key = (heading.rule_kind, heading.base_digits)

                # Group verified structural sub-rules (e.g. SR 5.13.1 + SR 5.13.2 or SR 5.13(1) + SR 5.13(2))
                # only when contiguous on same page, verified HIGH confidence, same kind & base_digits,
                # and current block hasn't already reached min_chars.
                current_block_chars = sum(len(x) + 1 for x in current_block.lines) if current_block is not None else 0
                same_base_subclause = (
                    current_block is not None
                    and current_block.base_key == heading_base_key
                    and current_block.confidence == "HIGH"
                    and heading.confidence == "HIGH"
                    and current_block.rule_kind in {"GR", "SR", "GR_SR"}
                    and current_block_chars < min_chars
                )

                if same_base_subclause and current_block is not None:
                    if pending_header_lines:
                        current_block.lines.extend(pending_header_lines)
                        current_block.line_owners.extend([heading.label] * len(pending_header_lines))
                        pending_header_lines = []
                        pending_start_offset = None
                    if heading.label not in current_block.contained_rules:
                        current_block.contained_rules.append(heading.label)
                    if len(current_block.contained_rules) > 1:
                        current_block.rule_label = heading.base_label
                    if current_block.parent_rule is None and heading.parent_rule is not None:
                        current_block.parent_rule = heading.parent_rule
                    current_block.lines.append(ln)
                    current_block.line_owners.append(heading.label)
                    current_block.end_offset = line_end
                else:
                    # Cross-page continuation when same base_key continues at top of consecutive page
                    cross_page_same_base = (
                        current_block is None
                        and not blocks
                        and last_rule_page == (page_number - 1)
                        and active_base_key == heading_base_key
                        and active_last_subrule_label is not None
                        and not pending_header_lines
                    )
                    init_lines = [*pending_header_lines, ln]
                    init_owners = [heading.label] * len(init_lines)
                    init_start = pending_start_offset if pending_start_offset is not None else line_start
                    pending_header_lines = []
                    pending_start_offset = None
                    current_block = _RuleBlock(
                        chapter=active_chapter,
                        rule_label=heading.label,
                        rule_kind=heading.rule_kind,
                        base_key=heading_base_key,
                        parent_rule=heading.parent_rule,
                        confidence=heading.confidence,
                        is_continuation=cross_page_same_base,
                        continued_from_rule=active_last_subrule_label if cross_page_same_base else None,
                        contained_rules=[heading.label],
                        lines=init_lines,
                        line_owners=init_owners,
                        start_offset=init_start,
                        end_offset=line_end,
                    )
                    blocks.append(current_block)

                active_rule_label = current_block.rule_label
                active_last_subrule_label = heading.label
                active_rule_kind = heading.rule_kind
                active_base_key = heading_base_key
                active_parent_rule = current_block.parent_rule
                active_confidence = heading.confidence
                last_rule_page = page_number
            else:
                if current_block is None:
                    # Buffer short unruled title lines preceding a rule (when no active continuation)
                    # only if another rule heading follows later on the same page
                    is_cont = (
                        active_rule_label is not None
                        and last_rule_page == (page_number - 1)
                        and not pending_header_lines
                    )
                    has_later_rule_on_page = any(
                        _parse_rule_heading_line(
                            page_lines[k].text,
                            is_bold=page_lines[k].is_bold,
                            typography_available=typo_available,
                            leading_is_bold=page_lines[k].leading_is_bold,
                            heading_prefix_is_bold=page_lines[k].heading_prefix_is_bold,
                        )
                        is not None
                        for k in range(line_idx + 1, len(page_lines))
                    )
                    looks_like_short_preface_heading = (
                        not is_cont
                        and len(ln) <= 100
                        and not ln.endswith(".")
                        and has_later_rule_on_page
                        and sum(len(x) + 1 for x in pending_header_lines) + len(ln) < 240
                    )
                    if looks_like_short_preface_heading:
                        if pending_start_offset is None:
                            pending_start_offset = line_start
                        pending_header_lines.append(ln)
                        prev_body_line_text = ln
                        continue

                    init_lines = [*pending_header_lines, ln]
                    init_start = pending_start_offset if pending_start_offset is not None else line_start
                    pending_header_lines = []
                    pending_start_offset = None
                    cont_label = active_last_subrule_label or active_rule_label
                    init_owners = [cont_label if is_cont else None] * len(init_lines)
                    current_block = _RuleBlock(
                        chapter=active_chapter,
                        rule_label=cont_label if is_cont else None,
                        rule_kind=active_rule_kind if is_cont else None,
                        base_key=active_base_key if is_cont else None,
                        parent_rule=active_parent_rule if is_cont else None,
                        confidence=active_confidence if is_cont else "NONE",
                        is_continuation=is_cont,
                        continued_from_rule=cont_label if is_cont else None,
                        contained_rules=[cont_label] if is_cont and cont_label else [],
                        lines=init_lines,
                        line_owners=init_owners,
                        start_offset=init_start,
                        end_offset=line_end,
                    )
                    blocks.append(current_block)
                    if is_cont:
                        last_rule_page = page_number
                else:
                    current_block.lines.append(ln)
                    current_block.line_owners.append(current_block.line_owners[-1] if current_block.line_owners else current_block.rule_label)
                    current_block.end_offset = line_end
                    if current_block.rule_label:
                        last_rule_page = page_number

            prev_body_line_text = ln

        if pending_header_lines:
            blocks.append(
                _RuleBlock(
                    chapter=active_chapter,
                    rule_label=None,
                    rule_kind=None,
                    base_key=None,
                    parent_rule=None,
                    confidence="NONE",
                    is_continuation=False,
                    continued_from_rule=None,
                    contained_rules=[],
                    lines=pending_header_lines,
                    line_owners=[None] * len(pending_header_lines),
                    start_offset=pending_start_offset or 0,
                    end_offset=cursor,
                )
            )

        # 3. Emit chunks from each rule block cleanly (overlap ONLY inside a single long rule block!)
        for block in blocks:
            joined_lines = [x.strip() for x in block.lines if x.strip()]
            joined_owners = [
                own for x, own in zip(block.lines, block.line_owners) if x.strip()
            ]
            block_text = "\n".join(joined_lines).strip()
            if not block_text:
                continue

            # Map exact character intervals inside block_text to each line's owner rule label
            line_intervals: list[tuple[int, int, str | None]] = []
            pos = 0
            for ln_txt, ln_own in zip(joined_lines, joined_owners):
                ln_end = pos + len(ln_txt)
                line_intervals.append((pos, ln_end, ln_own))
                pos = ln_end + 1

            start = 0
            sub_idx = 0
            while start < len(block_text):
                end = _find_split_point(block_text, start, max_chars=max_chars, min_chars=min_chars)
                slice_raw = block_text[start:end]
                slice_text = slice_raw.strip()
                if slice_text:
                    # Exact trimmed bounds inside block_text for accurate contained_rules & offsets
                    lead_ws = len(slice_raw) - len(slice_raw.lstrip())
                    trail_ws = len(slice_raw) - len(slice_raw.rstrip())
                    eff_start = start + lead_ws
                    eff_end = end - trail_ws

                    slice_contained_list: list[str] = []
                    for l_start, l_end, l_own in line_intervals:
                        if l_own and l_end > eff_start and l_start < eff_end:
                            if l_own not in slice_contained_list:
                                slice_contained_list.append(l_own)
                    slice_contained = tuple(slice_contained_list) or tuple(block.contained_rules)

                    if len(slice_contained) == 1:
                        chunk_rule_number = slice_contained[0]
                    else:
                        chunk_rule_number = block.rule_label

                    is_cont_chunk = block.is_continuation or (sub_idx > 0)
                    continued_from = (
                        block.continued_from_rule
                        if block.is_continuation
                        else (chunk_rule_number if sub_idx > 0 else None)
                    )
                    first_line = next((ln.strip() for ln in slice_text.splitlines() if ln.strip()), "")
                    cross_refs = _extract_inline_cross_references(slice_text, set(slice_contained))
                    chunks.append(
                        ExtractedChunk(
                            chunk_index=chunk_idx,
                            page_number=page_number,
                            rule_number=chunk_rule_number,
                            chapter=block.chapter,
                            section_title=first_line[:120] if first_line else None,
                            content=slice_text,
                            token_count=max(1, len(slice_text.split())),
                            physical_page_number=page_number,
                            printed_page_candidate=printed_cand,
                            printed_page_status=printed_status,
                            rule_kind=block.rule_kind,
                            parent_rule=block.parent_rule,
                            contained_rules=slice_contained,
                            cross_references=cross_refs,
                            is_continuation=is_cont_chunk,
                            continued_from_rule=continued_from,
                            classification_confidence=block.confidence,
                            source_start_offset=block.start_offset + eff_start,
                            source_end_offset=block.start_offset + eff_end,
                        )
                    )
                    chunk_idx += 1
                    sub_idx += 1

                if end >= len(block_text):
                    break
                next_start = max(start + 1, end - overlap_chars)
                space_idx = block_text.find(" ", next_start, end)
                if space_idx != -1 and (end - space_idx) >= 80:
                    next_start = space_idx + 1
                start = next_start

    return chunks
