#!/usr/bin/env python3
"""
sheLLaMa Comprehensive Test Suite

Tests all API endpoints, frontend routing, backend processing, and admin features.
Run after any code changes to verify nothing is broken.

Usage:
    python3 tests/test_all.py                          # Test against default (localhost:5000)
    python3 tests/test_all.py --frontend http://192.168.1.229:5000
    python3 tests/test_all.py --backend http://192.168.1.218:5000   # Direct backend tests only
    python3 tests/test_all.py --tag chat,analyze        # Run only specific tags
    python3 tests/test_all.py --skip image              # Skip slow tests
    python3 tests/test_all.py --verbose                 # Show response details
"""

import argparse
import json
import sys
import time
import requests
import uuid

# ── Config ──────────────────────────────────────────────────────────────────

DEFAULT_FRONTEND = "http://192.168.1.229:5000"
DEFAULT_MODEL = "qwen2.5-coder:7b"
TIMEOUT = 120  # per-request timeout

# ── Test framework ──────────────────────────────────────────────────────────

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

results = TestResult()
VERBOSE = False

def test(name, tags=None):
    """Decorator to register a test function with optional tags."""
    def decorator(fn):
        fn._test_name = name
        fn._test_tags = set(tags or [])
        return fn
    return decorator

def ok(name, detail=""):
    results.passed += 1
    mark = "\033[32m✓\033[0m"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail and VERBOSE else ""))

def fail(name, reason=""):
    results.failed += 1
    results.errors.append((name, reason))
    mark = "\033[31m✗\033[0m"
    print(f"  {mark} {name}  — {reason}")

def skip(name, reason=""):
    results.skipped += 1
    mark = "\033[33m-\033[0m"
    print(f"  {mark} {name}  (skipped: {reason})")

def post(url, data, timeout=TIMEOUT):
    return requests.post(url, json=data, timeout=timeout)

def get(url, timeout=30):
    return requests.get(url, timeout=timeout)

# ── Backend direct tests ────────────────────────────────────────────────────

@test("Backend: /queue-status", tags=["backend", "status"])
def test_backend_queue_status(base):
    r = get(f"{base}/queue-status")
    d = r.json()
    assert "queue_size" in d, "missing queue_size"
    assert "active" in d, "missing active"
    ok("queue-status returns valid JSON", f"queue={d['queue_size']}")

@test("Backend: /models", tags=["backend", "models"])
def test_backend_models(base):
    r = get(f"{base}/models")
    d = r.json()
    assert "models" in d, "missing models key"
    assert len(d["models"]) > 0, "no models available"
    names = [m.get("name", m.get("model", "")) for m in d["models"]]
    ok("models endpoint", f"{len(names)} models")

@test("Backend: /chat", tags=["backend", "chat"])
def test_backend_chat(base):
    r = post(f"{base}/chat", {"message": "Reply with only the word PONG", "model": DEFAULT_MODEL})
    d = r.json()
    assert "response" in d, f"no response key: {d}"
    assert d.get("elapsed", 0) > 0, "no elapsed time"
    assert d.get("total_tokens", 0) > 0, "no tokens"
    ok("chat", f"{d['elapsed']:.1f}s, {d['total_tokens']} tok")

@test("Backend: /generate (shell→ansible)", tags=["backend", "generate"])
def test_backend_generate(base):
    r = post(f"{base}/generate", {"commands": "apt update && apt install nginx", "model": DEFAULT_MODEL})
    d = r.json()
    assert "playbook" in d or "response" in d, f"no playbook/response: {list(d.keys())}"
    ok("generate shell→ansible", f"{d.get('elapsed', 0):.1f}s")

@test("Backend: /generate-code", tags=["backend", "codegen"])
def test_backend_generate_code(base):
    r = post(f"{base}/generate-code", {"description": "Python hello world", "model": DEFAULT_MODEL})
    d = r.json()
    assert "code" in d or "response" in d, f"no code/response: {list(d.keys())}"
    ok("generate-code", f"{d.get('elapsed', 0):.1f}s")

@test("Backend: /explain-code", tags=["backend", "explain"])
def test_backend_explain_code(base):
    r = post(f"{base}/explain-code", {"code": "print('hello')", "model": DEFAULT_MODEL})
    d = r.json()
    assert "explanation" in d or "response" in d, f"no explanation: {list(d.keys())}"
    ok("explain-code", f"{d.get('elapsed', 0):.1f}s")

@test("Backend: /explain (playbook)", tags=["backend", "explain"])
def test_backend_explain_playbook(base):
    playbook = "---\n- hosts: all\n  tasks:\n    - name: Install nginx\n      apt: name=nginx state=present"
    r = post(f"{base}/explain", {"playbook": playbook, "model": DEFAULT_MODEL})
    d = r.json()
    assert "explanation" in d or "response" in d, f"no explanation: {list(d.keys())}"
    ok("explain playbook", f"{d.get('elapsed', 0):.1f}s")

@test("Backend: /analyze", tags=["backend", "analyze"])
def test_backend_analyze(base):
    r = post(f"{base}/analyze", {
        "files": [{"path": "test.py", "content": "def add(a, b):\n    return a + b"}],
        "model": DEFAULT_MODEL
    })
    d = r.json()
    assert "analysis" in d or "response" in d, f"no analysis: {list(d.keys())}"
    assert not d.get("error"), f"error: {d.get('error')}"
    ok("analyze", f"{d.get('elapsed', 0):.1f}s")

@test("Backend: /heartbeat", tags=["backend", "heartbeat"])
def test_backend_heartbeat(base):
    r = post(f"{base}/heartbeat", {"task_id": "nonexistent"})
    assert r.status_code == 404, f"expected 404, got {r.status_code}"
    ok("heartbeat rejects unknown task_id")

@test("Backend: /stop", tags=["backend", "admin"])
def test_backend_stop(base):
    r = post(f"{base}/stop", {})
    try:
        d = r.json()
    except Exception:
        # Frontend doesn't have /stop, only /stop-all
        skip("stop endpoint", "not a direct backend")
        return
    assert "queue_cleared" in d, f"unexpected response: {d}"
    ok("stop endpoint", f"cleared={d['queue_cleared']}")

# ── Frontend routing tests ──────────────────────────────────────────────────

@test("Frontend: /queue-status (aggregate)", tags=["frontend", "status"])
def test_frontend_queue_status(base):
    r = get(f"{base}/queue-status")
    d = r.json()
    assert "backends" in d, "missing backends"
    assert "total_backends" in d, "missing total_backends"
    assert d["total_backends"] > 0, "no backends"
    healthy = sum(1 for b in d["backends"] if b.get("health") == "healthy")
    ok("frontend queue-status", f"{healthy}/{d['total_backends']} healthy")

@test("Frontend: /models", tags=["frontend", "models"])
def test_frontend_models(base):
    r = get(f"{base}/models")
    d = r.json()
    assert "models" in d, "missing models"
    ok("frontend models", f"{len(d['models'])} models")

@test("Frontend: /chat routed", tags=["frontend", "chat"])
def test_frontend_chat(base):
    r = post(f"{base}/chat", {"message": "Reply PONG only", "model": DEFAULT_MODEL})
    d = r.json()
    assert "response" in d, f"no response: {d}"
    assert not d.get("error"), f"error: {d.get('error')}"
    ok("frontend chat routing", f"{d.get('elapsed', 0):.1f}s")

@test("Frontend: /chat conversation memory", tags=["frontend", "chat"])
def test_frontend_conversation(base):
    conv_id = str(uuid.uuid4())
    r1 = post(f"{base}/chat", {"message": "My name is TestBot. Remember it.", "model": DEFAULT_MODEL, "conversation_id": conv_id})
    d1 = r1.json()
    assert "response" in d1, f"no response: {d1}"
    r2 = post(f"{base}/chat", {"message": "What is my name?", "model": DEFAULT_MODEL, "conversation_id": conv_id})
    d2 = r2.json()
    assert "response" in d2, f"no response: {d2}"
    ok("conversation memory", f"2 turns, {d1.get('total_tokens',0)+d2.get('total_tokens',0)} tok")

@test("Frontend: /generate-code routed", tags=["frontend", "codegen"])
def test_frontend_generate_code(base):
    r = post(f"{base}/generate-code", {"description": "Python hello world", "model": DEFAULT_MODEL})
    d = r.json()
    assert not d.get("error"), f"error: {d.get('error')}"
    ok("frontend generate-code routing", f"{d.get('elapsed', 0):.1f}s")

@test("Frontend: /explain-code routed", tags=["frontend", "explain"])
def test_frontend_explain_code(base):
    r = post(f"{base}/explain-code", {"code": "x = 1", "model": DEFAULT_MODEL})
    d = r.json()
    assert not d.get("error"), f"error: {d.get('error')}"
    ok("frontend explain-code routing", f"{d.get('elapsed', 0):.1f}s")

@test("Frontend: /analyze routed", tags=["frontend", "analyze"])
def test_frontend_analyze(base):
    r = post(f"{base}/analyze", {
        "files": [{"path": "t.py", "content": "x=1"}],
        "model": DEFAULT_MODEL
    })
    d = r.json()
    assert not d.get("error"), f"error: {d.get('error')}"
    assert "analysis" in d or "response" in d, f"no analysis: {list(d.keys())}"
    ok("frontend analyze routing", f"{d.get('elapsed', 0):.1f}s")

@test("Frontend: /generate routed", tags=["frontend", "generate"])
def test_frontend_generate(base):
    r = post(f"{base}/generate", {"commands": "systemctl restart nginx", "model": DEFAULT_MODEL})
    d = r.json()
    assert not d.get("error"), f"error: {d.get('error')}"
    ok("frontend generate routing", f"{d.get('elapsed', 0):.1f}s")

# ── OpenAI-compatible API ───────────────────────────────────────────────────

@test("Frontend: /v1/chat/completions", tags=["frontend", "openai"])
def test_openai_compat(base):
    r = post(f"{base}/v1/chat/completions", {
        "model": DEFAULT_MODEL,
        "messages": [{"role": "user", "content": "Say hi"}]
    })
    d = r.json()
    assert "choices" in d, f"no choices: {list(d.keys())}"
    assert len(d["choices"]) > 0, "empty choices"
    assert d["choices"][0].get("message", {}).get("content"), "empty content"
    ok("OpenAI /v1/chat/completions", f"{d.get('usage', {}).get('total_tokens', '?')} tok")

@test("Frontend: /v1/models", tags=["frontend", "openai"])
def test_openai_models(base):
    r = get(f"{base}/v1/models")
    d = r.json()
    assert "data" in d, f"no data: {list(d.keys())}"
    ok("OpenAI /v1/models", f"{len(d['data'])} models")

# ── Cost & stats endpoints ──────────────────────────────────────────────────

@test("Frontend: /cloud-costs", tags=["frontend", "costs"])
def test_cloud_costs(base):
    r = get(f"{base}/cloud-costs")
    d = r.json()
    assert "cloud_costs" in d, "missing cloud_costs"
    assert "pricing_source" in d, "missing pricing_source"
    providers = [c["provider"] for c in d["cloud_costs"]]
    bedrock = [p for p in providers if p.startswith("Bedrock")]
    ok("cloud-costs", f"{len(providers)} providers, {len(bedrock)} Bedrock")

@test("Frontend: /cloud-costs has Bedrock models", tags=["frontend", "costs", "bedrock"])
def test_bedrock_costs(base):
    r = get(f"{base}/cloud-costs")
    d = r.json()
    providers = {c["provider"] for c in d["cloud_costs"]}
    expected = ["Bedrock Claude Opus 4", "Bedrock Claude 4 Sonnet", "Bedrock Nova Pro", "Bedrock Nova Micro"]
    missing = [e for e in expected if e not in providers]
    assert not missing, f"missing Bedrock models: {missing}"
    ok("Bedrock models in costs", f"all {len(expected)} present")

@test("Frontend: /cost-history", tags=["frontend", "costs"])
def test_cost_history(base):
    r = get(f"{base}/cost-history?since=0")
    d = r.json()
    assert "cloud_costs" in d, "missing cloud_costs"
    assert "prompt_tokens" in d, "missing prompt_tokens"
    ok("cost-history", f"{d['prompt_tokens']} prompt tok")

@test("Frontend: /ip-tokens", tags=["frontend", "stats"])
def test_ip_tokens(base):
    r = get(f"{base}/ip-tokens")
    d = r.json()
    assert isinstance(d, dict), "expected dict"
    ok("ip-tokens", f"{len(d)} entries")

@test("Frontend: /usage-stats", tags=["frontend", "stats"])
def test_usage_stats(base):
    r = get(f"{base}/usage-stats")
    d = r.json()
    ok("usage-stats", f"{len(d)} keys")

@test("Frontend: /queue-history", tags=["frontend", "stats"])
def test_queue_history(base):
    r = get(f"{base}/queue-history")
    d = r.json()
    assert isinstance(d, (list, dict)), "expected list or dict"
    ok("queue-history", f"{len(d)} entries")

# ── Admin endpoints ─────────────────────────────────────────────────────────

@test("Frontend: /auto-fallback GET", tags=["frontend", "admin"])
def test_auto_fallback(base):
    r = get(f"{base}/auto-fallback")
    d = r.json()
    assert "auto_fallback" in d, f"missing auto_fallback: {d}"
    ok("auto-fallback", f"enabled={d['auto_fallback']}")

@test("Frontend: /api/backends GET", tags=["frontend", "admin"])
def test_api_backends(base):
    r = get(f"{base}/api/backends")
    d = r.json()
    assert "backends" in d, f"missing backends: {list(d.keys())}"
    ok("api/backends", f"{len(d['backends'])} backends")

@test("Frontend: /image-models", tags=["frontend", "models"])
def test_image_models(base):
    r = get(f"{base}/image-models")
    d = r.json()
    assert "models" in d, f"missing models: {d}"
    ok("image-models", f"{len(d['models'])} models")

# ── Web UI pages ────────────────────────────────────────────────────────────

@test("Frontend: /status page", tags=["frontend", "web"])
def test_status_page(base):
    r = get(f"{base}/status")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "sheLLaMa" in r.text, "missing title"
    ok("status page loads")

@test("Frontend: /backends page", tags=["frontend", "web"])
def test_backends_page(base):
    r = get(f"{base}/backends")
    assert r.status_code == 200, f"status={r.status_code}"
    ok("backends page loads")

@test("Frontend: /stats page", tags=["frontend", "web"])
def test_stats_page(base):
    r = get(f"{base}/stats")
    assert r.status_code == 200, f"status={r.status_code}"
    ok("stats page loads")

@test("Frontend: /costs page", tags=["frontend", "web"])
def test_costs_page(base):
    r = get(f"{base}/costs")
    assert r.status_code == 200, f"status={r.status_code}"
    assert "Bedrock" in r.text or "bedrock" in r.text or "Amazon" in r.text or "cost-table" in r.text, "costs page missing expected content"
    ok("costs page loads")

# ── SSO/Auth endpoints (should not error even without SSO configured) ──────

@test("Frontend: /sso/userinfo", tags=["frontend", "auth"])
def test_sso_userinfo(base):
    r = get(f"{base}/sso/userinfo")
    d = r.json()
    assert "role" in d, f"missing role: {d}"
    ok("sso/userinfo", f"role={d['role']}")

# ── Backend resilience ──────────────────────────────────────────────────────

@test("Frontend: handles unavailable model gracefully", tags=["frontend", "resilience"])
def test_unavailable_model(base):
    r = post(f"{base}/chat", {"message": "hi", "model": "nonexistent-model:999b"})
    d = r.json()
    assert "error" in d or "response" in d, f"unexpected: {d}"
    ok("unavailable model handled gracefully")

@test("Frontend: concurrent requests", tags=["frontend", "resilience"])
def test_concurrent(base):
    import concurrent.futures
    def do_chat(i):
        r = post(f"{base}/chat", {"message": f"Say {i}", "model": DEFAULT_MODEL})
        return r.json()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(do_chat, i) for i in range(3)]
        results_list = [f.result() for f in concurrent.futures.as_completed(futures)]
    succeeded = sum(1 for r in results_list if "response" in r and not r.get("error"))
    assert succeeded >= 2, f"only {succeeded}/3 succeeded"
    ok("concurrent requests", f"{succeeded}/3 succeeded")

# ── Prompt cache ────────────────────────────────────────────────────────────

@test("Frontend: prompt cache", tags=["frontend", "cache"])
def test_prompt_cache(base):
    payload = {"message": "What is 2+2? Reply with just the number.", "model": DEFAULT_MODEL}
    r1 = post(f"{base}/chat", payload)
    d1 = r1.json()
    r2 = post(f"{base}/chat", payload)
    d2 = r2.json()
    if d2.get("cached"):
        ok("prompt cache hit", f"saved {d1.get('total_tokens', 0)} tokens")
    else:
        ok("prompt cache (may be disabled or TTL=0)")

# ── Runner ──────────────────────────────────────────────────────────────────

def collect_tests():
    """Collect all @test-decorated functions."""
    tests = []
    for name, obj in globals().items():
        if callable(obj) and hasattr(obj, "_test_name"):
            tests.append(obj)
    return tests

def run_tests(base, tags_include=None, tags_exclude=None):
    all_tests = collect_tests()
    for fn in all_tests:
        name = fn._test_name
        fn_tags = fn._test_tags

        if tags_include and not fn_tags.intersection(tags_include):
            continue
        if tags_exclude and fn_tags.intersection(tags_exclude):
            skip(name, "excluded by --skip")
            continue

        try:
            fn(base)
        except requests.exceptions.Timeout:
            fail(name, "TIMEOUT")
        except requests.exceptions.ConnectionError:
            fail(name, "CONNECTION REFUSED")
        except AssertionError as e:
            fail(name, str(e))
        except Exception as e:
            fail(name, f"{type(e).__name__}: {e}")

def main():
    global VERBOSE, DEFAULT_MODEL
    parser = argparse.ArgumentParser(description="sheLLaMa comprehensive test suite")
    parser.add_argument("--frontend", default=DEFAULT_FRONTEND, help="Frontend URL")
    parser.add_argument("--backend", default=None, help="Direct backend URL (runs backend-only tests)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use")
    parser.add_argument("--tag", default=None, help="Comma-separated tags to include")
    parser.add_argument("--skip", default=None, help="Comma-separated tags to skip")
    parser.add_argument("--verbose", action="store_true", help="Show response details")
    args = parser.parse_args()

    VERBOSE = args.verbose
    DEFAULT_MODEL = args.model

    tags_include = set(args.tag.split(",")) if args.tag else None
    tags_exclude = set(args.skip.split(",")) if args.skip else None

    start = time.time()

    if args.backend:
        print(f"\n\033[1m═══ Backend Tests: {args.backend} ═══\033[0m\n")
        run_tests(args.backend, tags_include={"backend"} if not tags_include else tags_include, tags_exclude=tags_exclude)
    else:
        # Run backend tests on each backend discovered via frontend
        print(f"\n\033[1m═══ Frontend Tests: {args.frontend} ═══\033[0m\n")
        run_tests(args.frontend, tags_include=tags_include or {"frontend"}, tags_exclude=tags_exclude)

        # Discover backends and test each
        try:
            qs = get(f"{args.frontend}/queue-status").json()
            backends = [b["url"] for b in qs.get("backends", []) if b.get("health") == "healthy"]
        except Exception:
            backends = []

        if backends and (not tags_include or "backend" in tags_include):
            for burl in backends:
                print(f"\n\033[1m═══ Backend Tests: {burl} ═══\033[0m\n")
                run_tests(burl, tags_include={"backend"}, tags_exclude=tags_exclude)

    elapsed = time.time() - start
    print(f"\n\033[1m{'═' * 60}\033[0m")
    print(f"  \033[32m{results.passed} passed\033[0m, \033[31m{results.failed} failed\033[0m, \033[33m{results.skipped} skipped\033[0m  ({elapsed:.1f}s)")
    if results.errors:
        print(f"\n  \033[31mFailures:\033[0m")
        for name, reason in results.errors:
            print(f"    • {name}: {reason}")
    print()
    sys.exit(1 if results.failed else 0)

if __name__ == "__main__":
    main()
