#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

NODE_VERSION="${NODE_VERSION:-v20.19.0}"
RUNTIME_DIR="$SCRIPT_DIR/.runtime"
TARGET_DIR="$RUNTIME_DIR/node"
TMP_DIR="$RUNTIME_DIR/tmp"

mkdir -p "$RUNTIME_DIR" "$TMP_DIR"

if [ -d "$TARGET_DIR/bin" ]; then
  echo "Portable Node already installed at: $TARGET_DIR"
  echo "Remove '$TARGET_DIR' if you want to reinstall."
  exit 0
fi

ARCH="$(uname -m)"
case "$ARCH" in
  arm64)
    NODE_ARCH="arm64"
    ;;
  x86_64)
    NODE_ARCH="x64"
    ;;
  *)
    echo "Unsupported macOS architecture: $ARCH"
    exit 1
    ;;
esac

TARBALL="node-${NODE_VERSION}-darwin-${NODE_ARCH}.tar.gz"
URL="https://nodejs.org/dist/${NODE_VERSION}/${TARBALL}"
ARCHIVE_PATH="${1:-}"

if [ -n "$ARCHIVE_PATH" ]; then
  if [ ! -f "$ARCHIVE_PATH" ]; then
    echo "Archive not found: $ARCHIVE_PATH"
    exit 1
  fi
  SRC_ARCHIVE="$ARCHIVE_PATH"
  echo "Using local archive: $SRC_ARCHIVE"
else
  SRC_ARCHIVE="$TMP_DIR/$TARBALL"
  echo "Downloading portable Node runtime: $URL"
  curl -LfsS "$URL" -o "$SRC_ARCHIVE"
fi

echo "Extracting runtime..."
EXTRACT_DIR="$TMP_DIR/extract"
rm -rf "$EXTRACT_DIR"
mkdir -p "$EXTRACT_DIR"
tar -xzf "$SRC_ARCHIVE" -C "$EXTRACT_DIR"

EXTRACTED_ROOT="$EXTRACT_DIR/node-${NODE_VERSION}-darwin-${NODE_ARCH}"
if [ ! -d "$EXTRACTED_ROOT" ]; then
  echo "Unexpected archive layout; expected: $EXTRACTED_ROOT"
  exit 1
fi

mv "$EXTRACTED_ROOT" "$TARGET_DIR"

echo "Portable Node installed: $TARGET_DIR"
"$TARGET_DIR/bin/node" -v
"$TARGET_DIR/bin/npm" -v

echo "Done. Start the app with: ./Start\\ Custom\\ Stems\\ UI.command"
