import SwiftUI
import AppKit
import UniformTypeIdentifiers
import HoursCore

@MainActor @Observable final class AppModel {
    var tracker: Tracker?
    var state = TrackerState()
    var error: String?
    var selected: UUID?
    var notes = ""
    init() {
        do {
            let folder = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let tracker = try Tracker(file: folder.appending(path: "NonprofitHours/sessions.json"))
            self.tracker = tracker
            state = tracker.state
            selected = state.active?.nonprofitId ?? state.nonprofits.first?.id
            notes = state.active?.notes ?? ""
        } catch { self.error = "Could not load saved hours: \(error.localizedDescription). Your saved file has not been changed." }
    }
    func perform(_ action: (Tracker) throws -> Void) {
        guard let tracker else { return }
        do { try action(tracker); state = tracker.state }
        catch { self.error = error.localizedDescription }
    }
    func toggleTracking() {
        perform { tracker in
            if state.active != nil { try tracker.stop(); notes = "" }
            else if let selected { try tracker.start(nonprofitId: selected, notes: notes) }
        }
    }
    func export() {
        guard let tracker else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "nonprofit-hours.csv"
        if panel.runModal() == .OK, let url = panel.url {
            do { try tracker.csv().write(to: url, atomically: true, encoding: .utf8) }
            catch { self.error = error.localizedDescription }
        }
    }
}

@main struct HoursApp: App {
    @State private var model = AppModel()
    var body: some Scene {
        Window("Nonprofit Hours", id: "main") { TrackerView(model: model) }
            .defaultSize(width: 720, height: 640)
        MenuBarExtra {
            MenuBarTrackerView(model: model)
        } label: {
            Label(model.state.active == nil ? "Nonprofit Hours" : "Tracking hours",
                  systemImage: model.state.active == nil ? "clock" : "record.circle.fill")
        }
        .menuBarExtraStyle(.window)
    }
}

struct TrackerView: View {
    @Bindable var model: AppModel
    @State private var newName = ""
    private var active: Session? { model.state.active }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Nonprofit Hours").font(.largeTitle.bold())
            Text("Make your time count.").foregroundStyle(.secondary)
            HStack {
                TextField("Add a nonprofit", text: $newName)
                    .onSubmit { addNonprofit() }
                Button("Add", action: addNonprofit).disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .disabled(active != nil)
            Picker("Nonprofit", selection: $model.selected) {
                Text("Choose a nonprofit").tag(nil as UUID?)
                ForEach(model.state.nonprofits) { Text($0.name).tag(Optional($0.id)) }
            }.disabled(active != nil)
            TextField("Notes (optional)", text: $model.notes).disabled(active != nil)
            if let active {
                Text("Tracking for \(active.nonprofitName)").font(.headline)
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(elapsed(context.date.timeIntervalSince(active.startTimeUtc)))
                        .font(.system(size: 44, weight: .medium, design: .monospaced))
                }
            } else { Text("Ready when you are").font(.headline) }
            Button {
                model.toggleTracking()
            } label: {
                Text(active == nil ? "Start" : "Stop").font(.title2.bold()).frame(maxWidth: .infinity).padding(10)
            }
            .buttonStyle(.borderedProminent).tint(active == nil ? .green : .red)
            .disabled(model.tracker == nil || (active == nil && model.selected == nil))
            HStack {
                Text("Completed: \(Double(model.state.sessions.compactMap(\.durationSeconds).reduce(0, +)) / 3600, specifier: "%.2f") hours").font(.headline)
                Spacer()
                Button("Export CSV…") { model.export() }.disabled(!model.state.sessions.contains { $0.endTimeUtc != nil })
            }
            Text("Import the CSV into Google Sheets using File → Import.").font(.caption).foregroundStyle(.secondary)
            List(model.state.sessions.reversed()) { session in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(session.nonprofitName).bold()
                        Spacer()
                        Text(session.durationSeconds.map { elapsed(Double($0)) } ?? "In progress")
                    }
                    Text(session.startTimeUtc.formatted(date: .abbreviated, time: .shortened)).foregroundStyle(.secondary)
                    if !session.notes.isEmpty { Text(session.notes) }
                }.padding(.vertical, 4)
            }
        }.padding(24).frame(minWidth: 560, minHeight: 580)
        .disabled(model.tracker == nil)
        .alert("Unable to complete action", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK") { model.error = nil }
        } message: { Text(model.error ?? "") }
    }
    private func addNonprofit() {
        model.perform { model.selected = try $0.addNonprofit(newName); newName = "" }
    }
    private func elapsed(_ seconds: Double) -> String {
        let value = max(0, Int(seconds))
        return String(format: "%02d:%02d:%02d", value / 3600, (value % 3600) / 60, value % 60)
    }
}

/// Uses the same model as the main window, including selection and draft notes.
struct MenuBarTrackerView: View {
    @Bindable var model: AppModel
    @Environment(\.openWindow) private var openWindow
    private var active: Session? { model.state.active }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Nonprofit Hours").font(.headline)
            if let active {
                Text(active.nonprofitName).font(.subheadline.bold())
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
                    Picker("Nonprofit", selection: $model.selected) {
                        Text("Choose a nonprofit").tag(nil as UUID?)
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
            Button("Open Nonprofit Hours") {
                openWindow(id: "main")
                NSApplication.shared.activate(ignoringOtherApps: true)
            }
            Button("Quit Nonprofit Hours") { NSApplication.shared.terminate(nil) }
            if active != nil {
                Text("Closing the window or quitting keeps this session running until you stop it.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(18).frame(width: 300)
    }
}
