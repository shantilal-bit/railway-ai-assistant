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

RULE_HEADER_PATTERN = re.compile(
    r"\b(?:Rule|Para|Paragraph|Clause|Sub-rule|SR|GR|RBE|Circular|नियम|पैरा)\s*(?:No\.?|सं\.?)?\s*[A-Z0-9][A-Z0-9./()-]{0,28}",
    re.IGNORECASE,
)

DRIVE_FILE_ID_PATTERNS = [
    re.compile(r"/file/d/([a-zA-Z0-9_-]{10,})"),
    re.compile(r"/d/([a-zA-Z0-9_-]{10,})"),
]


class PdfPipelineError(ValueError):
    """Raised when PDF validation, download, or text/OCR extraction fails."""


@dataclass
class ExtractedChunk:
    chunk_index: int
    page_number: int
    rule_number: str | None
    chapter: str | None
    section_title: str | None
    content: str
    token_count: int


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


def extract_pdf_pages_with_stats(
    pdf_bytes: bytes,
    force_ocr: bool = False,
) -> tuple[list[tuple[int, str]], bool]:
    """Extracts text page-by-page using PyMuPDF, falling back to English+Hindi Tesseract OCR for scanned pages."""
    validate_pdf_bytes(pdf_bytes)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[tuple[int, str]] = []
    used_ocr = False

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = _normalize_page_text(page.get_text("text") or "")
            non_space_len = len(re.sub(r"\s+", "", text))
            if force_ocr or non_space_len < MIN_NATIVE_TEXT_CHARS:
                pix = page.get_pixmap(dpi=250)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr_text = pytesseract.image_to_string(img, lang="eng+hin")
                cleaned_ocr = _normalize_page_text(ocr_text)
                if cleaned_ocr or force_ocr:
                    text = cleaned_ocr
                    used_ocr = True
            pages.append((page_idx + 1, text))
    finally:
        doc.close()

    return pages, used_ocr


def extract_pdf_pages(pdf_bytes: bytes, force_ocr: bool = False) -> list[tuple[int, str]]:
    """Backward-compatible wrapper returning [(page_number, text), ...]."""
    pages, _ = extract_pdf_pages_with_stats(pdf_bytes, force_ocr=force_ocr)
    return pages


def _normalize_page_text(text: str) -> str:
    text = text.replace("\x00", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    collapsed = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


def _find_split_point(text: str, start: int, max_chars: int, min_chars: int) -> int:
    limit = min(len(text), start + max_chars)
    if limit == len(text):
        return limit

    search_floor = min(limit, start + min_chars)
    window = text[search_floor:limit]

    for sep in ("\n\n", "\n", ". ", "। ", "; ", " "):
        idx = window.rfind(sep)
        if idx != -1:
            return search_floor + idx + len(sep)
    return limit


def chunk_pages_with_metadata(
    pages: list[tuple[int, str]],
    min_chars: int = 1000,
    max_chars: int = 1400,
    overlap_chars: int = 200,
) -> list[ExtractedChunk]:
    """Splits page text into ~1000-1500 char overlapping chunks while preserving page, chapter, and rule numbers."""
    chunks: list[ExtractedChunk] = []
    chunk_idx = 0
    active_chapter: str | None = None
    active_rule: str | None = None

    for page_number, raw_text in pages:
        cleaned = _normalize_page_text(raw_text)
        if not cleaned:
            continue

        start = 0
        while start < len(cleaned):
            end = _find_split_point(cleaned, start, max_chars=max_chars, min_chars=min_chars)
            slice_text = cleaned[start:end].strip()
            if slice_text:
                chapter_matches = CHAPTER_HEADER_PATTERN.findall(slice_text)
                if chapter_matches:
                    active_chapter = chapter_matches[-1].strip()[:120]

                rule_matches = RULE_HEADER_PATTERN.findall(slice_text)
                if rule_matches:
                    active_rule = rule_matches[0].strip()[:80]
                    # Advance carried rule to last rule seen in slice for subsequent chunks
                    last_rule = rule_matches[-1].strip()[:80]
                else:
                    last_rule = active_rule

                first_line = next((ln.strip() for ln in slice_text.splitlines() if ln.strip()), "")
                chunks.append(
                    ExtractedChunk(
                        chunk_index=chunk_idx,
                        page_number=page_number,
                        rule_number=rule_matches[0].strip()[:80] if rule_matches else active_rule,
                        chapter=active_chapter,
                        section_title=first_line[:120] if first_line else None,
                        content=slice_text,
                        token_count=max(1, len(slice_text.split())),
                    )
                )
                active_rule = last_rule
                chunk_idx += 1

            if end >= len(cleaned):
                break
            next_start = max(start + 1, end - overlap_chars)
            # Align overlap start to word boundary when possible
            space_idx = cleaned.find(" ", next_start, end)
            if space_idx != -1 and (end - space_idx) >= 80:
                next_start = space_idx + 1
            start = next_start

    return chunks
