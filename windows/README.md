# Windows

Native C# / WinUI 3 application with nonprofit creation/selection, green Start/red
Stop, notes, restart-safe sessions, history, total hours, and CSV export using the
Windows save picker. Import CSV into Google Sheets with File → Import. Automatic
sync is not implemented.

In **History**, choose **Edit notes** on a completed session to update what you
worked on. **Save** persists the notes and updates CSV exports; **Cancel** discards
the edit. Session times and recorded hours stay unchanged.

## Build on Windows

Install Visual Studio 2022 with Windows application development tools, .NET 8 SDK,
and Windows SDK 10.0.26100. Open `tick/tick.csproj` in Visual
Studio and select x64, or run from the repository root:

```powershell
dotnet test windows/HoursCore.Tests/HoursCore.Tests.csproj -c Release
dotnet publish windows/tick/tick.csproj -c Release -p:Platform=x64 -r win-x64 --self-contained true -o windows/publish
```

Run `windows/publish/tick.exe`. Keep the entire published directory together;
the app is unpackaged and includes its runtime dependencies. For ARM64 use
`-p:Platform=ARM64 -r win-arm64`. Native UI compilation requires Windows; the core
library and tests are independent of WinUI. The repository's Native clients workflow
builds the x64 app and uploads the published directory. No installer or signing yet.

The green clock icon in the Windows system tray stays available when you close the
window. Click it to reopen, or right-click for **Open Time is Clearly Kept** and **Quit**.
Launching the app again also reopens the existing window. Windows may initially
place the icon in the hidden-icons menu near the clock; drag it onto the tray to
keep it visible. Quitting preserves any active session; press Stop to finish tracking.

Data lives in `%LOCALAPPDATA%\NonprofitHours\sessions.json`. Back up this file or export
CSV to preserve hours. Saves replace the file only after writing the new state. An
unreadable file disables tracking rather than overwriting saved data. One application
instance writes to the store at a time. Closing the app keeps the active session's
start time; reopen and press Stop to finish. System clock changes affect elapsed time.
Dates use UTC ISO-8601 and exports contain completed sessions only. Export does not
mark sessions synced.

Dependency reference: [Windows App SDK 1.8 release notes](https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/release-notes/windows-app-sdk-1-8).

## Configure the data folder

Use **Data location** to choose where the app stores its working data. The selected
folder is remembered across restarts; every subsequent read/save uses
`tick.json` there. Existing data in that folder is loaded without being
overwritten. Otherwise the current data is copied there and the old file is retained.
The previously documented private/default path applies only until you choose a folder.

The file can be used by macOS, iOS, Android, Windows, and Linux. See
[shared data storage](../docs/data-storage.md) for compatibility and access details.
Use one device at a time and wait for any cloud synchronization before switching.
