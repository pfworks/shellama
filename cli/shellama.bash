# sheLLaMa bash integration — source this in your .bashrc
# Usage: source /path/to/shellama/cli/shellama.bash

# Guard against recursive sourcing (Python CLI snapshots bash env via bash -ic)
[ -n "$SHELLAMA_NO_SOURCE" ] && return 2>/dev/null

#
# Gives you the , command in your real bash session:
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

# Find shellama directory (where this file lives)
SHELLAMA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHELLAMA_BIN="${SHELLAMA_DIR}/shellama"

# Export config if not already set
export SHELLAMA_API="${SHELLAMA_API:-http://192.168.1.229:5000}"
export SHELLAMA_MODEL="${SHELLAMA_MODEL:-auto}"
export SHELLAMA_DOWNLOAD_DIR="${SHELLAMA_DOWNLOAD_DIR:-}"
export SHELLAMA_API_KEY="${SHELLAMA_API_KEY:-}"

# Session conversation ID (persists across , calls in same terminal)
export SHELLAMA_CONV_ID="${SHELLAMA_CONV_ID:-$(python3 -c 'import uuid; print(uuid.uuid4())')}"
export SHELLAMA_SESSION_START="${SHELLAMA_SESSION_START:-$(python3 -c 'import time; print(time.time())')}"

# Add red HAL eye to prompt
_SHELLAMA_ORIG_PS1="$PS1"
PS1="🔴 ${PS1}"

# Unload sheLLaMa
,exit() {
    unset -f , ,, ,do ,explain ,generate ,analyze ,img ,save ,test ,models ,tokens ,list ,help ,exit
    PS1="$_SHELLAMA_ORIG_PS1"
    unset _SHELLAMA_ORIG_PS1 SHELLAMA_CONV_ID
    echo "sheLLaMa unloaded"
}
# Default , is chat (no command execution). Use ,do for agentic mode.
,() {
    if [ $# -eq 0 ]; then
        echo "Usage: , <prompt> or ,<command> <args>"
        echo "Try: ,list"
        return
    fi
    python3 "$SHELLAMA_BIN" quiet "$@"
}

# Agentic mode (AI runs commands)
,do() {
    python3 "$SHELLAMA_BIN" agent "$@"
}

# ,, is same as , (chat)
,,() {
    python3 "$SHELLAMA_BIN" quiet "$@"
}

# Named commands
,explain()  { python3 "$SHELLAMA_BIN" explain "$@"; }
,generate() { python3 "$SHELLAMA_BIN" generate "$@"; }
,analyze()  { python3 "$SHELLAMA_BIN" analyze "$@"; }
,img()      { python3 "$SHELLAMA_BIN" img "$@"; }
,save()     { python3 "$SHELLAMA_BIN" save "$@"; }
,test()     { python3 "$SHELLAMA_BIN" test "$@"; }
,models()   { python3 "$SHELLAMA_BIN" models "$@"; }
,tokens()   { python3 "$SHELLAMA_BIN" tokens "$@"; }
,list()     { python3 "$SHELLAMA_BIN" list "$@"; }
,help()     { python3 "$SHELLAMA_BIN" help "$@"; }
