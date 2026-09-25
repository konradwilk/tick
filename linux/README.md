# Linux GTK

Native GTK 4 application written in Python with PyGObject. Includes nonprofit
creation/selection, green Start/red Stop, notes, persisted sessions, elapsed time,
history, total completed hours, and CSV export through a native save dialog.

## Install dependencies and run

Requires Python 3.10 or newer, GTK 4, and PyGObject. No pip dependencies or
compilation are needed. Use the system Python that provides the GTK bindings.

Ubuntu 22.04+ / Debian 12+:

```sh
sudo apt install python3 python3-gi gir1.2-gtk-4.0
```

Fedora:

```sh
sudo dnf install python3 python3-gobject gtk4
```

From the repository root:

```sh
cd linux
/usr/bin/python3 -m nonprofit_hours
```

Run this in a normal graphical desktop session. Repeated launches activate the
existing window through GTK's application registration on the session D-Bus.
The app closes when its window closes; an active session remains saved. Reopen
and press Stop to finish. No background process is needed to measure elapsed time.
Nonprofit selection and notes are locked during an active session.

## Data and export

Sessions live at `$XDG_DATA_HOME/nonprofit-hours/sessions.json`, defaulting to
`~/.local/share/nonprofit-hours/sessions.json`. Saves use a temporary file and atomic
replacement before publishing the change in memory. Unreadable or malformed data
disables tracking instead of overwriting saved history. Back up this file to retain
local data. Dates are UTC ISO-8601 and sessions use `platform: linux`.

Export includes completed sessions only, handles quotes/newlines, and neutralizes
spreadsheet formulas in text fields. In Google Sheets use File → Import to load
the CSV. Automatic sync, tray integration, an installer, and signing are not included.
Changing the system clock affects elapsed time; stopping before the start is rejected.

## Tests

Core tests run without GTK, including on macOS:

```sh
cd linux
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

GTK smoke test on Linux (install `xvfb` and `dbus-x11` for headless execution):

```sh
cd linux
PYTHONPATH=. xvfb-run -a dbus-run-session -- /usr/bin/python3 tests/gtk_smoke.py
```

The Native clients workflow runs both and uploads the Linux source package.
The smoke test covers window creation, Start/Stop, selection locking, and restart
recovery. The interactive export dialog still needs a manual desktop check.

References: [GTK Python bindings](https://www.gtk.org/docs/language-bindings/python),
[PyGObject GTK application guide](https://pygobject.gnome.org/tutorials/gtk4/application.html).

## Configure the data folder

Use **Data location** to choose where the app stores its working data. The selected
folder is remembered across restarts; every subsequent read/save uses
`nonprofit-hours.json` there. Existing data in that folder is loaded without being
overwritten. Otherwise the current data is copied there and the old file is retained.
The previously documented private/default path applies only until you choose a folder.

The file can be used by macOS, iOS, Android, Windows, and Linux. See
[shared data storage](../docs/data-storage.md) for compatibility and access details.
Use one device at a time and wait for any cloud synchronization before switching.
