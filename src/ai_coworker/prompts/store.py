"""Runtime prompt catalog — persisted JSON store, seeded from manifest.yaml."""

from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from langchain_core.messages import SystemMessage
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent
PromptSource = Literal["catalog"]


class PromptError(LookupError):
    """Unknown prompt id or missing template."""


@dataclass(frozen=True)
class PromptMeta:
    id: str
    role: str
    description: str
    variables: list[str]


@dataclass(frozen=True)
class PromptRecord:
    id: str
    text: str
    source: PromptSource
    role: str
    description: str
    variables: list[str]
    updated_at: str | None = None


class PromptStore:
    """Thread-safe prompt catalog backed by persisted JSON."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or _PROMPTS_ROOT
        self._lock = threading.RLock()
        self._manifest: dict[str, Any] | None = None
        self._catalog: dict[str, dict[str, Any]] | None = None
        self._persist_path: Path | None = None

    def configure_persistence(self, path: str | Path | None) -> None:
        with self._lock:
            self._persist_path = Path(path) if path else None
            if self._persist_path and self._persist_path.is_file():
                self._load_persisted()
            elif self._catalog is None:
                self._catalog = self._seed_catalog_from_manifest()
                self._persist()

    def _ensure_catalog(self) -> None:
        with self._lock:
            if self._catalog is None:
                self._catalog = self._seed_catalog_from_manifest()

    def catalog_version(self) -> int:
        return int(self._read_manifest().get("version", 0))

    def list_ids(self) -> list[str]:
        self._ensure_catalog()
        with self._lock:
            assert self._catalog is not None
            return sorted(self._catalog.keys())

    def get_meta(self, prompt_id: str) -> PromptMeta:
        entry = self._entry(prompt_id)
        return PromptMeta(
            id=prompt_id,
            role=str(entry.get("role", "system")),
            description=str(entry.get("description", "")),
            variables=list(entry.get("variables") or []),
        )

    def get_record(self, prompt_id: str) -> PromptRecord:
        entry = self._entry(prompt_id)
        text = self._normalize_text(str(entry.get("text", "")))
        return PromptRecord(
            id=prompt_id,
            text=text,
            source="catalog",
            role=str(entry.get("role", "system")),
            description=str(entry.get("description", "")),
            variables=list(entry.get("variables") or []),
            updated_at=entry.get("updated_at"),
        )

    def list_records(self) -> list[PromptRecord]:
        return [self.get_record(pid) for pid in self.list_ids()]

    def get_text(self, prompt_id: str) -> str:
        return self.get_record(prompt_id).text

    def get_template(self, prompt_id: str) -> PromptTemplate:
        meta = self.get_meta(prompt_id)
        text = self.get_text(prompt_id)
        if meta.variables:
            return PromptTemplate(input_variables=meta.variables, template=text)
        return PromptTemplate.from_template(text)

    def render(self, prompt_id: str, **variables: Any) -> str:
        return self.get_template(prompt_id).format(**variables)

    def system_message(self, prompt_id: str, **variables: Any) -> SystemMessage:
        text = self.render(prompt_id, **variables) if variables else self.get_text(prompt_id)
        return SystemMessage(content=text.strip())

    def upsert_prompt(
        self,
        prompt_id: str,
        text: str,
        *,
        role: str | None = None,
        description: str | None = None,
        variables: list[str] | None = None,
    ) -> PromptRecord:
        self._ensure_catalog()
        now = datetime.now(UTC).isoformat()
        normalized = self._normalize_text(text)
        with self._lock:
            assert self._catalog is not None
            existing = self._catalog.get(prompt_id, {})
            self._catalog[prompt_id] = {
                "role": role if role is not None else existing.get("role", "system"),
                "description": description
                if description is not None
                else existing.get("description", ""),
                "variables": variables
                if variables is not None
                else list(existing.get("variables") or []),
                "text": normalized,
                "updated_at": now,
            }
            self._persist()
        logger.info("Prompt saved: %s", prompt_id)
        return self.get_record(prompt_id)

    def set_override(self, prompt_id: str, text: str) -> PromptRecord:
        """Backward-compatible alias for upsert on an existing prompt."""
        self._entry(prompt_id)
        return self.upsert_prompt(prompt_id, text)

    def delete_prompt(self, prompt_id: str) -> None:
        """Remove a prompt from the catalog entirely."""
        self._ensure_catalog()
        with self._lock:
            assert self._catalog is not None
            if prompt_id not in self._catalog:
                raise PromptError(f"Unknown prompt id: {prompt_id!r}")
            del self._catalog[prompt_id]
            self._persist()
        logger.info("Prompt deleted: %s", prompt_id)

    def clear_override(self, prompt_id: str) -> PromptRecord:
        """Reset a prompt to the bundled manifest default."""
        defaults = self._seed_catalog_from_manifest()
        if prompt_id not in defaults:
            raise PromptError(f"Unknown prompt id: {prompt_id!r}")
        self._ensure_catalog()
        with self._lock:
            assert self._catalog is not None
            self._catalog[prompt_id] = deepcopy(defaults[prompt_id])
            self._persist()
        logger.info("Prompt reset to default: %s", prompt_id)
        return self.get_record(prompt_id)

    def restore_prompt(self, prompt_id: str) -> PromptRecord:
        """Alias for reset — re-seed from manifest default."""
        return self.clear_override(prompt_id)

    def clear_all_overrides(self) -> int:
        with self._lock:
            count = len(self._catalog or {})
            self._catalog = self._seed_catalog_from_manifest()
            self._persist()
        logger.info("Reset %d prompts to manifest defaults", count)
        return count

    def reload_files(self) -> None:
        """Re-read manifest defaults into the in-memory catalog (keeps unsaved edits lost)."""
        with self._lock:
            self._manifest = None
            self._catalog = self._seed_catalog_from_manifest()
            self._persist()

    def _read_manifest(self) -> dict[str, Any]:
        with self._lock:
            if self._manifest is None:
                path = self._root / "manifest.yaml"
                with path.open(encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if not isinstance(data, dict) or "prompts" not in data:
                    raise PromptError("Invalid prompts/manifest.yaml")
                self._manifest = data
            return self._manifest

    def _seed_catalog_from_manifest(self) -> dict[str, dict[str, Any]]:
        catalog: dict[str, dict[str, Any]] = {}
        for prompt_id, entry in self._read_manifest()["prompts"].items():
            if not isinstance(entry, dict):
                continue
            text = entry.get("text")
            if text is None:
                raise PromptError(
                    f"Prompt {prompt_id!r} has no inline text in manifest.yaml"
                )
            catalog[prompt_id] = {
                "role": str(entry.get("role", "system")),
                "description": str(entry.get("description", "")),
                "variables": list(entry.get("variables") or []),
                "text": self._normalize_text(str(text)),
            }
        return catalog

    def _entry(self, prompt_id: str) -> dict[str, Any]:
        self._ensure_catalog()
        with self._lock:
            assert self._catalog is not None
            entry = self._catalog.get(prompt_id)
        if not entry:
            raise PromptError(f"Unknown prompt id: {prompt_id!r}")
        return entry

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.strip() + "\n"

    def _load_persisted(self) -> None:
        if not self._persist_path or not self._persist_path.is_file():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            prompts = data.get("prompts")
            if isinstance(prompts, dict):
                self._catalog = {
                    k: v for k, v in prompts.items() if isinstance(v, dict) and "text" in v
                }
                logger.info("Loaded %d prompts from %s", len(self._catalog), self._persist_path)
                return

            # Migrate legacy override/tombstone format.
            overrides = data.get("overrides") or {}
            deleted = data.get("deleted") or {}
            if isinstance(overrides, dict) or isinstance(deleted, dict):
                catalog = self._seed_catalog_from_manifest()
                if isinstance(overrides, dict):
                    for pid, override in overrides.items():
                        if pid in catalog and isinstance(override, dict) and "text" in override:
                            catalog[pid]["text"] = self._normalize_text(override["text"])
                            catalog[pid]["updated_at"] = override.get("updated_at")
                if isinstance(deleted, dict):
                    for pid in deleted:
                        catalog.pop(pid, None)
                self._catalog = catalog
                self._persist()
                logger.info("Migrated legacy prompt store to catalog format")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load prompts from %s: %s", self._persist_path, exc)
            self._catalog = self._seed_catalog_from_manifest()

    def _persist(self) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.catalog_version(),
            "prompts": self._catalog,
        }
        tmp = self._persist_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._persist_path)


# Process-wide singleton used by loader + API.
_store = PromptStore()


def get_store() -> PromptStore:
    return _store
