"""Automated Unit & Integration-Contract Tests for the Railway Rules Production RAG Pipeline.

Covers all 12 required scenarios:
1. Digital PDF text extraction & 1000-1500 char chunking
2. Scanned PDF OCR fallback (English + Hindi)
3. Bilingual Hindi + English Cloudflare BGE-M3 embedding + batching + retry
4. 1024-dimension embedding validation
5. Supabase search_railway_rules RPC invocation & migration SQL contract
6. Exact rule number search boosting
7. Department -> Division -> Zone -> Railway Board hierarchical & authority ranking
8. Superseded rule conflict comparison & warning
9. Grounded PDF page number & source citation enforcement (no hallucinations)
10. No relevant document -> isReliableAnswerFound = False (EN & HI)
11. Duplicate upload & idempotent re-indexing
12. Unauthorized (non-admin) upload/import/reprocess blocked with HTTP 403
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _install_test_stubs_if_missing() -> dict[str, bool]:
    """Provides minimal import shims only for packages absent in an Android-only build container."""
    stubbed: dict[str, bool] = {}

    if "httpx" not in sys.modules:
        try:
            importlib.import_module("httpx")
            stubbed["httpx"] = False
        except ImportError:
            stubbed["httpx"] = True
            httpx_mod = types.ModuleType("httpx")

            class TimeoutException(Exception):
                pass

            class ConnectError(Exception):
                pass

            class ReadError(Exception):
                pass

            class Headers(dict):
                pass

            class AsyncClient:
                def __init__(self, *args, **kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

            httpx_mod.TimeoutException = TimeoutException
            httpx_mod.ConnectError = ConnectError
            httpx_mod.ReadError = ReadError
            httpx_mod.Headers = Headers
            httpx_mod.AsyncClient = AsyncClient
            sys.modules["httpx"] = httpx_mod

    if "fitz" not in sys.modules:
        try:
            importlib.import_module("fitz")
            stubbed["fitz"] = False
        except ImportError:
            stubbed["fitz"] = True
            fitz_mod = types.ModuleType("fitz")
            fitz_mod.open = lambda *args, **kwargs: None
            sys.modules["fitz"] = fitz_mod

    if "pytesseract" not in sys.modules:
        try:
            importlib.import_module("pytesseract")
            stubbed["pytesseract"] = False
        except ImportError:
            stubbed["pytesseract"] = True
            tess_mod = types.ModuleType("pytesseract")
            tess_mod.image_to_string = lambda img, lang="eng+hin": ""
            sys.modules["pytesseract"] = tess_mod

    if "PIL" not in sys.modules:
        try:
            importlib.import_module("PIL.Image")
            stubbed["PIL"] = False
        except ImportError:
            stubbed["PIL"] = True
            pil_mod = types.ModuleType("PIL")
            img_mod = types.ModuleType("PIL.Image")
            img_mod.open = lambda bio: bio
            pil_mod.Image = img_mod
            sys.modules["PIL"] = pil_mod
            sys.modules["PIL.Image"] = img_mod

    if "boto3" not in sys.modules:
        try:
            importlib.import_module("boto3")
            stubbed["boto3"] = False
        except ImportError:
            stubbed["boto3"] = True
            boto3_mod = types.ModuleType("boto3")
            boto3_mod.client = lambda *args, **kwargs: MagicMock()
            sys.modules["boto3"] = boto3_mod

    if "fastapi" not in sys.modules:
        try:
            importlib.import_module("fastapi")
            stubbed["fastapi"] = False
        except ImportError:
            stubbed["fastapi"] = True
            fa_mod = types.ModuleType("fastapi")

            class HTTPException(Exception):
                def __init__(self, status_code: int, detail: str = ""):
                    super().__init__(detail)
                    self.status_code = status_code
                    self.detail = detail

            class FastAPI:
                def __init__(self, *args, **kwargs):
                    self.state = types.SimpleNamespace()

                def add_exception_handler(self, *args, **kwargs):
                    pass

                def get(self, *args, **kwargs):
                    return lambda fn: fn

                def post(self, *args, **kwargs):
                    return lambda fn: fn

                def patch(self, *args, **kwargs):
                    return lambda fn: fn

            class BackgroundTasks:
                def __init__(self):
                    self.tasks = []

                def add_task(self, fn, *args, **kwargs):
                    self.tasks.append((fn, args, kwargs))

            fa_mod.BackgroundTasks = BackgroundTasks
            fa_mod.Depends = lambda x=None: x
            fa_mod.FastAPI = FastAPI
            fa_mod.Header = lambda default=None: default
            fa_mod.HTTPException = HTTPException
            fa_mod.Query = lambda default=None: default
            fa_mod.Request = object
            sys.modules["fastapi"] = fa_mod

    if "pydantic" not in sys.modules:
        try:
            importlib.import_module("pydantic")
            stubbed["pydantic"] = False
        except ImportError:
            stubbed["pydantic"] = True
            pyd_mod = types.ModuleType("pydantic")

            class BaseModel:
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)

            pyd_mod.BaseModel = BaseModel
            pyd_mod.Field = lambda default=None, **kwargs: default
            sys.modules["pydantic"] = pyd_mod

    if "slowapi" not in sys.modules:
        try:
            importlib.import_module("slowapi")
            stubbed["slowapi"] = False
        except ImportError:
            stubbed["slowapi"] = True
            slow_mod = types.ModuleType("slowapi")
            slow_err = types.ModuleType("slowapi.errors")
            slow_util = types.ModuleType("slowapi.util")

            class Limiter:
                def __init__(self, *args, **kwargs):
                    pass

                def limit(self, *args, **kwargs):
                    return lambda fn: fn

            slow_mod.Limiter = Limiter
            slow_mod._rate_limit_exceeded_handler = lambda *a, **k: None
            slow_err.RateLimitExceeded = Exception
            slow_util.get_remote_address = lambda *a, **k: "127.0.0.1"
            sys.modules["slowapi"] = slow_mod
            sys.modules["slowapi.errors"] = slow_err
            sys.modules["slowapi.util"] = slow_util

    try:
        sb_pkg = importlib.import_module("supabase")
        if not hasattr(sb_pkg, "Client"):
            raise ImportError("Namespace package without Client")
        stubbed["supabase"] = False
    except ImportError:
        stubbed["supabase"] = True
        sb_mod = types.ModuleType("supabase")

        class Client:
            pass

        sb_mod.Client = Client
        sb_mod.create_client = lambda url, key: Client()
        sys.modules["supabase"] = sb_mod

    return stubbed


STUBBED_MODULES = _install_test_stubs_if_missing()

from app.ai_providers import AIProvider  # noqa: E402
from app.embeddings import (  # noqa: E402
    BGE_M3_DIMENSIONS,
    CloudflareBgeM3Embedder,
    EmbeddingDimensionError,
    resolve_cloudflare_account_id,
    validate_embedding_vector,
)
from app import pdf_pipeline  # noqa: E402
from app import rag_service  # noqa: E402
from app import main as backend_main  # noqa: E402


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeAsyncHttpClient:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.handler(len(self.calls), url, headers, json)


class FakeSupabaseQuery:
    def __init__(self, sb, table_name: str):
        self.sb = sb
        self.table_name = table_name
        self._op = "select"
        self._payload = None
        self._filters = []
        self._limit = None
        self._single = False

    def select(self, *args, **kwargs):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        rows = self.sb.tables.setdefault(self.table_name, [])

        def _matches(row):
            return all(row.get(k) == v for k, v in self._filters)

        if self._op == "select":
            matched = [dict(r) for r in rows if _matches(r)]
            if self._limit is not None:
                matched = matched[: self._limit]
            if self._single:
                return types.SimpleNamespace(data=matched[0] if matched else None)
            return types.SimpleNamespace(data=matched)

        if self._op == "insert":
            items = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for item in items:
                copy_item = dict(item)
                if "id" not in copy_item:
                    self.sb.id_seq += 1
                    copy_item["id"] = f"{self.table_name}-{self.sb.id_seq}"
                rows.append(copy_item)
                inserted.append(dict(copy_item))
            return types.SimpleNamespace(data=inserted)

        if self._op == "update":
            updated = []
            for row in rows:
                if _matches(row):
                    row.update(self._payload)
                    updated.append(dict(row))
            return types.SimpleNamespace(data=updated)

        if self._op == "delete":
            kept = [r for r in rows if not _matches(r)]
            deleted = [r for r in rows if _matches(r)]
            self.sb.tables[self.table_name] = kept
            return types.SimpleNamespace(data=deleted)

        return types.SimpleNamespace(data=[])


class FakeSupabaseClient:
    def __init__(self, rpc_results=None):
        self.tables = {
            "documents": [],
            "document_scopes": [],
            "rule_chunks": [],
            "amendments": [],
        }
        self.id_seq = 0
        self.rpc_calls = []
        self.rpc_results = rpc_results or []

    def table(self, name: str):
        return FakeSupabaseQuery(self, name)

    def rpc(self, fn_name: str, params: dict):
        self.rpc_calls.append((fn_name, params))
        results = self.rpc_results
        return types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=list(results)))


class FakeGroqProvider(AIProvider):
    def __init__(self, response_dict: dict):
        self.provider_name = "groq"
        self.model_name = "llama-3.3-70b-versatile"
        self.response_dict = response_dict
        self.seen_messages = None

    async def generate_structured_json(self, system_prompt: str, messages: list[dict]) -> str:
        self.seen_messages = messages
        return json.dumps(self.response_dict, ensure_ascii=False)


class FakePixmap:
    def tobytes(self, fmt: str = "png"):
        return b"FAKE_PNG_IMAGE"


class FakePdfPage:
    def __init__(self, native_text: str):
        self._native_text = native_text

    def get_text(self, mode: str = "text"):
        return self._native_text

    def get_pixmap(self, dpi: int = 250):
        return FakePixmap()


class FakePdfDocument:
    def __init__(self, page_texts: list[str]):
        self._pages = [FakePdfPage(t) for t in page_texts]

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, idx):
        return self._pages[idx]

    def close(self):
        pass


class ProductionRagPipelineTests(unittest.TestCase):
    def test_01_digital_pdf_text_extraction_and_chunking(self):
        long_page = (
            "CHAPTER IV\n"
            "Rule 4.10 Limits of Speed over Facing Points.\n"
            + ("Trains running through stations over facing points shall not exceed prescribed speed. " * 26)
        )
        fake_doc = FakePdfDocument([long_page, "Rule 4.11 Authority to proceed on single line."])
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": fake_doc
            pages, used_ocr = pdf_pipeline.extract_pdf_pages_with_stats(b"%PDF-1.4\n...mock...", force_ocr=False)
        finally:
            pdf_pipeline.fitz.open = orig_open

        self.assertFalse(used_ocr)
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0][0], 1)
        self.assertEqual(pages[1][0], 2)

        chunks = pdf_pipeline.chunk_pages_with_metadata(pages, min_chars=1000, max_chars=1400, overlap_chars=200)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(c.page_number in (1, 2) for c in chunks))
        self.assertTrue(1000 <= len(chunks[0].content) <= 1450)
        self.assertEqual(chunks[0].chapter, "CHAPTER IV")
        self.assertIn("4.10", chunks[0].rule_number or "")

    def test_02_scanned_pdf_ocr_eng_and_hin_fallback(self):
        scanned_doc = FakePdfDocument(["", "  "])
        ocr_calls = []

        def fake_ocr(img, lang="eng+hin"):
            ocr_calls.append(lang)
            if len(ocr_calls) == 1:
                return "Rule 5.02 Duty of Station Master on Western Railway."
            return "नियम 5.03 रेल कर्मचारी के चिकित्सा एवं अवकाश संबंधी आदेश।"

        orig_open = pdf_pipeline.fitz.open
        orig_img_open = pdf_pipeline.Image.open
        orig_tess = pdf_pipeline.pytesseract.image_to_string
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": scanned_doc
            pdf_pipeline.Image.open = lambda bio: bio
            pdf_pipeline.pytesseract.image_to_string = fake_ocr
            pages, used_ocr = pdf_pipeline.extract_pdf_pages_with_stats(b"%PDF-1.4\n...scanned...", force_ocr=False)
        finally:
            pdf_pipeline.fitz.open = orig_open
            pdf_pipeline.Image.open = orig_img_open
            pdf_pipeline.pytesseract.image_to_string = orig_tess

        self.assertTrue(used_ocr)
        self.assertEqual(ocr_calls, ["eng+hin", "eng+hin"])
        self.assertIn("Rule 5.02", pages[0][1])
        self.assertIn("नियम 5.03", pages[1][1])

    def test_03_bge_m3_bilingual_hindi_english_embedding_and_batch_retry(self):
        old_acc = os.environ.pop("CLOUDFLARE_ACCOUNT_ID", None)
        old_r2 = os.environ.get("R2_ACCOUNT_ID")
        os.environ["R2_ACCOUNT_ID"] = "r2-acct-fallback-123"
        try:
            self.assertEqual(resolve_cloudflare_account_id(), "r2-acct-fallback-123")
        finally:
            if old_acc is not None:
                os.environ["CLOUDFLARE_ACCOUNT_ID"] = old_acc
            if old_r2 is None:
                os.environ.pop("R2_ACCOUNT_ID", None)
            else:
                os.environ["R2_ACCOUNT_ID"] = old_r2

        def handler(attempt_num, url, headers, payload):
            if attempt_num == 1:
                return FakeResponse(429, {"success": False})
            batch = payload["text"]
            return FakeResponse(
                200,
                {
                    "success": True,
                    "result": {
                        "shape": [len(batch), 1024],
                        "data": [[0.01] * 1024 for _ in batch],
                    },
                },
            )

        fake_client = FakeAsyncHttpClient(handler)
        embedder = CloudflareBgeM3Embedder(
            account_id="cf-acct-999",
            api_token="cf-secret-token",
            batch_size=2,
            max_retries=3,
            client=fake_client,
        )
        texts = [
            "रेलवे कर्मचारियों को मिलने वाले आकस्मिक अवकाश के नियम",
            "Casual leave entitlement under IREC",
            "DAR Major Penalty SF-5 procedure",
        ]
        vectors = asyncio.run(embedder.embed_texts(texts))
        self.assertEqual(len(vectors), 3)
        self.assertTrue(all(len(v) == BGE_M3_DIMENSIONS for v in vectors))
        self.assertEqual(
            fake_client.calls[0]["url"],
            "https://api.cloudflare.com/client/v4/accounts/cf-acct-999/ai/run/@cf/baai/bge-m3",
        )
        self.assertEqual(fake_client.calls[0]["headers"]["Authorization"], "Bearer cf-secret-token")

    def test_04_embedding_1024_dimension_validation(self):
        valid = validate_embedding_vector([0.1] * 1024)
        self.assertEqual(len(valid), 1024)
        with self.assertRaises(EmbeddingDimensionError):
            validate_embedding_vector([0.1] * 768)
        with self.assertRaises(EmbeddingDimensionError):
            validate_embedding_vector([0.1] * 1536)
        with self.assertRaises(EmbeddingDimensionError):
            validate_embedding_vector([float("nan")] * 1024)

    def test_05_supabase_vector_search_rpc_and_sql_contract(self):
        sql_path = REPO_ROOT / "supabase" / "migrations" / "002_production_rag.sql"
        sql_text = sql_path.read_text(encoding="utf-8")
        self.assertIn("embedding_bge_m3 vector(1024)", sql_text)
        self.assertIn("using hnsw (embedding_bge_m3 vector_cosine_ops)", sql_text)
        self.assertIn("using gin (search_tsv)", sql_text)
        self.assertIn("create or replace function public.search_railway_rules", sql_text)
        self.assertIn("d.ingestion_status = 'completed'", sql_text)
        self.assertIn("coalesce(d.status, 'published') in ('published', 'superseded', 'active')", sql_text)

        sb = FakeSupabaseClient(rpc_results=[])
        embedder = CloudflareBgeM3Embedder(
            account_id="cf-1",
            api_token="tok-1",
            client=FakeAsyncHttpClient(
                lambda n, u, h, j: FakeResponse(200, {"success": True, "result": {"data": [[0.02] * 1024]}})
            ),
        )
        asyncio.run(
            rag_service.answer_railway_rule_question(
                sb=sb,
                question="What is GR 4.10?",
                zone_id="1",
                division_id="11",
                department_id="101",
                embedder=embedder,
                ai_provider=FakeGroqProvider({}),
            )
        )
        self.assertEqual(len(sb.rpc_calls), 1)
        fn_name, params = sb.rpc_calls[0]
        self.assertEqual(fn_name, "search_railway_rules")
        self.assertEqual(len(params["query_embedding"]), 1024)
        self.assertEqual(params["p_zone_id"], "1")
        self.assertEqual(params["p_division_id"], "11")
        self.assertEqual(params["p_department_id"], "101")

    def test_06_exact_rule_number_search_ranking(self):
        candidates = [
            {
                "chunk_id": "c-semantic",
                "document_id": "d-1",
                "document_title": "General Operating Notes",
                "document_number": "WR-2020-01",
                "rule_number": "Rule 2.01",
                "authority_rank": 60,
                "search_tier": 1,
                "is_superseded": False,
                "vector_score": 0.62,
                "keyword_score": 0.05,
                "similarity_score": 0.44,
            },
            {
                "chunk_id": "c-exact",
                "document_id": "d-2",
                "document_title": "G&SR Western Railway",
                "document_number": "G&SR-WR",
                "rule_number": "GR 4.10",
                "authority_rank": 85,
                "search_tier": 4,
                "is_superseded": False,
                "vector_score": 0.48,
                "keyword_score": 0.70,
                "similarity_score": 0.55,
            },
        ]
        ranked = rag_service.rerank_and_select_chunks(candidates, "Explain GR 4.10 speed limit")
        self.assertEqual(ranked[0]["chunk_id"], "c-exact")

    def test_07_hierarchical_tier_priority_and_legal_authority(self):
        candidates = [
            {
                "chunk_id": "c-div-old",
                "document_id": "d-div",
                "document_title": "BCT Divisional Operating Instruction",
                "document_number": "BCT-OPT-12",
                "rule_number": "JPO 12",
                "authority_rank": 50,
                "effective_date": "2018-01-01",
                "search_tier": 1,
                "is_superseded": False,
                "vector_score": 0.72,
                "keyword_score": 0.20,
                "similarity_score": 0.55,
            },
            {
                "chunk_id": "c-rb-new",
                "document_id": "d-rb",
                "document_title": "Railway Board Statutory Circular",
                "document_number": "RBE 45/2024",
                "rule_number": "RBE 45/2024",
                "authority_rank": 100,
                "effective_date": "2024-06-01",
                "search_tier": 5,
                "is_superseded": False,
                "vector_score": 0.72,
                "keyword_score": 0.20,
                "similarity_score": 0.55,
            },
        ]
        ranked = rag_service.rerank_and_select_chunks(candidates, "RBE 45/2024 duty hours")
        # Railway Board (authority_rank=100) must beat lower-authority Tier-1 divisional rule
        self.assertEqual(ranked[0]["chunk_id"], "c-rb-new")

    def test_08_superseded_rule_conflict_comparison_and_warning(self):
        retrieved = [
            {
                "chunk_id": "c-new",
                "document_id": "d-new",
                "document_title": "Railway Board RBE 88/2024",
                "document_number": "RBE 88/2024",
                "rule_number": "Rule 14",
                "authority_rank": 100,
                "effective_date": "2024-09-01",
                "page_number": 3,
                "search_tier": 5,
                "search_tier_label": "Railway Board / Common",
                "is_superseded": False,
                "superseded_by_ref": None,
                "content": "Revised ceiling is 30 days per year effective 2024-09-01.",
            },
            {
                "chunk_id": "c-old",
                "document_id": "d-old",
                "document_title": "Old Divisional Memo 2019",
                "document_number": "BCT-2019-09",
                "rule_number": "Para 4",
                "authority_rank": 50,
                "effective_date": "2019-03-01",
                "page_number": 2,
                "search_tier": 1,
                "search_tier_label": "Selected Dept + Division + Zone",
                "is_superseded": True,
                "superseded_by_ref": "RBE 88/2024",
                "content": "Earlier ceiling was 15 days.",
            },
        ]
        llm_out = {
            "responseLanguage": "en",
            "isReliableAnswerFound": True,
            "directAnswer": "The revised ceiling is 30 days under RBE 88/2024.",
            "detailedExplanation": "Railway Board RBE 88/2024 overrides the 2019 Divisional Memo.",
            "applicableRuleNumber": "Rule 14",
            "officialDocumentName": "Railway Board RBE 88/2024",
            "pdfPageNumber": "3",
            "citations": [
                {
                    "documentId": "d-new",
                    "documentTitle": "Railway Board RBE 88/2024",
                    "pageNumber": 3,
                    "excerpt": "Revised ceiling is 30 days per year",
                }
            ],
        }
        grounded = rag_service.validate_and_ground_answer(llm_out, retrieved, "en", "groq", "llama-3.3-70b-versatile")
        self.assertTrue(grounded["isReliableAnswerFound"])
        self.assertIsNotNone(grounded["conflictWarning"])
        self.assertIn("Old Divisional Memo 2019", grounded["conflictWarning"])

    def test_09_grounding_validator_preserves_real_page_and_drops_hallucinations(self):
        retrieved = [
            {
                "chunk_id": "c-real",
                "document_id": "doc-real-1",
                "document_title": "IREC Vol I Official Manual",
                "document_number": "IREC-I",
                "rule_number": "Rule 523",
                "page_number": 47,
                "search_tier": 5,
                "search_tier_label": "Railway Board / Common",
                "effective_date": "2022-01-01",
                "is_superseded": False,
                "content": "Leave on average pay is admissible as specified in Rule 523.",
            }
        ]
        # LLM tries to cite a hallucinated document and a wrong page number
        llm_output = {
            "responseLanguage": "en",
            "isReliableAnswerFound": True,
            "directAnswer": "Leave on average pay is governed by Rule 523.",
            "detailedExplanation": "Details from IREC Vol I.",
            "applicableRuleNumber": "Rule 523",
            "officialDocumentName": "Invented Fake Manual",
            "pdfPageNumber": "999",
            "citations": [
                {
                    "documentId": "doc-fake-999",
                    "documentTitle": "Invented Fake Manual",
                    "pageNumber": 999,
                    "excerpt": "Made up quote",
                },
                {
                    "documentId": "doc-real-1",
                    "documentTitle": "IREC Vol I Official Manual",
                    "pageNumber": 47,
                    "excerpt": "Leave on average pay is admissible",
                },
            ],
        }
        grounded = rag_service.validate_and_ground_answer(llm_output, retrieved, "en", "groq", "llama-3.3-70b-versatile")
        self.assertEqual(len(grounded["citations"]), 1)
        self.assertEqual(grounded["citations"][0]["documentId"], "doc-real-1")
        self.assertEqual(grounded["citations"][0]["pageNumber"], 47)
        self.assertEqual(grounded["officialDocumentName"], "IREC Vol I Official Manual")
        self.assertEqual(grounded["pdfPageNumber"], "47")

    def test_10_no_relevant_document_returns_reliable_false_bilingual(self):
        sb = FakeSupabaseClient(rpc_results=[])
        embedder = CloudflareBgeM3Embedder(
            account_id="cf-1",
            api_token="tok-1",
            client=FakeAsyncHttpClient(
                lambda n, u, h, j: FakeResponse(200, {"success": True, "result": {"data": [[0.05] * 1024]}})
            ),
        )
        res_hi = asyncio.run(
            rag_service.answer_railway_rule_question(
                sb=sb,
                question="क्या कोई नियम यहाँ उपलब्ध है?",
                zone_id="1",
                division_id="11",
                department_id="101",
                preferred_language="auto",
                embedder=embedder,
                ai_provider=FakeGroqProvider({}),
            )
        )
        self.assertFalse(res_hi["isReliableAnswerFound"])
        self.assertEqual(res_hi["responseLanguage"], "hi")
        self.assertEqual(res_hi["citations"], [])

        res_en = asyncio.run(
            rag_service.answer_railway_rule_question(
                sb=sb,
                question="Unrelated cryptocurrency rules?",
                zone_id="1",
                division_id="11",
                department_id="101",
                preferred_language="en",
                embedder=embedder,
                ai_provider=FakeGroqProvider({}),
            )
        )
        self.assertFalse(res_en["isReliableAnswerFound"])
        self.assertEqual(res_en["responseLanguage"], "en")
        self.assertEqual(res_en["citations"], [])

    def test_11_duplicate_upload_and_idempotent_reindexing(self):
        sb = FakeSupabaseClient()
        sb.tables["documents"].append(
            {
                "id": "doc-dup-1",
                "title": "Existing Circular",
                "r2_object_key": "wr/bct/opt/circ.pdf",
                "file_sha256": "abc123",
                "status": "draft",
                "ingestion_status": "completed",
            }
        )
        fake_doc = FakePdfDocument(["Rule 7.1 Initial Page Text " + ("detail " * 80)])
        embedder = CloudflareBgeM3Embedder(
            account_id="cf-1",
            api_token="tok-1",
            client=FakeAsyncHttpClient(
                lambda n, u, h, j: FakeResponse(
                    200,
                    {"success": True, "result": {"data": [[0.03] * 1024 for _ in j["text"]]}},
                )
            ),
        )
        orig_open = pdf_pipeline.fitz.open
        try:
            pdf_pipeline.fitz.open = lambda stream, filetype="pdf": fake_doc
            asyncio.run(rag_service.ingest_document_bytes(sb, "doc-dup-1", b"%PDF-1.4\nfirst", embedder=embedder))
            first_count = len(sb.tables["rule_chunks"])
            asyncio.run(rag_service.ingest_document_bytes(sb, "doc-dup-1", b"%PDF-1.4\nsecond", embedder=embedder))
            second_count = len(sb.tables["rule_chunks"])
        finally:
            pdf_pipeline.fitz.open = orig_open

        self.assertGreaterEqual(first_count, 1)
        self.assertEqual(first_count, second_count)

    def test_12_unauthorized_user_upload_and_reprocess_blocked_403(self):
        employee_user = {"id": "emp-1", "email": "emp@wr.railnet.gov.in", "role": "employee"}
        with self.assertRaises(backend_main.HTTPException) as ctx1:
            asyncio.run(
                backend_main.presign_pdf_upload(
                    backend_main.PresignUploadRequest(fileName="secret.pdf", zoneCode="WR"),
                    user=employee_user,
                )
            )
        self.assertEqual(ctx1.exception.status_code, 403)

        with self.assertRaises(backend_main.HTTPException) as ctx2:
            asyncio.run(
                backend_main.import_google_drive_pdf(
                    backend_main.ImportDrivePdfRequest(
                        driveUrl="https://drive.google.com/file/d/1234567890abcdef/view",
                        title="Test",
                        issuingAuthority="WR",
                    ),
                    background_tasks=backend_main.BackgroundTasks(),
                    user=employee_user,
                )
            )
        self.assertEqual(ctx2.exception.status_code, 403)

        with self.assertRaises(backend_main.HTTPException) as ctx3:
            asyncio.run(
                backend_main.reprocess_document(
                    "doc-1",
                    backend_main.ReprocessDocumentRequest(forceOcr=False),
                    background_tasks=backend_main.BackgroundTasks(),
                    user=employee_user,
                )
            )
        self.assertEqual(ctx3.exception.status_code, 403)

    def test_13_bigint_document_id_serialization_and_rpc_contract(self):
        serialized = backend_main._serialize_admin_document(
            {
                "id": 42,
                "title": "WR Operating Manual",
                "document_type": "MANUAL",
                "issuing_authority": "Western Railway",
                "status": "published",
                "zone_id": 1,
                "division_id": 11,
                "department_id": 101,
            }
        )
        self.assertEqual(serialized["id"], "42")
        self.assertIsInstance(serialized["id"], str)
        self.assertEqual(serialized["zone_id"], "1")
        self.assertEqual(serialized["division_id"], "11")
        self.assertEqual(serialized["department_id"], "101")

        sb = FakeSupabaseClient(
            rpc_results=[
                {
                    "chunk_id": "9001",
                    "document_id": "42",
                    "document_title": "WR Operating Manual",
                    "document_number": "WR-OM-2024",
                    "document_type": "MANUAL",
                    "issuing_authority": "Western Railway",
                    "authority_rank": 85,
                    "effective_date": "2024-01-01",
                    "page_number": 12,
                    "rule_number": "Rule 3.04",
                    "chapter": "Chapter III",
                    "section_title": "Signals",
                    "content": "Under Rule 3.04, fixed signals shall be kept at danger when not in use.",
                    "search_tier": 1,
                    "search_tier_label": "Selected Dept + Division + Zone",
                    "is_superseded": False,
                    "superseded_by_ref": None,
                    "vector_score": 0.78,
                    "keyword_score": 0.65,
                    "similarity_score": 0.74,
                }
            ]
        )
        embedder = CloudflareBgeM3Embedder(
            account_id="cf-1",
            api_token="tok-1",
            client=FakeAsyncHttpClient(
                lambda n, u, h, j: FakeResponse(200, {"success": True, "result": {"data": [[0.04] * 1024]}})
            ),
        )
        groq_provider = FakeGroqProvider(
            {
                "responseLanguage": "en",
                "isReliableAnswerFound": True,
                "directAnswer": "Fixed signals must be kept at danger when not in use (Rule 3.04).",
                "detailedExplanation": "Per WR Operating Manual Page 12, Rule 3.04 governs fixed signals.",
                "applicableRuleNumber": "Rule 3.04",
                "officialDocumentName": "WR Operating Manual",
                "pdfPageNumber": "12",
                "citations": [
                    {
                        "documentId": "42",
                        "documentTitle": "WR Operating Manual",
                        "pageNumber": 12,
                        "excerpt": "Under Rule 3.04, fixed signals shall be kept at danger",
                    }
                ],
            }
        )
        ans = asyncio.run(
            rag_service.answer_railway_rule_question(
                sb=sb,
                question="What does Rule 3.04 say about fixed signals?",
                zone_id="1",
                division_id="11",
                department_id="101",
                embedder=embedder,
                ai_provider=groq_provider,
            )
        )
        self.assertTrue(ans["isReliableAnswerFound"])
        self.assertEqual(ans["citations"][0]["documentId"], "42")
        self.assertEqual(ans["citations"][0]["pageNumber"], 12)


if __name__ == "__main__":
    unittest.main()
