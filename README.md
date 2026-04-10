# SheLLama

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
- PowerShell CLI (`powershell/powershellama.ps1`) — Windows
- PowerShell GUI (`powershell/powershellama-gui.ps1`, `powershell/powershellama-gui.cmd`) — Windows
- Python GUI (`cli/shellama-gui.pyw`) — cross-platform
- Web UI with dark mode (`frontend/web/index.html`)
- Admin console: Status, Backends, Stats pages
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
│   └── shellama-gui.pyw       # Python GUI (cross-platform)
├── powershell/                 # Windows clients
│   ├── powershellama.ps1      # PowerShell CLI + agentic shell
│   ├── powershellama-gui.ps1  # PowerShell WinForms GUI
│   └── powershellama-gui.cmd  # Double-click GUI launcher
├── backend/                    # Backend worker
│   ├── app.py                 # Ollama interface, queue, AI endpoints
│   └── ansible-ollama.service # Linux systemd service
├── frontend/                   # Frontend load balancer
│   ├── app-distributed.py     # Weighted routing, parallel analysis, stats
│   ├── ansible-ollama-frontend.service
│   └── web/                   # Web UI + admin console
│       ├── index.html         # Main web UI
│       ├── status.html        # Admin: status summary
│       ├── backends.html      # Admin: backend details
│       └── stats.html         # Admin: charts and graphs
├── deploy/                     # Ansible deployment
│   ├── deploy.yml             # Backend playbook
│   ├── deploy-frontend.yml    # Frontend playbook
│   ├── inventory.ini.example
│   ├── inventory-frontend.ini.example
│   ├── backends.json.example
│   └── com.ooma.ansible-ollama.plist  # macOS LaunchDaemon
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
# Web UI: http://localhost:5000
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
| `,tokens` | Show session usage stats |
| `,quiet` | Toggle quiet mode |
| `,list` / `,help` | Show available commands |

### PowerShell CLI (`powershell/powershellama.ps1`)

```powershell
$env:SHELLAMA_API = "http://your-server:5000"
.\powershell\powershellama.ps1
```

Same command set as bash CLI. Agentic loop executes PowerShell commands instead of bash.

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

## Web UI

Access at `http://your-server:5000`

Services: Shell→Ansible, Explain Playbook, Generate Code, Explain Code, Chat, Analyze Files, Generate Image.

Features: model selection, dark mode, file upload, copy/save output, queue position display, token statistics.

## Admin Console

| Page | URL | Description |
|------|-----|-------------|
| Status | `/status` | Summary: total requests, tokens, active backends, queue size |
| Backends | `/backends` | Per-backend details: online/offline, CPU/RAM, weight, models, active task |
| Stats | `/stats` | Charts: queue size and token usage over time (hour/day/week/month/year) |

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
```

### Status & Control Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/queue-status` | GET | Aggregate queue/backend status, token/request totals |
| `/models` | GET | List available Ollama models (deduplicated across backends) |
| `/image-models` | GET | List image generation models |
| `/ip-tokens` | GET | Token usage history per client IP and per backend |
| `/queue-history` | GET | Queue size history for graphs |
| `/usage-stats` | GET | Cumulative usage by client IP and by task type |
| `/stop` | POST | Stop active task (single backend) |
| `/stop-all` | POST | Stop all backends (frontend only) |
| `/stop-backend` | POST | Stop a specific backend (frontend only, takes `{"url": "..."}`) |

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

### Recommended Models for CPU

| Model | Response Time | Notes |
|-------|--------------|-------|
| `qwen2.5-coder:3b` | 10-30s | Fast, decent quality |
| `qwen2.5-coder:7b` | 30-60s | Best balance |
| `deepseek-coder:6.7b` | 30-60s | Alternative |
| `qwen2.5-coder:14b` | 1-3min | Higher quality, needs 32+ cores |

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
