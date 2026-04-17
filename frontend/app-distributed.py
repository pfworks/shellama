#!/export/ollama/bin/python3
from flask import Flask, request, jsonify, send_from_directory, redirect, session
import requests
import json
from queue import Queue, PriorityQueue
from threading import Thread, Lock
import time
import uuid
import os
import sys

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'shellama-default-secret-change-me')

# Auth setup
_proj = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
if _proj not in sys.path:
    sys.path.insert(0, _proj)
from shared.auth import require_auth, require_admin, get_key_name, auth_enabled, init_sso, get_oauth, sso_enabled, require_sso, get_web_role, record_rate_tokens

# Backend TLS client cert config (for frontend→backend mTLS)
_backend_cert = os.environ.get('SHELLAMA_BACKEND_CERT')
_backend_key = os.environ.get('SHELLAMA_BACKEND_KEY')
_backend_ca = os.environ.get('SHELLAMA_BACKEND_CA')
BACKEND_TLS = (_backend_cert, _backend_key) if _backend_cert and _backend_key else None
BACKEND_VERIFY = _backend_ca if _backend_ca else True  # True = default CA bundle, path = custom CA

def _backend_get(url, **kwargs):
    """GET request to a backend with optional mTLS."""
    return requests.get(url, cert=BACKEND_TLS, verify=BACKEND_VERIFY, **kwargs)

def _backend_post(url, **kwargs):
    """POST request to a backend with optional mTLS."""
    return requests.post(url, cert=BACKEND_TLS, verify=BACKEND_VERIFY, **kwargs)

# Persistence file
HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'shellama-history.json')

# Conversation memory (in-memory, expires after inactivity)
conversations = {}  # {conv_id: {'messages': [...], 'model': str, 'updated': timestamp}}
CONV_MAX_AGE = 28800  # 8 hours

# Per-IP token tracking
ip_token_history = {}  # {ip: [{timestamp, tokens}]}
ip_token_lock = Lock()
IP_HISTORY_MAX = 8640  # ~1 day at 10s intervals

# Per-backend token tracking (snapshots of cumulative totals)
backend_token_history = {}  # {url: [{timestamp, tokens}]}
last_backend_tokens = {}    # {url: last_known_total} for computing deltas

# Queue history for graphs
queue_history = {}  # {url: [{timestamp, queue_size}]}
QUEUE_HISTORY_MAX = 86400  # ~1 day at 1s intervals

# Persisted cumulative totals (survive frontend+backend restarts)
persisted_totals = {'requests': 0, 'tokens': 0, 'prompt_tokens': 0, 'response_tokens': 0}
last_backend_requests = {}  # {url: last_known_total} for computing deltas

# Per-client and per-task cumulative usage
# by_client: {ip: {requests: N, tokens: N}}
# by_task: {task_type: {requests: N, tokens: N}}  — aggregated across all IPs
usage_stats = {'by_client': {}, 'by_task': {}}


def load_history():
    global ip_token_history, backend_token_history, queue_history, persisted_totals
    global last_backend_tokens, last_backend_requests, usage_stats
    try:
        with open(HISTORY_FILE, 'r') as f:
            data = json.load(f)
            ip_token_history = data.get('ip_tokens', {})
            backend_token_history = data.get('backend_tokens', {})
            queue_history = data.get('queue', {})
            persisted_totals = data.get('totals', {'requests': 0, 'tokens': 0})
            last_backend_tokens = data.get('last_backend_tokens', {})
            last_backend_requests = data.get('last_backend_requests', {})
            usage_stats = data.get('usage_stats', {'by_client': {}, 'by_task': {}})
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def save_history():
    with ip_token_lock:
        data = {
            'ip_tokens': ip_token_history,
            'backend_tokens': backend_token_history,
            'queue': queue_history,
            'totals': persisted_totals,
            'last_backend_tokens': last_backend_tokens,
            'last_backend_requests': last_backend_requests,
            'usage_stats': usage_stats
        }
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def periodic_save():
    while True:
        time.sleep(60)
        save_history()


load_history()
Thread(target=periodic_save, daemon=True).start()

def record_ip_tokens(ip, tokens, task_type='unknown', prompt_tokens=0, response_tokens=0, cloud_fallback=False, key_name='anonymous', cached=False):
    """Record token usage for a client IP and task type"""
    with ip_token_lock:
        # Always update cumulative by_client and by_task
        if ip not in usage_stats['by_client']:
            usage_stats['by_client'][ip] = {'requests': 0, 'tokens': 0}
        usage_stats['by_client'][ip]['requests'] += 1
        usage_stats['by_client'][ip]['tokens'] += tokens
        if task_type not in usage_stats['by_task']:
            usage_stats['by_task'][task_type] = {'requests': 0, 'tokens': 0}
        usage_stats['by_task'][task_type]['requests'] += 1
        usage_stats['by_task'][task_type]['tokens'] += tokens
        # Accumulate prompt/response tokens for cloud cost tab (exclude test)
        if task_type != 'test':
            persisted_totals['prompt_tokens'] = persisted_totals.get('prompt_tokens', 0) + prompt_tokens
            persisted_totals['response_tokens'] = persisted_totals.get('response_tokens', 0) + response_tokens
        # Track actual cloud fallback spend separately
        if cloud_fallback:
            persisted_totals['fallback_prompt_tokens'] = persisted_totals.get('fallback_prompt_tokens', 0) + prompt_tokens
            persisted_totals['fallback_response_tokens'] = persisted_totals.get('fallback_response_tokens', 0) + response_tokens
            persisted_totals['fallback_requests'] = persisted_totals.get('fallback_requests', 0) + 1
        # Per-API-key tracking
        if key_name != 'anonymous':
            by_key = usage_stats.setdefault('by_key', {})
            if key_name not in by_key:
                by_key[key_name] = {'requests': 0, 'tokens': 0, 'prompt_tokens': 0, 'response_tokens': 0}
            by_key[key_name]['requests'] += 1
            by_key[key_name]['tokens'] += tokens
            by_key[key_name]['prompt_tokens'] += prompt_tokens
            by_key[key_name]['response_tokens'] += response_tokens
        # Track cached responses separately
        if cached:
            persisted_totals['cached_requests'] = persisted_totals.get('cached_requests', 0) + 1
            persisted_totals['cached_tokens'] = persisted_totals.get('cached_tokens', 0) + tokens
        # Record time-series entry only if there were tokens
        if tokens > 0 or cached:
            if ip not in ip_token_history:
                ip_token_history[ip] = []
            ip_token_history[ip].append({'timestamp': time.time(), 'tokens': tokens, 'task': task_type,
                                          'prompt_tokens': prompt_tokens, 'response_tokens': response_tokens,
                                          'cloud_fallback': cloud_fallback, 'cached': cached})
            if len(ip_token_history[ip]) > IP_HISTORY_MAX:
                ip_token_history[ip] = ip_token_history[ip][-IP_HISTORY_MAX:]

# Load backends from config file
def load_backends():
    config_file = os.path.join(os.path.dirname(__file__), 'backends.json')
    try:
        with open(config_file, 'r') as f:
            cfg = json.load(f)
            backends = cfg['backends']
            if backends and isinstance(backends[0], str):
                return [{'url': url, 'weight': 1, 'max_model': 'codellama:70b', 'tasks': ['all']} for url in backends]
            for b in backends:
                if 'max_model' not in b:
                    b['max_model'] = 'codellama:70b'
                if 'tasks' not in b:
                    b['tasks'] = ['all']
            return backends
    except:
        return [{'url': 'http://localhost:5001', 'weight': 1, 'max_model': 'codellama:70b', 'tasks': ['all']}]

def load_model_aliases():
    config_file = os.path.join(os.path.dirname(__file__), 'backends.json')
    try:
        with open(config_file, 'r') as f:
            return json.load(f).get('model_aliases', {})
    except:
        return {}

def save_backends():
    config_file = os.path.join(os.path.dirname(__file__), 'backends.json')
    try:
        with open(config_file, 'r') as f:
            cfg = json.load(f)
    except:
        cfg = {}
    cfg['backends'] = BACKENDS
    cfg['model_aliases'] = MODEL_ALIASES
    with open(config_file, 'w') as f:
        json.dump(cfg, f, indent=2)

BACKENDS = load_backends()
MODEL_ALIASES = load_model_aliases()

def resolve_model(model):
    """Resolve model alias to actual model name."""
    return MODEL_ALIASES.get(model, model)

# Model size ordering for comparison
MODEL_SIZES = {
    'codellama:7b': 2,
    'codellama:13b': 3,
    'codellama:34b': 4,
    'codellama:70b': 5,
    'deepseek-coder:1.3b': 1,
    'deepseek-coder:6.7b': 2,
    'deepseek-coder:33b': 4,
    'qwen2.5-coder:0.5b': 1,
    'qwen2.5-coder:1.5b': 1,
    'qwen2.5-coder:3b': 1,
    'qwen2.5-coder:7b': 2,
    'qwen2.5-coder:14b': 3,
    'qwen2.5-coder:32b': 4
}

# Track backend availability and queue size
backend_status = {b['url']: {'available': True, 'queue_size': 0, 'weight': b['weight'], 'max_model': b['max_model'], 'tasks': b.get('tasks', ['all'])} for b in BACKENDS}
backend_lock = Lock()

# Health check tracking
_health_failures = {b['url']: 0 for b in BACKENDS}  # consecutive failures
_health_status = {b['url']: 'unknown' for b in BACKENDS}  # healthy/unhealthy/unknown
HEALTH_FAIL_THRESHOLD = 3  # mark unhealthy after N consecutive failures
HEALTH_CHECK_INTERVAL = 30  # seconds

def _health_check_loop():
    """Background thread: ping backends periodically."""
    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)
        for backend in BACKENDS:
            url = backend['url']
            try:
                resp = _backend_get(f"{url}/queue-status", timeout=5)
                if resp.status_code == 200:
                    _health_failures[url] = 0
                    _health_status[url] = 'healthy'
                    continue
            except:
                pass
            _health_failures[url] = _health_failures.get(url, 0) + 1
            if _health_failures[url] >= HEALTH_FAIL_THRESHOLD:
                _health_status[url] = 'unhealthy'

Thread(target=_health_check_loop, daemon=True).start()

def get_backend_queue_size(url):
    """Check backend queue size and capacity stats"""
    try:
        resp = _backend_get(
            f"{url}/queue-status", 
            timeout=2
        )
        data = resp.json()
        return data
    except:
        return None

def get_available_backend(requested_model='codellama:13b', wait=True, timeout=300, task_type='unknown'):
    """Get backend with lowest weighted queue score that supports the requested model.
    Among same-weight backends, prefer those with more free RAM and lower CPU usage."""
    import time
    start_time = time.time()
    
    while True:
        # Poll backends WITHOUT holding the lock
        polled = {}
        for backend in BACKENDS:
            url = backend['url']
            data = get_backend_queue_size(url)
            if data:
                polled[url] = data

        with backend_lock:
            # Update status from polled data
            for backend in BACKENDS:
                url = backend['url']
                if url in polled:
                    data = polled[url]
                    backend_status[url]['queue_size'] = data.get('queue_size', 999)
                    backend_status[url]['cpu_percent'] = data.get('cpu_percent', 50)
                    backend_status[url]['ram_available_gb'] = data.get('ram_available_gb', 0)
                    backend_status[url]['ram_total_gb'] = data.get('ram_total_gb', 16)
                    backend_status[url]['cpu_arch'] = data.get('cpu_arch', 'x86_64')
                    backend_status[url]['cpu_count'] = data.get('cpu_count', 4)
                    backend_status[url]['cpu_freq_mhz'] = data.get('cpu_freq_mhz', 2000)
                else:
                    backend_status[url]['queue_size'] = 999
            
            # Filter backends that support the requested model
            requested_size = MODEL_SIZES.get(requested_model, 2)
            available = []
            for url in backend_status.keys():
                if backend_status[url]['available']:
                    # Skip unhealthy backends
                    if _health_status.get(url) == 'unhealthy':
                        continue
                    # Check task assignment
                    tasks = backend_status[url].get('tasks', ['all'])
                    if 'all' not in tasks and task_type not in tasks:
                        continue
                    max_model = backend_status[url]['max_model']
                    max_size = MODEL_SIZES.get(max_model, 4)
                    if requested_model == 'none' or requested_size <= max_size:
                        qs = backend_status[url]['queue_size']
                        w = backend_status[url]['weight']
                        cpu = backend_status[url].get('cpu_percent', 50)
                        ram = backend_status[url].get('ram_available_gb', 0)
                        # Score: lower is better
                        # queue_size is primary, weight reduces score
                        # cpu adds 0-1 penalty, total ram gives capacity bonus
                        # Apple Silicon (arm64) gets major bonus for unified memory / neural engine
                        # CPU frequency normalized to 5GHz scale
                        ram_total = backend_status[url].get('ram_total_gb', 16)
                        arch = backend_status[url].get('cpu_arch', 'x86_64')
                        freq = backend_status[url].get('cpu_freq_mhz', 2000)
                        arch_multiplier = 3.0 if arch == 'arm64' else 1.0
                        score = qs - (w * 0.1) + (cpu / 100.0) - (ram_total / 128.0) * arch_multiplier - (freq / 5000.0)
                        available.append((url, score))
            
            if available:
                best_backend = min(available, key=lambda x: x[1])[0]
                backend_status[best_backend]['available'] = False
                return best_backend
        
        # If no backend available and not waiting, return None
        if not wait:
            return None
        
        # Check timeout
        if time.time() - start_time > timeout:
            return None
        
        # Wait a bit before retrying
        time.sleep(0.5)

def release_backend(url):
    """Mark backend as available"""
    with backend_lock:
        backend_status[url]['available'] = True

# Prompt cache: {hash: {'result': {...}, 'time': timestamp}}
_prompt_cache = {}
CACHE_TTL = int(os.environ.get('SHELLAMA_CACHE_TTL', '300'))  # 5 min default, 0 = disabled
CACHE_MAX = 500  # max entries

# Audit log: optional request logging
AUDIT_LOG = os.environ.get('SHELLAMA_AUDIT_LOG', '')  # path to log file, empty = disabled
AUDIT_MAX_ENTRIES = 10000  # max in-memory entries for web view
_audit_entries = []
_audit_lock = Lock()

def _audit(client_ip, key_name, endpoint, model, prompt_preview, tokens, elapsed, cached=False, fallback=False):
    """Record an audit log entry."""
    if not AUDIT_LOG and not persisted_totals.get('audit_enabled'):
        return
    entry = {
        'timestamp': time.time(),
        'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'client_ip': client_ip or '',
        'key_name': key_name or 'anonymous',
        'endpoint': endpoint,
        'model': model or '',
        'prompt': prompt_preview[:200] if prompt_preview else '',
        'tokens': tokens,
        'elapsed': elapsed,
        'cached': cached,
        'fallback': fallback,
    }
    with _audit_lock:
        _audit_entries.append(entry)
        if len(_audit_entries) > AUDIT_MAX_ENTRIES:
            _audit_entries.pop(0)
    if AUDIT_LOG:
        try:
            with open(AUDIT_LOG, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass

def _cache_key(endpoint, data):
    """Generate cache key from endpoint + model + content."""
    import hashlib
    # Only cache deterministic requests — skip if conversation_id present
    if data.get('conversation_id') or data.get('messages') or data.get('force_cloud'):
        return None
    content = data.get('message', '') or data.get('commands', '') or data.get('description', '') or data.get('code', '') or data.get('playbook', '')
    if not content:
        return None
    model = data.get('model', '')
    raw = f"{endpoint}:{model}:{content}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def proxy_request(endpoint, data, client_ip=None, task_type='unknown'):
    """Send request to available backend with keepalive"""
    model = resolve_model(data.get('model', 'codellama:13b'))
    data['model'] = model  # pass resolved name to backend

    # Check prompt cache
    ck = _cache_key(endpoint, data) if CACHE_TTL > 0 else None
    if ck and ck in _prompt_cache:
        entry = _prompt_cache[ck]
        if time.time() - entry['time'] < CACHE_TTL:
            result = dict(entry['result'])
            result['cached'] = True
            if client_ip:
                record_ip_tokens(client_ip, result.get('total_tokens', 0), task_type,
                               prompt_tokens=result.get('prompt_tokens', 0),
                               response_tokens=result.get('response_tokens', 0),
                               key_name=get_key_name(), cached=True)
            prompt_preview = data.get('message', '') or data.get('commands', '') or data.get('description', '') or data.get('code', '') or ''
            _audit(client_ip, get_key_name(), endpoint, data.get('model', ''),
                   prompt_preview, result.get('total_tokens', 0), 0, cached=True)
            return result, 200
        else:
            del _prompt_cache[ck]

    backend = get_available_backend(model, task_type=task_type)
    if not backend:
        return {'error': f'No backends available that support model {model}. Check backends.json configuration.'}, 200
    
    # Forward client info to backend for tracking
    if client_ip:
        data['client_ip'] = client_ip
    
    max_retries = 2
    tried = set()
    last_error = None

    for attempt in range(max_retries + 1):
        if not backend:
            break
        tried.add(backend)

        try:
            session = requests.Session()
            session.headers.update({'Connection': 'keep-alive'})
            if BACKEND_TLS:
                session.cert = BACKEND_TLS
                session.verify = BACKEND_VERIFY
            
            response = session.post(
                f"{backend}{endpoint}", 
                json=data, 
                timeout=3600,
                stream=False
            )
            result = response.json()
            
            # Check if result was lost — retry on different backend
            if result.get('error') and 'result was lost' in result.get('error', ''):
                last_error = f"Backend {backend} lost task result"
                release_backend(backend)
                backend = get_available_backend(model, task_type=task_type)
                continue
            
            # Auto-fallback: if backend suggests fallback and auto mode is on, retry with force_cloud
            if result.get('fallback_available') and persisted_totals.get('auto_fallback', False):
                data['force_cloud'] = True
                release_backend(backend)
                backend2 = get_available_backend(model, task_type=task_type)
                if backend2:
                    resp2 = session.post(f"{backend2}{endpoint}", json=data, timeout=3600, stream=False)
                    result = resp2.json()
                    release_backend(backend2)
        
            # Record tokens for this client IP
            if client_ip:
                record_ip_tokens(client_ip, result.get('total_tokens', 0), task_type,
                               prompt_tokens=result.get('prompt_tokens', 0),
                               response_tokens=result.get('response_tokens', 0),
                               cloud_fallback=result.get('cloud_fallback', False),
                               key_name=get_key_name())
            # Record tokens for rate limiting
            rate_key = getattr(request, '_shellama_key', None)
            if rate_key:
                record_rate_tokens(rate_key, result.get('total_tokens', 0),
                                  prompt_tokens=result.get('prompt_tokens', 0),
                                  response_tokens=result.get('response_tokens', 0),
                                  cloud_fallback=result.get('cloud_fallback', False))

            # Audit log
            prompt_preview = data.get('message', '') or data.get('commands', '') or data.get('description', '') or data.get('code', '') or data.get('playbook', '')
            _audit(client_ip, get_key_name(), endpoint, data.get('model', ''),
                   prompt_preview, result.get('total_tokens', 0), result.get('elapsed', 0),
                   fallback=result.get('cloud_fallback', False))
            
            # Store in prompt cache
            if ck and not result.get('error') and not result.get('cloud_fallback'):
                if len(_prompt_cache) >= CACHE_MAX:
                    oldest = min(_prompt_cache, key=lambda k: _prompt_cache[k]['time'])
                    del _prompt_cache[oldest]
                _prompt_cache[ck] = {'result': result, 'time': time.time()}

            if attempt > 0:
                result['retried'] = attempt
            release_backend(backend)
            return result, 200

        except requests.exceptions.Timeout:
            last_error = f'Backend {backend} timed out'
            release_backend(backend)
            _health_failures[backend] = _health_failures.get(backend, 0) + 1
            backend = get_available_backend(model, task_type=task_type)
            continue
        except Exception as e:
            last_error = f'Backend {backend}: {str(e)}'
            release_backend(backend)
            _health_failures[backend] = _health_failures.get(backend, 0) + 1
            backend = get_available_backend(model, task_type=task_type)
            continue

    return {'error': f'All backends failed. Last error: {last_error}'}, 500

def split_and_process(commands, model, chunk_size=10):
    """Split commands into chunks and process in parallel"""
    lines = commands.strip().split('\n')
    if len(lines) <= chunk_size:
        return proxy_request('/generate', {'commands': commands, 'model': model})
    
    # Split into chunks
    chunks = ['\n'.join(lines[i:i+chunk_size]) for i in range(0, len(lines), chunk_size)]
    results = []
    threads = []
    
    def process_chunk(chunk, idx):
        result, _ = proxy_request('/generate', {'commands': chunk, 'model': model})
        results.append((idx, result))
    
    for idx, chunk in enumerate(chunks):
        t = Thread(target=process_chunk, args=(chunk, idx))
        t.start()
        threads.append(t)
    
    for t in threads:
        t.join()
    
    # Combine results
    results.sort(key=lambda x: x[0])
    combined = '\n---\n'.join([r[1].get('playbook', '') for r in results])
    total_time = sum([r[1].get('elapsed', 0) for r in results])
    
    return {
        'playbook': combined,
        'elapsed': round(max([r[1].get('elapsed', 0) for r in results]), 2),
        'total_tokens': sum([r[1].get('total_tokens', 0) for r in results]),
        'chunks_processed': len(chunks)
    }, 200

@app.route('/')
def index():
    from flask import redirect
    return redirect('/status')

@app.route('/status')
@require_sso
def status_page():
    return send_from_directory('/export/html', 'status.html')

@app.route('/backends')
@require_sso
def backends_page():
    return send_from_directory('/export/html', 'backends.html')

@app.route('/stats')
@require_sso
def stats_page():
    return send_from_directory('/export/html', 'stats.html')

@app.route('/costs')
@require_sso
def costs_page():
    return send_from_directory('/export/html', 'costs.html')

@app.route('/queue-status')
def queue_status():
    """Aggregate queue status from all backends"""
    backends_info = []
    total_queue = 0
    active_count = 0
    
    for backend in BACKENDS:
        url = backend['url']
        weight = backend['weight']
        max_model = backend.get('max_model', 'codellama:70b')
        try:
            resp = _backend_get(
                f"{url}/queue-status", 
                timeout=2
            )
            data = resp.json()
            queue_size = data.get('queue_size', 0)
            total_queue += queue_size
            is_active = data.get('active', False)
            if is_active:
                active_count += 1
            
            cpu_pct = data.get('cpu_percent', 0)
            ram_avail = data.get('ram_available_gb', 0)
            ram_total = data.get('ram_total_gb', 0)
            backends_info.append({
                'url': url,
                'weight': weight,
                'max_model': max_model, 'tasks': backend.get('tasks', ['all']),
                'queue_size': queue_size,
                'active': is_active,
                'status': 'online',
                'health': _health_status.get(url, 'unknown'),
                'active_model': data.get('active_model', 'none'),
                'active_type': data.get('active_type', ''),
                'active_client': data.get('active_client', ''),
                'active_agent': data.get('active_agent', ''),
                'active_summary': data.get('active_summary', ''),
                'backend_tokens': data.get('total_tokens', 0),
                'backend_requests': data.get('total_requests', 0),
                'cpu_percent': cpu_pct,
                'ram_available_gb': ram_avail,
                'ram_total_gb': ram_total,
                'cpu_arch': data.get('cpu_arch', 'x86_64'),
                'cpu_count': data.get('cpu_count', 0),
                'cpu_freq_mhz': data.get('cpu_freq_mhz', 0)
            })
        except:
            backends_info.append({
                'url': url,
                'weight': weight,
                'max_model': max_model, 'tasks': backend.get('tasks', ['all']),
                'queue_size': 0,
                'active': False,
                'status': 'offline',
                'health': 'unhealthy',
                'active_model': 'none',
                'backend_tokens': 0,
                'backend_requests': 0,
                'cpu_percent': 0,
                'ram_available_gb': 0,
                'ram_total_gb': 0,
                'cpu_arch': 'unknown',
                'cpu_count': 0,
                'cpu_freq_mhz': 0
            })
    
    # Record per-backend token/request deltas and queue history
    now = time.time()
    with ip_token_lock:
        for b in backends_info:
            url = b['url']
            # Token deltas — detect backend restart (current < previous)
            cur_tokens = b.get('backend_tokens', 0)
            prev_tokens = last_backend_tokens.get(url, 0)
            if cur_tokens < prev_tokens:
                # Backend restarted, treat entire current value as new
                delta_tokens = cur_tokens
            else:
                delta_tokens = cur_tokens - prev_tokens
            last_backend_tokens[url] = cur_tokens
            if delta_tokens > 0:
                persisted_totals['tokens'] += delta_tokens
                if url not in backend_token_history:
                    backend_token_history[url] = []
                backend_token_history[url].append({'timestamp': now, 'tokens': delta_tokens})
                if len(backend_token_history[url]) > IP_HISTORY_MAX:
                    backend_token_history[url] = backend_token_history[url][-IP_HISTORY_MAX:]
            # Request deltas
            cur_reqs = b.get('backend_requests', 0)
            prev_reqs = last_backend_requests.get(url, 0)
            if cur_reqs < prev_reqs:
                delta_reqs = cur_reqs
            else:
                delta_reqs = cur_reqs - prev_reqs
            last_backend_requests[url] = cur_reqs
            if delta_reqs > 0:
                persisted_totals['requests'] += delta_reqs
            # Queue history
            if url not in queue_history:
                queue_history[url] = []
            queue_history[url].append({'timestamp': now, 'queue_size': b.get('queue_size', 0)})
            if len(queue_history[url]) > QUEUE_HISTORY_MAX:
                queue_history[url] = queue_history[url][-QUEUE_HISTORY_MAX:]

    return jsonify({
        'queue_size': total_queue,
        'active': active_count > 0,
        'active_backends': active_count,
        'total_backends': len(BACKENDS),
        'total_requests': persisted_totals['requests'],
        'total_tokens': persisted_totals['tokens'],
        'backends': backends_info,
        'timestamp': time.time(),
        'auto_fallback': persisted_totals.get('auto_fallback', False),
        'model_aliases': MODEL_ALIASES
    })

@app.route('/stop-all', methods=['POST'])
@require_admin
def stop_all():
    """Stop processing on all backends"""
    results = {}
    for backend in BACKENDS:
        url = backend['url']
        try:
            resp = _backend_post(f"{url}/stop", timeout=10)
            results[url] = resp.json()
        except Exception as e:
            results[url] = {'error': str(e)}
    return jsonify(results)

@app.route('/stop-backend', methods=['POST'])
@require_admin
def stop_backend():
    """Stop processing on a specific backend"""
    url = request.json.get('url', '')
    if not url:
        return jsonify({'error': 'No backend URL provided'}), 400
    try:
        resp = _backend_post(f"{url}/stop", timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate', methods=['POST'])
@require_auth
def generate():
    commands = request.json.get('commands', '')
    model = request.json.get('model', 'codellama:13b')
    split = request.json.get('split', False)
    client_ip = request.remote_addr
    
    if split:
        result, status = split_and_process(commands, model)
    else:
        result, status = proxy_request('/generate', {'commands': commands, 'model': model}, client_ip, 'shell2ansible')
    
    return jsonify(result), status

@app.route('/explain', methods=['POST'])
@require_auth
def explain():
    playbook = request.json.get('playbook', '')
    model = request.json.get('model', 'codellama:13b')
    result, status = proxy_request('/explain', {'playbook': playbook, 'model': model}, request.remote_addr, 'explain')
    return jsonify(result), status

@app.route('/generate-code', methods=['POST'])
@require_auth
def generate_code_endpoint():
    description = request.json.get('description', '')
    model = request.json.get('model', 'codellama:13b')
    result, status = proxy_request('/generate-code', {'description': description, 'model': model}, request.remote_addr, 'generate-code')
    return jsonify(result), status

@app.route('/explain-code', methods=['POST'])
@require_auth
def explain_code_endpoint():
    code = request.json.get('code', '')
    model = request.json.get('model', 'codellama:13b')
    result, status = proxy_request('/explain-code', {'code': code, 'model': model}, request.remote_addr, 'explain-code')
    return jsonify(result), status

@app.route('/chat', methods=['POST'])
@require_auth
def chat_endpoint():
    message = request.json.get('message', '')
    model = resolve_model(request.json.get('model', 'codellama:13b'))
    conv_id = request.json.get('conversation_id')
    system_prompt = request.json.get('system_prompt')

    # Expire old conversations
    now = time.time()
    expired = [k for k, v in conversations.items() if now - v['updated'] > CONV_MAX_AGE]
    for k in expired:
        del conversations[k]

    # Build messages from conversation history
    messages = None
    if conv_id:
        conv = conversations.get(conv_id)
        if conv:
            messages = conv['messages'] + [{'role': 'user', 'content': message}]
        else:
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': message})
    elif system_prompt:
        messages = [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': message}]

    payload = {'message': message, 'model': model}
    if messages:
        payload['messages'] = messages

    result, status = proxy_request('/chat', payload, request.remote_addr, 'chat')

    # Store conversation if conv_id provided
    if conv_id and not result.get('error'):
        if conv_id not in conversations:
            conversations[conv_id] = {'messages': [], 'model': model, 'updated': now}
            if system_prompt:
                conversations[conv_id]['messages'].append({'role': 'system', 'content': system_prompt})
        conversations[conv_id]['messages'].append({'role': 'user', 'content': message})
        conversations[conv_id]['messages'].append({'role': 'assistant', 'content': result.get('response', '')})
        conversations[conv_id]['updated'] = now
        result['conversation_id'] = conv_id

    return jsonify(result), status

@app.route('/analyze', methods=['POST'])
@require_auth
def analyze_endpoint():
    files = request.json.get('files', [])
    model = request.json.get('model', 'codellama:13b')
    client_ip = request.remote_addr
    
    # If we have multiple files, check if we should process in parallel or sequential
    if len(files) > 1:
        # Count available backends that support this model
        requested_size = MODEL_SIZES.get(model, 2)
        available_backends = 0
        for backend in BACKENDS:
            max_size = MODEL_SIZES.get(backend.get('max_model', 'codellama:70b'), 4)
            if requested_size <= max_size:
                available_backends += 1
        
        # If only 1 backend, process sequentially to avoid timeout
        if available_backends <= 1:
            combined_parts = []
            total_elapsed = 0
            total_tokens = 0
            
            for idx, file_data in enumerate(files):
                result, status = proxy_request('/analyze', {'files': [file_data], 'model': model}, client_ip, 'analyze')
                if result.get('error'):
                    return jsonify({'error': f"Error processing {file_data.get('path', f'file {idx}')}: {result['error']}"}), 200
                
                analysis = result.get('analysis', '')
                file_path = file_data.get('path', f'File {idx+1}')
                combined_parts.append(f"--- {file_path} ---\n{analysis}")
                total_elapsed = max(total_elapsed, result.get('elapsed', 0))
                total_tokens += result.get('total_tokens', 0)
            
            return jsonify({
                'analysis': "\n\n".join(combined_parts),
                'elapsed': round(total_elapsed, 2),
                'total_tokens': total_tokens,
                'files_processed': len(files),
                'parallel': False
            }), 200
        
        # Multiple backends available, process in parallel in batches
        results = []

        for batch_start in range(0, len(files), available_backends):
            batch = files[batch_start:batch_start + available_backends]
            threads = []
            batch_results = []

            def process_file(file_data, idx, out):
                result, status = proxy_request('/analyze', {'files': [file_data], 'model': model}, client_ip, 'analyze')
                out.append((idx, result, status))

            for i, file_data in enumerate(batch):
                t = Thread(target=process_file, args=(file_data, batch_start + i, batch_results))
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

            results.extend(batch_results)

        # Check for errors
        errors = [r[1].get('error') for r in results if r[1].get('error')]
        if errors:
            return jsonify({'error': f"Errors from backends: {'; '.join(set(errors))}"}), 200
        
        # Combine analyses
        results.sort(key=lambda x: x[0])
        combined_parts = []
        for idx, (_, result, _) in enumerate(results, 1):
            analysis = result.get('analysis', '')
            file_path = files[idx-1].get('path', f'File {idx}')
            combined_parts.append(f"--- {file_path} ---\n{analysis}")
        
        combined_analysis = "\n\n".join(combined_parts)
        
        total_elapsed = max([r[1].get('elapsed', 0) for r in results])
        total_tokens = sum([r[1].get('total_tokens', 0) for r in results])
        
        return jsonify({
            'analysis': combined_analysis,
            'elapsed': round(total_elapsed, 2),
            'total_tokens': total_tokens,
            'files_processed': len(files),
            'parallel': True
        }), 200
    else:
        # Single file processing
        result, status = proxy_request('/analyze', {'files': files, 'model': model}, client_ip, 'analyze')
        return jsonify(result), status

@app.route('/ip-tokens')
def ip_tokens():
    """Return token usage history per client IP and per backend"""
    with ip_token_lock:
        result = {ip: entries for ip, entries in ip_token_history.items()}
        for url, entries in backend_token_history.items():
            result[f"backend:{url}"] = entries
        return jsonify(result)

@app.route('/queue-history')
def get_queue_history():
    """Return persisted queue history for graphs."""
    with ip_token_lock:
        return jsonify(queue_history)

@app.route('/usage-stats')
def get_usage_stats():
    """Return cumulative token/request usage by client IP and by task type."""
    with ip_token_lock:
        return jsonify(usage_stats)

@app.route('/generate-image', methods=['POST'])
@require_auth
def generate_image_endpoint():
    data = request.json
    client_ip = request.remote_addr
    if client_ip:
        data['client_ip'] = client_ip

    # Image generation doesn't use an LLM — try each backend until one succeeds
    errors = []
    for b in BACKENDS:
        try:
            _backend_get(f"{b['url']}/queue-status", timeout=2)
            resp = _backend_post(f"{b['url']}/generate-image", json=data, timeout=3600)
            result = resp.json()
            if result.get('error'):
                errors.append(f"{b['url']}: {result['error']}")
                continue
            if client_ip:
                record_ip_tokens(client_ip, result.get('total_tokens', 0), 'generate-image')
            return jsonify(result), 200
        except:
            errors.append(f"{b['url']}: unreachable")
            continue
    return jsonify({'error': 'All backends failed: ' + '; '.join(errors)}), 200

@app.route('/image-models')
def image_models():
    """Proxy to any online backend"""
    for backend in BACKENDS:
        try:
            resp = _backend_get(f"{backend['url']}/image-models", timeout=5)
            return jsonify(resp.json())
        except:
            continue
    return jsonify({'models': []})

@app.route('/models')
def list_models():
    """Aggregate models from all backends, deduplicated."""
    seen = {}
    for backend in BACKENDS:
        try:
            resp = _backend_get(f"{backend['url']}/models", timeout=5)
            for m in resp.json().get('models', []):
                seen[m['name']] = m
        except:
            continue
    return jsonify({'models': sorted(seen.values(), key=lambda m: m['name'])})

@app.route('/test', methods=['POST'])
@require_auth
def test_models():
    """Benchmark models with optional custom prompt. Returns results + cloud cost estimates."""
    _proj = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    if _proj not in sys.path:
        sys.path.insert(0, _proj)
    from shared.constants import TEST_PROMPT, model_size, cloud_cost_estimates, fetch_cloud_pricing

    data = request.json or {}
    prompt = data.get('prompt', TEST_PROMPT)
    model_filter = data.get('model', 'all')
    client_ip = request.remote_addr

    # Get available models from any reachable backend
    all_models = []
    for b in BACKENDS:
        try:
            resp = _backend_get(f"{b['url']}/models", timeout=5)
            all_models = [m['name'] for m in resp.json().get('models', [])]
            if all_models:
                break
        except:
            continue
    if not all_models:
        return jsonify({'error': 'No models available'}), 200

    # Filter models
    if model_filter == 'all':
        max_sizes = []
        for b in BACKENDS:
            try:
                _backend_get(f"{b['url']}/queue-status", timeout=2)
                max_sizes.append(model_size(b.get('max_model', '')))
            except:
                pass
        max_avail = max(max_sizes) if max_sizes else 999
        test_list = [m for m in all_models if model_size(m) <= max_avail]
        skipped = [m for m in all_models if model_size(m) > max_avail]
    else:
        test_list = [m for m in all_models if model_filter in m]
        skipped = []

    if not test_list:
        return jsonify({'error': f'No models matching "{model_filter}"'}), 200

    results = []
    for m in test_list:
        result, status = proxy_request('/chat', {'message': prompt, 'model': m}, client_ip, 'test')
        if result.get('error'):
            results.append({'model': m, 'error': result['error']})
            continue
        p = result.get('prompt_tokens', 0)
        r = result.get('response_tokens', 0)
        t = result.get('total_tokens', 0)
        e = result.get('elapsed', 0)
        results.append({
            'model': m, 'elapsed': e, 'prompt_tokens': p,
            'response_tokens': r, 'total_tokens': t,
            'tok_per_sec': round(r / e, 1) if e > 0 else 0,
        })

    # Cloud cost estimates using average tokens (refresh pricing from OpenRouter)
    ok = [r for r in results if 'error' not in r and r.get('total_tokens', 0) > 0]
    costs = []
    pricing_source = 'none'
    if ok:
        avg_p = sum(r['prompt_tokens'] for r in ok) // len(ok)
        avg_r = sum(r['response_tokens'] for r in ok) // len(ok)
        fetch_cloud_pricing()  # refresh from OpenRouter (or fall back to static)
        costs, pricing_source = cloud_cost_estimates(avg_p, avg_r)

    return jsonify({
        'prompt': prompt,
        'results': results,
        'skipped': skipped,
        'cloud_costs': costs,
        'pricing_source': pricing_source,
    }), 200

@app.route('/cloud-costs')
def cloud_costs_tab():
    """Running tab: hypothetical cloud costs + actual fallback costs."""
    _proj = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    if _proj not in sys.path:
        sys.path.insert(0, _proj)
    from shared.constants import cloud_cost_estimates, get_cloud_pricing

    with ip_token_lock:
        p_tok = persisted_totals.get('prompt_tokens', 0)
        r_tok = persisted_totals.get('response_tokens', 0)
        fb_p = persisted_totals.get('fallback_prompt_tokens', 0)
        fb_r = persisted_totals.get('fallback_response_tokens', 0)
        fb_reqs = persisted_totals.get('fallback_requests', 0)
        c_reqs = persisted_totals.get('cached_requests', 0)
        c_tok = persisted_totals.get('cached_tokens', 0)

    hypothetical, source = cloud_cost_estimates(p_tok, r_tok)
    actual, _ = cloud_cost_estimates(fb_p, fb_r)
    return jsonify({
        'prompt_tokens': p_tok,
        'response_tokens': r_tok,
        'total_tokens': p_tok + r_tok,
        'cloud_costs': hypothetical,
        'pricing_source': source,
        'note': 'Excludes tokens from /test benchmarks',
        'fallback': {
            'prompt_tokens': fb_p,
            'response_tokens': fb_r,
            'total_tokens': fb_p + fb_r,
            'requests': fb_reqs,
            'cloud_costs': actual,
        },
        'cached': {
            'requests': c_reqs,
            'tokens_saved': c_tok,
        },
    })

@app.route('/reset-stats', methods=['POST'])
@require_admin
def reset_stats():
    """Reset request/token counters."""
    with ip_token_lock:
        persisted_totals['requests'] = 0
        persisted_totals['tokens'] = 0
    save_history()
    return jsonify({'status': 'ok'})

@app.route('/reset-cloud-costs', methods=['POST'])
@require_admin
def reset_cloud_costs():
    """Reset cloud cost running tab."""
    with ip_token_lock:
        persisted_totals['prompt_tokens'] = 0
        persisted_totals['response_tokens'] = 0
        persisted_totals['fallback_prompt_tokens'] = 0
        persisted_totals['fallback_response_tokens'] = 0
        persisted_totals['fallback_requests'] = 0
        persisted_totals['cached_requests'] = 0
        persisted_totals['cached_tokens'] = 0
    save_history()
    return jsonify({'status': 'ok'})

@app.route('/reset-all', methods=['POST'])
@require_admin
def reset_all():
    """Reset all counters."""
    with ip_token_lock:
        persisted_totals['requests'] = 0
        persisted_totals['tokens'] = 0
        persisted_totals['prompt_tokens'] = 0
        persisted_totals['response_tokens'] = 0
        persisted_totals['fallback_prompt_tokens'] = 0
        persisted_totals['fallback_response_tokens'] = 0
        persisted_totals['fallback_requests'] = 0
        persisted_totals['cached_requests'] = 0
        persisted_totals['cached_tokens'] = 0
    save_history()
    return jsonify({'status': 'ok'})

@app.route('/cost-history')
def cost_history():
    """Return token totals filtered by time range for cost calculations."""
    _proj = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    if _proj not in sys.path:
        sys.path.insert(0, _proj)
    from shared.constants import cloud_cost_estimates

    since = request.args.get('since', '0')
    until = request.args.get('until', '')
    try:
        since_ts = float(since)
    except:
        since_ts = 0
    until_ts = float(until) if until else time.time()

    p_tok = r_tok = fb_p = fb_r = fb_reqs = total_reqs = c_reqs = c_tok = 0
    with ip_token_lock:
        for ip, entries in ip_token_history.items():
            for e in entries:
                ts = e.get('timestamp', 0)
                if ts < since_ts or ts > until_ts:
                    continue
                if e.get('task') == 'test':
                    continue
                pt = e.get('prompt_tokens', 0)
                rt = e.get('response_tokens', 0)
                p_tok += pt
                r_tok += rt
                total_reqs += 1
                if e.get('cloud_fallback'):
                    fb_p += pt
                    fb_r += rt
                    fb_reqs += 1
                if e.get('cached'):
                    c_reqs += 1
                    c_tok += e.get('tokens', 0)

    hypothetical, source = cloud_cost_estimates(p_tok, r_tok)
    actual, _ = cloud_cost_estimates(fb_p, fb_r)
    return jsonify({
        'since': since_ts, 'until': until_ts,
        'requests': total_reqs,
        'prompt_tokens': p_tok, 'response_tokens': r_tok, 'total_tokens': p_tok + r_tok,
        'cloud_costs': hypothetical, 'pricing_source': source,
        'fallback': {
            'requests': fb_reqs, 'prompt_tokens': fb_p, 'response_tokens': fb_r,
            'total_tokens': fb_p + fb_r, 'cloud_costs': actual,
        },
        'cached': {
            'requests': c_reqs,
            'tokens_saved': c_tok,
        },
    })

def _require_secure_admin():
    """Check SSO is active, HTTPS is on, and user is admin. Returns error tuple or None."""
    errors = []
    if not sso_enabled():
        errors.append('SSO')
    if not request.is_secure and not os.environ.get('SHELLAMA_TLS_CERT'):
        errors.append('HTTPS')
    if errors:
        return jsonify({'error': f'Key management requires {" and ".join(errors)} to be configured'}), 403
    if get_web_role() != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    return None

@app.route('/api/audit', methods=['GET'])
@require_sso
def api_audit_log():
    """View audit log (SSO admin + HTTPS only)."""
    err = _require_secure_admin()
    if err:
        return err
    limit = int(request.args.get('limit', 100))
    since = float(request.args.get('since', 0))
    with _audit_lock:
        entries = [e for e in _audit_entries if e['timestamp'] > since]
    return jsonify({'entries': entries[-limit:], 'total': len(entries)})

@app.route('/api/audit/toggle', methods=['POST'])
@require_sso
def api_audit_toggle():
    """Enable/disable audit logging (SSO admin + HTTPS only)."""
    err = _require_secure_admin()
    if err:
        return err
    enabled = (request.json or {}).get('enabled', False)
    with ip_token_lock:
        persisted_totals['audit_enabled'] = bool(enabled)
    save_history()
    return jsonify({'audit_enabled': bool(enabled)})

@app.route('/api/audit/status')
def api_audit_status():
    """Check if audit logging is enabled."""
    return jsonify({
        'audit_enabled': bool(AUDIT_LOG) or persisted_totals.get('audit_enabled', False),
        'file_log': AUDIT_LOG or None,
        'entries_in_memory': len(_audit_entries),
    })

@app.route('/api/keys', methods=['GET'])
@require_sso
def api_keys_list():
    """List API keys (SSO admin + HTTPS only, keys are masked)."""
    err = _require_secure_admin()
    if err:
        return err
    from shared.auth import _load_config
    cfg = _load_config()
    if not cfg:
        return jsonify({'keys': []})
    keys = []
    for k, v in cfg.get('api_keys', {}).items():
        keys.append({
            'key_masked': k[:6] + '...' + k[-4:],
            'key_id': k[:8],
            'name': v.get('name', ''),
            'role': v.get('role', 'viewer'),
            'models': v.get('models', ['all']),
            'cloud_fallback': v.get('cloud_fallback', True),
        })
    return jsonify({'keys': keys})

@app.route('/api/keys', methods=['POST'])
@require_sso
def api_keys_create():
    """Create a new API key (SSO admin + HTTPS only)."""
    err = _require_secure_admin()
    if err:
        return err
    import secrets
    from shared.auth import _load_config, AUTH_FILE
    data = request.json or {}
    name = data.get('name', '')
    role = data.get('role', 'user')
    models = data.get('models', ['all'])
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if role not in ('admin', 'user', 'viewer'):
        return jsonify({'error': 'Role must be admin, user, or viewer'}), 400
    key = 'sk-' + secrets.token_hex(16)
    cfg = _load_config() or {'api_keys': {}}
    cfg.setdefault('api_keys', {})
    cfg['api_keys'][key] = {'name': name, 'role': role, 'models': models}
    if 'cloud_fallback' in data:
        cfg['api_keys'][key]['cloud_fallback'] = data['cloud_fallback']
    with open(AUTH_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)
    return jsonify({'key': key, 'name': name, 'role': role})

@app.route('/api/keys/revoke', methods=['POST'])
@require_sso
def api_keys_revoke():
    """Revoke an API key by key_id prefix (SSO admin + HTTPS only)."""
    err = _require_secure_admin()
    if err:
        return err
    from shared.auth import _load_config, AUTH_FILE
    key_id = (request.json or {}).get('key_id', '')
    if not key_id:
        return jsonify({'error': 'key_id required'}), 400
    cfg = _load_config()
    if not cfg:
        return jsonify({'error': 'No auth config'}), 404
    for k in list(cfg.get('api_keys', {}).keys()):
        if k.startswith(key_id):
            name = cfg['api_keys'][k].get('name', 'unknown')
            del cfg['api_keys'][k]
            with open(AUTH_FILE, 'w') as f:
                json.dump(cfg, f, indent=2)
            return jsonify({'status': 'ok', 'revoked': name})
    return jsonify({'error': 'Key not found'}), 404

@app.route('/api/model-aliases', methods=['GET', 'POST'])
def api_model_aliases():
    """Get or update model aliases."""
    global MODEL_ALIASES
    if request.method == 'POST':
        # Require admin (API key or SSO)
        if auth_enabled():
            key = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            if key:
                from shared.auth import get_api_key_info
                info = get_api_key_info(key)
                if not info or info.get('role') != 'admin':
                    return jsonify({'error': 'Admin access required'}), 403
            elif sso_enabled():
                if get_web_role() != 'admin':
                    return jsonify({'error': 'Admin access required'}), 403
            else:
                return jsonify({'error': 'Admin access required'}), 403
        data = request.json or {}
        if 'aliases' in data:
            MODEL_ALIASES = data['aliases']
        elif 'set' in data:
            MODEL_ALIASES[data['set']['alias']] = data['set']['model']
        elif 'delete' in data:
            MODEL_ALIASES.pop(data['delete'], None)
        save_backends()
        return jsonify({'model_aliases': MODEL_ALIASES})
    return jsonify({'model_aliases': MODEL_ALIASES})

@app.route('/api/backends', methods=['GET', 'POST'])
@require_admin
def api_backends():
    """Get or update backend configuration (tasks, weight, max_model)."""
    if request.method == 'POST':
        updates = request.json or {}
        url = updates.get('url', '')
        for b in BACKENDS:
            if b['url'] == url:
                if 'tasks' in updates:
                    b['tasks'] = updates['tasks']
                    with backend_lock:
                        backend_status[url]['tasks'] = updates['tasks']
                if 'weight' in updates:
                    b['weight'] = updates['weight']
                    with backend_lock:
                        backend_status[url]['weight'] = updates['weight']
                if 'max_model' in updates:
                    b['max_model'] = updates['max_model']
                    with backend_lock:
                        backend_status[url]['max_model'] = updates['max_model']
                save_backends()
                return jsonify({'status': 'ok', 'backend': b})
        return jsonify({'error': 'Backend not found'}), 404
    return jsonify({'backends': BACKENDS})

@app.route('/auto-fallback', methods=['GET', 'POST'])
@require_admin
def auto_fallback_setting():
    """Get or set auto-fallback mode. When enabled, clients skip confirmation."""
    if request.method == 'POST':
        val = (request.json or {}).get('enabled', False)
        with ip_token_lock:
            persisted_totals['auto_fallback'] = bool(val)
        save_history()
        return jsonify({'auto_fallback': bool(val)})
    return jsonify({'auto_fallback': persisted_totals.get('auto_fallback', False)})

# --- OpenAI-Compatible API ---

@app.route('/v1/models', methods=['GET'])
def v1_models():
    """OpenAI-compatible model list."""
    models = []
    seen = set()
    for backend in BACKENDS:
        try:
            resp = _backend_get(f"{backend['url']}/models", timeout=5)
            for m in resp.json().get('models', []):
                if m['name'] not in seen:
                    seen.add(m['name'])
                    models.append({
                        'id': m['name'],
                        'object': 'model',
                        'owned_by': 'local',
                    })
        except:
            continue
    # Include aliases
    for alias, real in MODEL_ALIASES.items():
        if alias not in seen:
            models.append({'id': alias, 'object': 'model', 'owned_by': 'alias'})
    return jsonify({'object': 'list', 'data': models})

@app.route('/v1/chat/completions', methods=['POST'])
@require_auth
def v1_chat_completions():
    """OpenAI-compatible chat completions endpoint."""
    data = request.json or {}
    messages = data.get('messages', [])
    model = resolve_model(data.get('model', 'default'))

    # Extract the last user message for our /chat endpoint
    message = ''
    for m in reversed(messages):
        if m.get('role') == 'user':
            message = m.get('content', '')
            break

    if not message:
        return jsonify({'error': {'message': 'No user message found', 'type': 'invalid_request_error'}}), 400

    # Pass full messages array to backend
    result, status = proxy_request('/chat', {
        'message': message,
        'model': model,
        'messages': messages,
    }, request.remote_addr, 'chat')

    if result.get('error'):
        return jsonify({'error': {'message': result['error'], 'type': 'server_error'}}), 500

    # Convert to OpenAI format
    import uuid as _uuid
    response_id = f"chatcmpl-{_uuid.uuid4().hex[:12]}"
    return jsonify({
        'id': response_id,
        'object': 'chat.completion',
        'created': int(time.time()),
        'model': model,
        'choices': [{
            'index': 0,
            'message': {
                'role': 'assistant',
                'content': result.get('response', ''),
            },
            'finish_reason': 'stop',
        }],
        'usage': {
            'prompt_tokens': result.get('prompt_tokens', 0),
            'completion_tokens': result.get('response_tokens', 0),
            'total_tokens': result.get('total_tokens', 0),
        },
    })

@app.route('/upload', methods=['POST'])
@require_auth
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    commands = file.read().decode('utf-8')
    model = request.form.get('model', 'codellama:13b')
    
    result, status = proxy_request('/generate', {'commands': commands, 'model': model}, request.remote_addr, 'shell2ansible')
    return jsonify(result), status

# --- SSO Routes ---
@app.route('/sso/login')
def sso_login():
    oauth = get_oauth()
    if not oauth:
        return redirect('/status')
    redirect_uri = request.url_root.rstrip('/') + '/sso/callback'
    return oauth.sso.authorize_redirect(redirect_uri)

@app.route('/sso/callback')
def sso_callback():
    oauth = get_oauth()
    if not oauth:
        return redirect('/status')
    token = oauth.sso.authorize_access_token()
    userinfo = token.get('userinfo') or oauth.sso.userinfo()
    session['user'] = dict(userinfo)
    return redirect('/status')

@app.route('/sso/logout')
def sso_logout():
    session.pop('user', None)
    return redirect('/status')

@app.route('/sso/userinfo')
def sso_userinfo():
    """Return current SSO user info and role (for web UI)."""
    user = session.get('user')
    if not user:
        return jsonify({'authenticated': False, 'role': 'admin' if not sso_enabled() else 'none'})
    from shared.auth import get_sso_role
    return jsonify({'authenticated': True, 'user': user, 'role': get_sso_role(user)})

# Initialize SSO (overrides secret_key if SSO configured)
init_sso(app)

if __name__ == '__main__':
    ssl_ctx = None
    cert = os.environ.get('SHELLAMA_TLS_CERT')
    key = os.environ.get('SHELLAMA_TLS_KEY')
    ca = os.environ.get('SHELLAMA_TLS_CA')
    if cert and key:
        import ssl
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert, key)
        if ca:
            ssl_ctx.load_verify_locations(ca)
    app.run(host='0.0.0.0', port=5000, threaded=True, ssl_context=ssl_ctx)
