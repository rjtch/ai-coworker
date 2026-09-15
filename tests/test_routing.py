"""Graph and state tests."""

from ai_coworker.graph import initial_state
from ai_coworker.mcp.client import ROLE_MCP_ALLOWLIST


def test_chat_only_mcp_allowlist():
    assert set(ROLE_MCP_ALLOWLIST) == {"chat"}
    assert ROLE_MCP_ALLOWLIST["chat"] == set()


def test_initial_state_defaults():
    state = initial_state()
    assert state["messages"] == []
    assert state["last_agent"] == ""
    assert state["thread_summary"] == ""
