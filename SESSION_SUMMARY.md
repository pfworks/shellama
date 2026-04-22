# sheLLaMa - Session Summary

Last updated: April 21, 2026

## Project Overview

sheLLaMa is a local LLM-powered tool (Ollama backend) for shell→Ansible conversion, code generation/explanation, chat, multi-file analysis, and image generation. Distributed architecture with frontend load balancer and backend workers. Fully offline after initial model pull. Formerly named "ansible-tools" — renamed April 9, 2026.

## Project Structure

```
shellama/
├── cli/                        # Linux/macOS clients
│   ├── shellama                # Bash CLI + agentic shell (Python)
│   ├── shellama.bash           # Bash integration (source in .bashrc)
│   └── shellama-gui.pyw       # Python GUI (cross-platform, tkinter)
├── powershell/                 # Windows clients
│   ├── powershellama.ps1      # PowerShell CLI + agentic shell
│   ├── shellama.ps1           # PowerShell integration (dot-source in $PROFILE)
│   ├── shellama-config.ps1    # Shared config (API URL, model, system prompt, API key)
│   ├── powershellama-gui.ps1  # PowerShell WinForms GUI
│   └── powershellama-gui.cmd  # Double-click GUI launcher (async HttpWebRequest)
├── backend/                    # Backend worker
│   ├── app.py                 # Ollama interface, queue, all AI endpoints, cloud fallback, stats
│   └── ansible-ollama.service # Linux systemd service
├── frontend/                   # Frontend load balancer
│   ├── app-distributed.py     # Weighted routing, parallel analysis, usage tracking, stats
│   ├── ansible-ollama-frontend.service
│   └── web/                   # Web UI + admin console
│       ├── index.html         # Legacy web UI (/ redirects to /status)
│       ├── status.html        # Admin: status summary + cloud cost tab
│       ├── backends.html      # Admin: backend details
│       ├── stats.html         # Admin: charts and graphs
│       └── costs.html         # Admin: cloud cost tracking
├── deploy/                     # Ansible deployment
│   ├── deploy.yml             # Backend playbook
│   ├── deploy-frontend.yml    # Frontend playbook
│   ├── inventory.ini.example
│   ├── inventory-frontend.ini.example
│   ├── backends.json.example
│   ├── auth.json.example      # API key + SSO config template
│   └── com.ooma.ansible-ollama.plist  # macOS LaunchDaemon
├── shared/                     # Shared Python modules
│   ├── constants.py           # Cloud pricing, test prompt, model_size()
│   └── auth.py                # Authentication (API keys + SSO/OIDC)
├── docs/                       # Documentation
│   ├── cloud-fallback-setup.md   # OpenRouter + LiteLLM guide
│   ├── cloud-fallback-setup.pdf  # PDF version
│   ├── cloud-fallback-setup.tex  # LaTeX source
│   └── SECURITY_CLEANUP.md
├── bin/                        # Certificate management
│   ├── generate-certs.sh
│   ├── generate-user-cert.sh
│   ├── manage-keys.sh         # API key management CLI
│   └── revoke-cert.sh
├── README.md
├── SESSION_SUMMARY.md          # This file — read at session start
├── requirements.txt            # Python dependencies
└── .gitignore
```

## Architecture

```
Clients → Frontend (:5000) → Backend Farm
                               ├─ Backend 1 (:5000)
                               └─ Backend 2 (:5000)
External tools → /v1/chat/completions (OpenAI-compatible)
```

- **Backend** (`backend/app.py`) — Ollama worker, queue-based, cloud fallback with quality detection
- **Frontend** (`frontend/app-distributed.py`) — Load balancer, routing, caching, auth, rate limiting, health checks, webhooks
- **Deploy** — `deploy/deploy.yml` (backend), `deploy/deploy-frontend.yml` (frontend)

## All Client Commands (prefix with `,`)

| Command | Endpoint | Description |
|---|---|---|
| `, <prompt>` | `/chat` | Chat with AI (conversation memory, no command execution) |
| `,do <prompt>` | `/chat` (agentic) | Agentic mode — AI runs commands, iterates up to 10 rounds |
| `,explain <file>` | `/explain` or `/explain-code` | Auto-detects .yml→playbook, other→code |
| `,generate <desc>` | `/generate` or `/generate-code` | Keywords `ansible\|playbook\|shell command`→playbook, else→code |
| `,analyze <paths>` | `/analyze` | Files and/or directories, recursive |
| `,img <prompt>` | `/generate-image` | Text-to-image (Stable Diffusion) |
| `,models` | `/models` | List and select model |
| `,test [model\|all] [--prompt "..."]` | `/test` | Benchmark models — speed, tokens, cloud cost estimate |
| `,tokens` | — | Show session usage stats (CLI only) |
| `,quiet` | — | Toggle quiet mode (CLI only) |
| `,stop` | `/stop-all` | Stop backend processing (GUI only) |
| `,list` / `,help` | — | Show available commands |

## Frontend API Endpoints

### Core (proxied to backends)

| Endpoint | Method | Purpose |
|---|---|---|
| `/chat` | POST | Chat with conversation memory (message, model, conversation_id) |
| `/generate` | POST | Shell commands → Ansible playbook |
| `/explain` | POST | Ansible playbook → explanation |
| `/generate-code` | POST | Description → code |
| `/explain-code` | POST | Code → explanation |
| `/analyze` | POST | Multi-file analysis (parallel/sequential) |
| `/generate-image` | POST | Text → image |
| `/upload` | POST | File upload for shell→ansible |
| `/test` | POST | Benchmark models with cloud cost estimates |

### OpenAI-Compatible

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-format chat (messages array, model) |
| `/v1/models` | GET | Model list in OpenAI format |

### Status & Control

| Endpoint | Method | Purpose |
|---|---|---|
| `/queue-status` | GET | Aggregate status, tokens, backends, aliases, auto_fallback |
| `/models` | GET | List available Ollama models |
| `/image-models` | GET | List image generation models |
| `/stop-all` | POST | Stop all backends (admin) |
| `/stop-backend` | POST | Stop specific backend (admin) |
| `/auto-fallback` | GET/POST | Toggle auto cloud fallback (admin) |
| `/api/backends` | GET/POST | Get/update backend config — tasks, weight, max_model (admin) |
| `/api/model-aliases` | GET/POST | Get/set model aliases (admin) |

### Cost & Stats

| Endpoint | Method | Purpose |
|---|---|---|
| `/cloud-costs` | GET | Running cost tab: hypothetical + actual fallback + cached |
| `/cost-history` | GET | Token totals by time range: `?since=TS&until=TS` |
| `/ip-tokens` | GET | Token history per client IP and backend |
| `/queue-history` | GET | Queue size history for graphs |
| `/usage-stats` | GET | Usage by client, task type, and API key |
| `/reset-stats` | POST | Clear request/token counters (admin) |
| `/reset-cloud-costs` | POST | Clear cost data (admin) |
| `/reset-all` | POST | Clear everything (admin) |

### Auth & Security

| Endpoint | Method | Purpose |
|---|---|---|
| `/sso/login` | GET | Redirect to SSO provider |
| `/sso/callback` | GET | Handle SSO return |
| `/sso/logout` | GET | Clear session |
| `/sso/userinfo` | GET | Current user + role |
| `/api/keys` | GET/POST | List/create API keys (SSO+HTTPS admin) |
| `/api/keys/revoke` | POST | Revoke API key (SSO+HTTPS admin) |
| `/api/audit` | GET | View audit log (SSO+HTTPS admin) |
| `/api/audit/toggle` | POST | Enable/disable audit (SSO+HTTPS admin) |
| `/api/audit/status` | GET | Audit status (public) |
| `/api/webhooks` | GET/POST | Manage webhook URLs (admin) |

## Key Features

### Rate Limiting & Budgets
- Per-key `rate_limit: {rpm: N, tpd: N}` (requests/min, tokens/day)
- Per-key `budget: {max_daily: N}` — enforced on actual cloud fallback spend only
- Budget warning webhook at 80%
- Returns 429 when exceeded

### Prompt Caching
- SHA256(endpoint + model + content) → cached response
- TTL: 5 min (SHELLAMA_CACHE_TTL env, 0 to disable), max 500 entries
- Skips: conversations, force_cloud, errors
- Stats: cached_requests, tokens_saved

### Conversation Memory
- `conversation_id` in /chat → maintains message history across requests
- 8-hour expiry, in-memory on frontend
- Clients auto-generate session IDs (SHELLAMA_CONV_ID)

### Model Aliases
- `backends.json` → `model_aliases: {"fast": "llama3.2:1b", "default": "qwen2.5-coder:7b"}`
- Resolved server-side in proxy_request
- Manageable via API and config file

### Health Checks & Retry
- Background thread pings backends every 30s
- 3 consecutive failures → unhealthy (skipped in routing)
- Auto-recovers when backend responds
- proxy_request retries up to 2x on different backends
- Failures increment health counter

### Webhooks
- Events: backend_down, backend_recovered, budget_warning
- Config: SHELLAMA_WEBHOOK_URL env or /api/webhooks API
- Dedup: same event suppressed for 5 min
- Payload: JSON with event, timestamp, details

### Authentication
- **API keys**: X-API-Key header, roles (admin/user/viewer), per-key model/budget/rate limits
- **SSO (OIDC)**: Keycloak, Azure AD, Authentik — role mapping from group claims
- **Web UI**: admin-only controls hidden for non-admin roles
- **Key management**: bin/manage-keys.sh CLI + /api/keys (SSO+HTTPS required)

### OpenAI-Compatible API
- `/v1/chat/completions` — standard OpenAI format, full auth/caching/retry pipeline
- `/v1/models` — model list including aliases
- Use with: Cursor, Continue, Open WebUI, LangChain, any OpenAI client

### Amazon Bedrock Cost Tracking
- Costs page shows Bedrock on-demand pricing alongside OpenRouter cloud providers
- 13 Bedrock models: Claude Opus 4, Claude 4 Sonnet, Claude 3.5 Sonnet/Haiku, Nova Pro/Lite/Micro/Premier, Llama 4 Maverick/Scout, Llama 3.3 70B, DeepSeek R1, Mistral Large 3
- Prices fetched live from AWS Pricing API (`aws pricing get-products`), static fallback for models not yet in API (e.g., newer Claude)
- Bedrock section displayed with AWS orange styling, separate from OpenRouter providers

### Backend Leak Prevention
- `proxy_request` uses `try/finally` to guarantee `release_backend()` is always called
- Prevents backends from getting permanently marked unavailable when exceptions occur in token recording, audit, or caching code

### Task Heartbeat & Stale Task Reaper
- `submit_and_wait()` replaces bare `event.wait()` — sends heartbeats every 10s while waiting
- `stale_task_reaper` background thread checks every 10s:
  - Tasks running longer than `SHELLAMA_TASK_TIMEOUT` (default 30 min) are killed
  - Tasks whose client disconnected (no heartbeat for 30s) are killed
- `/heartbeat` endpoint for explicit keepalive
- Prevents stuck image generation or other long tasks from blocking backends indefinitely

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SHELLAMA_API` | `http://192.168.1.229:5000` | API endpoint (clients) |
| `SHELLAMA_MODEL` | `qwen2.5-coder:7b` | Default model (clients) |
| `SHELLAMA_API_KEY` | *(empty)* | API key for auth (clients) |
| `SHELLAMA_CONV_ID` | *(auto-generated)* | Conversation ID for chat memory |
| `SHELLAMA_DOWNLOAD_DIR` | *(current dir)* | Default save directory for images |
| `SHELLAMA_CACHE_TTL` | `300` | Prompt cache TTL seconds (0 = disabled) |
| `SHELLAMA_AUTH_FILE` | `/etc/shellama/auth.json` | Auth config file |
| `SHELLAMA_AUDIT_LOG` | *(empty)* | Audit log file path |
| `SHELLAMA_WEBHOOK_URL` | *(empty)* | Webhook notification URL |
| `SHELLAMA_TLS_CERT` | *(empty)* | Server TLS certificate |
| `SHELLAMA_TLS_KEY` | *(empty)* | Server TLS key |
| `SHELLAMA_TLS_CA` | *(empty)* | CA for client verification (mTLS) |
| `SHELLAMA_BACKEND_CERT` | *(empty)* | Client cert for frontend→backend mTLS |
| `SHELLAMA_BACKEND_KEY` | *(empty)* | Client key for frontend→backend mTLS |
| `SHELLAMA_BACKEND_CA` | *(empty)* | CA to verify backend certs |
| `SHELLAMA_CERT_DIR` | `/etc/shellama/pki` | PKI directory |
| `AI_IMAGE_MODEL` | `sd-turbo` | Image generation model |
| `SHELLAMA_TASK_TIMEOUT` | `1800` | Max task runtime in seconds (backend, 0 = no limit) |
| `AI_PS1` | (bash PS1) | Custom prompt (bash CLI only) |
| `AI_QUIET` | `false` | Start in quiet mode |
| `OPENROUTER_API_KEY` | *(empty)* | Cloud fallback API key |
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-sonnet` | Cloud fallback model |
| `OPENROUTER_URL` | `https://openrouter.ai/api/v1/chat/completions` | Cloud fallback endpoint |
| `USE_CLOUD_FALLBACK` | `false` | Enable cloud fallback (backends) |
