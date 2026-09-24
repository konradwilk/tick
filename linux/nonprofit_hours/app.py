"""GTK 4 UI. Run with python3 -m nonprofit_hours from linux/."""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, GLib, Gdk
from datetime import datetime, timezone
from .core import FileStore, Tracker, data_path, elapsed, parse


class HoursWindow(Gtk.ApplicationWindow):
    def __init__(self, application, path=None):
        super().__init__(application=application, title="Nonprofit Hours", default_width=640, default_height=720)
        self.tracker = None
        self.timer = None
        self.chooser = None
        self.selected_id = None
        self.connect("close-request", self.on_close)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.set_child(scroll)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, "set_margin_" + side)(24)
        scroll.set_child(box)
        heading = Gtk.Label(label="Nonprofit Hours", xalign=0)
        heading.add_css_class("title-1")
        box.append(heading)
        self.error = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.error.add_css_class("error")
        box.append(self.error)
        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self.controls)
        add_row = Gtk.Box(spacing=8)
        self.name = Gtk.Entry(placeholder_text="New nonprofit", hexpand=True)
        self.name.connect("activate", lambda *_: self.add_nonprofit())
        self.add = Gtk.Button(label="Add nonprofit")
        self.add.connect("clicked", lambda *_: self.add_nonprofit())
        add_row.append(self.name)
        add_row.append(self.add)
        self.controls.append(add_row)
        self.controls.append(Gtk.Label(label="Nonprofit", xalign=0))
        self.nonprofits = Gtk.DropDown(model=Gtk.StringList.new([]))
        self.nonprofits.connect("notify::selected", self.on_select)
        self.controls.append(self.nonprofits)
        self.notes = Gtk.Entry(placeholder_text="Notes (optional)")
        self.controls.append(self.notes)
        self.clock = Gtk.Label(xalign=0, wrap=True)
        self.clock.add_css_class("title-2")
        self.controls.append(self.clock)
        self.toggle = Gtk.Button(label="Start")
        self.toggle.connect("clicked", lambda *_: self.toggle_tracking())
        self.controls.append(self.toggle)
        self.total = Gtk.Label(xalign=0)
        self.controls.append(self.total)
        self.export = Gtk.Button(label="Export CSV for Google Sheets")
        self.export.connect("clicked", self.export_csv)
        self.controls.append(self.export)
        self.controls.append(Gtk.Label(label="Timing continues when the app closes. Reopen and press Stop to finish.", wrap=True, xalign=0))
        box.append(Gtk.Label(label="History", xalign=0))
        self.history = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self.history)
        try:
            self.tracker = Tracker(FileStore(path or data_path()))
            active = self.tracker.active
            self.selected_id = active["nonprofitId"] if active else next((n["id"] for n in self.tracker.state["nonprofits"]), None)
            self.notes.set_text(active["notes"] if active else "")
            self.refresh()
            self.timer = GLib.timeout_add_seconds(1, self.update_clock)
        except Exception as error:
            self.controls.set_sensitive(False)
            self.error.set_text("Could not load saved hours. Your file was not changed. " + str(error))

    def perform(self, operation):
        try:
            operation()
            self.refresh()
            self.error.set_text("")
        except Exception as error:
            self.error.set_text(str(error))

    def add_nonprofit(self):
        def operation():
            self.selected_id = self.tracker.add_nonprofit(self.name.get_text())
            self.name.set_text("")
        self.perform(operation)

    def on_select(self, *_):
        if self.tracker:
            index = self.nonprofits.get_selected()
            nonprofits = self.tracker.state["nonprofits"]
            self.selected_id = nonprofits[index]["id"] if index < len(nonprofits) else None
            self.toggle.set_sensitive(self.tracker.active is not None or self.selected_id is not None)

    def toggle_tracking(self):
        def operation():
            if self.tracker.active:
                self.tracker.stop()
                self.notes.set_text("")
            else:
                self.tracker.start(self.selected_id, self.notes.get_text())
        self.perform(operation)

    def refresh(self):
        state = self.tracker.state
        selected = self.selected_id
        nonprofits = state["nonprofits"]
        self.nonprofits.set_model(Gtk.StringList.new([n["name"] for n in nonprofits]))
        index = next((i for i, n in enumerate(nonprofits) if n["id"] == selected), Gtk.INVALID_LIST_POSITION)
        self.nonprofits.set_selected(index)
        self.selected_id = selected
        active = self.tracker.active is not None
        for widget in (self.nonprofits, self.notes, self.name, self.add):
            widget.set_sensitive(not active)
        self.toggle.set_label("Stop" if active else "Start")
        self.toggle.remove_css_class("start" if active else "stop")
        self.toggle.add_css_class("stop" if active else "start")
        self.toggle.set_sensitive(active or selected is not None)
        seconds = sum(s.get("durationSeconds") or 0 for s in state["sessions"])
        self.total.set_text(f"Completed: {seconds / 3600:.2f} hours")
        self.export.set_sensitive(any(s.get("endTimeUtc") for s in state["sessions"]))
        while child := self.history.get_first_child():
            self.history.remove(child)
        for session in reversed(state["sessions"]):
            duration = elapsed(session["durationSeconds"]) if session.get("endTimeUtc") else "In progress"
            date = parse(session["startTimeUtc"]).astimezone().strftime("%Y-%m-%d %H:%M")
            label = Gtk.Label(label=f"{session['nonprofitName']} — {date}\n{duration}\n{session['notes']}", xalign=0, wrap=True, selectable=True)
            self.history.append(label)
        self.update_clock()

    def update_clock(self):
        active = self.tracker.active if self.tracker else None
        if active:
            seconds = (datetime.now(timezone.utc) - parse(active["startTimeUtc"])).total_seconds()
            self.clock.set_text(f"{active['nonprofitName']}: {elapsed(seconds)}")
        else:
            self.clock.set_text("Ready when you are")
        return GLib.SOURCE_CONTINUE

    def export_csv(self, *_):
        if self.chooser:
            self.chooser.show()
            return
        self.chooser = Gtk.FileChooserNative.new("Export completed hours", self, Gtk.FileChooserAction.SAVE, "Save", "Cancel")
        self.chooser.set_current_name("nonprofit-hours.csv")
        filter_ = Gtk.FileFilter()
        filter_.set_name("CSV files")
        filter_.add_pattern("*.csv")
        self.chooser.add_filter(filter_)
        self.chooser.connect("response", self.on_export_response, self.tracker.csv())
        self.chooser.show()

    def on_export_response(self, chooser, response, snapshot):
        try:
            if response == Gtk.ResponseType.ACCEPT:
                target = chooser.get_file()
                if target is None:
                    raise ValueError("Choose an export file.")
                target.replace_contents(snapshot.encode("utf-8"), None, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None)
                self.error.set_text("")
        except Exception as error:
            self.error.set_text("Export failed: " + str(error))
        finally:
            chooser.destroy()
            self.chooser = None

    def on_close(self, *_):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.chooser:
            self.chooser.destroy()
            self.chooser = None
        return False


class HoursApplication(Gtk.Application):
    def __init__(self):
        # GApplication forwards repeat launches to the existing process via D-Bus.
        super().__init__(application_id="org.nonprofithours.Linux", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            provider = Gtk.CssProvider()
            provider.load_from_data(b"button.start { background: #16733b; color: white; } button.stop { background: #b3261e; color: white; }")
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            window = HoursWindow(self)
        window.present()
