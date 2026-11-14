"""PDF Text Extraction, Scanned PDF OCR, and Rule-Aware Chunking Pipeline.

Runs server-side after an authorized Admin uploads an official Railway PDF to Cloudflare R2.
"""

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import re
from dataclasses import dataclass


@dataclass
class ExtractedChunk:
    chunk_index: int
    page_number: int
    rule_number: str | None
    section_title: str | None
    content: str


RULE_HEADER_PATTERN = re.compile(
    r"(?:Rule|Para|Clause|SR|GR|RBE)\s*(?:No\.?)?\s*[A-Z0-9./()-]+",
    re.IGNORECASE,
)


def extract_pdf_pages(pdf_bytes: bytes, force_ocr: bool = False) -> list[tuple[int, str]]:
    """Extracts text page-by-page from native PDFs, falling back to Tesseract OCR for scanned pages."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[tuple[int, str]] = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text = page.get_text("text").strip()
        if force_ocr or len(text) < 40:
            pix = page.get_pixmap(dpi=250)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(img, lang="eng+hin").strip()
        pages.append((page_idx + 1, text))
    return pages


def chunk_pages_with_metadata(
    pages: list[tuple[int, str]],
    max_chars: int = 1600,
    overlap_chars: int = 200,
) -> list[ExtractedChunk]:
    """Splits page text into overlapping chunks while preserving exact PDF page and rule numbers."""
    chunks: list[ExtractedChunk] = []
    chunk_idx = 0

    for page_number, raw_text in pages:
        if not raw_text:
            continue
        start = 0
        while start < len(raw_text):
            end = min(len(raw_text), start + max_chars)
            slice_text = raw_text[start:end].strip()
            rule_match = RULE_HEADER_PATTERN.search(slice_text)
            chunks.append(
                ExtractedChunk(
                    chunk_index=chunk_idx,
                    page_number=page_number,
                    rule_number=rule_match.group(0) if rule_match else None,
                    section_title=slice_text.splitlines()[0][:120] if slice_text else None,
                    content=slice_text,
                )
            )
            chunk_idx += 1
            if end == len(raw_text):
                break
            start = max(0, end - overlap_chars)

    return chunks
