#!/bin/bash
# sheLLaMa API key management
# Usage: ./bin/manage-keys.sh [command] [args]
#
# Commands:
#   add <name> <role> [models]   Generate API key (role: admin/user/viewer)
#   list                         List all API keys
#   revoke <key>                 Remove an API key
#   help                         Show this help
#
# Examples:
#   ./bin/manage-keys.sh add rory admin
#   ./bin/manage-keys.sh add ci-bot user "llama3.2:1b,qwen2.5-coder:7b"
#   ./bin/manage-keys.sh add dashboard viewer
#   ./bin/manage-keys.sh list
#   ./bin/manage-keys.sh revoke sk-abc123

set -e

AUTH_FILE="${SHELLAMA_AUTH_FILE:-/etc/shellama/auth.json}"

ensure_file() {
    if [ ! -f "$AUTH_FILE" ]; then
        mkdir -p "$(dirname "$AUTH_FILE")"
        echo '{"api_keys":{}}' > "$AUTH_FILE"
        chmod 600 "$AUTH_FILE"
    fi
}

cmd_add() {
    local name="$1" role="$2" models="$3"
    [ -z "$name" ] || [ -z "$role" ] && echo "Usage: $0 add <name> <role> [models]" && exit 1
    [[ "$role" != "admin" && "$role" != "user" && "$role" != "viewer" ]] && echo "Role must be admin, user, or viewer" && exit 1
    ensure_file
    local key="sk-$(openssl rand -hex 16)"
    local models_json='["all"]'
    if [ -n "$models" ]; then
        models_json=$(echo "$models" | tr ',' '\n' | sed 's/^/"/;s/$/"/' | paste -sd, | sed 's/^/[/;s/$/]/')
    fi
    python3 -c "
import json, sys
with open('$AUTH_FILE', 'r') as f:
    cfg = json.load(f)
cfg.setdefault('api_keys', {})
cfg['api_keys']['$key'] = {'name': '$name', 'role': '$role', 'models': $models_json}
with open('$AUTH_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
"
    echo "Created API key:"
    echo "  Key:    $key"
    echo "  Name:   $name"
    echo "  Role:   $role"
    echo "  Models: ${models:-all}"
    echo ""
    echo "Set in client: export SHELLAMA_API_KEY=$key"
    echo "Or use header: X-API-Key: $key"
}

cmd_list() {
    ensure_file
    python3 -c "
import json
with open('$AUTH_FILE', 'r') as f:
    cfg = json.load(f)
keys = cfg.get('api_keys', {})
if not keys:
    print('No API keys configured')
else:
    print(f'API keys in $AUTH_FILE:')
    print()
    for k, v in keys.items():
        masked = k[:6] + '...' + k[-4:]
        models = ', '.join(v.get('models', ['all']))
        print(f'  {masked:<20} {v.get(\"name\",\"?\"):<15} {v.get(\"role\",\"?\"):<8} models: {models}')
"
}

cmd_revoke() {
    local key="$1"
    [ -z "$key" ] && echo "Usage: $0 revoke <key>" && exit 1
    ensure_file
    python3 -c "
import json, sys
with open('$AUTH_FILE', 'r') as f:
    cfg = json.load(f)
keys = cfg.get('api_keys', {})
if '$key' not in keys:
    print('Key not found')
    sys.exit(1)
name = keys['$key'].get('name', 'unknown')
del keys['$key']
with open('$AUTH_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
print(f'Revoked key for {name}')
"
}

cmd_help() {
    head -14 "$0" | tail -13
    echo ""
    echo "Auth file: $AUTH_FILE (set SHELLAMA_AUTH_FILE to change)"
}

case "${1:-help}" in
    add)    cmd_add "$2" "$3" "$4" ;;
    list)   cmd_list ;;
    revoke) cmd_revoke "$2" ;;
    *)      cmd_help ;;
esac
