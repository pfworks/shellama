# sheLLaMa PowerShell integration — dot-source this in your $PROFILE
# Usage: . /path/to/shellama/powershell/shellama.ps1
#   or add to $PROFILE: . C:\path\to\shellama\powershell\shellama.ps1
#
# Gives you , commands in your real PowerShell session:
#   , <prompt>          agentic chat (AI runs commands)
#   ,, <prompt>         quiet mode (output only)
#   ,explain <file>     explain any file
#   ,generate <desc>    generate code/playbook
#   ,analyze <paths>    analyze files/dirs
#   ,img <prompt>       generate image
#   ,test [model|all]   benchmark models
#   ,models             select model
#   ,tokens             session usage
#   ,list               show commands

# Load shared config
. "$PSScriptRoot\shellama-config.ps1"
$script:SessionTokens = 0
$script:SessionRequests = 0
$script:SessionElapsed = 0.0
$script:MaxRounds = 10

function Invoke-ShellamaChat {
    param([string]$Message, [string]$Model = $script:SHELLAMA_MODEL)
    $body = @{ message = $Message; model = $Model; conversation_id = $script:SHELLAMA_CONV_ID } | ConvertTo-Json -Depth 10
    $headers = Get-ShellamaHeaders
    try {
        $resp = Invoke-RestMethod -Uri "$($script:SHELLAMA_API)/chat" -Method Post -Body $body -Headers $headers -TimeoutSec 3600
        return $resp
    } catch {
        Write-Host "shellama: $_" -ForegroundColor Red
        return $null
    }
}

function Invoke-ShellamaAgent {
    param([string]$Query, [switch]$Quiet)
    $system = $script:SHELLAMA_SYSTEM_PROMPT -f (Get-Location)
    $conversation = "$system`n`nUser: $Query"
    $totalTokens = 0; $totalElapsed = 0

    for ($round = 0; $round -lt $script:MaxRounds; $round++) {
        $resp = Invoke-ShellamaChat -Message $conversation
        if (-not $resp -or $resp.error) {
            if ($resp.error) { Write-Host "Error: $($resp.error)" -ForegroundColor Red }
            return
        }
        $response = $resp.response
        $tokens = if ($resp.total_tokens) { $resp.total_tokens } else { 0 }
        $elapsed = if ($resp.elapsed) { $resp.elapsed } else { 0 }
        $totalTokens += $tokens; $totalElapsed += $elapsed
        $script:SessionTokens += $tokens; $script:SessionRequests++; $script:SessionElapsed += $elapsed

        $commands = [regex]::Matches($response, '```powershell\n(.*?)```', 'Singleline') | ForEach-Object { $_.Groups[1].Value.Trim() }

        if ($commands.Count -eq 0) {
            if ($Quiet) { Write-Host $response } else {
                Write-Host $response -ForegroundColor Cyan
                Write-Host "[$($round + 1) round$(if($round){'s'}) | $([math]::Round($totalElapsed,1))s | $totalTokens tokens | $($script:SHELLAMA_MODEL)]" -ForegroundColor DarkGray
            }
            return
        }

        if (-not $Quiet) {
            $parts = [regex]::Split($response, '```powershell\n.*?```', 'Singleline')
            foreach ($part in $parts) { $part = $part.Trim(); if ($part) { Write-Host $part -ForegroundColor Cyan } }
            Write-Host "[round $($round + 1) | $([math]::Round($elapsed,1))s | $tokens tokens]" -ForegroundColor DarkGray
        }

        $cmdOutputs = @()
        foreach ($cmd in $commands) {
            Write-Host "PS> $cmd" -ForegroundColor Yellow
            if (-not $Quiet) {
                $answer = Read-Host "Run? [Y/n/q]"
                if ($answer -eq 'q') { return }
                if ($answer -eq 'n') { $cmdOutputs += "PS> $cmd`n(skipped by user)"; continue }
            }
            try {
                $output = Invoke-Expression $cmd 2>&1 | Out-String
                if ($output.Trim()) {
                    if ($Quiet) { Write-Host $output.Trim() } else { Write-Host $output.Trim() -ForegroundColor DarkGray }
                }
                $cmdOutputs += "PS> $cmd`n$output"
            } catch {
                Write-Host "Error: $_" -ForegroundColor Red
                $cmdOutputs += "PS> $cmd`nError: $_"
            }
        }
        $results = $cmdOutputs -join "`n`n"
        $conversation += "`n`nAssistant: $response`n`nCommand output:`n$results`n`nContinue. If you have enough information, give your final answer without any ``````powershell blocks."
    }
    Write-Host "[max rounds reached | $([math]::Round($totalElapsed,1))s | $totalTokens tokens]" -ForegroundColor DarkGray
}

function Invoke-ShellamaSimple {
    param([string]$Endpoint, [hashtable]$Body, [string]$ResultKey)
    $json = $Body | ConvertTo-Json -Depth 10
    $headers = Get-ShellamaHeaders
    try {
        $resp = Invoke-RestMethod -Uri "$($script:SHELLAMA_API)$Endpoint" -Method Post -Body $json -Headers $headers -TimeoutSec 3600
        if ($resp.error) { Write-Host "shellama: $($resp.error)" -ForegroundColor Red; return }
        $script:SessionTokens += ($resp.total_tokens -as [int])
        $script:SessionRequests++
        $script:SessionElapsed += ($resp.elapsed -as [double])
        Write-Host $resp.$ResultKey -ForegroundColor Cyan
        Write-Host "[$($resp.elapsed)s | $($resp.total_tokens) tokens | $($script:SHELLAMA_MODEL)]" -ForegroundColor DarkGray
    } catch {
        Write-Host "shellama: $_" -ForegroundColor Red
    }
}

# Define , commands as functions
function , { Invoke-ShellamaAgent -Query ($args -join ' ') }
function ,, { Invoke-ShellamaAgent -Query ($args -join ' ') -Quiet }

function ,explain {
    $file = $args[0]
    if (-not $file -or -not (Test-Path $file)) { Write-Host "Usage: ,explain <file>" -ForegroundColor Red; return }
    $content = Get-Content $file -Raw
    $ext = [IO.Path]::GetExtension($file).ToLower()
    if ($ext -in @('.yml', '.yaml')) {
        Invoke-ShellamaSimple "/explain" @{ playbook = $content; model = $script:SHELLAMA_MODEL } "explanation"
    } else {
        Invoke-ShellamaSimple "/explain-code" @{ code = $content; model = $script:SHELLAMA_MODEL } "explanation"
    }
}

function ,generate {
    $desc = $args -join ' '
    if ($desc -match 'ansible|playbook|shell command') {
        Invoke-ShellamaSimple "/generate" @{ commands = $desc; model = $script:SHELLAMA_MODEL } "playbook"
    } else {
        Invoke-ShellamaSimple "/generate-code" @{ description = $desc; model = $script:SHELLAMA_MODEL } "code"
    }
}

function ,analyze {
    $filesData = @()
    foreach ($p in $args) {
        if (Test-Path $p -PathType Container) {
            Get-ChildItem $p -Recurse -File | ForEach-Object {
                try { $filesData += @{ path = $_.FullName; content = (Get-Content $_.FullName -Raw) } } catch {}
            }
        } elseif (Test-Path $p) {
            try { $filesData += @{ path = (Resolve-Path $p).Path; content = (Get-Content $p -Raw) } } catch {}
        } else { Write-Host "${p}: not found" -ForegroundColor Red }
    }
    if ($filesData.Count -eq 0) { Write-Host "No readable files found" -ForegroundColor Red; return }
    Write-Host "Analyzing $($filesData.Count) file$(if($filesData.Count -ne 1){'s'})..." -ForegroundColor DarkGray
    Invoke-ShellamaSimple "/analyze" @{ files = @($filesData); model = $script:SHELLAMA_MODEL } "analysis"
}

function ,img {
    $prompt = $args -join ' '
    $im = if ($env:AI_IMAGE_MODEL) { $env:AI_IMAGE_MODEL } else { "sd-turbo" }
    $st = if ($im -match "turbo") { 4 } else { 20 }
    $body = @{ prompt = $prompt; image_model = $im; steps = $st; width = 512; height = 512 } | ConvertTo-Json
    try {
        $resp = Invoke-RestMethod -Uri "$($script:SHELLAMA_API)/generate-image" -Method Post -Body $body -Headers (Get-ShellamaHeaders) -TimeoutSec 3600
        if ($resp.image) {
            $dlDir = if ($env:SHELLAMA_DOWNLOAD_DIR) { $env:SHELLAMA_DOWNLOAD_DIR } else { $PWD }
            if (!(Test-Path $dlDir)) { New-Item -ItemType Directory -Path $dlDir -Force | Out-Null }
            $defaultFile = "$dlDir\generated_$([int](Get-Date -UFormat %s)).png"
            $custom = Read-Host "Save as [$defaultFile]"
            $outfile = if ($custom) { $custom } else { $defaultFile }
            $outDir = [IO.Path]::GetDirectoryName($outfile)
            if ($outDir -and !(Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
            [IO.File]::WriteAllBytes($outfile, [Convert]::FromBase64String($resp.image))
            Write-Host "Saved: $outfile" -ForegroundColor Cyan
        }
    } catch { Write-Host "shellama: $_" -ForegroundColor Red }
}

function ,test {
    $testArgs = $args -join ' '
    $body = @{ model = if ($testArgs) { $testArgs } else { "all" } } | ConvertTo-Json
    try {
        $resp = Invoke-RestMethod -Uri "$($script:SHELLAMA_API)/test" -Method Post -Body $body -Headers (Get-ShellamaHeaders) -TimeoutSec 3600
        if ($resp.error) { Write-Host "shellama: $($resp.error)" -ForegroundColor Red; return }
        if ($resp.skipped) { Write-Host "Skipped (too large): $($resp.skipped -join ', ')" -ForegroundColor DarkGray }
        $results = $resp.results | Where-Object { -not $_.error }
        if ($results.Count -eq 0) { Write-Host "No results"; return }
        Write-Host ("{0,-30} {1,7} {2,7} {3,7} {4,7} {5,7}" -f "Model","Time","Prompt","Reply","Total","tok/s") -ForegroundColor Cyan
        foreach ($r in ($results | Sort-Object elapsed)) {
            Write-Host ("{0,-30} {1,6:F1}s {2,7} {3,7} {4,7} {5,6:F1}" -f $r.model,$r.elapsed,$r.prompt_tokens,$r.response_tokens,$r.total_tokens,$r.tok_per_sec)
        }
        if ($resp.cloud_costs) {
            Write-Host "`nCloud cost estimate ($($resp.pricing_source)):" -ForegroundColor Cyan
            foreach ($c in $resp.cloud_costs) {
                Write-Host ("{0,-25} `${1,8:F6}" -f $c.provider,$c.total_cost)
            }
            Write-Host "`nLocal models: `$0.00" -ForegroundColor DarkGray
        }
    } catch { Write-Host "shellama: $_" -ForegroundColor Red }
}

function ,models {
    try {
        $resp = Invoke-RestMethod -Uri "$($script:SHELLAMA_API)/models" -Headers (Get-ShellamaHeaders) -TimeoutSec 10
        $models = $resp.models
        Write-Host "Available models:" -ForegroundColor Cyan
        for ($i = 0; $i -lt $models.Count; $i++) {
            $current = if ($models[$i].name -eq $script:SHELLAMA_MODEL) { " <- current" } else { "" }
            Write-Host "  $($i+1)) $($models[$i].name)$current" -ForegroundColor Yellow
        }
        $choice = Read-Host "Select [1-$($models.Count)]"
        if ($choice -match '^\d+$' -and [int]$choice -ge 1 -and [int]$choice -le $models.Count) {
            $script:SHELLAMA_MODEL = $models[[int]$choice - 1].name
            Write-Host "model: $($script:SHELLAMA_MODEL)"
        }
    } catch { Write-Host "shellama: $_" -ForegroundColor Red }
}

function ,tokens { Write-Host "Session usage: $($script:SessionRequests) requests | $($script:SessionTokens) tokens | $([math]::Round($script:SessionElapsed,1))s" -ForegroundColor Cyan }

function ,list {
    Write-Host ",  <prompt>       agentic chat" -ForegroundColor Yellow
    Write-Host ",,  <prompt>      quiet mode" -ForegroundColor Yellow
    Write-Host ",explain  <file>  explain any file" -ForegroundColor Yellow
    Write-Host ",generate <desc>  generate code" -ForegroundColor Yellow
    Write-Host ",analyze  <path>  analyze files/dirs" -ForegroundColor Yellow
    Write-Host ",img <prompt>     generate image" -ForegroundColor Yellow
    Write-Host ",test [model]     benchmark models" -ForegroundColor Yellow
    Write-Host ",models           select model" -ForegroundColor Yellow
    Write-Host ",tokens           session usage" -ForegroundColor Yellow
}

function ,help { ,list }

# Add HAL eye to prompt
# Save original prompt
$script:_OriginalPrompt = (Get-Command prompt).ScriptBlock
function prompt { "🔴 $(Get-Location)> " }

function ,exit {
    # Restore original prompt
    Set-Item Function:\prompt $script:_OriginalPrompt
    # Remove all , functions
    ',', ',,', ',explain', ',generate', ',analyze', ',img', ',test', ',models', ',tokens', ',list', ',help', ',exit' | ForEach-Object {
        Remove-Item "Function:\$_" -ErrorAction SilentlyContinue
    }
    Remove-Variable _OriginalPrompt -Scope Script -ErrorAction SilentlyContinue
    Write-Host "sheLLaMa unloaded" -ForegroundColor DarkGray
}

Write-Host "sheLLaMa loaded — type ,list for commands (,exit to unload)" -ForegroundColor DarkGray
