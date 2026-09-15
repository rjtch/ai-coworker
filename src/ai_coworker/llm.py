from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ai_coworker.config import Settings


def build_llm(settings: Settings, *, model: str | None = None) -> BaseChatModel:
    """Talk only to a self-hosted OpenAI-compatible server (no cloud AI providers)."""
    if not settings.llm_base_url:
        raise ValueError("LLM_BASE_URL is required (e.g. http://vllm:8000/v1 or http://ollama:11434/v1)")
    model_name = model or settings.llm_model
    if not model_name:
        raise ValueError("LLM_MODEL is required (served model name on your inference server)")

    # Ollama reads options.num_ctx; without this it often keeps a 4096-token window.
    extra_body: dict = {}
    if settings.llm_num_ctx and settings.llm_num_ctx > 0:
        extra_body["options"] = {"num_ctx": settings.llm_num_ctx}

    return ChatOpenAI(
        model=model_name,
        api_key=settings.llm_api_key or "not-needed",
        base_url=settings.llm_base_url.rstrip("/"),
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        streaming=True,
        extra_body=extra_body or None,
    )
