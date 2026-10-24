# AI Coworker web UI

React + TypeScript + Vite frontend for the AI Coworker chat host. Project overview: [../README.md](../README.md). Agent instructions: [../AGENTS.md](../AGENTS.md).

## What it does

- **Chat** (`src/App.tsx`) — threads via `thread_id`, PDF/PNG/JPEG attachments, and three transports: WebSocket `/ws/chat` (default, supports cancel), SSE `/chat/stream`, or plain HTTP `/chat`.
- **Prompts panel** (`src/PromptsPanel.tsx`) — list, edit, reset, delete, and reload the prompt catalog (`/prompts`). Mutations send `X-Prompts-Token` when an admin token is set; the token is kept in `localStorage`.
- **API client** (`src/api.ts`) — all calls go through `VITE_API_BASE` (default `/api`).

The deploy-approval UI (`approveDeploy`, "Awaiting deploy approval") is leftover. The backend graph is `START → chat → END` and has no `approve-deploy` route.

## Develop

```bash
npm install
npm run dev     # http://localhost:3000, proxies /api (incl. WebSocket) → http://127.0.0.1:8000
npm run lint    # oxlint
npm run build   # tsc -b && vite build
```

Run the API first (see the root README).

## Production

`Dockerfile` builds the app and serves it with nginx (`nginx.conf`), which proxies `/api/` and `/api/ws/` to `api:8000`. In Compose the UI is on http://localhost:3080.
