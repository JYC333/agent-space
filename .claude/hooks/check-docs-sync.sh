#!/usr/bin/env bash
# PostToolUse hook — remind agent to update .agent/ docs when structural files change.
#
# Claude Code passes tool input as JSON on stdin:
#   {"tool_name": "Edit", "tool_input": {"file_path": "...", ...}, "tool_response": {...}}
#
# Exit 0 = feedback only (no block). Exit 2 = block the tool call (PreToolUse only).

set -euo pipefail

input=$(cat)

# Extract file_path from tool_input
file_path=$(printf '%s' "$input" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')
" 2>/dev/null)

[[ -z "$file_path" ]] && exit 0

basename_file=$(basename "$file_path")

# Map filenames to the .agent/ docs that should be reviewed after an edit.
# Format: "filename|doc1,doc2,..."
declare -A DOC_MAP
DOC_MAP["models.py"]="modules/space.md, modules/agents.md, modules/memory.md, modules/proposals.md, GLOSSARY.md"
DOC_MAP["schemas.py"]="modules/space.md, modules/agents.md, modules/memory.md"
DOC_MAP["runner.py"]="modules/agents.md, modules/sandbox.md"
DOC_MAP["sandbox_manager.py"]="modules/sandbox.md"
DOC_MAP["context_builder.py"]="modules/memory.md, modules/context-compiler.md"
DOC_MAP["context_compiler.py"]="modules/context-compiler.md"
DOC_MAP["agent_service.py"]="modules/agents.md"
DOC_MAP["seeder.py"]="modules/agents.md"
DOC_MAP["engine.py"]="modules/policy.md"
DOC_MAP["rules.py"]="modules/policy.md, BOUNDARIES.md"
DOC_MAP["decisions.py"]="modules/policy.md"
DOC_MAP["path_policy.py"]="modules/sandbox.md, modules/workspace-console.md"
DOC_MAP["reflector.py"]="modules/memory.md, modules/proposals.md"
DOC_MAP["evolver.py"]="modules/memory.md"
DOC_MAP["proposals.py"]="modules/proposals.md, modules/memory.md"

relevant_docs="${DOC_MAP[$basename_file]:-}"

if [[ -n "$relevant_docs" ]]; then
    echo ""
    echo "╔─ DOCS SYNC REMINDER ──────────────────────────────────────────╗"
    echo "│ '$basename_file' was edited."
    echo "│ Review these .agent/ docs if the change affects their content:"
    echo "│"
    IFS=',' read -ra docs <<< "$relevant_docs"
    for doc in "${docs[@]}"; do
        echo "│   .agent/${doc# }"
    done
    echo "│"
    echo "│ Also check: .agent/tasks/current-focus.md (if status changed)"
    echo "╚───────────────────────────────────────────────────────────────╝"
fi

exit 0
