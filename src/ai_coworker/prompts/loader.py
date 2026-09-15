"""Load prompts via the runtime PromptStore."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.prompts import PromptTemplate

from ai_coworker.prompts.store import PromptError, get_store

__all__ = [
    "PromptError",
    "catalog_version",
    "clear_prompt_cache",
    "get_template",
    "get_text",
    "init_prompt_store",
    "list_prompt_ids",
    "render",
    "system_message",
]


def init_prompt_store(persist_path: str | None = None) -> None:
    """Call once at API startup to load persisted overrides."""
    get_store().configure_persistence(persist_path)


def catalog_version() -> int:
    return get_store().catalog_version()


def list_prompt_ids() -> list[str]:
    return get_store().list_ids()


def get_text(prompt_id: str) -> str:
    return get_store().get_text(prompt_id)


def get_template(prompt_id: str) -> PromptTemplate:
    return get_store().get_template(prompt_id)


def render(prompt_id: str, **variables: Any) -> str:
    return get_store().render(prompt_id, **variables)


def system_message(prompt_id: str, **variables: Any) -> SystemMessage:
    return get_store().system_message(prompt_id, **variables)


def clear_prompt_cache() -> None:
    """Reload file defaults from disk (overrides are kept)."""
    get_store().reload_files()
