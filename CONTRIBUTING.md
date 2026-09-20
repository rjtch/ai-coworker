# Contributing

1. Branch from `main`. Open a PR — CI must pass. There is **no** deploy job.
2. Never commit `.env`, keys, or `PROMPTS_ADMIN_TOKEN`.
3. Match existing style. Do not reformat unrelated files.
4. `uv sync --extra dev && uv run pytest && uv run ruff check src tests`
5. Frontend: `cd frontend && npm ci && npm run lint && npm run build`
6. Dependabot opens grouped weekly patch/minor PRs per ecosystem. Those auto-merge when CI is green (enable **Allow auto-merge** on the repo and require CI on `main`). **Major** bumps stay for review.

Coding agents: follow [AGENTS.md](AGENTS.md). Humans: [README.md](README.md). Security: [SECURITY.md](SECURITY.md).
