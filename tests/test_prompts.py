"""Prompt catalog loader tests."""

from ai_coworker.prompts import (
    catalog_version,
    get_text,
    list_prompt_ids,
    system_message,
)


def test_manifest_lists_chat_prompt():
    ids = list_prompt_ids()
    assert "chat.system" in ids
    assert catalog_version() >= 3


def test_chat_system_prompt_loads():
    text = get_text("chat.system")
    assert "AI Coworker" in text
    msg = system_message("chat.system")
    assert "AI Coworker" in msg.content
