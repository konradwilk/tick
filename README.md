# Nonprofit Hours

Native time-tracking apps for Android, iPhone, macOS, Windows, and Linux with CSV export for Google Sheets.

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

In session history, choose **Edit notes** on a completed session in Windows,
macOS, Android, or Linux. **Save** persists the edited notes and includes them in
future CSV exports; **Cancel** discards the draft. Times and recorded hours stay
unchanged. If saving fails, the editor keeps your draft available to retry.
The shared Apple core also supports note updates for iOS; this checkout does not
include the iOS screen sources.
- Android: Kotlin + Jetpack Compose
- iPhone: Swift + SwiftUI
- macOS: Swift + SwiftUI
- Windows: C# + WinUI 3
- Linux: Python + GTK 4 / PyGObject

## Backend
A small Google Apps Script endpoint will accept completed time sessions and upsert them into a Google Sheet using a globally unique session ID.

## Session model
See `docs/session-schema.md`.

## Repository layout
- `android/` Android native app
- `apple/` shared Swift model/sync code plus iOS and macOS targets
- `windows/` Windows native app
- `linux/` Linux GTK native app
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
using File → Import. Automatic Sheets sync is still pending.
The iOS app is in `apple/iOS/`; it uses the same Swift tracking and storage library.
The app bundle is unsigned and intended for local use.

Run the tracking tests:

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path apple
```

## Android and Windows

- [Android build and installation](android/README.md): Kotlin / Jetpack Compose.
- [Windows build and installation](windows/README.md): C# / WinUI 3.

Both implement the local tracking milestone: nonprofit selection/creation,
Start/Stop, notes, persistent sessions, history, totals, and CSV export. They use the
shared versioned file format in `docs/data-storage.md`; the same data file can
be used across platforms. Google Sheets automatic sync remains a future milestone.

`.github/workflows/native-clients.yml` builds and tests both platforms and uploads
an Android debug APK and Windows x64 publish folder. These new platform builds have
not been executed on the development Mac, which lacks Android SDK/JDK/Gradle and
.NET/Windows tools. Check the workflow results or build on a configured machine
before distributing either app.

## Linux GTK

[Linux setup and tests](linux/README.md) — native GTK 4 interface with nonprofit
selection, Start/Stop, notes, restart-safe timing, history, totals, and CSV export.
Install the system GTK/Python packages, then run `python3 -m nonprofit_hours` from
`linux/`. Core tests run without GTK; the Native clients workflow also runs a GTK
smoke test on Ubuntu. Automatic Google Sheets sync remains pending.

## Configure where data is stored

Use **Data location** to choose a folder. The app remembers it and automatically
reads and saves `nonprofit-hours.json` there on every launch and change. If the file
already exists, its data is loaded; otherwise the current data is copied into the
folder, preserving the original. This is a persistent setting, not an import/export
step. Select the corresponding shared folder on your other devices.

All five clients use the same versioned JSON format and accept the earlier Apple
and Android formats. Use one device at a time and let any cloud synchronization
finish before switching devices. See [storage behavior and compatibility](docs/data-storage.md).

[iPhone/iPad build instructions](apple/iOS/README.md).
