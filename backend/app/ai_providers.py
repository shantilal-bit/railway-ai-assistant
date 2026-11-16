"""AI Provider abstraction with Groq as the primary active provider."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import json
import logging
import os
import re
import httpx

logger = logging.getLogger(__name__)

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GROQ_MAX_TOKENS = 2200
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


class AIProviderError(RuntimeError):
    """Sanitized exception raised when an upstream AI provider call fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def _sanitize_provider_text(text: str, max_len: int = 240) -> str:
    cleaned = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"(key|token|secret|password)=[^&\s]+", r"\1=[REDACTED]", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()[:max_len]


def strip_json_markdown_fences(raw_text: str) -> str:
    """Safely extracts a JSON object string even if wrapped in ```json ... ``` markdown fences."""
    cleaned = (raw_text or "").strip()
    if not cleaned:
        return ""

    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace : last_brace + 1].strip()
    return cleaned


def _extract_groq_error_details(resp: httpx.Response) -> tuple[str | None, str | None, str]:
    err_type = None
    err_code = None
    err_msg = f"HTTP {resp.status_code}"
    try:
        body = resp.json()
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            err_obj = body["error"]
            err_type = str(err_obj.get("type") or "") or None
            err_code = str(err_obj.get("code") or "") or None
            if err_obj.get("message"):
                err_msg = _sanitize_provider_text(str(err_obj["message"]))
    except Exception:
        pass
    return err_type, err_code, err_msg


class AIProvider(ABC):
    provider_name: str
    model_name: str

    @abstractmethod
    async def generate_structured_json(self, system_prompt: str, messages: list[dict]) -> str:
        raise NotImplementedError


class GroqProvider(AIProvider):
    def __init__(self, max_retries: int = 2) -> None:
        self.provider_name = "groq"
        self.model_name = os.getenv("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL
        self.api_key = os.environ["GROQ_API_KEY"].strip()
        raw_max_tokens = os.getenv("GROQ_MAX_TOKENS", str(DEFAULT_GROQ_MAX_TOKENS)).strip()
        try:
            self.max_tokens = max(512, min(int(raw_max_tokens), 4096))
        except ValueError:
            self.max_tokens = DEFAULT_GROQ_MAX_TOKENS
        self.max_retries = max(1, max_retries)

    async def generate_structured_json(self, system_prompt: str, messages: list[dict]) -> str:
        payload = {
            "model": self.model_name,
            "temperature": 0.15,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }

        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=45.0) as client:
            for attempt in range(1, self.max_retries + 2):
                try:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )

                    if resp.status_code in TRANSIENT_HTTP_STATUSES and attempt <= self.max_retries:
                        await asyncio.sleep(min(4.0, 0.75 * attempt))
                        continue

                    if resp.status_code >= 400:
                        err_type, err_code, err_msg = _extract_groq_error_details(resp)
                        logger.error(
                            "Groq API error status=%s model=%s type=%s code=%s message=%s",
                            resp.status_code,
                            self.model_name,
                            err_type,
                            err_code,
                            err_msg,
                        )
                        # Retry once without strict json_object if json_validate_failed occurred
                        if (
                            resp.status_code == 400
                            and err_code == "json_validate_failed"
                            and attempt == 1
                            and "response_format" in payload
                        ):
                            payload = {k: v for k, v in payload.items() if k != "response_format"}
                            continue

                        raise AIProviderError(
                            f"Groq API returned HTTP {resp.status_code} ({err_code or err_type or 'error'}): {err_msg}",
                            status_code=resp.status_code,
                            error_code=err_code,
                        )

                    data = resp.json()
                    choices = data.get("choices") if isinstance(data, dict) else None
                    if not isinstance(choices, list) or not choices:
                        raise AIProviderError("Groq API returned no completion choices.", status_code=502)

                    content = (choices[0].get("message") or {}).get("content") or ""
                    cleaned = strip_json_markdown_fences(str(content))
                    try:
                        parsed = json.loads(cleaned)
                        if not isinstance(parsed, dict):
                            raise ValueError("Top-level JSON is not an object.")
                        return json.dumps(parsed, ensure_ascii=False)
                    except (json.JSONDecodeError, ValueError) as parse_exc:
                        last_exc = parse_exc
                        logger.warning("Groq returned non-JSON output on attempt %s", attempt)
                        if attempt <= self.max_retries:
                            await asyncio.sleep(0.5)
                            continue
                        raise AIProviderError(
                            "AI model returned malformed JSON output.",
                            status_code=502,
                            error_code="invalid_json_output",
                        ) from parse_exc

                except AIProviderError:
                    raise
                except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as net_exc:
                    last_exc = net_exc
                    logger.warning("Groq network error on attempt %s: %s", attempt, net_exc.__class__.__name__)
                    if attempt <= self.max_retries:
                        await asyncio.sleep(min(4.0, 0.75 * attempt))
                        continue
                    raise AIProviderError(
                        f"Groq network timeout/error ({net_exc.__class__.__name__}).",
                        status_code=504,
                        error_code="network_error",
                    ) from net_exc

        raise AIProviderError(f"Groq failed after retries: {last_exc}", status_code=502)


def get_ai_provider() -> AIProvider:
    selected = os.getenv("AI_PROVIDER", "groq").lower().strip()
    if selected != "groq":
        raise ValueError(f"Unsupported AI_PROVIDER '{selected}'. Only 'groq' is currently enabled.")
    return GroqProvider()

