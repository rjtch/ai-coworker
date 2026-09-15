"""LangGraph chat agent."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from ai_coworker.agents.chat import run_chat
from ai_coworker.config import Settings, get_settings
from ai_coworker.llm import build_llm
from ai_coworker.mcp.client import load_tools_for_role
from ai_coworker.state import CoworkerState

logger = logging.getLogger(__name__)


async def build_graph(
    settings: Settings | None = None,
    llm: BaseChatModel | None = None,
    checkpointer: Any | None = None,
):
    settings = settings or get_settings()
    llm = llm or build_llm(settings)
    vision_llm: BaseChatModel | None = None
    if settings.llm_vision_model and settings.llm_vision_model != settings.llm_model:
        vision_llm = build_llm(settings, model=settings.llm_vision_model)
    tools = await load_tools_for_role("chat", settings)

    async def chat_node(state: CoworkerState) -> dict:
        return await run_chat(state, llm, tools, vision_llm=vision_llm)

    builder = StateGraph(CoworkerState)
    builder.add_node("chat", chat_node)
    builder.add_edge(START, "chat")
    builder.add_edge("chat", END)

    if checkpointer is None:
        checkpointer = MemorySaver()
        logger.info("Using MemorySaver checkpointer")

    return builder.compile(checkpointer=checkpointer)


@asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncIterator[Any]:
    """Yield a durable Postgres saver when DATABASE_URL is set; else MemorySaver."""
    if not settings.database_url:
        yield MemorySaver()
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        await saver.setup()
        logger.info("Using Postgres checkpointer")
        yield saver


def initial_state() -> CoworkerState:
    return {
        "messages": [],
        "thread_summary": "",
        "last_agent": "",
        "error": None,
    }
