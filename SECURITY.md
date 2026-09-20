# Security

Do **not** open a public issue for vulnerabilities, leaked secrets, or anything that could be used to take over the API, inference, or MCP credentials.

## Report

Use [GitHub private vulnerability reporting](https://github.com/rjtch/ai-coworker/security/advisories/new) if it is enabled, or email the repository owner from the GitHub profile.

Include: affected version/commit, impact, and a minimal reproduction. Do not attach production tokens.

## Scope

In scope: this repository’s API, UI, Compose/K8s examples, CI, and default configs.

Out of scope: third-party models, Ollama/vLLM themselves, and MCP servers you run separately.

## Please do not

- Commit `.env`, API keys, or MCP tokens
- Expose the chat API without auth on a public network (there is no auth today)
- Add shell/write tools without a human gate and allowlisted paths
