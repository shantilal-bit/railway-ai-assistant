"""Dedicated Mocked Unit Tests for Read-Only Dry-Run Audit Script (backend/scripts/gsr_dry_run_audit.py).

Note: All PDF, Cloudflare R2, Token Inspection API, and Supabase interactions here are
100% synthetic/mocked. Passing these tests proves ONLY script logic — NOT real PDF parsing.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "gsr_dry_run_audit.py"
for _p in (str(TESTS_DIR), str(BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_rag_pipeline as base_tests  # noqa: F401,E402
from app.pdf_pipeline import ExtractedChunk, ExtractedPage, PageLineInfo  # noqa: E402


def _load_script_module():
    spec = importlib.util.spec_from_file_location("gsr_dry_run_audit", str(SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


DRY = _load_script_module()
MODS = DRY._load_backend_modules(BACKEND_DIR)


def _make_jwt(claims: dict) -> str:
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    pl = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{hdr}.{pl}.mock_sig"


class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, table_name, state):
        self.table_name = table_name
        self.state = state
        self.range_bounds = None

    def select(self, cols):
        self.state["selects"].append((self.table_name, cols))
        return self

    def eq(self, col, val):
        return self

    def order(self, col, desc=False):
        return self

    def range(self, start, end):
        self.range_bounds = (start, end)
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self.table_name == "profiles":
            if self.state.get("profile_exc") is not None:
                raise self.state["profile_exc"]
            return _FakeResp(self.state["profile_row"])
        if self.table_name == "documents":
            return _FakeResp(self.state["doc_row"])
        rows = self.state["chunk_rows"]
        if self.range_bounds is not None:
            s, e = self.range_bounds
            return _FakeResp(rows[s : e + 1])
        return _FakeResp(rows)


class _FakeSupabase:
    def __init__(self, doc_row, chunk_rows, profile_row="__DEFAULT__", profile_exc=None):
        if profile_row == "__DEFAULT__":
            profile_row = {"id": "user-123", "role": "employee"}
        self.state = {
            "doc_row": doc_row,
            "chunk_rows": chunk_rows,
            "profile_row": profile_row,
            "profile_exc": profile_exc,
            "selects": [],
        }
        self.postgrest = type("_PG", (), {"auth": lambda _s, _t: None})()

    def table(self, name):
        return _FakeQuery(name, self.state)


class _FakeR2:
    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF")}

    def put_object(self, **kwargs):
        raise AssertionError("put_object must never be called")


class _FakeUrlopenResp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _make_valid_doc(**overrides):
    base = {
        "id": 1,
        "title": "G&SR",
        "document_number": "GSR-CS108",
        "document_type": "RULE_BOOK",
        "status": "published",
        "ingestion_status": "completed",
        "ocr_status": "not_needed",
        "chunk_count": 1309,
        "page_count": 552,
        "r2_object_key": DRY.TARGET_R2_OBJECT_KEY,
    }
    base.update(overrides)
    return base


def _make_1309_rows():
    rows = []
    for i in range(1309):
        page = (i // 3) + 1
        rows.append(
            {
                "id": i + 1,
                "chunk_index": i,
                "page_number": page,
                "rule_number": "green" if i == 522 else f"GR {1 + (i // 100)}.{(i % 99) + 1:02d}",
                "chapter": "CHAPTER I",
                "section_title": "Sample",
                "token_count": 100,
            }
        )
    return rows


class DryRunAuditScriptTests(unittest.TestCase):
    # Problem 1: Text Loss Audit scope disclaimer + OCR & extraction limitations separate report
    def test_1_text_loss_scope_and_separate_ocr_extraction_limitations(self):
        pages = (
            ExtractedPage(
                physical_page_number=1,
                text="G.R. 1.01 Short title.",
                lines=(PageLineInfo(text="G.R. 1.01 Short title."),),
                used_ocr=True,
                typography_available=False,
                removed_margin_lines=("General & Subsidiary Rules",),
            ),
            ExtractedPage(
                physical_page_number=2,
                text="",
                lines=(),
                used_ocr=True,
                typography_available=False,
            ),
        )
        chunks = (
            ExtractedChunk(
                chunk_index=0,
                page_number=1,
                rule_number="GR 1.01",
                chapter=None,
                section_title="G.R. 1.01 Short title.",
                content="G.R. 1.01 Short title.",
                token_count=4,
                physical_page_number=1,
                rule_kind="GR",
                contained_rules=("GR 1.01",),
            ),
        )
        text_audit, _ov, _pm, limits = DRY._audit_text_overlap_and_pages(pages, chunks, MODS)
        self.assertEqual(text_audit["status"], "PASS")
        self.assertEqual(text_audit["scope"], "EXTRACTED_TEXT_TO_CHUNKS_PARITY_ONLY")
        self.assertIn("visual PDF completeness not verified", text_audit["reason"])
        self.assertEqual(limits["ocr_page_count"], 2)
        self.assertEqual(limits["no_typography_page_count"], 2)
        self.assertEqual(limits["empty_text_page_count"], 1)
        self.assertEqual(limits["dict_removed_margin_lines"], 1)

    # Problem 2: Cross-page overlap & missing offsets MUST yield INCONCLUSIVE (never guessed PASS)
    def test_2_cross_page_and_missing_offset_overlap_returns_inconclusive_never_pass(self):
        pages = (
            ExtractedPage(
                physical_page_number=230,
                text="S.R. 5.13 Duties.\nSame page part one\nSame page part two",
                lines=(
                    PageLineInfo(text="S.R. 5.13 Duties."),
                    PageLineInfo(text="Same page part one"),
                    PageLineInfo(text="Same page part two"),
                ),
            ),
        )
        # Same-page continuation WITHOUT source_start_offset / source_end_offset -> must be INCONCLUSIVE
        chunks_no_offsets = (
            ExtractedChunk(
                chunk_index=0,
                page_number=230,
                rule_number="SR 5.13",
                chapter=None,
                section_title="S.R. 5.13 Duties.",
                content="S.R. 5.13 Duties.\nSame page part one",
                token_count=7,
                physical_page_number=230,
                rule_kind="SR",
                contained_rules=("SR 5.13",),
            ),
            ExtractedChunk(
                chunk_index=1,
                page_number=230,
                rule_number="SR 5.13",
                chapter=None,
                section_title="Same page part two",
                content="Same page part two",
                token_count=4,
                physical_page_number=230,
                rule_kind="SR",
                contained_rules=("SR 5.13",),
                is_continuation=True,
                continued_from_rule="SR 5.13",
                source_start_offset=None,
                source_end_offset=None,
            ),
        )
        t_res, ov_res, _pm, _lim = DRY._audit_text_overlap_and_pages(pages, chunks_no_offsets, MODS)
        self.assertEqual(ov_res["status"], "INCONCLUSIVE")
        self.assertEqual(t_res["status"], "INCONCLUSIVE")

        # Cross-page continuation repeating last >=4 tokens from prev page without offsets -> INCONCLUSIVE
        pages_cp = (
            ExtractedPage(
                physical_page_number=230,
                text="Alpha beta gamma delta epsilon.",
                lines=(PageLineInfo(text="Alpha beta gamma delta epsilon."),),
            ),
            ExtractedPage(
                physical_page_number=231,
                text="Zeta eta theta iota.",
                lines=(PageLineInfo(text="Zeta eta theta iota."),),
            ),
        )
        chunks_cp_overlap = (
            ExtractedChunk(
                chunk_index=0,
                page_number=230,
                rule_number=None,
                chapter=None,
                section_title=None,
                content="Alpha beta gamma delta epsilon.",
                token_count=5,
                physical_page_number=230,
            ),
            ExtractedChunk(
                chunk_index=1,
                page_number=231,
                rule_number=None,
                chapter=None,
                section_title=None,
                content="beta gamma delta epsilon. Zeta eta theta iota.",
                token_count=8,
                physical_page_number=231,
                is_continuation=True,
                continued_from_rule=None,
            ),
        )
        t_cp, ov_cp, _pm2, _lim2 = DRY._audit_text_overlap_and_pages(pages_cp, chunks_cp_overlap, MODS)
        self.assertEqual(ov_cp["status"], "INCONCLUSIVE")
        self.assertNotEqual(t_cp["status"], "PASS")

    # Problem 3: Independent physical page mapping rejects wrong page ownership even when global text matches!
    def test_3_independent_page_mapping_catches_wrong_physical_page_number_despite_global_match(self):
        pages = (
            ExtractedPage(
                physical_page_number=230,
                text="G.R. 5.12 Page one text.",
                lines=(PageLineInfo(text="G.R. 5.12 Page one text."),),
            ),
            ExtractedPage(
                physical_page_number=231,
                text="G.R. 5.13 Page two text.",
                lines=(PageLineInfo(text="G.R. 5.13 Page two text."),),
            ),
        )
        # Global tokens match 100%, BUT chunk 0 wrongly declares physical_page_number=231!
        wrong_owner_chunks = (
            ExtractedChunk(
                chunk_index=0,
                page_number=231,
                rule_number="GR 5.12",
                chapter=None,
                section_title="G.R. 5.12 Page one text.",
                content="G.R. 5.12 Page one text.",
                token_count=5,
                physical_page_number=231,
                rule_kind="GR",
                contained_rules=("GR 5.12",),
            ),
            ExtractedChunk(
                chunk_index=1,
                page_number=231,
                rule_number="GR 5.13",
                chapter=None,
                section_title="G.R. 5.13 Page two text.",
                content="G.R. 5.13 Page two text.",
                token_count=5,
                physical_page_number=231,
                rule_kind="GR",
                contained_rules=("GR 5.13",),
            ),
        )
        t_res, _ov, pm_res, _lim = DRY._audit_text_overlap_and_pages(pages, wrong_owner_chunks, MODS)
        self.assertEqual(t_res["status"], "PASS")
        self.assertEqual(pm_res["status"], "FAIL")

        # Valid cross-page spanning chunk (declared on start page 230, spanning 230..231) -> PASS
        spanning_chunks = (
            ExtractedChunk(
                chunk_index=0,
                page_number=230,
                rule_number="GR 5.12",
                chapter=None,
                section_title="G.R. 5.12 Page one text.",
                content="G.R. 5.12 Page one text.\nG.R. 5.13 Page two text.",
                token_count=10,
                physical_page_number=230,
                rule_kind="GR",
                contained_rules=("GR 5.12",),
            ),
        )
        t_sp, _ov_sp, pm_sp, _lim_sp = DRY._audit_text_overlap_and_pages(pages, spanning_chunks, MODS)
        self.assertEqual(t_sp["status"], "PASS")
        self.assertEqual(pm_sp["status"], "PASS")
        self.assertEqual(pm_sp["chunk_covered_pages"][0], (230, 231))

    # Problem 4: New Chunk Integrity checks uniqueness, gaps, empty content, and invalid physical_page_number
    def test_4_new_chunk_integrity_rejects_gaps_duplicates_empty_content_and_bad_pages(self):
        pages = (ExtractedPage(physical_page_number=1, text="Hello world.", lines=(PageLineInfo(text="Hello world."),)),)
        good = (
            ExtractedChunk(
                chunk_index=0, page_number=1, rule_number=None, chapter=None, section_title=None,
                content="Hello world.", token_count=2, physical_page_number=1,
            ),
        )
        self.assertEqual(DRY._audit_new_chunk_integrity(pages, good)["status"], "PASS")

        gap_chunks = (
            ExtractedChunk(chunk_index=0, page_number=1, rule_number=None, chapter=None, section_title=None, content="Hello", token_count=1, physical_page_number=1),
            ExtractedChunk(chunk_index=2, page_number=1, rule_number=None, chapter=None, section_title=None, content="world", token_count=1, physical_page_number=1),
        )
        self.assertEqual(DRY._audit_new_chunk_integrity(pages, gap_chunks)["status"], "FAIL")

        empty_chunks = (
            ExtractedChunk(chunk_index=0, page_number=1, rule_number=None, chapter=None, section_title=None, content="   ", token_count=0, physical_page_number=1),
        )
        self.assertEqual(DRY._audit_new_chunk_integrity(pages, empty_chunks)["status"], "FAIL")

        bad_page_chunks = (
            ExtractedChunk(chunk_index=0, page_number=99, rule_number=None, chapter=None, section_title=None, content="Hello", token_count=1, physical_page_number=99),
        )
        self.assertEqual(DRY._audit_new_chunk_integrity(pages, bad_page_chunks)["status"], "FAIL")

    # Problem 5: GR/SR Classification verifies rule_number, contained_rules, parent_rule & hierarchy
    def test_5_gr_sr_classification_checks_contained_rules_parent_rule_and_bleed(self):
        valid_sub = (
            ExtractedChunk(
                chunk_index=0,
                page_number=235,
                rule_number="SR 5.13.1",
                chapter="CHAPTER V",
                section_title="S.R. 5.13.1 Duties.",
                content="S.R. 5.13.1 Duties of Pointsman.",
                token_count=5,
                physical_page_number=235,
                rule_kind="SR",
                parent_rule="SR 5.13",
                contained_rules=("SR 5.13.1",),
                classification_confidence="HIGH",
            ),
        )
        self.assertEqual(DRY._audit_classification_and_hierarchy(valid_sub, MODS)["status"], "PASS")

        # Missing parent_rule on dotted SR sub-rule -> FAIL
        missing_parent = (
            ExtractedChunk(
                chunk_index=0, page_number=235, rule_number="SR 5.13.1", chapter="CHAPTER V",
                section_title="S.R. 5.13.1", content="S.R. 5.13.1 Duties.", token_count=3,
                physical_page_number=235, rule_kind="SR", parent_rule=None, contained_rules=("SR 5.13.1",),
            ),
        )
        self.assertEqual(DRY._audit_classification_and_hierarchy(missing_parent, MODS)["status"], "FAIL")

        # False/glued entry hidden inside contained_rules -> FAIL
        bad_contained = (
            ExtractedChunk(
                chunk_index=0, page_number=235, rule_number="GR 5.12", chapter=None,
                section_title="G.R. 5.12", content="G.R. 5.12 text", token_count=3,
                physical_page_number=235, rule_kind="GR", parent_rule=None,
                contained_rules=("GR 5.12", "GR 1.01at"),
            ),
        )
        self.assertEqual(DRY._audit_classification_and_hierarchy(bad_contained, MODS)["status"], "FAIL")

        # Cross-kind bleed (SR inside GR chunk) -> FAIL
        cross_kind = (
            ExtractedChunk(
                chunk_index=0, page_number=235, rule_number="GR 5.12", chapter=None,
                section_title="G.R. 5.12", content="G.R. 5.12 text", token_count=3,
                physical_page_number=235, rule_kind="GR", parent_rule=None,
                contained_rules=("SR 5.12",),
            ),
        )
        self.assertEqual(DRY._audit_classification_and_hierarchy(cross_kind, MODS)["status"], "FAIL")

    # Problem 6 & 7: Credential Security (JWT claims + DB profiles.role, Cloudflare R2 exact bucket scope, proxies & exit codes 0/1/2)
    def test_6_and_7_credential_security_and_exit_codes_0_1_2(self):
        anon_jwt = _make_jwt({"role": "anon", "exp": 9999999999})
        auth_jwt = _make_jwt({"role": "authenticated", "sub": "user-123", "exp": 9999999999})
        service_jwt = _make_jwt({"role": "service_role", "exp": 9999999999})

        # Valid non-admin authenticated JWT passes local claim check (notes signature_verified_locally=False)
        jwt_ok = DRY._verify_supabase_jwt_claims(anon_jwt, auth_jwt)
        self.assertEqual(jwt_ok["readonly_role"], "authenticated")
        self.assertEqual(jwt_ok["sub"], "user-123")
        self.assertFalse(jwt_ok["signature_verified_locally"])

        # R2 credential matching R2_ACCESS_KEY_ID MUST BE REJECTED
        with self.assertRaises(PermissionError):
            DRY._verify_r2_readonly_permission("acc1", "same_key", "same_key", bucket_name="bucket_mock")

        # Missing CLOUDFLARE_TOKEN_INSPECT_API_KEY -> cannot verify policy/scope -> INCONCLUSIVE
        with patch.dict(os.environ, {}, clear=True):
            r2_st, _ = DRY._verify_r2_readonly_permission("acc1", "ro_tok_1", "rw_key_2", bucket_name="bucket_mock")
            self.assertEqual(r2_st, "INCONCLUSIVE")

        # Exact bucket scope + active R2 Read -> PASS
        exact_ro_payload = {
            "success": True,
            "result": {
                "id": "ro_tok_id",
                "status": "active",
                "policies": [
                    {
                        "effect": "allow",
                        "resources": {"com.cloudflare.edge.r2.bucket.acc_mock_default_bucket_mock": "*"},
                        "permission_groups": [{"name": "Workers R2 Storage Read"}],
                    }
                ],
            },
        }
        syn_pages = [
            ExtractedPage(
                physical_page_number=230,
                text="S.R. 5.13 Duties of Pointsman.\nLock the facing points.",
                lines=(
                    PageLineInfo(text="S.R. 5.13 Duties of Pointsman.", is_bold=True, leading_is_bold=True),
                    PageLineInfo(text="Lock the facing points."),
                ),
                printed_page_candidate=210,
                printed_page_status="MARGIN_CANDIDATE",
            ),
        ]
        base_env = {
            "R2_ACCOUNT_ID": "acc_mock",
            "R2_BUCKET_NAME": "bucket_mock",
            "R2_READONLY_ACCESS_KEY_ID": "ro_tok_id",
            "R2_READONLY_SECRET_ACCESS_KEY": "ro_secret_mock",
            "R2_ACCESS_KEY_ID": "rw_tok_id",
            "CLOUDFLARE_TOKEN_INSPECT_API_KEY": "cf_inspect_tok",
            "SUPABASE_URL": "https://mock.supabase.co",
            "SUPABASE_ANON_KEY": anon_jwt,
            "SUPABASE_READONLY_JWT": auth_jwt,
        }
        fake_sb_employee = _FakeSupabase(_make_valid_doc(), _make_1309_rows(), profile_row={"id": "user-123", "role": "employee"})
        fake_r2 = _FakeR2()

        with (
            patch.dict(os.environ, base_env, clear=True),
            patch("boto3.client", return_value=fake_r2),
            patch("supabase.create_client", return_value=fake_sb_employee),
            patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(exact_ro_payload)),
            patch.object(DRY, "_load_backend_modules", return_value={**MODS, "extract_pdf_pages_detailed": lambda _b, force_ocr=False: (syn_pages, False)}),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_PASS)
            self.assertIn(("profiles", "id,role"), fake_sb_employee.state["selects"])

        # Missing CLOUDFLARE_TOKEN_INSPECT_API_KEY -> INCONCLUSIVE -> MUST return Exit Code 2 (never 0!)
        env_unverified_r2 = {k: v for k, v in base_env.items() if k != "CLOUDFLARE_TOKEN_INSPECT_API_KEY"}
        with (
            patch.dict(os.environ, env_unverified_r2, clear=True),
            patch("boto3.client", return_value=fake_r2),
            patch("supabase.create_client", return_value=fake_sb_employee),
            patch.object(DRY, "_load_backend_modules", return_value={**MODS, "extract_pdf_pages_detailed": lambda _b, force_ocr=False: (syn_pages, False)}),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_INCONCLUSIVE)

        # service_role JWT inside SUPABASE_READONLY_JWT -> FAIL -> Exit Code 1
        env_service_jwt = {**base_env, "SUPABASE_READONLY_JWT": service_jwt}
        with (
            patch.dict(os.environ, env_service_jwt, clear=True),
            patch("boto3.client", return_value=fake_r2),
            patch("supabase.create_client", return_value=fake_sb_employee),
            patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(exact_ro_payload)),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_FAIL)

    def test_negative_jwt_claims_and_profiles_role_verification(self):
        valid_anon = _make_jwt({"role": "anon", "exp": 9999999999})
        valid_auth = _make_jwt({"role": "authenticated", "sub": "user-123", "exp": 9999999999})

        # 1) Expired, missing-exp, bool/non-numeric exp, and wrong-role anon JWT -> PermissionError
        bad_anons = [
            _make_jwt({"role": "anon", "exp": 1000}),
            _make_jwt({"role": "anon"}),
            _make_jwt({"role": "anon", "exp": True}),
            _make_jwt({"role": "anon", "exp": "9999999999"}),
            _make_jwt({"role": "authenticated", "exp": 9999999999}),
            _make_jwt({"role": "service_role", "exp": 9999999999}),
        ]
        for bad_anon in bad_anons:
            with self.assertRaises(PermissionError):
                DRY._verify_supabase_jwt_claims(bad_anon, valid_auth)

        # 2) Expired, missing-exp, bool exp, privileged roles, wrong role, missing sub, admin metadata -> PermissionError
        bad_ro_jwts = [
            _make_jwt({"role": "authenticated", "sub": "user-123", "exp": 1000}),
            _make_jwt({"role": "authenticated", "sub": "user-123"}),
            _make_jwt({"role": "authenticated", "sub": "user-123", "exp": True}),
            _make_jwt({"role": "authenticated", "sub": "user-123", "exp": "9999999999"}),
            _make_jwt({"role": "anon", "sub": "user-123", "exp": 9999999999}),
            _make_jwt({"role": "service_role", "sub": "user-123", "exp": 9999999999}),
            _make_jwt({"role": "supabase_admin", "sub": "user-123", "exp": 9999999999}),
            _make_jwt({"role": "postgres", "sub": "user-123", "exp": 9999999999}),
            _make_jwt({"role": "admin", "sub": "user-123", "exp": 9999999999}),
            _make_jwt({"role": "authenticated", "exp": 9999999999}),
            _make_jwt({"role": "authenticated", "sub": "   ", "exp": 9999999999}),
            _make_jwt({"role": "authenticated", "sub": "user-123", "exp": 9999999999, "app_metadata": {"role": "admin"}}),
            _make_jwt({"role": "authenticated", "sub": "user-123", "exp": 9999999999, "user_metadata": {"role": "admin"}}),
            _make_jwt({"role": "authenticated", "sub": "user-123", "exp": 9999999999, "is_admin": True}),
        ]
        for bad_ro in bad_ro_jwts:
            with self.assertRaises(PermissionError):
                DRY._verify_supabase_jwt_claims(valid_anon, bad_ro)

        # 3) DB public.profiles.role checks (never trust JWT alone!)
        syn_pages = [
            ExtractedPage(
                physical_page_number=230,
                text="S.R. 5.13 Duties.",
                lines=(PageLineInfo(text="S.R. 5.13 Duties.", is_bold=True, leading_is_bold=True),),
                printed_page_candidate=210,
                printed_page_status="MARGIN_CANDIDATE",
            ),
        ]
        exact_ro_payload = {
            "success": True,
            "result": {
                "id": "ro_tok_id",
                "status": "active",
                "policies": [
                    {
                        "effect": "allow",
                        "resources": {"com.cloudflare.edge.r2.bucket.acc_mock_default_bucket_mock": "*"},
                        "permission_groups": [{"name": "Workers R2 Storage Read"}],
                    }
                ],
            },
        }
        base_env = {
            "R2_ACCOUNT_ID": "acc_mock",
            "R2_BUCKET_NAME": "bucket_mock",
            "R2_READONLY_ACCESS_KEY_ID": "ro_tok_id",
            "R2_READONLY_SECRET_ACCESS_KEY": "ro_secret_mock",
            "R2_ACCESS_KEY_ID": "rw_tok_id",
            "CLOUDFLARE_TOKEN_INSPECT_API_KEY": "cf_inspect_tok",
            "SUPABASE_URL": "https://mock.supabase.co",
            "SUPABASE_ANON_KEY": valid_anon,
            "SUPABASE_READONLY_JWT": valid_auth,
        }

        # 3a) profiles.role == 'admin' -> FAIL (Exit Code 1)!
        sb_admin_profile = _FakeSupabase(_make_valid_doc(), _make_1309_rows(), profile_row={"id": "user-123", "role": "admin"})
        with (
            patch.dict(os.environ, base_env, clear=True),
            patch("boto3.client", return_value=_FakeR2()),
            patch("supabase.create_client", return_value=sb_admin_profile),
            patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(exact_ro_payload)),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_FAIL)

        # 3b) Server rejects JWT signature (401 / PGRST301) -> FAIL (Exit Code 1)
        sb_bad_sig = _FakeSupabase(_make_valid_doc(), _make_1309_rows(), profile_exc=RuntimeError("PGRST301: JWT invalid signature"))
        with (
            patch.dict(os.environ, base_env, clear=True),
            patch("boto3.client", return_value=_FakeR2()),
            patch("supabase.create_client", return_value=sb_bad_sig),
            patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(exact_ro_payload)),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_FAIL)

        # 3c) Missing profile row, NULL role, or non-JWT RLS/query error -> INCONCLUSIVE -> Exit Code 2 (never 0, never RLS bypass)
        inconclusive_sbs = [
            _FakeSupabase(_make_valid_doc(), _make_1309_rows(), profile_row=None),
            _FakeSupabase(_make_valid_doc(), _make_1309_rows(), profile_row={"id": "user-123", "role": None}),
            _FakeSupabase(_make_valid_doc(), _make_1309_rows(), profile_exc=RuntimeError("42501 permission denied for table profiles")),
        ]
        for sb_inc in inconclusive_sbs:
            with (
                patch.dict(os.environ, base_env, clear=True),
                patch("boto3.client", return_value=_FakeR2()),
                patch("supabase.create_client", return_value=sb_inc),
                patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(exact_ro_payload)),
                patch.object(DRY, "_load_backend_modules", return_value={**MODS, "extract_pdf_pages_detailed": lambda _b, force_ocr=False: (syn_pages, False)}),
            ):
                self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_INCONCLUSIVE)

    def test_negative_r2_policies_scopes_proxies_and_flags(self):
        valid_anon = _make_jwt({"role": "anon", "exp": 9999999999})
        valid_auth = _make_jwt({"role": "authenticated", "sub": "user-123", "exp": 9999999999})
        syn_pages = [
            ExtractedPage(
                physical_page_number=230,
                text="S.R. 5.13 Duties.",
                lines=(PageLineInfo(text="S.R. 5.13 Duties.", is_bold=True, leading_is_bold=True),),
                printed_page_candidate=210,
                printed_page_status="MARGIN_CANDIDATE",
            ),
        ]
        base_env = {
            "R2_ACCOUNT_ID": "acc_mock",
            "R2_BUCKET_NAME": "bucket_mock",
            "R2_READONLY_ACCESS_KEY_ID": "ro_tok_id",
            "R2_READONLY_SECRET_ACCESS_KEY": "ro_secret_mock",
            "R2_ACCESS_KEY_ID": "rw_tok_id",
            "CLOUDFLARE_TOKEN_INSPECT_API_KEY": "cf_inspect_tok",
            "SUPABASE_URL": "https://mock.supabase.co",
            "SUPABASE_ANON_KEY": valid_anon,
            "SUPABASE_READONLY_JWT": valid_auth,
        }
        sb_emp = _FakeSupabase(_make_valid_doc(), _make_1309_rows(), profile_row={"id": "user-123", "role": "employee"})

        # 1) Disabled R2 token & Write permission in main() -> EXIT_FAIL (1)
        fail_payloads = [
            {
                "success": True,
                "result": {
                    "id": "ro_tok_id",
                    "status": "disabled",
                    "policies": [
                        {
                            "effect": "allow",
                            "resources": {"com.cloudflare.edge.r2.bucket.acc_mock_default_bucket_mock": "*"},
                            "permission_groups": [{"name": "Workers R2 Storage Read"}],
                        }
                    ],
                },
            },
            {
                "success": True,
                "result": {
                    "id": "ro_tok_id",
                    "status": "active",
                    "policies": [
                        {
                            "effect": "allow",
                            "resources": {"com.cloudflare.edge.r2.bucket.acc_mock_default_bucket_mock": "*"},
                            "permission_groups": [{"name": "Workers R2 Storage Write"}],
                        }
                    ],
                },
            },
        ]
        for bad_r2_payload in fail_payloads:
            with (
                patch.dict(os.environ, base_env, clear=True),
                patch("boto3.client", return_value=_FakeR2()),
                patch("supabase.create_client", return_value=sb_emp),
                patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(bad_r2_payload)),
            ):
                self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_FAIL)

        # Reusing CLOUDFLARE_TOKEN_INSPECT_API_KEY as R2_READONLY_ACCESS_KEY_ID -> EXIT_FAIL (1)
        env_same_inspect = {**base_env, "R2_READONLY_ACCESS_KEY_ID": "cf_inspect_tok"}
        with (
            patch.dict(os.environ, env_same_inspect, clear=True),
            patch("boto3.client", return_value=_FakeR2()),
            patch("supabase.create_client", return_value=sb_emp),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_FAIL)

        # 2) Wildcard, account-wide, wrong bucket, missing resources -> NEVER PASS -> EXIT_INCONCLUSIVE (2)
        inconclusive_r2_payloads = [
            {
                "success": True,
                "result": {
                    "id": "ro_tok_id",
                    "status": "active",
                    "policies": [
                        {
                            "effect": "allow",
                            "resources": {"com.cloudflare.edge.r2.bucket.*": "*"},
                            "permission_groups": [{"name": "Workers R2 Storage Read"}],
                        }
                    ],
                },
            },
            {
                "success": True,
                "result": {
                    "id": "ro_tok_id",
                    "status": "active",
                    "policies": [
                        {
                            "effect": "allow",
                            "resources": {"com.cloudflare.api.account.acc_mock": "*"},
                            "permission_groups": [{"name": "Workers R2 Storage Read"}],
                        }
                    ],
                },
            },
            {
                "success": True,
                "result": {
                    "id": "ro_tok_id",
                    "status": "active",
                    "policies": [
                        {
                            "effect": "allow",
                            "resources": {"com.cloudflare.edge.r2.bucket.acc_mock_default_other_bucket": "*"},
                            "permission_groups": [{"name": "Workers R2 Storage Read"}],
                        }
                    ],
                },
            },
            {
                "success": True,
                "result": {
                    "id": "ro_tok_id",
                    "status": "active",
                    "policies": [
                        {
                            "effect": "allow",
                            "permission_groups": [{"name": "Workers R2 Storage Read"}],
                        }
                    ],
                },
            },
        ]
        for inc_payload in inconclusive_r2_payloads:
            with (
                patch.dict(os.environ, base_env, clear=True),
                patch("boto3.client", return_value=_FakeR2()),
                patch("supabase.create_client", return_value=sb_emp),
                patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(inc_payload)),
                patch.object(DRY, "_load_backend_modules", return_value={**MODS, "extract_pdf_pages_detailed": lambda _b, force_ocr=False: (syn_pages, False)}),
            ):
                self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_INCONCLUSIVE)

        # User API Token / HTTP 404 from Cloudflare Account Token Inspect -> EXIT_INCONCLUSIVE (2)
        http_404 = urllib.error.HTTPError("https://api.cloudflare.com", 404, "Not Found", {}, None)
        with (
            patch.dict(os.environ, base_env, clear=True),
            patch("boto3.client", return_value=_FakeR2()),
            patch("supabase.create_client", return_value=sb_emp),
            patch("urllib.request.urlopen", side_effect=http_404),
            patch.object(DRY, "_load_backend_modules", return_value={**MODS, "extract_pdf_pages_detailed": lambda _b, force_ocr=False: (syn_pages, False)}),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR)]), DRY.EXIT_INCONCLUSIVE)

        # 3) --allow-app-r2-env and --allow-service-role-db fallback flags -> EXIT_INCONCLUSIVE (2)
        env_no_ro_r2 = {k: v for k, v in base_env.items() if not k.startswith("R2_READONLY_")}
        env_no_ro_r2["R2_SECRET_ACCESS_KEY"] = "rw_secret"
        with (
            patch.dict(os.environ, env_no_ro_r2, clear=True),
            patch("supabase.create_client", return_value=sb_emp),
            patch.object(DRY, "_load_backend_modules", return_value={**MODS, "get_r2_client": lambda: _FakeR2(), "extract_pdf_pages_detailed": lambda _b, force_ocr=False: (syn_pages, False)}),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR), "--allow-app-r2-env"]), DRY.EXIT_INCONCLUSIVE)

        env_no_ro_db = {k: v for k, v in base_env.items() if k not in {"SUPABASE_ANON_KEY", "SUPABASE_READONLY_JWT"}}
        env_no_ro_db["SUPABASE_SERVICE_ROLE_KEY"] = "sr_secret"
        exact_ro_payload = {
            "success": True,
            "result": {
                "id": "ro_tok_id",
                "status": "active",
                "policies": [
                    {
                        "effect": "allow",
                        "resources": {"com.cloudflare.edge.r2.bucket.acc_mock_default_bucket_mock": "*"},
                        "permission_groups": [{"name": "Workers R2 Storage Read"}],
                    }
                ],
            },
        }
        with (
            patch.dict(os.environ, env_no_ro_db, clear=True),
            patch("boto3.client", return_value=_FakeR2()),
            patch("urllib.request.urlopen", return_value=_FakeUrlopenResp(exact_ro_payload)),
            patch.object(DRY, "_load_backend_modules", return_value={**MODS, "get_supabase": lambda: sb_emp, "extract_pdf_pages_detailed": lambda _b, force_ocr=False: (syn_pages, False)}),
        ):
            self.assertEqual(DRY.main(["--backend-dir", str(BACKEND_DIR), "--allow-service-role-db"]), DRY.EXIT_INCONCLUSIVE)

        # 4) Read-Only Proxies block ALL mutating/unauthorized methods
        r2_proxy = DRY._ReadOnlyR2Proxy(_FakeR2())
        with self.assertRaises(PermissionError):
            r2_proxy.put_object(Bucket="b", Key="k", Body=b"x")
        with self.assertRaises(PermissionError):
            r2_proxy.delete_object(Bucket="b", Key="k")
        with self.assertRaises(PermissionError):
            r2_proxy.copy_object(Bucket="b", Key="k", CopySource="b/k")

        sb_proxy = DRY._ReadOnlySupabaseProxy(sb_emp)
        with self.assertRaises(PermissionError):
            sb_proxy.table("profiles")
        with self.assertRaises(PermissionError):
            sb_proxy.rpc("search_railway_rules", {})
        for tbl_op in ("insert", "update", "delete", "upsert"):
            with self.assertRaises(PermissionError):
                getattr(sb_proxy.table("documents"), tbl_op)({"id": 2})
            with self.assertRaises(PermissionError):
                getattr(sb_proxy.table("rule_chunks").select("id"), tbl_op)({"id": 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
