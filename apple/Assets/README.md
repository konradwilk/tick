# Apple app icons

`folder-clock.svg` is the same artwork added in commit
`4de13dd409aac99ab8a6b298c735a3bb2ecaa30b` for Windows.
The macOS bundle uses `Tick.icns`; iOS uses `Assets.xcassets/AppIcon.appiconset`.

To regenerate both from the SVG, run from the repository root on macOS:

```sh
swift apple/scripts/generate-icons.swift
```

The generator uses AppKit and iconutil. It adds a white background, rounded for
macOS and opaque square for iOS (where the system applies the icon mask).
