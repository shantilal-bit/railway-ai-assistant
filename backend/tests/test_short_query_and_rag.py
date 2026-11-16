"""Unit & Contract Tests for Short Query Understanding, Bilingual Search, Error Handling, and Migration 003.

Note: These tests verify query normalization, language detection, reranking, GR/SR co-retrieval,
continuation chunk enrichment, FTS fallback, Groq error/JSON resilience, JWT 401 mapping, and
SQL migration 003 contracts locally using controlled mock responses (not live Supabase/Groq APIs).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import types
import unittest

import test_rag_pipeline as base_tests  # Installs import stubs cleanly if needed

from app import main as backend_main
from app import rag_service
from app.ai_providers import AIProviderError, GroqProvider, strip_json_markdown_fences
from app.embeddings import CloudflareBgeM3Embedder
from app.query_understanding import detect_query_language, normalize_railway_query

REPO_ROOT = Path(__file__).resolve().parents[2]


class ShortQueryAndRagTests(unittest.TestCase):
    def test_01_short_query_normalization_for_all_10_sample_queries(self):
        cases = [
            ("पंचमैन की ड्यूटी?", "Pointsman", True, "hi"),
            ("पॉइंट्समैन क्या करता है?", "Pointsman", False, "hi"),
            ("पॉइंट्समैन की क्या ड्यूटी है?", "Pointsman", True, "hi"),
            ("pointsman ki duty kya hai?", "Pointsman", True, "hi"),
            ("What are the duties of a Pointsman?", "Pointsman", True, "en"),
            ("गेटमैन की ड्यूटी?", "Gateman", True, "hi"),
            ("स्टेशन मास्टर की जिम्मेदारियाँ?", "Station Master", True, "hi"),
            ("SPAD क्या है?", "SPAD (Signal Passed At Danger)", False, "hi"),
            ("GR 4.10", None, False, "en"),
            ("Fog signal?", "Fog Signal / Detonator", False, "hi" if False else "en"),
        ]
        for query, expected_concept, expect_duty, expected_lang in cases:
            norm = normalize_railway_query(query)
            self.assertEqual(norm.original_query, query.strip())
            if expected_concept:
                self.assertIn(expected_concept, norm.matched_concepts, f"Missed concept for {query!r}")
            self.assertEqual(norm.has_duty_intent, expect_duty, f"Duty mismatch for {query!r}")
            self.assertEqual(detect_query_language(query, "auto"), expected_lang, f"Lang mismatch for {query!r}")
            self.assertTrue(len(norm.embedding_query) >= len(norm.original_query))
            self.assertTrue(bool(norm.fts_query))

        # Numeric rule query "4.10?" must produce bidirectional tokens
        norm_num = normalize_railway_query("4.10?")
        self.assertIn("4.10", norm_num.rule_tokens)
        self.assertIn("GR 4.10", norm_num.rule_tokens)
        self.assertIn("SR 4.10", norm_num.rule_tokens)

        # UI override precedence for Hinglish & English
        self.assertEqual(detect_query_language("pointsman ki duty kya hai?", "hi"), "hi")
        self.assertEqual(detect_query_language("What are the duties of a Pointsman?", "en"), "en")
        self.assertEqual(detect_query_language("What are the duties of a Pointsman?", "hi"), "hi")

    def test_02_ambiguous_unknown_terms_do_not_guess_wrong_post(self):
        norm = normalize_railway_query("xyzqwert क्या है?")
        self.assertEqual(norm.matched_concepts, ())
        self.assertEqual(norm.rule_tokens, ())
        self.assertEqual(norm.original_query, "xyzqwert क्या है?")

    def test_03_bidirectional_rule_match_and_gr_sr_coretrieval(self):
        candidates = [
            {
                "chunk_id": "c-gr",
                "document_id": "1",
                "document_title": "General and Subsidiary Rules (G&SR)",
                "document_number": "WR-GSR",
                "rule_number": "GR 4.10",
                "authority_rank": 95,
                "search_tier": 5,
                "page_number": 72,
                "is_superseded": False,
                "vector_score": 0.45,
                "keyword_score": 0.40,
                "similarity_score": 0.43,
                "content": "4.10 Limits of speed over facing points: max 15 kmph unless interlocked.",
            },
            {
                "chunk_id": "c-sr",
                "document_id": "1",
                "document_title": "General and Subsidiary Rules (G&SR)",
                "document_number": "WR-GSR",
                "rule_number": "SR 4.10.1",
                "authority_rank": 95,
                "search_tier": 5,
                "page_number": 73,
                "is_superseded": False,
                "vector_score": 0.34,
                "keyword_score": 0.25,
                "similarity_score": 0.31,
                "content": "SR 4.10.1 When facing points are clamped and padlocked, speed up to 30 kmph...",
            },
        ]
        # Force max_chunks=1 to confirm companion SR 4.10.1 is retained with GR 4.10
        selected = rag_service.rerank_and_select_chunks(candidates, "4.10?", max_chunks=1)
        selected_rules = {c["rule_number"] for c in selected}
        self.assertIn("GR 4.10", selected_rules)
        self.assertIn("SR 4.10.1", selected_rules)

    def test_04_adaptive_rescue_for_short_cross_lingual_query_vs_unrelated_rejection(self):
        short_query_candidates = [
            {
                "chunk_id": "c-pm-1",
                "document_id": "1",
                "document_title": "General and Subsidiary Rules (G&SR)",
                "rule_number": "SR 5.14.1",
                "section_title": "Duties of Pointsman",
                "authority_rank": 95,
                "search_tier": 5,
                "page_number": 118,
                "is_superseded": False,
                "vector_score": 0.22,
                "keyword_score": 0.05,
                "similarity_score": 0.20,
                "content": "The Pointsman shall ensure points are properly set, clamped, and exhibit hand signals.",
            }
        ]
        norm = normalize_railway_query("पंचमैन की ड्यूटी?")
        selected = rag_service.rerank_and_select_chunks(
            short_query_candidates,
            "पंचमैन की ड्यूटी?",
            normalized_query=norm,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["chunk_id"], "c-pm-1")

        # Unrelated query with same low vector score MUST still be rejected
        unrelated_norm = normalize_railway_query("Bitcoin crypto trading rules?")
        rejected = rag_service.rerank_and_select_chunks(
            short_query_candidates,
            "Bitcoin crypto trading rules?",
            normalized_query=unrelated_norm,
        )
        self.assertEqual(rejected, [])

    def test_05_multi_chunk_continuation_and_fts_fallback_on_embedding_error(self):
        sb = base_tests.FakeSupabaseClient(
            rpc_results=[
                {
                    "chunk_id": "rc-1",
                    "document_id": "1",
                    "document_title": "General and Subsidiary Rules (G&SR)",
                    "document_number": "WR-GSR",
                    "document_type": "RULE_BOOK",
                    "issuing_authority": "Western Railway",
                    "authority_rank": 95,
                    "effective_date": "2023-01-01",
                    "page_number": 118,
                    "rule_number": "SR 5.14.1",
                    "chapter": "Chapter V",
                    "section_title": "Duties of Pointsman",
                    "content": "Pointsman duties part 1: check facing points and display hand signal.",
                    "search_tier": 5,
                    "search_tier_label": "Railway Board / Common",
                    "is_superseded": False,
                    "superseded_by_ref": None,
                    "vector_score": 0.0,
                    "keyword_score": 0.45,
                    "similarity_score": 0.45,
                }
            ]
        )
        sb.tables["rule_chunks"] = [
            {
                "id": "rc-1",
                "document_id": "1",
                "chunk_index": 200,
                "page_number": 118,
                "rule_number": "SR 5.14.1",
                "chapter": "Chapter V",
                "section_title": "Duties of Pointsman",
                "content": "Pointsman duties part 1: check facing points and display hand signal.",
            },
            {
                "id": "rc-2",
                "document_id": "1",
                "chunk_index": 201,
                "page_number": 119,
                "rule_number": "SR 5.14.1",
                "chapter": "Chapter V",
                "section_title": "Duties of Pointsman (cont.)",
                "content": "Pointsman duties part 2: pilot shunting movements and obey Station Master.",
            },
        ]

        # Simulate Cloudflare outage (HTTP 503 after retries)
        failing_embedder = CloudflareBgeM3Embedder(
            account_id="cf-1",
            api_token="tok-1",
            max_retries=1,
            client=base_tests.FakeAsyncHttpClient(lambda n, u, h, j: base_tests.FakeResponse(503, {})),
        )
        groq_provider = base_tests.FakeGroqProvider(
            {
                "responseLanguage": "hi",
                "isReliableAnswerFound": True,
                "directAnswer": "पॉइंट्समैन (Pointsman) का मुख्य कार्य काँटा जाँचना, हस्त सिग्नल दिखाना और शंटिंग में पायलटिंग करना है।",
                "detailedExplanation": "नियम SR 5.14.1 के अनुसार पॉइंट्समैन को फेसिंग पॉइंट्स की जाँच करनी होती है और स्टेशन मास्टर के निर्देशानुसार शंटिंग करानी होती है।",
                "applicableRuleNumber": "SR 5.14.1",
                "officialDocumentName": "General and Subsidiary Rules (G&SR)",
                "pdfPageNumber": "118",
                "citations": [
                    {
                        "documentId": "1",
                        "documentTitle": "General and Subsidiary Rules (G&SR)",
                        "pageNumber": 118,
                        "excerpt": "Pointsman duties part 1",
                    },
                    {
                        "documentId": "1",
                        "documentTitle": "General and Subsidiary Rules (G&SR)",
                        "pageNumber": 119,
                        "excerpt": "Pointsman duties part 2",
                    },
                ],
            }
        )

        res = asyncio.run(
            rag_service.answer_railway_rule_question(
                sb=sb,
                question="पंचमैन की ड्यूटी?",
                zone_id="1",
                division_id="11",
                department_id="101",
                preferred_language="auto",
                embedder=failing_embedder,
                ai_provider=groq_provider,
            )
        )
        self.assertTrue(res["isReliableAnswerFound"])
        self.assertEqual(res["responseLanguage"], "hi")
        self.assertEqual(len(res["citations"]), 2)
        # Confirm FTS-only fallback passed query_embedding=None and expanded English keywords
        _, rpc_params = sb.rpc_calls[0]
        self.assertIsNone(rpc_params["query_embedding"])
        self.assertIn("Pointsman", rpc_params["query_text"])
        # Confirm continuation chunk content reached Groq
        self.assertIn("Pointsman duties part 2", groq_provider.seen_messages[-1]["content"])

    def test_06_json_fence_stripping_and_groq_error_handling(self):
        fenced = '```json\n{"responseLanguage": "hi", "isReliableAnswerFound": true}\n```'
        stripped = strip_json_markdown_fences(fenced)
        self.assertEqual(json.loads(stripped)["responseLanguage"], "hi")

        old_key = os.environ.get("GROQ_API_KEY")
        os.environ["GROQ_API_KEY"] = "gsk_super_secret_test_value"
        try:
            provider = GroqProvider(max_retries=1)
            self.assertGreaterEqual(provider.max_tokens, 2000)

            class FakeGroqHttpClient:
                def __init__(self, *args, **kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

                async def post(self, url, headers=None, json=None):
                    return base_tests.FakeResponse(
                        404,
                        {"error": {"type": "invalid_request_error", "code": "model_not_found", "message": "Model missing"}},
                    )

            orig_client = sys_async_client = None
            import app.ai_providers as ai_mod

            orig_client = ai_mod.httpx.AsyncClient
            ai_mod.httpx.AsyncClient = FakeGroqHttpClient
            try:
                with self.assertRaises(AIProviderError) as ctx:
                    asyncio.run(provider.generate_structured_json("sys", [{"role": "user", "content": "hi"}]))
                self.assertEqual(ctx.exception.status_code, 404)
                self.assertEqual(ctx.exception.error_code, "model_not_found")
                self.assertNotIn("gsk_super_secret_test_value", str(ctx.exception))
            finally:
                ai_mod.httpx.AsyncClient = orig_client
        finally:
            if old_key is None:
                os.environ.pop("GROQ_API_KEY", None)
            else:
                os.environ["GROQ_API_KEY"] = old_key

    def test_07_expired_jwt_returns_401_not_500(self):
        class BrokenAuthSb:
            class auth:
                @staticmethod
                def get_user(token):
                    raise RuntimeError("JWT expired")

        orig_get_sb = backend_main.get_supabase
        backend_main.get_supabase = lambda: BrokenAuthSb()
        try:
            with self.assertRaises(backend_main.HTTPException) as ctx:
                asyncio.run(backend_main.get_current_user("Bearer expired.jwt.token"))
            self.assertEqual(ctx.exception.status_code, 401)
        finally:
            backend_main.get_supabase = orig_get_sb

    def test_08_migration_003_non_destructive_and_preserves_signature(self):
        sql_path = REPO_ROOT / "supabase" / "migrations" / "003_short_query_and_hybrid_search.sql"
        sql_text = sql_path.read_text(encoding="utf-8")
        sql_low = sql_text.lower()

        for pattern in (r"\bdrop\s+table\b", r"\btruncate\b", r"\bdelete\s+from\b", r"\bdrop\s+column\b"):
            self.assertIsNone(re.search(pattern, sql_low))

        self.assertIn("create or replace function public.build_railway_or_tsquery", sql_low)
        self.assertIn("create or replace function public.search_railway_rules", sql_low)
        self.assertIn("query_embedding vector(1024)", sql_low)
        self.assertIn("query_embedding is null", sql_low)
        self.assertIn("to authenticated, service_role", sql_low)
        # Bug 1 & Bug 2 SQL checks: monotonic formula and boundary-aware rule matching (digit + dot rejected)
        self.assertIn("0.92 * s.vector_score + 0.08 * least(1.0, s.keyword_score)", sql_low)
        self.assertNotIn("when s.keyword_score <= 0.001", sql_low)
        self.assertNotIn("like '%' || rt.tok || '%'", sql_low)
        self.assertIn("(?:^|[^0-9.])", sql_low)
        self.assertIn("(?:$|[^0-9.])", sql_low)
        self.assertNotIn("(?:$|[^0-9])", sql_low)

        dollar_tags = re.findall(r"\$[a-zA-Z_]*\$", sql_text)
        self.assertEqual(len(dollar_tags) % 2, 0)

    def test_09_regression_sql_hybrid_scoring_is_monotonic_in_keyword_score(self):
        def _sql_hybrid_score(v: float, k: float) -> float:
            k_cap = min(1.0, max(0.0, k))
            return max(0.92 * v + 0.08 * k_cap, 0.68 * v + 0.32 * k_cap)

        for v in (0.15, 0.30, 0.45, 0.60, 0.85, 1.0):
            zero_kw = _sql_hybrid_score(v, 0.0)
            prev = zero_kw
            for k in (0.001, 0.05, 0.15, 0.30, 0.50, 0.80, 1.0, 1.5):
                curr = _sql_hybrid_score(v, k)
                self.assertGreaterEqual(curr, zero_kw)
                self.assertGreaterEqual(curr, prev)
                prev = curr

    def test_10_regression_boundary_aware_rule_matching_rejects_4_10_for_gr_4_1(self):
        # Verify exact rule-number matching directly (rejecting both digit AND dot suffixes)
        tokens_4_1 = normalize_railway_query("GR 4.1").rule_tokens
        self.assertTrue(rag_service._rule_matches_bidirectionally("GR 4.1", "gr 4.1", tokens_4_1))
        self.assertFalse(rag_service._rule_matches_bidirectionally("GR 4.10", "gr 4.1", tokens_4_1))
        self.assertFalse(rag_service._rule_matches_bidirectionally("SR 4.12", "gr 4.1", tokens_4_1))
        self.assertFalse(rag_service._rule_matches_bidirectionally("SR 4.1.1", "gr 4.1", tokens_4_1))

        tokens_4_10 = normalize_railway_query("GR 4.10").rule_tokens
        self.assertTrue(rag_service._rule_matches_bidirectionally("GR 4.10", "gr 4.10", tokens_4_10))
        self.assertFalse(rag_service._rule_matches_bidirectionally("GR 4.1", "gr 4.10", tokens_4_10))

        # Verify SQL regex pattern semantics identically reject digit & dot after 4.1
        sql_pattern = re.compile(r"(?:^|[^0-9.])4\.1(?:$|[^0-9.])")
        self.assertIsNotNone(sql_pattern.search("gr 4.1"))
        self.assertIsNone(sql_pattern.search("gr 4.10"))
        self.assertIsNone(sql_pattern.search("sr 4.12"))
        self.assertIsNone(sql_pattern.search("sr 4.1.1"))
        sql_pattern_410 = re.compile(r"(?:^|[^0-9.])4\.10(?:$|[^0-9.])")
        self.assertIsNotNone(sql_pattern_410.search("gr 4.10"))

        candidates = [
            {
                "chunk_id": "c-wrong-410",
                "document_id": "1",
                "document_title": "General and Subsidiary Rules (G&SR)",
                "rule_number": "GR 4.10",
                "authority_rank": 95,
                "search_tier": 5,
                "page_number": 72,
                "is_superseded": False,
                "vector_score": 0.25,
                "keyword_score": 0.02,
                "similarity_score": 0.22,
                "content": "GR 4.10 Speed over facing points.",
            },
            {
                "chunk_id": "c-wrong-412",
                "document_id": "1",
                "document_title": "General and Subsidiary Rules (G&SR)",
                "rule_number": "SR 4.12",
                "authority_rank": 95,
                "search_tier": 5,
                "page_number": 75,
                "is_superseded": False,
                "vector_score": 0.24,
                "keyword_score": 0.02,
                "similarity_score": 0.21,
                "content": "SR 4.12 Another unrelated rule.",
            },
            {
                "chunk_id": "c-exact-41",
                "document_id": "1",
                "document_title": "General and Subsidiary Rules (G&SR)",
                "rule_number": "GR 4.1",
                "authority_rank": 95,
                "search_tier": 5,
                "page_number": 60,
                "is_superseded": False,
                "vector_score": 0.22,
                "keyword_score": 0.70,
                "similarity_score": 0.43,
                "content": "GR 4.1 Standard rule provision.",
            },
            {
                "chunk_id": "c-sub-411",
                "document_id": "1",
                "document_title": "General and Subsidiary Rules (G&SR)",
                "rule_number": "SR 4.1.1",
                "authority_rank": 95,
                "search_tier": 5,
                "page_number": 61,
                "is_superseded": False,
                "vector_score": 0.26,
                "keyword_score": 0.20,
                "similarity_score": 0.27,
                "content": "SR 4.1.1 Subsidiary provision companion text.",
            },
        ]
        selected = rag_service.rerank_and_select_chunks(candidates, "GR 4.1", max_chunks=4)
        selected_rules = [c["rule_number"] for c in selected]
        self.assertIn("GR 4.1", selected_rules)
        self.assertIn("SR 4.1.1", selected_rules)
        self.assertNotIn("GR 4.10", selected_rules)
        self.assertNotIn("SR 4.12", selected_rules)
        # Ensure GR 4.1 ranks ahead of SR 4.1.1 because only GR 4.1 gets exact rule-number boost
        self.assertEqual(selected_rules[0], "GR 4.1")

        # Companion pairing retains SR 4.1.1 with GR 4.1 via _core_rule_digits, never GR 4.10
        paired = rag_service.rerank_and_select_chunks(candidates, "GR 4.1", max_chunks=1)
        paired_rules = {c["rule_number"] for c in paired}
        self.assertEqual(paired_rules, {"GR 4.1", "SR 4.1.1"})

        # Verify GR 4.10 query matches GR 4.10 directly
        selected_410 = rag_service.rerank_and_select_chunks(candidates, "GR 4.10", max_chunks=2)
        self.assertEqual(selected_410[0]["rule_number"], "GR 4.10")

    def test_11_regression_generic_duty_rules_words_do_not_trigger_concept_rescue(self):
        norm = normalize_railway_query("पंचमैन की ड्यूटी?")
        self.assertNotIn("duties", norm.expanded_keywords)
        self.assertNotIn("responsibilities", norm.expanded_keywords)
        self.assertNotIn("rules", norm.expanded_keywords)

        unrelated_post_chunk = [
            {
                "chunk_id": "c-wrong-post",
                "document_id": "1",
                "document_title": "General and Subsidiary Rules (G&SR)",
                "rule_number": "GR 5.01",
                "section_title": "Station Master Responsibilities",
                "authority_rank": 95,
                "search_tier": 5,
                "page_number": 90,
                "is_superseded": False,
                "vector_score": 0.21,
                "keyword_score": 0.04,
                "similarity_score": 0.20,
                "content": "General duties and responsibilities under railway rules for station operations.",
            }
        ]
        rescued = rag_service.rerank_and_select_chunks(
            unrelated_post_chunk,
            "पंचमैन की ड्यूटी?",
            normalized_query=norm,
        )
        self.assertEqual(rescued, [])

    def test_12_regression_adjacent_continuation_fetches_max_extra_and_stops_at_different_rule(self):
        # 1) When max_extra=2 and next two chunks belong to the same rule, BOTH are appended
        sb_same = base_tests.FakeSupabaseClient()
        sb_same.tables["rule_chunks"] = [
            {"id": "c-10", "document_id": "1", "chunk_index": 10, "page_number": 72, "rule_number": "GR 4.10", "chapter": "Ch IV", "section_title": "4.10", "content": "Part 1"},
            {"id": "c-11", "document_id": "1", "chunk_index": 11, "page_number": 72, "rule_number": "GR 4.10", "chapter": "Ch IV", "section_title": "4.10", "content": "Part 2"},
            {"id": "c-12", "document_id": "1", "chunk_index": 12, "page_number": 73, "rule_number": "GR 4.10", "chapter": "Ch IV", "section_title": "4.10", "content": "Part 3"},
        ]
        top_chunk = {
            "chunk_id": "c-10",
            "document_id": "1",
            "document_title": "G&SR",
            "page_number": 72,
            "rule_number": "GR 4.10",
            "search_tier": 5,
            "search_tier_label": "Common",
            "is_superseded": False,
        }
        enriched_same = rag_service._fetch_adjacent_continuation_chunks(sb_same, [top_chunk], max_extra=2)
        self.assertEqual([c["chunk_id"] for c in enriched_same], ["c-10", "c-11", "c-12"])

        # 2) When next chunk on the SAME page belongs to a DIFFERENT rule (GR 4.11), it must NOT be appended
        sb_diff = base_tests.FakeSupabaseClient()
        sb_diff.tables["rule_chunks"] = [
            {"id": "c-10", "document_id": "1", "chunk_index": 10, "page_number": 72, "rule_number": "GR 4.10", "chapter": "Ch IV", "section_title": "4.10", "content": "Part 1"},
            {"id": "c-11", "document_id": "1", "chunk_index": 11, "page_number": 72, "rule_number": "GR 4.11", "chapter": "Ch IV", "section_title": "4.11", "content": "Different rule"},
            {"id": "c-12", "document_id": "1", "chunk_index": 12, "page_number": 73, "rule_number": "GR 4.11", "chapter": "Ch IV", "section_title": "4.11", "content": "Different rule cont"},
        ]
        enriched_diff = rag_service._fetch_adjacent_continuation_chunks(sb_diff, [top_chunk], max_extra=2)
        self.assertEqual([c["chunk_id"] for c in enriched_diff], ["c-10"])


if __name__ == "__main__":
    unittest.main()
