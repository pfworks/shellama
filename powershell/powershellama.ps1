<#
.SYNOPSIS
    PowerSheLLama - PowerShell + AI agent. Prefix with , to talk to the AI.
#>

$SHELLAMA_API = if ($env:SHELLAMA_API) { $env:SHELLAMA_API } elseif ($env:ANSIBLE_TOOLS_API) { $env:ANSIBLE_TOOLS_API } else { "http://192.168.1.229:5000" }
$SHELLAMA_MODEL = if ($env:SHELLAMA_MODEL) { $env:SHELLAMA_MODEL } elseif ($env:ANSIBLE_TOOLS_MODEL) { $env:ANSIBLE_TOOLS_MODEL } else { "qwen2.5-coder:7b" }
$TRIGGER = ","
$Quiet = $false
$MaxRounds = 10

# Session usage tracking
$script:SessionTokens = 0
$script:SessionRequests = 0
$script:SessionElapsed = 0.0

$CYAN = "`e[36m"
$YELLOW = "`e[33m"
$GRAY = "`e[90m"
$DIM = "`e[2m"
$RESET = "`e[0m"
$HAL = "🔴 "

$SystemPrompt = @"
You are an AI assistant running inside a PowerShell session on Windows.
Current directory: {0}

You can run PowerShell commands to answer the user's question. To run a command, output it in a ```powershell block like this:

```powershell
Get-ChildItem
```

You will see the command output, then you can run more commands or give your final answer.

IMPORTANT:
- Always run commands yourself, never ask the user to run them
- You MUST use ```powershell blocks to run commands
- When you have enough info, give your final answer as plain text with no ```powershell blocks
- Keep commands short and focused
- If a command fails, try a different approach
- Never run destructive commands (Remove-Item -Recurse -Force, Format-Volume, etc.) without the user explicitly asking
"@

function Show-Banner {
    Write-Host "${CYAN}shellama${RESET} - PowerShell + AI agent"
    Write-Host "${GRAY}backend: $SHELLAMA_API | model: $SHELLAMA_MODEL${RESET}"
    Write-Host ""
    Write-Host "  ${YELLOW},${RESET}  <prompt>       agentic chat        ${YELLOW},,${RESET} <prompt>       quiet chat"
    Write-Host "  ${YELLOW},explain${RESET}  <file>  explain any file     ${YELLOW},generate${RESET} <desc>  generate code"
    Write-Host "  ${YELLOW},analyze${RESET}  <path>  analyze files/dirs   ${YELLOW},img${RESET} <prompt>     generate image"
    Write-Host "  ${YELLOW},list${RESET}             all services         ${YELLOW},quiet${RESET}            toggle quiet"
    Write-Host "  ${YELLOW},models${RESET}           select model         ${YELLOW},tokens${RESET}           session usage"
    Write-Host ""
}

function Start-LlamaSpinner {
    $script:SpinnerRunning = $true
    $script:SpinnerRunspace = [runspacefactory]::CreateRunspace()
    $script:SpinnerRunspace.Open()
    $script:SpinnerRunspace.SessionStateProxy.SetVariable('host', $Host)
    $script:SpinnerRunspace.SessionStateProxy.SetVariable('running', [ref]$script:SpinnerRunning)
    $ps = [powershell]::Create().AddScript({
        $frames = @("  🦙     ", "  🦙 .   ", "  🦙 ..  ", "  🦙 ... ")
        $i = 0
        while ($running.Value) {
            $host.UI.Write("`r$($frames[$i % $frames.Count])")
            Start-Sleep -Milliseconds 300
            $i++
        }
        $host.UI.Write("`r                    `r")
    })
    $ps.Runspace = $script:SpinnerRunspace
    $script:SpinnerHandle = $ps.BeginInvoke()
    $script:SpinnerPS = $ps
}

function Stop-LlamaSpinner {
    if ($script:SpinnerPS) {
        $script:SpinnerRunning = $false
        try { $script:SpinnerPS.EndInvoke($script:SpinnerHandle) } catch {}
        $script:SpinnerPS.Dispose()
        $script:SpinnerRunspace.Close()
        $script:SpinnerPS = $null
        Write-Host -NoNewline "`r                    `r"
    }
}

function Invoke-AIChat {
    param([string]$Message)
    try {
        $body = @{ message = $Message; model = $SHELLAMA_MODEL } | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$SHELLAMA_API/chat" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 3600
        return $resp
    } catch [System.Management.Automation.PipelineStoppedException] {
        # Ctrl+C pressed — stop backend
        try { Invoke-RestMethod -Uri "$SHELLAMA_API/stop-all" -Method Post -TimeoutSec 5 | Out-Null } catch {}
        return @{ error = "cancelled" }
    } catch [System.OperationCanceledException] {
        try { Invoke-RestMethod -Uri "$SHELLAMA_API/stop-all" -Method Post -TimeoutSec 5 | Out-Null } catch {}
        return @{ error = "cancelled" }
    } catch {
        return @{ error = $_.Exception.Message }
    }
}

function Invoke-AISimple {
    param([string]$Endpoint, [hashtable]$Payload, [string]$ResultKey)
    try {
        if (-not $Quiet) { Start-LlamaSpinner }
        $body = $Payload | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$SHELLAMA_API$Endpoint" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 3600
        if (-not $Quiet) { Stop-LlamaSpinner }
        if ($resp.error) { Write-Host "shellama: $($resp.error)" -ForegroundColor Red; return }
        $script:SessionTokens += [int]($resp.total_tokens)
        $script:SessionRequests += 1
        $script:SessionElapsed += [double]($resp.elapsed)
        Write-Host "${CYAN}$($resp.$ResultKey)${RESET}"
        Write-Host "${GRAY}[$($resp.elapsed)s | $($resp.total_tokens) tokens | $SHELLAMA_MODEL]${RESET}"
    } catch [System.Management.Automation.PipelineStoppedException] {
        Stop-LlamaSpinner
        Write-Host "`n${GRAY}cancelled - stopping backend...${RESET}"
        try { Invoke-RestMethod -Uri "$SHELLAMA_API/stop-all" -Method Post -TimeoutSec 5 | Out-Null } catch {}
    } catch {
        Stop-LlamaSpinner
        Write-Host "shellama: $_" -ForegroundColor Red
    }
}

function Invoke-AIAgent {
    param([string]$Query, [bool]$IsQuiet = $false)

    $system = $SystemPrompt -f (Get-Location).Path
    $conversation = "$system`n`nUser: $Query"
    $totalTokens = 0
    $totalElapsed = 0

    for ($round = 0; $round -lt $MaxRounds; $round++) {
        if (-not $IsQuiet) { Start-LlamaSpinner }
        $resp = Invoke-AIChat -Message $conversation
        if (-not $IsQuiet) { Stop-LlamaSpinner }

        if ($resp.error) { Write-Host "shellama: $($resp.error)" -ForegroundColor Red; return }

        $response = $resp.response
        $tokens = if ($resp.total_tokens) { $resp.total_tokens } else { 0 }
        $elapsed = if ($resp.elapsed) { $resp.elapsed } else { 0 }
        $totalTokens += $tokens
        $totalElapsed += $elapsed
        $script:SessionTokens += [int]$tokens
        $script:SessionRequests += 1
        $script:SessionElapsed += [double]$elapsed

        # Extract powershell code blocks
        $commands = [regex]::Matches($response, '```powershell\n(.*?)```', 'Singleline') | ForEach-Object { $_.Groups[1].Value.Trim() }

        if ($commands.Count -eq 0) {
            if (-not $IsQuiet) {
                Write-Host "${CYAN}$response${RESET}"
                Write-Host "${GRAY}[$($round + 1) round$(if($round){'s'}) | $([math]::Round($totalElapsed,1))s | $totalTokens tokens | $SHELLAMA_MODEL]${RESET}"
            }
            return
        }

        if (-not $IsQuiet) {
            # Show reasoning between code blocks
            $parts = [regex]::Split($response, '```powershell\n.*?```', 'Singleline')
            foreach ($part in $parts) {
                $part = $part.Trim()
                if ($part) { Write-Host "${CYAN}$part${RESET}" }
            }
            Write-Host "${GRAY}[round $($round + 1) | $([math]::Round($elapsed,1))s | $tokens tokens]${RESET}"
        }

        # Execute commands
        $cmdOutputs = @()
        foreach ($cmd in $commands) {
            Write-Host "${YELLOW}PS> $cmd${RESET}"
            if (-not $IsQuiet) {
                $answer = Read-Host "${GRAY}Run? [Y/n/q]${RESET}"
                if ($answer -eq 'q') { return }
                if ($answer -eq 'n') { $cmdOutputs += "PS> $cmd`n(skipped by user)"; continue }
            }
            try {
                $output = Invoke-Expression $cmd 2>&1 | Out-String
                $output = $output.Trim()
                if ($output) {
                    if ($IsQuiet) { Write-Host $output } else { Write-Host "${DIM}$output${RESET}" }
                }
                $cmdOutputs += "PS> $cmd`n$output"
            } catch {
                $err = $_.Exception.Message
                Write-Host "Error: $err" -ForegroundColor Red
                $cmdOutputs += "PS> $cmd`nError: $err"
            }
        }

        $results = $cmdOutputs -join "`n`n"
        $conversation += "`n`nAssistant: $response`n`nCommand output:`n$results`n`nContinue. If you have enough information, give your final answer without any ``````powershell blocks."
    }
    Write-Host "${GRAY}[max rounds reached | $([math]::Round($totalElapsed,1))s | $totalTokens tokens]${RESET}"
}

function Invoke-AIImage {
    param([string]$Prompt)
    $imageModel = if ($env:AI_IMAGE_MODEL) { $env:AI_IMAGE_MODEL } else { "sd-turbo" }
    $steps = if ($imageModel -match "turbo") { 4 } else { 20 }
    try {
        Start-LlamaSpinner
        $body = @{ prompt = $Prompt; image_model = $imageModel; steps = $steps; width = 512; height = 512 } | ConvertTo-Json
        $resp = Invoke-RestMethod -Uri "$SHELLAMA_API/generate-image" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 3600
        Stop-LlamaSpinner
        if ($resp.error) { Write-Host "shellama: $($resp.error)" -ForegroundColor Red; return }
        $script:SessionRequests += 1
        $script:SessionElapsed += [double]($resp.elapsed)
        $outfile = "generated_$([int](Get-Date -UFormat %s)).png"
        [IO.File]::WriteAllBytes("$PWD\$outfile", [Convert]::FromBase64String($resp.image))
        Write-Host "${CYAN}$(Resolve-Path $outfile)${RESET}"
        Write-Host "${GRAY}[$($resp.elapsed)s | $($resp.model) | $($resp.steps) steps]${RESET}"
    } catch [System.Management.Automation.PipelineStoppedException] {
        Stop-LlamaSpinner
        Write-Host "`n${GRAY}cancelled - stopping backend...${RESET}"
        try { Invoke-RestMethod -Uri "$SHELLAMA_API/stop-all" -Method Post -TimeoutSec 5 | Out-Null } catch {}
    } catch {
        Stop-LlamaSpinner
        Write-Host "shellama: $_" -ForegroundColor Red
    }
}

function Invoke-AIAnalyze {
    param([string[]]$Paths)
    [array]$filesData = @()
    foreach ($p in $Paths) {
        if (Test-Path $p -PathType Container) {
            Get-ChildItem $p -Recurse -File | ForEach-Object {
                try { $filesData += @{ path = $_.FullName; content = (Get-Content $_.FullName -Raw) } } catch {}
            }
        } elseif (Test-Path $p) {
            try { $filesData += @{ path = (Resolve-Path $p).Path; content = (Get-Content $p -Raw) } } catch {}
        } else {
            Write-Host "shellama: ${p}: not found" -ForegroundColor Red
        }
    }
    if ($filesData.Count -eq 0) { Write-Host "shellama: no readable files found" -ForegroundColor Red; return }
    Write-Host "${GRAY}Analyzing $($filesData.Count) file$(if($filesData.Count -ne 1){'s'})...${RESET}"
    Invoke-AISimple -Endpoint "/analyze" -Payload @{ files = @($filesData); model = $SHELLAMA_MODEL } -ResultKey "analysis"
}

function Show-Services {
    Write-Host "${CYAN}Available services (prefix with ,):${RESET}"
    Write-Host "  ${YELLOW},${RESET}  <prompt>       agentic chat        ${YELLOW},,${RESET} <prompt>       quiet chat"
    Write-Host "  ${YELLOW},explain${RESET}  <file>  explain any file     ${YELLOW},generate${RESET} <desc>  generate code"
    Write-Host "  ${YELLOW},analyze${RESET}  <path>  analyze files/dirs   ${YELLOW},img${RESET} <prompt>     generate image"
    Write-Host "  ${YELLOW},list${RESET}             all services         ${YELLOW},models${RESET}           select model"
    Write-Host "  ${YELLOW},quiet${RESET}            toggle quiet"
}

function Select-Model {
    try {
        $resp = Invoke-RestMethod -Uri "$SHELLAMA_API/models" -TimeoutSec 10
        $models = $resp.models
    } catch {
        Write-Host "shellama: $_" -ForegroundColor Red; return
    }
    if ($models.Count -eq 0) { Write-Host "shellama: no models available" -ForegroundColor Red; return }
    Write-Host "${CYAN}Available models:${RESET}"
    for ($i = 0; $i -lt $models.Count; $i++) {
        $m = $models[$i]
        $sizeGb = [math]::Round($m.size / 1GB, 1)
        $current = if ($m.name -eq $SHELLAMA_MODEL) { " <- current" } else { "" }
        Write-Host "  ${YELLOW}$($i+1)${RESET}) $($m.name) (${sizeGb}GB)$current"
    }
    $choice = Read-Host "${GRAY}Select [1-$($models.Count)]${RESET}"
    if ($choice -match '^\d+$' -and [int]$choice -ge 1 -and [int]$choice -le $models.Count) {
        $script:SHELLAMA_MODEL = $models[[int]$choice - 1].name
        Write-Host "model: $SHELLAMA_MODEL"
    } else {
        Write-Host "cancelled"
    }
}

# Main loop
Show-Banner

while ($true) {
    $prompt = "${HAL}PS $($executionContext.SessionState.Path.CurrentLocation)> "
    $line = Read-Host -Prompt $prompt
    if ($null -eq $line) { break }
    $line = $line.Trim()
    if (-not $line) { continue }

    if ($line -in @('exit', 'quit', 'logout')) { break }

    if ($line.StartsWith(",,")) {
        $query = $line.Substring(2).Trim()
        if ($query) { Invoke-AIAgent -Query $query -IsQuiet $true }
    }
    elseif ($line.StartsWith(",")) {
        $query = $line.Substring(1).Trim()
        if (-not $query) { continue }

        if ($query -in @('list', 'help')) { Show-Services }
        elseif ($query -eq 'models') { Select-Model }
        elseif ($query -eq 'quiet') { $Quiet = -not $Quiet; Write-Host "quiet mode: $(if($Quiet){'on'}else{'off'})" }
        elseif ($query -eq 'tokens') { Write-Host "${CYAN}Session usage: $($script:SessionRequests) requests | $($script:SessionTokens) tokens | $([math]::Round($script:SessionElapsed,1))s${RESET}" }
        elseif ($query.StartsWith('img ')) { Invoke-AIImage -Prompt $query.Substring(4).Trim() }
        elseif ($query.StartsWith('analyze ')) { Invoke-AIAnalyze -Paths ($query.Substring(8).Trim() -split '\s+') }
        elseif ($query.StartsWith('explain ')) {
            $file = $query.Substring(8).Trim()
            if (-not (Test-Path $file)) { Write-Host "shellama: ${file}: not found" -ForegroundColor Red; continue }
            $content = Get-Content $file -Raw
            $ext = [IO.Path]::GetExtension($file).ToLower()
            if ($ext -in @('.yml', '.yaml')) {
                Invoke-AISimple -Endpoint "/explain" -Payload @{ playbook = $content; model = $SHELLAMA_MODEL } -ResultKey "explanation"
            } else {
                Invoke-AISimple -Endpoint "/explain-code" -Payload @{ code = $content; model = $SHELLAMA_MODEL } -ResultKey "explanation"
            }
        }
        elseif ($query.StartsWith('generate ')) {
            $desc = $query.Substring(9).Trim()
            if ($desc -match 'ansible|playbook|shell command') {
                Invoke-AISimple -Endpoint "/generate" -Payload @{ commands = $desc; model = $SHELLAMA_MODEL } -ResultKey "playbook"
            } else {
                Invoke-AISimple -Endpoint "/generate-code" -Payload @{ description = $desc; model = $SHELLAMA_MODEL } -ResultKey "code"
            }
        }
        else { Invoke-AIAgent -Query $query -IsQuiet $Quiet }
    }
    else {
        # Regular PowerShell command
        try { Invoke-Expression $line } catch { Write-Host $_.Exception.Message -ForegroundColor Red }
    }
}
