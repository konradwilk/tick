import SwiftUI
import UniformTypeIdentifiers
import UIKit

@MainActor struct PhoneTrackerView: View {
    @Bindable var model: PhoneModel
    @State private var newName = ""
    @State private var settings = false
    @State private var manualNonprofit: UUID?
    @State private var manualNotes = ""
    @State private var manualStart = Date().addingTimeInterval(-3600)
    @State private var manualEnd = Date()
    @State private var manualDatesInitialized = false
    @State private var manualEndEdited = false
    @State private var manualStatus = ""
    @State private var period = ExportPeriod.monthly
    @State private var date = Date()
    @State private var choosingFolder = false
    @State private var chooseFolderAfterSettings = false
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
            VStack(spacing: 12) {
                if model.needsDataLocation {
                    Text("Choose where to save tick.json to get started.")
                    Button("Choose data folder…") { choosingFolder = true }
                }
                capture.padding(.horizontal)
                Divider()
                GeometryReader { geometry in
                    ScrollView {
                        let layout = geometry.size.width >= 760 ? AnyLayout(HStackLayout(alignment: .top, spacing: 20)) : AnyLayout(VStackLayout(alignment: .leading, spacing: 20))
                        layout {
                            history.frame(maxWidth: .infinity, alignment: .leading)
                            report.frame(maxWidth: .infinity, alignment: .leading)
                        }.padding()
                    }
                }
            }
            .navigationTitle("Time is Clearly Kept").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Settings") { settings = true } } }
        }
        .task {
            if model.needsDataLocation && !model.promptedForDataLocation {
                model.promptedForDataLocation = true
                choosingFolder = true
            }
        }
        .fileImporter(isPresented: $choosingFolder, allowedContentTypes: [.folder]) { result in
            switch result {
            case .success(let folder): model.selectFolder(folder)
            case .failure(let error): model.error = error.localizedDescription
            }
        }
        .onChange(of: period) { copyStatus = "" }
        .onChange(of: date) { copyStatus = "" }
        .sheet(isPresented: $settings, onDismiss: {
            if chooseFolderAfterSettings { chooseFolderAfterSettings = false; choosingFolder = true }
        }) { settingsView }
        .fileExporter(isPresented: $exporting, document: document, contentType: .commaSeparatedText, defaultFilename: filename) { result in
            if case .failure(let error) = result { model.error = error.localizedDescription }
        }
        .sheet(item: $editing) { PhoneNotesEditor(session: $0, model: model) }
        .alert("Unable to complete action", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK") { model.error = nil }
        } message: { Text(model.error ?? "") }
    }
    private var capture: some View {
        VStack(alignment: .leading, spacing: 10) {
            Picker("Project", selection: $model.selected) {
                Text("Choose a project").tag(nil as UUID?)
                ForEach(model.state.nonprofits) { Text($0.name).tag(Optional($0.id)) }
            }.disabled(model.tracker == nil || model.state.active != nil)
            Button {
                model.perform { tracker in
                    if model.state.active != nil { try tracker.stop(); model.notes = "" }
                    else if let id = model.selected { try tracker.start(projectId: id, notes: model.notes, platform: "ios") }
                }
            } label: { Text(model.state.active == nil ? "Start" : "Stop").font(.title3.bold()).frame(maxWidth: .infinity).padding(.vertical, 6) }
                .buttonStyle(.borderedProminent).tint(model.state.active == nil ? .green : .red)
                .disabled(model.tracker == nil || (model.state.active == nil && model.selected == nil))
            if let active = model.state.active {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text("\(active.project): \(duration(Int(context.date.timeIntervalSince(active.startTimeUtc))))").monospacedDigit()
                }
            } else { Text("Ready when you are").foregroundStyle(.secondary) }
            TextField("What are you working on? (optional)", text: $model.notes)
                .textFieldStyle(.roundedBorder).disabled(model.tracker == nil || model.state.active != nil)
            if model.state.nonprofits.isEmpty { Button("Add your first nonprofit in Settings") { settings = true }.font(.caption) }
        }
    }
    private var history: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("History").font(.title2.bold())
            Text("Completed: \(Double(model.state.sessions.compactMap(\.durationSeconds).reduce(0, +)) / 3600, specifier: "%.2f") hours").font(.subheadline)
            if model.state.sessions.isEmpty { Text("Sessions will appear here.").foregroundStyle(.secondary) }
            ForEach(model.state.sessions.sorted { $0.startTimeUtc > $1.startTimeUtc }) { session in
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(session.project).font(.headline)
                        Text(session.startTimeUtc.formatted(date: .abbreviated, time: .shortened)).font(.caption)
                        Text(session.durationSeconds.map(duration) ?? "In progress").monospacedDigit()
                        Text(session.notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "No notes" : session.notes)
                        if session.endTimeUtc != nil {
                            HStack {
                                Button("Edit notes") { editing = session }
                                if let seconds = session.durationSeconds, seconds >= 0, seconds < 60 {
                                    Button("Delete", role: .destructive) { model.perform { try $0.deleteSession(sessionId: session.sessionId); copyStatus = "" } }
                                }
                            }
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }
    private var report: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                Text("Export & copy").font(.title2.bold())
                Picker("Period", selection: $period) {
                    ForEach(ExportPeriod.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.segmented)
                DatePicker("Date in period", selection: $date, displayedComponents: .date)
                Text("\(range.start.formatted(date: .abbreviated, time: .omitted)) – \(range.end.addingTimeInterval(-1).formatted(date: .abbreviated, time: .omitted)): \(count) completed sessions").font(.caption)
                Text("Completed sessions by local start date. Weeks run Monday–Sunday.").font(.caption).foregroundStyle(.secondary)
                Text("Summary preview").font(.headline)
                Text(count == 0 ? "No completed sessions in this period." : model.tracker?.clipboardText(range: range) ?? "")
                    .font(.system(.body, design: .monospaced)).textSelection(.enabled)
                Button("Export CSV…") {
                    guard let tracker = model.tracker else { return }
                    document = CSVDocument(text: tracker.csv(range: range))
                    let formatter = DateFormatter()
                    formatter.locale = Locale(identifier: "en_US_POSIX")
                    formatter.calendar = Calendar(identifier: .gregorian)
                    formatter.dateFormat = "yyyy-MM-dd"
                    filename = "tick-\(period.rawValue.lowercased())-\(formatter.string(from: range.start))"
                    exporting = true
                }.buttonStyle(.bordered).disabled(count == 0)
                Button("Copy summary") {
                    guard let tracker = model.tracker else { return }
                    UIPasteboard.general.string = tracker.clipboardText(range: range)
                    copyStatus = "Copied durations and notes."
                }.buttonStyle(.bordered).disabled(count == 0)
                if !copyStatus.isEmpty { Text(copyStatus).font(.caption) }
            }.frame(maxWidth: .infinity, alignment: .leading)
        }
    }
    private var manualSessionForm: some View {
        DisclosureGroup("Add session by hand") {
            VStack(alignment: .leading, spacing: 12) {
                Picker("Project", selection: $manualNonprofit) {
                    Text("Choose a project").tag(nil as UUID?)
                    ForEach(model.state.nonprofits) { Text($0.name).tag(Optional($0.id)) }
                }
                TextField("What did you work on?", text: $manualNotes, axis: .vertical)
                DatePicker("Started", selection: Binding(get: { manualStart }, set: {
                    manualStart = $0
                    if !manualEndEdited { manualEnd = $0.addingTimeInterval(900) }
                }), displayedComponents: [.date, .hourAndMinute])
                DatePicker("Ended", selection: Binding(get: { manualEnd }, set: {
                    manualEnd = $0; manualEndEdited = true
                }), displayedComponents: [.date, .hourAndMinute])
                Text("Times use your local timezone.").font(.caption)
                Button("Save session") {
                    model.perform { tracker in
                        guard let id = manualNonprofit else { throw TrackerError.invalidNonprofit }
                        try tracker.addSession(projectId: id, notes: manualNotes, start: manualStart, end: manualEnd, platform: "ios")
                        manualNotes = ""
                        manualStatus = "Session saved."
                    }
                }.disabled(manualNonprofit == nil || manualNotes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || manualEnd <= manualStart)
                if manualEnd <= manualStart { Text("End must be after start.").foregroundStyle(.red) }
                if model.state.nonprofits.isEmpty { Text("Add a nonprofit in Settings first.").font(.caption) }
                if let error = model.error { Text(error).foregroundStyle(.red) }
                if !manualStatus.isEmpty { Text(manualStatus).font(.caption) }
            }.padding(.top, 8)
        }.disabled(model.tracker == nil)
            .onAppear {
                if !manualDatesInitialized {
                    manualEnd = manualStart.addingTimeInterval(900)
                    manualDatesInitialized = true
                }
            }
    }
    private var settingsView: some View {
        NavigationStack {
            Form {
                Section("Nonprofits") {
                    TextField("New project", text: $newName)
                    Button("Add nonprofit") { model.perform { model.selected = try $0.addNonprofit(newName); newName = "" } }
                        .disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }.disabled(model.tracker == nil || model.state.active != nil)
                Section { manualSessionForm }
                Section("Data location") {
                    Button("Choose data folder…") { chooseFolderAfterSettings = true; settings = false }
                    Text(model.location).font(.caption)
                    Text("All changes are saved here. Use one device at a time.").font(.caption)
                }
                Text("Timing continues when the app closes. Reopen and press Stop to finish.").font(.caption)
                if let error = model.error { Text(error).foregroundStyle(.red) }
            }.navigationTitle("Settings")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { settings = false } } }

        }
    }
}
