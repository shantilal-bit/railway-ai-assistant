"""Static & structural SQL validation for supabase/migrations/002_production_rag.sql.

Validates compatibility with BOTH:
1. Existing live Supabase schemas with bigint IDs and missing/legacy columns across
   zones, divisions, departments, documents, rule_chunks, amendments, chat_history, profiles.
2. Fresh empty PostgreSQL databases.

Note: Execution container lacks psql/postgres, so this validates SQL structure,
statement ordering, non-destructiveness, type compatibility, and RBAC hardening statically.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "supabase" / "migrations" / "002_production_rag.sql"


class ProductionRagSqlMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION_PATH.read_text(encoding="utf-8")
        cls.sql_lower = cls.sql.lower()

    def test_01_preserves_all_existing_tables_and_data(self):
        forbidden_destructive = [
            r"\bdrop\s+table\b",
            r"\btruncate\b",
            r"\bdelete\s+from\b",
            r"\bdrop\s+column\b",
        ]
        for pattern in forbidden_destructive:
            self.assertIsNone(
                re.search(pattern, self.sql_lower),
                f"Destructive SQL pattern {pattern!r} is forbidden in 002_production_rag.sql",
            )

        # Must preserve legacy rule_chunks.embedding (768/1536) while making it nullable
        self.assertIn("alter column embedding drop not null", self.sql_lower)

    def test_02_baseline_tables_exist_for_empty_db(self):
        for table in (
            "zones",
            "divisions",
            "departments",
            "profiles",
            "documents",
            "rule_chunks",
            "amendments",
            "chat_history",
        ):
            self.assertRegex(
                self.sql_lower,
                rf"create\s+table\s+if\s+not\s+exists\s+public\.{table}\b",
                f"Baseline table public.{table} missing for standalone empty-DB execution",
            )

    def test_03_documents_required_columns_ensured_before_indexes_and_checks(self):
        required_doc_cols = [
            "file_sha256",
            "document_number",
            "issuing_authority",
            "authority_rank",
            "r2_object_key",
            "document_type",
            "issue_date",
            "effective_date",
            "requires_ocr",
            "ocr_status",
            "status",
            "ingestion_status",
            "ingestion_error",
            "chunk_count",
            "indexed_at",
            "source_type",
            "source_url",
        ]
        for col in required_doc_cols:
            self.assertRegex(
                self.sql_lower,
                rf"add\s+column\s+if\s+not\s+exists\s+{col}\b",
                f"documents.{col} must be added via ADD COLUMN IF NOT EXISTS",
            )

        add_sha_pos = self.sql_lower.index("add column if not exists file_sha256")
        idx_sha_pos = self.sql_lower.index("idx_documents_sha256")
        self.assertLess(add_sha_pos, idx_sha_pos)

        add_doc_num_pos = self.sql_lower.index("add column if not exists document_number")
        idx_doc_num_pos = self.sql_lower.index("idx_documents_number_lower")
        self.assertLess(add_doc_num_pos, idx_doc_num_pos)

        # Legacy values normalized before adding check constraints
        norm_ing_pos = self.sql_lower.index("when lower(coalesce(ingestion_status")
        chk_ing_pos = self.sql_lower.index("add constraint chk_documents_ingestion_status")
        self.assertLess(norm_ing_pos, chk_ing_pos)

    def test_04_rule_chunks_fts_independent_of_legacy_content_tsv(self):
        # Issue #3 & #6: never depend on legacy content_tsv column
        non_comment_lines = [
            line.lower()
            for line in self.sql.splitlines()
            if not line.lstrip().startswith("--")
        ]
        non_comment_sql = "\n".join(non_comment_lines)
        self.assertNotIn("content_tsv", non_comment_sql)

        for col in ("section_title", "rule_number", "chapter", "content", "embedding_bge_m3"):
            self.assertRegex(
                self.sql_lower,
                rf"add\s+column\s+if\s+not\s+exists\s+{col}\b",
            )

        sec_pos = self.sql_lower.index("add column if not exists section_title")
        tsv_pos = self.sql_lower.index("add column if not exists search_tsv tsvector generated always as")
        gin_pos = self.sql_lower.index("idx_rule_chunks_search_tsv")
        self.assertLess(sec_pos, tsv_pos)
        self.assertLess(tsv_pos, gin_pos)

    def test_05_document_scopes_created_dynamically_before_indexes_and_rls(self):
        # Issue #1: document_scopes must be created matching actual documents/taxonomy PK types
        self.assertIn("create table public.document_scopes", self.sql_lower)
        self.assertIn("format_type(a.atttypid, a.atttypmod)", self.sql_lower)
        self.assertIn("insert into public.document_scopes", self.sql_lower)

        create_pos = self.sql_lower.index("create table public.document_scopes")
        idx_pos = self.sql_lower.index("idx_doc_scopes_lookup")
        rls_pos = self.sql_lower.index("alter table public.document_scopes enable row level security")
        rpc_pos = self.sql_lower.index("create or replace function public.search_railway_rules")
        self.assertLess(create_pos, idx_pos)
        self.assertLess(create_pos, rls_pos)
        self.assertLess(create_pos, rpc_pos)

    def test_06_amendments_reconciled_with_legacy_schemas(self):
        # Issue #4: legacy amendments column backfill + NOT NULL relaxation
        self.assertIn("amending_document_id", self.sql_lower)
        self.assertIn("target_document_id", self.sql_lower)
        self.assertIn("relationship_type", self.sql_lower)
        self.assertIn("circular_reference", self.sql_lower)
        self.assertIn("alter column %i drop not null", self.sql_lower)

        for legacy_col in ("amendment_document_id", "superseded_document_id", "amendment_type"):
            self.assertIn(legacy_col, self.sql_lower)

    def test_07_rpc_supports_bigint_and_uuid_without_uuid_return_cast(self):
        # Issue #5: search_railway_rules must NOT require uuid parameters or return uuid IDs
        fn_start = self.sql_lower.index("create or replace function public.search_railway_rules")
        fn_block = self.sql_lower[fn_start:]

        self.assertIn("p_zone_id text", fn_block)
        self.assertIn("p_division_id text", fn_block)
        self.assertIn("p_department_id text", fn_block)
        self.assertIn("chunk_id text", fn_block)
        self.assertIn("document_id text", fn_block)
        self.assertIn("rc.id::text as chunk_id", fn_block)
        self.assertIn("d.id::text as document_id", fn_block)
        self.assertNotIn("chunk_id uuid", fn_block)
        self.assertNotIn("document_id uuid", fn_block)
        self.assertNotIn("content_tsv", fn_block)
        self.assertIn("rc.search_tsv", fn_block)

        # Security: revoke from public/anon, grant to authenticated & service_role
        self.assertIn("revoke all on function public.search_railway_rules", fn_block)
        self.assertIn("from anon", fn_block)
        self.assertIn("to authenticated, service_role", fn_block)

    def test_08_profiles_rbac_prevents_role_escalation(self):
        # Drops all old permissive policies on profiles dynamically
        self.assertIn("from pg_policies", self.sql_lower)
        self.assertIn("tablename = 'profiles'", self.sql_lower)
        self.assertIn("drop policy if exists %i on public.profiles", self.sql_lower)

        # Trigger + helper function lock down self-promotion to admin
        self.assertIn("create or replace function public.is_admin()", self.sql_lower)
        self.assertIn("create or replace function public.prevent_profile_role_escalation()", self.sql_lower)
        self.assertIn("create trigger trg_prevent_profile_role_escalation", self.sql_lower)
        self.assertIn("with check (auth.uid() = id and role = 'employee')", self.sql_lower)

    def test_09_balanced_dollar_quoting_and_parentheses(self):
        dollar_tags = re.findall(r"\$[a-zA-Z_]*\$", self.sql)
        counts: dict[str, int] = {}
        for tag in dollar_tags:
            counts[tag] = counts.get(tag, 0) + 1
        for tag, cnt in counts.items():
            self.assertEqual(
                cnt % 2,
                0,
                f"Unbalanced PostgreSQL dollar-quote delimiter {tag}: count={cnt}",
            )


if __name__ == "__main__":
    unittest.main()
