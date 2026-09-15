"""Attachment parsing tests."""

import base64

import pytest
from langchain_core.messages import HumanMessage
from pypdf import PdfWriter

from ai_coworker.attachments import (
    AttachmentError,
    AttachmentInput,
    build_human_message,
    history_has_images,
    message_has_images,
)


def _pdf_bytes(text: str = "Hello PDF") -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # pypdf blank pages have no text; use a minimal PDF with text via reportlab alternative
    # Instead write a simple PDF manually - actually use add_blank_page and inject via merge
    # Simplest: create empty pdf and test error path, or use pypdf to read existing
    from io import BytesIO

    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_build_human_message_with_pdf():
    # Minimal valid PDF (empty page) — extraction returns no-text message
    raw = _pdf_bytes()
    attachment = AttachmentInput(
        name="notes.pdf",
        mime_type="application/pdf",
        data=base64.b64encode(raw).decode("ascii"),
    )
    msg = build_human_message(
        "Summarize this",
        [attachment],
        max_bytes=1024 * 1024,
        max_count=5,
    )
    assert isinstance(msg, HumanMessage)
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    assert "Summarize this" in text
    assert "notes.pdf" in text


def test_build_human_message_with_image():
    # 1x1 PNG
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
        "AAAABJRU5ErkJggg=="
    )
    attachment = AttachmentInput(
        name="dot.png",
        mime_type="image/png",
        data=png_b64,
    )
    msg = build_human_message("", [attachment], max_bytes=1024 * 1024, max_count=5)
    assert isinstance(msg.content, list)
    assert message_has_images(msg)
    assert history_has_images([msg])


def test_rejects_unsupported_mime():
    attachment = AttachmentInput(
        name="evil.exe",
        mime_type="application/octet-stream",
        data=base64.b64encode(b"x").decode("ascii"),
    )
    with pytest.raises(AttachmentError, match="Unsupported"):
        build_human_message("hi", [attachment], max_bytes=1024, max_count=5)


def test_rejects_oversized_file():
    attachment = AttachmentInput(
        name="big.png",
        mime_type="image/png",
        data=base64.b64encode(b"x" * 20).decode("ascii"),
    )
    with pytest.raises(AttachmentError, match="exceeds max size"):
        build_human_message("hi", [attachment], max_bytes=10, max_count=5)


def test_pdf_text_is_truncated():
    from ai_coworker.attachments import _truncate_text

    long = "a" * 500
    out = _truncate_text(long, 100)
    assert len(out) < 200
    assert "truncated" in out
    assert _truncate_text("short", 100) == "short"
