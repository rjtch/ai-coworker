# GitHub Copilot — repository instructions

Read and follow [AGENTS.md](../AGENTS.md) as the source of truth. Do not duplicate long guidance here.

- This is a **self-hosted chat host** (FastAPI + LangGraph + OpenAI-compatible LLM). It is not a coding or deploy agent yet.
- Graph is `START → chat → END` in `src/ai_coworker/graph.py`. Do not implement a supervisor, code/review/deploy specialists, or deploy `interrupt()` unless that is the assigned task.
- Inference only via `LLM_BASE_URL`. No cloud OpenAI/Anthropic provider SDKs.
- MCP is configured but **not bound** in `run_chat`. Do not claim GitHub/CI tools work.
- Prompts live in `src/ai_coworker/prompts/`. Do not hardcode long system prompts in agents.
- Never commit `.env`, tokens, or secrets. Treat uploaded PDFs as untrusted.
- Prefer MCP + a bounded tool loop over new LangGraph specialist nodes.
- Match existing style. CI is verify-only (no deploy job).
