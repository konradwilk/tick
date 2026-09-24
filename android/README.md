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
