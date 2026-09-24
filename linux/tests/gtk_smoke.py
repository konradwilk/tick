"""Run on Linux with a display (or xvfb-run); never touches real user data."""
from pathlib import Path
import tempfile
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio
from nonprofit_hours.app import HoursWindow

app = Gtk.Application(application_id="org.nonprofithours.Smoke", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "sessions.json"
    window = HoursWindow(app, path)
    window.present()
    assert window.error.get_text() == ""
    assert not window.toggle.get_sensitive()
    window.name.set_text("Community Kitchen")
    window.add_nonprofit()
    assert window.selected_id is not None
    window.notes.set_text("Dinner service")
    window.toggle_tracking()
    assert window.tracker.active is not None
    assert window.toggle.get_label() == "Stop"
    assert not window.nonprofits.get_sensitive()
    session_id = window.tracker.active["sessionId"]
    window.on_close()
    window.destroy()
    restored = HoursWindow(app, path)
    assert restored.tracker.active["sessionId"] == session_id
    assert restored.notes.get_text() == "Dinner service"
    restored.toggle_tracking()
    assert restored.tracker.active is None
    assert restored.toggle.get_label() == "Start"
    assert restored.export.get_sensitive()
    restored.on_close()
    restored.destroy()
print("GTK smoke test passed")
