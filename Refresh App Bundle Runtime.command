#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_RT="$ROOT/Custom Stem Dev.app/Contents/Resources/AppRuntime"

sync_runtime() {
  local target="$1"
  local label="$2"

  mkdir -p "$target"
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
    "$ROOT/" "$target/"
  echo "Refreshed $label runtime: $target"
}

sync_runtime "$APP_RT" "embedded app"
