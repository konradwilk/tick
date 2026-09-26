import SwiftUI
import UniformTypeIdentifiers
import UIKit

@main @MainActor struct NonprofitHoursApp: App {
    @State private var model = PhoneModel()
    var body: some Scene { WindowGroup { PhoneTrackerView(model: model) } }
}

@MainActor @Observable final class PhoneModel {
    var tracker: Tracker?
    var state = TrackerState()
    var selected: UUID?
    var notes = ""
    var error: String?
    var location = ""
    private let storage = StorageLocation()

    init() {
        do {
            let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let saved = try storage.resolve(defaultURL: base.appendingPathComponent("NonprofitHours/sessions.json"))
            let file = saved.selected ? saved.url.appendingPathComponent("nonprofit-hours.json") : saved.url
            adopt(try Tracker(file: file, requireExisting: saved.selected))
        } catch { self.error = "Could not load saved hours. " + error.localizedDescription }
    }
    private func adopt(_ next: Tracker) {
        tracker = next
        state = next.state
        selected = state.active?.nonprofitId ?? state.nonprofits.first?.id
        notes = state.active?.notes ?? ""
        location = next.file.deletingLastPathComponent().path
    }
    func perform(_ action: (Tracker) throws -> Void) {
        guard let tracker else { return }
        do { try action(tracker); state = tracker.state; error = nil }
        catch { self.error = error.localizedDescription }
    }
    func selectFolder(_ folder: URL) {
        let access = folder.startAccessingSecurityScopedResource()
        defer { if access { folder.stopAccessingSecurityScopedResource() } }
        do {
            let file = folder.appendingPathComponent("nonprofit-hours.json")
            let next: Tracker
            if FileManager.default.fileExists(atPath: file.path) {
                next = try Tracker(file: file, requireExisting: true)
            } else if let tracker { next = try tracker.saveAs(file) }
            else { throw CocoaError(.fileReadNoSuchFile) }
            try storage.remember(folder)
            adopt(next)
            error = nil
        } catch { self.error = error.localizedDescription }
    }
}

private struct CSVDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.commaSeparatedText] }
    var text: String
    init(text: String) { self.text = text }
    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents, let text = String(data: data, encoding: .utf8) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        self.text = text
    }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: Data(text.utf8))
    }
}

private func duration(_ seconds: Int) -> String {
    let value = max(0, seconds)
    return String(format: "%02d:%02d:%02d", value / 3600, value % 3600 / 60, value % 60)
}

@MainActor struct PhoneTrackerView: View {
    @Bindable var model: PhoneModel
    @State private var newName = ""
    @State private var period = ExportPeriod.monthly
    @State private var date = Date()
    @State private var choosingFolder = false
    @State private var exporting = false
    @State private var document = CSVDocument(text: "")
    @State private var filename = "nonprofit-hours"
    @State private var copyStatus = ""
    @State private var editing: Session?
    private var range: ExportRange { ExportRange(period: period, date: date) }
    private var count: Int {
        model.state.sessions.filter { $0.endTimeUtc != nil && $0.startTimeUtc >= range.start && $0.startTimeUtc < range.end }.count
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Data location") {
                    Button("Choose data folder…") { choosingFolder = true }
                    Text(model.location).font(.caption).textSelection(.enabled)
                    Text("All changes are saved here. Use one device at a time.").font(.caption)
                }
                Section("Capture") {
                    HStack {
                        TextField("New nonprofit", text: $newName)
                        Button("Add") { model.perform { model.selected = try $0.addNonprofit(newName); newName = "" } }
                            .disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }.disabled(model.tracker == nil || model.state.active != nil)
                    Picker("Nonprofit", selection: $model.selected) {
                        Text("Choose a nonprofit").tag(nil as UUID?)
                        ForEach(model.state.nonprofits) { Text($0.name).tag(Optional($0.id)) }
                    }.disabled(model.tracker == nil || model.state.active != nil)
                    TextField("Notes (optional)", text: $model.notes, axis: .vertical)
                        .disabled(model.tracker == nil || model.state.active != nil)
                    if let active = model.state.active {
                        Text(active.nonprofitName).font(.headline)
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            Text(duration(Int(context.date.timeIntervalSince(active.startTimeUtc)))).monospacedDigit()
                        }
                    }
                    Button(model.state.active == nil ? "Start" : "Stop") {
                        model.perform { tracker in
                            if model.state.active != nil { try tracker.stop(); model.notes = "" }
                            else if let id = model.selected { try tracker.start(nonprofitId: id, notes: model.notes, platform: "ios") }
                        }
                    }
                    .tint(model.state.active == nil ? .green : .red)
                    .disabled(model.tracker == nil || (model.state.active == nil && model.selected == nil))
                    Text("Timing continues when the app closes. Reopen and press Stop to finish.").font(.caption)
                }
                Section("Export") {
                    Text("Completed: \(Double(model.state.sessions.compactMap(\.durationSeconds).reduce(0, +)) / 3600, specifier: "%.2f") hours")
                    Picker("Period", selection: $period) {
                        ForEach(ExportPeriod.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    DatePicker("Date in period", selection: $date, displayedComponents: .date)
                    Text("\(range.start.formatted(date: .abbreviated, time: .omitted)) – \(range.end.addingTimeInterval(-1).formatted(date: .abbreviated, time: .omitted)): \(count) completed sessions")
                        .font(.caption)
                    Text("Completed sessions by local start date. Weeks run Monday–Sunday.").font(.caption)
                    Button("Export CSV…") {
                        guard let tracker = model.tracker else { return }
                        document = CSVDocument(text: tracker.csv(range: range))
                        let formatter = DateFormatter()
                        formatter.locale = Locale(identifier: "en_US_POSIX")
                        formatter.calendar = Calendar(identifier: .gregorian)
                        formatter.dateFormat = "yyyy-MM-dd"
                        filename = "nonprofit-hours-\(period.rawValue.lowercased())-\(formatter.string(from: range.start))"
                        exporting = true
                    }.disabled(count == 0)
                    Button("Copy durations and notes") {
                        guard let tracker = model.tracker else { return }
                        UIPasteboard.general.string = tracker.clipboardText(range: range)
                        copyStatus = "Copied durations and notes."
                    }.disabled(count == 0)
                    if !copyStatus.isEmpty { Text(copyStatus).font(.caption) }
                }
                Section("History") {
                    ForEach(model.state.sessions.reversed()) { session in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(session.nonprofitName).font(.headline)
                            Text(session.startTimeUtc.formatted(date: .abbreviated, time: .shortened)).font(.caption)
                            Text(session.durationSeconds.map(duration) ?? "In progress")
                            if !session.notes.isEmpty { Text(session.notes) }
                            if session.endTimeUtc != nil { Button("Edit notes") { editing = session } }
                        }
                    }
                }
            }
            .navigationTitle("Nonprofit Hours")
        }
        .onChange(of: period) { copyStatus = "" }
        .onChange(of: date) { copyStatus = "" }
        .fileImporter(isPresented: $choosingFolder, allowedContentTypes: [.folder]) { result in
            switch result {
            case .success(let folder): model.selectFolder(folder)
            case .failure(let error): model.error = error.localizedDescription
            }
        }
        .fileExporter(isPresented: $exporting, document: document, contentType: .commaSeparatedText, defaultFilename: filename) { result in
            if case .failure(let error) = result { model.error = error.localizedDescription }
        }
        .sheet(item: $editing) { session in PhoneNotesEditor(session: session, model: model) }
        .alert("Unable to complete action", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK") { model.error = nil }
        } message: { Text(model.error ?? "") }
    }
}

@MainActor struct PhoneNotesEditor: View {
    let session: Session
    let model: PhoneModel
    @Environment(\.dismiss) private var dismiss
    @State private var notes: String
    @State private var error: String?
    init(session: Session, model: PhoneModel) {
        self.session = session
        self.model = model
        _notes = State(initialValue: session.notes)
    }
    var body: some View {
        NavigationStack {
            Form {
                Text(session.nonprofitName)
                Text(session.startTimeUtc.formatted(date: .abbreviated, time: .shortened))
                Section("What did you work on?") {
                    TextEditor(text: $notes).frame(minHeight: 180).accessibilityLabel("Session notes")
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("Edit notes")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        do {
                            guard let tracker = model.tracker else { throw TrackerError.missingSession }
                            try tracker.updateNotes(sessionId: session.sessionId, notes: notes)
                            model.state = tracker.state
                            dismiss()
                        } catch { self.error = "Could not save notes. " + error.localizedDescription }
                    }
                }
            }
        }
    }
}
