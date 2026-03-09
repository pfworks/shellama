# Deployment Guide - New Installation

## System Requirements

### Backend Server (CPU-based)
**Minimum for small models (7B):**
- CPU: 8 cores
- RAM: 16GB
- Storage: 50GB SSD
- OS: Ubuntu 22.04 LTS or Debian 12

**Recommended for medium models (13B-14B):**
- CPU: 16 cores
- RAM: 32GB
- Storage: 100GB SSD
- OS: Ubuntu 22.04 LTS or Debian 12

**For large models (32B-34B):**
- CPU: 32+ cores
- RAM: 64GB+
- Storage: 200GB SSD
- OS: Ubuntu 22.04 LTS or Debian 12

### Frontend Server
**Minimum:**
- CPU: 4 cores
- RAM: 8GB
- Storage: 20GB SSD
- OS: Ubuntu 22.04 LTS or Debian 12

## Deployment Steps

### 1. Prepare Deployment Machine

On your local machine (where you have this repo):

```bash
# Navigate to repo
cd /path/to/ansible-tools

# Create configuration files
cp inventory.ini.example inventory.ini
cp inventory-frontend.ini.example inventory-frontend.ini
cp backends.json.example backends.json

# Edit inventory.ini with your backend server
nano inventory.ini
```

Add:
```ini
[servers]
192.168.1.230 ansible_user=youruser
```

```bash
# Edit inventory-frontend.ini with your frontend server
nano inventory-frontend.ini
```

Add:
```ini
[frontend]
192.168.1.229 ansible_user=youruser
```

```bash
# Edit backends.json with backend URLs
nano backends.json
```

Add:
```json
{
  "backends": [
    {"url": "http://192.168.1.230:5000", "weight": 10, "max_model": "qwen2.5-coder:14b"}
  ]
}
```

### 2. Ensure SSH Access

```bash
# Test SSH access to both servers
ssh youruser@192.168.1.230 "echo Backend OK"
ssh youruser@192.168.1.229 "echo Frontend OK"

# If needed, copy SSH keys
ssh-copy-id youruser@192.168.1.230
ssh-copy-id youruser@192.168.1.229
```

### 3. Deploy Backend

From your local machine:

```bash
cd /path/to/ansible-tools

# Deploy backend
ansible-playbook -i inventory.ini deploy.yml
```

This will:
- Install Python, pip, and dependencies
- Install Ollama
- Deploy backend app (app.py)
- Create systemd service
- Start the service

**Note:** Models are NOT automatically pulled. You must pull them manually (see next step).

### 4. Pull Models on Backend

SSH to backend and pull only the models you need:

```bash
ssh youruser@192.168.1.230

# For CPU, recommended models (in order of preference):
ollama pull qwen2.5-coder:7b      # Best balance for CPU
ollama pull deepseek-coder:6.7b   # Alternative, good performance
ollama pull codellama:13b         # Original, slower on CPU

# Optional smaller models for faster responses:
ollama pull qwen2.5-coder:3b      # Fast, decent quality
ollama pull qwen2.5-coder:1.5b    # Very fast, lower quality

# Check installed models
ollama list
```

**CPU Performance Notes:**
- 7B models: ~30-60 seconds per response
- 13B-14B models: 1-3 minutes per response
- 32B+ models: 5-10+ minutes per response (not recommended for CPU)

**Internet Access:**
- Only needed for `ollama pull` commands
- After models are downloaded, system runs completely offline
- Optional: Disable Claude fallback for fully offline operation (see Post-Deployment Configuration)

### 5. Verify Backend

```bash
# Check service status
ssh youruser@192.168.1.230 "systemctl status ansible-ollama"

# Test backend directly
curl http://192.168.1.230:5000/queue-status

# Test a simple request
curl -X POST http://192.168.1.230:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2+2?", "model": "qwen2.5-coder:7b"}'
```

### 6. Deploy Frontend

From your local machine:

```bash
cd /path/to/ansible-tools

# Deploy frontend
ansible-playbook -i inventory-frontend.ini deploy-frontend.yml
```

This will:
- Install Python and dependencies
- Deploy frontend app (app-distributed.py)
- Deploy web UI (index.html, status.html)
- Copy backends.json configuration
- Create systemd service
- Start the service

### 7. Verify Frontend

```bash
# Check service status
ssh youruser@192.168.1.229 "systemctl status ansible-ollama-frontend"

# Test frontend
curl http://192.168.1.229:5000/queue-status

# Should show backend as online
```

### 8. Access Web UI

Open browser to:
```
http://192.168.1.229:5000/
```

Or status dashboard:
```
http://192.168.1.229:5000/status.html
```

### 9. Install Client Tools (Optional)

On your workstation:

```bash
# Set API endpoint
export ANSIBLE_TOOLS_API=http://192.168.1.229:5000

# Use the CLI
./ansible-tools chat

# Analyze files
./ansible-tools analyze file1.py file2.yml

# Or use the GUI
python3 ansible-tools-gui.pyw
```

**Available CLI Commands:**
- `shell2ansible <file>` - Convert shell commands to Ansible playbook
- `explain-ansible <file>` - Explain an Ansible playbook
- `generate-code <file>` - Generate code from description
- `explain-code <file>` - Explain code
- `analyze <file1> [file2 ...]` - Analyze one or more files
- `chat` - Interactive chat mode
- `interactive` - Interactive mode for Ansible tools

## Post-Deployment Configuration

### Update Backend Max Model

Edit backends.json on frontend to match what you actually pulled:

```bash
ssh youruser@192.168.1.229
sudo nano /usr/local/bin/backends.json
```

Update max_model to match your largest model:
```json
{
  "backends": [
    {"url": "http://192.168.1.230:5000", "weight": 10, "max_model": "qwen2.5-coder:7b"}
  ]
}
```

Restart frontend:
```bash
sudo systemctl restart ansible-ollama-frontend
```

### Disable Internet Access (Fully Offline Mode)

To run completely offline after models are downloaded:

```bash
ssh youruser@192.168.1.230
sudo systemctl edit ansible-ollama
```

Add or modify:
```ini
[Service]
Environment="USE_CLAUDE_FALLBACK=false"
```

Restart:
```bash
sudo systemctl restart ansible-ollama
```

### Configure Claude Fallback (Optional - Requires Internet)

If you want Claude API fallback for better quality:

1. Get Infisical token from your Infisical instance
2. Add to backend service:

```bash
ssh youruser@192.168.1.230
sudo systemctl edit ansible-ollama
```

Add:
```ini
[Service]
Environment="INFISICAL_TOKEN=your-token-here"
Environment="INFISICAL_URL=https://infisical.corp.ooma.com"
Environment="USE_CLAUDE_FALLBACK=true"
```

Restart:
```bash
sudo systemctl restart ansible-ollama
```

### Firewall Configuration

If using firewall:

```bash
# On backend
sudo ufw allow 5000/tcp

# On frontend
sudo ufw allow 5000/tcp
```

## Troubleshooting

### Backend not responding
```bash
ssh root@backend.example.com
journalctl -u ansible-ollama -n 50
systemctl restart ansible-ollama
```

### Frontend shows backend offline
```bash
# Test from frontend to backend
ssh root@frontend.example.com
curl http://backend.example.com:5000/queue-status
```

### Slow responses
- Use smaller models (3B-7B for CPU)
- Check CPU usage: `htop`
- Consider adding more backends for load distribution

### Out of memory
- Reduce model size
- Increase RAM
- Check: `free -h`

## Scaling

### Add More Backends

1. Deploy another backend server following steps 4-6
2. Update backends.json on frontend:

```json
{
  "backends": [
    {"url": "http://backend1.example.com:5000", "weight": 5, "max_model": "qwen2.5-coder:7b"},
    {"url": "http://backend2.example.com:5000", "weight": 10, "max_model": "qwen2.5-coder:14b"}
  ]
}
```

3. Restart frontend: `systemctl restart ansible-ollama-frontend`

### Weight Configuration

- Higher weight = higher priority
- Use weight to prefer faster/better backends
- Example: GPU backend weight=10, CPU backend weight=1

## Maintenance

### Update Models
```bash
ssh root@backend.example.com
ollama pull qwen2.5-coder:7b  # Updates to latest version
systemctl restart ansible-ollama
```

### Update Application
```bash
# On control node
cd /tmp/ansible-tools
git pull  # If using git
ansible-playbook -i inventory.ini deploy.yml
ansible-playbook -i inventory-frontend.ini deploy-frontend.yml
```

### View Logs
```bash
# Backend logs
ssh root@backend.example.com "journalctl -u ansible-ollama -f"

# Frontend logs
ssh root@frontend.example.com "journalctl -u ansible-ollama-frontend -f"
```

### Backup Configuration
```bash
# Backup from frontend
scp root@frontend.example.com:/usr/local/bin/backends.json backends.json.backup
```

## Performance Tuning for CPU

### Recommended Settings

For CPU-based deployments, edit the backend app to reduce context size:

```bash
ssh root@backend.example.com
nano /usr/local/bin/app.py
```

Look for `ollama.chat()` calls and add:
```python
options={'num_ctx': 2048}  # Reduce from default 4096
```

This reduces memory usage and speeds up responses at the cost of shorter context.

### Model Recommendations by CPU

**8-16 cores:**
- qwen2.5-coder:1.5b or 3b
- Response time: 10-30 seconds

**16-32 cores:**
- qwen2.5-coder:7b
- deepseek-coder:6.7b
- Response time: 30-90 seconds

**32+ cores:**
- qwen2.5-coder:14b
- Response time: 1-3 minutes

**Not recommended for CPU:**
- Models 32B and larger (too slow)
