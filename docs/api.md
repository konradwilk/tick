# Direct Google Sheets storage

Native clients and the Python migration tool use Google OAuth and call the Sheets
and Drive REST APIs directly. The Apps Script POST endpoint and shared access-key
protocol have been removed. See [user setup and migration](google-sheets.md) and
[maintainer OAuth registration](google-cloud-setup.md).

Authorization uses only `https://www.googleapis.com/auth/drive.file`.
Desktop clients use system-browser OAuth with PKCE, a random loopback port, and
state validation. iOS uses ASWebAuthenticationSession and its registered reverse
client-ID callback scheme. Android uses Google Play services AuthorizationClient,
including consent resolution and token renewal.

`GET https://www.googleapis.com/drive/v3/files` lists authorized spreadsheet files,
with pagination. `POST https://sheets.googleapis.com/v4/spreadsheets` creates a
spreadsheet with the requested title and a six-column `TickLog` tab.

## TickLog v1

Each saved snapshot occupies one or more adjacent rows. A single
`spreadsheets.batchUpdate` appends these rows using `appendCells`, refreshes the
reserved Sessions and Projects views using `updateCells`, and hides TickLog
(and legacy TickData). The batch is atomic; history and views cannot partially
commit. Text uses explicit `userEnteredValue.stringValue` to prevent formulas.
Each history row contains:

| Column | Value |
| --- | --- |
| A | `tick-log-v1` |
| B | New revision UUID |
| C | Parent revision ID, or empty string for a new dataset |
| D | Zero-based chunk index |
| E | Number of chunks in this revision |
| F | Portable schema-v1 JSON text chunk |

Chunks respect Google's cell size limit and never split a Unicode surrogate pair.
Readers reconstruct and validate all revisions in order. Each complete revision
must refer to the previously read revision; duplicate revisions, missing chunks,
malformed data, and sibling branches reject the read without changing app state.
The root parent may identify a previous `TickData` revision when upgrading an old
spreadsheet. The old tab retains its values and is hidden.

Before appending, a client checks that the current revision matches its loaded
revision. After appending, it verifies the returned history and saved snapshot.
These checks do not provide atomic compare-and-swap. Concurrent sibling commits
remain available for recovery and produce an explicit conflict. Writes are never
automatically retried after an ambiguous timeout. No external server or server
lock is used. Only portable data enters the sheet; tokens remain on the device.

## Readable views

Sessions is first, Projects second. Both have frozen headers, filters, wrapped
text, and numeric hours formatted to two decimals. Sessions columns are Project,
Started (UTC), Ended (UTC), Duration, Hours, Notes, Status, Platform. Projects
columns are Project, Total hours, Sessions. Totals group by project ID, use current
project names, and exclude unfinished durations; counts include running sessions.
Durations display whole seconds; numeric hours retain fractional precision.

Views are generated from the validated portable dataset and are not read back as
user edits. Refreshes clear stale generated values, so deleted sessions disappear.
Only these reserved tabs are rewritten. View text is capped at 20,000 Unicode
scalars (or fewer UTF-16 units); full values remain in TickLog. Schema, OAuth,
revision ancestry, and recovery remain compatible with previous direct-API data.
The migration CLI verifies visible values in addition to the history. Its
`--upgrade-existing --spreadsheet ID_OR_URL` mode rebuilds views without adding a
history revision or uploading a source file.
