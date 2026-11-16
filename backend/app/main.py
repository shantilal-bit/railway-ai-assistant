"""FastAPI Backend for Railway Rules AI Assistant.

Production RAG Architecture:
- Supabase Auth, Postgres + pgvector (1024-dim HNSW + bilingual FTS)
- Cloudflare Workers AI (@cf/baai/bge-m3) multilingual embeddings
- 5-tier search hierarchy with legal authority & supersession comparison
- Groq AI synthesis via AIProvider abstraction
- Private Cloudflare R2 PDF storage + public Google Drive import + Tesseract OCR (eng+hin)
"""


import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from supabase import Client, create_client

from app.ai_providers import AIProviderError, get_ai_provider
from app.embeddings import BGE_M3_DIMENSIONS, BGE_M3_MODEL, CloudflareBgeM3Embedder, EmbeddingError
from app.pdf_pipeline import (
    PdfPipelineError,
    compute_sha256,
    download_pdf_from_r2,
    download_public_google_drive_pdf,
    upload_pdf_to_r2,
    validate_pdf_bytes,
)
from app.rag_service import (
    answer_railway_rule_question,
    ingest_document_bytes,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Railway Rules AI Assistant API", version="2.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_DOC_TYPES = {
    "ACT",
    "RULE_BOOK",
    "MANUAL",
    "CIRCULAR",
    "JPO",
    "AMENDMENT_SLIP",
    "GAZETTE",
    "OTHER",
}
ALLOWED_DOC_STATUSES = {"draft", "in_review", "published", "superseded", "disabled"}
ALLOWED_SCOPE_LEVELS = {"DEPARTMENT", "DIVISION", "ZONE", "RAILWAY_BOARD", "COMMON"}


def get_supabase() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def get_r2_client():
    account_id = os.getenv("R2_ACCOUNT_ID") or os.getenv("CLOUDFLARE_ACCOUNT_ID")
    if not account_id:
        raise RuntimeError("Missing R2_ACCOUNT_ID environment variable.")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


async def get_current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    sb = get_supabase()
    try:
        user_resp = sb.auth.get_user(token)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Supabase JWT verification failed: %s", sanitize_error_message(exc))
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc

    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    try:
        profile = sb.table("profiles").select("*").eq("id", user_resp.user.id).single().execute()
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Profile lookup failed: %s", sanitize_error_message(exc))
        raise HTTPException(status_code=401, detail="User profile not found") from exc

    if not profile.data:
        raise HTTPException(status_code=401, detail="User profile not found")
    return profile.data


def require_admin(user: dict[str, Any]) -> dict[str, Any]:
    if str(user.get("role", "")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def _safe_filename(name: str) -> str:
    base = os.path.basename((name or "document.pdf").strip())
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    if not cleaned.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are permitted.")
    return cleaned


def _build_r2_object_key(
    zone_code: str,
    division_code: Optional[str],
    department_code: Optional[str],
    file_name: str,
    sha_prefix: Optional[str] = None,
) -> str:
    safe_file = _safe_filename(file_name)
    if sha_prefix:
        safe_file = f"{sha_prefix[:10]}_{safe_file}"
    parts = [
        re.sub(r"[^a-z0-9_-]", "", (zone_code or "common").lower()) or "common",
        re.sub(r"[^a-z0-9_-]", "", (division_code or "zone-wide").lower()) or "zone-wide",
        re.sub(r"[^a-z0-9_-]", "", (department_code or "common").lower()) or "common",
        safe_file,
    ]
    return "/".join(parts)


def _default_authority_rank(document_type: str, scope_level: str) -> int:
    if scope_level == "RAILWAY_BOARD" or document_type in ("ACT", "GAZETTE"):
        return 100
    if document_type in ("RULE_BOOK", "MANUAL"):
        return 85
    if scope_level == "ZONE":
        return 70
    if scope_level == "DIVISION":
        return 60
    if scope_level == "COMMON":
        return 75
    return 50


def _serialize_admin_document(row: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(row)
    if serialized.get("id") is not None:
        serialized["id"] = str(serialized["id"])
    for optional_id_key in ("uploaded_by", "reviewed_by", "zone_id", "division_id", "department_id"):
        if optional_id_key in serialized and serialized[optional_id_key] is not None:
            serialized[optional_id_key] = str(serialized[optional_id_key])
    return serialized


def _upsert_document_scope(
    sb: Client,
    document_id: Any,
    scope_level: str,
    zone_id: Optional[str],
    division_id: Optional[str],
    department_id: Optional[str],
) -> None:
    sb.table("document_scopes").delete().eq("document_id", document_id).execute()
    scope_payload: dict[str, Any] = {
        "document_id": document_id,
        "scope_level": scope_level,
        "zone_id": zone_id if scope_level in ("DEPARTMENT", "DIVISION", "ZONE") else None,
        "division_id": division_id if scope_level in ("DEPARTMENT", "DIVISION") else None,
        "department_id": department_id if scope_level == "DEPARTMENT" else None,
    }
    sb.table("document_scopes").insert(scope_payload).execute()


def _upsert_supersession_link(
    sb: Client,
    amending_document_id: Any,
    target_document_id: Optional[str],
    effective_date: Optional[str],
    document_number: Optional[str],
) -> None:
    if not target_document_id:
        return
    existing = (
        sb.table("amendments")
        .select("id")
        .eq("amending_document_id", amending_document_id)
        .eq("target_document_id", target_document_id)
        .execute()
        .data
        or []
    )
    if not existing:
        sb.table("amendments").insert(
            {
                "amending_document_id": amending_document_id,
                "target_document_id": target_document_id,
                "relationship_type": "SUPERSEDES",
                "circular_reference": document_number,
                "effective_date": effective_date,
            }
        ).execute()


async def _run_r2_ingestion_task(document_id: str, object_key: str, force_ocr: bool) -> None:
    sb = get_supabase()
    try:
        r2 = get_r2_client()
        pdf_bytes = download_pdf_from_r2(r2, os.environ["R2_BUCKET_NAME"], object_key)
        await ingest_document_bytes(
            sb=sb,
            document_id=document_id,
            pdf_bytes=pdf_bytes,
            force_ocr=force_ocr,
            embedder=CloudflareBgeM3Embedder(),
        )
    except Exception as exc:
        err_msg = sanitize_error_message(exc)
        sb.table("documents").update(
            {
                "ingestion_status": "failed",
                "ingestion_error": err_msg,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", document_id).execute()


async def _run_bytes_ingestion_task(document_id: str, pdf_bytes: bytes, force_ocr: bool) -> None:
    sb = get_supabase()
    try:
        await ingest_document_bytes(
            sb=sb,
            document_id=document_id,
            pdf_bytes=pdf_bytes,
            force_ocr=force_ocr,
            embedder=CloudflareBgeM3Embedder(),
        )
    except Exception as exc:
        err_msg = sanitize_error_message(exc)
        sb.table("documents").update(
            {
                "ingestion_status": "failed",
                "ingestion_error": err_msg,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", document_id).execute()


class ChatAskRequest(BaseModel):
    sessionId: Optional[str] = None
    zoneId: str
    divisionId: str
    departmentId: str
    question: str = Field(..., min_length=1, max_length=2000)
    preferredLanguage: str = "auto"
    history: list[dict] = []


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str
    fullName: str
    employeeId: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refreshToken: str = Field(..., min_length=10)


class PresignUploadRequest(BaseModel):
    fileName: str
    zoneCode: str
    divisionCode: Optional[str] = None
    departmentCode: Optional[str] = None


class RegisterDocumentRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=300)
    documentNumber: Optional[str] = None
    documentType: str = "CIRCULAR"
    issuingAuthority: str = Field(..., min_length=2, max_length=200)
    authorityRank: Optional[int] = Field(default=None, ge=1, le=100)
    objectKey: str
    fileSha256: str
    scopeLevel: str = "DEPARTMENT"
    zoneId: Optional[str] = None
    divisionId: Optional[str] = None
    departmentId: Optional[str] = None
    issueDate: Optional[str] = None
    effectiveDate: Optional[str] = None
    requiresOcr: bool = False
    supersedesDocumentId: Optional[str] = None
    runSync: bool = False


class ImportDrivePdfRequest(BaseModel):
    driveUrl: str
    title: str = Field(..., min_length=2, max_length=300)
    documentNumber: Optional[str] = None
    documentType: str = "CIRCULAR"
    issuingAuthority: str = Field(..., min_length=2, max_length=200)
    authorityRank: Optional[int] = Field(default=None, ge=1, le=100)
    scopeLevel: str = "DEPARTMENT"
    zoneId: Optional[str] = None
    zoneCode: str = "WR"
    divisionId: Optional[str] = None
    divisionCode: Optional[str] = None
    departmentId: Optional[str] = None
    departmentCode: Optional[str] = None
    issueDate: Optional[str] = None
    effectiveDate: Optional[str] = None
    requiresOcr: bool = False
    supersedesDocumentId: Optional[str] = None
    runSync: bool = False


class ReprocessDocumentRequest(BaseModel):
    forceOcr: bool = False
    runSync: bool = False


class DocumentStatusUpdateRequest(BaseModel):
    status: str
    disabledReason: Optional[str] = None


@app.get("/v1/health")
async def health():
    return {
        "status": "ok",
        "aiProvider": os.getenv("AI_PROVIDER", "groq"),
        "embeddingProvider": "cloudflare_workers_ai",
        "embeddingModel": BGE_M3_MODEL,
        "embeddingDimensions": BGE_M3_DIMENSIONS,
        "storage": "cloudflare_r2",
        "database": "supabase_pgvector",
    }


@app.get("/v1/taxonomy")
async def get_taxonomy(includeInactiveZones: bool = False):
    sb = get_supabase()
    zones_q = sb.table("zones").select("*").order("sort_order")
    if not includeInactiveZones:
        zones_q = zones_q.eq("is_active", True)
    raw_zones = zones_q.execute().data or []
    raw_divisions = (
        sb.table("divisions").select("*").eq("is_active", True).order("sort_order").execute().data or []
    )
    raw_departments = (
        sb.table("departments").select("*").eq("is_active", True).order("sort_order").execute().data or []
    )

    zones = [{**row, "id": str(row["id"])} for row in raw_zones]
    divisions = [
        {**row, "id": str(row["id"]), "zone_id": str(row["zone_id"])}
        for row in raw_divisions
    ]
    departments = [{**row, "id": str(row["id"])} for row in raw_departments]
    return {"zones": zones, "divisions": divisions, "departments": departments}


@app.post("/v1/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest):
    sb = get_supabase()
    res = sb.auth.sign_in_with_password({"email": body.email, "password": body.password})
    if not res.session:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    profile = sb.table("profiles").select("*").eq("id", res.user.id).single().execute().data
    return {
        "accessToken": res.session.access_token,
        "refreshToken": res.session.refresh_token,
        "user": profile,
    }


@app.post("/v1/auth/signup")
@limiter.limit("5/minute")
async def signup(request: Request, body: SignupRequest):
    sb = get_supabase()
    res = sb.auth.sign_up({"email": body.email, "password": body.password})
    if not res.user:
        raise HTTPException(status_code=400, detail="Signup failed")
    sb.table("profiles").insert(
        {
            "id": res.user.id,
            "email": body.email,
            "full_name": body.fullName,
            "employee_id": body.employeeId,
            "role": "employee",
        }
    ).execute()
    return {"status": "created", "userId": res.user.id}


@app.post("/v1/auth/refresh")
@limiter.limit("20/minute")
async def refresh_session(request: Request, body: RefreshTokenRequest):
    sb = get_supabase()
    try:
        res = sb.auth.refresh_session(body.refreshToken.strip())
    except Exception as exc:
        logger.warning("Session refresh failed: %s", sanitize_error_message(exc))
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token") from exc

    if not res or not res.session or not res.user:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    profile = sb.table("profiles").select("*").eq("id", res.user.id).single().execute().data
    if not profile:
        raise HTTPException(status_code=401, detail="User profile not found")

    return {
        "accessToken": res.session.access_token,
        "refreshToken": res.session.refresh_token,
        "user": profile,
    }


@app.post("/v1/chat/ask")
@limiter.limit("20/minute")
async def ask_rule(request: Request, body: ChatAskRequest, user=Depends(get_current_user)):
    sb = get_supabase()
    try:
        provider = get_ai_provider()
        embedder = CloudflareBgeM3Embedder()
        return await answer_railway_rule_question(
            sb=sb,
            question=body.question,
            zone_id=body.zoneId,
            division_id=body.divisionId,
            department_id=body.departmentId,
            preferred_language=body.preferredLanguage,
            history=body.history,
            embedder=embedder,
            ai_provider=provider,
        )
    except HTTPException:
        raise
    except AIProviderError as exc:
        logger.error("Chat AI provider error: %s", sanitize_error_message(exc))
        status = 429 if exc.status_code == 429 else 503
        detail = (
            "AI answer service rate limit reached. Please retry in a moment."
            if status == 429
            else "AI answer generation service is temporarily unavailable."
        )
        raise HTTPException(status_code=status, detail=detail) from exc
    except EmbeddingError as exc:
        logger.error("Chat embedding error: %s", sanitize_error_message(exc))
        raise HTTPException(
            status_code=503,
            detail="Rule search embedding service is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected chat error: %s", sanitize_error_message(exc))
        raise HTTPException(
            status_code=503,
            detail="Unable to process rule query right now. Please try again.",
        ) from exc


@app.get("/v1/admin/documents")
async def list_admin_documents(
    search: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    ingestionStatus: Optional[str] = Query(default=None),
    user=Depends(get_current_user),
):
    require_admin(user)
    sb = get_supabase()
    query = sb.table("documents").select("*").order("created_at", desc=True)
    if status:
        query = query.eq("status", status)
    if ingestionStatus:
        query = query.eq("ingestion_status", ingestionStatus)
    rows = query.execute().data or []

    if search and search.strip():
        needle = search.strip().lower()
        rows = [
            row
            for row in rows
            if needle in str(row.get("title") or "").lower()
            or needle in str(row.get("document_number") or "").lower()
            or needle in str(row.get("issuing_authority") or "").lower()
            or needle in str(row.get("document_type") or "").lower()
        ]
    return [_serialize_admin_document(row) for row in rows]


@app.post("/v1/admin/documents/presign-upload")
async def presign_pdf_upload(body: PresignUploadRequest, user=Depends(get_current_user)):
    require_admin(user)
    key = _build_r2_object_key(
        zone_code=body.zoneCode,
        division_code=body.divisionCode,
        department_code=body.departmentCode,
        file_name=body.fileName,
    )
    r2 = get_r2_client()
    upload_url = r2.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": os.environ["R2_BUCKET_NAME"],
            "Key": key,
            "ContentType": "application/pdf",
        },
        ExpiresIn=900,
    )
    return {"objectKey": key, "presignedPutUrl": upload_url}


@app.post("/v1/admin/documents")
async def register_document(
    body: RegisterDocumentRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
):
    require_admin(user)
    doc_type = body.documentType.upper().strip()
    scope_level = body.scopeLevel.upper().strip()
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported documentType.")
    if scope_level not in ALLOWED_SCOPE_LEVELS:
        raise HTTPException(status_code=400, detail="Unsupported scopeLevel.")

    sb = get_supabase()
    r2 = get_r2_client()

    # Verify PDF exists in private R2 and passes PDF size + magic header validation before indexing
    try:
        pdf_bytes = download_pdf_from_r2(r2, os.environ["R2_BUCKET_NAME"], body.objectKey)
        validate_pdf_bytes(pdf_bytes)
    except PdfPipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Uploaded PDF could not be read from R2 storage.") from exc

    actual_sha = compute_sha256(pdf_bytes)
    authority_rank = body.authorityRank or _default_authority_rank(doc_type, scope_level)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Duplicate-safe / Idempotent upload check by SHA-256 or R2 key
    existing_rows = (
        sb.table("documents")
        .select("*")
        .eq("file_sha256", actual_sha)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not existing_rows:
        existing_rows = (
            sb.table("documents")
            .select("*")
            .eq("r2_object_key", body.objectKey)
            .limit(1)
            .execute()
            .data
            or []
        )

    doc_payload = {
        "title": body.title.strip(),
        "document_number": body.documentNumber.strip() if body.documentNumber else None,
        "document_type": doc_type,
        "issuing_authority": body.issuingAuthority.strip(),
        "authority_rank": authority_rank,
        "r2_object_key": body.objectKey,
        "file_sha256": actual_sha,
        "issue_date": body.issueDate or None,
        "effective_date": body.effectiveDate or None,
        "requires_ocr": body.requiresOcr,
        "ocr_status": "pending" if body.requiresOcr else "not_needed",
        "ingestion_status": "processing",
        "ingestion_error": None,
        "source_type": "r2_upload",
        "uploaded_by": user["id"],
        "updated_at": now_iso,
    }

    if existing_rows:
        document_id = existing_rows[0]["id"]
        saved_doc = sb.table("documents").update(doc_payload).eq("id", document_id).execute().data[0]
    else:
        doc_payload["status"] = "draft"
        saved_doc = sb.table("documents").insert(doc_payload).execute().data[0]
        document_id = saved_doc["id"]

    _upsert_document_scope(
        sb=sb,
        document_id=document_id,
        scope_level=scope_level,
        zone_id=body.zoneId,
        division_id=body.divisionId,
        department_id=body.departmentId,
    )
    _upsert_supersession_link(
        sb=sb,
        amending_document_id=document_id,
        target_document_id=body.supersedesDocumentId,
        effective_date=body.effectiveDate,
        document_number=body.documentNumber,
    )

    if body.runSync:
        await ingest_document_bytes(
            sb=sb,
            document_id=str(document_id),
            pdf_bytes=pdf_bytes,
            force_ocr=body.requiresOcr,
            embedder=CloudflareBgeM3Embedder(),
        )
        saved_doc = sb.table("documents").select("*").eq("id", document_id).single().execute().data
    else:
        background_tasks.add_task(_run_bytes_ingestion_task, str(document_id), pdf_bytes, body.requiresOcr)

    return _serialize_admin_document(saved_doc)


@app.post("/v1/admin/documents/import-drive")
async def import_google_drive_pdf(
    body: ImportDrivePdfRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
):
    require_admin(user)
    doc_type = body.documentType.upper().strip()
    scope_level = body.scopeLevel.upper().strip()
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported documentType.")
    if scope_level not in ALLOWED_SCOPE_LEVELS:
        raise HTTPException(status_code=400, detail="Unsupported scopeLevel.")

    try:
        pdf_bytes, file_name = await download_public_google_drive_pdf(body.driveUrl)
    except PdfPipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Google Drive download failed: {exc.__class__.__name__}") from exc

    sha256 = compute_sha256(pdf_bytes)
    object_key = _build_r2_object_key(
        zone_code=body.zoneCode,
        division_code=body.divisionCode,
        department_code=body.departmentCode,
        file_name=file_name,
        sha_prefix=sha256,
    )

    r2 = get_r2_client()
    upload_pdf_to_r2(r2, os.environ["R2_BUCKET_NAME"], object_key, pdf_bytes)

    sb = get_supabase()
    authority_rank = body.authorityRank or _default_authority_rank(doc_type, scope_level)
    now_iso = datetime.now(timezone.utc).isoformat()

    existing_rows = (
        sb.table("documents")
        .select("*")
        .eq("file_sha256", sha256)
        .limit(1)
        .execute()
        .data
        or []
    )

    doc_payload = {
        "title": body.title.strip(),
        "document_number": body.documentNumber.strip() if body.documentNumber else None,
        "document_type": doc_type,
        "issuing_authority": body.issuingAuthority.strip(),
        "authority_rank": authority_rank,
        "r2_object_key": existing_rows[0]["r2_object_key"] if existing_rows else object_key,
        "file_sha256": sha256,
        "issue_date": body.issueDate or None,
        "effective_date": body.effectiveDate or None,
        "requires_ocr": body.requiresOcr,
        "ocr_status": "pending" if body.requiresOcr else "not_needed",
        "ingestion_status": "processing",
        "ingestion_error": None,
        "source_type": "google_drive",
        "source_url": body.driveUrl.strip(),
        "uploaded_by": user["id"],
        "updated_at": now_iso,
    }

    if existing_rows:
        document_id = existing_rows[0]["id"]
        saved_doc = sb.table("documents").update(doc_payload).eq("id", document_id).execute().data[0]
    else:
        doc_payload["status"] = "draft"
        saved_doc = sb.table("documents").insert(doc_payload).execute().data[0]
        document_id = saved_doc["id"]

    _upsert_document_scope(
        sb=sb,
        document_id=document_id,
        scope_level=scope_level,
        zone_id=body.zoneId,
        division_id=body.divisionId,
        department_id=body.departmentId,
    )
    _upsert_supersession_link(
        sb=sb,
        amending_document_id=document_id,
        target_document_id=body.supersedesDocumentId,
        effective_date=body.effectiveDate,
        document_number=body.documentNumber,
    )

    if body.runSync:
        await ingest_document_bytes(
            sb=sb,
            document_id=str(document_id),
            pdf_bytes=pdf_bytes,
            force_ocr=body.requiresOcr,
            embedder=CloudflareBgeM3Embedder(),
        )
        saved_doc = sb.table("documents").select("*").eq("id", document_id).single().execute().data
    else:
        background_tasks.add_task(_run_bytes_ingestion_task, str(document_id), pdf_bytes, body.requiresOcr)

    return _serialize_admin_document(saved_doc)


@app.post("/v1/admin/documents/{document_id}/reprocess")
async def reprocess_document(
    document_id: str,
    body: ReprocessDocumentRequest,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
):
    require_admin(user)
    sb = get_supabase()
    doc_resp = sb.table("documents").select("*").eq("id", document_id).single().execute()
    doc = doc_resp.data
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    force_ocr = body.forceOcr or bool(doc.get("requires_ocr"))
    updated = (
        sb.table("documents")
        .update(
            {
                "ingestion_status": "processing",
                "ingestion_error": None,
                "ocr_status": "pending" if force_ocr else doc.get("ocr_status", "not_needed"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", document_id)
        .execute()
        .data[0]
    )

    if body.runSync:
        r2 = get_r2_client()
        pdf_bytes = download_pdf_from_r2(r2, os.environ["R2_BUCKET_NAME"], doc["r2_object_key"])
        await ingest_document_bytes(
            sb=sb,
            document_id=document_id,
            pdf_bytes=pdf_bytes,
            force_ocr=force_ocr,
            embedder=CloudflareBgeM3Embedder(),
        )
        updated = sb.table("documents").select("*").eq("id", document_id).single().execute().data
    else:
        background_tasks.add_task(_run_r2_ingestion_task, document_id, doc["r2_object_key"], force_ocr)

    return _serialize_admin_document(updated)


@app.patch("/v1/admin/documents/{document_id}/status")
async def update_document_status(
    document_id: str,
    body: DocumentStatusUpdateRequest,
    user=Depends(get_current_user),
):
    require_admin(user)
    new_status = body.status.lower().strip()
    if new_status not in ALLOWED_DOC_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid document status.")

    sb = get_supabase()
    existing = sb.table("documents").select("*").eq("id", document_id).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")

    if new_status == "published" and existing.get("ingestion_status") != "completed":
        raise HTTPException(
            status_code=400,
            detail="Document cannot be published until PDF ingestion and indexing complete.",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "status": new_status,
        "disabled_reason": body.disabledReason,
        "updated_at": now_iso,
    }
    if new_status == "published":
        payload["published_at"] = now_iso
        payload["reviewed_by"] = user["id"]

    updated = sb.table("documents").update(payload).eq("id", document_id).execute().data
    return _serialize_admin_document(updated[0])
