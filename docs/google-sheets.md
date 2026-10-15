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

These are generated views. Make changes in Tick; editing these cells does not
update Tick, and the next save replaces the views. Tick updates both views and
its hidden recovery history in one Google API batch. `TickLog` contains the
complete portable dataset, IDs, and saved revisions for app compatibility and
recovery. Unusually long text is limited to 20,000 characters in the views;
the full text remains in the recovery history.

### Fix a spreadsheet migrated by an older version

There is no need to migrate again or create another spreadsheet. Close Tick on
other devices, then refresh the existing spreadsheet's layout:

```sh
python3 tools/migrate_to_sheets.py --upgrade-existing --spreadsheet SPREADSHEET_ID_OR_URL
```

This adds the Sessions and Projects views, hides the internal history, and
verifies the visible values. It preserves the spreadsheet's name, URL, IDs,
projects, sessions, and recovery history. `Sessions` and `Projects` are reserved
for Tick's generated views; put your own analysis in differently named tabs.
New migrations create the readable views automatically. Updated apps refresh
them on each save; install the updated app on every device.

## Connect in the app

1. Choose **Google Sheets** in Settings or on first launch.
2. Choose **Sign in with Google** and approve access to files you use with Tick.
3. Choose **Create a new spreadsheet**, or select an existing Tick spreadsheet
   that appears in the list.
4. For a new spreadsheet, keep **Time is Clearly Kept** or enter another name.
5. Choose **Connect**.

A new spreadsheet receives your current projects and sessions. An existing Tick
dataset opens without merging; its name and data are preserved. The choice is
remembered. To switch back, choose Local file and a new folder to copy your current
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
history. Each save first checks the loaded revision, then appends a complete new
revision to hidden `TickLog` together with refreshed readable views, and reads it
back to confirm the result. User text is sent
as literal `stringValue` cells, so it cannot become a formula.

This is not a server lock or atomic compare-and-swap. If two devices save from the
same parent at the same time, both revisions remain in `TickLog` and Tick reports
a conflict instead of silently choosing or overwriting a version. Stop using
that spreadsheet and keep it for recovery. Each revision's six-column rows store
`tick-log-v1`, its revision ID, parent ID, zero-based chunk index, chunk count, and
JSON text. Recover an individual revision by joining its chunks in index order;
validate the resulting portable JSON before opening it locally or migrating it
to a fresh spreadsheet. Do not manually edit the live history to hide conflicts. The separate read-only
[recovery tool](../tools/recover_sheets.py) can list and export retained revisions:

```sh
python3 tools/recover_sheets.py SPREADSHEET_ID
python3 tools/recover_sheets.py SPREADSHEET_ID --revision REVISION_ID --output recovered-tick.json
```

The recovery tool refuses to overwrite an existing output file. Open the recovered
JSON locally or migrate it to a new spreadsheet after reviewing it.

Every revision retains a full dataset. Long histories increase spreadsheet size
and read time; Google quota and sheet-size limits apply. There is no offline write
queue or silent switch to a local file. Failed saves preserve the last confirmed
in-memory state and display an error. CSV export still works.

## Moving from the previous connection

The Apps Script connection and its URL/key form have been removed. Old connection
settings are not sufficient for Google sign-in: reconnect through Settings.
A spreadsheet containing the previous `TickData` format can be read directly once
Google grants Tick access. If it does not appear in Tick's authorized-file list,
use your original `tick.json` with the migration tool to create a new spreadsheet.
An arbitrary pasted URL does not grant Google permission. The old `TickData` is
left intact when the first direct-API save creates `TickLog`. Stop older clients
before switching; they do not understand the new log format.

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
