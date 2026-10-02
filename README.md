# Time is Clearly Kept (TICK)

Native time-tracking apps for Android, iPhone, macOS, Windows, and Linux that save data in a local JSON file (`tick.json`), with optional CSV export.

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

New nonprofit names and saved notes capitalize the first letter of each entry.
Commas and line breaks start a new activity; other casing and whitespace are preserved.
This applies to tracking, manual sessions, and note edits. Existing saved data is
unchanged until edited.

The main screen puts nonprofit selection and Start/Stop first, followed by notes.
History and **Export & copy** sit side by side in wide windows and stack on
phones or narrow windows. Capture stays visible while the workspace scrolls.
The report panel previews the exact summary produced by **Copy summary**.
Use **Settings** for adding nonprofits and choosing the data folder.

In all five apps, choose **Settings → Add session by hand** to record completed
work. Select a nonprofit, describe what you worked on, and enter the start and end
dates and times in your local timezone. Add the nonprofit in Settings first if
needed. The end defaults to 15 minutes after the start and follows start changes
until you edit the end yourself, moving to the next day when needed. The end must
be after the start. Saving adds the session to history,
totals, CSV exports, and summaries; a running timer continues unchanged.

CSV export in Windows, macOS, iOS, Android, and Linux offers **Daily**, **Weekly**, and
**Monthly** periods. Choose a date within the desired period, check the displayed
date range and completed-session count, then choose **Export CSV**. The file
contains individual session records, including durations and notes, and its name
includes the period and starting date. The default is the current month.

All clients use these CSV columns, in order: `nonprofitName`, `startTimeUtc`,
`endTimeUtc`, `durationSeconds`, `hours`, `notes`, `deviceId`, `platform`.
The exports omit `sessionId`, `nonprofitId`, and `updatedAtUtc`.

Periods use the device's local timezone; weeks run Monday–Sunday and months use
calendar boundaries. A completed session belongs to its start date, including its
full duration if it crosses midnight. Active sessions are excluded. Empty periods
disable export and copy.

**Copy summary** groups the selected sessions by nonprofit. Each
heading contains its name and total duration for the selected period, followed
by descriptions in alphabetical order. Sessions with the same displayed
description are combined into one entry with their durations added together:

```text
Kitchen 01:45:00:
Cleanup   00:45:00
Meals   01:00:00
```

Durations use `HH:MM:SS`. Empty or whitespace-only notes display as **No notes**.
Clipboard notes are split into activities at commas and line breaks, with whitespace
trimmed and empty activities ignored. Each session's seconds are divided equally
among its activities; leftover seconds go to the first activities in their original
order so the total stays exact. Shares are then combined by description. Matching is case-sensitive; alphabetical
sorting ignores case. Saved notes and CSV retain the original text and individual sessions,
and durations longer than 24 hours are not wrapped. A confirmation appears after
copying. iOS and macOS compile the same tracking and export implementation.

In session history, choose **Edit notes** on a completed session in Windows,
macOS, iOS, Android, or Linux. Completed sessions under one minute also show
**Delete** beside **Edit notes**; deleting removes them from history, totals,
and future exports and summaries. Sessions lasting exactly one minute or longer
and active sessions cannot be deleted.

In the notes editor, **Save** persists the edited notes and includes them in
future CSV exports; **Cancel** discards the draft. Times and recorded hours stay
unchanged. If saving fails, the editor keeps your draft available to retry.
See [iPhone and iPad setup](apple/iOS/README.md) for the Xcode project and build
instructions. Apple and Android builds require their native development tools;
the newly added iOS UI and storage implementations still need native verification.

- Android: Kotlin + Jetpack Compose
- iPhone: Swift + SwiftUI
- macOS: Swift + SwiftUI
- Windows: C# + WinUI 3
- Linux: Python + GTK 4 / PyGObject

## Session model
See `docs/session-schema.md`.

## Repository layout
- `android/` Android native app
- `apple/` shared Swift model/sync code plus iOS and macOS targets
- `windows/` Windows native app
- `linux/` Linux GTK native app
- `docs/` architecture and API contract

## Run the macOS app

Requires macOS 14 or later and Swift 6. Build the app from the repository root:

```sh
sh apple/scripts/build-macos.sh
```

Open `apple/build/Time is Clearly Kept.app`. Quit any older running copy before opening
the rebuilt app. The build script also accepts Swift build options such as
`--scratch-path /tmp/tick-build`.

Click the clock in the menu bar at the top of the screen to select a nonprofit,
enter optional notes, and use green **Start** / red **Stop**. While tracking, the
icon becomes a recording symbol and the panel shows elapsed time. The menu bar
and main window share the same session, nonprofit selection, and draft notes.
Close the main window to keep using the menu bar; choose **Open Time is Clearly Kept**
to return to history and CSV export. Add your first nonprofit in the main window.

Quitting does not stop an active session. Its start time is saved; reopen the app
and press Stop to finish. Data is stored locally in
`~/Library/Application Support/NonprofitHours/sessions.json`.

Export completed sessions with **Export CSV…** when you need a separate report.
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
Install the system GTK/Python packages, then run `python3 -m tick` from
`linux/`. Core tests run without GTK; the Native clients workflow also runs a GTK
smoke test on Ubuntu.

## Configure where data is stored

Use **Data location** to choose a folder. The app remembers it and automatically
reads and saves `tick.json` there on every launch and change. If the file
already exists, its data is loaded; otherwise the current data is copied into the
folder, preserving the original. This is a persistent setting, not an import/export
step. Select the corresponding shared folder on your other devices.

All five clients use the same versioned JSON format and accept the earlier Apple
and Android formats. Use one device at a time and let any cloud synchronization
finish before switching devices. See [storage behavior and compatibility](docs/data-storage.md).

[iPhone/iPad build instructions](apple/iOS/README.md).

## Naming and compatibility

TICK stands for **Time is Clearly Kept**. Project files, executables, and CSV
exports use `tick`. Shared data folders use `tick.json`. Application identifiers
and private/default storage locations remain unchanged.
