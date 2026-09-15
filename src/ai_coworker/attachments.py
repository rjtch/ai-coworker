"""Parse user attachments (PDF, PNG, JPEG) into LangChain message content."""

from __future__ import annotations

import base64
import binascii
import io
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator, model_validator

AttachmentKind = Literal["pdf", "image"]

ALLOWED_MIME: dict[str, AttachmentKind] = {
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
}


class AttachmentInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=128)
    data: str = Field(min_length=1, description="Base64-encoded file bytes")

    @field_validator("mime_type")
    @classmethod
    def normalize_mime(cls, value: str) -> str:
        mime = value.strip().lower()
        if mime == "image/jpg":
            return "image/jpeg"
        return mime

    @field_validator("data")
    @classmethod
    def strip_data_url(cls, value: str) -> str:
        raw = value.strip()
        if raw.startswith("data:"):
            _, _, raw = raw.partition(",")
        return re.sub(r"\s+", "", raw)


class ChatPayload(BaseModel):
    message: str = ""
    attachments: list[AttachmentInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_content(self) -> ChatPayload:
        if not self.message.strip() and not self.attachments:
            raise ValueError("message or attachments required")
        return self


class AttachmentError(ValueError):
    """Invalid or unsupported attachment."""


def build_human_message(
    message: str,
    attachments: list[AttachmentInput],
    *,
    max_bytes: int,
    max_count: int,
    max_pdf_chars: int = 12_000,
) -> HumanMessage:
    if len(attachments) > max_count:
        raise AttachmentError(f"At most {max_count} attachments per message")

    blocks: list[str | dict[str, Any]] = []
    text = message.strip()
    if text:
        blocks.append({"type": "text", "text": text})

    for attachment in attachments:
        kind = ALLOWED_MIME.get(attachment.mime_type)
        if kind is None:
            allowed = ", ".join(sorted(ALLOWED_MIME))
            raise AttachmentError(
                f"Unsupported file type {attachment.mime_type!r} for {attachment.name!r}. "
                f"Allowed: {allowed}"
            )

        try:
            raw = base64.b64decode(attachment.data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AttachmentError(f"Invalid base64 for {attachment.name!r}") from exc

        if len(raw) > max_bytes:
            raise AttachmentError(
                f"{attachment.name!r} exceeds max size ({max_bytes // (1024 * 1024)} MB)"
            )

        if kind == "pdf":
            pdf_text = _truncate_text(_extract_pdf_text(raw), max_pdf_chars)
            blocks.append(
                {
                    "type": "text",
                    "text": _format_pdf_text(attachment.name, pdf_text),
                }
            )
        else:
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{attachment.mime_type};base64,{attachment.data}",
                    },
                }
            )

    if not blocks:
        return HumanMessage(content="")
    if len(blocks) == 1 and isinstance(blocks[0], dict) and blocks[0].get("type") == "text":
        return HumanMessage(content=str(blocks[0]["text"]))
    return HumanMessage(content=blocks)


def message_has_images(message: HumanMessage) -> bool:
    content = message.content
    if not isinstance(content, list):
        return False
    return any(isinstance(block, dict) and block.get("type") == "image_url" for block in content)


def history_has_images(messages: list) -> bool:
    for msg in messages:
        if isinstance(msg, HumanMessage) and message_has_images(msg):
            return True
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "image_url" for b in content):
                return True
    return False


def summarize_attachments(attachments: list[AttachmentInput]) -> str:
    if not attachments:
        return ""
    names = ", ".join(a.name for a in attachments)
    return f"[attachments: {names}]"


def _extract_pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    parts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if page_text:
            parts.append(f"--- Page {index} ---\n{page_text}")
    if not parts:
        return "(No extractable text — the PDF may be scanned images only.)"
    return "\n\n".join(parts)


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + "\n\n… [truncated — PDF too long for model context; ask about a specific section]"
    )


def _format_pdf_text(name: str, body: str) -> str:
    return f"\n\n--- PDF: {name} ---\n{body}\n--- end PDF ---\n"
