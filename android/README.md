# Android

Native Kotlin / Jetpack Compose application for Android 8.0 (API 26) or later.
Includes nonprofit creation/selection, green Start/red Stop, optional notes,
restart-safe timing, history, total hours, and CSV export through the system file picker.
Import exported CSV in Google Sheets using File → Import. Automatic sync is not implemented.

## Build

Install JDK 17, Android SDK platform 35, and Gradle 8.11.1. Open this directory
in Android Studio, set the Gradle JDK to 17, and use the installed Gradle distribution.
A Gradle wrapper binary is not bundled. To generate the standard wrapper with your
installed Gradle, run `gradle wrapper --gradle-version 8.11.1` here.

```sh
gradle :app:testDebugUnitTest :app:assembleDebug :app:lintDebug
```

The debug APK is `app/build/outputs/apk/debug/app-debug.apk`. Install it on a
connected device with `adb install -r app/build/outputs/apk/debug/app-debug.apk`.
The repository's Native clients workflow performs the same build and uploads the APK.

Sessions are JSON in app-private storage, saved via Android AtomicFile before the
screen changes. An active session survives app closure; no background service is
needed. Reopen and press Stop to finish. Nonprofit and notes are locked while tracking.
Uninstalling or clearing app data removes local hours; export to keep a copy.
Dates use UTC ISO-8601. Export includes only completed sessions and does not mark
anything synced. System clock changes affect elapsed time; negative duration is rejected.

Toolchain reference: [Android Gradle plugin 8.9 compatibility](https://developer.android.com/build/releases/agp-8-9-0-release-notes).

## Configure the data folder

Use **Data location** to choose where the app stores its working data. The selected
folder is remembered across restarts; every subsequent read/save uses
`tick.json` there. Existing data in that folder is loaded without being
overwritten. Otherwise the current data is copied there and the old file is retained.
The previously documented private/default path applies only until you choose a folder.

The file can be used by macOS, iOS, Android, Windows, and Linux. See
[shared data storage](../docs/data-storage.md) for compatibility and access details.
Use one device at a time and wait for any cloud synchronization before switching.
