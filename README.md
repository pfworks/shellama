# Ansible Tools - Complete Guide

Local LLM-powered tool for converting shell commands to Ansible playbooks, explaining code, generating code, and analyzing files. Runs completely offline after initial setup.

## Table of Contents
- [Features](#features)
- [System Requirements](#system-requirements)
- [Quick Start](#quick-start)
- [Deployment](#deployment)
- [Usage](#usage)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

## Features

**AI Services:**
- Shell commands → Ansible playbooks
- Ansible playbooks → Explanations
- Descriptions → Code generation
- Code → Explanations
- Multi-file analysis

**Interfaces:**
- Web UI with dark mode
- Python GUI (cross-platform)
- CLI tool
- REST API

**Architecture:**
- Standalone or distributed deployment
- Load balancing across multiple backends
- Parallel file processing across backends
- Request queuing with position tracking
- Optional Claude API fallback
- Fully offline capable

## System Requirements

### Backend Server
**Minimum (7B models):**
- CPU: 8 cores
- RAM: 16GB
- Storage: 50GB
- OS: Ubuntu 22.04 LTS, Debian 12, or macOS 12+

**Recommended (13B-14B models):**
- CPU: 16 cores
- RAM: 32GB
- Storage: 100GB
- OS: Ubuntu 22.04 LTS, Debian 12, or macOS 12+

**Large models (32B-34B):**
- CPU: 32+ cores
- RAM: 64GB+
- Storage: 200GB
- Not recommended for CPU-only systems

### Frontend Server
- CPU: 4 cores
- RAM: 8GB
- Storage: 20GB
- OS: Ubuntu 22.04 LTS, Debian 12, or macOS 12+

### Client (GUI/CLI)
- Python 3.8+
- 2GB RAM
- Windows, macOS, or Linux

## Quick Start

### Standalone Installation (Linux/macOS)

**1. Install Ollama:**
```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS
brew install ollama
```

**2. Pull a model:**
```bash
ollama pull qwen2.5-coder:7b
```

**3. Clone and run:**
```bash
git clone <repo-url>
cd ansible-tools
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install flask ollama pyyaml requests anthropic
python app.py
```

**4. Access:**
- Web UI: http://localhost:5000
- GUI: `python ansible-tools-gui.pyw`
- CLI: `./ansible-tools chat`

## Deployment

### Distributed Setup (Production)

**1. Prepare configuration:**
```bash
cd ansible-tools

# Backend inventory
cat > inventory.ini << EOF
[servers]
192.168.1.230 ansible_user=youruser
EOF

# Frontend inventory
cat > inventory-frontend.ini << EOF
[frontend]
192.168.1.229 ansible_user=youruser
EOF

# Backend configuration
cat > backends.json << EOF
{
  "backends": [
    {"url": "http://192.168.1.230:5000", "weight": 10, "max_model": "qwen2.5-coder:7b"}
  ]
}
EOF
```

**2. Deploy backend:**
```bash
ansible-playbook -i inventory.ini deploy.yml
```

**3. Pull models on backend:**
```bash
ssh youruser@192.168.1.230
ollama pull qwen2.5-coder:7b
```

**4. Deploy frontend:**
```bash
ansible-playbook -i inventory-frontend.ini deploy-frontend.yml
```

**5. Update backends.json on frontend:**
```bash
ssh youruser@192.168.1.229
sudo nano /usr/local/bin/backends.json
# Update max_model to match what you pulled
sudo systemctl restart ansible-ollama-frontend
```

**6. Access:**
- Web UI: http://192.168.1.229:5000
- Status: http://192.168.1.229:5000/status.html (includes queue and token graphs with day/week/month/year views)

### macOS-Specific Notes

**Deployment differences:**
- Uses LaunchDaemon instead of systemd
- Service file: `com.ooma.ansible-ollama.plist`
- Homebrew for dependencies

**Manual service management:**
```bash
# Load service
sudo launchctl load /Library/LaunchDaemons/com.ooma.ansible-ollama.plist

# Unload service
sudo launchctl unload /Library/LaunchDaemons/com.ooma.ansible-ollama.plist

# View logs
tail -f /var/log/ansible-ollama.log
```

## Usage

### Web UI

Access at http://your-server:5000

**Features:**
- Model selection dropdown
- Dark mode toggle
- File upload support
- Copy/save output
- Queue position display
- Token statistics

**Services:**
1. Shell → Ansible: Convert commands to playbooks
2. Ansible → Explanation: Explain playbooks
3. Description → Code: Generate code
4. Code → Explanation: Explain code
5. Chat: General questions
6. Analyze Files: Multi-file analysis (supports directories)

### Python GUI

```bash
# Set API endpoint
export ANSIBLE_TOOLS_API=http://192.168.1.229:5000

# Run GUI
python3 ansible-tools-gui.pyw
```

**Features:**
- Cross-platform (Windows, macOS, Linux)
- Dark mode with color themes
- Multiple font options
- File upload (single or multiple)
- Directory browser for analyzing entire folders
- Interactive mode for follow-up questions
- Error log viewer
- Persistent settings

### CLI Tool

```bash
# Set API endpoint
export ANSIBLE_TOOLS_API=http://192.168.1.229:5000
export ANSIBLE_TOOLS_MODEL=qwen2.5-coder:7b

# Convert shell commands
ansible-tools shell2ansible commands.txt > playbook.yml

# Explain playbook
ansible-tools explain-ansible playbook.yml

# Generate code
ansible-tools generate-code description.txt > script.py

# Explain code
ansible-tools explain-code script.py

# Analyze files
ansible-tools analyze file1.py file2.yml file3.txt

# Analyze entire directory (recursively)
ansible-tools analyze /path/to/directory

# Mix files and directories
ansible-tools analyze file1.py /path/to/directory file2.yml

# Interactive analysis with follow-up questions
ansible-tools analyze-interactive playbook.yml

# Interactive chat
ansible-tools chat

# Interactive mode
ansible-tools interactive
```

### REST API

**Generate playbook:**
```bash
curl -X POST http://your-server:5000/generate \
  -H "Content-Type: application/json" \
  -d '{"commands": "apt update\napt install nginx", "model": "qwen2.5-coder:7b"}'
```

**Explain playbook:**
```bash
curl -X POST http://your-server:5000/explain \
  -H "Content-Type: application/json" \
  -d '{"playbook": "'"$(cat playbook.yml)"'", "model": "qwen2.5-coder:7b"}'
```

**Generate code:**
```bash
curl -X POST http://your-server:5000/generate-code \
  -H "Content-Type: application/json" \
  -d '{"description": "Python script to parse CSV", "model": "qwen2.5-coder:7b"}'
```

**Explain code:**
```bash
curl -X POST http://your-server:5000/explain-code \
  -H "Content-Type: application/json" \
  -d '{"code": "'"$(cat script.py)"'", "model": "qwen2.5-coder:7b"}'
```

**Analyze files:**
```bash
curl -X POST http://your-server:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"files": [{"path": "app.py", "content": "..."}], "model": "qwen2.5-coder:7b"}'
```

**Chat:**
```bash
curl -X POST http://your-server:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is Ansible?", "model": "qwen2.5-coder:7b"}'
```

**Queue status:**
```bash
curl http://your-server:5000/queue-status
```

## Configuration

### Model Selection

**Recommended models for CPU:**
- `qwen2.5-coder:7b` - Best balance (30-60s response)
- `deepseek-coder:6.7b` - Alternative (30-60s response)
- `codellama:13b` - Original (1-3min response)
- `qwen2.5-coder:3b` - Fast (10-30s response)

**Pull models:**
```bash
ollama pull qwen2.5-coder:7b
ollama list  # View installed models
```

### Offline Mode

**Disable internet after setup:**
```bash
ssh youruser@192.168.1.230
sudo systemctl edit ansible-ollama
```

Add:
```ini
[Service]
Environment="USE_CLAUDE_FALLBACK=false"
```

Restart:
```bash
sudo systemctl restart ansible-ollama
```

### Claude API Fallback (Optional)

**Enable Claude fallback:**
```bash
ssh youruser@192.168.1.230
sudo systemctl edit ansible-ollama
```

Add:
```ini
[Service]
Environment="INFISICAL_TOKEN=your-token"
Environment="INFISICAL_URL=https://infisical.corp.ooma.com"
Environment="USE_CLAUDE_FALLBACK=true"
```

Restart:
```bash
sudo systemctl restart ansible-ollama
```

### Load Balancing

**Add multiple backends:**
```bash
ssh youruser@192.168.1.229
sudo nano /usr/local/bin/backends.json
```

```json
{
  "backends": [
    {"url": "http://192.168.1.230:5000", "weight": 10, "max_model": "qwen2.5-coder:7b"},
    {"url": "http://192.168.1.231:5000", "weight": 5, "max_model": "qwen2.5-coder:14b"}
  ]
}
```

**Weight logic:**
- Higher weight = higher priority
- Score = queue_size - (weight * 0.1)
- Backend with lowest score is selected

Restart frontend:
```bash
sudo systemctl restart ansible-ollama-frontend
```

### Firewall

**Linux (ufw):**
```bash
sudo ufw allow 5000/tcp
```

**macOS:**
```bash
# System Preferences → Security & Privacy → Firewall → Firewall Options
# Add Python to allowed applications
```

## Troubleshooting

### Request timeout after 10 minutes

**Timeout increased to 1 hour:**
- Frontend to backend timeout: 3600 seconds
- Keepalive connections prevent drops
- Long-running requests (large file analysis) now supported
- Unique task IDs track each request
- Error returned if task completes but result is lost

### Backend not responding

**Check service:**
```bash
# Linux
sudo systemctl status ansible-ollama
sudo journalctl -u ansible-ollama -n 50

# macOS
sudo launchctl list | grep ansible
tail -f /var/log/ansible-ollama.log
```

**Restart service:**
```bash
# Linux
sudo systemctl restart ansible-ollama

# macOS
sudo launchctl unload /Library/LaunchDaemons/com.ooma.ansible-ollama.plist
sudo launchctl load /Library/LaunchDaemons/com.ooma.ansible-ollama.plist
```

### Frontend shows "No backends available"

**Check backends.json:**
```bash
ssh youruser@192.168.1.229
cat /usr/local/bin/backends.json
```

**Verify max_model matches pulled models:**
- If you pulled `qwen2.5-coder:7b`, set `max_model: "qwen2.5-coder:7b"`
- Model size check: requested model must be ≤ max_model

**Test backend connectivity:**
```bash
curl http://192.168.1.230:5000/queue-status
```

### Model not found error

**Pull the model:**
```bash
ssh youruser@192.168.1.230
ollama pull qwen2.5-coder:7b
ollama list  # Verify it's installed
```

### Slow responses

**Use smaller models:**
```bash
ollama pull qwen2.5-coder:3b  # Faster
```

**Check CPU usage:**
```bash
htop
```

**Add more backends:**
- Deploy additional backend servers
- Update backends.json with new URLs

### Out of memory

**Check memory:**
```bash
free -h
```

**Solutions:**
- Use smaller model (3B instead of 7B)
- Increase system RAM
- Reduce concurrent requests

### GUI not connecting

**Check API URL:**
```bash
export ANSIBLE_TOOLS_API=http://192.168.1.229:5000
python3 ansible-tools-gui.pyw
```

**Test API:**
```bash
curl http://192.168.1.229:5000/queue-status
```

### macOS Permission Issues

**Grant full disk access:**
1. System Preferences → Security & Privacy → Privacy
2. Full Disk Access → Add Python

**Service won't start:**
```bash
# Check permissions
ls -la /Library/LaunchDaemons/com.ooma.ansible-ollama.plist

# Should be owned by root
sudo chown root:wheel /Library/LaunchDaemons/com.ooma.ansible-ollama.plist
```

## Performance Tips

### CPU Optimization

**Reduce context size:**
```bash
ssh youruser@192.168.1.230
sudo nano /usr/local/bin/app.py
```

Find `ollama.chat()` calls and add:
```python
options={'num_ctx': 2048}  # Default is 4096
```

**Model recommendations by CPU:**
- 8-16 cores: qwen2.5-coder:1.5b or 3b
- 16-32 cores: qwen2.5-coder:7b
- 32+ cores: qwen2.5-coder:14b

### Scaling

**Horizontal scaling:**
1. Deploy multiple backend servers
2. Update backends.json on frontend
3. Restart frontend service

**Benefits of multiple backends:**
- Load balancing across servers
- Parallel file processing (analyze multiple files simultaneously)
- Higher throughput
- Automatic failover

**Vertical scaling:**
- Add more CPU cores
- Increase RAM
- Use faster storage (NVMe SSD)

## Maintenance

### Update models
```bash
ssh youruser@192.168.1.230
ollama pull qwen2.5-coder:7b  # Updates to latest
sudo systemctl restart ansible-ollama
```

### Update application
```bash
cd ansible-tools
git pull
ansible-playbook -i inventory.ini deploy.yml
ansible-playbook -i inventory-frontend.ini deploy-frontend.yml
```

### View logs
```bash
# Backend (Linux)
sudo journalctl -u ansible-ollama -f

# Frontend (Linux)
sudo journalctl -u ansible-ollama-frontend -f

# macOS
tail -f /var/log/ansible-ollama.log
```

### Backup configuration
```bash
scp youruser@192.168.1.229:/usr/local/bin/backends.json backends.json.backup
```

## Files Reference

**Core:**
- `app.py` - Backend worker
- `app-distributed.py` - Frontend load balancer
- `ansible-tools` - CLI tool
- `ansible-tools-gui.pyw` - Python GUI
- `index.html` - Web UI
- `status.html` - Status dashboard

**Deployment:**
- `deploy.yml` - Backend deployment
- `deploy-frontend.yml` - Frontend deployment
- `inventory.ini` - Backend inventory
- `inventory-frontend.ini` - Frontend inventory
- `backends.json` - Backend configuration

**Services:**
- `ansible-ollama.service` - Linux backend service
- `ansible-ollama-frontend.service` - Linux frontend service
- `com.ooma.ansible-ollama.plist` - macOS backend service

**Documentation:**
- `README.md` - This file

## Internet Requirements

**Required (one-time):**
- `ollama pull <model>` - Download models

**Optional:**
- Claude API fallback (if enabled)

**Not required:**
- Running services
- Making requests
- All LLM inference (runs locally)

After initial setup, system runs completely offline.
