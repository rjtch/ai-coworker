"""Chat node model selection and WebSocket cancel."""

import asyncio
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from ai_coworker.agents.chat import run_chat
from ai_coworker.api import main
from ai_coworker.config import Settings
from ai_coworker.graph import build_graph, initial_state


class RecordingChatModel(BaseChatModel):
    """Fake LLM that records calls and optionally sleeps before replying."""

    label: str = "fake"
    delay: float = 0.0
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.label))])


def _image_message() -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]
    )


async def test_text_only_turn_uses_text_model():
    text_llm = RecordingChatModel(label="text")
    vision_llm = RecordingChatModel(label="vision")
    state = {**initial_state(), "messages": [HumanMessage(content="Hi")]}

    result = await run_chat(state, text_llm, vision_llm=vision_llm)

    assert result["messages"][0].content == "text"
    assert (text_llm.calls, vision_llm.calls) == (1, 0)


async def test_image_turn_uses_vision_model():
    text_llm = RecordingChatModel(label="text")
    vision_llm = RecordingChatModel(label="vision")
    state = {**initial_state(), "messages": [_image_message()]}

    result = await run_chat(state, text_llm, vision_llm=vision_llm)

    assert result["messages"][0].content == "vision"
    assert (text_llm.calls, vision_llm.calls) == (0, 1)


def test_websocket_cancel_stops_running_chat(monkeypatch):
    slow_llm = RecordingChatModel(label="late", delay=5.0)
    graph = asyncio.run(build_graph(Settings(), llm=slow_llm))
    monkeypatch.setattr(main, "graph", graph)

    with TestClient(main.app).websocket_connect("/ws/chat") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "chat", "message": "Hello"})
        assert ws.receive_json()["type"] == "thread"

        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"

        ws.send_json({"type": "chat", "message": "Again"})
        assert ws.receive_json() == {"type": "error", "message": "Busy — cancel first"}

        ws.send_json({"type": "cancel"})
        assert ws.receive_json()["type"] == "cancelled"
