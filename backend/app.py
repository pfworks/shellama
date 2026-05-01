#!/export/ollama/bin/python3
from flask import Flask, request, jsonify, send_from_directory, Response
import ollama
from queue import Queue
from threading import Thread, Event, Lock
import uuid
import os
import requests

import json
import time

app = Flask(__name__)
task_queue = Queue()
active_task = None
task_results = {}
stop_requested = False

# Task timeout: cancel tasks if client disconnects or max time exceeded
TASK_TIMEOUT = int(os.environ.get('SHELLAMA_TASK_TIMEOUT', '1800'))  # 30 min default
task_waiters = {}  # task_id -> {'last_heartbeat': timestamp}
_waiter_lock = Lock()

# Statistics tracking
total_requests = 0
total_tokens = 0
stats_lock = Lock()

# Persistence
STATS_FILE = os.path.join(os.path.dirname(__file__), 'shellama-stats.json')

def load_stats():
    global total_requests, total_tokens
    try:
        with open(STATS_FILE, 'r') as f:
            data = json.load(f)
            total_requests = data.get('total_requests', 0)
            total_tokens = data.get('total_tokens', 0)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

def save_stats():
    try:
        with stats_lock:
            data = {'total_requests': total_requests, 'total_tokens': total_tokens}
        with open(STATS_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass

def periodic_save_stats():
    while True:
        time.sleep(60)
        save_stats()

load_stats()
Thread(target=periodic_save_stats, daemon=True).start()

def stale_task_reaper():
    """Kill active task if the requesting client has disconnected (no heartbeat)."""
    global active_task, stop_requested
    while True:
        time.sleep(10)
        if active_task is None:
            continue
        task_id = active_task.get('id')
        task_type = active_task.get('type', '')
        started = active_task.get('started', 0)
        now = time.time()

        should_kill = False
        # Check max timeout
        if TASK_TIMEOUT and started and (now - started) > TASK_TIMEOUT:
            should_kill = True
        # Check if waiter is gone (client disconnected)
        if not should_kill:
            with _waiter_lock:
                waiter = task_waiters.get(task_id)
            if waiter is None:
                if started and (now - started) > 15:
                    should_kill = True
            elif (now - waiter['last_heartbeat']) > 30:
                should_kill = True

        if should_kill:
            stop_requested = True
            # For LLM tasks, also kill the ollama runner process
            if task_type != 'generate_image':
                try:
                    import subprocess
                    subprocess.run(['pkill', '-f', 'ollama.*runner'], timeout=5, capture_output=True)
                except Exception:
                    pass

Thread(target=stale_task_reaper, daemon=True).start()


def submit_and_wait(task, timeout=3600):
    """Submit task to queue, send heartbeats while waiting, clean up on disconnect."""
    global stop_requested
    task_id = task['id']
    event = task['event']
    deadline = time.time() + timeout
    with _waiter_lock:
        task_waiters[task_id] = {'last_heartbeat': time.time()}
    task_queue.put(task)
    try:
        while not event.wait(timeout=10):
            if time.time() > deadline:
                # Overall timeout — cancel the task
                stop_requested = True
                return task_results.pop(task_id, {'error': f'Task timed out after {timeout}s'})
            # Update heartbeat while we're still connected
            with _waiter_lock:
                if task_id in task_waiters:
                    task_waiters[task_id]['last_heartbeat'] = time.time()
    finally:
        with _waiter_lock:
            task_waiters.pop(task_id, None)
    return task_results.pop(task_id, None)

# Cloud fallback configuration (OpenRouter or LiteLLM)
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'anthropic/claude-3.5-sonnet')
OPENROUTER_URL = os.environ.get('OPENROUTER_URL', 'https://openrouter.ai/api/v1/chat/completions')
USE_CLOUD_FALLBACK = os.environ.get('USE_CLOUD_FALLBACK', 'false').lower() == 'true'

def worker():
    global active_task, total_requests, total_tokens, stop_requested
    while True:
        task = task_queue.get()
        if task is None:
            break
        active_task = task
        stop_requested = False
        task_id = task['id']
        task['started'] = time.time()
        task_type = task.get('type')
        model = task.get('model', 'codellama:13b')
        
        # Increment request counter
        with stats_lock:
            total_requests += 1
        
        try:
            if task_type == 'explain':
                result = explain_playbook(task['playbook'], model)
            elif task_type == 'generate_code':
                result = generate_code(task['description'], model)
            elif task_type == 'explain_code':
                result = explain_code(task['code'], model)
            elif task_type == 'chat':
                result = chat(task['message'], model, messages=task.get('messages'))
            elif task_type == 'analyze':
                result = analyze_files(task['files'], model)
            elif task_type == 'generate_image':
                result = generate_image(task['prompt'], task.get('image_model', 'sd-turbo'),
                                       task.get('steps', 20), task.get('width', 512), task.get('height', 512))
            else:
                result = generate_playbook(task['commands'], model)
            
            # Update token counter
            with stats_lock:
                total_tokens += result.get('total_tokens', 0)
            
            # Check if we should fallback to cloud (not applicable to image generation)
            if USE_CLOUD_FALLBACK and OPENROUTER_API_KEY and task_type != 'generate_image':
                force_cloud = task.get('force_cloud', False)
                if force_cloud:
                    result = fallback_to_openrouter(task, result)
                elif should_use_cloud(result):
                    result['fallback_available'] = True
                    result['fallback_reason'] = _fallback_reason(result)
                    result['fallback_model'] = OPENROUTER_MODEL
            
            task_results[task_id] = result
        except Exception as e:
            if stop_requested:
                task_results[task_id] = {'error': 'Task cancelled by admin'}
            else:
                task_results[task_id] = {'error': f'Task processing failed: {str(e)}'}
        
        stop_requested = False
        task['event'].set()
        active_task = None
        task_queue.task_done()
        save_stats()

def should_use_cloud(result):
    """Determine if response quality is low enough to trigger cloud fallback."""
    return _fallback_reason(result) is not None


def _fallback_reason(result):
    """Return reason string if fallback is recommended, None otherwise."""
    if result.get('error'):
        return f"error: {result['error']}"

    content = None
    for key in ('playbook', 'code', 'response', 'explanation', 'analysis'):
        val = result.get(key)
        if val is not None:
            content = val
            break

    if content is None:
        return "no content in response"

    stripped = content.strip()

    if not stripped:
        return "empty response"

    if len(stripped) < 20 and any(k in result for k in ('playbook', 'code', 'explanation', 'analysis')):
        return f"very short response ({len(stripped)} chars)"

    prompt_tok = result.get('prompt_tokens', 0)
    resp_tok = result.get('response_tokens', 0)
    if prompt_tok > 50 and resp_tok < 5:
        return f"minimal output ({resp_tok} tokens for {prompt_tok} token prompt)"

    lines = stripped.split('\n')
    if len(lines) > 10:
        unique = set(l.strip() for l in lines if l.strip())
        if len(unique) < len(lines) * 0.2:
            return f"excessive repetition ({len(unique)} unique of {len(lines)} lines)"

    return None

def fallback_to_openrouter(task, ollama_result):
    """Call OpenRouter API as fallback (supports Claude, GPT-4, Llama, etc.)"""
    try:
        task_type = task.get('type')

        if task_type == 'explain':
            prompt = f"Explain this Ansible playbook:\n\n{task['playbook']}"
        elif task_type == 'generate_code':
            prompt = f"Generate code for: {task['description']}"
        elif task_type == 'explain_code':
            prompt = f"Explain this code:\n\n{task['code']}"
        elif task_type == 'chat':
            prompt = task['message']
        elif task_type == 'analyze':
            files_content = ""
            for f in task['files']:
                if f.get('error'):
                    files_content += f"\n=== {f['path']} (Error: {f['error']}) ===\n"
                else:
                    files_content += f"\n=== {f['path']} ===\n{f['content']}\n"
            prompt = f"Analyze these files:\n{files_content}"
        else:
            prompt = f"Convert these shell commands into an Ansible playbook. Return ONLY valid YAML:\n\n{task['commands']}"

        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENROUTER_MODEL,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=120
        )
        data = resp.json()
        content = data['choices'][0]['message']['content']

        if task_type in ['explain', 'explain_code']:
            ollama_result['explanation'] = content
        elif task_type == 'generate_code':
            ollama_result['code'] = content
        elif task_type == 'chat':
            ollama_result['response'] = content
        elif task_type == 'analyze':
            ollama_result['analysis'] = content
        else:
            ollama_result['playbook'] = content

        ollama_result['error'] = None
        ollama_result['cloud_fallback'] = True
        ollama_result['cloud_model'] = OPENROUTER_MODEL

        # Capture token usage from cloud response
        usage = data.get('usage', {})
        ollama_result['prompt_tokens'] = usage.get('prompt_tokens', 0)
        ollama_result['response_tokens'] = usage.get('completion_tokens', 0)
        ollama_result['total_tokens'] = usage.get('total_tokens',
            usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0))

    except Exception as e:
        ollama_result['cloud_error'] = str(e)

    return ollama_result

def generate_playbook(commands, model='codellama:13b'):
    import time
    import yaml
    import re
    
    # Check if model exists
    try:
        ollama.show(model)
    except:
        return {
            'playbook': '',
            'elapsed': 0,
            'error': f'Model {model} not found. Please run: ollama pull {model}',
            'prompt_tokens': 0,
            'response_tokens': 0,
            'total_tokens': 0
        }
    
    start_time = time.time()
    
    prompt = f"""Convert these shell commands into an Ansible playbook. Return ONLY valid YAML, no explanations:

Commands:
{commands}

Generate a complete Ansible playbook with proper tasks."""

    max_retries = 3
    for attempt in range(max_retries):
        response = ollama.chat(model=model, messages=[
            {'role': 'user', 'content': prompt}
        ])
        
        playbook_text = response['message']['content']
        
        # Strip markdown code blocks (handle multiple variations)
        import re
        # Remove opening code fence with optional language
        playbook_text = re.sub(r'^```[a-z]*\s*\n', '', playbook_text, flags=re.MULTILINE)
        # Remove closing code fence
        playbook_text = re.sub(r'\n```\s*$', '', playbook_text, flags=re.MULTILINE)
        # Remove any remaining backticks at start/end
        playbook_text = playbook_text.strip('`').strip()
        
        # Validate YAML
        try:
            yaml.safe_load(playbook_text)
            break  # Valid YAML, exit retry loop
        except yaml.YAMLError as e:
            if attempt == max_retries - 1:
                return {
                    'playbook': playbook_text,
                    'elapsed': round(time.time() - start_time, 2),
                    'error': f'Invalid YAML after {max_retries} attempts: {str(e)}',
                    'prompt_tokens': response.get('prompt_eval_count', 0),
                    'response_tokens': response.get('eval_count', 0),
                    'total_tokens': response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
                }
    
    elapsed = time.time() - start_time
    
    return {
        'playbook': playbook_text,
        'elapsed': round(elapsed, 2),
        'prompt_tokens': response.get('prompt_eval_count', 0),
        'response_tokens': response.get('eval_count', 0),
        'total_tokens': response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
    }

def explain_playbook(playbook, model='codellama:13b'):
    import time
    
    # Check if model exists
    try:
        ollama.show(model)
    except:
        return {
            'explanation': '',
            'elapsed': 0,
            'error': f'Model {model} not found. Please run: ollama pull {model}',
            'prompt_tokens': 0,
            'response_tokens': 0,
            'total_tokens': 0
        }
    
    start_time = time.time()
    
    prompt = f"""Explain what this Ansible playbook does in clear, simple language. Describe each task and its purpose:

{playbook}"""

    response = ollama.chat(model=model, messages=[
        {'role': 'user', 'content': prompt}
    ])
    
    elapsed = time.time() - start_time
    
    return {
        'explanation': response['message']['content'],
        'elapsed': round(elapsed, 2),
        'prompt_tokens': response.get('prompt_eval_count', 0),
        'response_tokens': response.get('eval_count', 0),
        'total_tokens': response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
    }

def generate_code(description, model='codellama:13b'):
    import time
    
    # Check if model exists
    try:
        ollama.show(model)
    except:
        return {
            'code': '',
            'elapsed': 0,
            'error': f'Model {model} not found. Please run: ollama pull {model}',
            'prompt_tokens': 0,
            'response_tokens': 0,
            'total_tokens': 0
        }
    
    start_time = time.time()
    
    prompt = f"""Generate clean, well-commented code based on this description. Include the language and provide working code:

{description}"""

    response = ollama.chat(model=model, messages=[
        {'role': 'user', 'content': prompt}
    ])
    
    elapsed = time.time() - start_time
    
    return {
        'code': response['message']['content'],
        'elapsed': round(elapsed, 2),
        'prompt_tokens': response.get('prompt_eval_count', 0),
        'response_tokens': response.get('eval_count', 0),
        'total_tokens': response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
    }

def explain_code(code, model='codellama:13b'):
    import time
    
    # Check if model exists
    try:
        ollama.show(model)
    except:
        return {
            'explanation': '',
            'elapsed': 0,
            'error': f'Model {model} not found. Please run: ollama pull {model}',
            'prompt_tokens': 0,
            'response_tokens': 0,
            'total_tokens': 0
        }
    
    start_time = time.time()
    
    prompt = f"""Explain what this code does in clear, simple language. Describe the logic, functions, and purpose:

{code}"""

    response = ollama.chat(model=model, messages=[
        {'role': 'user', 'content': prompt}
    ])
    
    elapsed = time.time() - start_time
    
    return {
        'explanation': response['message']['content'],
        'elapsed': round(elapsed, 2),
        'prompt_tokens': response.get('prompt_eval_count', 0),
        'response_tokens': response.get('eval_count', 0),
        'total_tokens': response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
    }

def chat(message, model='codellama:13b', messages=None):
    import time
    
    # Check if model exists
    try:
        ollama.show(model)
    except:
        return {
            'response': '',
            'elapsed': 0,
            'error': f'Model {model} not found. Please run: ollama pull {model}',
            'prompt_tokens': 0,
            'response_tokens': 0,
            'total_tokens': 0
        }
    
    start_time = time.time()
    
    if messages is None:
        messages = [{'role': 'user', 'content': message}]
    
    response = ollama.chat(model=model, messages=messages)
    
    elapsed = time.time() - start_time
    
    return {
        'response': response['message']['content'],
        'elapsed': round(elapsed, 2),
        'prompt_tokens': response.get('prompt_eval_count', 0),
        'response_tokens': response.get('eval_count', 0),
        'total_tokens': response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
    }

_image_pipe = None  # cached pipeline
_image_pipe_model = None  # which model is loaded

def generate_image(prompt, model='sd-turbo', steps=20, width=512, height=512):
    global _image_pipe, _image_pipe_model
    import time
    import base64
    import io
    
    start_time = time.time()
    
    # Map friendly names to HuggingFace model IDs
    model_map = {
        'sd-1.5': 'sd-legacy/stable-diffusion-v1-5',
        'stable-diffusion-v1-5': 'sd-legacy/stable-diffusion-v1-5',
        'sd-2.1': 'stabilityai/stable-diffusion-2-1',
        'stable-diffusion-2-1': 'stabilityai/stable-diffusion-2-1',
        'sdxl-turbo': 'stabilityai/sdxl-turbo',
        'sd-turbo': 'stabilityai/sd-turbo',
    }
    
    hf_model = model_map.get(model, model)
    
    try:
        import torch
        from diffusers import AutoPipelineForText2Image
        
        # Use bfloat16 on CPU for speed, float16 on CUDA
        has_cuda = torch.cuda.is_available()
        dtype = torch.float16 if has_cuda else (torch.bfloat16 if hasattr(torch, 'bfloat16') else torch.float32)
        device = "cuda" if has_cuda else "cpu"
        
        # Cache pipeline — only reload if model changed
        if _image_pipe is None or _image_pipe_model != hf_model:
            if stop_requested:
                raise InterruptedError("Task cancelled during setup")
            _image_pipe = AutoPipelineForText2Image.from_pretrained(
                hf_model,
                torch_dtype=dtype,
            )
            if stop_requested:
                raise InterruptedError("Task cancelled during setup")
            _image_pipe.to(device)
            _image_pipe_model = hf_model
        
        if stop_requested:
            raise InterruptedError("Task cancelled before inference")
        
        # Turbo models use fewer steps
        if 'turbo' in hf_model:
            steps = min(steps, 4)
        
        # Callback to abort if stop_requested
        def _check_stop(pipe, step, timestep, kwargs):
            if stop_requested:
                raise InterruptedError("Task cancelled")
            return kwargs

        result = _image_pipe(
            prompt,
            num_inference_steps=steps,
            width=width,
            height=height,
            guidance_scale=0.0 if 'turbo' in hf_model else 7.5,
            callback_on_step_end=_check_stop,
        )
        
        image = result.images[0]
        
        # Convert to base64 PNG
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        image_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        elapsed = time.time() - start_time
        
        return {
            'image': image_b64,
            'elapsed': round(elapsed, 2),
            'model': hf_model,
            'prompt': prompt,
            'steps': steps,
            'width': width,
            'height': height,
        }
    except Exception as e:
        return {
            'image': '',
            'elapsed': round(time.time() - start_time, 2),
            'error': str(e),
        }

def analyze_files(files, model='codellama:13b'):
    import time
    
    try:
        ollama.show(model)
    except:
        return {
            'analysis': '',
            'elapsed': 0,
            'error': f'Model {model} not found. Please run: ollama pull {model}',
            'prompt_tokens': 0,
            'response_tokens': 0,
            'total_tokens': 0
        }
    
    start_time = time.time()
    
    files_content = ""
    for f in files:
        if f.get('error'):
            files_content += f"\n=== {f['path']} (Error: {f['error']}) ===\n"
        else:
            files_content += f"\n=== {f['path']} ===\n{f['content']}\n"
    
    prompt = f"""Analyze these files and provide insights about their purpose, structure, relationships, potential issues, and suggestions for improvement:

{files_content}"""

    response = ollama.chat(model=model, messages=[
        {'role': 'user', 'content': prompt}
    ])
    
    elapsed = time.time() - start_time
    
    return {
        'analysis': response['message']['content'],
        'elapsed': round(elapsed, 2),
        'prompt_tokens': response.get('prompt_eval_count', 0),
        'response_tokens': response.get('eval_count', 0),
        'total_tokens': response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
    }

Thread(target=worker, daemon=True).start()

@app.route('/')
def index():
    return send_from_directory('/export/html', 'index.html')

@app.route('/queue-status')
def queue_status():
    global total_requests, total_tokens
    import psutil
    import platform
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    status = {
        'queue_size': queue_size,
        'active': active_task is not None,
        'total_requests': total_requests,
        'total_tokens': total_tokens,
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'ram_available_gb': round(psutil.virtual_memory().available / (1024**3), 2),
        'ram_total_gb': round(psutil.virtual_memory().total / (1024**3), 2),
        'cpu_arch': platform.machine(),
        'cpu_count': psutil.cpu_count(logical=True),
        'cpu_freq_mhz': round((psutil.cpu_freq().max or psutil.cpu_freq().current) if psutil.cpu_freq() else 0),
    }
    
    if active_task:
        status['active_type'] = active_task.get('type', 'generate')
        status['active_model'] = active_task.get('model', 'unknown')
        status['active_client'] = active_task.get('client_ip', '')
        status['active_agent'] = active_task.get('client_agent', '')
        status['active_summary'] = active_task.get('summary', '')

    # Report models currently loaded in Ollama memory
    try:
        ps = ollama.ps()
        status['loaded_models'] = [m.model for m in ps.models] if ps.models else []
    except:
        status['loaded_models'] = []
    
    return jsonify(status)

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    """Client sends heartbeat to keep its task alive."""
    task_id = request.json.get('task_id', '')
    with _waiter_lock:
        if task_id in task_waiters:
            task_waiters[task_id]['last_heartbeat'] = time.time()
            return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'unknown task_id'}), 404

@app.route('/stop', methods=['POST'])
def stop_processing():
    """Stop active task and clear queue"""
    global active_task, stop_requested
    stopped = {'active_cancelled': False, 'queue_cleared': 0}

    # Clear queued tasks
    cleared = 0
    while not task_queue.empty():
        try:
            task = task_queue.get_nowait()
            task_results[task['id']] = {'error': 'Task cancelled by admin'}
            task['event'].set()
            task_queue.task_done()
            cleared += 1
        except:
            break
    stopped['queue_cleared'] = cleared

    # Signal active task to stop (ollama will be killed)
    if active_task is not None:
        stop_requested = True
        stopped['active_cancelled'] = True
        # Kill any running ollama process to interrupt inference
        import subprocess
        try:
            subprocess.run(['pkill', '-f', 'ollama.*runner'], timeout=5)
        except:
            pass

    return jsonify(stopped)

@app.route('/models')
def list_models():
    try:
        models = ollama.list()
        return jsonify({'models': [{'name': m.model, 'size': m.size} for m in models.models]})
    except Exception as e:
        return jsonify({'models': [], 'error': str(e)})

@app.route('/generate', methods=['POST'])
def generate():
    commands = request.json.get('commands', '')
    model = request.json.get('model', 'codellama:13b')
    
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    task_id = str(uuid.uuid4())
    event = Event()
    summary = commands[:80].replace('\n', ' ')
    task = {'id': task_id, 'commands': commands, 'model': model, 'event': event, 'force_cloud': request.json.get('force_cloud', False),
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'shell2ansible: {summary}'}
    result = submit_and_wait(task)
    
    if result is None:
        return jsonify({'error': f'Task {task_id} completed but result was lost'}), 500
    
    if queue_size > 0:
        result['queue_position'] = queue_size + 1
    result['task_id'] = task_id
    
    return jsonify(result)

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    commands = file.read().decode('utf-8')
    model = request.form.get('model', 'codellama:13b')
    
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    task_id = str(uuid.uuid4())
    event = Event()
    task = {'id': task_id, 'commands': commands, 'model': model, 'event': event, 'force_cloud': request.json.get('force_cloud', False),
            'client_ip': request.remote_addr, 'client_agent': request.headers.get('User-Agent', ''),
            'summary': f'upload: {commands[:80].replace(chr(10), " ")}'}
    result = submit_and_wait(task)
    
    if result is None:
        return jsonify({"error": f"Task {task_id} completed but result was lost"}), 500
    
    if queue_size > 0:
        result['queue_position'] = queue_size + 1
    result['task_id'] = task_id
    
    return jsonify(result)

@app.route('/explain', methods=['POST'])
def explain():
    playbook = request.json.get('playbook', '')
    model = request.json.get('model', 'codellama:13b')
    
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    task_id = str(uuid.uuid4())
    event = Event()
    task = {'id': task_id, 'playbook': playbook, 'model': model, 'event': event, 'force_cloud': request.json.get('force_cloud', False), 'type': 'explain',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'explain: {playbook[:80].replace(chr(10), " ")}'}
    result = submit_and_wait(task)
    
    if result is None:
        return jsonify({"error": f"Task {task_id} completed but result was lost"}), 500
    
    if queue_size > 0:
        result['queue_position'] = queue_size + 1
    result['task_id'] = task_id
    
    return jsonify(result)

@app.route('/generate-code', methods=['POST'])
def generate_code_endpoint():
    description = request.json.get('description', '')
    model = request.json.get('model', 'codellama:13b')
    
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    task_id = str(uuid.uuid4())
    event = Event()
    task = {'id': task_id, 'description': description, 'model': model, 'event': event, 'force_cloud': request.json.get('force_cloud', False), 'type': 'generate_code',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'codegen: {description[:80].replace(chr(10), " ")}'}
    result = submit_and_wait(task)
    
    if result is None:
        return jsonify({"error": f"Task {task_id} completed but result was lost"}), 500
    
    if queue_size > 0:
        result['queue_position'] = queue_size + 1
    result['task_id'] = task_id
    
    return jsonify(result)

@app.route('/explain-code', methods=['POST'])
def explain_code_endpoint():
    code = request.json.get('code', '')
    model = request.json.get('model', 'codellama:13b')
    
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    task_id = str(uuid.uuid4())
    event = Event()
    task = {'id': task_id, 'code': code, 'model': model, 'event': event, 'force_cloud': request.json.get('force_cloud', False), 'type': 'explain_code',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'explain-code: {code[:80].replace(chr(10), " ")}'}
    result = submit_and_wait(task)
    
    if result is None:
        return jsonify({"error": f"Task {task_id} completed but result was lost"}), 500
    
    if queue_size > 0:
        result['queue_position'] = queue_size + 1
    result['task_id'] = task_id
    
    return jsonify(result)

@app.route('/chat', methods=['POST'])
def chat_endpoint():
    message = request.json.get('message', '')
    model = request.json.get('model', 'codellama:13b')
    
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    task_id = str(uuid.uuid4())
    event = Event()
    task = {'id': task_id, 'message': message, 'messages': request.json.get('messages'), 'model': model, 'event': event, 'force_cloud': request.json.get('force_cloud', False), 'type': 'chat',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'chat: {message[:80].replace(chr(10), " ")}'}
    result = submit_and_wait(task)
    
    if result is None:
        return jsonify({"error": f"Task {task_id} completed but result was lost"}), 500
    
    if queue_size > 0:
        result['queue_position'] = queue_size + 1
    result['task_id'] = task_id
    
    return jsonify(result)

@app.route('/analyze', methods=['POST'])
def analyze_endpoint():
    files = request.json.get('files', [])
    model = request.json.get('model', 'codellama:13b')
    
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    task_id = str(uuid.uuid4())
    event = Event()
    paths = ', '.join(f.get('path', '?') for f in files[:3])
    task = {'id': task_id, 'files': files, 'model': model, 'event': event, 'force_cloud': request.json.get('force_cloud', False), 'type': 'analyze',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'analyze: {paths}'}
    result = submit_and_wait(task)
    
    if result is None:
        return jsonify({"error": f"Task {task_id} completed but result was lost"}), 500
    
    if queue_size > 0:
        result['queue_position'] = queue_size + 1
    result['task_id'] = task_id
    
    return jsonify(result)

@app.route('/generate-image', methods=['POST'])
def generate_image_endpoint():
    prompt = request.json.get('prompt', '')
    image_model = request.json.get('image_model', 'sd-turbo')
    steps = request.json.get('steps', 20)
    width = request.json.get('width', 512)
    height = request.json.get('height', 512)
    
    queue_size = task_queue.qsize()
    if active_task is not None:
        queue_size += 1
    
    task_id = str(uuid.uuid4())
    event = Event()
    task = {'id': task_id, 'prompt': prompt, 'image_model': image_model,
            'steps': steps, 'width': width, 'height': height,
            'model': image_model, 'event': event, 'force_cloud': request.json.get('force_cloud', False), 'type': 'generate_image',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'image: {prompt[:80]}'}
    result = submit_and_wait(task)
    
    if result is None:
        return jsonify({'error': f'Task {task_id} completed but result was lost'}), 500
    
    if queue_size > 0:
        result['queue_position'] = queue_size + 1
    result['task_id'] = task_id
    
    return jsonify(result)

@app.route('/image-models')
def image_models():
    return jsonify({
        'models': [
            {'id': 'sd-turbo', 'name': 'Stable Diffusion Turbo', 'description': 'Fast, 1-4 steps, 512x512'},
            {'id': 'sdxl-turbo', 'name': 'SDXL Turbo', 'description': 'Fast SDXL, 1-4 steps, 512x512'},
            {'id': 'sd-1.5', 'name': 'Stable Diffusion 1.5', 'description': 'Classic, 20+ steps, 512x512'},
            {'id': 'sd-2.1', 'name': 'Stable Diffusion 2.1', 'description': 'Improved, 20+ steps, 768x768'},
        ]
    })

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
            ssl_ctx.verify_mode = ssl.CERT_REQUIRED
    app.run(host='0.0.0.0', port=5000, ssl_context=ssl_ctx)
