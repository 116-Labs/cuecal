#!/usr/bin/env bash
# PreToolUse(Bash) hook: refuse `git commit` on `main`, so changes land on a
# feature branch and merge through a pull request. A local mirror of the
# `main-protection` ruleset, which admins can bypass server-side.
#
# Only enforces when the effective cwd (a leading `cd <path>`, else $PWD) is
# inside this repo. Not bulletproof (subshells, pushd), but covers day-to-day
# shapes.
#
# Override (rare): export CUECAL_SKIP_HOOKS=1 before starting the session.

set -euo pipefail

[[ "${CUECAL_SKIP_HOOKS:-0}" == "1" ]] && exit 0

input="$(cat)"

# Windows often has no `python3`, or only the Store stub, which exists but
# fails; use the first interpreter that actually runs.
py=""
for candidate in python3 python py; do
  if "$candidate" -c 'import json' >/dev/null 2>&1; then
    py="$candidate"
    break
  fi
done

# A parse failure must still block: any exit but 2 lets the tool call through.
if [[ -n "$py" ]]; then
  if ! command="$(printf '%s' "$input" | "$py" -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))')"; then
    echo "cuecal: unable to parse hook input; refusing tool call." >&2
    exit 2
  fi
elif command -v jq >/dev/null 2>&1; then
  if ! command="$(printf '%s' "$input" | jq -er '.tool_input.command')"; then
    echo "cuecal: unable to parse hook input; refusing tool call." >&2
    exit 2
  fi
else
  # No Python or jq (stock Git Bash on Windows): pull tool_input.command out
  # with sed. Refuse anything it can't decode reliably rather than allow it:
  # a missing command, or \uXXXX escapes, which could spell `git commit`.
  raw="$(printf '%s' "$input" | tr -d '\n' \
    | sed -nE 's/.*"command"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)".*/\1/p')"
  if [[ -z "$raw" || "$raw" == *'\u'* ]]; then
    echo "cuecal: unable to parse hook input without python or jq; refusing tool call." >&2
    exit 2
  fi
  command="$(printf '%s' "$raw" \
    | sed -e 's/\\n/\n/g' -e 's/\\t/\t/g' -e 's/\\r//g' -e 's/\\"/"/g' -e 's#\\/#/#g' -e 's/\\\\/\\/g')"
fi

# Only gate `git commit`, allowing git's -C <path> and -c <name=value> before it.
GIT_OPTS='(([[:space:]]+-[Cc][[:space:]]+[^[:space:];|&()]+)*)'
if [[ ! "$command" =~ (^|[[:space:];|&])git${GIT_OPTS}[[:space:]]+commit([[:space:]]|$|\;) ]]; then
  exit 0
fi
git_opts="${BASH_REMATCH[2]}"

# This hook lives at <repo>/scripts/hooks/, so two `..` up.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"

# Effective cwd: a leading `cd <path>`, else $PWD; then any `git -C <path>`,
# applied in order as git does.
effective_cwd=""
if [[ "$command" =~ ^[[:space:]]*cd[[:space:]]+([^[:space:];|\&]+) ]]; then
  cd_target="${BASH_REMATCH[1]}"
  cd_target="${cd_target%\"}"; cd_target="${cd_target#\"}"
  cd_target="${cd_target%\'}"; cd_target="${cd_target#\'}"
  cd_target="${cd_target/#\~/$HOME}"
  if [[ -d "$cd_target" ]]; then
    effective_cwd="$(cd "$cd_target" 2>/dev/null && pwd -P || true)"
  fi
fi
[[ -z "$effective_cwd" ]] && effective_cwd="$(pwd -P)"
while [[ "$git_opts" =~ -C[[:space:]]+([^[:space:];|&()]+)(.*) ]]; do
  c_target="${BASH_REMATCH[1]}"; git_opts="${BASH_REMATCH[2]}"
  c_target="${c_target%\"}"; c_target="${c_target#\"}"
  c_target="${c_target%\'}"; c_target="${c_target#\'}"
  c_target="${c_target/#\~/$HOME}"
  [[ "$c_target" != /* ]] && c_target="$effective_cwd/$c_target"
  effective_cwd="$(cd "$c_target" 2>/dev/null && pwd -P || echo "$effective_cwd")"
done

# Definitively outside this repo, or in a repo nested inside it: skip.
if [[ "$effective_cwd" != "$REPO_ROOT" && "$effective_cwd" != "$REPO_ROOT"/* ]]; then
  exit 0
fi
top="$(git -C "$effective_cwd" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -n "$top" && "$(cd "$top" && pwd -P)" != "$REPO_ROOT" ]]; then
  exit 0
fi

branch="$(git -C "$effective_cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ "$branch" == "main" ]]; then
  echo "cuecal: refusing \`git commit\` on main." >&2
  echo "Commit on a feature branch and open a PR:  git switch -c chore/<slug>" >&2
  exit 2
fi

exit 0
