# Nonprofit Hours

Native time-tracking apps for Android, iPhone, macOS, and Windows with Google Sheets sync.

## Goals
- One-tap Start / Stop time tracking
- Select the nonprofit for each session
- Optional notes
- Local-first storage and offline support
- Automatic Google Sheets sync
- Daily, monthly, per-nonprofit, and overall totals
- Manual correction/history
- Duplicate-safe synchronization across devices

## Native clients
- Android: Kotlin + Jetpack Compose
- iPhone: Swift + SwiftUI
- macOS: Swift + SwiftUI
- Windows: C# + WinUI 3

## Backend
A small Google Apps Script endpoint will accept completed time sessions and upsert them into a Google Sheet using a globally unique session ID.

## Session model
See `docs/session-schema.md`.

## Repository layout
- `android/` Android native app
- `apple/` shared Swift model/sync code plus iOS and macOS targets
- `windows/` Windows native app
- `backend/` Google Apps Script backend
- `docs/` architecture and API contract

## Run the macOS app

Requires macOS 14 or later and Swift 6. Build the app from the repository root:

```sh
sh apple/scripts/build-macos.sh
```

Open `apple/build/Nonprofit Hours.app`. Quit any older running copy before opening
the rebuilt app. The build script also accepts Swift build options such as
`--scratch-path /tmp/nonprofit-hours-build`.

Click the clock in the menu bar at the top of the screen to select a nonprofit,
enter optional notes, and use green **Start** / red **Stop**. While tracking, the
icon becomes a recording symbol and the panel shows elapsed time. The menu bar
and main window share the same session, nonprofit selection, and draft notes.
Close the main window to keep using the menu bar; choose **Open Nonprofit Hours**
to return to history and CSV export. Add your first nonprofit in the main window.

Quitting does not stop an active session. Its start time is saved; reopen the app
and press Stop to finish. Data is stored locally in
`~/Library/Application Support/NonprofitHours/sessions.json`.

Export completed sessions with **Export CSV…** and import the file in Google Sheets
using File → Import. Automatic Sheets sync and native iOS, Android, and Windows
clients are still pending. The shared Swift tracking library is available for iOS.
The app bundle is unsigned and intended for local use.

Run the tracking tests:

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path apple
```
