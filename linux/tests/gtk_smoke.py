"""Run on Linux with a display (or xvfb-run); never touches real user data."""
from pathlib import Path
import tempfile
import os
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio
from tick.app import HoursWindow
from tick.core import FileStore, Tracker, StorageLocation

app = Gtk.Application(application_id="org.timeisclearlykept.Smoke", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
with tempfile.TemporaryDirectory() as directory:
    os.environ["XDG_CONFIG_HOME"] = directory
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
    # A selection without starting a session survives reopening.
    restored.name.set_text("Second project")
    restored.add_nonprofit()
    second_id = restored.selected_id
    reopened = HoursWindow(app, path)
    assert reopened.selected_id == second_id
    reopened.nonprofits.set_selected(0)
    first_id = reopened.selected_id
    reopened.destroy()
    reopened = HoursWindow(app, path)
    assert reopened.selected_id == first_id
    reopened.destroy()
    # An unavailable saved project falls back to the first project.
    restored.location.settings.with_name("last-project").write_text("missing", encoding="utf-8")
    reopened = HoursWindow(app, path)
    assert reopened.selected_id == first_id
    reopened.destroy()
    # Remember manual selections even when canceled; leave tracking unchanged.
    dialog = restored.add_manual_session()
    selector = dialog.get_content_area().get_first_child().get_next_sibling()
    selector.set_selected(1)
    dialog.response(Gtk.ResponseType.CANCEL)
    reopened = HoursWindow(app, path)
    assert reopened.selected_id == first_id
    dialog = reopened.add_manual_session()
    selector = dialog.get_content_area().get_first_child().get_next_sibling()
    assert selector.get_selected() == 1
    selector.set_selected(0)
    dialog.response(Gtk.ResponseType.CANCEL)
    dialog = reopened.add_manual_session()
    assert dialog.get_content_area().get_first_child().get_next_sibling().get_selected() == 0
    dialog.response(Gtk.ResponseType.CANCEL)
    reopened.location.settings.with_name("last-manual-project").write_text("missing", encoding="utf-8")
    dialog = reopened.add_manual_session()
    assert dialog.get_content_area().get_first_child().get_next_sibling().get_selected() == 0
    dialog.response(Gtk.ResponseType.CANCEL)
    # Live conflicts require a second explicit action; editing revokes confirmation.
    from datetime import datetime, timedelta, timezone
    start = datetime(2020, 1, 1, 12, tzinfo=timezone.utc)
    reopened.tracker.add_session(first_id, "Existing activity", start, start + timedelta(hours=1))
    dialog = reopened.add_manual_session()
    widgets = []
    child = dialog.get_content_area().get_first_child()
    while child is not None:
        widgets.append(child)
        child = child.get_next_sibling()
    entries = [widget for widget in widgets if isinstance(widget, Gtk.Entry)]
    warning = next(widget for widget in widgets if isinstance(widget, Gtk.ScrolledWindow)).get_child()
    if isinstance(warning, Gtk.Viewport):
        warning = warning.get_child()
    entries[0].set_text("Intentional overlap")
    entries[1].set_text((start + timedelta(minutes=15)).astimezone().strftime("%Y-%m-%d %H:%M"))
    entries[2].set_text((start + timedelta(minutes=45)).astimezone().strftime("%Y-%m-%d %H:%M"))
    assert "Existing activity" in warning.get_text()
    assert "Overlap: 00:30:00" in warning.get_text()
    count = len(reopened.tracker.state["sessions"])
    dialog.response(Gtk.ResponseType.ACCEPT)
    assert len(reopened.tracker.state["sessions"]) == count
    assert dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).get_label() == "Save anyway"
    entries[2].set_text((start + timedelta(minutes=50)).astimezone().strftime("%Y-%m-%d %H:%M"))
    assert dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).get_label() == "Save"
    dialog.response(Gtk.ResponseType.ACCEPT)
    assert len(reopened.tracker.state["sessions"]) == count
    dialog.response(Gtk.ResponseType.ACCEPT)
    assert len(reopened.tracker.state["sessions"]) == count + 1
    assert entries[0].get_text() == ""
    # Successful saves advance the open form, including across midnight.
    entries[0].set_text("Late activity")
    entries[1].set_text("2020-01-02 23:00")
    entries[2].set_text("2020-01-02 23:59")
    dialog.response(Gtk.ResponseType.ACCEPT)
    assert len(reopened.tracker.state["sessions"]) == count + 2
    assert entries[1].get_text() == "2020-01-03 00:00"
    assert entries[2].get_text() == "2020-01-03 00:14"
    assert entries[0].get_text() == ""
    entries[0].set_text("Next activity")
    dialog.response(Gtk.ResponseType.ACCEPT)
    assert len(reopened.tracker.state["sessions"]) == count + 3
    assert entries[1].get_text() == "2020-01-03 00:15"
    assert entries[2].get_text() == "2020-01-03 00:29"
    # Invalid entries do not advance the form.
    dialog.response(Gtk.ResponseType.ACCEPT)
    assert len(reopened.tracker.state["sessions"]) == count + 3
    assert entries[1].get_text() == "2020-01-03 00:15"
    assert entries[2].get_text() == "2020-01-03 00:29"
    dialog.response(Gtk.ResponseType.CANCEL)
    reopened.on_close()
    reopened.destroy()
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
# Exercise the location-picker callback with isolated first-run data.
class FolderChooser:
    def __init__(self, folder):
        self.folder = folder
        self.destroyed = False

    def get_file(self):
        return Gio.File.new_for_path(str(self.folder))

    def destroy(self):
        self.destroyed = True


for scenario in ("empty", "populated", "cancel", "invalid", "later"):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        folder = root / "selected"
        folder.mkdir()
        if scenario == "populated":
            saved = Tracker(FileStore(folder / "tick.json"))
            saved.add_nonprofit("Existing project")
        elif scenario == "invalid":
            (folder / "tick.json").write_text("invalid JSON")
        elif scenario == "empty":
            FileStore(folder / "tick.json").save(Tracker(FileStore(root / "empty.json")).state)
        window = HoursWindow(app, root / "seed.json")
        window.location = StorageLocation(root / "location.json")
        if scenario != "later":
            window.tracker = None
        chooser = FolderChooser(folder)
        window.chooser = chooser
        response = Gtk.ResponseType.CANCEL if scenario == "cancel" else Gtk.ResponseType.ACCEPT
        window.on_data_response(chooser, response)
        assert window.settings_panel.get_reveal_child() == (scenario == "empty"), scenario
        assert chooser.destroyed and window.chooser is None
        if scenario == "empty":
            assert window.name.get_sensitive() and window.add.get_sensitive()
            window.name.set_text("First project")
            window.add_nonprofit()
            assert window.tracker.state["nonprofits"][0]["name"] == "First project"
        elif scenario in ("cancel", "invalid"):
            assert window.tracker is None
        window.on_close()
        window.destroy()
print("GTK smoke test passed")
