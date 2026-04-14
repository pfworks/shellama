"""sheLLaMa authentication — API keys with roles and per-key tracking."""
import json
import os
import time
from functools import wraps
from flask import request, jsonify

AUTH_FILE = os.environ.get('SHELLAMA_AUTH_FILE', '/etc/shellama/auth.json')

# Roles and their permissions
ROLE_PERMISSIONS = {
    'admin': {
        'endpoints': ['all'],
        'web_modify': True,
        'cloud_fallback': True,
    },
    'user': {
        'endpoints': ['chat', 'generate', 'explain', 'generate-code', 'explain-code',
                      'analyze', 'generate-image', 'upload', 'test', 'models',
                      'image-models', 'queue-status', 'cloud-costs', 'cost-history'],
        'web_modify': False,
        'cloud_fallback': True,
    },
    'viewer': {
        'endpoints': ['queue-status', 'models', 'image-models', 'cloud-costs',
                      'cost-history', 'ip-tokens', 'queue-history', 'usage-stats'],
        'web_modify': False,
        'cloud_fallback': False,
    },
}

# Read-only endpoints that don't need auth (status pages, static)
PUBLIC_PATHS = ['/', '/status', '/backends', '/stats', '/costs']

_config = None
_config_mtime = 0


def _load_config():
    """Load auth config, reload if file changed."""
    global _config, _config_mtime
    try:
        mtime = os.path.getmtime(AUTH_FILE)
        if _config is None or mtime > _config_mtime:
            with open(AUTH_FILE, 'r') as f:
                _config = json.load(f)
            _config_mtime = mtime
    except FileNotFoundError:
        _config = None
    return _config


def auth_enabled():
    """Check if auth is configured."""
    cfg = _load_config()
    return cfg is not None and bool(cfg.get('api_keys'))


def get_api_key_info(key):
    """Look up an API key, return its config or None."""
    cfg = _load_config()
    if not cfg:
        return None
    return cfg.get('api_keys', {}).get(key)


def check_endpoint_access(role, endpoint):
    """Check if a role can access an endpoint."""
    perms = ROLE_PERMISSIONS.get(role, {})
    allowed = perms.get('endpoints', [])
    if 'all' in allowed:
        return True
    # Strip leading / and match
    ep = endpoint.lstrip('/')
    return ep in allowed


def check_model_access(key_info, model):
    """Check if an API key can use a specific model."""
    models = key_info.get('models', ['all'])
    if 'all' in models:
        return True
    return model in models


def check_cloud_fallback(key_info):
    """Check if an API key can trigger cloud fallback."""
    role = key_info.get('role', 'viewer')
    # Per-key override
    if 'cloud_fallback' in key_info:
        return key_info['cloud_fallback']
    return ROLE_PERMISSIONS.get(role, {}).get('cloud_fallback', False)


def require_auth(f):
    """Decorator: require valid API key. Skips if auth not configured."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not auth_enabled():
            # No auth configured — allow everything
            request._shellama_key_info = None
            return f(*args, **kwargs)

        # Check for API key in header or query param
        key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '') or request.args.get('api_key')

        if not key:
            return jsonify({'error': 'API key required. Set X-API-Key header or Authorization: Bearer <key>'}), 401

        key_info = get_api_key_info(key)
        if not key_info:
            return jsonify({'error': 'Invalid API key'}), 401

        role = key_info.get('role', 'viewer')
        endpoint = request.path

        if not check_endpoint_access(role, endpoint):
            return jsonify({'error': f'Role "{role}" cannot access {endpoint}'}), 403

        # Check model access for endpoints that use models
        model = (request.json or {}).get('model', '') if request.is_json else ''
        if model and not check_model_access(key_info, model):
            return jsonify({'error': f'API key not authorized for model "{model}"'}), 403

        request._shellama_key_info = key_info
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Decorator: require admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not auth_enabled():
            return f(*args, **kwargs)

        key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '') or request.args.get('api_key')
        if not key:
            return jsonify({'error': 'Admin API key required'}), 401

        key_info = get_api_key_info(key)
        if not key_info or key_info.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403

        request._shellama_key_info = key_info
        return f(*args, **kwargs)
    return decorated


def get_key_name():
    """Get the name of the current API key, or 'anonymous'."""
    info = getattr(request, '_shellama_key_info', None)
    return info.get('name', 'unknown') if info else 'anonymous'
