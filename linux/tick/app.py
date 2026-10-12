"""GTK 4 UI. Run with python3 -m tick from linux/."""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, GLib, Gdk
from datetime import datetime, timezone, date, timedelta
from .core import FileStore, Tracker, data_path, elapsed, parse, StorageLocation, period_bounds
from .layout import build_layout


class HoursWindow(Gtk.ApplicationWindow):
    def __init__(self, application, path=None):
        super().__init__(application=application, title="Time is Clearly Kept", default_width=1000, default_height=760)
        self.tracker = None
        self.timer = None
        self.chooser = None
        self.selected_id = None
        self.refreshing_projects = False
        self.location = StorageLocation()
        self.connect("close-request", self.on_close)
        build_layout(self)
        try:
            self.tracker = Tracker(FileStore(path)) if path else self.location.open()
            active = self.tracker.active
            self.selected_id = self.default_project()
            self.notes.set_text(active["notes"] if active else "")
            self.refresh()
            self.timer = GLib.timeout_add_seconds(1, self.update_clock)
        except Exception as error:
            self.controls.set_sensitive(False)
            self.name.set_sensitive(False)
            self.add.set_sensitive(False)
            if isinstance(error, FileNotFoundError):
                self.error.set_text("Choose where to save tick.json to get started (Settings → Data location).")
                GLib.idle_add(self.prompt_for_data_location)
            else:
                self.error.set_text("Could not load saved hours. Your file was not changed. " + str(error))

    def prompt_for_data_location(self):
        self.choose_data_location()
        return GLib.SOURCE_REMOVE

    def perform(self, operation):
        try:
            operation()
            self.refresh()
            self.error.set_text("")
        except Exception as error:
            self.refresh()
            self.error.set_text(str(error))

    def add_nonprofit(self):
        def operation():
            self.selected_id = self.tracker.add_nonprofit(self.name.get_text())
            self.name.set_text("")
        self.perform(operation)

    def default_project(self):
        active = self.tracker.active
        if active:
            return active["projectId"]
        try:
            saved = self.location.settings.with_name("last-project").read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            saved = None
        nonprofits = self.tracker.state["nonprofits"]
        return next((n["id"] for n in nonprofits if n["id"] == saved),
                    next((n["id"] for n in nonprofits), None))

    def remember_project(self):
        if self.selected_id is not None:
            try:
                path = self.location.settings.with_name("last-project")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self.selected_id, encoding="utf-8")
            except OSError as error:
                self.error.set_text("Could not remember the project: " + str(error))

    def on_select(self, *_):
        if self.tracker and not self.refreshing_projects:
            index = self.nonprofits.get_selected()
            nonprofits = self.tracker.state["nonprofits"]
            self.selected_id = nonprofits[index]["id"] if index < len(nonprofits) else None
            self.remember_project()
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
        self.first_run.set_visible(not state["nonprofits"])
        selected = self.selected_id
        nonprofits = state["nonprofits"]
        self.refreshing_projects = True
        self.nonprofits.set_model(Gtk.StringList.new([n["name"] for n in nonprofits]))
        index = next((i for i, n in enumerate(nonprofits) if n["id"] == selected), Gtk.INVALID_LIST_POSITION)
        self.nonprofits.set_selected(index)
        self.selected_id = selected
        self.refreshing_projects = False
        self.remember_project()
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
        if not state["sessions"]:
            self.history.append(Gtk.Label(label="Sessions will appear here.", xalign=0))
        previous_week = None
        for session in sorted(state["sessions"], key=lambda s: parse(s["startTimeUtc"]), reverse=True):
            day = parse(session["startTimeUtc"]).astimezone().date()
            week_start, week_end = period_bounds("Weekly", day)
            if week_start != previous_week:
                last_day = week_end - timedelta(days=1)
                first_label = f"{week_start:%b} {week_start.day}"
                if week_start.year != last_day.year:
                    first_label += f", {week_start.year}"
                week_label = f"{first_label} – {last_day:%b} {last_day.day}, {last_day.year}"
                divider = Gtk.Box(spacing=12, margin_top=8, margin_bottom=4)
                heading = Gtk.Label(label=week_label, xalign=0, wrap=True)
                heading.add_css_class("heading")
                divider.append(heading)
                divider.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, valign=Gtk.Align.CENTER))
                week_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                                   margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
                week_frame = Gtk.Frame()
                week_frame.set_child(week_box)
                week_box.append(divider)
                self.history.append(week_frame)
            previous_week = week_start
            duration = elapsed(session["durationSeconds"]) if session.get("endTimeUtc") else "In progress"
            date = parse(session["startTimeUtc"]).astimezone().strftime("%Y-%m-%d %H:%M")
            label = Gtk.Label(label=f"{session['project']} — {date}\n{duration}\n{session['notes']}", xalign=0, wrap=True, selectable=True)
            week_box.append(label)
            if session.get("endTimeUtc"):
                edit = Gtk.Button(label="Edit notes", halign=Gtk.Align.START)
                edit.connect("clicked", lambda _, selected=session: self.edit_notes(selected))
                actions = Gtk.Box(spacing=8)
                actions.append(edit)
                times = Gtk.Button(label="Edit times", halign=Gtk.Align.START)
                times.connect("clicked", lambda _, selected=session: self.edit_times(selected))
                actions.append(times)
                if session.get("durationSeconds") is not None and 0 <= session["durationSeconds"] < 60:
                    delete = Gtk.Button(label="Delete")
                    delete.connect("clicked", lambda _, selected=session: self.perform(lambda: self.tracker.delete_session(selected["sessionId"])))
                    actions.append(delete)
                week_box.append(actions)
        self.update_clock()

    def add_manual_session(self):
        if self.tracker is None:
            self.error.set_text("Load your data folder first.")
            return
        dialog = Gtk.Dialog(title="Add session by hand", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.ACCEPT)
        content = dialog.get_content_area()
        content.set_spacing(12)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, "set_margin_" + side)(16)
        nonprofits = list(self.tracker.state["nonprofits"])
        content.append(Gtk.Label(label="Project", xalign=0))
        nonprofit = Gtk.DropDown(model=Gtk.StringList.new([n["name"] for n in nonprofits]))
        manual_path = self.location.settings.with_name("last-manual-project")
        try:
            saved = manual_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            saved = None
        nonprofit.set_selected(next((i for i, n in enumerate(nonprofits) if n["id"] == saved),
                                    0 if nonprofits else Gtk.INVALID_LIST_POSITION))

        def remember_manual_project(*_):
            index = nonprofit.get_selected()
            if index < len(nonprofits):
                try:
                    manual_path.parent.mkdir(parents=True, exist_ok=True)
                    manual_path.write_text(nonprofits[index]["id"], encoding="utf-8")
                except OSError as problem:
                    self.error.set_text("Could not remember the manual project: " + str(problem))

        nonprofit.connect("notify::selected", remember_manual_project)
        remember_manual_project()
        content.append(nonprofit)
        if not nonprofits:
            content.append(Gtk.Label(label="Add a nonprofit in Settings first.", xalign=0))
        entries = []
        now = datetime.now().replace(second=0, microsecond=0)
        start = now - timedelta(hours=1)
        for label, text in [("What did you work on?", ""),
                            ("Started (YYYY-MM-DD HH:MM)", start.strftime("%Y-%m-%d %H:%M")),
                            ("Ended (YYYY-MM-DD HH:MM)", (start + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"))]:
            content.append(Gtk.Label(label=label, xalign=0))
            entry = Gtk.Entry(text=text)
            entries.append(entry)
            content.append(entry)
        end_edited = False
        updating_end = False

        def end_changed(_):
            nonlocal end_edited
            if not updating_end:
                end_edited = True

        def start_changed(entry):
            nonlocal updating_end
            if end_edited:
                return
            try:
                suggested = datetime.strptime(entry.get_text(), "%Y-%m-%d %H:%M") + timedelta(minutes=15)
            except ValueError:
                return
            updating_end = True
            entries[2].set_text(suggested.strftime("%Y-%m-%d %H:%M"))
            updating_end = False

        entries[1].connect("changed", start_changed)
        entries[2].connect("changed", end_changed)
        content.append(Gtk.Label(label="Times use your local timezone (24-hour).", xalign=0))
        error = Gtk.Label(xalign=0, wrap=True)
        content.append(error)

        def local_time(entry):
            try:
                value = datetime.strptime(entry.get_text(), "%Y-%m-%d %H:%M")
            except ValueError:
                raise ValueError("Enter dates and times as YYYY-MM-DD HH:MM.")
            # Reject missing/repeated local wall times rather than silently shifting them.
            choices = [value.replace(fold=fold).astimezone(timezone.utc) for fold in (0, 1)]
            if choices[0] != choices[1] or choices[0].astimezone().replace(tzinfo=None) != value:
                raise ValueError("This local time is missing or repeated due to a clock change.")
            return choices[0]

        warning = Gtk.Label(xalign=0, wrap=True, selectable=True)
        scroll = Gtk.ScrolledWindow(max_content_height=220, propagate_natural_height=True)
        scroll.set_child(warning)
        content.append(scroll)
        confirmation = None
        def check_conflicts(*_):
            nonlocal confirmation
            confirmation = None
            dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).set_label("Save")
            try:
                conflicts = self.tracker.session_conflicts(local_time(entries[1]), local_time(entries[2]))
                warning.set_text(conflict_text(conflicts))
            except ValueError:
                warning.set_text("")
        def conflict_text(conflicts):
            def duration(seconds):
                seconds = int(seconds)
                return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
            details = []
            for c in conflicts:
                session = c["session"]
                details.append(f"{session['notes'].strip() or 'No notes'} — {session['project']}\n"
                               f"Duration: {duration(c['duration'])}"
                               + (" (running, so far)" if not session.get("endTimeUtc") else "")
                               + f"\nOverlap: {duration(c['overlap'])}\n"
                               + f"{c['start'].astimezone():%Y-%m-%d %H:%M:%S %Z} – {c['end'].astimezone():%Y-%m-%d %H:%M:%S %Z}")
            return "Time overlap detected\n\n" + "\n\n".join(details) if details else ""
        for entry in entries:
            entry.connect("changed", check_conflicts)
        nonprofit.connect("notify::selected", check_conflicts)
        check_conflicts()

        def respond(_, response):
            nonlocal confirmation
            if response == Gtk.ResponseType.ACCEPT:
                try:
                    index = nonprofit.get_selected()
                    if index >= len(nonprofits):
                        raise ValueError("Select a project.")
                    conflicts = self.tracker.session_conflicts(local_time(entries[1]), local_time(entries[2]))
                    signature = (tuple(e.get_text() for e in entries), index,
                                 tuple((c["session"]["sessionId"], c["session"]["startTimeUtc"], c["session"].get("endTimeUtc")) for c in conflicts))
                    warning.set_text(conflict_text(conflicts))
                    if conflicts and confirmation != signature:
                        confirmation = signature
                        error.set_text("Review the conflicts. Choose Save anyway to confirm intentional overlap.")
                        dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT).set_label("Save anyway")
                        return
                    self.tracker.add_session(nonprofits[index]["id"], entries[0].get_text(), local_time(entries[1]), local_time(entries[2]))
                    self.refresh()
                    self.error.set_text("")
                except Exception as problem:
                    error.set_text(str(problem))
                    return
            dialog.destroy()
        dialog.connect("response", respond)
        dialog.present()
        return dialog

    def edit_times(self, session):
        dialog = Gtk.Dialog(title="Edit session times", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.ACCEPT)
        content = dialog.get_content_area()
        content.set_spacing(12)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, "set_margin_" + side)(16)
        content.append(Gtk.Label(label=session["project"], xalign=0))
        content.append(Gtk.Label(label="Local dates and times: YYYY-MM-DD HH:MM:SS (24-hour).", xalign=0))
        entries = []
        originals = []
        for label, key in (("Started", "startTimeUtc"), ("Ended", "endTimeUtc")):
            original = parse(session[key])
            text = original.astimezone().replace(tzinfo=None).isoformat(sep=" ")
            originals.append((original, text))
            content.append(Gtk.Label(label=label, xalign=0))
            entry = Gtk.Entry(text=text)
            entries.append(entry)
            content.append(entry)
        error = Gtk.Label(xalign=0, wrap=True)
        error.add_css_class("error")
        content.append(error)

        def respond(_, response):
            if response == Gtk.ResponseType.ACCEPT:
                try:
                    def local_time(index):
                        text = entries[index].get_text()
                        original, initial = originals[index]
                        if text == initial:
                            return original
                        try:
                            value = datetime.fromisoformat(text)
                            if value.tzinfo is not None:
                                raise ValueError()
                        except ValueError:
                            raise ValueError("Enter local dates and times as YYYY-MM-DD HH:MM:SS.")
                        choices = [value.replace(fold=fold).astimezone(timezone.utc) for fold in (0, 1)]
                        if choices[0] != choices[1] or choices[0].astimezone().replace(tzinfo=None) != value:
                            raise ValueError("This local time is missing or repeated due to a clock change.")
                        return choices[0]
                    self.tracker.update_times(session["sessionId"], local_time(0), local_time(1))
                    self.refresh()
                    self.error.set_text("")
                except Exception as problem:
                    error.set_text(str(problem))
                    return
            dialog.destroy()
        dialog.connect("response", respond)
        dialog.present()
        return dialog

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
        content.append(Gtk.Label(label=f"{session['project']} — {date}", xalign=0, wrap=True))
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
            self.clock.set_text(f"{active['project']}: {elapsed(seconds)}")
        else:
            self.clock.set_text("Ready when you are")
        return GLib.SOURCE_CONTINUE

    def choose_data_location(self):
        if self.chooser:
            self.chooser.show()
            return
        self.chooser = Gtk.FileChooserNative.new("Choose where to save tick.json", self,
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
                first_run = self.tracker is None
                next_tracker = self.location.select(path, self.tracker)
                self.tracker = next_tracker
                active = self.tracker.active
                self.selected_id = self.default_project()
                self.notes.set_text(active["notes"] if active else "")
                self.refresh()
                if self.timer is None:
                    self.timer = GLib.timeout_add_seconds(1, self.update_clock)
                self.error.set_text("")
                if first_run and not self.tracker.state["nonprofits"]:
                    self.settings_panel.set_reveal_child(True)
                    self.name.grab_focus()
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
        self.chooser.set_current_name(f"tick-{period.lower()}-{start.isoformat()}.csv")
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
            self.report_preview.set_text(self.tracker.clipboard_text(period, day) or "No completed sessions in this period.")
            self.export.set_sensitive(count > 0)
            self.copy.set_sensitive(count > 0)
        except ValueError as error:
            self.report_summary.set_text(str(error))
            self.report_preview.set_text("")
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
        if self.layout_tick:
            self.remove_tick_callback(self.layout_tick)
            self.layout_tick = None
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
