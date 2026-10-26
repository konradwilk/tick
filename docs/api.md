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
spreadsheet with the requested title and an empty staging tab; the first save
initializes row storage.

## Row storage v1

The first save creates `TickMeta` and `TickChanges`, and initializes `Sessions`
and `Projects`. Existing `TickLog`/`TickData` contents are preserved by renaming
those tabs to `TickLogBackup`/`TickDataBackup`; this also prevents old clients
from silently writing an obsolete dataset. Migration is one atomic
`spreadsheets.batchUpdate`, including initial rows and its recovery entry.

`TickMeta!A1:B1` contains `tick-rows-v1` and a JSON object with `schemaVersion` and
`deviceId`. `Sessions` starts with Project, Started (UTC), Ended (UTC), Duration,
Hours, Notes, Status, Platform. `Projects` starts with Project, Total hours,
Sessions. The first row contains headers. Each data row then contains:

| Relative column | Meaning |
|---|---|
| 0 | Permanent entity ID (sessionId or project id), lowercase |
| 1 | Last modifying operation UUID |
| 2 | Deleted: literal `0` or `1` |
| 3 | Number of JSON chunks, 1–1000 |
| 4 onward | Complete portable session/project JSON in chunks |

The offsets are zero-based 8 for Sessions (column I) and 3 for Projects (column
D). Technical columns are hidden. Chunks contain at most 20,000 Unicode scalars
(or 20,000 UTF-16 units on Windows/Android), below Google's cell size limit.
Every write uses literal `stringValue` or `numberValue`, never formulas.
Visible text previews are bounded, while hidden payloads preserve the full text.
JSON chunk count and IDs must agree; malformed or duplicate rows fail closed.

Normal saves use a `values.batchGet` for `TickMeta!A1:B1`, `Sessions`, `Projects`,
and `TickChanges!A:D`. Records are located by ID, never by a persisted row index.
The loaded journal revision is checked, then only changed entity rows are sent
as bounded `updateCells` ranges in one `spreadsheets.batchUpdate`. New records
use the next unused row. Deletions retain their ID and payload with Deleted=1
and blank visible fields. Updating shorter text clears obsolete chunk cells.
Project summary rows update only when their data/totals change. Formatting is
setup-only; grid dimensions grow only as needed. No-op saves perform no write.
A final batch read validates the journal chain and confirms the saved state.

## Changed-row journal

`TickChanges` has no header. Each operation occupies contiguous rows:

| Column | Meaning |
|---|---|
| A | New operation UUID |
| B | Parent operation UUID, or empty for initialization |
| C | Zero-based chunk index |
| D | Chunk count (1–1000) |
| E | JSON chunk |

The joined JSON is `{"changes":[{"table":"Sessions","id":"...","row":[...]}]}`.
Each changed row includes its visible values, ID, operation UUID, deletion
marker, chunk count and full payload. Project changes use table `Projects`.
Initialization includes every entity; subsequent operations include only changed
rows, including tombstones and affected project totals. Current state is read
from entity rows. Journal payloads are read only during recovery.

A normal reader checks all journal A:D metadata for complete chunks, unique
operations and a single parent chain. It rejects stale writes before mutation.
Two simultaneous batches can still share a parent: Sheets has no conditional
write transaction. Both sets of changed records remain in the journal even if
one overwrites current row cells. A post-write read detects the branch and
requires recovery. Use one device at a time. The recovery tool reconstructs each
operation by applying its changes to its own parent, so sibling branches can be
exported independently. Network failures require reload before retrying.

## Legacy input

Readers accept the old `TickLog` six-column snapshot format and `TickData` JSON
chunks until the first save migrates them. Legacy history is validated before
migration. `TickLog` columns are marker `tick-log-v1`, revision ID, parent ID,
chunk index, chunk count, JSON text. The backup remains available for manual
recovery. The new protocol is shared by all five platforms; update every client
before first migration. Cross-platform fixture: `fixtures/storage/sheets-rows-v1.json`.
