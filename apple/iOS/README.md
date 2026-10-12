# iPhone and iPad

Open `tick.xcodeproj` in Xcode 16 or later on a Mac. Select the
tick target, choose your development team under Signing & Capabilities,
and run on an iOS 17+ device or simulator. No third-party packages are required.

The project compiles the same files in `../Sources/HoursCore` as the macOS app.
It includes Start/Stop tracking, nonprofit creation, persistent data-folder
selection, direct JSON-file selection for providers such as OneDrive, history with Edit notes and Save/Cancel, and daily/weekly/monthly CSV
exports using the system save sheet. Copy durations and notes uses the selected
period and the same grouped format, No notes placeholder, and comma-space
separator as the other clients. CSV omits sessionId, projectId, and updatedAtUtc.

From the repository root on macOS:

```sh
swift test --package-path apple
xcodebuild -project apple/iOS/tick.xcodeproj -target tick -configuration Debug -sdk iphonesimulator CODE_SIGNING_ALLOWED=NO build
```

The source was generated on Windows; an Xcode build and simulator/device check
are still required. Check folder selection and reopening, Start/Stop across app
restarts, note editing and cancellation, all three export periods, and clipboard
output including empty and multiline notes before distributing a build.

## OneDrive

Use **Open tick.json…** on the setup screen or in Settings, then select the
existing Tick data file in OneDrive. The folder picker may disable providers
that cannot grant persistent folder access. Direct file selection retains a
bookmark to the chosen file, and reads and writes use file coordination.
If starting fresh, first create tick.json with Tick on another device or in an
iCloud folder, then copy it to OneDrive using Files and open that copy in Tick.
Test opening an online-only file, saving a change, restarting Tick, and checking
that the change reaches another device before relying on OneDrive storage.
