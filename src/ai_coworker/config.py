from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Self-hosted OpenAI-compatible endpoint (vLLM, Ollama, TGI, llama.cpp, etc.)
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "not-needed"
    # MiniCPM-V 4.6 (OpenBMB) — Chinese multimodal; best lightweight fit for CPU-only hosts
    llm_model: str = "openbmb/minicpm-v4.6"
    llm_vision_model: str | None = None  # optional override; leave empty to use LLM_MODEL
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 240.0
    # Ollama default num_ctx is often 4096; raise it so PDFs/images fit
    llm_num_ctx: int = 16384

    chat_max_attachments: int = 5
    chat_max_attachment_bytes: int = 10 * 1024 * 1024
    chat_max_pdf_chars: int = 12_000  # ~3–4k tokens; avoids blowing context

    # Optional local tracing only — leave off unless you run your own LangSmith/OTEL stack
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "ai-coworker"

    database_url: str | None = None

    mcp_github_url: str | None = None
    mcp_github_token: str | None = None
    mcp_ci_url: str | None = None
    mcp_ci_token: str | None = None

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Runtime prompt injection (optional)
    prompts_persist_path: str | None = None  # e.g. /data/prompts.json
    prompts_admin_token: str | None = None  # required for PUT/DELETE if set


@lru_cache
def get_settings() -> Settings:
    return Settings()
