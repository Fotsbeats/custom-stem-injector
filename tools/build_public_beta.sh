#!/bin/zsh
set -euo pipefail
export COPYFILE_DISABLE=1

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_APP="$ROOT/node_modules/electron/dist/Electron.app"
BETA_ROOT="$ROOT/Public Builds"
BETA_DIR="$BETA_ROOT/Custom Stem Injector Beta"
BETA_APP="$BETA_DIR/Custom Stem Injector.app"
BETA_RUNTIME="$BETA_APP/Contents/Resources/app"
BETA_HELPER="$BETA_DIR/Open Custom Stem Injector.command"
BETA_README="$BETA_DIR/README.txt"
BETA_LICENSE="$BETA_DIR/LICENSE.txt"
BETA_ZIP="$BETA_ROOT/Custom Stem Injector Beta.zip"
RELEASE_ZIP="$BETA_ROOT/Custom.Stem.Injector.Beta.zip"
SOURCE_BETA_README="$ROOT/distribution/BETA_README.txt"
SOURCE_LICENSE="$ROOT/LICENSE.txt"
SOURCE_ICON="$ROOT/tools/AppIcon.icns"
PYTHON_PREFIX="$(python3 -c 'import sys; print(sys.prefix)')"
PYTHON_VERSION="$(python3 -c 'import sys; print("{}.{}".format(sys.version_info.major, sys.version_info.minor))')"
SOURCE_PYTHON_FRAMEWORK="$(cd "$PYTHON_PREFIX/../.." && pwd)"
FRAMEWORKS_DIR="$BETA_APP/Contents/Frameworks"
EMBEDDED_PYTHON_FRAMEWORK="$FRAMEWORKS_DIR/Python3.framework"
EMBEDDED_PYTHON_BIN="$EMBEDDED_PYTHON_FRAMEWORK/Versions/$PYTHON_VERSION/bin/python$PYTHON_VERSION"

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

is_system_dylib() {
  local dep="$1"
  case "$dep" in
    /System/*|/usr/lib/*)
      return 0
      ;;
  esac
  return 1
}

bundle_ffmpeg_dylibs() {
  local ffmpeg_bin="$BETA_RUNTIME/bin/ffmpeg"
  local ffprobe_bin="$BETA_RUNTIME/bin/ffprobe"
  local dylib_dir="$BETA_RUNTIME/bin/ffmpeg-libs"
  local rpath="@executable_path/ffmpeg-libs"
  local -a roots targets deps pending lib_files
  local -A copied
  local item dep dest dep_name target source_ffprobe

  if [ ! -x "$ffmpeg_bin" ]; then
    echo "Bundled ffmpeg not found or not executable: $ffmpeg_bin" >&2
    exit 1
  fi

  if [ ! -x "$ffprobe_bin" ]; then
    source_ffprobe="$(command -v ffprobe || true)"
    if [ -n "$source_ffprobe" ] && [ -x "$source_ffprobe" ]; then
      cp -f "$source_ffprobe" "$ffprobe_bin"
      chmod +x "$ffprobe_bin"
    fi
  fi

  roots=("$ffmpeg_bin")
  if [ -x "$ffprobe_bin" ]; then
    roots+=("$ffprobe_bin")
  fi

  rm -rf "$dylib_dir"
  mkdir -p "$dylib_dir"
  pending=("${roots[@]}")

  while [ "${#pending[@]}" -gt 0 ]; do
    item="${pending[1]}"
    pending=("${pending[@]:1}")
    deps=("${(@f)$(otool -L "$item" | awk 'NR > 1 { print $1 }')}")
    for dep in "${deps[@]}"; do
      if is_system_dylib "$dep"; then
        continue
      fi
      case "$dep" in
        @rpath/*|@loader_path/*|@executable_path/*)
          continue
          ;;
      esac
      if [ ! -f "$dep" ]; then
        echo "Missing ffmpeg dependency: $dep" >&2
        exit 1
      fi
      dep_name="${dep:t}"
      dest="$dylib_dir/$dep_name"
      if [[ -z "${copied[$dep_name]:-}" ]]; then
        cp -f "$dep" "$dest"
        chmod u+w "$dest"
        copied[$dep_name]="$dest"
        pending+=("$dest")
      fi
    done
  done

  targets=("${roots[@]}")
  lib_files=("$dylib_dir"/*.dylib(N))
  targets+=("${lib_files[@]}")

  for target in "${targets[@]}"; do
    deps=("${(@f)$(otool -L "$target" | awk 'NR > 1 { print $1 }')}")
    for dep in "${deps[@]}"; do
      if is_system_dylib "$dep"; then
        continue
      fi
      case "$dep" in
        @rpath/*|@loader_path/*|@executable_path/*)
          continue
          ;;
      esac
      dep_name="${dep:t}"
      if [ -f "$dylib_dir/$dep_name" ]; then
        install_name_tool -change "$dep" "@rpath/$dep_name" "$target"
      fi
    done
  done

  for target in "$dylib_dir"/*.dylib; do
    [ -f "$target" ] || continue
    install_name_tool -id "@rpath/${target:t}" "$target"
  done

  for target in "${roots[@]}"; do
    if ! otool -l "$target" | grep -F "$rpath" >/dev/null 2>&1; then
      install_name_tool -add_rpath "$rpath" "$target"
    fi
  done

  for target in "${targets[@]}"; do
    codesign --force --sign - "$target" >/dev/null 2>&1
  done
}

customize_shell() {
  local app_path="$1"
  local plist="$app_path/Contents/Info.plist"
  local main_icon="$app_path/Contents/Resources/electron.icns"
  local custom_icon="$app_path/Contents/Resources/CustomStemInjector.icns"

  if [ -f "$SOURCE_ICON" ]; then
    cp -f "$SOURCE_ICON" "$main_icon"
    cp -f "$SOURCE_ICON" "$custom_icon"
  fi

  if [ -f "$plist" ]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName Custom Stem Injector" "$plist" >/dev/null 2>&1 || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleName Custom Stem Injector" "$plist" >/dev/null 2>&1 || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.fotsbeats.customstems" "$plist" >/dev/null 2>&1 || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile CustomStemInjector" "$plist" >/dev/null 2>&1 || true
    /usr/libexec/PlistBuddy -c "Set :LSApplicationCategoryType public.app-category.music" "$plist" >/dev/null 2>&1 || true
  fi
}

require_tool rsync
require_tool ditto
require_tool codesign
require_tool install_name_tool
require_tool otool
require_tool xattr
require_tool zip

if [ ! -x /usr/libexec/PlistBuddy ]; then
  echo "Missing required tool: /usr/libexec/PlistBuddy" >&2
  exit 1
fi

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

if [ ! -f "$SOURCE_ICON" ]; then
  echo "App icon not found: $SOURCE_ICON" >&2
  exit 1
fi

if [ ! -d "$SOURCE_PYTHON_FRAMEWORK" ]; then
  echo "Bundled Python framework source not found: $SOURCE_PYTHON_FRAMEWORK" >&2
  exit 1
fi

echo "1) Quitting running app instances"
osascript -e 'tell application id "com.fotsbeats.customstems" to quit' >/dev/null 2>&1 || true
sleep 1

echo "2) Rebuilding beta folder"
rm -rf "$BETA_DIR"
mkdir -p "$BETA_ROOT"
mkdir -p "$BETA_DIR"
ditto "$SOURCE_APP" "$BETA_APP"
customize_shell "$BETA_APP"

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

echo "4) Embedding Python runtime"
mkdir -p "$FRAMEWORKS_DIR"
rm -rf "$EMBEDDED_PYTHON_FRAMEWORK"
ditto "$SOURCE_PYTHON_FRAMEWORK" "$EMBEDDED_PYTHON_FRAMEWORK"

echo "5) Bundling ffmpeg runtime libraries"
bundle_ffmpeg_dylibs

echo "6) Removing stale signatures so the app is cleanly unsigned"
strip_signatures "$BETA_APP"
xattr -cr "$BETA_APP" >/dev/null 2>&1 || true
strip_appledouble "$BETA_DIR"

echo "7) Writing beta helper files"
cp -f "$ROOT/Open Custom Stem Injector.command" "$BETA_HELPER"
chmod +x "$BETA_HELPER"
cp -f "$SOURCE_BETA_README" "$BETA_README"
cp -f "$SOURCE_LICENSE" "$BETA_LICENSE"
strip_appledouble "$BETA_DIR"

echo "8) Applying fresh ad hoc signature"
codesign --force --deep --sign - "$BETA_APP" >/dev/null 2>&1

echo "9) Building zip artifact"
rm -f "$BETA_ZIP"
rm -f "$RELEASE_ZIP"
ditto -c -k --keepParent --norsrc "$BETA_DIR" "$BETA_ZIP"
cp -f "$BETA_ZIP" "$RELEASE_ZIP"

echo "10) Validation"
spctl -a -vv "$BETA_APP" || true
codesign -dvvv "$BETA_APP" 2>&1 | sed -n '1,20p' || true
"$BETA_RUNTIME/bin/ffmpeg" -hide_banner -version | sed -n '1,3p'
"$EMBEDDED_PYTHON_BIN" -c "import sys; print(sys.executable); print(sys.prefix)" || true
"$EMBEDDED_PYTHON_BIN" -c "import sys; sys.path.insert(0, r'$BETA_RUNTIME/tools/_pydeps'); import mutagen, numpy; print('Embedded Python import check: ok')" || true

echo
echo "Created:"
echo "  Folder: $BETA_DIR"
echo "  App:    $BETA_APP"
echo "  Zip:    $BETA_ZIP"
echo "  Asset:  $RELEASE_ZIP"
