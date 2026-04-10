#!/export/ollama/bin/python3
from flask import Flask, request, jsonify, send_from_directory
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
                result = chat(task['message'], model)
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
            
            # Check if we should fallback to cloud
            if USE_CLOUD_FALLBACK and OPENROUTER_API_KEY and should_use_cloud(result):
                result = fallback_to_openrouter(task, result)
            
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
    """Determine if response quality is low"""
    if result.get('error'):
        return True
    if result.get('playbook', '').strip() == '':
        return True
    if result.get('code', '').strip() == '':
        return True
    return False

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

def chat(message, model='codellama:13b'):
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
    
    response = ollama.chat(model=model, messages=[
        {'role': 'user', 'content': message}
    ])
    
    elapsed = time.time() - start_time
    
    return {
        'response': response['message']['content'],
        'elapsed': round(elapsed, 2),
        'prompt_tokens': response.get('prompt_eval_count', 0),
        'response_tokens': response.get('eval_count', 0),
        'total_tokens': response.get('prompt_eval_count', 0) + response.get('eval_count', 0)
    }

def generate_image(prompt, model='stable-diffusion-v1-5', steps=20, width=512, height=512):
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
        
        pipe = AutoPipelineForText2Image.from_pretrained(
            hf_model,
            torch_dtype=torch.float32,
        )
        pipe.to("cpu")
        
        # Turbo models use fewer steps
        if 'turbo' in hf_model:
            steps = min(steps, 4)
        
        result = pipe(
            prompt,
            num_inference_steps=steps,
            width=width,
            height=height,
            guidance_scale=0.0 if 'turbo' in hf_model else 7.5,
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
    
    return jsonify(status)

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
    task = {'id': task_id, 'commands': commands, 'model': model, 'event': event,
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'shell2ansible: {summary}'}
    task_queue.put(task)
    
    event.wait()
    result = task_results.pop(task_id, None)
    
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
    task = {'id': task_id, 'commands': commands, 'model': model, 'event': event,
            'client_ip': request.remote_addr, 'client_agent': request.headers.get('User-Agent', ''),
            'summary': f'upload: {commands[:80].replace(chr(10), " ")}'}
    task_queue.put(task)
    
    event.wait()
    result = task_results.pop(task_id, None)
    
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
    task = {'id': task_id, 'playbook': playbook, 'model': model, 'event': event, 'type': 'explain',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'explain: {playbook[:80].replace(chr(10), " ")}'}
    task_queue.put(task)
    
    event.wait()
    result = task_results.pop(task_id, None)
    
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
    task = {'id': task_id, 'description': description, 'model': model, 'event': event, 'type': 'generate_code',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'codegen: {description[:80].replace(chr(10), " ")}'}
    task_queue.put(task)
    
    event.wait()
    result = task_results.pop(task_id, None)
    
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
    task = {'id': task_id, 'code': code, 'model': model, 'event': event, 'type': 'explain_code',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'explain-code: {code[:80].replace(chr(10), " ")}'}
    task_queue.put(task)
    
    event.wait()
    result = task_results.pop(task_id, None)
    
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
    task = {'id': task_id, 'message': message, 'model': model, 'event': event, 'type': 'chat',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'chat: {message[:80].replace(chr(10), " ")}'}
    task_queue.put(task)
    
    event.wait()
    result = task_results.pop(task_id, None)
    
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
    task = {'id': task_id, 'files': files, 'model': model, 'event': event, 'type': 'analyze',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'analyze: {paths}'}
    task_queue.put(task)
    
    event.wait()
    result = task_results.pop(task_id, None)
    
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
            'model': 'none', 'event': event, 'type': 'generate_image',
            'client_ip': request.json.get('client_ip', request.remote_addr),
            'client_agent': request.json.get('client_agent', request.headers.get('User-Agent', '')),
            'summary': f'image: {prompt[:80]}'}
    task_queue.put(task)
    
    event.wait()
    result = task_results.pop(task_id, None)
    
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
    app.run(host='0.0.0.0', port=5000)
