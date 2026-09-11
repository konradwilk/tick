# Sync API v1

## POST /session
Upserts one session.

Request body: session JSON from `session-schema.md`.

Response:
```json
{
  "ok": true,
  "sessionId": "uuid",
  "action": "inserted|updated"
}
```

## GET /health
Returns backend availability and schema version.

The first backend implementation will use Google Apps Script Web App + Google Sheets.
