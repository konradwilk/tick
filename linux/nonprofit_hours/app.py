"""GTK 4 UI. Run with python3 -m nonprofit_hours from linux/."""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, GLib, Gdk
from datetime import datetime, timezone, date, timedelta
from .core import FileStore, Tracker, data_path, elapsed, parse, StorageLocation, period_bounds


class HoursWindow(Gtk.ApplicationWindow):
    def __init__(self, application, path=None):
        super().__init__(application=application, title="Nonprofit Hours", default_width=640, default_height=720)
        self.tracker = None
        self.timer = None
        self.chooser = None
        self.selected_id = None
        self.location = StorageLocation()
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
        location_button = Gtk.Button(label="Data location…")
        location_button.connect("clicked", lambda *_: self.choose_data_location())
        box.append(location_button)
        self.location_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        box.append(self.location_label)
        box.append(Gtk.Label(label="All changes are saved in this folder. Use one device at a time.", xalign=0, wrap=True))
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
        self.controls.append(Gtk.Label(label="Export period", xalign=0))
        self.report_period = Gtk.DropDown(model=Gtk.StringList.new(["Daily", "Weekly", "Monthly"]))
        self.report_period.set_selected(2)
        self.report_period.connect("notify::selected", self.update_report)
        self.controls.append(self.report_period)
        self.controls.append(Gtk.Label(label="Date in period (YYYY-MM-DD)", xalign=0))
        self.report_date = Gtk.Entry(text=date.today().isoformat())
        self.report_date.connect("changed", self.update_report)
        self.controls.append(self.report_date)
        self.controls.append(Gtk.Label(label="Completed sessions by local start date. Weeks run Monday–Sunday.", xalign=0, wrap=True))
        self.report_summary = Gtk.Label(xalign=0, wrap=True)
        self.controls.append(self.report_summary)
        self.export = Gtk.Button(label="Export CSV for Google Sheets")
        self.export.connect("clicked", self.export_csv)
        self.controls.append(self.export)
        self.copy = Gtk.Button(label="Copy durations and notes")
        self.copy.connect("clicked", self.copy_report)
        self.controls.append(self.copy)
        self.copy_status = Gtk.Label(xalign=0)
        self.controls.append(self.copy_status)
        self.controls.append(Gtk.Label(label="Timing continues when the app closes. Reopen and press Stop to finish.", wrap=True, xalign=0))
        box.append(Gtk.Label(label="History", xalign=0))
        self.history = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(self.history)
        try:
            self.tracker = Tracker(FileStore(path)) if path else self.location.open()
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
        self.controls.set_sensitive(True)
        self.location_label.set_text(str(self.tracker.store.path.parent))
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
        self.update_report()
        while child := self.history.get_first_child():
            self.history.remove(child)
        for session in reversed(state["sessions"]):
            duration = elapsed(session["durationSeconds"]) if session.get("endTimeUtc") else "In progress"
            date = parse(session["startTimeUtc"]).astimezone().strftime("%Y-%m-%d %H:%M")
            label = Gtk.Label(label=f"{session['nonprofitName']} — {date}\n{duration}\n{session['notes']}", xalign=0, wrap=True, selectable=True)
            self.history.append(label)
            if session.get("endTimeUtc"):
                edit = Gtk.Button(label="Edit notes", halign=Gtk.Align.START)
                edit.connect("clicked", lambda _, selected=session: self.edit_notes(selected))
                self.history.append(edit)
        self.update_clock()

    def edit_notes(self, session):
        dialog = Gtk.Dialog(title="Edit session notes", transient_for=self, modal=True)
        dialog.set_default_size(440, 300)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.ACCEPT)
        content = dialog.get_content_area()
        content.set_spacing(12)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, "set_margin_" + side)(16)
        date = parse(session["startTimeUtc"]).astimezone().strftime("%Y-%m-%d %H:%M")
        content.append(Gtk.Label(label=f"{session['nonprofitName']} — {date}", xalign=0, wrap=True))
        content.append(Gtk.Label(label="What did you work on?", xalign=0))
        editor = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        buffer = editor.get_buffer()
        buffer.set_text(session["notes"])
        scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=120)
        scroll.set_child(editor)
        content.append(scroll)
        error = Gtk.Label(xalign=0, wrap=True)
        error.add_css_class("error")
        content.append(error)

        def respond(_, response):
            if response == Gtk.ResponseType.ACCEPT:
                try:
                    self.tracker.update_notes(session["sessionId"], buffer.get_text(*buffer.get_bounds(), True))
                    self.refresh()
                    self.error.set_text("")
                except Exception as problem:
                    error.set_text("Could not save notes. " + str(problem))
                    return
            dialog.destroy()

        dialog.connect("response", respond)
        dialog.present()
        return dialog

    def update_clock(self):
        active = self.tracker.active if self.tracker else None
        if active:
            seconds = (datetime.now(timezone.utc) - parse(active["startTimeUtc"])).total_seconds()
            self.clock.set_text(f"{active['nonprofitName']}: {elapsed(seconds)}")
        else:
            self.clock.set_text("Ready when you are")
        return GLib.SOURCE_CONTINUE

    def choose_data_location(self):
        if self.chooser:
            self.chooser.show()
            return
        self.chooser = Gtk.FileChooserNative.new("Choose data folder", self,
            Gtk.FileChooserAction.SELECT_FOLDER, "Use this folder", "Cancel")
        self.chooser.connect("response", self.on_data_response)
        self.chooser.show()

    def on_data_response(self, chooser, response):
        try:
            if response == Gtk.ResponseType.ACCEPT:
                target = chooser.get_file()
                path = target.get_path() if target else None
                if not path:
                    raise ValueError("Choose a local file or a mounted cloud/network folder.")
                next_tracker = self.location.select(path, self.tracker)
                self.tracker = next_tracker
                active = self.tracker.active
                self.selected_id = active["nonprofitId"] if active else next((n["id"] for n in self.tracker.state["nonprofits"]), None)
                self.notes.set_text(active["notes"] if active else "")
                self.refresh()
                if self.timer is None:
                    self.timer = GLib.timeout_add_seconds(1, self.update_clock)
                self.error.set_text("")
        except Exception as error:
            self.error.set_text(str(error))
        finally:
            chooser.destroy()
            self.chooser = None

    def export_csv(self, *_):
        if self.chooser:
            self.chooser.show()
            return
        try:
            period, day = self.report_selection()
            snapshot = self.tracker.csv(period, day)
            start, _ = period_bounds(period, day)
        except Exception as error:
            self.error.set_text(str(error))
            return
        self.chooser = Gtk.FileChooserNative.new("Export completed hours", self, Gtk.FileChooserAction.SAVE, "Save", "Cancel")
        self.chooser.set_current_name(f"nonprofit-hours-{period.lower()}-{start.isoformat()}.csv")
        filter_ = Gtk.FileFilter()
        filter_.set_name("CSV files")
        filter_.add_pattern("*.csv")
        self.chooser.add_filter(filter_)
        self.chooser.connect("response", self.on_export_response, snapshot)
        self.chooser.show()

    def report_selection(self):
        try:
            day = date.fromisoformat(self.report_date.get_text())
        except ValueError:
            raise ValueError("Enter a valid date in YYYY-MM-DD format.")
        return ("Daily", "Weekly", "Monthly")[self.report_period.get_selected()], day

    def update_report(self, *_):
        if self.tracker is None:
            return
        self.copy_status.set_text("")
        try:
            period, day = self.report_selection()
            start, end = period_bounds(period, day)
            count = len(self.tracker.export_sessions(period, day))
            self.report_summary.set_text(f"{start} – {end - timedelta(days=1)}: {count} completed sessions")
            self.export.set_sensitive(count > 0)
            self.copy.set_sensitive(count > 0)
        except ValueError as error:
            self.report_summary.set_text(str(error))
            self.export.set_sensitive(False)
            self.copy.set_sensitive(False)

    def copy_report(self, *_):
        try:
            period, day = self.report_selection()
            text = self.tracker.clipboard_text(period, day)
            if text:
                self.get_clipboard().set(text)
                self.copy_status.set_text("Copied durations and notes.")
                self.error.set_text("")
        except Exception as error:
            self.error.set_text("Could not copy. " + str(error))

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
