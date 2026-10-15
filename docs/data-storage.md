# Shared data storage

All clients offer Local file and Google Sheets in Settings and on first launch.
See [Google Sheets setup and migration](google-sheets.md) for the API backend,
network requirements, conflict handling, and the separate Python migration tool.
The file-specific behavior below applies to Local file mode.

Each client stores UTF-8 JSON with `schemaVersion: 1`, a device UUID, a
`nonprofits` array (`id`, `name`), and a `sessions` array following
[the session schema](session-schema.md). Timestamps include a timezone; writers
use UTC. Active sessions have no end time or duration. UUIDs and session times
remain in storage even though the CSV report omits sessionId, projectId, and
updatedAtUtc.

Sessions are sorted chronologically by start time (oldest first) on every write,
including backdated additions and note edits. Equal start times retain their order.

Choose Data location to use `tick.json` in a selected folder. An
existing file is read before adopting it. A new folder receives a copy of the
current state. Folder selection is remembered using platform settings (Apple
security-scoped bookmarks and Android persistable document-tree permissions).
Use one device at a time and let cloud synchronization finish before switching.
Opening or returning to the app rereads `tick.json` on macOS, iOS, Windows,
Android, and Linux. The displayed projects, history, reports, and running session
update from the file. Draft notes are preserved unless the running session changes;
a removed selected project falls back to an available project. If reloading fails,
the app shows an error and keeps its last successfully loaded state without writing
to the file.

Saving a session entered by hand also rereads the file before checking for time
overlaps, so newly shared history is included in the confirmation. Manual draft
fields are preserved when returning to the app.

Pressing Start rereads the file before checking the selected project and active
session, preserving updates saved by another instance. If another session is
already running, it is shown instead of creating a second session. Missing or
unreadable files block Start. The apps still reject writes when the file differs
from the snapshot they loaded, including changes made after this refresh.

Windows, Linux, and Apple use atomic local file replacement; Android uses
AtomicFile for private storage. Android document-provider writes depend on the
provider and cannot guarantee atomic replacement; a failed write attempts to
restore the original bytes. Back up the shared file before using a new provider.

Every committed change (projects, Start/Stop, manual sessions, edits, and deletions)
writes `tick.json` synchronously before reporting success. Apple explicitly flushes
and closes the replaced file within coordinated access; Windows uses
`FileStream.Flush(true)` before replacement; Linux flushes and calls `fsync` before
replacement. Android flushes and synchronizes private files and regular files
returned by document providers, and closes provider streams before returning.
Providers that return pipes receive the bytes and stream closure; they control
when those bytes reach their storage. These guarantees also apply when creating
or copying the data file to a newly selected location. Unsaved form drafts are
not written. Cloud upload and availability on another device remain controlled
by iCloud Drive, OneDrive, or the selected provider and network connection.

Earlier unversioned files are accepted, including Apple timestamps represented
as seconds since 2001-01-01. Invalid identities, duplicate sessions, multiple
active sessions, unsupported versions, and inconsistent durations are rejected.

If `tick.json` is missing at startup, all five apps first explain that the file
stores projects and tracked hours, how to create or reuse it, and that its location
can be changed later in Settings. Choose data folder opens the folder picker;
iOS also offers Open tick.json for providers such as OneDrive. Later dismisses
the explanation and leaves the data-location controls available. Choosing a
folder creates and saves an empty `tick.json` immediately, or loads the existing
file there. Canceling leaves tracking disabled until a folder is chosen through
Data location. The chosen location is remembered for subsequent launches.

After a manual session is saved successfully, all apps keep manual entry open
and prepare the next entry: start one minute after the saved end, end fifteen
minutes after the saved end (for example, 18:00–19:00 becomes 19:01–19:15).
The project stays selected and activity notes are cleared. Validation errors or
unconfirmed overlap warnings leave the entered times unchanged.
