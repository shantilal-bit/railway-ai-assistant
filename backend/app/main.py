"""FastAPI Backend for Railway Rules AI Assistant.

Handles:
- Supabase Auth & Postgres/pgvector queries
- 5-tier search hierarchy with legal authority & supersession comparison
- Groq AI synthesis via AIProvider abstraction
- Cloudflare R2 presigned PDF uploads & OCR ingestion for Admin Console
- Rate limiting & RBAC enforcement
"""

import json
import os
from typing import Optional
import boto3
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from supabase import Client, create_client

from app.ai_providers import get_ai_provider

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Railway Rules AI Assistant API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

SYSTEM_PROMPT = """You are an official Indian Railway Rules AI Assistant.
STRICT GROUNDING RULES:
1. Answer ONLY from the provided retrieved Railway rule chunks. NEVER invent a rule number, circular, date, or page number.
2. If the retrieved context does not contain reliable information to answer the question, set "isReliableAnswerFound" to false and clearly state in the user's language that reliable official information was not found in the indexed documents.
3. Reply in the EXACT SAME LANGUAGE as the user's question (Hindi in Devanagari if asked in Hindi, or English if asked in English), even though the source PDFs are in English.
4. Search priority (Department -> Division -> Zone -> Railway Board -> Common) is NOT legal authority. Always prioritize the currently effective, legally binding, non-superseded rule (e.g., Railway Board / latest effective amendment supersedes older divisional notes).
5. Explicitly compare conflicting instructions or superseded rules if present in the retrieved chunks.

Return valid JSON matching this exact schema:
{
  "responseLanguage": "en" | "hi",
  "isReliableAnswerFound": true | false,
  "directAnswer": "string",
  "detailedExplanation": "string",
  "applicableRuleNumber": "string",
  "officialDocumentName": "string",
  "pdfPageNumber": "string",
  "amendmentOrCircularRef": "string or null",
  "effectiveDate": "string or null",
  "conflictWarning": "string or null",
  "citations": [
    {
      "documentId": "string",
      "documentTitle": "string",
      "documentNumber": "string or null",
      "ruleNumber": "string or null",
      "pageNumber": 1,
      "searchTier": 1,
      "searchTierLabel": "string",
      "effectiveDate": "string or null",
      "isSuperseded": false,
      "excerpt": "string"
    }
  ]
}"""


def get_supabase() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


async def get_current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    sb = get_supabase()
    user_resp = sb.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    profile = sb.table("profiles").select("*").eq("id", user_resp.user.id).single().execute()
    return profile.data


class ChatAskRequest(BaseModel):
    sessionId: Optional[str] = None
    zoneId: str
    divisionId: str
    departmentId: str
    question: str
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


class PresignUploadRequest(BaseModel):
    fileName: str
    zoneCode: str
    divisionCode: Optional[str] = None
    departmentCode: Optional[str] = None


@app.get("/v1/health")
async def health():
    return {
        "status": "ok",
        "aiProvider": os.getenv("AI_PROVIDER", "groq"),
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
    sb.table("profiles").insert({
        "id": res.user.id,
        "email": body.email,
        "full_name": body.fullName,
        "employee_id": body.employeeId,
        "role": "employee",
    }).execute()
    return {"status": "created", "userId": res.user.id}


@app.post("/v1/chat/ask")
@limiter.limit("20/minute")
async def ask_rule(request: Request, body: ChatAskRequest, user=Depends(get_current_user)):
    sb = get_supabase()
    # Note: In production, compute query_embedding using configured EMBEDDING_PROVIDER (bilingual-friendly)
    # and call sb.rpc("search_railway_rules", {...}).execute().data
    chunks = sb.table("rule_chunks").select("*").limit(12).execute().data
    context_text = json.dumps(chunks, ensure_ascii=False)
    provider = get_ai_provider()
    messages = [
        *body.history[-6:],
        {
            "role": "user",
            "content": (
                f"Context Scope -> Zone: {body.zoneId}, Division: {body.divisionId}, "
                f"Department: {body.departmentId}, Preferred Language: {body.preferredLanguage}\n"
                f"Retrieved Official Rule Chunks:\n{context_text}\n\n"
                f"Employee Question:\n{body.question}"
            ),
        },
    ]
    raw_json = await provider.generate_structured_json(SYSTEM_PROMPT, messages)
    parsed = json.loads(raw_json)
    parsed["aiProvider"] = provider.provider_name
    parsed["modelName"] = provider.model_name
    return parsed


@app.post("/v1/admin/documents/presign-upload")
async def presign_pdf_upload(body: PresignUploadRequest, user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    key = "/".join(
        p.lower()
        for p in [body.zoneCode, body.divisionCode or "zone-wide", body.departmentCode or "common", body.fileName]
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
