# sheLLaMa

Local LLM-powered tool for code generation, explanation, shell-to-Ansible conversion, file analysis, chat, and image generation. Agentic shell where the AI can run commands and iterate. Runs completely offline after initial model pull.

## Features

**AI Services:**
- Shell commands → Ansible playbooks
- Ansible playbooks → Explanations
- Descriptions → Code generation
- Code → Explanations
- Multi-file/directory analysis (parallel across backends)
- Chat with agentic command execution
- Text → Image generation (Stable Diffusion)

**Agentic Shell:**
- AI proposes bash/PowerShell commands, executes them (with confirmation), reads output, iterates up to 10 rounds
- Quiet mode for scripting (output only, no confirmations)
- Bash environment snapshot (functions, aliases, variables) inherited by AI commands

**Interfaces:**
- Bash CLI (`cli/shellama`) — Linux/macOS
- Bash integration (`cli/shellama.bash`) — source in .bashrc for , commands in real bash
- PowerShell CLI (`powershell/powershellama.ps1`) — Windows (standalone)
- PowerShell integration (`powershell/shellama.ps1`) — dot-source in $PROFILE for , commands
- PowerShell GUI (`powershell/powershellama-gui.ps1`, `powershell/powershellama-gui.cmd`) — Windows
- Python GUI (`cli/shellama-gui.pyw`) — cross-platform
- Admin console: Status (with cloud cost tab), Backends, Stats pages
- REST API

**Architecture:**
- Standalone or distributed deployment
- Frontend load balancer with weighted routing
- Parallel file processing across backends
- Sequential fallback when only 1 backend available
- Request queuing with position tracking
- Cloud fallback via OpenRouter or self-hosted LiteLLM
- Per-client and per-task usage tracking
- Persistent stats (survive restarts)
- Fully offline capable

## Project Structure

```
shellama/
├── cli/                        # Linux/macOS clients
│   ├── shellama                # Bash CLI + agentic shell
│   ├── shellama.bash           # Bash integration (source in .bashrc)
│   └── shellama-gui.pyw       # Python GUI (cross-platform)
├── powershell/                 # Windows clients
│   ├── powershellama.ps1      # PowerShell CLI + agentic shell
│   ├── shellama.ps1           # PowerShell integration (dot-source in $PROFILE)
│   ├── shellama-config.ps1    # Shared config (API URL, model, system prompt)
│   ├── powershellama-gui.ps1  # PowerShell WinForms GUI
│   └── powershellama-gui.cmd  # Double-click GUI launcher
├── backend/                    # Backend worker
│   ├── app.py                 # Ollama interface, queue, AI endpoints
│   └── ansible-ollama.service # Linux systemd service
├── frontend/                   # Frontend load balancer
│   ├── app-distributed.py     # Weighted routing, parallel analysis, stats
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
└── bin/                        # Certificate management
    ├── generate-certs.sh
    ├── generate-user-cert.sh
    └── revoke-cert.sh
```

## System Requirements

### Backend Server
| Tier | CPU | RAM | Storage | Models |
|------|-----|-----|---------|--------|
| Minimum | 8 cores | 16GB | 50GB | 7B (30-60s/response) |
| Recommended | 16 cores | 32GB | 100GB | 13B-14B (1-3min/response) |
| Large | 32+ cores | 64GB+ | 200GB | 32B+ (not recommended for CPU) |

### Frontend Server
- 4 cores, 8GB RAM, 20GB storage

### Clients
- Python 3.8+ or PowerShell 5.1+

## Quick Start

```bash
# 1. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh   # Linux
brew install ollama                               # macOS

# 2. Pull a model
ollama pull qwen2.5-coder:7b

# 3. Clone and run
git clone <repo-url>
cd shellama
python3 -m venv venv && source venv/bin/activate
pip install flask ollama pyyaml requests psutil
python backend/app.py

# 4. Access
# Admin: http://localhost:5000
# CLI:    ./cli/shellama
# GUI:    python3 cli/shellama-gui.pyw
```

## CLI Usage

### Bash CLI (`cli/shellama`)

```bash
export SHELLAMA_API=http://your-server:5000
export SHELLAMA_MODEL=qwen2.5-coder:7b
./cli/shellama
```

The CLI is a full bash shell with AI integration. Regular commands run in bash. Prefix with `,` to talk to the AI.

| Command | Description |
|---------|-------------|
| `, <prompt>` | Agentic chat — AI runs commands, iterates up to 10 rounds |
| `,, <prompt>` | Quiet mode — output only, no confirmations |
| `,explain <file>` | Explain any file (auto-detects .yml→playbook, other→code) |
| `,generate <desc>` | Generate code (detects `ansible\|playbook\|shell command`→playbook) |
| `,analyze <paths>` | Analyze files and/or directories recursively |
| `,img <prompt>` | Generate image (Stable Diffusion) |
| `,models` | List and select model |
| `,test [model\|all] [--prompt "..."]` | Benchmark models — compare speed, tokens, cloud cost |
| `,tokens` | Show session usage stats |
| `,quiet` | Toggle quiet mode |
| `,list` / `,help` | Show available commands |

### Bash Integration (`cli/shellama.bash`)

```bash
# Add to .bashrc:
source /path/to/shellama/cli/shellama.bash
```

Gives you all `,` commands in your real bash session. Full job control, history, tab completion, aliases, native PS1. The `,` functions call the Python CLI under the hood.

### PowerShell CLI (`powershell/powershellama.ps1`)

```powershell
$env:SHELLAMA_API = "http://your-server:5000"
.\powershell\powershellama.ps1
```

Same command set as bash CLI. Agentic loop executes PowerShell commands instead of bash.

### PowerShell Integration (`powershell/shellama.ps1`)

```powershell
# Add to $PROFILE:
. C:\path\to\shellama\powershell\shellama.ps1
```

Same as bash integration but for PowerShell. Defines `,` functions in your real PS session. Pure PowerShell + REST, no Python dependency.

### PowerShell GUI

```powershell
powershell -ExecutionPolicy Bypass -File powershell\powershellama-gui.ps1
# Or double-click powershell\powershellama-gui.cmd
```

WinForms GUI with dark mode, Consolas font, agentic loop in terminal pane. Use `,stop` to stop backend processing.

### Python GUI (`cli/shellama-gui.pyw`)

```bash
export SHELLAMA_API=http://your-server:5000
python3 cli/shellama-gui.pyw
```

Cross-platform GUI with dark mode, color themes, multiple fonts, file/directory browser, interactive follow-up questions, error log viewer, persistent settings.

## Admin Console

Access at `http://your-server:5000` (redirects to `/status`)

| Page | URL | Description |
|------|-----|-------------|
| Status | `/status` | Summary: total requests, tokens, active backends, queue size, cloud cost tab |
| Backends | `/backends` | Per-backend details: online/offline, CPU/RAM, weight, models, active task |
| Stats | `/stats` | Charts: queue size and token usage over time (hour/day/week/month/year) |
| Costs | `/costs` | Cloud cost tracking by day/week/month/year/custom range, fallback spend |

## REST API

### Core Endpoints

```bash
# Chat
curl -X POST http://server:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is Ansible?", "model": "qwen2.5-coder:7b"}'

# Shell → Ansible
curl -X POST http://server:5000/generate \
  -H "Content-Type: application/json" \
  -d '{"commands": "apt update\napt install nginx", "model": "qwen2.5-coder:7b"}'

# Explain playbook
curl -X POST http://server:5000/explain \
  -H "Content-Type: application/json" \
  -d '{"playbook": "'"$(cat playbook.yml)"'", "model": "qwen2.5-coder:7b"}'

# Generate code
curl -X POST http://server:5000/generate-code \
  -H "Content-Type: application/json" \
  -d '{"description": "Python CSV parser", "model": "qwen2.5-coder:7b"}'

# Explain code
curl -X POST http://server:5000/explain-code \
  -H "Content-Type: application/json" \
  -d '{"code": "'"$(cat script.py)"'", "model": "qwen2.5-coder:7b"}'

# Analyze files
curl -X POST http://server:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"files": [{"path": "app.py", "content": "..."}], "model": "qwen2.5-coder:7b"}'

# Upload file (shell → ansible)
curl -X POST http://server:5000/upload \
  -F "file=@commands.txt" -F "model=qwen2.5-coder:7b"

# Generate image
curl -X POST http://server:5000/generate-image \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A futuristic server room", "image_model": "sd-turbo", "steps": 4}'

# Benchmark a model (use /test endpoint)
curl -X POST http://server:5000/test \
  -H "Content-Type: application/json" \
  -d '{"model": "all"}'
# Response: {results: [{model, elapsed, prompt_tokens, response_tokens, ...}], cloud_costs: [...]}

# Benchmark specific models with custom prompt
curl -X POST http://server:5000/test \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3.2", "prompt": "Explain quicksort"}'

# List available models
curl http://server:5000/models

# Check which models each backend supports
curl http://server:5000/queue-status
```

### Status & Control Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/queue-status` | GET | Aggregate queue/backend status, token/request totals |
| `/models` | GET | List available Ollama models (deduplicated across backends) |
| `/image-models` | GET | List image generation models |
| `/test` | POST | Benchmark models: `{"model": "all\|name", "prompt": "..."}` |
| `/cloud-costs` | GET | Running tab: what total usage would cost on cloud providers |
| `/ip-tokens` | GET | Token usage history per client IP and per backend |
| `/queue-history` | GET | Queue size history for graphs |
| `/usage-stats` | GET | Cumulative usage by client IP and by task type |
| `/stop` | POST | Stop active task (single backend) |
| `/stop-all` | POST | Stop all backends (frontend only) |
| `/stop-backend` | POST | Stop a specific backend (frontend only, takes `{"url": "..."}`) |
| `/costs` | GET | Cost tracking page (day/week/month/year/custom range) |
| `/cost-history` | GET | Token totals filtered by time: `?since=TIMESTAMP&until=TIMESTAMP` |
| `/api/backends` | GET/POST | Get or update backend config (tasks, weight, max_model) |
| `/auto-fallback` | GET/POST | Get or toggle auto cloud fallback mode |

## Deployment

### Distributed Setup

```bash
# 1. Configure
cp deploy/inventory.ini.example inventory.ini
cp deploy/inventory-frontend.ini.example inventory-frontend.ini
cp deploy/backends.json.example backends.json
# Edit each file with your server details

# 2. Deploy backend, pull models
ansible-playbook -i inventory.ini deploy/deploy.yml
ssh root@192.168.1.230 "ollama pull qwen2.5-coder:7b"

# 3. Deploy frontend
ansible-playbook -i inventory-frontend.ini deploy/deploy-frontend.yml

# 4. Access
# Web UI: http://frontend:5000
# Admin:  http://frontend:5000/status
```

### Load Balancing

```json
{
  "backends": [
    {"url": "http://192.168.1.230:5000", "weight": 10, "max_model": "qwen2.5-coder:7b"},
    {"url": "http://192.168.1.233:5000", "weight": 10, "max_model": "qwen2.5-coder:14b"}
  ]
}
```

- Higher weight = higher priority. Score = `queue_size - (weight * 0.1)`, lowest wins.
- Multi-file analysis runs in parallel across backends, or sequentially if only 1 backend available.
- Model size filtering: requested model must be ≤ backend's `max_model`.

### Cloud Fallback

Two options for fallback when local models produce poor output:

**OpenRouter (cloud):**
```ini
[Service]
Environment="OPENROUTER_API_KEY=sk-or-v1-your-key"
Environment="OPENROUTER_MODEL=anthropic/claude-3.5-sonnet"
Environment="USE_CLOUD_FALLBACK=true"
```

**LiteLLM (self-hosted):**
```ini
[Service]
Environment="OPENROUTER_API_KEY=sk-anything"
Environment="OPENROUTER_MODEL=fallback"
Environment="OPENROUTER_URL=http://litellm-host:4000/v1/chat/completions"
Environment="USE_CLOUD_FALLBACK=true"
```

See `docs/cloud-fallback-setup.md` for full setup guide including LiteLLM configuration.

### macOS Notes

Uses LaunchDaemon instead of systemd:
```bash
sudo launchctl load /Library/LaunchDaemons/com.ooma.ansible-ollama.plist
sudo launchctl unload /Library/LaunchDaemons/com.ooma.ansible-ollama.plist
tail -f /var/log/ansible-ollama.log
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SHELLAMA_API` | `http://192.168.1.229:5000` | API endpoint |
| `SHELLAMA_MODEL` | `qwen2.5-coder:7b` | Default model |
| `AI_IMAGE_MODEL` | `sd-turbo` | Image generation model |
| `AI_PS1` | (bash PS1) | Custom prompt (bash CLI only) |
| `AI_QUIET` | `false` | Start in quiet mode (bash CLI only) |
| `OPENROUTER_API_KEY` | *(empty)* | Cloud fallback API key |
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-sonnet` | Cloud fallback model |
| `OPENROUTER_URL` | `https://openrouter.ai/api/v1/chat/completions` | Cloud fallback endpoint (change for LiteLLM) |
| `USE_CLOUD_FALLBACK` | `false` | Enable cloud fallback |
| `SHELLAMA_TLS_CERT` | *(empty)* | Server TLS certificate path (enables HTTPS) |
| `SHELLAMA_TLS_KEY` | *(empty)* | Server TLS private key path |
| `SHELLAMA_TLS_CA` | *(empty)* | CA cert for client verification (backend mTLS) |
| `SHELLAMA_BACKEND_CERT` | *(empty)* | Client cert for frontend→backend mTLS |
| `SHELLAMA_BACKEND_KEY` | *(empty)* | Client key for frontend→backend mTLS |
| `SHELLAMA_BACKEND_CA` | *(empty)* | CA to verify backend server certs |
| `SHELLAMA_DOWNLOAD_DIR` | *(current dir)* | Default save directory for generated images |
| `SHELLAMA_AUTH_FILE` | `/etc/shellama/auth.json` | API key auth config file (optional, auth disabled if missing) |

### Recommended Models for CPU

| Model | Response Time | Notes |
|-------|--------------|-------|
| `qwen2.5-coder:3b` | 10-30s | Fast, decent quality |
| `qwen2.5-coder:7b` | 30-60s | Best balance |
| `deepseek-coder:6.7b` | 30-60s | Alternative |
| `qwen2.5-coder:14b` | 1-3min | Higher quality, needs 32+ cores |

### Benchmarking Models

Use `,test` in the CLI to compare models side by side:

```bash
,test              # Interactive — pick a model or all
,test all          # Benchmark all runnable models
,test qwen         # Benchmark models matching "qwen"
,test 7b --prompt "Explain quicksort"   # Custom prompt, models matching "7b"
,test all --prompt "Write a REST API"   # Custom prompt, all models
```

Output includes a comparison table with time, token counts, and tokens/sec for each model, followed by cloud cost estimates showing what the same request would cost on Claude, GPT-4o, Gemini, Grok, Llama 3, and Amazon Nova via cloud providers.

Pricing is fetched live from OpenRouter on each test run. If OpenRouter is unreachable, static fallback prices are used. The response includes `pricing_source` (`openrouter` or `static`).

Models that are too large for your backends (based on `max_model` in `backends.json`) are automatically skipped when testing all. They show as "(too large)" in the interactive picker.

To benchmark via the API directly:

```bash
# Benchmark all runnable models with default prompt
curl -X POST http://server:5000/test \
  -H "Content-Type: application/json" \
  -d '{"model": "all"}'

# Benchmark specific models with custom prompt
curl -X POST http://server:5000/test \
  -H "Content-Type: application/json" \
  -d '{"model": "llama3.2", "prompt": "Explain quicksort"}'

# Response:
# {"prompt": "...", "results": [{model, elapsed, prompt_tokens, response_tokens,
#   total_tokens, tok_per_sec}], "skipped": [...], "cloud_costs": [{provider,
#   input_cost, output_cost, total_cost}], "pricing_source": "openrouter"}
```

### Cloud Cost Running Tab

Track what your total usage would have cost on cloud providers:

```bash
curl http://server:5000/cloud-costs
# {"prompt_tokens": 1234, "response_tokens": 5678, "total_tokens": 6912,
#  "pricing_source": "openrouter", "note": "Excludes tokens from /test benchmarks",
#  "cloud_costs": [{"provider": "Claude 4 Sonnet", "total_cost": 0.091170}, ...]}
```

Tokens from `/test` benchmarks are excluded so the tab reflects real usage only. The tab persists across restarts.

## Authentication

Optional — disabled when `/etc/shellama/auth.json` doesn't exist.

**API Keys** (for CLI/API clients):
```bash
# Set in header
curl -H "X-API-Key: sk-your-key" http://server:5000/chat ...

# Or in environment for CLI
export SHELLAMA_API_KEY=sk-your-key
```

**SSO** (for web UI — Keycloak or Azure AD):
- Web pages redirect to SSO login when configured
- Role mapped from group claims (admin/user/viewer)
- Admin buttons hidden for non-admin roles

**Roles:**
| Role | API Access | Web UI | Models | Cloud Fallback |
|------|-----------|--------|--------|----------------|
| admin | All endpoints | Full (modify settings) | All | Yes |
| user | Chat, generate, explain, analyze, image, test | View only | Configured per key | Configurable |
| viewer | Read-only (status, models, costs) | View only | None | No |

**Setup:**
```bash
cp deploy/auth.json.example /etc/shellama/auth.json
# Edit API keys, optionally add SSO config
```

See `deploy/auth.json.example` for Keycloak and Azure AD configuration.

## Certificate Management

```bash
bin/generate-certs.sh init                           # Generate CA
bin/generate-certs.sh server backend-1 192.168.1.230,localhost  # Server cert with SANs
bin/generate-certs.sh server frontend 192.168.1.229,localhost   # Frontend server cert
bin/generate-certs.sh client frontend-mtls           # Client cert for mTLS
bin/generate-certs.sh list                           # List all certs
bin/generate-certs.sh revoke backend-1               # Revoke a cert
bin/generate-certs.sh delete backend-1               # Delete cert files
```

IP addresses in SANs are automatically detected and added as `IP:` entries. PKI directory defaults to `/etc/shellama/pki` (set `SHELLAMA_CERT_DIR` to change).

## Troubleshooting

**Timeouts:** Frontend→backend timeout is 3600s (1 hour). Uses keepalive connections. Each task gets a unique ID for tracking.

**No backends available:** Check `backends.json` — `max_model` must match or exceed the requested model. Test with `curl http://backend:5000/queue-status`.

**Slow responses:** Use smaller models. Add more backends. Check `htop`.

**Service management (Linux):**
```bash
sudo systemctl status ansible-ollama
sudo journalctl -u ansible-ollama -f
sudo systemctl restart ansible-ollama
```

## Internet Requirements

**Required once:** `ollama pull <model>`

**Optional:** OpenRouter/LiteLLM cloud fallback

**Not required:** All inference, all services, all clients — runs fully offline after model pull.
