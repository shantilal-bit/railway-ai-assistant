"""Automated Unit Tests for Structural G&SR Rule Extraction, Boundary Chunking, and Physical vs Printed Page Metadata.

Note: These tests verify parser behavior using synthetic/mocked PDF structures in memory.
No live Supabase, R2, or actual G___SR_corrected_with_CS-108.pdf file is accessed here.
"""

from __future__ import annotations

import asyncio
import types
import unittest

import test_rag_pipeline as base_tests  # Installs import stubs cleanly if needed

from app import pdf_pipeline  # noqa: E402
from app import rag_service  # noqa: E402
from app.embeddings import CloudflareBgeM3Embedder  # noqa: E402


class _MockDictPage:
    """Simulates a PyMuPDF Page supporting 'text', 'dict', multi-span lines, and multi-block layouts."""

    def __init__(self, height: float, lines_spec: list[dict], width: float = 600.0):
        self.rect = types.SimpleNamespace(height=height, width=width)
        self._lines_spec = lines_spec

    def get_text(self, mode: str = "text"):
        if mode == "text":
            return "\n".join(
                item["text"] if "text" in item else "".join(sp["text"] for sp in item.get("spans", []))
                for item in self._lines_spec
            )
        if mode == "dict":
            blocks = []
            for item in self._lines_spec:
                bbox = item.get("bbox", (50.0, 200.0, 500.0, 215.0))
                if "spans" in item:
                    spans = [
                        {
                            "text": sp["text"],
                            "font": sp.get("font", "Times-Bold" if sp.get("bold") else "Times-Roman"),
                            "flags": sp.get("flags", 16 if sp.get("bold") else 0),
                            "size": sp.get("size", 11.0),
                        }
                        for sp in item["spans"]
                    ]
                else:
                    if item.get("no_font_meta"):
                        font = ""
                        flags = 0
                    else:
                        font = "Times-Bold" if item.get("bold") else "Times-Roman"
                        flags = 16 if item.get("bold") else 0
                    spans = [
                        {
                            "text": item["text"],
                            "font": font,
                            "flags": flags,
                            "size": 11.0,
                        }
                    ]
                blocks.append(
                    {
                        "type": 0,
                        "bbox": bbox,
                        "lines": [
                            {
                                "bbox": bbox,
                                "spans": spans,
                            }
                        ],
                    }
                )
            return {"blocks": blocks}
        return ""

    def get_pixmap(self, dpi: int = 250):
        return base_tests.FakePixmap()


class _MockDictDocument:
    def __init__(self, pages: list[_MockDictPage]):
        self._pages = pages

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, idx: int):
        return self._pages[idx]

    def close(self):
        pass


class PdfParserTests(unittest.TestCase):
    def test_01_rejects_false_positive_prose_words_and_glued_digits(self):
        invalid_labels = [
            None,
            "",
            "   ",
            "rule",
            "rules",
            "green",
            "granted",
            "great",
            "gradients",
            "group",
            "general",
            "grade 1",
            "group 2",
            "rules 1989",
            "GR 1.01at",
            "SR 5.13the",
            "Rule 3(1)the",
            "Rule 3(1",
        ]
        for bad in invalid_labels:
            self.assertIsNone(pdf_pipeline.validate_rule_label(bad), f"Expected None for {bad!r}")

        valid_labels = [
            ("GR 5.13", "GR 5.13"),
            ("GR 5.13.", "GR 5.13"),
            ("GR 4.10A", "GR 4.10A"),
            ("SR 5.13(1)", "SR 5.13(1)"),
            ("Rule 3(1)(i)", "Rule 3(1)(i)"),
            ("Rule 215-A", "Rule 215-A"),
            ("RBE 45/2024", "RBE 45/2024"),
            ("नियम 5.13", "नियम 5.13"),
        ]
        for raw, expected in valid_labels:
            self.assertEqual(pdf_pipeline.validate_rule_label(raw), expected)

        # Synthetic prose page packed with historical false-positive words and measurements
        prose_page = (
            "General Rules and Subsidiary Rules for Railways.\n"
            "All green hand signals granted to the group must show great care on gradients.\n"
            "Rules 1976 apply to grade 1 points and group 2 sidings.\n"
            "1.5 metres clearance must be kept from the running line.\n"
            "GR 1.01at the station yard requires caution (see Rule 3.39).\n"
        )
        chunks = pdf_pipeline.chunk_pages_with_metadata([(10, prose_page)])
        self.assertEqual(len(chunks), 1)
        self.assertIsNone(chunks[0].rule_number)
        self.assertEqual(chunks[0].contained_rules, ())
        self.assertIn("Rule 3.39", chunks[0].cross_references)

    def test_02_separates_multiple_gr_sr_rules_and_keeps_cross_references_distinct(self):
        page_text = (
            "CHAPTER V\n"
            "GR 5.12 Supply and custody of clamps and padlocks.—\n"
            "The Station Master shall ensure a green flag and group of clamps are maintained.\n"
            "S.R. 5.12(1) At stations where points are non-interlocked, permission granted shall be logged.\n"
            "Refer also to Rule 3.39 when fixed signals fail.\n"
            "GR 5.13 Duties of Pointsman.—\n"
            "A Pointsman shall examine facing points before any train movement.\n"
            "S.R. 5.13(1) The Pointsman on duty shall clean and inspect point blades.\n"
            "S.R. 5.13(2) He shall exhibit all-right hand signals after setting points properly.\n"
        )
        chunks = pdf_pipeline.chunk_pages_with_metadata([(234, page_text)], min_chars=200, max_chars=800)

        rules_by_chunk = [c.rule_number for c in chunks]
        self.assertEqual(rules_by_chunk, ["GR 5.12", "SR 5.12(1)", "GR 5.13", "SR 5.13"])

        # Ensure GR 5.12 chunk never bleeds GR 5.13 text or vice versa
        self.assertIn("custody of clamps", chunks[0].content)
        self.assertNotIn("Duties of Pointsman", chunks[0].content)

        # Inline Rule 3.39 stays in cross_references, NOT as SR 5.12's rule_number
        self.assertEqual(chunks[1].rule_number, "SR 5.12(1)")
        self.assertIn("Rule 3.39", chunks[1].cross_references)

        # Sub-clauses SR 5.13(1) and SR 5.13(2) group coherently under SR 5.13
        self.assertEqual(chunks[3].rule_kind, "SR")
        self.assertEqual(chunks[3].contained_rules, ("SR 5.13(1)", "SR 5.13(2)"))

    def test_03_prevents_stale_rule_carryover_across_chapters_or_gaps_and_tracks_continuations(self):
        # Case A: Chapter boundary & page gap reset active_rule_label
        pages_gap = [
            (10, "CHAPTER V\nGR 5.12 Custody of keys.\nKeys remain with Station Master."),
            (11, "CHAPTER VI\nThis chapter introduces Accidents and Unusual Occurrences before Rule 6.01."),
            (13, "Prefatory note after a blank/divider page 12 with no rule heading."),
        ]
        chunks_gap = pdf_pipeline.chunk_pages_with_metadata(pages_gap)
        self.assertEqual(chunks_gap[0].rule_number, "GR 5.12")
        self.assertIsNone(chunks_gap[1].rule_number)
        self.assertEqual(chunks_gap[1].chapter, "CHAPTER VI")
        self.assertIsNone(chunks_gap[2].rule_number)

        # Case B: Genuine continuation from consecutive page stops immediately when next rule starts
        pages_cont = [
            (234, "CHAPTER V\nSR 5.13(1) Pointsman shall check facing points and lock them.\n" + ("Detail line. " * 20)),
            (235, "(c) He shall report any obstruction immediately to the Station Master.\nGR 5.14 Responsibility of Cabinman.\nCabinman checks lever frame."),
        ]
        chunks_cont = pdf_pipeline.chunk_pages_with_metadata(pages_cont)
        self.assertEqual(chunks_cont[0].rule_number, "SR 5.13(1)")
        self.assertFalse(chunks_cont[0].is_continuation)

        # Continuation on page 235 inherits SR 5.13(1) until GR 5.14 starts
        self.assertEqual(chunks_cont[1].page_number, 235)
        self.assertEqual(chunks_cont[1].rule_number, "SR 5.13(1)")
        self.assertTrue(chunks_cont[1].is_continuation)
        self.assertEqual(chunks_cont[1].continued_from_rule, "SR 5.13(1)")
        self.assertNotIn("Cabinman", chunks_cont[1].content)

        # GR 5.14 starts fresh without continuation flag
        self.assertEqual(chunks_cont[2].rule_number, "GR 5.14")
        self.assertFalse(chunks_cont[2].is_continuation)
        self.assertIsNone(chunks_cont[2].continued_from_rule)

    def test_04_bold_typography_vs_ocr_unclassified_rule_identity(self):
        # Digital page with BOLD heading "5.13. Duties of Pointsman."
        digital_doc = _MockDictDocument(
            [
                _MockDictPage(
                    height=800.0,
                    lines_spec=[
                        {"text": "201", "bold": False, "bbox": (270.0, 20.0, 310.0, 36.0)},
                        {"text": "CHAPTER V", "bold": True, "bbox": (220.0, 140.0, 360.0, 158.0)},
                        {"text": "5.13. Duties of Pointsman.—", "bold": True, "bbox": (60.0, 180.0, 350.0, 198.0)},
                        {"text": "The Pointsman shall inspect facing points and clamps.", "bold": False, "bbox": (60.0, 205.0, 500.0, 220.0)},
                        {"text": "S.R. 5.13(1) Pointsman shall exhibit hand signal.", "bold": False, "bbox": (60.0, 240.0, 500.0, 255.0)},
                    ],
                )
            ]
        )

        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": digital_doc
            detailed_pages, used_ocr = pdf_pipeline.extract_pdf_pages_detailed(b"%PDF-1.4\n...mock...", force_ocr=False)
        finally:
            pdf_pipeline.fitz.open = orig_open

        self.assertFalse(used_ocr)
        self.assertEqual(detailed_pages[0].printed_page_candidate, 201)
        self.assertEqual(detailed_pages[0].printed_page_status, "MARGIN_CANDIDATE")
        self.assertTrue(detailed_pages[0].typography_available)

        chunks = pdf_pipeline.chunk_pages_with_metadata(detailed_pages)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].rule_number, "GR 5.13")
        self.assertEqual(chunks[0].rule_kind, "GR")
        self.assertEqual(chunks[0].classification_confidence, "HIGH")
        self.assertEqual(chunks[0].physical_page_number, 1)
        self.assertEqual(chunks[0].printed_page_candidate, 201)
        self.assertEqual(chunks[0].printed_page_status, "MARGIN_CANDIDATE")
        # Margin token "201" excluded from body text
        self.assertNotIn("201", chunks[0].content)

        self.assertEqual(chunks[1].rule_number, "SR 5.13(1)")
        self.assertEqual(chunks[1].rule_kind, "SR")

        # OCR page without typography must NOT guess GR vs SR for unprefixed 5.13
        ocr_doc = base_tests.FakePdfDocument([""])
        orig_open = pdf_pipeline.fitz.open
        orig_img_open = pdf_pipeline.Image.open
        orig_tess = pdf_pipeline.pytesseract.image_to_string
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": ocr_doc
            pdf_pipeline.Image.open = lambda bio: bio
            pdf_pipeline.pytesseract.image_to_string = (
                lambda img, lang="eng+hin": "5.13. Duties of Pointsman.—\nThe Pointsman shall check points."
            )
            ocr_pages, ocr_used = pdf_pipeline.extract_pdf_pages_detailed(b"%PDF-1.4\n...ocr...", force_ocr=False)
        finally:
            pdf_pipeline.fitz.open = orig_open
            pdf_pipeline.Image.open = orig_img_open
            pdf_pipeline.pytesseract.image_to_string = orig_tess

        self.assertTrue(ocr_used)
        ocr_chunks = pdf_pipeline.chunk_pages_with_metadata(ocr_pages)
        self.assertEqual(ocr_chunks[0].rule_number, "Rule 5.13")
        self.assertEqual(ocr_chunks[0].rule_kind, "RULE")
        self.assertEqual(ocr_chunks[0].classification_confidence, "UNCLASSIFIED")
        self.assertEqual(ocr_chunks[0].printed_page_status, "OCR_PAGE")

    def test_05_ambiguous_margin_tokens_reported_as_unverified(self):
        ambig_doc = _MockDictDocument(
            [
                _MockDictPage(
                    height=800.0,
                    lines_spec=[
                        {"text": "201", "bold": False, "bbox": (270.0, 20.0, 310.0, 36.0)},
                        {"text": "Rule 5.12 Supplies at stations and lamps.", "bold": True, "bbox": (60.0, 200.0, 480.0, 215.0)},
                        {"text": "202", "bold": False, "bbox": (270.0, 760.0, 310.0, 780.0)},
                    ],
                )
            ]
        )
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": ambig_doc
            pages, _ = pdf_pipeline.extract_pdf_pages_detailed(b"%PDF-1.4\n...ambig...")
        finally:
            pdf_pipeline.fitz.open = orig_open

        self.assertIsNone(pages[0].printed_page_candidate)
        self.assertEqual(pages[0].printed_page_status, "AMBIGUOUS_MARGIN_CANDIDATES")

    def test_06_ingest_document_bytes_stores_structured_metadata(self):
        sb = base_tests.FakeSupabaseClient()
        sb.tables["documents"].append(
            {
                "id": "doc-gsr-test",
                "title": "G&SR Synthetic",
                "r2_object_key": "wr/test/gsr.pdf",
                "status": "draft",
                "ingestion_status": "pending",
            }
        )
        mock_doc = _MockDictDocument(
            [
                _MockDictPage(
                    height=800.0,
                    lines_spec=[
                        {"text": "201", "bold": False, "bbox": (270.0, 20.0, 310.0, 36.0)},
                        {"text": "5.13. Duties of Pointsman.—", "bold": True, "bbox": (60.0, 180.0, 350.0, 198.0)},
                        {"text": "Pointsman duties regarding facing points and hand signals.", "bold": False, "bbox": (60.0, 210.0, 500.0, 225.0)},
                    ],
                )
            ]
        )
        embedder = CloudflareBgeM3Embedder(
            account_id="cf-1",
            api_token="tok-1",
            client=base_tests.FakeAsyncHttpClient(
                lambda n, u, h, j: base_tests.FakeResponse(
                    200,
                    {"success": True, "result": {"data": [[0.01] * 1024 for _ in j["text"]]}},
                )
            ),
        )
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": mock_doc
            result = asyncio.run(
                rag_service.ingest_document_bytes(sb, "doc-gsr-test", b"%PDF-1.4\nmock", embedder=embedder)
            )
        finally:
            pdf_pipeline.fitz.open = orig_open

        self.assertEqual(result["chunk_count"], 1)
        stored = sb.tables["rule_chunks"][0]
        self.assertEqual(stored["rule_number"], "GR 5.13")
        self.assertEqual(stored["page_number"], 1)
        self.assertEqual(stored["metadata"]["physical_page_number"], 1)
        self.assertEqual(stored["metadata"]["printed_page_candidate"], 201)
        self.assertEqual(stored["metadata"]["printed_page_status"], "MARGIN_CANDIDATE")
        self.assertEqual(stored["metadata"]["rule_kind"], "GR")
        self.assertEqual(stored["metadata"]["contained_rules"], ["GR 5.13"])
        self.assertEqual(stored["metadata"]["classification_confidence"], "HIGH")
        self.assertFalse(stored["metadata"]["is_continuation"])

    def test_07_leading_span_bold_detection_without_70_percent_whole_line_threshold(self):
        # Rule 5.13 has only the leading number "5.13." bold (<10% of whole line chars), rest is normal prose.
        # Unprefixed 5.14 has no bold anywhere -> remains unclassified Rule 5.14.
        # Mixed-font page without any font metadata -> remains unclassified Rule 5.15.
        doc = _MockDictDocument(
            [
                _MockDictPage(
                    height=800.0,
                    width=600.0,
                    lines_spec=[
                        {
                            "bbox": (50.0, 180.0, 560.0, 198.0),
                            "spans": [
                                {"text": "5.13.", "bold": True},
                                {
                                    "text": " Duties of Pointsman.— A Pointsman shall clean and inspect every facing point before train movements in the station yard.",
                                    "bold": False,
                                },
                            ],
                        },
                        {
                            "bbox": (50.0, 220.0, 560.0, 238.0),
                            "spans": [
                                {"text": "5.14.", "bold": False},
                                {"text": " Signals at stations.— Fixed signals shall be checked daily.", "bold": False},
                            ],
                        },
                    ],
                ),
                _MockDictPage(
                    height=800.0,
                    width=600.0,
                    lines_spec=[
                        {"text": "5.15. Station working order compliance.— Staff shall sign assurance register.", "no_font_meta": True, "bbox": (50.0, 200.0, 550.0, 216.0)},
                    ],
                ),
            ]
        )
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": doc
            pages, _ = pdf_pipeline.extract_pdf_pages_detailed(b"%PDF-1.4\n...spans...")
        finally:
            pdf_pipeline.fitz.open = orig_open

        self.assertTrue(pages[0].typography_available)
        self.assertFalse(pages[1].typography_available)

        chunks = pdf_pipeline.chunk_pages_with_metadata(pages)
        self.assertEqual(chunks[0].rule_number, "GR 5.13")
        self.assertEqual(chunks[0].rule_kind, "GR")
        self.assertEqual(chunks[0].classification_confidence, "HIGH")

        self.assertEqual(chunks[1].rule_number, "Rule 5.14")
        self.assertEqual(chunks[1].rule_kind, "RULE")
        self.assertEqual(chunks[1].classification_confidence, "UNCLASSIFIED")

        self.assertEqual(chunks[2].rule_number, "Rule 5.15")
        self.assertEqual(chunks[2].classification_confidence, "UNCLASSIFIED")

    def test_08_rejoins_split_rule_number_and_heading_across_blocks_and_lines(self):
        # Case A: Same-row horizontal split blocks (left margin bold "5.13." + right heading "Duties of Pointsman.—")
        # Case B: Vertical line split ("S.R. 5.13.1" on one line, "Inspection of blades." on next line)
        doc = _MockDictDocument(
            [
                _MockDictPage(
                    height=800.0,
                    width=600.0,
                    lines_spec=[
                        {"text": "Duties of Pointsman.—", "bold": False, "bbox": (110.0, 180.0, 480.0, 196.0)},
                        {"text": "5.13.", "bold": True, "bbox": (45.0, 180.0, 82.0, 196.0)},
                        {"text": "A Pointsman shall examine facing points carefully.", "bold": False, "bbox": (110.0, 202.0, 540.0, 218.0)},
                        {"text": "S.R. 5.13.1", "bold": False, "bbox": (45.0, 240.0, 110.0, 255.0)},
                        {"text": "Inspection of facing point blades and cotters.", "bold": False, "bbox": (45.0, 258.0, 520.0, 274.0)},
                    ],
                )
            ]
        )
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": doc
            pages, _ = pdf_pipeline.extract_pdf_pages_detailed(b"%PDF-1.4\n...split...")
        finally:
            pdf_pipeline.fitz.open = orig_open

        chunks = pdf_pipeline.chunk_pages_with_metadata(pages)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].rule_number, "GR 5.13")
        self.assertIn("5.13. Duties of Pointsman.", chunks[0].content)
        self.assertEqual(chunks[1].rule_number, "SR 5.13.1")
        self.assertEqual(chunks[1].parent_rule, "SR 5.13")
        self.assertIn("Inspection of facing point blades", chunks[1].content)

    def test_09_multi_column_and_out_of_order_blocks_follow_visual_reading_order(self):
        # Blocks intentionally listed out of order in PDF stream: Right column before Left column
        doc = _MockDictDocument(
            [
                _MockDictPage(
                    height=800.0,
                    width=600.0,
                    lines_spec=[
                        # Spanning chapter header at top
                        {"text": "CHAPTER V", "bold": True, "bbox": (150.0, 125.0, 450.0, 142.0)},
                        # Right column emitted first in PDF raw stream
                        {"text": "S.R. 5.13(1) Pointsman right-column clause.", "bold": False, "bbox": (320.0, 170.0, 560.0, 186.0)},
                        {"text": "Right column continuation detail for SR 5.13(1).", "bold": False, "bbox": (320.0, 192.0, 560.0, 208.0)},
                        # Left column emitted later in raw stream, but visually earlier
                        {"text": "5.12. Custody of padlocks.—", "bold": True, "bbox": (40.0, 170.0, 270.0, 186.0)},
                        {"text": "Left column custody body for GR 5.12.", "bold": False, "bbox": (40.0, 192.0, 270.0, 208.0)},
                    ],
                )
            ]
        )
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": doc
            pages, _ = pdf_pipeline.extract_pdf_pages_detailed(b"%PDF-1.4\n...multicol...")
        finally:
            pdf_pipeline.fitz.open = orig_open

        chunks = pdf_pipeline.chunk_pages_with_metadata(pages)
        self.assertEqual([c.rule_number for c in chunks], ["GR 5.12", "SR 5.13(1)"])
        self.assertIn("Left column custody body", chunks[0].content)
        self.assertNotIn("right-column", chunks[0].content)
        self.assertIn("Right column continuation", chunks[1].content)

    def test_10_dotted_sr_subrules_parent_and_normalized_contained_rules_per_slice(self):
        # Part A: Short dotted SR 5.13.1 + SR 5.13.2 group under SR 5.13; GR 5.13 stays separate; SR 5.14.1 never mixes.
        page_text = (
            "GR 5.13 Duties of Pointsman.—\n"
            "Pointsman ensures correct setting of points.\n"
            "S.R. 5.13.1 The Pointsman shall clean blades before locking.\n"
            "S. R. 5.13.2(a) He shall show green hand signal once points are locked.\n"
            "S.R. 5.14.1 Separate rule under 5.14.\n"
        )
        chunks = pdf_pipeline.chunk_pages_with_metadata([(234, page_text)], min_chars=500, max_chars=900)
        self.assertEqual([c.rule_number for c in chunks], ["GR 5.13", "SR 5.13", "SR 5.14.1"])
        self.assertEqual(chunks[1].parent_rule, "SR 5.13")
        self.assertEqual(chunks[1].contained_rules, ("SR 5.13.1", "SR 5.13.2(a)"))
        self.assertEqual(chunks[2].parent_rule, "SR 5.14")

        # Part B: Long dotted sub-rules (> min_chars) stay in distinct slices/chunks without wrong contained_rules leak
        long_sub_1 = "S.R. 5.13.1 " + ("Cleaning of facing point switches and slide chairs. " * 22)
        long_sub_2 = "S.R. 5.13.2 " + ("Exhibiting hand signals and clamping non-interlocked points. " * 22)
        split_chunks = pdf_pipeline.chunk_pages_with_metadata(
            [(234, long_sub_1 + "\n" + long_sub_2)],
            min_chars=800,
            max_chars=1200,
            overlap_chars=150,
        )
        self.assertGreaterEqual(len(split_chunks), 2)
        self.assertEqual(split_chunks[0].contained_rules, ("SR 5.13.1",))
        self.assertEqual(split_chunks[-1].contained_rules, ("SR 5.13.2",))
        self.assertEqual(split_chunks[-1].parent_rule, "SR 5.13")
        self.assertNotIn("SR 5.13.1", split_chunks[-1].contained_rules)

        # Part C: Verify normalization of dash-paren sub-rule (e.g. S.R. 5.13-1(a))
        mixed_chunks = pdf_pipeline.chunk_pages_with_metadata(
            [(234, "S.R. 5.13-1(a) Special clamp verification at night.")]
        )
        self.assertEqual(mixed_chunks[0].rule_number, "SR 5.13-1(a)")
        self.assertEqual(mixed_chunks[0].parent_rule, "SR 5.13")

        # Part D: Same _RuleBlock grouped (< min_chars when added) and then sliced across 2 chunks:
        # Slice 1 must NOT blindly inherit SR 5.13.1 when only SR 5.13.2 text is in Slice 1.
        med_sub_1 = "S.R. 5.13.1 " + ("Check switch rail gauge. " * 20)   # ~512 chars < min_chars=600
        med_sub_2 = "S.R. 5.13.2 " + ("Clamp facing point tongue. " * 20)  # ~552 chars -> total ~1065 > max_chars=700
        grouped_split = pdf_pipeline.chunk_pages_with_metadata(
            [(234, med_sub_1.strip() + "\n" + med_sub_2.strip())],
            min_chars=600,
            max_chars=700,
            overlap_chars=0,
        )
        self.assertEqual(len(grouped_split), 2)
        self.assertEqual(grouped_split[0].contained_rules, ("SR 5.13.1", "SR 5.13.2"))
        self.assertEqual(grouped_split[1].contained_rules, ("SR 5.13.2",))
        self.assertEqual(grouped_split[1].rule_number, "SR 5.13.2")
        self.assertEqual(grouped_split[1].parent_rule, "SR 5.13")

    def test_11_cross_page_continuation_preserves_subrule_relationship_until_next_rule(self):
        pages = [
            (
                234,
                "CHAPTER V\n"
                "S.R. 5.13(1) Pointsman shall check facing points and test locking mechanism.",
            ),
            (
                235,
                "CHAPTER V\n"
                "S.R. 5.13(2) On completion of setting, Pointsman shall clamp the switch.\n"
                "GR 5.14 Duties of Cabinman.—\n"
                "Cabinman operates levers in the cabin.",
            ),
        ]
        chunks = pdf_pipeline.chunk_pages_with_metadata(pages)
        self.assertEqual([c.rule_number for c in chunks], ["SR 5.13(1)", "SR 5.13(2)", "GR 5.14"])

        # Page 235's SR 5.13(2) continues SR 5.13 from page 234 (and repeated "CHAPTER V" did not break or pollute content)
        self.assertTrue(chunks[1].is_continuation)
        self.assertEqual(chunks[1].continued_from_rule, "SR 5.13(1)")
        self.assertEqual(chunks[1].parent_rule, "SR 5.13")
        self.assertNotIn("CHAPTER V", chunks[1].content)

        # GR 5.14 is a different rule -> stops continuation cleanly
        self.assertFalse(chunks[2].is_continuation)
        self.assertIsNone(chunks[2].continued_from_rule)

    def test_12_running_headers_and_footers_excluded_and_printed_page_never_marked_verified(self):
        pages_spec = [
            _MockDictPage(
                height=800.0,
                width=600.0,
                lines_spec=[
                    {"text": "GENERAL AND SUBSIDIARY RULES", "bold": False, "bbox": (150.0, 18.0, 450.0, 32.0)},
                    {"text": "201", "bold": False, "bbox": (520.0, 18.0, 550.0, 32.0)},
                    {"text": "S.R. 5.13(1) Pointsman must verify switch blade fit.", "bold": False, "bbox": (50.0, 200.0, 520.0, 216.0)},
                    {"text": "Corrected up to CS-108", "bold": False, "bbox": (50.0, 760.0, 250.0, 775.0)},
                ],
            ),
            _MockDictPage(
                height=800.0,
                width=600.0,
                lines_spec=[
                    {"text": "GENERAL AND SUBSIDIARY RULES", "bold": False, "bbox": (150.0, 18.0, 450.0, 32.0)},
                    {"text": "Page 202", "bold": False, "bbox": (500.0, 18.0, 560.0, 32.0)},
                    {"text": "(b) Continuation clause on next printed page.", "bold": False, "bbox": (50.0, 200.0, 520.0, 216.0)},
                    {"text": "Corrected up to CS-108", "bold": False, "bbox": (50.0, 760.0, 250.0, 775.0)},
                ],
            ),
            _MockDictPage(
                height=800.0,
                width=600.0,
                lines_spec=[
                    {"text": "GENERAL AND SUBSIDIARY RULES", "bold": False, "bbox": (150.0, 18.0, 450.0, 32.0)},
                    {"text": "203", "bold": False, "bbox": (520.0, 18.0, 550.0, 32.0)},
                    {"text": "GR 5.14 Duties of Cabinman.— Cabinman verifies signals.", "bold": True, "bbox": (50.0, 200.0, 520.0, 216.0)},
                    {"text": "Corrected up to CS-108", "bold": False, "bbox": (50.0, 760.0, 250.0, 775.0)},
                ],
            ),
        ]
        doc = _MockDictDocument(pages_spec)
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": doc
            pages, _ = pdf_pipeline.extract_pdf_pages_detailed(b"%PDF-1.4\n...margins...")
        finally:
            pdf_pipeline.fitz.open = orig_open

        chunks = pdf_pipeline.chunk_pages_with_metadata(pages)
        self.assertEqual(len(chunks), 3)
        for idx, expected_phys, expected_printed in [(0, 1, 201), (1, 2, 202), (2, 3, 203)]:
            self.assertEqual(chunks[idx].physical_page_number, expected_phys)
            self.assertEqual(chunks[idx].page_number, expected_phys)
            self.assertEqual(chunks[idx].printed_page_candidate, expected_printed)
            self.assertEqual(chunks[idx].printed_page_status, "MARGIN_CANDIDATE")
            self.assertNotIn("VERIFIED", chunks[idx].printed_page_status)
            self.assertNotIn("GENERAL AND SUBSIDIARY RULES", chunks[idx].content)
            self.assertNotIn("CS-108", chunks[idx].content)

        # Page 2's continuation preserves SR 5.13(1) cleanly without header noise
        self.assertEqual(chunks[1].rule_number, "SR 5.13(1)")
        self.assertTrue(chunks[1].is_continuation)

    def test_13_prevents_tiny_orphan_chunks_while_keeping_gr_sr_separate_and_zero_text_loss(self):
        # Part A: Short preface title before GR 5.13 attaches to GR 5.13 instead of making tiny orphan chunk,
        # while wrapped "see\nRule 3.39 of this book." stays inside GR 5.13 as cross_reference.
        page = (
            "POINTS AND SIGNALS AT STATIONS\n"
            "GR 5.13 Duties of Pointsman.— For detailed speed restrictions see\n"
            "Rule 3.39 of this book before clearing signals.\n"
            "S.R. 5.13(1) Subsidiary duty remains distinct from GR 5.13."
        )
        chunks = pdf_pipeline.chunk_pages_with_metadata([(10, page)])
        self.assertEqual([c.rule_number for c in chunks], ["GR 5.13", "SR 5.13(1)"])
        self.assertIn("POINTS AND SIGNALS AT STATIONS", chunks[0].content)
        self.assertIn("Rule 3.39 of this book", chunks[0].content)
        self.assertIn("Rule 3.39", chunks[0].cross_references)
        self.assertNotIn("Subsidiary duty", chunks[0].content)

        # Part B: Balanced tail split avoids tiny trailing slice while preserving 100% of original sentences
        sentences = [f"Sentence {i:02d} describing facing point locking verification procedure." for i in range(1, 24)]
        long_rule = "GR 5.13 Duties of Pointsman.— " + " ".join(sentences)
        split_chunks = pdf_pipeline.chunk_pages_with_metadata([(10, long_rule)], min_chars=800, max_chars=1200, overlap_chars=150)
        self.assertGreaterEqual(len(split_chunks), 2)
        self.assertGreaterEqual(len(split_chunks[-1].content), 250)
        combined = " ".join(c.content for c in split_chunks)
        for s in sentences:
            self.assertIn(s, combined)

    def test_14_ingest_document_bytes_embeds_exact_chunk_content_and_keeps_schema_compat(self):
        captured_embed_inputs: list[list[str]] = []

        class _CapturingClient:
            def post(self, url, headers=None, json=None):
                captured_embed_inputs.append(list(json["text"]))
                return base_tests.FakeResponse(
                    200,
                    {"success": True, "result": {"data": [[0.02] * 1024 for _ in json["text"]]}},
                )

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        # FakeAsyncHttpClient compatibility wrapper
        sb = base_tests.FakeSupabaseClient()
        sb.tables["documents"].append(
            {
                "id": "doc-gsr-exact",
                "title": "G&SR Exact",
                "r2_object_key": "wr/test/gsr.pdf",
                "status": "draft",
                "ingestion_status": "pending",
            }
        )
        doc = _MockDictDocument(
            [
                _MockDictPage(
                    height=800.0,
                    width=600.0,
                    lines_spec=[
                        {"text": "201", "bold": False, "bbox": (500.0, 20.0, 540.0, 34.0)},
                        {"text": "GR 5.13 Duties of Pointsman.— Guarding points.", "bold": True, "bbox": (50.0, 180.0, 500.0, 196.0)},
                        {"text": "S.R. 5.13.1 Cleaning point switches daily.", "bold": False, "bbox": (50.0, 210.0, 500.0, 226.0)},
                    ],
                )
            ]
        )
        embedder = CloudflareBgeM3Embedder(
            account_id="cf-1",
            api_token="tok-1",
            client=base_tests.FakeAsyncHttpClient(
                lambda n, u, h, j: _CapturingClient().post(u, h, j)
            ),
        )
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": doc
            asyncio.run(
                rag_service.ingest_document_bytes(sb, "doc-gsr-exact", b"%PDF-1.4\nmock", embedder=embedder)
            )
        finally:
            pdf_pipeline.fitz.open = orig_open

        self.assertEqual(len(sb.tables["rule_chunks"]), 2)
        flat_embedded = [txt for batch in captured_embed_inputs for txt in batch]
        self.assertEqual(flat_embedded, [row["content"] for row in sb.tables["rule_chunks"]])
        # Dotted SR row preserves schema columns + stores parent_rule in metadata JSONB
        sr_row = sb.tables["rule_chunks"][1]
        self.assertEqual(sr_row["rule_number"], "SR 5.13.1")
        self.assertEqual(sr_row["metadata"]["parent_rule"], "SR 5.13")
        self.assertEqual(sr_row["metadata"]["physical_page_number"], 1)
        self.assertEqual(sr_row["metadata"]["printed_page_candidate"], 201)
        self.assertEqual(sr_row["metadata"]["printed_page_status"], "MARGIN_CANDIDATE")


if __name__ == "__main__":
    unittest.main()
