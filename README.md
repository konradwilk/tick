# Time is Clearly Kept (TICK)

Native time-tracking apps for Android, iPhone, macOS, Windows, and Linux with a choice of local JSON (`tick.json`) or Google Sheets API storage, plus CSV export.

## Goals
- One-tap Start / Stop time tracking
- Select the project for each session
- Optional notes
- Local-first storage and offline support
- Daily, monthly, per-project, and overall totals
- Manual correction/history

## Native clients

New project names and saved notes capitalize the first letter of each entry.
Commas and line breaks start a new activity; other casing and whitespace are preserved.
This applies to tracking, manual sessions, and note edits. Existing saved data is
unchanged until edited.

The main screen puts project selection and Start/Stop first, followed by notes.
On every platform, the last selected project is remembered across app launches.
An active session takes priority; if the remembered project is unavailable, the
first project is selected.
History and **Export & copy** sit side by side in wide windows and stack on
phones or narrow windows. Capture stays visible while the workspace scrolls.
The report panel previews the exact summary produced by **Copy summary**.
Use **Settings** for adding projects and choosing **Local file** or **Google Sheets** storage.

In all five apps, choose **Settings → Add session by hand** to record completed
work. Manual entry remembers its last selected project across app launches,
independently of the tracking selector. Select a project, describe what you worked on, and enter the start and end
dates and times in your local timezone. Add the project in Settings first if
needed. The end defaults to 15 minutes after the start and follows start changes
until you edit the end yourself, moving to the next day when needed. The end must
be after the start. The form checks all projects for overlapping saved sessions as
the dates change and again before saving. Each conflict shows its activity, project,
total duration, overlap duration (HH:MM:SS), and overlapping local time range.
Running sessions are checked through the current time and labeled "running, so far".
Touching endpoints do not overlap. Choose **Save**, review any conflicts, then choose
**Save anyway** to confirm intentional overlap; changing the draft requires a fresh
confirmation. Saving adds the session to history,
totals, CSV exports, and summaries; a running timer continues unchanged.

CSV export in Windows, macOS, iOS, Android, and Linux offers **Daily**, **Weekly**, and
**Monthly** periods. Choose a date within the desired period, check the displayed
date range and completed-session count, then choose **Export CSV**. The file
contains individual session records, including durations and notes, and its name
includes the period and starting date. The default is the current month.

All clients use these CSV columns, in order: `projectName`, `startTimeUtc`,
`endTimeUtc`, `durationSeconds`, `hours`, `notes`, `deviceId`, `platform`.
The exports omit `sessionId`, `projectId`, and `updatedAtUtc`.

Periods use the device's local timezone; weeks run Monday–Sunday and months use
calendar boundaries. A completed session belongs to its start date, including its
full duration if it crosses midnight. Active sessions are excluded. Empty periods
disable export and copy.

**Copy summary** groups the selected sessions by project. Each
heading resolves the current project name by project ID and contains its total
duration for the selected period, followed
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

Session history displays entries by start time, newest first,
including newly added backdated sessions. All five clients separate history with
an outlined box around each week's date heading and entries. Weeks run Monday–Sunday in the device's
local timezone; sessions are grouped by their start date, including sessions that
cross midnight. Empty weeks are omitted.

In session history, choose **Edit notes** on a completed session in Windows,
macOS, iOS, Android, or Linux. Completed sessions under one minute also show
**Delete** beside **Edit notes**; deleting removes them from history, totals,
and future exports and summaries. Sessions lasting exactly one minute or longer
and active sessions cannot be deleted.

Choose **Edit times** on a completed session to correct its start and end dates
and times in your local timezone. The end must be after the start. **Save**
recalculates the duration, updates totals and reports, and reorders History;
**Cancel** leaves the original times unchanged. If saving fails, the editor stays
open with your changes available to retry. Stop active sessions before editing times.

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
- `apple/` shared Swift model/storage code plus iOS and macOS targets
- `windows/` Windows native app
- `linux/` Linux GTK native app
- `docs/` architecture and API contract

## Run the macOS app

Requires macOS 14 or later, Swift 6, Git, and Python 3.9+ (`python3` on PATH).
All clients derive their Settings version from release tags; see
[versioning](docs/versioning.md). Build the app from the repository root:

```sh
sh apple/scripts/build-macos.sh
```

Open `apple/build/Time is Clearly Kept.app`. Quit any older running copy before opening
the rebuilt app. The build script also accepts Swift build options such as
`--scratch-path /tmp/tick-build`.

Click the clock in the menu bar at the top of the screen to select a project,
enter optional notes, and use green **Start** / red **Stop**. While tracking, the
icon becomes a recording symbol and the panel shows elapsed time. The menu bar
and main window share the same session, project selection, and draft notes.
Close the main window to keep using the menu bar; choose **Open Time is Clearly Kept**
to return to history and CSV export. Add your first project in the main window.

Quitting does not stop an active session. Its start time is saved; reopen the app
and press Stop to finish. Data is saved in `tick.json` in your chosen folder.

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

Both implement the local tracking milestone: project selection/creation,
Start/Stop, notes, persistent sessions, history, totals, and CSV export. They use the
shared versioned file format in `docs/data-storage.md`; the same data file can
be used across platforms.

`.github/workflows/native-clients.yml` builds and tests both platforms and uploads
an Android debug APK and Windows x64 publish folder. These new platform builds have
not been executed on the development Mac, which lacks Android SDK/JDK/Gradle and
.NET/Windows tools. Check the workflow results or build on a configured machine
before distributing either app.

## Linux GTK

[Linux setup and tests](linux/README.md) — native GTK 4 interface with project
selection, Start/Stop, notes, restart-safe timing, history, totals, and CSV export.
Install the system GTK/Python packages, then run `python3 -m tick` from
`linux/`. Core tests run without GTK; the Native clients workflow also runs a GTK
smoke test on Ubuntu.

## Configure where data is stored

On first launch and in Settings, all five apps offer two choices:

- **Local file (tick.json)**: choose a folder or existing file; local folders work offline.
- **Google Sheets**: sign in with Google, then create or open a spreadsheet. Internet is required; no Apps Script setup or access key is needed.

The app remembers your choice. An empty destination receives your current data;
an existing destination opens without merging. The previous destination is preserved.
Use one device at a time; stale Sheets saves are rejected, and concurrent revisions are retained for recovery.

See [Google Sheets setup and Python migration](docs/google-sheets.md). The separate
migration tool validates, uploads, and verifies an existing `tick.json`, leaving
its source untouched:

```sh
python3 tools/migrate_to_sheets.py /path/to/tick.json --dry-run
python3 tools/migrate_to_sheets.py /path/to/tick.json --name "Time is Clearly Kept"
```

Use `python` on Windows. The tool opens your browser for Google sign-in and verifies the upload. See
[storage behavior and compatibility](docs/data-storage.md) for local file details.

[iPhone/iPad build instructions](apple/iOS/README.md).

## Naming and compatibility

TICK stands for **Time is Clearly Kept**. Project files, executables, and CSV
exports use `tick`. Shared data folders use `tick.json`. Application identifiers use the `org.timeisclearlykept` base:

| Platform | Application identifier |
| --- | --- |
| Android | `org.timeisclearlykept` |
| iPhone / iPad | `org.timeisclearlykept.ios` |
| macOS | `org.timeisclearlykept.mac` |
| Windows (unpackaged manifest and instance key) | `org.timeisclearlykept.windows` |
| Linux | `org.timeisclearlykept.Linux` |

Android source packages and the Gradle namespace also use `org.timeisclearlykept`.
Default Apple and Windows data folders use `TimeIsClearlyKept`; Linux uses
`time-is-clearly-kept` for its data and settings folders. Old default locations
are not searched or migrated. The renamed apps start with fresh settings and
ask for a data location when no data has been selected. Android and iOS install
as new apps with separate private storage and preferences. Data files remain
named `tick.json`.
