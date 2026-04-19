# sheLLaMa shared PowerShell config — sourced by shellama.ps1 and GUI files
$script:SHELLAMA_API = if ($env:SHELLAMA_API) { $env:SHELLAMA_API } else { "http://192.168.1.229:5000" }
$script:SHELLAMA_MODEL = if ($env:SHELLAMA_MODEL) { $env:SHELLAMA_MODEL } else { "auto" }
$script:SHELLAMA_API_KEY = if ($env:SHELLAMA_API_KEY) { $env:SHELLAMA_API_KEY } else { "" }
$script:SHELLAMA_CONV_ID = if ($env:SHELLAMA_CONV_ID) { $env:SHELLAMA_CONV_ID } else { [guid]::NewGuid().ToString() }
$script:SHELLAMA_DOWNLOAD_DIR = if ($env:SHELLAMA_DOWNLOAD_DIR) { $env:SHELLAMA_DOWNLOAD_DIR } else { "" }
$script:SHELLAMA_SYSTEM_PROMPT = @"
You are an AI assistant running inside a PowerShell session on Windows.
Current directory: {0}

You can run PowerShell commands to answer the user's question. To run a command, output it in a ``````powershell block.
ONLY use ``````powershell blocks for commands you want executed — NEVER for code examples.
For code examples in other languages, use the appropriate language tag or no tag.
When you have enough info, give your final answer as plain text with no ``````powershell blocks.
Always run commands yourself. Keep commands short and focused.
"@

function Get-ShellamaHeaders {
    $headers = @{ "Content-Type" = "application/json" }
    if ($script:SHELLAMA_API_KEY) { $headers["X-API-Key"] = $script:SHELLAMA_API_KEY }
    return $headers
}
