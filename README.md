# Nonprofit Hours

Native time-tracking apps for Android, iPhone, macOS, and Windows with Google Sheets sync.

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
- Android: Kotlin + Jetpack Compose
- iPhone: Swift + SwiftUI
- macOS: Swift + SwiftUI
- Windows: C# + WinUI 3

## Backend
A small Google Apps Script endpoint will accept completed time sessions and upsert them into a Google Sheet using a globally unique session ID.

## Session model
See `docs/session-schema.md`.

## Repository layout
- `android/` Android native app
- `apple/` shared Swift model/sync code plus iOS and macOS targets
- `windows/` Windows native app
- `backend/` Google Apps Script backend
- `docs/` architecture and API contract
