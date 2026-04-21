#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting Custom Stem Dev (Electron)..."

LOCAL_NODE="$SCRIPT_DIR/.runtime/node/bin/node"
LOCAL_NPM="$SCRIPT_DIR/.runtime/node/bin/npm"

if [ -x "$LOCAL_NODE" ] && [ -x "$LOCAL_NPM" ]; then
  echo "Using portable Node runtime from .runtime/node"
  export PATH="$SCRIPT_DIR/.runtime/node/bin:$PATH"
  NODE_BIN="$LOCAL_NODE"
  NPM_BIN="$LOCAL_NPM"
elif command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  echo "Using system Node runtime"
  NODE_BIN="$(command -v node)"
  NPM_BIN="$(command -v npm)"
else
  echo "Error: No Node runtime found."
  echo "Run './Install Portable Node.command' in this folder to install a local portable Node runtime."
  exit 1
fi

if [ ! -d node_modules/electron ]; then
  echo "Installing desktop UI dependencies..."
  "$NPM_BIN" install --no-fund --no-audit
fi

set +e
"$NPM_BIN" run start
START_EXIT=$?
set -e

if [ "$START_EXIT" -ne 0 ]; then
  echo "Electron CLI launch failed (exit $START_EXIT)."
  exit "$START_EXIT"
fi
