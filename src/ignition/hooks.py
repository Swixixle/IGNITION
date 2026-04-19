"""Print-only shell snippets for optional integration (never installs or edits rc files)."""

from __future__ import annotations


def hook_print_body(shell: str) -> str:
    shell = shell.lower().strip()
    if shell == "fish":
        return _fish_snippet()
    if shell == "bash":
        return _bash_snippet()
    return _zsh_snippet()


def _bash_snippet() -> str:
    return r"""# IGNITION — paste into ~/.bashrc (optional)
alias igs='ignition start'
alias igc='ignition checkpoint'
alias igst='ignition status'
alias igx='ignition stop'
alias igcur='ignition current'

# Show active task/branch in prompt (prepend to PS1 as you like):
__ignition_prompt_info() {
  command -v ignition >/dev/null 2>&1 || return 0
  local out
  out=$(ignition current --json 2>/dev/null) || return 0
  command -v jq >/dev/null 2>&1 || return 0
  local task br
  task=$(echo "$out" | jq -r '.task // empty')
  br=$(echo "$out" | jq -r '.branch // empty')
  if [[ -n "$task" ]]; then
    printf '[%s @ %s] ' "$task" "$br"
  fi
}
"""


def _zsh_snippet() -> str:
    return r"""# IGNITION — paste into ~/.zshrc (optional)
alias igs='ignition start'
alias igc='ignition checkpoint'
alias igst='ignition status'
alias igx='ignition stop'
alias igcur='ignition current'

__ignition_prompt_info() {
  command -v ignition >/dev/null 2>&1 || return 0
  local out
  out=$(ignition current --json 2>/dev/null) || return 0
  command -v jq >/dev/null 2>&1 || return 0
  local task br
  task=$(echo "$out" | jq -r '.task // empty')
  br=$(echo "$out" | jq -r '.branch // empty')
  if [[ -n "$task" ]]; then
    printf '[%s @ %s] ' "$task" "$br"
  fi
}
# Example: PS1='$(__ignition_prompt_info)'"$PS1"
"""


def _fish_snippet() -> str:
    return r"""# IGNITION — paste into ~/.config/fish/config.fish (optional)
alias igs='ignition start'
alias igc='ignition checkpoint'
alias igst='ignition status'
alias igx='ignition stop'
alias igcur='ignition current'

function __ignition_prompt_info
    command -q ignition; or return
    set -l out (ignition current --json 2>/dev/null); or return
    command -q jq; or return
    set -l task (echo $out | jq -r '.task // empty')
    set -l br (echo $out | jq -r '.branch // empty')
    if test -n "$task"
        printf '[%s @ %s] ' $task $br
    end
end
"""
