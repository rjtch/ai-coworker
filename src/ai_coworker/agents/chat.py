from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool

from ai_coworker.prompts import system_message
from ai_coworker.state import CoworkerState


async def run_chat(
    state: CoworkerState,
    llm: BaseChatModel,
    tools: list[BaseTool] | None = None,
    *,
    vision_llm: BaseChatModel | None = None,
) -> dict:
    _ = tools
    history = _conversation_window(state, limit=8)
    if not history:
        history = [HumanMessage(content="Hello")]

    active_llm = vision_llm or llm
    chat_llm = active_llm.bind(temperature=0.55) if hasattr(active_llm, "bind") else active_llm
    response = await chat_llm.ainvoke([system_message("chat.system"), *history])
    text = _as_text(response.content)
    return {
        "messages": [AIMessage(content=text)],
        "last_agent": "chat",
        "thread_summary": text[:500],
    }


def _conversation_window(state: CoworkerState, limit: int = 8) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for msg in state.get("messages") or []:
        role = getattr(msg, "type", None)
        if role in ("human", "ai") or isinstance(msg, (HumanMessage, AIMessage)):
            if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                out.append(msg)
                continue
            content = _as_text(getattr(msg, "content", ""))
            if content.startswith("[routed →"):
                continue
            out.append(msg)
    return out[-limit:]


def _as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, dict) and block.get("type") == "image_url":
                parts.append("[image]")
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content or "")
