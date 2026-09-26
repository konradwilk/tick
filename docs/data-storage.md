# Shared data storage

Each client stores UTF-8 JSON with `schemaVersion: 1`, a device UUID, a
`nonprofits` array (`id`, `name`), and a `sessions` array following
[the session schema](session-schema.md). Timestamps include a timezone; writers
use UTC. Active sessions have no end time or duration. UUIDs and session times
remain in storage even though the CSV report omits sessionId, nonprofitId, and
updatedAtUtc.

Choose Data location to use `nonprofit-hours.json` in a selected folder. An
existing file is read before adopting it. A new folder receives a copy of the
current state. Folder selection is remembered using platform settings (Apple
security-scoped bookmarks and Android persistable document-tree permissions).
Use one device at a time and let cloud synchronization finish before switching.
The apps reject writes when the file differs from the snapshot they loaded.

Windows, Linux, and Apple use atomic local file replacement; Android uses
AtomicFile for private storage. Android document-provider writes depend on the
provider and cannot guarantee atomic replacement; a failed write attempts to
restore the original bytes. Back up the shared file before using a new provider.

Earlier unversioned files are accepted, including Apple timestamps represented
as seconds since 2001-01-01. Invalid identities, duplicate sessions, multiple
active sessions, unsupported versions, and inconsistent durations are rejected.
