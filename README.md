# Custom Stem Injector

Custom Stem Injector is a macOS desktop app for building Serato-compatible custom stem files from your own source audio and prepared stem layers. It wraps the existing Python stem-injection pipeline in a standalone Electron app so testers can run the full workflow through a guided UI instead of command-line tools.

This repository is the private source-of-truth repo for the project. Ongoing development happens here. Downloadable tester builds are distributed through GitHub Releases for this same repo rather than through branch ZIP downloads.

The current beta build is aimed at Apple Silicon testers and focuses on a stable three-step workflow:

1. Extract or align source material
2. Prepare Serato-ready audio assets
3. Build the `.serato-stems` sidecar

## What the app does

- Builds Serato stem sidecars from local audio files
- Supports both 2-stem and 4-stem workflows
- Includes built-in 2-stem extraction with Kim-2
- Supports aligning pre-made studio stems against a base track
- Includes a manual alignment editor with waveform timeline, transport, trim, mute, and solo controls
- Preserves the existing Python backend and app packaging flow already in use

## Downloading the app

Do not use GitHub's `Code` -> `Download ZIP` button to get the app. That only downloads the repository contents.

Use the repo's GitHub Releases page instead. The release asset should be:

- `Custom Stem Injector Beta.zip`

That release zip contains:

- `Custom Stem Injector.app`
- `README.txt`
- `LICENSE.txt`
- `Open Custom Stem Injector.command`

## Current workflow

### 2-stem mode

- Step 1: Extract vocals and instrumental from a base track, or align externally made stems
- Step 2: Prepare the selected files for Serato injection
- Step 3: Build the final `.serato-stems` file beside the base audio

### 4-stem mode

- Prepare vocals, bass, drums, and melody files
- Build a final `.serato-stems` sidecar from the prepared set

## Key app behavior

- Extraction is self-contained and does not depend on Ultimate Vocal Remover being installed
- Progress updates stream from the Python bridge into the Electron UI
- Retail mode keeps tester output concise; Debug Mode exposes detailed logs when needed
- The current beta packager produces an unsigned, non-notarized app bundle for tester distribution

## Repository layout

- `electron/main.js`: Electron main process and IPC wiring
- `electron/preload.js`: safe renderer API surface
- `electron/renderer/index.html`: renderer markup
- `electron/renderer/styles.css`: renderer styling
- `electron/renderer/renderer.js`: UI state and interaction logic
- `tools/electron_build_bridge.py`: bridge between Electron and the Python stem pipeline
- `tools/stems_injector_core.py`: core stem build logic
- `tools/build_public_beta.sh`: beta packaging script

## Development workflow

Use this folder as the long-term working project:

- `/Users/zachsilverman/Desktop/Custom Stem Dev`

Treat these as generated outputs, not source:

- `/Users/zachsilverman/Desktop/Custom Stem Dev/Public Builds/Custom Stem Injector Beta`
- `/Users/zachsilverman/Desktop/Custom Stem Dev/Public Builds/Custom Stem Injector Beta.zip`
- `/Users/zachsilverman/Desktop/Custom Stem Injector/Custom Stem Injector.app`

Normal loop:

1. Edit code in this repo.
2. Run the beta build script.
3. Verify the generated beta app and zip.
4. Upload the fresh zip to GitHub Releases.

## Building the beta package

From the repo root:

```bash
cd "/Users/zachsilverman/Desktop/Custom Stem Dev"
./Build\ Public\ Beta.command
```

That script:

- copies the working packaged shell app into a fresh Desktop beta folder
- syncs the latest runtime from this repo into the app bundle
- removes stale signing artifacts
- adds tester-facing documentation and helper files
- builds `Custom Stem Injector Beta.zip`

## Repo scope

This GitHub repo holds the app source, packaging scripts, and release documentation. Large local runtime payloads such as bundled Python dependencies, packaged app shells, and heavyweight model files are kept out of normal Git history so the repository remains pushable and manageable on GitHub. Large compiled app downloads belong in GitHub Releases, not in the branch itself.

## Tester install notes

- The beta is currently unsigned and not notarized
- Apple Silicon is required for the current packaged build
- On first launch, testers may need to approve the app in `System Settings > Privacy & Security`
- The beta folder also includes a helper launcher that removes the quarantine attribute before opening the app

## Distribution status

- Platform: macOS
- Architecture: Apple Silicon
- Signing: ad hoc / unsigned beta distribution
- Intended audience: approved testers

## Copyright and usage

Copyright Fotsbeats 2026. All rights reserved.

This repository and the distributed beta builds are proprietary. No license is granted for redistribution, resale, or public mirroring. See `LICENSE.txt` for the current tester-use terms.
