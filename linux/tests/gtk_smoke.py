"""Run on Linux with a display (or xvfb-run); never touches real user data."""
from pathlib import Path
import tempfile
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio
from tick.app import HoursWindow

app = Gtk.Application(application_id="org.nonprofithours.Smoke", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "sessions.json"
    window = HoursWindow(app, path)
    window.present()
    assert window.error.get_text() == ""
    assert not window.toggle.get_sensitive()
    assert not window.settings_panel.get_reveal_child()
    assert window.first_run.get_visible()
    window.name.set_text("Community Kitchen")
    window.add_nonprofit()
    assert window.selected_id is not None
    assert not window.first_run.get_visible()
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
    assert restored.copy.get_sensitive()
    assert restored.report_preview.get_text() == restored.tracker.clipboard_text(*restored.report_selection())
    selected_date = restored.report_date.get_text()
    restored.report_date.set_text("invalid")
    assert not restored.export.get_sensitive()
    assert not restored.copy.get_sensitive()
    restored.report_date.set_text("1900-01-01")
    assert not restored.export.get_sensitive()
    restored.report_date.set_text(selected_date)
    for index in range(3):
        restored.report_period.set_selected(index)
        assert restored.export.get_sensitive()
        assert restored.copy.get_sensitive()
    restored.copy_report()
    assert restored.copy_status.get_text() == "Copied durations and notes."
    session = restored.tracker.state["sessions"][0]
    dialog = restored.edit_notes(session)
    content = dialog.get_content_area()
    scroll = content.get_first_child().get_next_sibling().get_next_sibling()
    buffer = scroll.get_child().get_buffer()
    buffer.set_text("Updated dinner service\nCleanup")
    dialog.response(Gtk.ResponseType.ACCEPT)
    assert restored.tracker.state["sessions"][0]["notes"] == "Updated dinner service\nCleanup"
    assert "Updated dinner service, Cleanup" in restored.report_preview.get_text()
    assert restored.tracker.state["sessions"][0]["durationSeconds"] == session["durationSeconds"]
    dialog = restored.edit_notes(restored.tracker.state["sessions"][0])
    scroll = dialog.get_content_area().get_first_child().get_next_sibling().get_next_sibling()
    scroll.get_child().get_buffer().set_text("Discard this")
    dialog.response(Gtk.ResponseType.CANCEL)
    assert restored.tracker.state["sessions"][0]["notes"] == "Updated dinner service\nCleanup"
    restored.on_close()
    restored.destroy()
print("GTK smoke test passed")
