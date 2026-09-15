"""Runtime prompt injection tests."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from ai_coworker.api.main import app
from ai_coworker.prompts import get_store, get_text
from ai_coworker.prompts.store import PromptError, PromptStore


@pytest.fixture
def isolated_store(tmp_path: Path):
    """Fresh store with inline manifest defaults."""
    root = tmp_path / "prompts"
    root.mkdir()
    manifest = {
        "version": 1,
        "prompts": {
            "chat.system": {
                "role": "system",
                "description": "test",
                "text": "Default chat prompt.\n",
            },
        },
    }
    (root / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    store = PromptStore(root=root)
    persist = tmp_path / "prompts.json"
    store.configure_persistence(persist)
    return store, persist


def test_runtime_override_takes_precedence(isolated_store):
    store, _ = isolated_store
    assert store.get_text("chat.system") == "Default chat prompt.\n"
    store.set_override("chat.system", "Injected at runtime.")
    assert store.get_text("chat.system") == "Injected at runtime.\n"
    rec = store.get_record("chat.system")
    assert rec.source == "catalog"
    assert rec.updated_at is not None


def test_clear_override_reverts_to_default(isolated_store):
    store, _ = isolated_store
    store.set_override("chat.system", "Temporary.")
    store.clear_override("chat.system")
    rec = store.get_record("chat.system")
    assert rec.source == "catalog"
    assert "Default chat" in rec.text


def test_delete_removes_from_catalog(isolated_store):
    store, _ = isolated_store
    store.delete_prompt("chat.system")
    assert "chat.system" not in store.list_ids()
    with pytest.raises(PromptError):
        store.get_text("chat.system")


def test_reset_restores_deleted_default(isolated_store):
    store, _ = isolated_store
    store.delete_prompt("chat.system")
    store.clear_override("chat.system")
    assert "chat.system" in store.list_ids()
    assert "Default chat" in store.get_text("chat.system")


def test_persistence_survives_restart(isolated_store):
    store, persist = isolated_store
    store.set_override("chat.system", "Persisted override.")
    store2 = PromptStore(root=store._root)
    store2.configure_persistence(persist)
    assert store2.get_text("chat.system") == "Persisted override.\n"


def test_delete_persists(isolated_store):
    store, persist = isolated_store
    store.delete_prompt("chat.system")
    store2 = PromptStore(root=store._root)
    store2.configure_persistence(persist)
    assert "chat.system" not in store2.list_ids()


def test_prompts_api_put_and_get():
    client = TestClient(app)
    store = get_store()
    prompt_id = "chat.system"
    original = store.get_text(prompt_id)

    try:
        put = client.put(
            f"/prompts/{prompt_id}",
            json={"text": "Runtime injected chat persona."},
        )
        assert put.status_code == 200
        assert put.json()["source"] == "catalog"
        assert get_text(prompt_id) == "Runtime injected chat persona.\n"

        reset = client.post(f"/prompts/{prompt_id}/reset")
        assert reset.status_code == 200
        assert "AI Coworker" in reset.json()["text"]
    finally:
        store.clear_override(prompt_id)
        assert store.get_text(prompt_id) == original


def test_prompts_api_delete():
    client = TestClient(app)
    store = get_store()
    prompt_id = "chat.system"
    original = store.get_text(prompt_id)

    try:
        deleted = client.delete(f"/prompts/{prompt_id}")
        assert deleted.status_code == 204
        assert prompt_id not in store.list_ids()

        with pytest.raises(PromptError):
            get_text(prompt_id)

        store.clear_override(prompt_id)
        assert store.get_text(prompt_id) == original
    finally:
        if prompt_id not in store.list_ids():
            store.clear_override(prompt_id)
