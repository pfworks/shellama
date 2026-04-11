# sheLLaMa bash integration — source this in your .bashrc
# Usage: source /path/to/shellama/cli/shellama.bash
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
export SHELLAMA_MODEL="${SHELLAMA_MODEL:-qwen2.5-coder:7b}"

# The , function — dispatches to Python CLI
,() {
    if [ $# -eq 0 ]; then
        echo "Usage: , <prompt> or ,<command> <args>"
        echo "Try: ,list"
        return
    fi
    python3 "$SHELLAMA_BIN" agent "$@"
}

# Quiet mode
,,() {
    AI_QUIET=true python3 "$SHELLAMA_BIN" quiet "$@"
}

# Named commands
,explain()  { python3 "$SHELLAMA_BIN" explain "$@"; }
,generate() { python3 "$SHELLAMA_BIN" generate "$@"; }
,analyze()  { python3 "$SHELLAMA_BIN" analyze "$@"; }
,img()      { python3 "$SHELLAMA_BIN" img "$@"; }
,test()     { python3 "$SHELLAMA_BIN" test "$@"; }
,models()   { python3 "$SHELLAMA_BIN" models "$@"; }
,tokens()   { python3 "$SHELLAMA_BIN" tokens "$@"; }
,list()     { python3 "$SHELLAMA_BIN" list "$@"; }
,help()     { python3 "$SHELLAMA_BIN" help "$@"; }
