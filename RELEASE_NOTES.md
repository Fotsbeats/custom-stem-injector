# Custom Stem Injector Beta

Version: `0.1.0-beta.5`

## Release Summary

Custom Stem Injector Beta is an Apple Silicon macOS test build for approved testers.

## What's new in Beta 5

- bundles ffmpeg/ffprobe runtime libraries so tester Macs do not need Homebrew
- repairs stale packaged model links created by App Translocation between launches
- improves extraction decoding for common AAC/M4A inputs
- fixes Align Stems rendering failures caused by the aligned MP3 ffmpeg filter chain
- improves backend error reporting so the app shows the real bridge error instead of progress lines

## Included asset

- `Custom Stem Injector Beta.zip`

Use the Release asset download, not the repository branch ZIP from the `Code` menu.

## Install notes

- unsigned and not notarized
- first launch may require approval in `System Settings > Privacy & Security`
- helper launcher included: `Open Custom Stem Injector.command`

## Known distribution constraints

- Apple Silicon only
- distributed through GitHub Releases

## Copyright

Copyright Fotsbeats 2026. All rights reserved.
