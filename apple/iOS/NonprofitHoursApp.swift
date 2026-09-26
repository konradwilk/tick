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

struct CSVDocument: FileDocument {
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

func duration(_ seconds: Int) -> String {
    let value = max(0, seconds)
    return String(format: "%02d:%02d:%02d", value / 3600, value % 3600 / 60, value % 60)
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
