# Custom Stem Injector

Custom Stem Injector is a macOS app for creating Serato-compatible custom stem files from your own audio and stem sources.

It supports:

- 2-stem workflows using a base track plus vocals/instrumental
- 4-stem workflows using vocals, bass, drums, and melody
- built-in 2-stem and 4-stem extraction
- stem alignment tools for matching stems to a base song
- industry-leading separation models focused on high-quality stem extraction

## Download

Download the app from the repository's [Releases](https://github.com/Fotsbeats/custom-stem-injector/releases) page.

Do not use GitHub's `Code` download ZIP. That only contains repository files, not the packaged app.

Look for the release asset:

- `Custom.Stem.Injector.Beta.zip`

## Install

1. Download `Custom.Stem.Injector.Beta.zip` from the latest Release.
2. Unzip it.
3. Move `Custom Stem Injector.app` to `Applications` if you want.
4. Open the app.

If macOS blocks the first launch:

1. Open `System Settings > Privacy & Security`
2. Click `Open Anyway` for Custom Stem Injector
3. Confirm the second prompt

The download also includes `Open Custom Stem Injector.command`, which can help open the app on first launch.

## How It Works

The app follows a simple workflow:

1. Extract or align stems
2. Prepare the files for Serato
3. Build the final `.serato-stems` file

The finished `.serato-stems` sidecar is created next to your base audio file.

## Requirements

- macOS
- Apple Silicon Mac

## Notes

- The current beta build is unsigned and not notarized, so first-launch approval may be required.
- Python is bundled inside the app. You should not need to install Python separately.

## Copyright

Copyright Fotsbeats 2026. All rights reserved.

See `LICENSE.txt` for current use terms.
