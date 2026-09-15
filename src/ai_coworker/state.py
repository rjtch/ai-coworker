from typing import Annotated

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class CoworkerState(TypedDict):
    """Shared graph state — typed, checkpointed between turns."""

    messages: Annotated[list, add_messages]
    thread_summary: str
    last_agent: str
    error: str | None
