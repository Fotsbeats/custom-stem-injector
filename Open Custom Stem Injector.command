#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/Custom Stem Injector.app"

if [ ! -d "$APP_PATH" ]; then
  osascript -e 'display dialog "Custom Stem Injector.app was not found next to this launcher." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1 || true
  exit 1
fi

# Clear quarantine recursively so Gatekeeper does not block non-notarized builds.
xattr -dr com.apple.quarantine "$APP_PATH" >/dev/null 2>&1 || true

open -n "$APP_PATH" >/dev/null 2>&1 || {
  osascript -e 'display dialog "Unable to open Custom Stem Injector.app. Try right-clicking the app and selecting Open once." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1 || true
  exit 1
}

exit 0
