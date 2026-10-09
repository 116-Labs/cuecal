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

command="$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))')"

# This hook lives at <repo>/scripts/hooks/, so two `..` up.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"

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

# Definitively outside this repo: skip.
if [[ "$effective_cwd" != "$REPO_ROOT" && "$effective_cwd" != "$REPO_ROOT"/* ]]; then
  exit 0
fi

if [[ "$command" =~ (^|[[:space:];|&])git[[:space:]]+commit([[:space:]]|$|\;) ]]; then
  branch="$(git -C "$effective_cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ "$branch" == "main" ]]; then
    echo "cuecal: refusing \`git commit\` on main." >&2
    echo "Commit on a feature branch and open a PR:  git switch -c chore/<slug>" >&2
    exit 2
  fi
fi

exit 0
