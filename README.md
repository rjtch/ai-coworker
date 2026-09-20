# AI Coworker (WIP)

Self-hosted **chat** for a local OpenAI-compatible LLM (Ollama or vLLM). FastAPI + LangGraph, optional Postgres threads, PDF/PNG/JPEG attachments, and an editable prompt catalog.

It is **not** a multi-agent coding or deploy bot. The graph is `START → chat → END`. MCP GitHub/CI URLs can be set in `.env`, but tools are not bound to the model yet.

Agent instructions: **[AGENTS.md](AGENTS.md)**.

## Quick start (Docker / Podman)

```bash
cp .env.example .env
podman compose up -d --build
```

- **UI:** http://localhost:3080
- **API:** http://localhost:8000

### Frontend only (dev)

```bash
cd frontend && npm install && npm run dev
# → http://localhost:3000 (proxies /api → :8000)
```

### Local uv (LLM already running)

```bash
uv sync --extra dev
# LLM_BASE_URL=http://127.0.0.1:11434/v1  LLM_MODEL=openbmb/minicpm-v4.6
uv run uvicorn ai_coworker.api.main:app --host 0.0.0.0 --port 8000 --app-dir src
```

GPU Compose profile (vLLM):

```bash
LLM_BASE_URL=http://vllm:8000/v1 \
LLM_MODEL=Qwen/Qwen2.5-Coder-14B-Instruct \
docker compose --profile vllm up --build vllm api postgres
```

Kubernetes example: `deploy/k8s/ai-coworker.yaml`.

## Chat

```bash
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message":"Hello"}' | jq
```

Stream (SSE); the UI uses WebSocket `/ws/chat`:

```bash
curl -N localhost:8000/chat/stream -H 'content-type: application/json' \
  -d '{"message":"Hello"}'
```

Pass the same `thread_id` to continue a conversation.

## Self-hosted LLM

| Env | Example |
|-----|---------|
| `LLM_BASE_URL` | `http://ollama:11434/v1` or `http://vllm:8000/v1` |
| `LLM_MODEL` | name as served (`openbmb/minicpm-v4.6`, HF id for vLLM) |
| `LLM_API_KEY` | any string if the server ignores auth |

Works with Ollama, vLLM, TGI, llama.cpp server, LocalAI, and similar.

## MCP, state, tests

- `MCP_GITHUB_*` / `MCP_CI_*` — optional HTTP MCP; chat allowlist is empty today.
- Empty `DATABASE_URL` → in-memory checkpoints; Compose Postgres for durable threads.
- `uv run pytest` and `uv run ruff check src tests`. CI is verify-only (no deploy): `.github/workflows/ci.yaml`.
- Dependabot: grouped weekly patch/minor PRs auto-merge after CI. Majors need a human. Enable **Allow auto-merge** on the repo.

## Layout

```
src/ai_coworker/   API, graph, chat node, prompts, MCP scaffold
frontend/          React chat + prompts panel
tests/
compose.yml
.github/           CI (lint, test, deps, secrets) — no deploy
```

License: [MIT](LICENSE). Vulnerability reports: [SECURITY.md](SECURITY.md).
