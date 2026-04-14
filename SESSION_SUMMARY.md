# sheLLaMa - Session Summary

Last updated: April 10, 2026

## Project Overview

sheLLaMa is a local LLM-powered tool (Ollama backend) for shell→Ansible conversion, code generation/explanation, chat, multi-file analysis, and image generation. Distributed architecture with frontend load balancer and backend workers. Fully offline after initial model pull. Formerly named "ansible-tools" — renamed in commit `5c53cc0` on April 9, 2026.

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
│   ├── shellama-config.ps1    # Shared config (API URL, model, system prompt)
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
│       ├── backends.html      # Admin: backend details with strength bars
│       ├── stats.html         # Admin: Chart.js graphs with time range selector
│       └── costs.html         # Admin: cloud cost tracking with time ranges
├── deploy/                     # Ansible deployment
│   ├── deploy.yml             # Backend playbook (src paths: ../backend/, ../frontend/web/)
│   ├── deploy-frontend.yml    # Frontend playbook (src paths: ../frontend/, ../frontend/web/)
│   ├── inventory.ini.example
│   ├── inventory-frontend.ini.example
│   ├── backends.json.example
│   └── com.ooma.ansible-ollama.plist  # macOS LaunchDaemon
├── shared/                     # Shared Python modules
│   └── constants.py           # Cloud pricing, test prompt, model_size()
├── docs/                       # Documentation
│   ├── cloud-fallback-setup.md   # OpenRouter + LiteLLM guide
│   ├── cloud-fallback-setup.pdf  # PDF version
│   ├── cloud-fallback-setup.tex  # LaTeX source
│   └── SECURITY_CLEANUP.md
├── bin/                        # Certificate management
│   ├── generate-certs.sh      # CA, server, client cert generation + revoke + delete
│   ├── generate-user-cert.sh  # Per-user certificate generation
│   └── revoke-cert.sh         # Certificate revocation (legacy)
├── README.md
├── SESSION_SUMMARY.md          # This file — read at session start
└── .gitignore
```

Gitignored at root: `inventory.ini`, `inventory-frontend.ini`, `backends.json`, `certs/`, `ooma/`

## Architecture

```
Clients → app-distributed.py (Frontend :5000) → Backend Farm
                                                 ├─ app.py (Backend 1 :5000)
                                                 └─ app.py (Backend 2 :5000)
```

- **Backend** (`backend/app.py`) — Ollama worker on port 5000, queue-based task processing, cloud fallback, persistent stats, image generation via Stable Diffusion
- **Frontend** (`frontend/app-distributed.py`) — Load balancer, weighted routing, model size filtering, parallel/sequential file analysis, per-client and per-task usage tracking, persistent history
- **Config** — `backends.json` (URLs, weights, max_model), `inventory*.ini` (Ansible deploy)
- **Deploy** — `deploy/deploy.yml` (backend), `deploy/deploy-frontend.yml` (frontend). Playbook `src:` paths use `../backend/`, `../frontend/`, `../frontend/web/` relative references.

## Client Interfaces (all at endpoint parity)

### Bash CLI (`cli/shellama`)
- Python script wrapping a bash shell, runs on Linux/macOS
- Regular commands execute in bash; prefix with `,` to talk to AI
- Agentic loop: AI proposes bash commands, user confirms (Y/n/q), AI reads output, iterates up to 10 rounds
- Quiet mode (`,,` prefix or `,quiet` toggle): output only, no confirmations — good for scripting
- Bash environment snapshot at startup (functions, aliases, variables) inherited by AI commands
- Tab completion, readline history (`~/.shellama_history`)
- Spinner during API calls
- Ctrl+C sends `/stop-all` to backend
- Session token/request/elapsed tracking (`,tokens`)
- Also supports non-interactive mode: `shellama <command> [args]` for use from shellama.bash

### Bash Integration (`cli/shellama.bash`)
- Source in `.bashrc` for `,` commands in your real bash session
- Defines bash functions (`,`, `,,`, `,explain`, `,generate`, etc.) that call the Python CLI
- Full job control, history, tab completion, aliases, native PS1
- Red HAL eye (🔴) prepended to prompt
- No separate shell — you stay in your real bash session

### PowerShell CLI (`powershell/powershellama.ps1`)
- Terminal-based, runs on Windows
- Same command set as bash CLI
- Agentic loop executes PowerShell commands instead of bash
- Spinner via background runspace
- Ctrl+C sends `/stop-all` to backend

### PowerShell Integration (`powershell/shellama.ps1`)
- Dot-source in `$PROFILE` for `,` commands in your real PowerShell session
- Defines PowerShell functions (`,`, `,,`, `,explain`, `,generate`, etc.)
- Pure PowerShell + REST — no Python dependency
- Sources `shellama-config.ps1` for shared config
- Red HAL eye (🔴) in prompt

### Shared PowerShell Config (`powershell/shellama-config.ps1`)
- Single source of truth for API URL, model default, and system prompt
- Sourced by `shellama.ps1`, `powershellama-gui.ps1`, and `powershellama-gui.cmd`

### PowerShell GUI (`powershell/powershellama-gui.ps1`)
- WinForms GUI, dark mode, Consolas font
- Run with: `powershell -ExecutionPolicy Bypass -File powershell\powershellama-gui.ps1`
- Async `HttpWebRequest` + `BeginGetResponse` + `DoEvents()` loop (non-blocking UI)
- `$script:formClosing` flag + `FormClosing` handler aborts in-flight requests
- `try/catch [WebException]` around `EndGetResponse` handles abort gracefully
- `finally` block closes all streams (reader, response, request stream)
- Agentic loop in GUI terminal pane, bails out on form close
- `,stop` command for stopping backend

### PowerShell GUI CMD (`powershell/powershellama-gui.cmd`)
- Double-click launcher wrapping same GUI as .ps1
- Same async HTTP pattern with `formClosing` flag, `WebException` catch, `finally` cleanup
- Minimizes console window via Win32 `ShowWindow`
- `,stop` command for stopping backend

### Python GUI (`cli/shellama-gui.pyw`)
- Cross-platform (Linux/macOS/Windows)
- Dark mode, color themes, multiple fonts
- File/directory browser for analyze
- Interactive follow-up questions
- Error log viewer, persistent settings
- Session token counter in UI

### Web UI (`frontend/web/index.html`)
- Legacy web client — `/` now redirects to `/status`
- Still accessible directly if needed but no longer the default landing page

### Admin Console (3 pages with shared nav bar)
- **Status** (`frontend/web/status.html`) — `/status` — Summary: total requests, tokens, active backends, queue size, cloud cost running tab (per-provider costs, auto-refreshes every 10s)
- **Backends** (`frontend/web/backends.html`) — `/backends` — Per-backend: online/offline, CPU/RAM/arch, weight, models, active task, strength bars
- **Stats** (`frontend/web/stats.html`) — `/stats` — Chart.js graphs: queue size and token usage over time, time range selector (hour/day/week/month/year)
- **Costs** (`frontend/web/costs.html`) — `/costs` — Cloud cost tracking: hypothetical vs actual fallback spend, filterable by day/week/month/year/custom date range

## All Client Commands (prefix with `,`)

| Command | Endpoint | Description |
|---|---|---|
| `, <prompt>` | `/chat` (agentic) | Multi-round chat, AI executes commands, iterates up to 10 rounds |
| `,, <prompt>` | `/chat` (quiet) | Output only, no confirmations |
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

## Backend API Endpoints (`backend/app.py`)

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Redirect to `/status` |
| `/chat` | POST | General chat (message, model) |
| `/generate` | POST | Shell commands → Ansible playbook (commands, model) |
| `/explain` | POST | Ansible playbook → explanation (playbook, model) |
| `/generate-code` | POST | Description → code (description, model) |
| `/explain-code` | POST | Code → explanation (code, model) |
| `/analyze` | POST | Multi-file analysis (files[], model) |
| `/generate-image` | POST | Text → image (prompt, image_model, steps, width, height) |
| `/upload` | POST | File upload for shell→ansible (multipart form) |
| `/models` | GET | List available Ollama models |
| `/image-models` | GET | List image generation models |
| `/queue-status` | GET | Queue size, active task, CPU/RAM stats, total tokens/requests |
| `/stop` | POST | Stop active task on this backend |

## Frontend API Endpoints (`frontend/app-distributed.py`)

All backend endpoints above are proxied through the frontend, plus:

| Endpoint | Method | Purpose |
|---|---|---|
| `/status` | GET | Serve `status.html` |
| `/backends` | GET | Serve `backends.html` |
| `/stats` | GET | Serve `stats.html` |
| `/stop-all` | POST | Stop processing on all backends |
| `/stop-backend` | POST | Stop a specific backend (takes `{"url": "..."}`) |
| `/test` | POST | Benchmark models: `{"model": "all\|name", "prompt": "..."}` |
| `/cloud-costs` | GET | Running tab: what total usage would cost on cloud providers |
| `/ip-tokens` | GET | Token usage history per client IP and per backend |
| `/queue-history` | GET | Queue size history for graphs |
| `/usage-stats` | GET | Cumulative usage by client IP and by task type |
| `/costs` | GET | Serve `costs.html` |
| `/cost-history` | GET | Token totals filtered by time: `?since=TIMESTAMP&until=TIMESTAMP` |
| `/api/backends` | GET/POST | Get or update backend config (tasks, weight, max_model) |
| `/auto-fallback` | GET/POST | Get or toggle auto cloud fallback mode |

## Load Balancing

- `backends.json` defines backends with `url`, `weight`, and `max_model`
- Score = `queue_size - (weight * 0.1)`, lowest score wins
- Model size filtering: requested model must be ≤ backend's `max_model`
- `MODEL_SIZES` dict in `frontend/app-distributed.py` maps model names to numeric sizes for comparison
- `get_available_backend()` has wait/retry logic (default 300s timeout, 0.5s retry interval)
- Backend lock prevents double-assignment during parallel requests

## Multi-File Analysis

- If multiple backends available: files processed in parallel (batched by available backend count)
- If only 1 backend available: files processed sequentially (avoids timeout)
- Response includes `parallel: true/false` flag
- Combined output with `--- filename ---` separators

## Cloud Fallback

Configured on each backend via environment variables. Two options:

**OpenRouter (cloud):** Set `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `USE_CLOUD_FALLBACK=true`

**LiteLLM (self-hosted):** Same vars plus `OPENROUTER_URL=http://litellm-host:4000/v1/chat/completions`. LiteLLM requires an API key header but doesn't validate it — any non-empty value works.

Fallback triggers when local Ollama produces empty/error output. Response tagged with `cloud_fallback: true`.

See `docs/cloud-fallback-setup.md` for full guide.

## Persistence

- **Backend** (`backend/app.py`): Saves `total_requests` and `total_tokens` to `shellama-stats.json` every 60s. Survives restarts.
- **Frontend** (`frontend/app-distributed.py`): Saves `ip_token_history`, `backend_token_history`, `queue_history`, `persisted_totals` (including `prompt_tokens`/`response_tokens` for cloud cost tab), `usage_stats` to `shellama-history.json` every 60s. Detects backend restarts (current < previous) and handles token delta correctly.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SHELLAMA_API` | `http://192.168.1.229:5000` | API endpoint (clients) |
| `SHELLAMA_MODEL` | `qwen2.5-coder:7b` | Default model (clients) |
| `AI_IMAGE_MODEL` | `sd-turbo` | Image generation model |
| `AI_PS1` | (bash PS1) | Custom prompt (bash CLI only) |
| `AI_QUIET` | `false` | Start in quiet mode (bash CLI only) |
| `OPENROUTER_API_KEY` | *(empty)* | Cloud fallback API key (backends) |
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-sonnet` | Cloud fallback model (backends) |
| `OPENROUTER_URL` | `https://openrouter.ai/api/v1/chat/completions` | Cloud fallback endpoint (backends, change for LiteLLM) |
| `USE_CLOUD_FALLBACK` | `false` | Enable cloud fallback (backends) |
| `SHELLAMA_TLS_CERT` | *(empty)* | Server TLS cert path — enables HTTPS (backends + frontend) |
| `SHELLAMA_TLS_KEY` | *(empty)* | Server TLS key path (backends + frontend) |
| `SHELLAMA_TLS_CA` | *(empty)* | CA cert for client verification — enables mTLS (backends) |
| `SHELLAMA_BACKEND_CERT` | *(empty)* | Client cert for frontend→backend mTLS (frontend) |
| `SHELLAMA_BACKEND_KEY` | *(empty)* | Client key for frontend→backend mTLS (frontend) |
| `SHELLAMA_BACKEND_CA` | *(empty)* | CA to verify backend server certs (frontend) |
| `SHELLAMA_DOWNLOAD_DIR` | *(current dir)* | Default save directory for generated images |
| `SHELLAMA_AUTH_FILE` | `/etc/shellama/auth.json` | API key auth config file (optional, auth disabled if missing) |

## Benchmarking (`,test`)

Frontend `/test` endpoint handles all benchmarking server-side. CLI just calls the API and displays results.

- `POST /test {"model": "all"}` — benchmarks all runnable models with default prompt
- `POST /test {"model": "llama3.2", "prompt": "..."}` — specific model(s), custom prompt
- Filters by `max_model` from online backends via `model_size()` in `shared/constants.py`
- Returns `results` (per-model: elapsed, tokens, tok/s), `skipped` (too large), `cloud_costs`, `pricing_source`
- Pricing fetched live from OpenRouter (`https://openrouter.ai/api/v1/models`) on each `/test` call
- Falls back gracefully to `CLOUD_PRICING_STATIC` if OpenRouter unreachable
- `pricing_source` in response: `openrouter` or `static`
- 15 cloud providers mapped via `OPENROUTER_MODELS` dict in `shared/constants.py`:
  Claude 4 Sonnet/Haiku, Claude 3.5 Sonnet, GPT-4o/mini, OpenAI o3/o4-mini,
  Azure GPT-4o, Gemini 2.5 Pro/Flash, Grok 3/mini, Llama 3.1 70B, Amazon Nova Pro/Lite/Micro
- CLI interactive picker still fetches `/models` + `/queue-status` locally for the "(too large)" display, then sends selection to `/test`

## Cloud Cost Running Tab

`GET /cloud-costs` — shows what total non-benchmark usage would have cost on each cloud provider.

- Tracks cumulative `prompt_tokens` and `response_tokens` in `persisted_totals` (survives restarts)
- Excludes tokens from `/test` benchmarks (task_type == 'test')
- `proxy_request` passes prompt/response token counts to `record_ip_tokens`
- Uses same live OpenRouter pricing as `/test`

## Key Design Decisions

1. **Sequential vs parallel analysis**: When only 1 backend is available, multi-file analysis runs sequentially to avoid timeout. With 2+ backends, files are processed in parallel batches.

2. **Cloud fallback on backend, not frontend**: Each backend independently decides whether to fall back to OpenRouter/LiteLLM. Frontend just proxies.

3. **Agentic loop with confirmation**: AI proposes commands in ```bash blocks. User confirms each (Y/n/q). Output fed back to AI for next round. Max 10 rounds. Quiet mode skips confirmation.

4. **Bash environment snapshot**: At startup, `cli/shellama` captures the user's bash functions, aliases, and exported variables into a temp file. All AI-proposed commands run with this environment sourced, so the AI's commands have access to the user's shell setup.

5. **Persistent stats**: Both backend and frontend save stats to JSON files every 60 seconds. Frontend detects backend restarts by comparing current vs previous token counts.

6. **Model size filtering**: `max_model` in `backends.json` prevents routing large model requests to backends that can't handle them. Numeric size comparison via `model_size()` in `shared/constants.py`.

7. **Shared constants**: `shared/constants.py` is the single source of truth for cloud pricing, test prompt, and `model_size()`. Frontend `/test` endpoint imports from it. CLI has no local pricing logic — just calls the API. Pricing fetched live from OpenRouter with static fallback.

8. **Async HTTP in PowerShell GUIs**: Both `.ps1` and `.cmd` GUIs use `HttpWebRequest.BeginGetResponse` + `DoEvents()` loop to keep UI responsive during long API calls. `$script:formClosing` flag + `try/catch [WebException]` + `finally` cleanup prevents kernel security exceptions on form close.

9. **Optional TLS/mTLS**: Encryption is opt-in via env vars. Backend can serve HTTPS and require client certs. Frontend can serve HTTPS to clients and present client certs to backends. All frontend→backend requests go through `_backend_get`/`_backend_post` helpers that attach certs. Cert management via `bin/generate-certs.sh` script (init, server, client, list, revoke, delete). PKI stored in `/etc/shellama/pki` by default.


## Known Issues

- Ansible 2.9 cannot manage Ubuntu 24.04 (Python 3.12) hosts — need manual deployment or Ansible upgrade for those nodes
- `certs/` directory is in the repo but should be in `.gitignore` (docs/SECURITY_CLEANUP.md has instructions)
- Stats page graph data is browser-side only (resets on page reload) — backend persistence covers totals but not graph history

## Recommended Models for CPU

| Model | Response Time | Notes |
|---|---|---|
| `qwen2.5-coder:3b` | 10-30s | Fast, decent quality |
| `qwen2.5-coder:7b` | 30-60s | Best balance (default) |
| `deepseek-coder:6.7b` | 30-60s | Alternative |
| `qwen2.5-coder:14b` | 1-3min | Higher quality, needs 32+ cores |
