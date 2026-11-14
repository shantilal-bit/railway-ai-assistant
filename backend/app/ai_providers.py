"""AI Provider abstraction with Groq as the primary active provider."""

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


def get_ai_provider() -> AIProvider:
    selected = os.getenv("AI_PROVIDER", "groq").lower().strip()
    if selected != "groq":
        raise ValueError(f"Unsupported AI_PROVIDER '{selected}'. Only 'groq' is currently enabled.")
    return GroqProvider()
