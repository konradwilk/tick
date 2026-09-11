# Session schema

Each completed or in-progress work session uses this logical model:

```json
{
  "sessionId": "uuid",
  "nonprofitId": "uuid",
  "nonprofitName": "Somerville Pop Cheer",
  "startTimeUtc": "2026-09-11T00:32:00Z",
  "endTimeUtc": "2026-09-11T02:14:00Z",
  "durationSeconds": 6120,
  "notes": "Board work",
  "deviceId": "uuid",
  "platform": "android|ios|macos|windows",
  "updatedAtUtc": "2026-09-11T02:14:03Z",
  "syncState": "pending|synced|failed"
}
```

## Rules
- `sessionId` is generated on the device when START is pressed.
- The selected nonprofit is locked for the active session.
- Timing is based on persisted timestamps, not a continuously running background timer.
- `durationSeconds = endTimeUtc - startTimeUtc` for completed sessions.
- Backend writes are idempotent by `sessionId`.
- Edits reuse the same `sessionId` and update the existing row.
