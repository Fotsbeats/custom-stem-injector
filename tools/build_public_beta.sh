#!/bin/zsh
set -euo pipefail
export COPYFILE_DISABLE=1

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_APP="/Users/zachsilverman/Desktop/Custom Stem Injector/Custom Stem Injector.app"
BETA_DIR="/Users/zachsilverman/Desktop/Custom Stem Injector Beta"
BETA_APP="$BETA_DIR/Custom Stem Injector.app"
BETA_RUNTIME="$BETA_APP/Contents/Resources/app"
BETA_HELPER="$BETA_DIR/Open Custom Stem Injector.command"
BETA_README="$BETA_DIR/README.txt"
BETA_LICENSE="$BETA_DIR/LICENSE.txt"
BETA_ZIP="/Users/zachsilverman/Desktop/Custom Stem Injector Beta.zip"
SOURCE_BETA_README="$ROOT/distribution/BETA_README.txt"
SOURCE_LICENSE="$ROOT/LICENSE.txt"

require_tool() {
  local tool="$1"
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool" >&2
    exit 1
  fi
}

strip_signatures() {
  local app_path="$1"
  find "$app_path" -name _CodeSignature -type d -prune -exec rm -rf {} +
}

strip_appledouble() {
  local target="$1"
  find "$target" -name '._*' -type f -delete
}

require_tool rsync
require_tool ditto
require_tool codesign
require_tool xattr
require_tool zip

if [ ! -d "$SOURCE_APP" ]; then
  echo "Source app not found: $SOURCE_APP" >&2
  exit 1
fi

if [ ! -f "$SOURCE_BETA_README" ]; then
  echo "Beta README not found: $SOURCE_BETA_README" >&2
  exit 1
fi

if [ ! -f "$SOURCE_LICENSE" ]; then
  echo "License file not found: $SOURCE_LICENSE" >&2
  exit 1
fi

echo "1) Quitting running app instances"
osascript -e 'tell application id "com.fotsbeats.customstems" to quit' >/dev/null 2>&1 || true
sleep 1

echo "2) Rebuilding beta folder"
rm -rf "$BETA_DIR"
mkdir -p "$BETA_DIR"
ditto "$SOURCE_APP" "$BETA_APP"

echo "3) Syncing current runtime into beta app"
mkdir -p "$BETA_RUNTIME"
rsync -a --delete --delete-excluded \
  --exclude '/tools/kim2_runtime/model_bs_roformer_ep_317_sdr_12.9755.ckpt' \
  --exclude '/tools/kim2_runtime/model_bs_roformer_ep_317_sdr_12.9755.yaml' \
  --include '/electron/***' \
  --include '/tools/***' \
  --include '/bin/***' \
  --include '/node_modules/***' \
  --include '/package.json' \
  --include '/package-lock.json' \
  --exclude '*' \
  "$ROOT/" "$BETA_RUNTIME/"

echo "4) Removing stale signatures so the app is cleanly unsigned"
strip_signatures "$BETA_APP"
xattr -cr "$BETA_APP" >/dev/null 2>&1 || true
strip_appledouble "$BETA_DIR"

echo "5) Writing beta helper files"
cp -f "$ROOT/Open Custom Stem Injector.command" "$BETA_HELPER"
chmod +x "$BETA_HELPER"
cp -f "$SOURCE_BETA_README" "$BETA_README"
cp -f "$SOURCE_LICENSE" "$BETA_LICENSE"
strip_appledouble "$BETA_DIR"

echo "6) Building zip artifact"
rm -f "$BETA_ZIP"
ditto -c -k --keepParent --norsrc "$BETA_DIR" "$BETA_ZIP"

echo "7) Validation"
spctl -a -vv "$BETA_APP" || true
codesign -dvvv "$BETA_APP" 2>&1 | sed -n '1,20p' || true

echo
echo "Created:"
echo "  Folder: $BETA_DIR"
echo "  App:    $BETA_APP"
echo "  Zip:    $BETA_ZIP"
