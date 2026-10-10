#!/usr/bin/env bash

# cuecal — publish a release from this machine.
#
# Builds origin/main in a throwaway worktree, runs the lint and test gates,
# builds the wheel and sdist with `uv build`, smoke-tests the wheel as users
# install it (`uv tool install`, into a private tool dir with a private config
# and state DB, so the cuecal this machine runs is left alone), then tags
# v<version> and creates the GitHub Release with both files attached.
#
# The version is the one in pyproject.toml; bump it (and cuecal.__version__)
# in a PR first. It refuses to publish a version whose tag already exists.
#
# Users install a release with:
#   uv tool install https://github.com/116-Labs/cuecal/releases/download/v<version>/cuecal-<version>-py3-none-any.whl
#
# Usage: ./scripts/release.sh [--dry-run]
#   --dry-run  build, check and smoke-test, but tag and publish nothing
#
# Needs git, uv and gh (signed in, with write access to the repo).

set -euo pipefail

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run) DRY_RUN=true ;;
    --help | -h)
      sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "release: unknown option $1 (try --help)" >&2
      exit 2
      ;;
  esac
  shift
done

for tool in git uv gh; do
  command -v "$tool" >/dev/null || {
    echo "release: $tool is not on PATH" >&2
    exit 1
  }
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
REPO="116-Labs/cuecal"

git -C "$REPO_ROOT" fetch -q --tags origin main
SHA="$(git -C "$REPO_ROOT" rev-parse origin/main)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cuecal-release.XXXXXX")"
cleanup() {
  git -C "$REPO_ROOT" worktree remove --force "$WORK/src" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "release: building ${SHA:0:7} (origin/main) in $WORK"
git -C "$REPO_ROOT" worktree add -q --detach "$WORK/src" "$SHA"
cd "$WORK/src"

# The version lives in two places; a release where they disagree would report
# the wrong `cuecal --version`.
VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -n 1)"
PKG_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/cuecal/__init__.py)"
if [[ -z "$VERSION" || "$VERSION" != "$PKG_VERSION" ]]; then
  echo "release: pyproject.toml version ($VERSION) and cuecal.__version__ ($PKG_VERSION) differ" >&2
  exit 1
fi
if git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
  echo "release: v$VERSION is already tagged; bump the version first." >&2
  exit 1
fi
echo "release: version $VERSION"

uv sync --frozen --quiet
uv run --frozen ruff check .
uv run --frozen pytest -q

uv build --quiet --out-dir "$WORK/dist"
WHEEL="$WORK/dist/cuecal-$VERSION-py3-none-any.whl"
SDIST="$WORK/dist/cuecal-$VERSION.tar.gz"
[[ -f "$WHEEL" && -f "$SDIST" ]] || {
  echo "release: uv build did not produce $(basename "$WHEEL") and $(basename "$SDIST")" >&2
  exit 1
}

# The MCP source mappings ship as data files inside the package; a wheel
# without them installs fine and fails only at `cuecal run`. The listing is
# captured first: piping unzip into `grep -q` under pipefail fails spuriously
# when grep exits early and unzip takes SIGPIPE.
CONTENTS="$(unzip -l "$WHEEL")"
for mapping in zoho-mail zoho-cliq; do
  grep -q "cuecal/sources/mappings/$mapping.toml" <<<"$CONTENTS" || {
    echo "release: the wheel is missing sources/mappings/$mapping.toml" >&2
    exit 1
  }
done

# Smoke-test the wheel as users install it. Every location cuecal or uv
# writes to is redirected into $WORK.
export UV_TOOL_DIR="$WORK/tools" UV_TOOL_BIN_DIR="$WORK/bin"
export CUECAL_CONFIG="$WORK/home/config.toml" CUECAL_DB="$WORK/home/state.db"
export CUECAL_LOG_DIR="$WORK/home/logs" CUECAL_LAUNCHD_PLIST="$WORK/home/agent.plist"
uv tool install --quiet "$WHEEL"
CUECAL="$WORK/bin/cuecal"

"$CUECAL" --version | grep -qx "cuecal $VERSION" || {
  echo "release: the installed cuecal does not report version $VERSION" >&2
  exit 1
}
"$CUECAL" init >/dev/null
DOCTOR="$("$CUECAL" doctor)" || {
  echo "release: cuecal doctor failed on a fresh install:" >&2
  echo "$DOCTOR" >&2
  exit 1
}
# The plugin registry reads entry points from the installed metadata, so this
# is the check that the packaging, not just the code, is right.
for plugin in "sources: .*gmail" "sinks: .*google-calendar"; do
  grep -q "^$plugin" <<<"$DOCTOR" || {
    echo "release: cuecal doctor does not list the plugin matching '$plugin':" >&2
    echo "$DOCTOR" >&2
    exit 1
  }
done
echo "release: smoke test passed ($(basename "$WHEEL"))"

if [[ "$DRY_RUN" == true ]]; then
  echo "release: dry run, so v$VERSION is built and checked but not published."
  exit 0
fi

gh release create "v$VERSION" "$WHEEL" "$SDIST" \
  --repo "$REPO" --target "$SHA" --title "v$VERSION" --generate-notes
echo "release: published v$VERSION from ${SHA:0:7}."
echo "release: install with uv tool install https://github.com/$REPO/releases/download/v$VERSION/$(basename "$WHEEL")"
