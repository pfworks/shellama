<# : batch launcher
@echo off
powershell -ExecutionPolicy Bypass -NoProfile -Command "& {iex (Get-Content '%~f0' -Raw)}"
exit /b
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Minimize the console window so only the GUI shows
Add-Type -Name Win32 -Namespace Native -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();'
[Native.Win32]::ShowWindow([Native.Win32]::GetConsoleWindow(), 6) | Out-Null  # 6 = SW_MINIMIZE

$SHELLAMA_API = if ($env:SHELLAMA_API) { $env:SHELLAMA_API } elseif ($env:ANSIBLE_TOOLS_API) { $env:ANSIBLE_TOOLS_API } else { "http://192.168.1.229:5000" }
$SHELLAMA_MODEL = if ($env:SHELLAMA_MODEL) { $env:SHELLAMA_MODEL } else { "qwen2.5-coder:7b" }

$form = New-Object System.Windows.Forms.Form
$form.Text = "SheLLama"
$form.Size = New-Object System.Drawing.Size(1000, 700)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)
$form.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 0)
$font = New-Object System.Drawing.Font("Consolas", 10)
$form.Font = $font

$topPanel = New-Object System.Windows.Forms.FlowLayoutPanel
$topPanel.Dock = "Top"
$topPanel.Height = 40
$topPanel.BackColor = $form.BackColor
$topPanel.Padding = New-Object System.Windows.Forms.Padding(5)

$lblApi = New-Object System.Windows.Forms.Label
$lblApi.Text = "API:"
$lblApi.AutoSize = $true
$topPanel.Controls.Add($lblApi)

$txtApi = New-Object System.Windows.Forms.TextBox
$txtApi.Text = $SHELLAMA_API
$txtApi.Width = 250
$txtApi.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 45)
$txtApi.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 0)
$topPanel.Controls.Add($txtApi)

$lblModel = New-Object System.Windows.Forms.Label
$lblModel.Text = "  Model:"
$lblModel.AutoSize = $true
$topPanel.Controls.Add($lblModel)

$cmbModel = New-Object System.Windows.Forms.ComboBox
$cmbModel.Width = 200
$cmbModel.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 45)
$cmbModel.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 0)
$cmbModel.DropDownStyle = "DropDownList"
$cmbModel.Items.Add($SHELLAMA_MODEL)
$cmbModel.SelectedIndex = 0
$topPanel.Controls.Add($cmbModel)

$btnRefresh = New-Object System.Windows.Forms.Button
$btnRefresh.Text = "Refresh"
$btnRefresh.Width = 70
$btnRefresh.FlatStyle = "Flat"
$btnRefresh.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 45)
$btnRefresh.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 0)
$topPanel.Controls.Add($btnRefresh)

$form.Controls.Add($topPanel)

$txtOutput = New-Object System.Windows.Forms.RichTextBox
$txtOutput.Dock = "Fill"
$txtOutput.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)
$txtOutput.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 0)
$txtOutput.Font = $font
$txtOutput.ReadOnly = $true
$txtOutput.BorderStyle = "None"
$form.Controls.Add($txtOutput)

$inputPanel = New-Object System.Windows.Forms.Panel
$inputPanel.Dock = "Bottom"
$inputPanel.Height = 35
$inputPanel.BackColor = $form.BackColor

$lblPrompt = New-Object System.Windows.Forms.Label
$lblPrompt.Text = "PS>"
$lblPrompt.AutoSize = $true
$lblPrompt.Location = New-Object System.Drawing.Point(5, 8)
$inputPanel.Controls.Add($lblPrompt)

$txtInput = New-Object System.Windows.Forms.TextBox
$txtInput.Location = New-Object System.Drawing.Point(45, 5)
$txtInput.Width = $form.ClientSize.Width - 55
$txtInput.Anchor = "Left,Right,Top"
$txtInput.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 45)
$txtInput.ForeColor = [System.Drawing.Color]::FromArgb(0, 255, 0)
$txtInput.Font = $font
$inputPanel.Controls.Add($txtInput)

$form.Controls.Add($inputPanel)
$txtOutput.BringToFront()

function Write-Terminal {
    param([string]$Text, [System.Drawing.Color]$Color = [System.Drawing.Color]::FromArgb(0, 255, 0))
    $txtOutput.SelectionStart = $txtOutput.TextLength
    $txtOutput.SelectionColor = $Color
    $txtOutput.AppendText("$Text`n")
    $txtOutput.ScrollToCaret()
}

function Invoke-ShellamaAPI {
    param([string]$Endpoint, [hashtable]$Body)
    $json = $Body | ConvertTo-Json -Depth 10
    $frames = @("🦙     ", "🦙 .   ", "🦙 ..  ", "🦙 ... ")
    $uri = "$($txtApi.Text)$Endpoint"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $req = [System.Net.HttpWebRequest]::Create($uri)
    $script:activeRequest = $req
    $req.Method = "POST"
    $req.ContentType = "application/json"
    $req.Timeout = 3600000
    $req.ReadWriteTimeout = 3600000
    $stream = $req.GetRequestStream()
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Close()
    $asyncResult = $req.BeginGetResponse($null, $null)
    $i = 0
    while (-not $asyncResult.IsCompleted) {
        if (-not $form.Visible) { $req.Abort(); return $null }
        $lblPrompt.Text = $frames[$i % 4]
        $lblPrompt.Refresh()
        $i++
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 250
    }
    $script:activeRequest = $null
    $lblPrompt.Text = "PS>"
    $lblPrompt.Refresh()
    $webResp = $req.EndGetResponse($asyncResult)
    $reader = New-Object System.IO.StreamReader($webResp.GetResponseStream())
    $respText = $reader.ReadToEnd()
    $reader.Close()
    $webResp.Close()
    return ($respText | ConvertFrom-Json)
}

function Refresh-Models {
    $cmbModel.Items.Clear()
    try {
        $resp = Invoke-RestMethod -Uri "$($txtApi.Text)/models" -TimeoutSec 10
        foreach ($m in $resp.models) { $cmbModel.Items.Add($m.name) }
        if ($cmbModel.Items.Count -gt 0) { $cmbModel.SelectedIndex = 0 }
        Write-Terminal "Loaded $($cmbModel.Items.Count) models" ([System.Drawing.Color]::Gray)
    } catch {
        $cmbModel.Items.Add($SHELLAMA_MODEL)
        $cmbModel.SelectedIndex = 0
        Write-Terminal "Could not fetch models: $_" ([System.Drawing.Color]::Red)
    }
}

function Invoke-StopAll {
    try { Invoke-RestMethod -Uri "$($txtApi.Text)/stop-all" -Method Post -TimeoutSec 5 | Out-Null } catch {}
}

function Invoke-AgentLoop {
    param([string]$Query)
    $model = $cmbModel.SelectedItem
    $system = @"
You are an AI assistant running inside a PowerShell session on Windows.
Current directory: $(Get-Location)

You can run PowerShell commands to answer the user's question. To run a command, output it in a ```powershell block.
When you have enough info, give your final answer as plain text with no ```powershell blocks.
Always run commands yourself. Keep commands short and focused.
"@
    $conversation = "$system`n`nUser: $Query"
    $totalTokens = 0; $totalElapsed = 0

    for ($round = 0; $round -lt 10; $round++) {
        $lblPrompt.Text = "🦙..."
        $lblPrompt.Refresh()
        [System.Windows.Forms.Application]::DoEvents()
        $resp = Invoke-ShellamaAPI "/chat" @{ message = $conversation; model = $model }
        $lblPrompt.Text = "PS>"
        $lblPrompt.Refresh()
        if (-not $resp -or $resp.error) {
            if ($resp.error) { Write-Terminal "Error: $($resp.error)" ([System.Drawing.Color]::Red) }
            return
        }
        $response = $resp.response
        $tokens = if ($resp.total_tokens) { $resp.total_tokens } else { 0 }
        $elapsed = if ($resp.elapsed) { $resp.elapsed } else { 0 }
        $totalTokens += $tokens; $totalElapsed += $elapsed

        $commands = [regex]::Matches($response, '```powershell\n(.*?)```', 'Singleline') | ForEach-Object { $_.Groups[1].Value.Trim() }

        if ($commands.Count -eq 0) {
            Write-Terminal $response ([System.Drawing.Color]::Cyan)
            Write-Terminal "[$($round + 1) round$(if($round){'s'}) | $([math]::Round($totalElapsed,1))s | $totalTokens tokens | $model]" ([System.Drawing.Color]::Gray)
            return
        }

        $parts = [regex]::Split($response, '```powershell\n.*?```', 'Singleline')
        foreach ($part in $parts) { $part = $part.Trim(); if ($part) { Write-Terminal $part ([System.Drawing.Color]::Cyan) } }
        Write-Terminal "[round $($round + 1) | $([math]::Round($elapsed,1))s | $tokens tokens]" ([System.Drawing.Color]::Gray)

        $cmdOutputs = @()
        foreach ($cmd in $commands) {
            Write-Terminal "PS> $cmd" ([System.Drawing.Color]::Yellow)
            try {
                $output = Invoke-Expression $cmd 2>&1 | Out-String
                if ($output.Trim()) { Write-Terminal $output.Trim() ([System.Drawing.Color]::DarkGray) }
                $cmdOutputs += "PS> $cmd`n$output"
            } catch {
                Write-Terminal "Error: $_" ([System.Drawing.Color]::Red)
                $cmdOutputs += "PS> $cmd`nError: $_"
            }
        }
        $results = $cmdOutputs -join "`n`n"
        $conversation += "`n`nAssistant: $response`n`nCommand output:`n$results`n`nContinue. If you have enough information, give your final answer without any ``````powershell blocks."
    }
    Write-Terminal "[max rounds reached | $([math]::Round($totalElapsed,1))s | $totalTokens tokens]" ([System.Drawing.Color]::Gray)
}

function Process-Input {
    $line = $txtInput.Text.Trim()
    $txtInput.Clear()
    $txtInput.Refresh()
    if (-not $line) { return }
    $model = $cmbModel.SelectedItem
    Write-Terminal "PS> $line" ([System.Drawing.Color]::White)

    if ($line -in @('exit', 'quit')) { $form.Close(); return }

    if ($line.StartsWith(",")) {
        $query = $line.Substring(1).Trim()
        if ($query -in @('list', 'help')) {
            Write-Terminal ",  <prompt>       agentic chat" ([System.Drawing.Color]::Yellow)
            Write-Terminal ",explain  <file>  explain any file" ([System.Drawing.Color]::Yellow)
            Write-Terminal ",generate <desc>  generate code" ([System.Drawing.Color]::Yellow)
            Write-Terminal ",analyze  <path>  analyze files/dirs" ([System.Drawing.Color]::Yellow)
            Write-Terminal ",img <prompt>     generate image" ([System.Drawing.Color]::Yellow)
            Write-Terminal ",models           refresh models" ([System.Drawing.Color]::Yellow)
            Write-Terminal ",stop             stop backend" ([System.Drawing.Color]::Yellow)
            return
        }
        if ($query -eq 'models') { Refresh-Models; return }
        if ($query -eq 'stop') { Invoke-StopAll; Write-Terminal "Stop sent to backend" ([System.Drawing.Color]::Gray); return }
        try {
            if ($query.StartsWith('explain ')) {
                $file = $query.Substring(8).Trim()
                $content = Get-Content $file -Raw -ErrorAction Stop
                $ext = [IO.Path]::GetExtension($file).ToLower()
                if ($ext -in @('.yml', '.yaml')) {
                    $resp = Invoke-ShellamaAPI "/explain" @{ playbook = $content; model = $model }
                    Write-Terminal $resp.explanation ([System.Drawing.Color]::Cyan)
                } else {
                    $resp = Invoke-ShellamaAPI "/explain-code" @{ code = $content; model = $model }
                    Write-Terminal $resp.explanation ([System.Drawing.Color]::Cyan)
                }
            }
            elseif ($query.StartsWith('generate ')) {
                $desc = $query.Substring(9).Trim()
                if ($desc -match 'ansible|playbook|shell command') {
                    $resp = Invoke-ShellamaAPI "/generate" @{ commands = $desc; model = $model }
                    Write-Terminal $resp.playbook ([System.Drawing.Color]::Cyan)
                } else {
                    $resp = Invoke-ShellamaAPI "/generate-code" @{ description = $desc; model = $model }
                    Write-Terminal $resp.code ([System.Drawing.Color]::Cyan)
                }
            }
            elseif ($query.StartsWith('analyze ')) {
                $paths = $query.Substring(8).Trim() -split '\s+'
                [array]$filesData = @()
                foreach ($p in $paths) {
                    if (Test-Path $p -PathType Container) {
                        Get-ChildItem $p -Recurse -File | ForEach-Object {
                            try { $filesData += @{ path = $_.FullName; content = (Get-Content $_.FullName -Raw) } } catch {}
                        }
                    } elseif (Test-Path $p) {
                        try { $filesData += @{ path = (Resolve-Path $p).Path; content = (Get-Content $p -Raw) } } catch {}
                    } else {
                        Write-Terminal "${p}: not found" ([System.Drawing.Color]::Red)
                    }
                }
                if ($filesData.Count -eq 0) { Write-Terminal "No readable files found" ([System.Drawing.Color]::Red); return }
                Write-Terminal "Analyzing $($filesData.Count) file$(if($filesData.Count -ne 1){'s'})..." ([System.Drawing.Color]::Gray)
                $resp = Invoke-ShellamaAPI "/analyze" @{ files = @($filesData); model = $model }
                if ($resp.error) { Write-Terminal "Error: $($resp.error)" ([System.Drawing.Color]::Red) }
                elseif ($resp.analysis) { Write-Terminal $resp.analysis ([System.Drawing.Color]::Cyan) }
            }
            elseif ($query.StartsWith('img ')) {
                $im = if ($env:AI_IMAGE_MODEL) { $env:AI_IMAGE_MODEL } else { "sd-turbo" }
                $st = if ($im -match "turbo") { 4 } else { 20 }
                $resp = Invoke-ShellamaAPI "/generate-image" @{ prompt = $query.Substring(4).Trim(); image_model = $im; steps = $st; width = 512; height = 512 }
                if ($resp.image) {
                    $outfile = "$PWD\generated_$([int](Get-Date -UFormat %s)).png"
                    [IO.File]::WriteAllBytes($outfile, [Convert]::FromBase64String($resp.image))
                    Write-Terminal "Saved: $outfile" ([System.Drawing.Color]::Cyan)
                }
            }
            else {
                # Default: agentic chat
                Invoke-AgentLoop -Query $query
                return
            }
            if ($resp.elapsed) {
                Write-Terminal "[$($resp.elapsed)s | $($resp.total_tokens) tokens | $model]" ([System.Drawing.Color]::Gray)
            }
        } catch {
            Write-Terminal "Error: $_" ([System.Drawing.Color]::Red)
        }
    }
    else {
        try {
            $output = Invoke-Expression $line 2>&1 | Out-String
            if ($output.Trim()) { Write-Terminal $output.Trim() }
        } catch {
            Write-Terminal $_.Exception.Message ([System.Drawing.Color]::Red)
        }
    }
}

$btnRefresh.Add_Click({ Refresh-Models })
$txtInput.Add_KeyDown({
    if ($_.KeyCode -eq 'Return') { $_.SuppressKeyPress = $true; Process-Input }
})

$script:activeRequest = $null

$form.Add_FormClosing({
    param($s, $e)
    if ($script:activeRequest) {
        try { $script:activeRequest.Abort() } catch {}
        $script:activeRequest = $null
    }
})

Write-Terminal "SheLLama - PowerShell + AI agent" ([System.Drawing.Color]::Cyan)
Write-Terminal "Type , for AI commands, ,list for help" ([System.Drawing.Color]::Gray)
Write-Terminal ""
Refresh-Models
$txtInput.Focus()
[void]$form.ShowDialog()
$form.Dispose()
