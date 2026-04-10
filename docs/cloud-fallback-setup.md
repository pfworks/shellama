# Cloud Fallback Setup Guide for SheLLama

## Overview

SheLLama supports cloud LLM fallback when local Ollama models produce low-quality output. Two options are available:

- **OpenRouter** — cloud service at openrouter.ai, access to Claude/GPT-4/Llama/Gemini
- **LiteLLM** — self-hosted proxy, runs on your network, routes to any LLM provider

When enabled, SheLLama automatically detects poor responses from the local model and re-sends the request through the configured fallback.

---

## Option 1: LiteLLM (Self-Hosted, Recommended)

LiteLLM runs on your network as an OpenAI-compatible proxy. It can route to Ollama, vLLM, HuggingFace, or cloud providers.

### Install LiteLLM

On a server in your network (can be the frontend or a dedicated host):

```bash
pip install litellm[proxy]
```

### Configure LiteLLM

Create a config file:

```bash
cat > /etc/litellm/config.yaml << 'EOF'
model_list:
  - model_name: fallback
    litellm_params:
      model: ollama/qwen2.5-coder:14b
      api_base: http://192.168.1.218:11434
  - model_name: fallback
    litellm_params:
      model: ollama/qwen2.5-coder:14b
      api_base: http://192.168.1.219:11434
EOF
```

This routes the `fallback` model to your larger backends via Ollama directly. You can also add cloud models:

```yaml
  - model_name: cloud
    litellm_params:
      model: anthropic/claude-3.5-sonnet
      api_key: sk-ant-your-key-here
```

### Start LiteLLM

```bash
litellm --config /etc/litellm/config.yaml --port 4000
```

Or as a systemd service:

```bash
cat > /etc/systemd/system/litellm.service << 'EOF'
[Unit]
Description=LiteLLM Proxy
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/litellm --config /etc/litellm/config.yaml --port 4000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now litellm
```

### Configure SheLLama to Use LiteLLM

On each backend server:

```bash
ssh root@<backend-ip>
sudo systemctl edit ansible-ollama
```

Add:

```ini
[Service]
Environment="OPENROUTER_API_KEY=sk-anything"
Environment="OPENROUTER_MODEL=fallback"
Environment="OPENROUTER_URL=http://<litellm-host>:4000/v1/chat/completions"
Environment="USE_CLOUD_FALLBACK=true"
```

Note: LiteLLM requires an API key header but doesn't validate it by default — any non-empty value works.

Restart:

```bash
sudo systemctl restart ansible-ollama
```

### Configure All Backends at Once

```bash
for host in 192.168.1.230 192.168.1.233 192.168.1.218 192.168.1.219; do
  echo "--- $host ---"
  ssh root@$host "mkdir -p /etc/systemd/system/ansible-ollama.service.d && \
    cat > /etc/systemd/system/ansible-ollama.service.d/override.conf << 'EOF'
[Service]
Environment=\"OPENROUTER_API_KEY=sk-local\"
Environment=\"OPENROUTER_MODEL=fallback\"
Environment=\"OPENROUTER_URL=http://192.168.1.229:4000/v1/chat/completions\"
Environment=\"USE_CLOUD_FALLBACK=true\"
EOF
    systemctl daemon-reload && systemctl restart ansible-ollama"
done
```

### Verify LiteLLM

```bash
curl http://<litellm-host>:4000/v1/models
curl -X POST http://<litellm-host>:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-local" \
  -H "Content-Type: application/json" \
  -d '{"model": "fallback", "messages": [{"role": "user", "content": "hello"}]}'
```

---

## Option 2: OpenRouter (Cloud)

## 1. Create an OpenRouter Account

1. Go to [https://openrouter.ai](https://openrouter.ai)
2. Click **Sign Up** and create an account (Google/GitHub OAuth or email)
3. Navigate to **Keys** at [https://openrouter.ai/keys](https://openrouter.ai/keys)
4. Click **Create Key**
5. Name it (e.g., `shellama`) and copy the key — it starts with `sk-or-v1-...`

## 2. Add Credits

1. Go to **Credits** at [https://openrouter.ai/credits](https://openrouter.ai/credits)
2. Add funds — $5 is enough for significant usage
3. Optionally set a usage limit to avoid surprises

## 3. Choose a Model

Browse available models at [https://openrouter.ai/models](https://openrouter.ai/models).

Recommended models:

| Model | ID | Cost (per 1M tokens) | Notes |
|-------|----|-----------------------|-------|
| Claude 3.5 Sonnet | `anthropic/claude-3.5-sonnet` | ~$3/$15 | Default, high quality |
| GPT-4o | `openai/gpt-4o` | ~$2.50/$10 | Fast, good quality |
| Llama 3 70B | `meta-llama/llama-3-70b-instruct` | ~$0.60/$0.80 | Open source, cheap |
| Gemini Pro 1.5 | `google/gemini-pro-1.5` | ~$1.25/$5 | Large context window |

## 4. Configure SheLLama Backends

The cloud fallback is configured on each **backend** server (not the frontend). You need to set three environment variables in the systemd service.

### Option A: Using systemd override (recommended)

On each backend server:

```bash
ssh root@<backend-ip>
sudo systemctl edit ansible-ollama
```

This opens an editor. Add the following:

```ini
[Service]
Environment="OPENROUTER_API_KEY=sk-or-v1-your-key-here"
Environment="OPENROUTER_MODEL=anthropic/claude-3.5-sonnet"
Environment="USE_CLOUD_FALLBACK=true"
```

Save and restart:

```bash
sudo systemctl restart ansible-ollama
```

### Option B: Edit the service file directly

```bash
ssh root@<backend-ip>
sudo nano /etc/systemd/system/ansible-ollama.service
```

Update the `Environment` lines:

```ini
[Service]
Environment="OPENROUTER_API_KEY=sk-or-v1-your-key-here"
Environment="OPENROUTER_MODEL=anthropic/claude-3.5-sonnet"
Environment="USE_CLOUD_FALLBACK=true"
```

Reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ansible-ollama
```

### Configuring All Backends at Once

```bash
for host in 192.168.1.230 192.168.1.233 192.168.1.218 192.168.1.219; do
  echo "--- $host ---"
  ssh root@$host "mkdir -p /etc/systemd/system/ansible-ollama.service.d && \
    cat > /etc/systemd/system/ansible-ollama.service.d/override.conf << 'EOF'
[Service]
Environment=\"OPENROUTER_API_KEY=sk-or-v1-your-key-here\"
Environment=\"OPENROUTER_MODEL=anthropic/claude-3.5-sonnet\"
Environment=\"USE_CLOUD_FALLBACK=true\"
EOF
    systemctl daemon-reload && systemctl restart ansible-ollama"
done
```

## 5. Verify

Check that the service is running with the new config:

```bash
ssh root@<backend-ip>
sudo systemctl status ansible-ollama
```

Test the fallback by sending a request that would produce a poor local response:

```bash
curl -X POST http://<backend-ip>:5000/generate-code \
  -H "Content-Type: application/json" \
  -d '{"description": "complex distributed system", "model": "qwen2.5-coder:7b"}'
```

If the local model's response is empty or an error, the response JSON will include:

```json
{
  "cloud_fallback": true,
  "cloud_model": "anthropic/claude-3.5-sonnet"
}
```

## 6. Disable Cloud Fallback

To go back to fully offline operation:

```bash
ssh root@<backend-ip>
sudo systemctl edit ansible-ollama
```

Change to:

```ini
[Service]
Environment="USE_CLOUD_FALLBACK=false"
```

Restart:

```bash
sudo systemctl restart ansible-ollama
```

## How Fallback Works

1. Every request is first processed by the local Ollama model
2. The response is checked for quality:
   - Empty playbook or code output → triggers fallback
   - Error from Ollama → triggers fallback
   - Successful non-empty response → returned as-is (no cloud call)
3. If fallback triggers, the same prompt is sent to OpenRouter
4. The cloud response replaces the local response
5. The response is tagged with `cloud_fallback: true` so clients know

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | *(empty)* | API key (OpenRouter key or any string for LiteLLM) |
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-sonnet` | Model to use for fallback |
| `OPENROUTER_URL` | `https://openrouter.ai/api/v1/chat/completions` | API endpoint (change for LiteLLM) |
| `USE_CLOUD_FALLBACK` | `false` | Set to `true` to enable |

## Cost Management

- Monitor usage at [https://openrouter.ai/activity](https://openrouter.ai/activity)
- Set spending limits at [https://openrouter.ai/credits](https://openrouter.ai/credits)
- Use cheaper models (e.g., `meta-llama/llama-3-70b-instruct`) to reduce costs
- Fallback only triggers on poor local responses, so costs are minimal with a good local model
