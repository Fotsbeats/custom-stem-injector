# Custom Stem Injector Beta

Version: `0.1.0-beta.3`

## Release Summary

Custom Stem Injector Beta is an Apple Silicon macOS test build for approved testers.

## What's new in Beta 3

- fixed packaged extraction failure caused by read-only app-bundle writes under App Translocation
- moved mutable runtime support files and CoreML temp data into the writable injector work area under `~/Music/Custom Stem Injector`
- keeps bundled Python runtime support from Beta 2 so testers should not need to install Python separately

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
