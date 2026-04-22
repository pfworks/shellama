<#
.SYNOPSIS
    sheLLaMa Comprehensive Test Suite — PowerShell edition

.DESCRIPTION
    Tests all API endpoints from Windows. Mirrors tests/test_all.py.

.EXAMPLE
    .\tests\test_all.ps1
    .\tests\test_all.ps1 -Frontend http://192.168.1.229:5000
    .\tests\test_all.ps1 -Backend http://192.168.1.218:5000
    .\tests\test_all.ps1 -Skip image
#>
param(
    [string]$Frontend = "http://192.168.1.229:5000",
    [string]$Backend = "",
    [string]$Model = "qwen2.5-coder:7b",
    [string]$Tag = "",
    [string]$Skip = "",
    [switch]$Verbose
)

$passed = 0; $failed = 0; $skipped = 0; $errors = @()
$timeout = 120

function Post($url, $body) {
    $json = $body | ConvertTo-Json -Depth 10
    Invoke-RestMethod -Uri $url -Method Post -Body $json -ContentType "application/json" -TimeoutSec $timeout
}
function Get-Api($url) {
    Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 30
}
function Ok($name, $detail="") {
    $script:passed++
    Write-Host "  ✓ $name" -ForegroundColor Green -NoNewline
    if ($Verbose -and $detail) { Write-Host "  ($detail)" -ForegroundColor DarkGray } else { Write-Host "" }
}
function Fail($name, $reason="") {
    $script:failed++
    $script:errors += @{Name=$name; Reason=$reason}
    Write-Host "  ✗ $name  — $reason" -ForegroundColor Red
}
function Skip-Test($name, $reason="") {
    $script:skipped++
    Write-Host "  - $name  (skipped: $reason)" -ForegroundColor Yellow
}

function Run-Test($name, $tags, $block) {
    if ($Tag -and -not ($tags | Where-Object { $Tag.Split(",") -contains $_ })) { return }
    if ($Skip -and ($tags | Where-Object { $Skip.Split(",") -contains $_ })) { Skip-Test $name "excluded"; return }
    try { & $block } catch {
        Fail $name $_.Exception.Message
    }
}

function Test-BackendSuite($base) {
    Run-Test "Backend: /queue-status" @("backend","status") {
        $d = Get-Api "$base/queue-status"
        if ($null -eq $d.queue_size) { throw "missing queue_size" }
        Ok "queue-status" "queue=$($d.queue_size)"
    }
    Run-Test "Backend: /models" @("backend","models") {
        $d = Get-Api "$base/models"
        if (-not $d.models) { throw "no models" }
        Ok "models" "$($d.models.Count) models"
    }
    Run-Test "Backend: /chat" @("backend","chat") {
        $d = Post "$base/chat" @{message="Reply with only PONG"; model=$Model}
        if (-not $d.response) { throw "no response" }
        Ok "chat" "$([math]::Round($d.elapsed,1))s, $($d.total_tokens) tok"
    }
    Run-Test "Backend: /generate" @("backend","generate") {
        $d = Post "$base/generate" @{commands="apt update"; model=$Model}
        if (-not $d.playbook -and -not $d.response) { throw "no output" }
        Ok "generate" "$([math]::Round($d.elapsed,1))s"
    }
    Run-Test "Backend: /generate-code" @("backend","codegen") {
        $d = Post "$base/generate-code" @{description="Python hello world"; model=$Model}
        if (-not $d.code -and -not $d.response) { throw "no output" }
        Ok "generate-code" "$([math]::Round($d.elapsed,1))s"
    }
    Run-Test "Backend: /explain-code" @("backend","explain") {
        $d = Post "$base/explain-code" @{code="print(1)"; model=$Model}
        if (-not $d.explanation -and -not $d.response) { throw "no output" }
        Ok "explain-code" "$([math]::Round($d.elapsed,1))s"
    }
    Run-Test "Backend: /analyze" @("backend","analyze") {
        $d = Post "$base/analyze" @{files=@(@{path="t.py"; content="x=1"}); model=$Model}
        if ($d.error) { throw $d.error }
        Ok "analyze" "$([math]::Round($d.elapsed,1))s"
    }
    Run-Test "Backend: /heartbeat" @("backend","heartbeat") {
        try { Post "$base/heartbeat" @{task_id="fake"} } catch {
            if ($_.Exception.Response.StatusCode.value__ -eq 404) { Ok "heartbeat rejects unknown task"; return }
            throw $_
        }
        Ok "heartbeat"
    }
    Run-Test "Backend: /stop" @("backend","admin") {
        $d = Post "$base/stop" @{}
        if ($null -eq $d.queue_cleared) { throw "unexpected response" }
        Ok "stop" "cleared=$($d.queue_cleared)"
    }
}

function Test-FrontendSuite($base) {
    Run-Test "Frontend: /queue-status" @("frontend","status") {
        $d = Get-Api "$base/queue-status"
        if (-not $d.backends) { throw "missing backends" }
        $healthy = ($d.backends | Where-Object { $_.health -eq "healthy" }).Count
        Ok "queue-status" "$healthy/$($d.total_backends) healthy"
    }
    Run-Test "Frontend: /models" @("frontend","models") {
        $d = Get-Api "$base/models"
        Ok "models" "$($d.models.Count) models"
    }
    Run-Test "Frontend: /chat" @("frontend","chat") {
        $d = Post "$base/chat" @{message="Reply PONG only"; model=$Model}
        if ($d.error) { throw $d.error }
        Ok "chat routing" "$([math]::Round($d.elapsed,1))s"
    }
    Run-Test "Frontend: /chat conversation" @("frontend","chat") {
        $cid = [guid]::NewGuid().ToString()
        $d1 = Post "$base/chat" @{message="My name is TestBot"; model=$Model; conversation_id=$cid}
        $d2 = Post "$base/chat" @{message="What is my name?"; model=$Model; conversation_id=$cid}
        if (-not $d2.response) { throw "no response" }
        Ok "conversation memory" "2 turns"
    }
    Run-Test "Frontend: /generate-code" @("frontend","codegen") {
        $d = Post "$base/generate-code" @{description="Python hello world"; model=$Model}
        if ($d.error) { throw $d.error }
        Ok "generate-code routing" "$([math]::Round($d.elapsed,1))s"
    }
    Run-Test "Frontend: /analyze" @("frontend","analyze") {
        $d = Post "$base/analyze" @{files=@(@{path="t.py"; content="x=1"}); model=$Model}
        if ($d.error) { throw $d.error }
        Ok "analyze routing" "$([math]::Round($d.elapsed,1))s"
    }
    Run-Test "Frontend: /v1/chat/completions" @("frontend","openai") {
        $d = Post "$base/v1/chat/completions" @{model=$Model; messages=@(@{role="user"; content="Say hi"})}
        if (-not $d.choices) { throw "no choices" }
        Ok "OpenAI compat" "$($d.usage.total_tokens) tok"
    }
    Run-Test "Frontend: /v1/models" @("frontend","openai") {
        $d = Get-Api "$base/v1/models"
        Ok "OpenAI models" "$($d.data.Count) models"
    }
    Run-Test "Frontend: /cloud-costs" @("frontend","costs") {
        $d = Get-Api "$base/cloud-costs"
        $bedrock = ($d.cloud_costs | Where-Object { $_.provider -like "Bedrock*" }).Count
        Ok "cloud-costs" "$($d.cloud_costs.Count) providers, $bedrock Bedrock"
    }
    Run-Test "Frontend: /cloud-costs Bedrock" @("frontend","costs","bedrock") {
        $d = Get-Api "$base/cloud-costs"
        $providers = $d.cloud_costs | ForEach-Object { $_.provider }
        $expected = @("Bedrock Claude Opus 4", "Bedrock Claude 4 Sonnet", "Bedrock Nova Pro", "Bedrock Nova Micro")
        $missing = $expected | Where-Object { $_ -notin $providers }
        if ($missing) { throw "missing: $($missing -join ', ')" }
        Ok "Bedrock models present" "$($expected.Count) verified"
    }
    Run-Test "Frontend: /status page" @("frontend","web") {
        $r = Invoke-WebRequest -Uri "$base/status" -TimeoutSec 10
        if ($r.StatusCode -ne 200) { throw "status=$($r.StatusCode)" }
        Ok "status page"
    }
    Run-Test "Frontend: /costs page" @("frontend","web") {
        $r = Invoke-WebRequest -Uri "$base/costs" -TimeoutSec 10
        if ($r.StatusCode -ne 200) { throw "status=$($r.StatusCode)" }
        Ok "costs page"
    }
    Run-Test "Frontend: /sso/userinfo" @("frontend","auth") {
        $d = Get-Api "$base/sso/userinfo"
        Ok "sso/userinfo" "role=$($d.role)"
    }
    Run-Test "Frontend: unavailable model" @("frontend","resilience") {
        $d = Post "$base/chat" @{message="hi"; model="nonexistent:999b"}
        Ok "unavailable model handled"
    }
}

# ── Main ────────────────────────────────────────────────────────────────────

$sw = [System.Diagnostics.Stopwatch]::StartNew()

if ($Backend) {
    Write-Host "`n═══ Backend Tests: $Backend ═══`n" -ForegroundColor White
    Test-BackendSuite $Backend
} else {
    Write-Host "`n═══ Frontend Tests: $Frontend ═══`n" -ForegroundColor White
    Test-FrontendSuite $Frontend

    # Discover and test backends
    try {
        $qs = Get-Api "$Frontend/queue-status"
        $backends = $qs.backends | Where-Object { $_.health -eq "healthy" } | ForEach-Object { $_.url }
    } catch { $backends = @() }

    if (-not $Tag -or $Tag.Split(",") -contains "backend") {
        foreach ($burl in $backends) {
            Write-Host "`n═══ Backend Tests: $burl ═══`n" -ForegroundColor White
            Test-BackendSuite $burl
        }
    }
}

$sw.Stop()
Write-Host "`n$('═' * 60)" -ForegroundColor White
Write-Host "  $passed passed" -ForegroundColor Green -NoNewline
Write-Host ", $failed failed" -ForegroundColor Red -NoNewline
Write-Host ", $skipped skipped" -ForegroundColor Yellow -NoNewline
Write-Host "  ($([math]::Round($sw.Elapsed.TotalSeconds,1))s)"

if ($errors.Count -gt 0) {
    Write-Host "`n  Failures:" -ForegroundColor Red
    foreach ($e in $errors) {
        Write-Host "    • $($e.Name): $($e.Reason)" -ForegroundColor Red
    }
}
Write-Host ""
exit $(if ($failed -gt 0) { 1 } else { 0 })
