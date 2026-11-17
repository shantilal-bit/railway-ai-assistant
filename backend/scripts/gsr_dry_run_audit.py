#!/usr/bin/env python3
"""
Standalone READ-ONLY Dry-Run Audit Script for Real G&SR PDF Extraction & Chunking.

Safety & Verification Guarantees:
- Strictly READ-ONLY: zero writes/uploads/deletes to R2, Supabase, disk, or embeddings/LLM APIs.
- Uses only verified Supabase schema columns (document_number, document_type, etc.).
- Strict exact r2_object_key validation (NULL/empty or mismatch -> FAIL).
- Real credential verification: decodes & validates JWT exp/role/admin claims locally, verifies real DB
  public.profiles.role == 'employee' via Supabase server (signature & RLS enforced server-side),
  and inspects dedicated Cloudflare Account R2 token policy + exact bucket resource scope.
- Honest tri-state audits with explicit exit codes:
    EXIT_PASS = 0
    EXIT_FAIL = 1
    EXIT_INCONCLUSIVE = 2 (never returns 0 on any INCONCLUSIVE gate!)
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import base64
import difflib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_INCONCLUSIVE = 2

TARGET_DOCUMENT_ID = 1
TARGET_R2_OBJECT_KEY = "wr/bct/engg/G___SR_corrected_with_CS-108.pdf"
EXPECTED_OLD_DB_CHUNKS = 1309
DEFAULT_FOCUS_START_PAGE = 230
DEFAULT_FOCUS_END_PAGE = 245
TARGET_SR_FOCUS_NUM = "5.13"

_SECRET_ENV_KEYS = (
    "R2_READONLY_ACCESS_KEY_ID",
    "R2_READONLY_SECRET_ACCESS_KEY",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_TOKEN_INSPECT_API_KEY",
    "CLOUDFLARE_API_TOKEN",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_READONLY_JWT",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
)

_S3_SENSITIVE_PARAM_RE = re.compile(
    r"(AWSAccessKeyId|Signature|X-Amz-Credential|X-Amz-Signature|X-Amz-Security-Token)=[^&\s'\"]+",
    re.IGNORECASE,
)
_GLUED_LOWER_SUFFIX_RE = re.compile(r"(?:\d|\))[a-z]{2,}$")


def _resolve_backend_dir(cli_backend_dir: str | None) -> Path:
    """Resolves the backend directory containing app/{main,pdf_pipeline,rag_service}.py."""
    required_rel = (
        Path("app/main.py"),
        Path("app/pdf_pipeline.py"),
        Path("app/rag_service.py"),
    )

    def _is_valid_backend(candidate: Path) -> bool:
        return candidate.is_dir() and all((candidate / rel).is_file() for rel in required_rel)

    if cli_backend_dir:
        explicit = Path(cli_backend_dir).expanduser().resolve()
        if not _is_valid_backend(explicit):
            raise RuntimeError(
                f"Invalid --backend-dir '{explicit}': expected app/main.py, "
                "app/pdf_pipeline.py, and app/rag_service.py."
            )
        return explicit

    env_dir = (os.getenv("BACKEND_DIR") or "").strip()
    if env_dir:
        explicit_env = Path(env_dir).expanduser().resolve()
        if not _is_valid_backend(explicit_env):
            raise RuntimeError(
                f"Invalid BACKEND_DIR '{explicit_env}': expected app/*.py modules."
            )
        return explicit_env

    anchor_roots: list[Path] = [Path.cwd().resolve()]
    if "__file__" in globals():
        anchor_roots.append(Path(__file__).resolve().parent)

    seen: set[Path] = set()
    candidates: list[Path] = []
    for base in anchor_roots:
        for ancestor in (base, *base.parents):
            for probe in (ancestor, ancestor / "backend"):
                resolved = probe.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    candidates.append(resolved)

    matched = [cand for cand in candidates if _is_valid_backend(cand)]
    if matched:
        return matched[0]

    raise RuntimeError(
        "Could not resolve backend directory. Pass --backend-dir /path/to/repo/backend "
        "or set BACKEND_DIR."
    )


def _load_backend_modules(backend_dir: Path) -> dict[str, Any]:
    backend_str = str(backend_dir)
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)

    from app.main import get_r2_client, get_supabase
    from app.pdf_pipeline import (
        CHAPTER_HEADER_PATTERN,
        KNOWN_FALSE_POSITIVE_RULE_WORDS,
        ExtractedChunk,
        ExtractedPage,
        _detect_repeated_margin_signatures,
        _margin_signature,
        _merge_vertical_split_rule_lines,
        _normalize_page_text,
        _parse_rule_heading_line,
        chunk_pages_with_metadata,
        download_pdf_from_r2,
        extract_pdf_pages_detailed,
        validate_rule_label,
    )
    from app.rag_service import sanitize_error_message

    return {
        "get_r2_client": get_r2_client,
        "get_supabase": get_supabase,
        "sanitize_error_message": sanitize_error_message,
        "CHAPTER_HEADER_PATTERN": CHAPTER_HEADER_PATTERN,
        "KNOWN_FALSE_POSITIVE_RULE_WORDS": frozenset(KNOWN_FALSE_POSITIVE_RULE_WORDS),
        "ExtractedChunk": ExtractedChunk,
        "ExtractedPage": ExtractedPage,
        "_detect_repeated_margin_signatures": _detect_repeated_margin_signatures,
        "_margin_signature": _margin_signature,
        "_merge_vertical_split_rule_lines": _merge_vertical_split_rule_lines,
        "_normalize_page_text": _normalize_page_text,
        "_parse_rule_heading_line": _parse_rule_heading_line,
        "chunk_pages_with_metadata": chunk_pages_with_metadata,
        "download_pdf_from_r2": download_pdf_from_r2,
        "extract_pdf_pages_detailed": extract_pdf_pages_detailed,
        "validate_rule_label": validate_rule_label,
    }


def _safe_format_exception(exc: Exception, sanitize_fn: Any | None = None) -> str:
    """Formats exceptions without leaking secrets or throwing from sanitization."""
    msg = ""
    if sanitize_fn is not None:
        try:
            msg = str(sanitize_fn(exc) or "")
        except Exception:
            msg = ""
    if not msg:
        try:
            msg = f"{exc.__class__.__name__}: {exc}".strip()
        except Exception:
            msg = exc.__class__.__name__

    msg = _S3_SENSITIVE_PARAM_RE.sub(r"\1=[REDACTED]", msg)
    for env_key in _SECRET_ENV_KEYS:
        secret_val = (os.getenv(env_key) or "").strip()
        if len(secret_val) >= 6 and secret_val in msg:
            msg = msg.replace(secret_val, f"[REDACTED:{env_key}]")
    return msg[:500]


class _ReadOnlyR2Proxy:
    """Script-level R2 guardrail: blocks every boto3 method except get_object."""

    def __init__(self, inner_client: Any) -> None:
        self._inner = inner_client

    def get_object(self, **kwargs: Any) -> Any:
        return self._inner.get_object(**kwargs)

    def __getattr__(self, name: str) -> Any:
        raise PermissionError(
            f"READ-ONLY VIOLATION (Script-Level): R2 method '{name}' is blocked. Only get_object is allowed."
        )


class _ReadOnlyQueryBuilderProxy:
    """Script-level Supabase query guardrail: allows strictly read-only SELECT chain."""

    _ALLOWED_READ_METHODS = frozenset(
        {
            "select",
            "eq",
            "neq",
            "gt",
            "gte",
            "lt",
            "lte",
            "in_",
            "is_",
            "order",
            "range",
            "limit",
            "single",
            "maybe_single",
            "execute",
        }
    )

    def __init__(self, query_builder: Any) -> None:
        self._qb = query_builder

    def __getattr__(self, name: str) -> Any:
        if name not in self._ALLOWED_READ_METHODS:
            raise PermissionError(
                f"READ-ONLY VIOLATION (Script-Level): Query method '{name}' is blocked."
            )
        target = getattr(self._qb, name)
        if name == "execute":
            return target

        def _chained(*args: Any, **kwargs: Any) -> _ReadOnlyQueryBuilderProxy:
            return _ReadOnlyQueryBuilderProxy(target(*args, **kwargs))

        return _chained


class _ReadOnlyTableProxy:
    def __init__(self, table_builder: Any) -> None:
        self._tb = table_builder

    def select(self, *args: Any, **kwargs: Any) -> _ReadOnlyQueryBuilderProxy:
        return _ReadOnlyQueryBuilderProxy(self._tb.select(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        raise PermissionError(
            f"READ-ONLY VIOLATION (Script-Level): Table write/mutation method '{name}' is blocked."
        )


class _ReadOnlySupabaseProxy:
    """Script-level Supabase client guardrail: permits table(...).select(...) on documents/rule_chunks only."""

    def __init__(self, inner_client: Any) -> None:
        self._inner = inner_client

    def table(self, table_name: str) -> _ReadOnlyTableProxy:
        if table_name not in {"documents", "rule_chunks"}:
            raise PermissionError(
                f"READ-ONLY VIOLATION (Script-Level): Access to table '{table_name}' is blocked."
            )
        return _ReadOnlyTableProxy(self._inner.table(table_name))

    def __getattr__(self, name: str) -> Any:
        raise PermissionError(
            f"READ-ONLY VIOLATION (Script-Level): Supabase client method '{name}' is blocked."
        )


def _decode_jwt_claims_unverified(token: str) -> dict[str, Any]:
    """
    Decodes Base64url JWT payload claims locally WITHOUT verifying cryptographic signature.
    Cryptographic signature and server-side expiry MUST still be validated by Supabase PostgREST.
    """
    parts = (token or "").strip().split(".")
    if len(parts) != 3 or not parts[1]:
        raise PermissionError("Malformed JWT token: expected 3 dot-separated segments.")
    payload_b64 = parts[1] + ("=" * ((4 - len(parts[1]) % 4) % 4))
    try:
        raw_bytes = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        claims = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise PermissionError(f"Unable to decode JWT payload claims: {exc.__class__.__name__}") from exc
    if not isinstance(claims, dict):
        raise PermissionError("JWT payload claims must be a JSON object.")
    return claims


def _require_valid_jwt_exp(claims: dict[str, Any], label: str, now_ts: int) -> int | float:
    """Requires a present, numeric (non-bool), un-expired 'exp' claim."""
    exp = claims.get("exp")
    if exp is None:
        raise PermissionError(f"Credential security violation: {label} JWT is missing required 'exp' claim.")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        raise PermissionError(f"Credential security violation: {label} JWT 'exp' claim must be numeric (got {type(exp).__name__}).")
    if exp <= now_ts:
        raise PermissionError(f"{label} JWT is expired.")
    return exp


def _verify_supabase_jwt_claims(anon_key: str, readonly_jwt: str) -> dict[str, Any]:
    """
    Verifies local JWT payload claims (mandatory exp, role, sub, and absence of admin claims)
    for SUPABASE_ANON_KEY and SUPABASE_READONLY_JWT.
    NOTE: Signature is NOT verified locally; Supabase server verifies cryptographic signature & exp.
    """
    privileged_roles = {"service_role", "supabase_admin", "postgres", "admin"}
    now_ts = int(time.time())

    anon_claims = _decode_jwt_claims_unverified(anon_key)
    anon_role = str(anon_claims.get("role") or "").strip().lower()
    if anon_role != "anon":
        raise PermissionError(
            f"Credential security violation: SUPABASE_ANON_KEY JWT role must be 'anon', got '{anon_role or 'missing'}'."
        )
    _require_valid_jwt_exp(anon_claims, "SUPABASE_ANON_KEY", now_ts)

    ro_claims = _decode_jwt_claims_unverified(readonly_jwt)
    ro_role = str(ro_claims.get("role") or "").strip().lower()
    if ro_role in privileged_roles:
        raise PermissionError(
            f"Credential security violation: refusing privileged role '{ro_role}' in SUPABASE_READONLY_JWT."
        )
    if ro_role != "authenticated":
        raise PermissionError(
            f"Credential security violation: SUPABASE_READONLY_JWT role must be 'authenticated', got '{ro_role or 'missing'}'."
        )
    raw_sub = ro_claims.get("sub")
    if not isinstance(raw_sub, str) or not raw_sub.strip():
        raise PermissionError("SUPABASE_READONLY_JWT is missing non-empty string 'sub' claim.")
    ro_sub = raw_sub.strip()

    app_meta = ro_claims.get("app_metadata")
    user_meta = ro_claims.get("user_metadata")
    if isinstance(app_meta, dict) and str(app_meta.get("role") or "").strip().lower() in privileged_roles:
        raise PermissionError("Credential security violation: app_metadata indicates privileged/admin role.")
    if isinstance(user_meta, dict) and str(user_meta.get("role") or "").strip().lower() in privileged_roles:
        raise PermissionError("Credential security violation: user_metadata indicates privileged/admin role.")
    if ro_claims.get("is_admin") is True:
        raise PermissionError("Credential security violation: JWT claim is_admin=True.")

    _require_valid_jwt_exp(ro_claims, "SUPABASE_READONLY_JWT", now_ts)

    return {
        "anon_role": anon_role,
        "readonly_role": ro_role,
        "sub": ro_sub,
        "sub_present": True,
        "signature_verified_locally": False,
        "claim_status": "PASS",
    }


def _is_supabase_jwt_auth_error(exc: Exception) -> bool:
    """Detects server-side JWT signature/expiry rejection vs RLS or connectivity issues."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        return True
    err_code = str(getattr(exc, "code", "") or "").upper()
    if err_code in {"PGRST301", "PGRST302", "PGRST303"}:
        return True
    msg = f"{exc.__class__.__name__}: {exc}".lower()
    jwt_markers = (
        "401",
        "pgrst301",
        "pgrst302",
        "pgrst303",
        "jwserror",
        "jwt",
        "invalid signature",
        "signature verification",
        "token is expired",
        "invalid claim",
        "bad_jwt",
    )
    return any(marker in msg for marker in jwt_markers)


def _verify_supabase_profile_role_is_employee(
    raw_client: Any,
    expected_sub: str,
) -> tuple[str, str]:
    """
    Verifies real DB public.profiles.role == 'employee' using the authenticated user's own
    client (strictly SELECT via _ReadOnlyTableProxy, NEVER bypassing RLS).
    - Server-side JWT signature/expiry rejection -> PermissionError (EXIT_FAIL=1).
    - Admin or any non-employee DB role -> PermissionError (EXIT_FAIL=1).
    - Missing row / NULL role / RLS denial / query error -> INCONCLUSIVE (EXIT_INCONCLUSIVE=2).
    """
    try:
        prof_resp = (
            _ReadOnlyTableProxy(raw_client.table("profiles"))
            .select("id,role")
            .eq("id", expected_sub)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        if _is_supabase_jwt_auth_error(exc):
            raise PermissionError(
                f"Credential security violation: Supabase server rejected JWT signature/expiry during profiles check ({exc.__class__.__name__})."
            ) from exc
        return (
            "INCONCLUSIVE",
            f"Could not verify public.profiles.role safely via authenticated RLS SELECT ({exc.__class__.__name__}); "
            "refusing RLS bypass.",
        )

    profile_row = getattr(prof_resp, "data", None)
    if not isinstance(profile_row, dict):
        return (
            "INCONCLUSIVE",
            "Authenticated user's public.profiles row is missing or unreadable under current RLS; "
            "cannot confirm non-admin DB role without bypassing RLS.",
        )

    row_id = profile_row.get("id")
    if row_id is not None and str(row_id).strip() != expected_sub:
        return (
            "INCONCLUSIVE",
            "public.profiles.id mismatch against JWT sub; cannot safely trust profile role.",
        )

    raw_role = profile_row.get("role")
    db_role = raw_role.strip().lower() if isinstance(raw_role, str) else ""
    if not db_role:
        return (
            "INCONCLUSIVE",
            "Authenticated user's public.profiles.role is NULL or empty; expected 'employee'.",
        )
    if db_role != "employee":
        raise PermissionError(
            f"Credential security violation: DB public.profiles.role is '{db_role}' (expected 'employee'; admin/non-employee profiles are refused)."
        )

    return (
        "PASS",
        "Supabase server verified JWT signature/exp AND DB public.profiles.role=='employee' via authenticated RLS SELECT.",
    )


def _classify_r2_policy_resources(
    resources: Any,
    account_id: str,
    bucket_name: str,
) -> tuple[bool, list[str]]:
    """
    Checks whether Cloudflare token policy `resources` strictly scopes access to the exact target R2 bucket:
      com.cloudflare.edge.r2.bucket.<account_id>_<jurisdiction>_<bucket_name>
    Rejects (as non-exact / INCONCLUSIVE) missing resources, wildcards (*), account-wide keys,
    or mismatched account/bucket names.
    """
    if not account_id or not bucket_name:
        return False, ["missing_target_account_or_bucket_name"]
    if not isinstance(resources, dict) or not resources:
        return False, ["missing_or_empty_resources"]

    exact_bucket_re = re.compile(
        rf"^com\.cloudflare\.edge\.r2\.bucket\.{re.escape(account_id)}_(?P<jurisdiction>[A-Za-z0-9-]+)_{re.escape(bucket_name)}$"
    )

    reasons: list[str] = []
    exact_count = 0
    for res_key, res_val in resources.items():
        key_str = str(res_key or "").strip()
        val_str = str(res_val or "").strip() if isinstance(res_val, str) else ""
        if not key_str or not val_str:
            reasons.append("empty_resource_entry")
            continue
        if "*" in key_str:
            reasons.append(f"wildcard_resource:{key_str}")
            continue
        if key_str.startswith("com.cloudflare.api.account."):
            reasons.append(f"account_wide_resource:{key_str}")
            continue
        if not exact_bucket_re.match(key_str):
            if key_str.startswith("com.cloudflare.edge.r2.bucket."):
                reasons.append(f"wrong_bucket_or_account:{key_str}")
            else:
                reasons.append(f"unrecognized_resource:{key_str}")
            continue
        exact_count += 1

    if reasons:
        return False, reasons
    if exact_count < 1:
        return False, ["no_exact_bucket_resource"]
    return True, []


def _verify_r2_readonly_permission(
    account_id: str,
    ro_access_key_id: str,
    app_access_key_id: str | None,
    bucket_name: str = "",
) -> tuple[str, str]:
    """
    Verifies Cloudflare Account R2 token policy & exact bucket scope WITHOUT any write/delete probe.
    - Note: Per Cloudflare docs, R2 S3 Access Key ID == Cloudflare Token ID, while S3 Secret Access Key
      is the SHA-256 hash of the token secret. `/accounts/{account_id}/tokens/{token_id}` inspects
      ONLY Account-Owned API Tokens (User API Tokens return 404 -> INCONCLUSIVE) using a separate
      CLOUDFLARE_TOKEN_INSPECT_API_KEY credential.
    - Fails immediately (PermissionError -> Exit 1) on RW key reuse, disabled/non-active token,
      or any Write/Edit/Delete/Admin/Manage permission group.
    - Returns INCONCLUSIVE (-> Exit 2) whenever exact bucket-level Read-Only proof cannot be established:
      missing inspect token, API errors/404 User Token, missing/wildcard/account-wide/wrong bucket
      resources, or missing explicit R2 Read permission group.
    """
    if app_access_key_id and ro_access_key_id == app_access_key_id:
        raise PermissionError(
            "Credential security violation: R2_READONLY_ACCESS_KEY_ID is identical to R2_ACCESS_KEY_ID (RW key)."
        )

    inspect_token = (os.getenv("CLOUDFLARE_TOKEN_INSPECT_API_KEY") or "").strip()
    ro_secret = (os.getenv("R2_READONLY_SECRET_ACCESS_KEY") or "").strip()
    if inspect_token and (ro_access_key_id == inspect_token or (ro_secret and ro_secret == inspect_token)):
        raise PermissionError(
            "Credential security violation: CLOUDFLARE_TOKEN_INSPECT_API_KEY must be distinct from R2 Read-Only S3 credentials."
        )
    if not inspect_token:
        return (
            "INCONCLUSIVE",
            "R2 S3 Read-Only key ID/secret alone cannot prove write-denial non-destructively; "
            "separate CLOUDFLARE_TOKEN_INSPECT_API_KEY is unset.",
        )

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/{ro_access_key_id}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {inspect_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return (
                "INCONCLUSIVE",
                "Cloudflare Account Token Inspect API returned HTTP 404 (key may be a User API Token or outside "
                "this account; cannot verify policy without write probe).",
            )
        return (
            "INCONCLUSIVE",
            f"Cloudflare Account Token Inspect API returned HTTP {exc.code}; R2 permission could not be verified.",
        )
    except Exception as exc:
        return (
            "INCONCLUSIVE",
            f"Cloudflare Account Token Inspect API verification unavailable ({exc.__class__.__name__}); "
            "marking R2 credential security INCONCLUSIVE.",
        )

    if not isinstance(payload, dict) or not payload.get("success") or not isinstance(payload.get("result"), dict):
        return (
            "INCONCLUSIVE",
            "Cloudflare token inspect response did not return verified Account Token policies.",
        )

    token_info = payload["result"]
    returned_id = token_info.get("id")
    if returned_id is not None and str(returned_id).strip() != ro_access_key_id:
        return (
            "INCONCLUSIVE",
            "Cloudflare token inspect returned mismatched token ID for R2_READONLY_ACCESS_KEY_ID.",
        )

    status = str(token_info.get("status") or "").strip().lower()
    if status != "active":
        raise PermissionError(
            f"R2 credential security failure: Cloudflare token status is '{status or 'unknown'}' (expected 'active')."
        )

    policies = token_info.get("policies") or []
    exact_read_groups: list[str] = []
    forbidden_groups: list[str] = []
    scope_issues: list[str] = []
    saw_read_group_without_exact_scope = False

    for pol in policies:
        if not isinstance(pol, dict):
            continue
        effect = str(pol.get("effect") or "allow").strip().lower()
        if effect == "deny":
            continue
        if effect != "allow":
            scope_issues.append(f"unexpected_policy_effect:{effect}")
            continue

        pol_read_groups: list[str] = []
        for pg in pol.get("permission_groups") or []:
            name = str(pg.get("name") or "").strip() if isinstance(pg, dict) else str(pg).strip()
            low = name.lower()
            if any(w in low for w in ("write", "edit", "delete", "admin", "manage")):
                forbidden_groups.append(name)
            elif "r2" in low and "read" in low:
                pol_read_groups.append(name)

        res_exact, res_reasons = _classify_r2_policy_resources(pol.get("resources"), account_id, bucket_name)
        if not res_exact:
            scope_issues.extend(res_reasons)
            if pol_read_groups:
                saw_read_group_without_exact_scope = True
        elif pol_read_groups:
            exact_read_groups.extend(pol_read_groups)

    if forbidden_groups:
        raise PermissionError(
            f"R2 credential security violation: token has write/mutating permission groups {forbidden_groups}!"
        )
    if saw_read_group_without_exact_scope or scope_issues:
        return (
            "INCONCLUSIVE",
            "Cloudflare token policy lacks exact target bucket resource scope "
            f"(issues={sorted(set(scope_issues))}); never trusting permission group name alone.",
        )
    if not exact_read_groups:
        return (
            "INCONCLUSIVE",
            "Cloudflare Account Token Inspect found no write groups, but could not confirm an explicit R2 Read group "
            "scoped to the exact target bucket.",
        )

    return (
        "PASS",
        f"Verified active Account R2 Token ({', '.join(exact_read_groups)}) with exact bucket resource scope "
        f"for '{bucket_name}' and zero Write/Edit/Delete/Admin/Manage groups "
        "(inspected via separate CLOUDFLARE_TOKEN_INSPECT_API_KEY; S3 secret binding exercised read-only via get_object).",
    )


def _create_read_only_r2_client(
    mods: dict[str, Any],
    allow_app_r2_env: bool,
) -> tuple[Any, str, dict[str, str]]:
    """Builds R2 client with script-level proxy + honest credential-level verification status."""
    import boto3

    account_id = (os.getenv("R2_ACCOUNT_ID") or os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    bucket_name = (os.getenv("R2_BUCKET_NAME") or "").strip()
    if not account_id:
        raise RuntimeError("Missing R2_ACCOUNT_ID / CLOUDFLARE_ACCOUNT_ID.")
    if not bucket_name:
        raise RuntimeError("Missing R2_BUCKET_NAME.")

    ro_key = (os.getenv("R2_READONLY_ACCESS_KEY_ID") or "").strip()
    ro_secret = (os.getenv("R2_READONLY_SECRET_ACCESS_KEY") or "").strip()
    app_key = (os.getenv("R2_ACCESS_KEY_ID") or "").strip() or None
    inspect_configured = bool((os.getenv("CLOUDFLARE_TOKEN_INSPECT_API_KEY") or "").strip())

    if ro_key and ro_secret:
        cred_status, cred_reason = _verify_r2_readonly_permission(
            account_id, ro_key, app_key, bucket_name=bucket_name
        )
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=ro_key,
            aws_secret_access_key=ro_secret,
            region_name="auto",
        )
        return (
            _ReadOnlyR2Proxy(client),
            bucket_name,
            {
                "status": cred_status,
                "mode": (
                    f"SCRIPT-LEVEL (_ReadOnlyR2Proxy) | R2 RO Cred: distinct key | "
                    f"Inspect API Cred: {'separate' if inspect_configured else 'unset'} | R2 Policy Check: {cred_status}"
                ),
                "reason": cred_reason,
            },
        )

    if not allow_app_r2_env:
        raise RuntimeError(
            "Dedicated R2_READONLY_ACCESS_KEY_ID / R2_READONLY_SECRET_ACCESS_KEY not found. "
            "Refusing app.main.get_r2_client() because R2_ACCESS_KEY_ID carries backend RW permissions."
        )

    raw_client = mods["get_r2_client"]()
    return (
        _ReadOnlyR2Proxy(raw_client),
        bucket_name,
        {
            "status": "INCONCLUSIVE",
            "mode": "SCRIPT-LEVEL ONLY (_ReadOnlyR2Proxy wrapping backend RW keys!)",
            "reason": "--allow-app-r2-env used; credential-level R2 key is NOT read-only.",
        },
    )


def _create_read_only_supabase_client(
    mods: dict[str, Any],
    allow_service_role_db: bool,
) -> tuple[Any, dict[str, Any]]:
    """
    Requires SUPABASE_ANON_KEY + non-admin authenticated SUPABASE_READONLY_JWT and verifies
    DB public.profiles.role == 'employee' directly via the authenticated client before wrapping
    in _ReadOnlySupabaseProxy.
    """
    from supabase import create_client

    supabase_url = (os.getenv("SUPABASE_URL") or "").strip()
    if not supabase_url:
        raise RuntimeError("Missing SUPABASE_URL.")

    anon_key = (os.getenv("SUPABASE_ANON_KEY") or "").strip()
    readonly_jwt = (os.getenv("SUPABASE_READONLY_JWT") or "").strip()

    if anon_key and readonly_jwt:
        jwt_info = _verify_supabase_jwt_claims(anon_key, readonly_jwt)
        client = create_client(supabase_url, anon_key)
        client.postgrest.auth(readonly_jwt)

        profile_status, profile_reason = _verify_supabase_profile_role_is_employee(
            client, jwt_info["sub"]
        )
        return (
            _ReadOnlySupabaseProxy(client),
            {
                "status": profile_status,
                "mode": (
                    f"SERVER-VERIFIED JWT + DB profiles.role Check ({profile_status}) + "
                    "SCRIPT-LEVEL (_ReadOnlySupabaseProxy)"
                ),
                "reason": (
                    "Local JWT parser does NOT verify signature; " + profile_reason
                ),
                "jwt_info": jwt_info,
            },
        )

    if not allow_service_role_db:
        raise RuntimeError(
            "SUPABASE_ANON_KEY + SUPABASE_READONLY_JWT not found. "
            "Refusing SUPABASE_SERVICE_ROLE_KEY (bypasses RLS with full write rights)."
        )

    raw_client = mods["get_supabase"]()
    return (
        _ReadOnlySupabaseProxy(raw_client),
        {
            "status": "INCONCLUSIVE",
            "mode": "SCRIPT-LEVEL ONLY (_ReadOnlySupabaseProxy wrapping service_role!)",
            "reason": "--allow-service-role-db used; service_role bypasses DB RLS at credential level.",
        },
    )


def _audit_old_database_chunks(
    sb_ro: Any,
    doc_id: int,
    expected_r2_key: str,
) -> dict[str, Any]:
    """
    Validates existing DB document metadata (verified SQL columns: document_number, document_type)
    + strict non-empty exact r2_object_key + 1,309 gapless rule_chunks (chunk_index 0..1308).
    """
    doc_resp = (
        sb_ro.table("documents")
        .select(
            "id,title,document_number,document_type,status,ingestion_status,"
            "ocr_status,chunk_count,page_count,r2_object_key"
        )
        .eq("id", doc_id)
        .single()
        .execute()
    )
    doc_row = getattr(doc_resp, "data", None)
    if not isinstance(doc_row, dict):
        raise RuntimeError(f"Document id={doc_id} not found or unreadable via current DB credentials.")

    raw_r2_key = doc_row.get("r2_object_key")
    db_r2_key = str(raw_r2_key).strip() if isinstance(raw_r2_key, str) else ""
    if not db_r2_key or db_r2_key != expected_r2_key:
        raise RuntimeError(
            f"Fatal r2_object_key check failed for document id={doc_id}: "
            f"DB returned {raw_r2_key!r}, expected exact '{expected_r2_key}'."
        )

    declared_chunk_count = doc_row.get("chunk_count")
    if declared_chunk_count is not None and int(declared_chunk_count) != EXPECTED_OLD_DB_CHUNKS:
        raise RuntimeError(
            f"documents.chunk_count mismatch: expected {EXPECTED_OLD_DB_CHUNKS}, got {declared_chunk_count}."
        )

    all_rows: list[dict[str, Any]] = []
    offset = 0
    batch_size = 1000
    while True:
        chunk_resp = (
            sb_ro.table("rule_chunks")
            .select("id,chunk_index,page_number,rule_number,chapter,section_title,token_count")
            .eq("document_id", doc_id)
            .order("chunk_index", desc=False)
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        batch = getattr(chunk_resp, "data", None) or []
        all_rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    actual_count = len(all_rows)
    if actual_count != EXPECTED_OLD_DB_CHUNKS:
        raise RuntimeError(
            f"Mandatory old rule_chunks count check failed (even when chunk_count is NULL): "
            f"expected {EXPECTED_OLD_DB_CHUNKS}, found {actual_count}."
        )

    indices: list[int] = []
    for row in all_rows:
        idx_val = row.get("chunk_index")
        if idx_val is None or isinstance(idx_val, bool) or not isinstance(idx_val, int):
            raise RuntimeError(f"Invalid non-integer/null chunk_index on rule_chunks id={row.get('id')}: {idx_val!r}")
        indices.append(idx_val)

    counts = Counter(indices)
    duplicates = sorted(idx for idx, cnt in counts.items() if cnt > 1)
    if duplicates:
        raise RuntimeError(f"Duplicate chunk_index values detected in DB: {duplicates[:15]}")

    expected_set = set(range(EXPECTED_OLD_DB_CHUNKS))
    actual_set = set(indices)
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - expected_set)
    if missing or unexpected:
        raise RuntimeError(
            f"Non-contiguous chunk_index range detected. missing={missing[:15]}, unexpected={unexpected[:15]}"
        )

    null_rule_count = sum(1 for r in all_rows if not (r.get("rule_number") or "").strip())
    return {
        "document": doc_row,
        "old_chunk_count": actual_count,
        "declared_chunk_count": declared_chunk_count,
        "indices_contiguous_0_to_1308": True,
        "old_null_rule_count": null_rule_count,
        "old_rows": tuple(all_rows),
    }


def _tokenize_norm(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text or "").replace("\x00", " ")
    return tuple(normalized.split())


def _audit_new_chunk_integrity(
    pages: tuple[Any, ...],
    chunks: tuple[Any, ...],
) -> dict[str, Any]:
    """
    Mandatory structural integrity audit for NEW parser chunks:
    - non-empty chunk list when pages have text
    - unique, non-null integer chunk_index starting at 0 with zero gaps
    - non-empty chunk content & token_count > 0
    - valid physical_page_number in extracted pages, consistent page_number, valid source offsets
    """
    valid_page_nums = {p.physical_page_number for p in pages}
    non_empty_pages = [p for p in pages if _tokenize_norm(p.text)]
    violations: list[str] = []

    if not chunks:
        if non_empty_pages:
            violations.append("Zero chunks produced despite non-empty extracted PDF pages.")
        return {
            "status": "FAIL" if violations else "INCONCLUSIVE",
            "total_chunks": 0,
            "violations": tuple(violations),
        }

    seen_indices: dict[int, int] = {}
    empty_content_indices: list[int] = []
    invalid_page_chunks: list[tuple[Any, Any]] = []
    offset_errors: list[int] = []

    for pos, ch in enumerate(chunks):
        c_idx = ch.chunk_index
        if c_idx is None or isinstance(c_idx, bool) or not isinstance(c_idx, int) or c_idx < 0:
            violations.append(f"Chunk at pos={pos} has invalid chunk_index={c_idx!r}.")
            continue
        seen_indices[c_idx] = seen_indices.get(c_idx, 0) + 1
        if pos != c_idx:
            violations.append(f"Chunk ordering mismatch at pos={pos}: chunk_index={c_idx}.")

        if not (ch.content or "").strip() or (ch.token_count or 0) <= 0:
            empty_content_indices.append(c_idx)

        phys = ch.physical_page_number
        if (
            phys is None
            or isinstance(phys, bool)
            or not isinstance(phys, int)
            or phys not in valid_page_nums
            or ch.page_number != phys
        ):
            invalid_page_chunks.append((c_idx, phys))

        if ch.source_start_offset is not None or ch.source_end_offset is not None:
            if (
                ch.source_start_offset is None
                or ch.source_end_offset is None
                or ch.source_start_offset < 0
                or ch.source_end_offset <= ch.source_start_offset
            ):
                offset_errors.append(c_idx)

    dups = sorted(k for k, v in seen_indices.items() if v > 1)
    if dups:
        violations.append(f"Duplicate new chunk_index values: {dups[:15]}")

    expected_set = set(range(len(chunks)))
    actual_set = set(seen_indices.keys())
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - expected_set)
    if missing or unexpected:
        violations.append(f"Non-contiguous new chunk_index range: missing={missing[:15]}, unexpected={unexpected[:15]}")

    if empty_content_indices:
        violations.append(f"Empty chunk content detected at chunk_index={empty_content_indices[:15]}")
    if invalid_page_chunks:
        violations.append(f"Invalid physical_page_number on chunks={invalid_page_chunks[:15]}")
    if offset_errors:
        violations.append(f"Invalid source_start/end_offset bounds on chunk_index={offset_errors[:15]}")

    return {
        "status": "PASS" if not violations else "FAIL",
        "total_chunks": len(chunks),
        "unique_indices": len(seen_indices) == len(chunks) and not dups,
        "contiguous_0_to_n_minus_1": not missing and not unexpected,
        "empty_content_count": len(empty_content_indices),
        "invalid_page_count": len(invalid_page_chunks),
        "violations": tuple(violations[:25]),
    }


def _extract_rule_digits(label: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)*)", label or "")
    return m.group(1) if m else ""


def _label_prefix_kind(label: str) -> str | None:
    low = (label or "").strip().lower()
    if low.startswith("gr/sr "):
        return "GR_SR"
    if low.startswith("gr "):
        return "GR"
    if low.startswith("sr "):
        return "SR"
    if low.startswith(("rule ", "sub-rule ", "clause ", "नियम ")):
        return "RULE"
    if low.startswith(("para ", "पैरा ")):
        return "PARA"
    if low.startswith("circular "):
        return "CIRCULAR"
    if low.startswith("rbe "):
        return "RBE"
    if low.startswith("jpo "):
        return "JPO"
    return None


def _is_subrule_requiring_parent(label: str, rule_kind: str | None) -> bool:
    if rule_kind == "SR":
        if re.match(r"^SR\s+\d{1,2}\.\d{2}\.\d+", label):
            return True
        if re.match(r"^SR\s+\d{1,2}\.\d{2}[A-Z]?(?:\(|-\d+)", label):
            return True
    elif rule_kind == "GR":
        if re.match(r"^GR\s+\d{1,2}\.\d{2}[A-Z]?(?:\(|-\d+)", label):
            return True
    elif rule_kind == "GR_SR":
        if re.match(r"^GR/SR\s+\d{1,2}\.\d{2}[A-Z]?(?:\(|-\d+)", label):
            return True
    return False


def _audit_classification_and_hierarchy(
    chunks: tuple[Any, ...],
    mods: dict[str, Any],
) -> dict[str, Any]:
    """
    Validates EVERY chunk's rule_number, rule_kind, parent_rule, AND every contained_rules entry
    individually—checking hierarchy, sub-rule parentage, prefix consistency, and content grounding.
    """
    validate_rule_label = mods["validate_rule_label"]
    false_words: frozenset[str] = mods["KNOWN_FALSE_POSITIVE_RULE_WORDS"]

    kind_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    violations: list[str] = []
    sr_5_13_chunks: list[dict[str, Any]] = []
    verified_hierarchy_count = 0
    unclassified_rule_count = 0

    for ch in chunks:
        c_idx = ch.chunk_index
        r_kind = ch.rule_kind
        r_num = ch.rule_number
        parent = ch.parent_rule
        contained = tuple(ch.contained_rules or ())

        kind_counts[r_kind or "NONE"] += 1
        confidence_counts[ch.classification_confidence] += 1

        if r_kind is None:
            if r_num is not None or parent is not None or contained:
                violations.append(
                    f"chunk={c_idx}: rule_kind=None but metadata populated "
                    f"(rule={r_num!r}, parent={parent!r}, contained={contained!r})."
                )
            continue

        if not r_num:
            violations.append(f"chunk={c_idx}: rule_kind={r_kind!r} but rule_number is None.")
            continue

        # 1. Validate primary rule_number
        if r_num.strip().lower() in false_words or _GLUED_LOWER_SUFFIX_RE.search(r_num) or validate_rule_label(r_num) is None:
            violations.append(f"chunk={c_idx}: invalid/false-positive rule_number={r_num!r}.")
            continue

        inferred_kind = _label_prefix_kind(r_num)
        if inferred_kind != r_kind:
            violations.append(f"chunk={c_idx}: rule_number={r_num!r} prefix kind={inferred_kind!r} != rule_kind={r_kind!r}.")

        if ch.classification_confidence == "UNCLASSIFIED" and r_kind == "RULE":
            unclassified_rule_count += 1

        # 2. Validate contained_rules individually (no hidden junk, no duplicates, no cross-kind bleed)
        if not contained:
            violations.append(f"chunk={c_idx}: rule_number={r_num!r} has empty contained_rules.")
        if len(set(contained)) != len(contained):
            violations.append(f"chunk={c_idx}: duplicate entries in contained_rules={contained!r}.")

        base_prefixes: set[str] = set()
        for cr in contained:
            if cr.strip().lower() in false_words or _GLUED_LOWER_SUFFIX_RE.search(cr) or validate_rule_label(cr) is None:
                violations.append(f"chunk={c_idx}: invalid/false-positive entry in contained_rules={cr!r}.")
                continue
            cr_kind = _label_prefix_kind(cr)
            if cr_kind != r_kind:
                violations.append(f"chunk={c_idx}: contained_rule={cr!r} kind={cr_kind!r} conflicts with chunk rule_kind={r_kind!r}.")
            cr_dig = _extract_rule_digits(cr)
            if cr_dig:
                # Base 2-part digit group (e.g. 5.13 for SR 5.13.1 or SR 5.13.2)
                parts = cr_dig.split(".")
                base_prefixes.add(".".join(parts[:2]) if len(parts) >= 2 else cr_dig)

        if len(contained) == 1 and contained[0] != r_num:
            violations.append(f"chunk={c_idx}: single contained_rules[0]={contained[0]!r} != rule_number={r_num!r}.")
        if len(base_prefixes) > 1:
            violations.append(f"chunk={c_idx}: cross-rule bleed inside contained_rules={contained!r} (bases={sorted(base_prefixes)}).")

        # 3. Validate parent_rule & sub-rule hierarchy
        if parent is not None:
            if validate_rule_label(parent) is None or _GLUED_LOWER_SUFFIX_RE.search(parent):
                violations.append(f"chunk={c_idx}: invalid parent_rule={parent!r}.")
            elif _label_prefix_kind(parent) != r_kind:
                violations.append(f"chunk={c_idx}: parent_rule={parent!r} kind != rule_kind={r_kind!r}.")
            else:
                p_dig = _extract_rule_digits(parent)
                targets_to_check = contained or (r_num,)
                for tgt in targets_to_check:
                    t_dig = _extract_rule_digits(tgt)
                    if not p_dig or not t_dig.startswith(p_dig):
                        violations.append(f"chunk={c_idx}: parent_rule={parent!r} is not an ancestor of {tgt!r}.")
        else:
            if _is_subrule_requiring_parent(r_num, r_kind) or any(
                _is_subrule_requiring_parent(cr, r_kind) for cr in contained
            ):
                violations.append(f"chunk={c_idx}: sub-rule {r_num!r}/{contained!r} is missing parent_rule.")

        # 4. Content grounding vs continuation check (prevents stale previous-chunk rule leak)
        if not ch.is_continuation:
            r_dig = _extract_rule_digits(r_num)
            if r_dig and r_dig not in (ch.content or ""):
                violations.append(
                    f"chunk={c_idx}: non-continuation chunk carries rule_number={r_num!r} whose digits '{r_dig}' are absent from chunk content."
                )
        else:
            if ch.continued_from_rule is None:
                violations.append(f"chunk={c_idx}: is_continuation=True with rule_number={r_num!r} missing continued_from_rule.")

        verified_hierarchy_count += 1

        all_lbls = (r_num, *contained)
        if any(TARGET_SR_FOCUS_NUM in x and ("SR" in x or "Rule" in x) for x in all_lbls):
            sr_5_13_chunks.append(
                {
                    "chunk_index": c_idx,
                    "physical_page": ch.physical_page_number,
                    "printed_candidate": ch.printed_page_candidate,
                    "printed_status": ch.printed_page_status,
                    "rule_number": r_num,
                    "rule_kind": r_kind,
                    "parent_rule": parent,
                    "contained_rules": contained,
                    "section_title": ch.section_title,
                }
            )

    return {
        "status": "PASS" if not violations else "FAIL",
        "total_chunks": len(chunks),
        "verified_rule_chunks": verified_hierarchy_count,
        "unclassified_rule_chunks": unclassified_rule_count,
        "kind_counts": dict(kind_counts),
        "confidence_counts": dict(confidence_counts),
        "violations": tuple(violations[:30]),
        "sr_5_13_chunks": tuple(sr_5_13_chunks),
    }


def _collect_extraction_and_ocr_limitations(
    pages: tuple[Any, ...],
    exp_info: dict[str, Any],
) -> dict[str, Any]:
    """Collects explicit OCR & PDF extraction limitations separately from Text Loss parity."""
    ocr_pages = [p.physical_page_number for p in pages if getattr(p, "used_ocr", False)]
    no_typo_pages = [p.physical_page_number for p in pages if not getattr(p, "typography_available", False)]
    empty_pages = [p.physical_page_number for p in pages if not _tokenize_norm(p.text)]
    dict_removed_margins = sum(len(getattr(p, "removed_margin_lines", ()) or ()) for p in pages)

    return {
        "total_pages": len(pages),
        "ocr_page_count": len(ocr_pages),
        "ocr_pages_sample": tuple(ocr_pages[:20]),
        "no_typography_page_count": len(no_typo_pages),
        "empty_text_page_count": len(empty_pages),
        "empty_text_pages_sample": tuple(empty_pages[:20]),
        "dict_removed_margin_lines": dict_removed_margins,
        "skipped_repeated_margins": exp_info["skipped_repeated_margins"],
        "skipped_repeated_top_chapters": exp_info["skipped_repeated_top_chapters"],
        "limitation_notice": (
            "Text Loss Audit compares post-margin extracted PDF text vs reconstructed chunks ONLY. "
            "It CANNOT detect visual/image PDF omissions, scanned figure text missed by PyMuPDF, "
            "or OCR recognition typos inside OCR pages."
        ),
    }


def _extract_expected_document_tokens(
    pages: tuple[Any, ...],
    mods: dict[str, Any],
) -> dict[str, Any]:
    _normalize_page_text = mods["_normalize_page_text"]
    _margin_signature = mods["_margin_signature"]
    _detect_repeated_margin_signatures = mods["_detect_repeated_margin_signatures"]
    _merge_vertical_split_rule_lines = mods["_merge_vertical_split_rule_lines"]
    _parse_rule_heading_line = mods["_parse_rule_heading_line"]
    CHAPTER_HEADER_PATTERN = mods["CHAPTER_HEADER_PATTERN"]

    normalized_snapshots: list[dict[str, Any]] = []
    for p in pages:
        cleaned = _normalize_page_text(p.text)
        if not cleaned or not p.lines:
            continue
        normalized_snapshots.append(
            {
                "page_number": p.physical_page_number,
                "typo_available": p.typography_available,
                "lines": tuple(p.lines),
            }
        )

    repeated_sigs = frozenset(_detect_repeated_margin_signatures(normalized_snapshots))

    active_chapter: str | None = None
    active_rule_label: str | None = None
    last_rule_page: int | None = None

    expected_doc_tokens: list[str] = []
    page_token_ranges: dict[int, tuple[int, int]] = {}
    page_tokens_map: dict[int, tuple[str, ...]] = {}
    skipped_repeated_margins = 0
    skipped_repeated_top_chapters = 0

    for snap in normalized_snapshots:
        pnum = snap["page_number"]
        typo_ok = snap["typo_available"]
        raw_lines = snap["lines"]

        if repeated_sigs:
            total_ln = len(raw_lines)
            kept: list[Any] = []
            for idx_ln, ln_info in enumerate(raw_lines):
                is_edge = (idx_ln < 2) or (idx_ln >= total_ln - 2)
                if (
                    is_edge
                    and _margin_signature(ln_info.text) in repeated_sigs
                    and _parse_rule_heading_line(ln_info.text) is None
                ):
                    skipped_repeated_margins += 1
                    continue
                kept.append(ln_info)
            filtered_tuple = tuple(kept)
        else:
            filtered_tuple = raw_lines

        merged_lines = _merge_vertical_split_rule_lines(filtered_tuple)
        if not merged_lines:
            continue

        if last_rule_page is not None and (pnum - last_rule_page) > 1:
            active_rule_label = None

        page_kept_lines: list[str] = []
        in_block = False
        for line_idx, ln_info in enumerate(merged_lines):
            ln_txt = ln_info.text.strip()
            if not ln_txt:
                continue
            chap_m = CHAPTER_HEADER_PATTERN.match(ln_txt)
            heading = _parse_rule_heading_line(
                ln_txt,
                is_bold=ln_info.is_bold,
                typography_available=typo_ok,
                leading_is_bold=ln_info.leading_is_bold,
                heading_prefix_is_bold=ln_info.heading_prefix_is_bold,
            )
            if chap_m and heading is None:
                new_chap = chap_m.group(1).strip()[:120]
                is_rep_top_chap = (
                    line_idx < 2
                    and not in_block
                    and new_chap == active_chapter
                    and active_rule_label is not None
                )
                if is_rep_top_chap:
                    skipped_repeated_top_chapters += 1
                    continue
                if new_chap != active_chapter or in_block:
                    active_chapter = new_chap
                    active_rule_label = None
                    in_block = False
                page_kept_lines.append(ln_txt)
                continue

            if heading is not None:
                active_rule_label = heading.label
                last_rule_page = pnum
                in_block = True
            elif active_rule_label is not None and (in_block or last_rule_page == (pnum - 1)):
                last_rule_page = pnum
                in_block = True

            page_kept_lines.append(ln_txt)

        p_tokens = _tokenize_norm("\n".join(page_kept_lines))
        if p_tokens:
            p_start = len(expected_doc_tokens)
            expected_doc_tokens.extend(p_tokens)
            page_token_ranges[pnum] = (p_start, len(expected_doc_tokens))
            page_tokens_map[pnum] = p_tokens

    return {
        "expected_doc_tokens": tuple(expected_doc_tokens),
        "page_token_ranges": page_token_ranges,
        "page_tokens_map": page_tokens_map,
        "skipped_repeated_margins": skipped_repeated_margins,
        "skipped_repeated_top_chapters": skipped_repeated_top_chapters,
    }


def _reconstruct_stream_without_guessing(chunks: tuple[Any, ...]) -> dict[str, Any]:
    """
    Reconstructs global chunk text & token provenance using ONLY verifiable facts:
    1. Same-page continuation chunks: exact source_start_offset / source_end_offset character overlap
       or verified disjoint offsets. Missing/conflicting offsets -> flagged unverified (INCONCLUSIVE).
    2. Cross-page continuation chunks: concatenated WITHOUT heuristic/guessed token stripping;
       if a cross-page overlap phrase suspicion arises (duplicate boundary tokens without offsets),
       records cross_page_overlap_unverified so the caller reports INCONCLUSIVE rather than PASS.
    """
    ordered = sorted(chunks, key=lambda c: c.chunk_index)
    buf = ""
    chunk_global_char_spans: list[tuple[int, int, int]] = []
    unverified_same_page_overlaps: list[int] = []
    cross_page_continuations: list[int] = []
    suspected_unverified_cross_page_overlaps: list[int] = []
    verified_exact_overlaps = 0

    prev_chunk: Any | None = None
    for ch in ordered:
        txt = ch.content or ""
        if not txt.strip():
            prev_chunk = ch
            continue

        if not buf:
            buf = txt
            chunk_global_char_spans.append((ch.chunk_index, 0, len(buf)))
            prev_chunk = ch
            continue

        joined = False
        if prev_chunk is not None and getattr(ch, "is_continuation", False):
            curr_page = ch.physical_page_number or ch.page_number
            prev_page = prev_chunk.physical_page_number or prev_chunk.page_number

            if curr_page == prev_page:
                # Same-page continuation MUST have exact offsets proving overlap or disjointness
                if ch.source_start_offset is not None and prev_chunk.source_end_offset is not None:
                    if ch.source_start_offset < prev_chunk.source_end_offset:
                        ov_chars = prev_chunk.source_end_offset - ch.source_start_offset
                        prev_txt = prev_chunk.content or ""
                        if (
                            0 < ov_chars <= len(prev_txt)
                            and ov_chars <= len(txt)
                            and prev_txt[-ov_chars:] == txt[:ov_chars]
                        ):
                            c_start = len(buf) - ov_chars
                            buf += txt[ov_chars:]
                            chunk_global_char_spans.append((ch.chunk_index, c_start, len(buf)))
                            verified_exact_overlaps += 1
                            joined = True
                        else:
                            unverified_same_page_overlaps.append(ch.chunk_index)
                    else:
                        # Explicitly disjoint offsets on same page -> exact join
                        buf += "\n"
                        c_start = len(buf)
                        buf += txt
                        chunk_global_char_spans.append((ch.chunk_index, c_start, len(buf)))
                        joined = True
                else:
                    unverified_same_page_overlaps.append(ch.chunk_index)
            else:
                # Cross-page continuation: check WITHOUT stripping; flag if boundary looks overlapped
                cross_page_continuations.append(ch.chunk_index)
                prev_toks = _tokenize_norm(buf[-800:])
                curr_toks = _tokenize_norm(txt[:800])
                max_check = min(30, len(prev_toks), len(curr_toks))
                for k in range(max_check, 3, -1):
                    if prev_toks[-k:] == curr_toks[:k]:
                        suspected_unverified_cross_page_overlaps.append(ch.chunk_index)
                        break

        if not joined:
            buf += "\n"
            c_start = len(buf)
            buf += txt
            chunk_global_char_spans.append((ch.chunk_index, c_start, len(buf)))

        prev_chunk = ch

    reconstructed_tokens: list[str] = []
    token_owner_chunks: list[int] = []
    span_idx = 0
    num_spans = len(chunk_global_char_spans)
    for m in re.finditer(r"\S+", buf):
        tok_raw = unicodedata.normalize("NFKC", m.group(0)).replace("\x00", "")
        if not tok_raw:
            continue
        tok_mid = (m.start() + m.end()) // 2
        while span_idx + 1 < num_spans and chunk_global_char_spans[span_idx][2] <= tok_mid:
            span_idx += 1
        owner_idx = chunk_global_char_spans[span_idx][0] if num_spans > 0 else -1
        for sub_tok in tok_raw.split():
            reconstructed_tokens.append(sub_tok)
            token_owner_chunks.append(owner_idx)

    return {
        "reconstructed_doc_tokens": tuple(reconstructed_tokens),
        "token_owner_chunks": tuple(token_owner_chunks),
        "verified_exact_overlaps": verified_exact_overlaps,
        "unverified_same_page_overlaps": tuple(unverified_same_page_overlaps),
        "cross_page_continuations": tuple(cross_page_continuations),
        "suspected_unverified_cross_page_overlaps": tuple(suspected_unverified_cross_page_overlaps),
    }


def _verify_page_mapping_independently(
    pages: tuple[Any, ...],
    chunks: tuple[Any, ...],
    exp_info: dict[str, Any],
    rec_info: dict[str, Any],
    token_alignment_map: dict[int, int],  # expected_tok_idx -> reconstructed_tok_idx
) -> dict[str, Any]:
    """
    Independently verifies physical page mapping & chunk page ownership:
    1. Every extracted physical page p's expected token slice MUST equal its aligned reconstructed tokens.
    2. For each chunk c, independently finds covered physical pages via token ranges:
       - c.physical_page_number must equal the FIRST physical page covered by c's tokens.
       - Multi-page chunks are valid ONLY when covered pages form a contiguous range (e.g. [230, 231]).
       - Non-contiguous gaps, wrong start physical_page_number, or unowned tokens -> FAIL / INCONCLUSIVE.
    """
    page_token_ranges: dict[int, tuple[int, int]] = exp_info["page_token_ranges"]
    page_tokens_map: dict[int, tuple[str, ...]] = exp_info["page_tokens_map"]
    reconstructed_tokens: tuple[str, ...] = rec_info["reconstructed_doc_tokens"]
    token_owner_chunks: tuple[int, ...] = rec_info["token_owner_chunks"]

    chunk_by_idx = {c.chunk_index: c for c in chunks}
    page_covering_chunks: dict[int, tuple[int, ...]] = {}
    chunk_covered_pages: dict[int, list[int]] = {c.chunk_index: [] for c in chunks}
    page_issues: list[str] = []
    inconclusive_issues: list[str] = []

    for pnum in sorted(page_token_ranges.keys()):
        p_start, p_end = page_token_ranges[pnum]
        expected_p_toks = page_tokens_map[pnum]

        aligned_p_toks: list[str] = []
        owners: list[int] = []
        seen_owners: set[int] = set()
        missing_alignment = False

        for e_idx in range(p_start, p_end):
            r_idx = token_alignment_map.get(e_idx)
            if r_idx is None:
                missing_alignment = True
                break
            aligned_p_toks.append(reconstructed_tokens[r_idx])
            own_cid = token_owner_chunks[r_idx]
            if own_cid not in seen_owners:
                seen_owners.add(own_cid)
                owners.append(own_cid)
            if own_cid in chunk_covered_pages and (
                not chunk_covered_pages[own_cid] or chunk_covered_pages[own_cid][-1] != pnum
            ):
                chunk_covered_pages[own_cid].append(pnum)

        page_covering_chunks[pnum] = tuple(owners)

        if missing_alignment or tuple(aligned_p_toks) != expected_p_toks:
            page_issues.append(f"phys={pnum}: per-page tokens failed exact 1:1 alignment with covering chunks {owners}.")
            continue

        if not owners:
            page_issues.append(f"phys={pnum}: non-empty extracted page has ZERO covering chunks.")

    # Verify independent ownership metadata for EVERY chunk
    for c_idx, ch in chunk_by_idx.items():
        cov_pages = chunk_covered_pages.get(c_idx, [])
        if not cov_pages:
            # Chunk has tokens not aligned to any physical page!
            inconclusive_issues.append(
                f"chunk={c_idx} (declared phys={ch.physical_page_number}): did not uniquely align to any physical page."
            )
            continue

        expected_first_page = cov_pages[0]
        if ch.physical_page_number != expected_first_page:
            page_issues.append(
                f"chunk={c_idx}: declared physical_page_number={ch.physical_page_number} != "
                f"actual first covered page={expected_first_page} (covered={cov_pages})."
            )

        if len(cov_pages) > 1:
            contiguous = list(range(cov_pages[0], cov_pages[-1] + 1))
            if cov_pages != contiguous:
                page_issues.append(
                    f"chunk={c_idx}: non-contiguous multi-page span {cov_pages} (expected {contiguous})."
                )

    if page_issues:
        status = "FAIL"
        reason = f"Independent physical page mapping violations: {len(page_issues)}."
    elif inconclusive_issues:
        status = "INCONCLUSIVE"
        reason = f"Ambiguous chunk-to-page ownership on {len(inconclusive_issues)} chunk(s)."
    else:
        status = "PASS"
        reason = "All physical pages and spanning chunk declarations independently verified."

    return {
        "status": status,
        "reason": reason,
        "pages_verified": len(page_token_ranges),
        "page_covering_chunks": page_covering_chunks,
        "chunk_covered_pages": {k: tuple(v) for k, v in chunk_covered_pages.items()},
        "page_issues": tuple(page_issues[:25]),
        "inconclusive_issues": tuple(inconclusive_issues[:25]),
    }


def _audit_text_overlap_and_pages(
    pages: tuple[Any, ...],
    chunks: tuple[Any, ...],
    mods: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Runs all 3 coupled-yet-independent verification reports without false passes:
      1. extraction_limitations (OCR, absent font metadata, empty pages, filtered margins)
      2. cross_page_overlap_audit (PASS only if exact offsets / verified non-guessed boundaries)
      3. text_loss_audit (PASS = extracted-text-to-chunks parity ONLY; FAIL / INCONCLUSIVE)
      4. page_mapping_audit (independent per-page token & declared physical_page_number check)
    """
    exp_info = _extract_expected_document_tokens(pages, mods)
    rec_info = _reconstruct_stream_without_guessing(chunks)
    limitations = _collect_extraction_and_ocr_limitations(pages, exp_info)

    expected_tokens: tuple[str, ...] = exp_info["expected_doc_tokens"]
    reconstructed_tokens: tuple[str, ...] = rec_info["reconstructed_doc_tokens"]

    # Determine Cross-Page & Continuation Overlap Audit independently (never guess!)
    overlap_problems: list[str] = []
    if rec_info["unverified_same_page_overlaps"]:
        overlap_problems.append(
            f"Same-page continuations lack exact matching source offsets: {rec_info['unverified_same_page_overlaps'][:15]}"
        )
    if rec_info["suspected_unverified_cross_page_overlaps"]:
        overlap_problems.append(
            f"Cross-page continuations have unverified boundary overlap without cross-page offsets: "
            f"{rec_info['suspected_unverified_cross_page_overlaps'][:15]}"
        )

    overlap_audit = {
        "status": "INCONCLUSIVE" if overlap_problems else "PASS",
        "verified_exact_overlaps": rec_info["verified_exact_overlaps"],
        "cross_page_continuations_count": len(rec_info["cross_page_continuations"]),
        "issues": tuple(overlap_problems),
    }

    # Text Loss Audit (exact sequence + multiset + SequenceMatcher)
    token_alignment_map: dict[int, int] = {}
    if expected_tokens == reconstructed_tokens:
        for idx in range(len(expected_tokens)):
            token_alignment_map[idx] = idx
        missing_occ = 0
        extra_occ = 0
        if overlap_audit["status"] == "INCONCLUSIVE":
            text_status = "INCONCLUSIVE"
            text_reason = "Stream matched only alongside unverified overlap; cannot mark strict PASS."
        else:
            text_status = "PASS"
            text_reason = (
                "EXTRACTED_TEXT_TO_CHUNKS_PARITY PASS: post-margin extracted PDF tokens match "
                "reconstructed chunks 1:1 in order and occurrence count (visual PDF completeness not verified)."
            )
    else:
        exp_counter = Counter(expected_tokens)
        rec_counter = Counter(reconstructed_tokens)
        missing_occ = sum((exp_counter - rec_counter).values())
        extra_occ = sum((rec_counter - exp_counter).values())

        sm = difflib.SequenceMatcher(None, expected_tokens, reconstructed_tokens, autojunk=False)
        opcodes = sm.get_opcodes()
        has_delete_or_replace = False
        has_insert = False
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                for off in range(i2 - i1):
                    token_alignment_map[i1 + off] = j1 + off
            elif tag in {"delete", "replace"}:
                has_delete_or_replace = True
            elif tag == "insert":
                has_insert = True

        if missing_occ > 0 or has_delete_or_replace:
            text_status = "FAIL"
            text_reason = (
                f"Text loss or sequence swap detected between extracted text and chunks: "
                f"missing_occurrences={missing_occ}, extra_occurrences={extra_occ}."
            )
        elif has_insert or extra_occ > 0 or overlap_audit["status"] == "INCONCLUSIVE":
            text_status = "INCONCLUSIVE"
            text_reason = (
                f"Zero missing occurrences or deletions, but unresolved extra tokens/overlap ambiguity "
                f"(extra_occurrences={extra_occ}) require INCONCLUSIVE status (not PASS)."
            )
        else:
            text_status = "INCONCLUSIVE"
            text_reason = "Exact equality could not be established; marked INCONCLUSIVE."

    page_mapping_audit = _verify_page_mapping_independently(
        pages, chunks, exp_info, rec_info, token_alignment_map
    )

    text_loss_audit = {
        "status": text_status,
        "scope": "EXTRACTED_TEXT_TO_CHUNKS_PARITY_ONLY",
        "reason": text_reason,
        "expected_token_count": len(expected_tokens),
        "reconstructed_token_count": len(reconstructed_tokens),
        "missing_occurrence_count": missing_occ,
        "extra_occurrence_count": extra_occ,
        "pages_checked": len(exp_info["page_token_ranges"]),
    }

    return text_loss_audit, overlap_audit, page_mapping_audit, limitations


def _audit_focus_page_range_and_old_db(
    pages: tuple[Any, ...],
    chunks: tuple[Any, ...],
    db_audit: dict[str, Any],
    page_mapping_audit: dict[str, Any],
    mods: dict[str, Any],
    start_page: int,
    end_page: int,
) -> dict[str, Any]:
    validate_rule_label = mods["validate_rule_label"]
    false_words: frozenset[str] = mods["KNOWN_FALSE_POSITIVE_RULE_WORDS"]

    chunk_by_idx = {c.chunk_index: c for c in chunks}
    page_by_num = {p.physical_page_number: p for p in pages}
    covering_map: dict[int, tuple[int, ...]] = page_mapping_audit.get("page_covering_chunks", {})

    old_rows: tuple[dict[str, Any], ...] = db_audit["old_rows"]
    old_false_or_invalid: list[tuple[int, int, str]] = []
    for row in old_rows:
        r_lbl = (row.get("rule_number") or "").strip()
        if not r_lbl:
            continue
        if r_lbl.lower() in false_words or _GLUED_LOWER_SUFFIX_RE.search(r_lbl) or validate_rule_label(r_lbl) is None:
            old_false_or_invalid.append((int(row["id"]), int(row["chunk_index"]), r_lbl))

    old_by_page: dict[int, list[dict[str, Any]]] = {}
    for row in old_rows:
        pnum = row.get("page_number")
        if isinstance(pnum, int):
            old_by_page.setdefault(pnum, []).append(row)

    focus_pages_report: list[dict[str, Any]] = []
    for pnum in range(start_page, end_page + 1):
        p_obj = page_by_num.get(pnum)
        cov_indices = list(covering_map.get(pnum, ()))
        for ch in chunks:
            ch_p = ch.physical_page_number or ch.page_number
            if ch_p == pnum and ch.chunk_index not in cov_indices:
                cov_indices.append(ch.chunk_index)

        new_items = []
        for idx in cov_indices:
            ch = chunk_by_idx.get(idx)
            if ch is not None:
                new_items.append(
                    {
                        "chunk_index": ch.chunk_index,
                        "chunk_start_page": ch.physical_page_number,
                        "rule_number": ch.rule_number,
                        "parent_rule": ch.parent_rule,
                        "contained_rules": ch.contained_rules,
                    }
                )

        old_items = [
            {
                "id": r.get("id"),
                "chunk_index": r.get("chunk_index"),
                "page_number": r.get("page_number"),
                "rule_number": r.get("rule_number"),
            }
            for r in old_by_page.get(pnum, ())
        ]

        focus_pages_report.append(
            {
                "physical_page": pnum,
                "page_present_in_pdf": p_obj is not None,
                "printed_candidate": p_obj.printed_page_candidate if p_obj else None,
                "printed_status": p_obj.printed_page_status if p_obj else "PAGE_NOT_IN_PDF",
                "new_chunks_covering_page": tuple(new_items),
                "old_db_chunks_on_page": tuple(old_items),
            }
        )

    max_phys = max((p.physical_page_number for p in pages), default=0)
    old_out_of_range = [
        r.get("page_number")
        for r in old_rows
        if isinstance(r.get("page_number"), int) and (r["page_number"] < 1 or r["page_number"] > max_phys)
    ]

    return {
        "range_label": f"p{start_page}_{end_page}",
        "old_total_false_or_invalid_labels": len(old_false_or_invalid),
        "old_out_of_physical_range_count": len(old_out_of_range),
        "old_vs_new_text_comparison_note": (
            "METADATA_AND_PHYSICAL_PAGE_ONLY (old rule_chunks content/offsets not selected)."
        ),
        "focus_pages": tuple(focus_pages_report),
    }


def _aggregate_exit_code(verdicts: dict[str, str]) -> int:
    """PASS=0, FAIL=1, INCONCLUSIVE=2. FAIL dominates INCONCLUSIVE; any INCONCLUSIVE forbids 0."""
    statuses = list(verdicts.values())
    if any(s == "FAIL" for s in statuses):
        return EXIT_FAIL
    if any(s != "PASS" for s in statuses):
        return EXIT_INCONCLUSIVE
    return EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-Only Dry-Run Audit for G&SR PDF Extraction & Rule-Aware Chunking."
    )
    parser.add_argument("--backend-dir", default=None, help="Explicit path to repo backend/ directory.")
    parser.add_argument("--allow-app-r2-env", action="store_true", help="Allow RW app R2 fallback (results in INCONCLUSIVE).")
    parser.add_argument("--allow-service-role-db", action="store_true", help="Allow service_role DB fallback (results in INCONCLUSIVE).")
    parser.add_argument("--focus-start-page", type=int, default=DEFAULT_FOCUS_START_PAGE)
    parser.add_argument("--focus-end-page", type=int, default=DEFAULT_FOCUS_END_PAGE)
    args = parser.parse_args(argv)

    sanitize_fn = None
    try:
        if args.focus_start_page < 1 or args.focus_end_page < args.focus_start_page:
            raise ValueError("Invalid focus page range.")

        backend_dir = _resolve_backend_dir(args.backend_dir)
        mods = _load_backend_modules(backend_dir)
        sanitize_fn = mods["sanitize_error_message"]

        r2_ro, bucket_name, r2_sec = _create_read_only_r2_client(mods, allow_app_r2_env=args.allow_app_r2_env)
        sb_ro, db_sec = _create_read_only_supabase_client(mods, allow_service_role_db=args.allow_service_role_db)

        print("=== SECURITY MODES ===")
        print(f"Backend Dir : {backend_dir}")
        print(f"R2 Guard    : {r2_sec['mode']} | {r2_sec['reason']}")
        print(f"DB Guard    : {db_sec['mode']} | {db_sec['reason']}")

        db_audit = _audit_old_database_chunks(
            sb_ro, doc_id=TARGET_DOCUMENT_ID, expected_r2_key=TARGET_R2_OBJECT_KEY
        )
        print("\n=== EXISTING DB BASELINE AUDIT (READ-ONLY) ===")
        print(f"Document ID          : {TARGET_DOCUMENT_ID}")
        print(f"Document Type/Number : {db_audit['document'].get('document_type')} / {db_audit['document'].get('document_number')}")
        print(f"Exact R2 Object Key  : {db_audit['document'].get('r2_object_key')}")
        print(f"Declared chunk_count : {db_audit['declared_chunk_count']}")
        print(f"Verified DB chunks   : {db_audit['old_chunk_count']} (contiguous 0..1308 OK)")
        print(f"Old NULL rule_number : {db_audit['old_null_rule_count']}")

        pdf_bytes = mods["download_pdf_from_r2"](r2_ro, bucket_name, TARGET_R2_OBJECT_KEY)
        raw_pages, used_ocr = mods["extract_pdf_pages_detailed"](pdf_bytes, force_ocr=False)
        raw_chunks = mods["chunk_pages_with_metadata"](raw_pages)

        pages = tuple(raw_pages)
        chunks = tuple(raw_chunks)
        pre_pages_len, pre_chunks_len = len(pages), len(chunks)
        pre_text_lens = tuple(len(p.text) for p in pages)
        pre_chunk_lens = tuple(len(c.content) for c in chunks)

        chunk_integrity_audit = _audit_new_chunk_integrity(pages, chunks)
        classification_audit = _audit_classification_and_hierarchy(chunks, mods)
        text_loss_audit, overlap_audit, page_mapping_audit, limitations = _audit_text_overlap_and_pages(
            pages, chunks, mods
        )
        focus_audit = _audit_focus_page_range_and_old_db(
            pages,
            chunks,
            db_audit,
            page_mapping_audit,
            mods,
            start_page=args.focus_start_page,
            end_page=args.focus_end_page,
        )

        assert len(pages) == pre_pages_len and tuple(len(p.text) for p in pages) == pre_text_lens
        assert len(chunks) == pre_chunks_len and tuple(len(c.content) for c in chunks) == pre_chunk_lens

        print("\n=== NEW CHUNK INTEGRITY & GR/SR CLASSIFICATION ===")
        print(f"New Chunk Integrity  : {chunk_integrity_audit['status']} (total={chunk_integrity_audit['total_chunks']})")
        if chunk_integrity_audit["violations"]:
            print(f"  Violations         : {chunk_integrity_audit['violations']}")
        print(
            f"GR/SR Classification : {classification_audit['status']} "
            f"(verified={classification_audit['verified_rule_chunks']}, "
            f"unclassified_rule={classification_audit['unclassified_rule_chunks']})"
        )
        print(f"Rule Kind Counts     : {classification_audit['kind_counts']}")
        print(f"Confidence Counts    : {classification_audit['confidence_counts']}")
        if classification_audit["violations"]:
            print(f"  Class Violations   : {classification_audit['violations']}")

        print(f"\n=== FOCUS RANGE AUDIT ({focus_audit['range_label']}) & OLD DB COMPARISON ===")
        print(f"Old DB Invalid/False Labels : {focus_audit['old_total_false_or_invalid_labels']}")
        print(f"Old DB Out-of-Range Pages   : {focus_audit['old_out_of_physical_range_count']}")
        print(f"Comparison Scope            : {focus_audit['old_vs_new_text_comparison_note']}")
        for fp in focus_audit["focus_pages"]:
            new_rules = [(x["chunk_index"], x["rule_number"], x["parent_rule"]) for x in fp["new_chunks_covering_page"]]
            old_rules = [(x["id"], x["chunk_index"], x["rule_number"]) for x in fp["old_db_chunks_on_page"]]
            print(
                f"  phys={fp['physical_page']} printed={fp['printed_candidate']}({fp['printed_status']}) "
                f"| new={new_rules} | old={old_rules}"
            )

        print("\n=== SR 5.13 HIERARCHY & SUB-RULES ===")
        for item in classification_audit["sr_5_13_chunks"]:
            print(item)

        print("\n=== EXTRACTION & OCR LIMITATIONS (SEPARATE REPORT) ===")
        print(limitations)

        print("\n=== TEXT LOSS, CROSS-PAGE OVERLAP & INDEPENDENT PAGE MAPPING ===")
        print(f"Text Loss Scope      : {text_loss_audit['scope']}")
        print(f"Text Loss Status     : {text_loss_audit['status']} | {text_loss_audit['reason']}")
        print(f"Cross-Page Overlap   : {overlap_audit['status']} | issues={overlap_audit['issues']}")
        print(f"Page Mapping Audit   : {page_mapping_audit['status']} | {page_mapping_audit['reason']}")
        if page_mapping_audit["page_issues"]:
            print(f"  Page Issues        : {page_mapping_audit['page_issues']}")
        if page_mapping_audit["inconclusive_issues"]:
            print(f"  Inconclusive Pages : {page_mapping_audit['inconclusive_issues']}")

        verdicts = {
            "r2_credential_security": r2_sec["status"],
            "db_credential_security": db_sec["status"],
            "db_baseline_audit": "PASS",
            "new_chunk_integrity": chunk_integrity_audit["status"],
            "gr_sr_classification": classification_audit["status"],
            "cross_page_overlap": overlap_audit["status"],
            "text_loss_audit": text_loss_audit["status"],
            "page_mapping_audit": page_mapping_audit["status"],
        }
        exit_code = _aggregate_exit_code(verdicts)
        print(f"\n=== FINAL VERDICTS (EXIT_CODE={exit_code}) ===")
        for k, v in verdicts.items():
            print(f"  {k}: {v}")
        return exit_code
    except Exception as exc:
        print(f"DRY-RUN AUDIT FAILED: {_safe_format_exception(exc, sanitize_fn)}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
