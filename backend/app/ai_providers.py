"""Provider-agnostic LLM abstraction supporting Groq (initial), OpenAI, and Gemini."""

from abc import ABC, abstractmethod
import os
import httpx


class AIProvider(ABC):
    provider_name: str
    model_name: str

    @abstractmethod
    async def generate_structured_json(self, system_prompt: str, messages: list[dict]) -> str:
        raise NotImplementedError


class GroqProvider(AIProvider):
    def __init__(self) -> None:
        self.provider_name = "groq"
        self.model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.api_key = os.environ["GROQ_API_KEY"]

    async def generate_structured_json(self, system_prompt: str, messages: list[dict]) -> str:
        payload = {
            "model": self.model_name,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


class OpenAIProvider(AIProvider):
    def __init__(self) -> None:
        self.provider_name = "openai"
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = os.environ["OPENAI_API_KEY"]

    async def generate_structured_json(self, system_prompt: str, messages: list[dict]) -> str:
        payload = {
            "model": self.model_name,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


class GeminiProvider(AIProvider):
    def __init__(self) -> None:
        self.provider_name = "gemini"
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.api_key = os.environ["GEMINI_API_KEY"]

    async def generate_structured_json(self, system_prompt: str, messages: list[dict]) -> str:
        contents = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def get_ai_provider() -> AIProvider:
    selected = os.getenv("AI_PROVIDER", "groq").lower().strip()
    if selected == "openai":
        return OpenAIProvider()
    if selected == "gemini":
        return GeminiProvider()
    return GroqProvider()
