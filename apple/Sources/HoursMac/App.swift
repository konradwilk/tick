import SwiftUI
import AppKit
import UniformTypeIdentifiers
import HoursCore

@MainActor @Observable final class AppModel {
    var needsDataLocation = false
    var promptedForDataLocation = false
    var tracker: Tracker?
    var state = TrackerState()
    var error: String?
    var selected: UUID? {
        didSet {
            if let selected { UserDefaults.standard.set(selected.uuidString, forKey: "lastSelectedProject") }
        }
    }
    private var defaultProject: UUID? {
        let saved = UserDefaults.standard.string(forKey: "lastSelectedProject").flatMap(UUID.init(uuidString:))
        return state.active?.projectId ?? state.nonprofits.first(where: { $0.id == saved })?.id ?? state.nonprofits.first?.id
    }
    var notes = ""
    var dataLocation = ""
    var reportPeriod = ExportPeriod.monthly
    var reportDate = Date()
    var copyStatus = ""
    var reportRange: ExportRange { ExportRange(period: reportPeriod, date: reportDate) }
    var reportCount: Int { tracker?.exportSessions(range: reportRange).count ?? 0 }
    private let storage = StorageLocation()
    init() {
        do {
            let folder = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let location = try storage.resolve(defaultURL: folder.appending(path: "NonprofitHours/tick.json"))
            let file = location.selected ? location.url.appendingPathComponent("tick.json") : location.url
            guard FileManager.default.fileExists(atPath: file.path) else { needsDataLocation = true; return }
            dataLocation = file.deletingLastPathComponent().path
            let tracker = try Tracker(file: file, requireExisting: location.selected)
            self.tracker = tracker
            state = tracker.state
            selected = defaultProject
            notes = state.active?.notes ?? ""
        } catch { self.error = "Could not load saved hours: \(error.localizedDescription) Your saved file has not been changed." }
    }
    func perform(_ action: (Tracker) throws -> Void) {
        guard let tracker else { return }
        defer { state = tracker.state }
        do { try action(tracker) }
        catch { self.error = error.localizedDescription }
    }
    func toggleTracking() {
        perform { tracker in
            if state.active != nil { try tracker.stop(); notes = "" }
            else if let selected { try tracker.start(projectId: selected, notes: notes) }
        }
    }
    func chooseDataLocation() {
        do {
            let panel = NSOpenPanel()
            panel.title = "Choose where to save tick.json"
            panel.prompt = "Use this folder"
            panel.canChooseFiles = false
            panel.canChooseDirectories = true
            panel.canCreateDirectories = true
            panel.allowsMultipleSelection = false
            guard panel.runModal() == .OK, let folder = panel.url else { return }
            let access = folder.startAccessingSecurityScopedResource()
            defer { if access { folder.stopAccessingSecurityScopedResource() } }
            let file = folder.appendingPathComponent("tick.json")
            let next: Tracker
            if FileManager.default.fileExists(atPath: file.path) {
                next = try Tracker(file: file, requireExisting: true)
            } else if let tracker {
                next = try tracker.saveAs(file)
            } else {
                let fresh = try Tracker(file: file)
                next = try fresh.saveAs(file)
            }
            try storage.remember(folder)
            needsDataLocation = false
            tracker = next
            state = next.state
            dataLocation = folder.path
            selected = defaultProject
            notes = state.active?.notes ?? ""
            error = nil
        } catch { self.error = error.localizedDescription }
    }
    func export() {
        guard let tracker else { return }
        let range = reportRange
        let snapshot = tracker.csv(range: range)
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.dateFormat = "yyyy-MM-dd"
        panel.nameFieldStringValue = "tick-\(reportPeriod.rawValue.lowercased())-\(formatter.string(from: range.start)).csv"
        if panel.runModal() == .OK, let url = panel.url {
            do { try snapshot.write(to: url, atomically: true, encoding: .utf8) }
            catch { self.error = error.localizedDescription }
        }
    }
    func copyReport() {
        guard let text = tracker?.clipboardText(range: reportRange), !text.isEmpty else { return }
        NSPasteboard.general.clearContents()
        if NSPasteboard.general.setString(text, forType: .string) {
            copyStatus = "Copied durations and notes."
        } else { error = "Could not copy durations and notes." }
    }
}

@main struct HoursApp: App {
    @State private var model = AppModel()
    var body: some Scene {
        Window("Time is Clearly Kept", id: "main") { TrackerView(model: model) }
            .defaultSize(width: 1000, height: 760)
        MenuBarExtra {
            MenuBarTrackerView(model: model)
        } label: {
            Label(model.state.active == nil ? "Time is Clearly Kept" : "Tracking hours",
                  systemImage: model.state.active == nil ? "clock" : "record.circle.fill")
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor struct SessionTimesEditor: View {
    let session: Session
    let model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var start: Date
    @State private var end: Date
    @State private var error: String?
    init(session: Session, model: AppModel) {
        self.session = session
        self.model = model
        _start = State(initialValue: session.startTimeUtc)
        _end = State(initialValue: session.endTimeUtc ?? session.startTimeUtc)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Edit session times").font(.title2)
            Text(session.project)
            DatePicker("Started", selection: $start, displayedComponents: [.date, .hourAndMinute])
            DatePicker("Ended", selection: $end, displayedComponents: [.date, .hourAndMinute])
            Text("Times use your local timezone.").font(.caption)
            if end <= start { Text("End must be after start.").foregroundStyle(.red) }
            if let error { Text(error).foregroundStyle(.red) }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Save") {
                    do {
                        guard let tracker = model.tracker else { throw TrackerError.missingSession }
                        try tracker.updateTimes(sessionId: session.sessionId, start: start, end: end)
                        model.state = tracker.state
                        model.error = nil
                        model.copyStatus = ""
                        dismiss()
                    } catch { self.error = error.localizedDescription }
                }.disabled(end <= start).keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 440)
    }
}

struct SessionNotesEditor: View {
    let session: Session
    let model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var notes: String
    @State private var error: String?

    init(session: Session, model: AppModel) {
        self.session = session
        self.model = model
        _notes = State(initialValue: session.notes)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Edit session notes").font(.title2)
            Text("\(session.project) — \(session.startTimeUtc.formatted(date: .abbreviated, time: .shortened))")
            Text("What did you work on?")
            TextEditor(text: $notes).frame(minHeight: 140).accessibilityLabel("Session notes")
            if let error { Text(error).foregroundStyle(.red) }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Save") {
                    do {
                        guard let tracker = model.tracker else { throw TrackerError.missingSession }
                        try tracker.updateNotes(sessionId: session.sessionId, notes: notes)
                        model.state = tracker.state
                        model.error = nil
                        dismiss()
                    } catch { self.error = "Could not save notes. " + error.localizedDescription }
                }.keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 440)
    }
}

/// Uses the same model as the main window, including selection and draft notes.
struct MenuBarTrackerView: View {
    @Bindable var model: AppModel
    @Environment(\.openWindow) private var openWindow
    private var active: Session? { model.state.active }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Time is Clearly Kept").font(.headline)
            if let active {
                Text(active.project).font(.subheadline.bold())
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    let seconds = max(0, Int(context.date.timeIntervalSince(active.startTimeUtc)))
                    Text(String(format: "%02d:%02d:%02d", seconds / 3600, seconds % 3600 / 60, seconds % 60))
                        .font(.system(size: 30, weight: .medium, design: .monospaced))
                }
                if !active.notes.isEmpty { Text(active.notes).lineLimit(3) }
            } else {
                if model.state.nonprofits.isEmpty {
                    Text("Open the main window to add your first nonprofit.").foregroundStyle(.secondary)
                } else {
                    Picker("Project", selection: $model.selected) {
                        Text("Choose a project").tag(nil as UUID?)
                        ForEach(model.state.nonprofits) { Text($0.name).tag(Optional($0.id)) }
                    }
                    TextField("Notes (optional)", text: $model.notes)
                }
            }
            Button(action: model.toggleTracking) {
                Label(active == nil ? "Start" : "Stop", systemImage: active == nil ? "play.fill" : "stop.fill")
                    .frame(maxWidth: .infinity).padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .tint(active == nil ? .green : .red)
            .disabled(model.tracker == nil || (active == nil && model.selected == nil))
            if let error = model.error {
                Text(error).font(.caption).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                Button("Dismiss error") { model.error = nil }
            }
            Divider()
            Button("Open Time is Clearly Kept") {
                openWindow(id: "main")
                NSApplication.shared.activate(ignoringOtherApps: true)
            }
            Button("Quit Time is Clearly Kept") { NSApplication.shared.terminate(nil) }
            if active != nil {
                Text("Closing the window or quitting keeps this session running until you stop it.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(18).frame(width: 300)
    }
}
