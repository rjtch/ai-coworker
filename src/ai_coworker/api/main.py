"""HTTP + WebSocket API — chat streaming and cancel."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field, model_validator
from starlette.websockets import WebSocketState

from ai_coworker.api.prompts import router as prompts_router
from ai_coworker.attachments import (
    AttachmentError,
    AttachmentInput,
    build_human_message,
)
from ai_coworker.config import Settings, get_settings
from ai_coworker.graph import build_graph, initial_state, open_checkpointer
from ai_coworker.prompts import init_prompt_store

logger = logging.getLogger(__name__)

graph: Any = None

_NODE_NAMES = {"chat"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global graph
    settings = get_settings()
    init_prompt_store(settings.prompts_persist_path)
    if settings.langchain_tracing_v2 and settings.langchain_api_key:
        import os

        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langchain_api_key)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)
    async with open_checkpointer(settings) as checkpointer:
        graph = await build_graph(settings, checkpointer=checkpointer)
        logger.info("Graph compiled")
        yield
    graph = None


app = FastAPI(
    title="AI Coworker",
    version="0.1.0",
    description="Chat agent (LangGraph + MCP)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3080",
        "http://127.0.0.1:3080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prompts_router)


class ChatRequest(BaseModel):
    message: str = ""
    attachments: list[AttachmentInput] = Field(default_factory=list)
    thread_id: str | None = None

    @model_validator(mode="after")
    def require_content(self) -> ChatRequest:
        if not self.message.strip() and not self.attachments:
            raise ValueError("message or attachments required")
        return self


class ChatResponse(BaseModel):
    thread_id: str
    last_agent: str | None
    reply: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    if graph is None:
        raise HTTPException(503, "Graph not ready")

    settings = get_settings()
    try:
        human = _human_message_from_payload(body, settings)
    except AttachmentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    thread_id = body.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    inputs: dict[str, Any] = {"messages": [human]}
    if body.thread_id is None:
        inputs = {**initial_state(), **inputs}

    result = await graph.ainvoke(inputs, config=config)
    return _to_response(thread_id, result)


@app.post("/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    """SSE fallback — prefer WebSocket `/ws/chat` for interactive sessions."""
    if graph is None:
        raise HTTPException(503, "Graph not ready")

    thread_id = body.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    try:
        inputs = _build_inputs(body.message, body.thread_id, body.attachments)
    except AttachmentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    async def event_gen():
        async for event in _stream_graph_events(thread_id, config, inputs):
            yield _sse(event)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket) -> None:
    """Primary chat transport: bidirectional JSON frames over WebSocket."""
    await ws.accept()
    await _ws_send(ws, {"type": "ready"})
    run_task: asyncio.Task | None = None

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _ws_send(ws, {"type": "error", "message": "Invalid JSON"})
                continue

            kind = msg.get("type")
            if kind == "ping":
                await _ws_send(ws, {"type": "pong"})
                continue

            if kind == "cancel":
                if run_task and not run_task.done():
                    run_task.cancel()
                    await _ws_send(ws, {"type": "cancelled"})
                continue

            if kind != "chat":
                await _ws_send(ws, {"type": "error", "message": f"Unknown type: {kind}"})
                continue

            if graph is None:
                await _ws_send(ws, {"type": "error", "message": "Graph not ready"})
                continue
            if run_task and not run_task.done():
                await _ws_send(ws, {"type": "error", "message": "Busy — cancel first"})
                continue

            message = str(msg.get("message") or "").strip()
            raw_attachments = msg.get("attachments") or []
            if not message and not raw_attachments:
                await _ws_send(ws, {"type": "error", "message": "message or attachments required"})
                continue

            prior = msg.get("thread_id")
            thread_id = str(prior) if prior else str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            try:
                attachments = [AttachmentInput.model_validate(a) for a in raw_attachments]
                inputs = _build_inputs(message, str(prior) if prior else None, attachments)
            except (AttachmentError, ValueError) as exc:
                await _ws_send(ws, {"type": "error", "message": str(exc)})
                continue

            async def _run_chat(
                stream_thread_id: str = thread_id,
                stream_config: dict[str, Any] = config,
                stream_inputs: dict[str, Any] = inputs,
            ) -> None:
                async for event in _stream_graph_events(
                    stream_thread_id, stream_config, stream_inputs
                ):
                    await _ws_send(ws, event)

            run_task = asyncio.create_task(_run_chat())
            try:
                await run_task
            except asyncio.CancelledError:
                await _ws_send(ws, {"type": "cancelled"})
            except Exception as exc:  # noqa: BLE001
                logger.exception("ws chat failed")
                await _ws_send(ws, {"type": "error", "message": str(exc)})

    except WebSocketDisconnect:
        if run_task and not run_task.done():
            run_task.cancel()
        logger.info("WebSocket disconnected")


def _human_message_from_payload(body: ChatRequest, settings: Settings) -> HumanMessage:
    return build_human_message(
        body.message,
        body.attachments,
        max_bytes=settings.chat_max_attachment_bytes,
        max_count=settings.chat_max_attachments,
        max_pdf_chars=settings.chat_max_pdf_chars,
    )


def _build_inputs(
    message: str,
    thread_id: str | None,
    attachments: list[AttachmentInput] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    human = build_human_message(
        message,
        attachments or [],
        max_bytes=settings.chat_max_attachment_bytes,
        max_count=settings.chat_max_attachments,
        max_pdf_chars=settings.chat_max_pdf_chars,
    )
    inputs: dict[str, Any] = {"messages": [human]}
    if thread_id is None:
        inputs = {**initial_state(), **inputs}
    return inputs


async def _stream_graph_events(
    thread_id: str,
    config: dict[str, Any],
    inputs: dict[str, Any],
):
    yield {"type": "thread", "thread_id": thread_id}
    async for event in graph.astream_events(inputs, config=config, version="v2"):
        kind = event.get("event")
        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            text = getattr(chunk, "content", None) if chunk is not None else None
            if isinstance(text, list):
                text = "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in text
                )
            if text:
                yield {"type": "token", "text": str(text)}
        elif kind == "on_chain_end" and event.get("name") in _NODE_NAMES:
            yield {"type": "node_end", "node": event.get("name")}

    snap = await graph.aget_state(config)
    yield {
        "type": "done",
        "thread_id": thread_id,
        "interrupted": False,
        "values": _public_values(snap.values if snap else {}),
        "interrupt_payload": None,
    }


async def _ws_send(ws: WebSocket, payload: dict[str, Any]) -> None:
    if ws.client_state != WebSocketState.CONNECTED:
        return
    await ws.send_text(json.dumps(payload, default=str))


def _to_response(thread_id: str, result: dict[str, Any]) -> ChatResponse:
    reply = _latest_ai_text(result.get("messages") or [])
    return ChatResponse(
        thread_id=thread_id,
        last_agent=result.get("last_agent"),
        reply=reply,
    )


def _latest_ai_text(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
            return str(msg.content)
    return ""


def _public_values(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "last_agent": values.get("last_agent"),
    }


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, default=str)}\n\n"


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "ai_coworker.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
