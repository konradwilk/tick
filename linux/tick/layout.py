"""Capture-first layout, with a report beside history when space allows."""
from datetime import date
from gi.repository import Gtk
from .version import source_version


def build_layout(window):
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    for side in ("top", "bottom", "start", "end"):
        getattr(root, "set_margin_" + side)(24)
    window.set_child(root)
    header = Gtk.Box(spacing=12)
    title = Gtk.Label(label="Time is Clearly Kept", xalign=0, hexpand=True)
    title.add_css_class("title-1")
    header.append(title)
    settings = Gtk.Button(label="Settings")
    header.append(settings)
    root.append(header)
    window.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.append(window.controls)
    window.controls.append(Gtk.Label(label="Project", xalign=0))
    capture = Gtk.Box(spacing=14)
    window.nonprofits = Gtk.DropDown(model=Gtk.StringList.new([]), hexpand=True)
    window.nonprofits.connect("notify::selected", window.on_select)
    capture.append(window.nonprofits)
    window.toggle = Gtk.Button(label="Start")
    window.toggle.set_size_request(140, 48)
    window.toggle.connect("clicked", lambda button: window.write_feedback.run(button, window.toggle_tracking, root))
    capture.append(window.toggle)
    window.controls.append(capture)
    window.clock = Gtk.Label(xalign=0, wrap=True)
    window.clock.add_css_class("title-2")
    window.controls.append(window.clock)
    window.notes = Gtk.Entry(placeholder_text="What are you working on? (optional)")
    window.controls.append(window.notes)
    window.first_run = Gtk.Label(label="Add your first nonprofit in Settings to begin.", xalign=0, wrap=True)
    window.controls.append(window.first_run)
    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    root.append(scroll)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    scroll.set_child(body)
    window.error = Gtk.Label(xalign=0, wrap=True, selectable=True)
    window.error.add_css_class("error")
    body.append(window.error)
    window.settings_panel = Gtk.Revealer()
    settings.connect("clicked", lambda *_: window.settings_panel.set_reveal_child(not window.settings_panel.get_reveal_child()))
    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    window.settings_panel.set_child(panel)
    body.append(window.settings_panel)
    panel.append(Gtk.Label(label="Settings", xalign=0))
    window.name = Gtk.Entry(placeholder_text="New project", hexpand=True)
    window.name.connect("activate", lambda *_: window.write_feedback.run(window.add, window.add_nonprofit, root))
    window.add = Gtk.Button(label="Add nonprofit")
    window.add.connect("clicked", lambda *_: window.write_feedback.run(window.add, window.add_nonprofit, root))
    panel.append(window.name)
    panel.append(window.add)
    manual = Gtk.Button(label="Add session by hand…")
    manual.connect("clicked", lambda *_: window.add_manual_session())
    panel.append(manual)
    panel.append(Gtk.Label(label="Data storage: Local file works offline; Google Sheets shares data online.", xalign=0, wrap=True))
    provider = Gtk.CssProvider()
    provider.load_from_data(b"""
        button.tick-writing, button.tick-writing:disabled {
            background-image: none;
            background-color: #9c6500;
            color: white;
            opacity: 1;
        }
        button.tick-storage-active {
            background-image: none;
            background-color: rgba(46, 160, 67, 0.16);
            border: 2px solid #2ea043;
        }
        button.tick-storage-inactive {
            background-image: none;
            background-color: rgba(128, 128, 128, 0.08);
            border: 1px solid rgba(128, 128, 128, 0.4);
        }
    """)
    Gtk.StyleContext.add_provider_for_display(window.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    sheets = Gtk.Button(label="Google Sheets… — Not active")
    window.sheets_storage_button = sheets
    sheets.add_css_class("tick-storage-inactive")
    sheets.connect("clicked", lambda *_: window.choose_sheets())
    panel.append(sheets)
    location = Gtk.Button(label="Local file (tick.json)… — Not active")
    window.local_storage_button = location
    location.add_css_class("tick-storage-inactive")
    location.connect("clicked", lambda *_: window.choose_data_location())
    panel.append(location)
    window.location_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
    panel.append(window.location_label)
    panel.append(Gtk.Label(label="Use one device at a time; reload after a conflict.", xalign=0, wrap=True))
    panel.append(Gtk.Label(label="Timing continues when the app closes. Reopen and press Stop to finish.", xalign=0, wrap=True))
    panel.append(Gtk.Label(label="This is version " + source_version(), xalign=0, selectable=True))
    done = Gtk.Button(label="Done")
    done.connect("clicked", lambda *_: window.settings_panel.set_reveal_child(False))
    panel.append(done)
    window.workspace = Gtk.Box(spacing=24)
    body.append(window.workspace)
    history_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True, valign=Gtk.Align.START)
    window.workspace.append(history_panel)
    title = Gtk.Label(label="History", xalign=0)
    title.add_css_class("title-2")
    history_panel.append(title)
    window.total = Gtk.Label(xalign=0, wrap=True)
    history_panel.append(window.total)
    window.history = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    history_panel.append(window.history)
    window.report_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True, valign=Gtk.Align.START)
    report = window.report_panel
    window.workspace.append(report)
    title = Gtk.Label(label="Export & copy", xalign=0)
    title.add_css_class("title-2")
    report.append(title)
    window.report_period = Gtk.DropDown(model=Gtk.StringList.new(["Daily", "Weekly", "Monthly"]))
    window.report_period.set_selected(2)
    window.report_period.connect("notify::selected", window.update_report)
    report.append(window.report_period)
    report.append(Gtk.Label(label="Date in period (YYYY-MM-DD)", xalign=0))
    window.report_date = Gtk.Entry(text=date.today().isoformat())
    window.report_date.connect("changed", window.update_report)
    report.append(window.report_date)
    window.report_summary = Gtk.Label(xalign=0, wrap=True)
    report.append(window.report_summary)
    report.append(Gtk.Label(label="Completed sessions by local start date. Weeks run Monday–Sunday.", xalign=0, wrap=True))
    report.append(Gtk.Label(label="Summary preview", xalign=0))
    window.report_preview = Gtk.Label(xalign=0, wrap=True, selectable=True)
    window.report_preview.set_max_width_chars(44)
    window.report_preview.add_css_class("monospace")
    report.append(window.report_preview)
    window.export = Gtk.Button(label="Export CSV", sensitive=False)
    window.export.connect("clicked", window.export_csv)
    report.append(window.export)
    window.copy = Gtk.Button(label="Copy summary", sensitive=False)
    window.copy.connect("clicked", lambda button: window.write_feedback.run(button, window.copy_report, root))
    report.append(window.copy)
    window.copy_status = Gtk.Label(xalign=0, wrap=True)
    report.append(window.copy_status)

    def adapt(widget, _clock):
        narrow = widget.get_width() < 820
        orientation = Gtk.Orientation.VERTICAL if narrow else Gtk.Orientation.HORIZONTAL
        if window.workspace.get_orientation() != orientation:
            window.workspace.set_orientation(orientation)
        capture.set_orientation(Gtk.Orientation.VERTICAL if widget.get_width() < 460 else Gtk.Orientation.HORIZONTAL)
        return True

    window.layout_tick = window.add_tick_callback(adapt)
