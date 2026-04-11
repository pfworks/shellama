#!/export/ollama/bin/python3
from flask import Flask, request, jsonify, send_from_directory
import requests
import json
from queue import Queue, PriorityQueue
from threading import Thread, Lock
import time
import uuid
import os
import sys

app = Flask(__name__)

# Persistence file
HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'shellama-history.json')

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

def record_ip_tokens(ip, tokens, task_type='unknown', prompt_tokens=0, response_tokens=0):
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
        # Record time-series entry only if there were tokens
        if tokens > 0:
            if ip not in ip_token_history:
                ip_token_history[ip] = []
            ip_token_history[ip].append({'timestamp': time.time(), 'tokens': tokens, 'task': task_type})
            if len(ip_token_history[ip]) > IP_HISTORY_MAX:
                ip_token_history[ip] = ip_token_history[ip][-IP_HISTORY_MAX:]

# Load backends from config file
def load_backends():
    config_file = os.path.join(os.path.dirname(__file__), 'backends.json')
    try:
        with open(config_file, 'r') as f:
            backends = json.load(f)['backends']
            # Support both old format (list of strings) and new format (list of dicts)
            if backends and isinstance(backends[0], str):
                return [{'url': url, 'weight': 1, 'max_model': 'codellama:70b'} for url in backends]
            # Ensure max_model exists
            for b in backends:
                if 'max_model' not in b:
                    b['max_model'] = 'codellama:70b'
            return backends
    except:
        return [{'url': 'http://localhost:5001', 'weight': 1, 'max_model': 'codellama:70b'}]

BACKENDS = load_backends()

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
backend_status = {b['url']: {'available': True, 'queue_size': 0, 'weight': b['weight'], 'max_model': b['max_model']} for b in BACKENDS}
backend_lock = Lock()

def get_backend_queue_size(url):
    """Check backend queue size and capacity stats"""
    try:
        resp = requests.get(
            f"{url}/queue-status", 
            timeout=2
        )
        data = resp.json()
        return data
    except:
        return None

def get_available_backend(requested_model='codellama:13b', wait=True, timeout=300):
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

def proxy_request(endpoint, data, client_ip=None, task_type='unknown'):
    """Send request to available backend with keepalive"""
    model = data.get('model', 'codellama:13b')
    backend = get_available_backend(model)
    if not backend:
        return {'error': f'No backends available that support model {model}. Check backends.json configuration.'}, 200
    
    # Forward client info to backend for tracking
    if client_ip:
        data['client_ip'] = client_ip
    
    try:
        session = requests.Session()
        session.headers.update({'Connection': 'keep-alive'})
        
        response = session.post(
            f"{backend}{endpoint}", 
            json=data, 
            timeout=3600,
            stream=False
        )
        result = response.json()
        
        # Check if result was lost
        if result.get('error') and 'result was lost' in result.get('error', ''):
            return {'error': f"Backend {backend} lost task result. Task may have completed but response was not stored."}, 500
        
        # Record tokens for this client IP
        if client_ip:
            record_ip_tokens(client_ip, result.get('total_tokens', 0), task_type,
                           prompt_tokens=result.get('prompt_tokens', 0),
                           response_tokens=result.get('response_tokens', 0))
        
        return result, 200
    except requests.exceptions.Timeout:
        return {'error': f'Backend {backend} request timed out after 3600 seconds'}, 500
    except Exception as e:
        return {'error': f'Backend error: {str(e)}'}, 500
    finally:
        release_backend(backend)

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
def status_page():
    return send_from_directory('/export/html', 'status.html')

@app.route('/backends')
def backends_page():
    return send_from_directory('/export/html', 'backends.html')

@app.route('/stats')
def stats_page():
    return send_from_directory('/export/html', 'stats.html')

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
            resp = requests.get(
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
                'max_model': max_model,
                'queue_size': queue_size,
                'active': is_active,
                'status': 'online',
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
                'max_model': max_model,
                'queue_size': 0,
                'active': False,
                'status': 'offline',
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
        'timestamp': time.time()
    })

@app.route('/stop-all', methods=['POST'])
def stop_all():
    """Stop processing on all backends"""
    results = {}
    for backend in BACKENDS:
        url = backend['url']
        try:
            resp = requests.post(f"{url}/stop", timeout=10)
            results[url] = resp.json()
        except Exception as e:
            results[url] = {'error': str(e)}
    return jsonify(results)

@app.route('/stop-backend', methods=['POST'])
def stop_backend():
    """Stop processing on a specific backend"""
    url = request.json.get('url', '')
    if not url:
        return jsonify({'error': 'No backend URL provided'}), 400
    try:
        resp = requests.post(f"{url}/stop", timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate', methods=['POST'])
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
def explain():
    playbook = request.json.get('playbook', '')
    model = request.json.get('model', 'codellama:13b')
    result, status = proxy_request('/explain', {'playbook': playbook, 'model': model}, request.remote_addr, 'explain')
    return jsonify(result), status

@app.route('/generate-code', methods=['POST'])
def generate_code_endpoint():
    description = request.json.get('description', '')
    model = request.json.get('model', 'codellama:13b')
    result, status = proxy_request('/generate-code', {'description': description, 'model': model}, request.remote_addr, 'generate-code')
    return jsonify(result), status

@app.route('/explain-code', methods=['POST'])
def explain_code_endpoint():
    code = request.json.get('code', '')
    model = request.json.get('model', 'codellama:13b')
    result, status = proxy_request('/explain-code', {'code': code, 'model': model}, request.remote_addr, 'explain-code')
    return jsonify(result), status

@app.route('/chat', methods=['POST'])
def chat_endpoint():
    message = request.json.get('message', '')
    model = request.json.get('model', 'codellama:13b')
    result, status = proxy_request('/chat', {'message': message, 'model': model}, request.remote_addr, 'chat')
    return jsonify(result), status

@app.route('/analyze', methods=['POST'])
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
def generate_image_endpoint():
    data = request.json
    client_ip = request.remote_addr
    if client_ip:
        data['client_ip'] = client_ip

    # Image generation doesn't use an LLM — try each backend until one succeeds
    errors = []
    for b in BACKENDS:
        try:
            requests.get(f"{b['url']}/queue-status", timeout=2)
            resp = requests.post(f"{b['url']}/generate-image", json=data, timeout=3600)
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
            resp = requests.get(f"{backend['url']}/image-models", timeout=5)
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
            resp = requests.get(f"{backend['url']}/models", timeout=5)
            for m in resp.json().get('models', []):
                seen[m['name']] = m
        except:
            continue
    return jsonify({'models': sorted(seen.values(), key=lambda m: m['name'])})

@app.route('/test', methods=['POST'])
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
            resp = requests.get(f"{b['url']}/models", timeout=5)
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
                requests.get(f"{b['url']}/queue-status", timeout=2)
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
    """Running tab: what total usage (excluding /test) would cost on cloud providers."""
    _proj = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    if _proj not in sys.path:
        sys.path.insert(0, _proj)
    from shared.constants import cloud_cost_estimates, get_cloud_pricing

    with ip_token_lock:
        p_tok = persisted_totals.get('prompt_tokens', 0)
        r_tok = persisted_totals.get('response_tokens', 0)

    costs, source = cloud_cost_estimates(p_tok, r_tok)
    return jsonify({
        'prompt_tokens': p_tok,
        'response_tokens': r_tok,
        'total_tokens': p_tok + r_tok,
        'cloud_costs': costs,
        'pricing_source': source,
        'note': 'Excludes tokens from /test benchmarks',
    })

@app.route('/reset-stats', methods=['POST'])
def reset_stats():
    """Reset request/token counters."""
    with ip_token_lock:
        persisted_totals['requests'] = 0
        persisted_totals['tokens'] = 0
    save_history()
    return jsonify({'status': 'ok'})

@app.route('/reset-cloud-costs', methods=['POST'])
def reset_cloud_costs():
    """Reset cloud cost running tab."""
    with ip_token_lock:
        persisted_totals['prompt_tokens'] = 0
        persisted_totals['response_tokens'] = 0
    save_history()
    return jsonify({'status': 'ok'})

@app.route('/reset-all', methods=['POST'])
def reset_all():
    """Reset all counters."""
    with ip_token_lock:
        persisted_totals['requests'] = 0
        persisted_totals['tokens'] = 0
        persisted_totals['prompt_tokens'] = 0
        persisted_totals['response_tokens'] = 0
    save_history()
    return jsonify({'status': 'ok'})

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    commands = file.read().decode('utf-8')
    model = request.form.get('model', 'codellama:13b')
    
    result, status = proxy_request('/generate', {'commands': commands, 'model': model}, request.remote_addr, 'shell2ansible')
    return jsonify(result), status

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
