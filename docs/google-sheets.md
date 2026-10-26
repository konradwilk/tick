# Google Sheets storage and migration

Tick connects directly to Google Sheets with your Google account. No Apps Script,
deployment URL, service account, or shared access key is needed.

## What you see in the spreadsheet

**Sessions** is the first tab: one row per session, with the project, UTC start
and end times (YYYY-MM-DD HH:MM:SS), duration (hours:minutes:seconds), numeric hours, notes, status, and
platform. A running session has no end time or final duration yet.

**Projects** lists each project with total completed hours and its session count
(including a running session). Headers stay visible when scrolling, and filters
let you find a project or session. Hours display two decimal places; calculations
retain full precision.

Tick stores one current row per session and project. IDs, versions, deletion markers,
and complete records occupy hidden columns in those rows. Make changes in Tick;
the visible columns are readable projections, not an editor for Tick's data.
Text is always literal, including notes beginning with `=`. Long notes are
preserved across hidden cells in the same row; the visible preview shows the
first 20,000 characters.

A normal save reads current rows and a small journal index in one batch, writes
only changed rows in another batch, and verifies the result with one read. It
does not download previous dataset snapshots or reapply formatting. A note edit
usually updates one session row; stopping a session can also update its project's
totals. Deleting a session marks its existing row deleted and clears its visible
cells. Blank rows left by deletion are intentional.

The hidden `TickChanges` journal retains only the rows changed by each save for
conflict recovery. `TickMeta` identifies the row format and shared dataset.
On the first save, an older `TickLog` or `TickData` dataset migrates automatically.
Its original contents remain intact in `TickLogBackup` or `TickDataBackup`.
Install this version on every device before migrating: older clients cannot open
the new format. The first migration is larger than later saves.

### Fix a spreadsheet migrated by an older version

There is no need to migrate again or create another spreadsheet. Close Tick on
other devices, then refresh the existing spreadsheet's layout:

```sh
python3 tools/migrate_to_sheets.py --upgrade-existing --spreadsheet SPREADSHEET_ID_OR_URL
```

This upgrades an older Tick dataset to row storage and verifies its contents.
The spreadsheet name, URL, IDs, projects, sessions, and old recovery history are
preserved. Running the command again on row storage verifies it without adding
a journal entry. `Sessions`, `Projects`, `TickMeta`, and `TickChanges` are reserved
for Tick; put your own analysis in differently named tabs. Sorting complete rows
is supported because Tick locates records by ID on each save; do not sort only
the visible columns independently of their hidden columns.

## Connect in the app

1. Choose **Google Sheets** in Settings or on first launch.
2. Choose **Sign in with Google** to start Google sign-in directly, then approve
   access to files you use with Tick. The storage choices explain the internet
   requirement before you sign in.
3. Choose **Create a new spreadsheet**, or select an existing Tick spreadsheet
   that appears in the list.
4. For a new spreadsheet, keep **Time is Clearly Kept** or enter another name.
5. Choose **Connect**.

A new spreadsheet receives your current projects and sessions. An existing Tick
dataset opens without merging; its name and data are preserved. The choice is
remembered. On macOS, iOS/iPadOS, Windows, Android, and Linux, Settings marks the
current storage option in green with **✓ Active**; the other option is gray and
labeled **Not active**. The highlight changes after a successful connection or
folder selection. To switch back, choose Local file and a new folder to copy your current
data, or an existing folder to open its `tick.json`.

Internet is required. Local file storage remains available for offline work.
Google's `drive.file` permission limits access to files created by or authorized
for Tick. The list is not a list of every spreadsheet in your Google Drive.
Arbitrary spreadsheets are not overwritten or converted to Tick datasets.

While the Google project is in Testing, your Google account must be listed under
Google Auth Platform → Audience → Test users. Desktop and iOS client IDs are
bundled. Android's package and signing certificate must also be registered by
the app maintainer before Android sign-in will work. Android uses Google Play
services authorization; devices without compatible Google Play services can use
local storage. See [maintainer setup](google-cloud-setup.md).

## Migrate tick.json using Python

The separate [migration tool](../tools/migrate_to_sheets.py) runs on Windows,
macOS, and Linux with Python 3.9+ and the standard library. Keep `tools/` and
`linux/tick/` together. GTK is not required. The distributed tool must include the
maintainer-generated installed-app configuration described below.

Validate the source without signing in or contacting Google:

```sh
python3 tools/migrate_to_sheets.py /path/to/tick.json --dry-run
```

Migrate with browser sign-in:

```sh
python3 tools/migrate_to_sheets.py /path/to/tick.json
```

The tool reuses your saved Google sign-in or opens your default browser to request
permission. It creates **Time is Clearly Kept** by default. Choose another name:

```sh
python3 tools/migrate_to_sheets.py /path/to/tick.json --name "My work hours"
```

Use `--sign-in` to choose the Google account again. On Windows use `python` and a
quoted Windows path:

```powershell
python tools/migrate_to_sheets.py "C:\Users\You\Documents\tick.json" --name "My work hours"
```

For a specific uninitialized Tick spreadsheet already authorized for the app,
use `--spreadsheet ID_OR_URL`. Existing Tick datasets are refused even if they
contain no projects or sessions. The tool does not replace data.

Migration validates the source before Google sign-in, uploads all projects and
sessions, and reads back both the dataset and readable tables to verify their contents. IDs, timestamps, notes,
and running sessions are retained. Compatible legacy JSON is normalized to schema
v1, and sessions are sorted by start time. The source file is never changed.
The tool prints the created spreadsheet URL after successful verification.
In the app, sign in to the same Google account and open that spreadsheet.

If a request times out, its write may already have succeeded. Keep `tick.json`,
open/reload the destination, and inspect it before retrying. A retry that targets
an initialized sheet refuses to overwrite it. A retry without `--spreadsheet`
creates a separate new spreadsheet.

## Python sign-in succeeds in the browser but migration fails

The Python tool needs the generated Desktop OAuth configuration in addition to
browser consent. From the project folder, prepare it using the existing downloaded
Desktop client JSON:

```sh
python3 tools/configure_google.py
python3 tools/migrate_to_sheets.py --upgrade-existing --spreadsheet SPREADSHEET_ID_OR_URL --sign-in
```

The first command writes ignored `linux/tick/google-client.json` without printing
credentials. Keep that generated file with the Python distribution. If the
Desktop client download is absent, the maintainer must provide the configured
distribution; signing in repeatedly cannot fix missing app configuration.

`invalid_client` means Google rejected the app credentials. Regenerate the
configuration and check any `TICK_GOOGLE_DESKTOP_CLIENT_SECRET` environment
override, which takes precedence over the file. `invalid_grant` means an
expired/revoked or mismatched authorization; retry with `--sign-in`. The tool
reports only recognized error codes and guidance, never raw token responses.

## Credentials and platform requirements

Google refresh tokens are stored in macOS/iOS Keychain, Windows Credential Manager,
or Linux Secret Service. They never enter `tick.json`, the spreadsheet, or app
location settings. Android delegates token management to Google Play services.
Python uses the same desktop OAuth client as the desktop apps.

On Linux, install `libsecret-tools` for secure sign-in storage (for example,
`sudo apt install libsecret-tools`). It is not needed for local JSON storage or
`--dry-run`. A locked or unavailable system keyring produces an explicit error;
tokens are not saved to an unencrypted fallback file.

Google-account consent can be removed from Google's account settings. This does
not delete your spreadsheet. Apple and Windows setup dialogs also provide a
local sign-out option. Reconnect from Settings if access expires or is revoked.

## Concurrent writes and recovery

Use one device at a time. Returning to Tick or pressing Start reloads shared
data. Each save checks the loaded journal version before writing and verifies
both the saved rows and journal afterward. A stale save fails before writing.

Google Sheets does not offer an atomic compare-and-swap or server lock. If two
devices save from the same parent simultaneously, their row updates and appended
journal entries are applied together in each batch. The journal retains both
sets of changed rows and Tick reports the branched history. Stop using that
spreadsheet and recover into a new file or spreadsheet; do not hide a conflict
by editing the live journal. Complete-row sorting is safe between saves, but
avoid editing/sorting the spreadsheet while a save is in flight.

The read-only [recovery tool](../tools/recover_sheets.py) lists and exports either
old full-dataset revisions or new row-based changes, including sibling branches:

```sh
python3 tools/recover_sheets.py SPREADSHEET_ID
python3 tools/recover_sheets.py SPREADSHEET_ID --revision REVISION_ID --output recovered-tick.json
```

Add `--legacy-backup` to list or export pre-migration `TickLogBackup` revisions.

The recovery tool refuses to overwrite an existing output file. Review the
recovered JSON locally before migrating it to a fresh spreadsheet. Journal
payloads grow with changed rows rather than a full dataset on every save; normal
reads fetch only their small version/chunk index. Google quota and sheet-size
limits still apply. There is no offline write queue or silent switch to a local
file. Failed saves preserve the last confirmed in-memory state and display an
error. A timed-out write may have reached Google; reload before retrying.

## Moving from the previous connection

The Apps Script connection and its URL/key form have been removed. Old connection
settings are not sufficient for Google sign-in: reconnect through Settings.
A spreadsheet containing the previous `TickData` format can be read directly once
Google grants Tick access. If it does not appear in Tick's authorized-file list,
use your original `tick.json` with the migration tool to create a new spreadsheet.
An arbitrary pasted URL does not grant Google permission. The old `TickData` contents are
retained as `TickDataBackup` when the first row-based save migrates them. Stop
older clients before switching; they do not understand row storage.

## Maintainer packaging

Public OAuth client IDs are recorded in [config/google-oauth.json](../config/google-oauth.json).
The downloaded Desktop installed-app JSON stays in ignored `tick-credentials/`.
Run this once when preparing the Python/Linux distribution:

```sh
python3 tools/configure_google.py
```

This generates ignored `linux/tick/google-client.json`, which must accompany a
packaged Python/Linux release. Apple and Windows builds generate equivalent
compiled configuration automatically. CI/release builds can instead set
`TICK_GOOGLE_DESKTOP_CLIENT_SECRET`. This is the installed-app credential from
Google's Desktop client download, not a confidential web-server secret. It is
never user-entered. Missing configuration still permits local-only builds;
Google sign-in needs a configured release. Keep an independent copy of the
original download outside the repository so a cleanup cannot remove it.
