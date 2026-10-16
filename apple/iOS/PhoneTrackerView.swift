import SwiftUI
import UniformTypeIdentifiers
import UIKit

@MainActor struct PhoneTrackerView: View {
    @Bindable var model: PhoneModel
    @State private var newName = ""
    @State private var settings = false
    @State private var connectingGoogle = false
    @State private var explainingDataLocation = false
    @State private var manualNonprofit: UUID?
    @State private var manualNotes = ""
    @State private var manualStart = Date().addingTimeInterval(-3600)
    @State private var manualEnd = Date()
    @State private var manualDatesInitialized = false
    @State private var manualEndEdited = false
    @State private var manualStatus = ""
    @State private var manualConfirmation: String?
    @State private var period = ExportPeriod.monthly
    @State private var date = Date()
    @State private var choosingFolder = false
    @State private var selectingFile = false
    @State private var chooseFolderAfterSettings = false
    @State private var exporting = false
    @State private var document = CSVDocument(text: "")
    @State private var filename = "tick"
    @State private var copyStatus = ""
    @State private var editing: Session?
    @State private var editingTimes: Session?
    private var range: ExportRange { ExportRange(period: period, date: date) }
    private var count: Int {
        model.state.sessions.filter { $0.endTimeUtc != nil && $0.startTimeUtc >= range.start && $0.startTimeUtc < range.end }.count
    }
    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                if model.needsDataLocation {
                    Text("Choose Local file (tick.json) for offline storage in a folder, or Google Sheets to share data across devices over the internet. You can switch in Settings. An empty destination receives your current data; an existing destination is opened without merging.")
                    Button("Local file (tick.json)…") { selectingFile = false; choosingFolder = true }
            Button("Google Sheets…") { settings = true }
                    Button("Open tick.json…") { selectingFile = true; choosingFolder = true }
                    Text("For OneDrive, open an existing tick.json file.").font(.caption)
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
                explainingDataLocation = true
            }
        }
        .alert("Choose where to keep your data", isPresented: $explainingDataLocation) {
            Button("Local file (tick.json)…") { selectingFile = false; choosingFolder = true }
            Button("Google Sheets…") { settings = true }
            Button("Open tick.json…") { selectingFile = true; choosingFolder = true }
            Button("Later", role: .cancel) { }
        } message: { Text("Choose Local file (tick.json) for offline storage in a folder, or Google Sheets to share data across devices over the internet. You can switch in Settings. An empty destination receives your current data; an existing destination is opened without merging. For OneDrive, open an existing tick.json file.") }
        .fileImporter(isPresented: $choosingFolder, allowedContentTypes: selectingFile ? [.json] : [.folder]) { result in
            switch result {
            case .success(let url):
                if selectingFile { model.selectFile(url) }
                else { model.selectFolder(url) }
            case .failure(let error): model.error = error.localizedDescription
            }
        }
        .onChange(of: model.needsDataLocation) { wasNeeded, isNeeded in
            if wasNeeded && !isNeeded && model.state.nonprofits.isEmpty {
                settings = true
            }
        }
        .onChange(of: period) { copyStatus = "" }
        .onChange(of: date) { copyStatus = "" }
        .onChange(of: model.state.sessions.map { $0.updatedAtUtc }) { copyStatus = "" }
        .sheet(isPresented: $settings, onDismiss: {
            if chooseFolderAfterSettings { chooseFolderAfterSettings = false; choosingFolder = true }
        }) { settingsView }
        .fileExporter(isPresented: $exporting, document: document, contentType: .commaSeparatedText, defaultFilename: filename) { result in
            if case .failure(let error) = result { model.error = error.localizedDescription }
        }
        .sheet(item: $editing) { PhoneNotesEditor(session: $0, model: model) }
        .sheet(item: $editingTimes) { PhoneTimesEditor(session: $0, model: model) }
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
            if model.state.nonprofits.isEmpty { Button("Add your first project in Settings.") { settings = true }.font(.caption) }
        }
    }
    private var history: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("History").font(.title2.bold())
            Text("Completed: \(Double(model.state.sessions.compactMap(\.durationSeconds).reduce(0, +)) / 3600, specifier: "%.2f") hours").font(.subheadline)
            if model.state.sessions.isEmpty { Text("Sessions will appear here.").foregroundStyle(.secondary) }
            ForEach(historyWeeks(sessions: model.state.sessions)) { week in
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 12) {
                        Text(week.label).font(.subheadline.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
                        Rectangle().fill(.separator).frame(maxWidth: .infinity).frame(height: 1)
                    }.accessibilityAddTraits(.isHeader)
                    ForEach(week.sessions) { session in
                        GroupBox {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(session.project).font(.headline)
                                Text(session.startTimeUtc.formatted(date: .abbreviated, time: .shortened)).font(.caption)
                                Text(session.durationSeconds.map(duration) ?? "In progress").monospacedDigit()
                                Text(session.notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "No notes" : session.notes)
                                if session.endTimeUtc != nil {
                                    HStack {
                                        Button("Edit notes") { editing = session }
                                        Button("Edit times") { editingTimes = session }
                                        if let seconds = session.durationSeconds, seconds >= 0, seconds < 60 {
                                            Button("Delete", role: .destructive) { model.perform { try $0.deleteSession(sessionId: session.sessionId); copyStatus = "" } }
                                        }
                                    }
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }.padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(.separator, lineWidth: 1))
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
                Picker("Project", selection: Binding(get: { manualNonprofit }, set: {
                    manualNonprofit = $0
                    ManualProjectPreference.remember($0)
                })) {
                    Text("Choose a project").tag(nil as UUID?)
                    ForEach(model.state.nonprofits) { Text($0.name).tag(Optional($0.id)) }
                }
                // These controls share a Form row; avoid a navigation picker's row-wide tap target.
                .pickerStyle(.menu)
                TextField("What did you work on?", text: $manualNotes, axis: .vertical)
                DatePicker("Started", selection: Binding(get: { manualStart }, set: {
                    manualStart = $0
                    if !manualEndEdited { manualEnd = $0.addingTimeInterval(900) }
                }), displayedComponents: [.date, .hourAndMinute])
                DatePicker("Ended", selection: Binding(get: { manualEnd }, set: {
                    manualEnd = $0; manualEndEdited = true
                }), displayedComponents: [.date, .hourAndMinute])
                Text("Times use your local timezone.").font(.caption)
                let conflicts = sessionConflicts(sessions: model.state.sessions, start: manualStart, end: manualEnd)
                if !conflicts.isEmpty {
                    Text("Time overlap detected").foregroundStyle(.orange).bold()
                    ForEach(conflicts) { conflict in Text(conflict.description).font(.caption) }
                }
                Button(manualConfirmation == nil ? "Save session" : "Save anyway") {
                    // Reload before checking overlap so manual entry uses shared history too.
                    guard let tracker = model.tracker else { return }
                    do {
                        try tracker.reload()
                        model.state = tracker.state
                    } catch {
                        model.error = "Could not reload saved hours. " + error.localizedDescription
                        return
                    }
                    let latest = sessionConflicts(sessions: model.tracker?.state.sessions ?? [], start: manualStart, end: manualEnd)
                    let signature = "\(manualStart.timeIntervalSince1970)|\(manualEnd.timeIntervalSince1970)|\(manualNotes)|\(String(describing: manualNonprofit))|" + latest.map { "\($0.id)|\($0.session.startTimeUtc)|\(String(describing: $0.session.endTimeUtc))" }.joined(separator: ";")
                    if !latest.isEmpty && manualConfirmation != signature {
                        manualConfirmation = signature
                        manualStatus = "Review the conflicts above. Choose Save anyway to confirm intentional overlap."
                        return
                    }
                    model.perform { tracker in
                        guard let id = manualNonprofit else { throw TrackerError.invalidNonprofit }
                        try tracker.addSession(projectId: id, notes: manualNotes, start: manualStart, end: manualEnd, platform: "ios")
                        let savedEnd = manualEnd
                        manualStart = savedEnd.addingTimeInterval(60)
                        manualEnd = savedEnd.addingTimeInterval(900)
                        manualEndEdited = false
                        manualConfirmation = nil
                        manualNotes = ""
                        manualStatus = "Session saved."
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(manualNonprofit == nil || manualNotes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || manualEnd <= manualStart)
                if manualEnd <= manualStart { Text("End must be after start.").foregroundStyle(.red) }
                if model.state.nonprofits.isEmpty { Text("Add a project in Settings first.").font(.caption) }
                if let error = model.error { Text(error).foregroundStyle(.red) }
                if !manualStatus.isEmpty { Text(manualStatus).font(.caption) }
            }.padding(.top, 8)
        }.disabled(model.tracker == nil)
            .onChange(of: manualStart) { _, _ in manualConfirmation = nil; manualStatus = "" }
            .onChange(of: manualEnd) { _, _ in manualConfirmation = nil; manualStatus = "" }
            .onChange(of: manualNotes) { _, _ in manualConfirmation = nil }
            .onChange(of: manualNonprofit) { _, _ in manualConfirmation = nil }
            .onAppear {
                manualNonprofit = ManualProjectPreference.selection(projectIDs: model.state.nonprofits.map(\.id))
                if !manualDatesInitialized {
                    manualEnd = manualStart.addingTimeInterval(900)
                    manualDatesInitialized = true
                }
            }
    }
    private var settingsView: some View {
        NavigationStack {
            Form {
                Section("Projects") {
                    TextField("New project", text: $newName)
                    Button("Add project") { model.perform { model.selected = try $0.addNonprofit(newName); newName = "" } }
                        .disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }.disabled(model.tracker == nil || model.state.active != nil)
                Section { manualSessionForm }
                Section("Data storage") {
                    Text("Local file: works offline. Google Sheets: shared online storage.").font(.caption)
                    Text("Google Sheets requires internet access and Google sign-in. After signing in, create a spreadsheet or open your existing Tick data.").font(.caption)
                    StorageOptionButton("Sign in with Google…", symbol: "cloud", isActive: model.tracker?.usesGoogleSheets == true) { connectingGoogle = true }

                    StorageOptionButton("Local file (tick.json)…", symbol: "doc", isActive: model.tracker?.usesGoogleSheets == false) { selectingFile = false; chooseFolderAfterSettings = true; settings = false }
                    Button("Open tick.json…") { selectingFile = true; chooseFolderAfterSettings = true; settings = false }
                    Text("For OneDrive, open an existing tick.json file.").font(.caption)
                    Text(model.location).font(.caption)
                    Text("Use one device at a time; reload after a conflict.").font(.caption)
                }
                Text("Timing continues when the app closes. Reopen and press Stop to finish.").font(.caption)
                Text("This is version \(BuildVersion.current)").font(.caption).textSelection(.enabled)
                if let error = model.error { Text(error).foregroundStyle(.red) }
            }.navigationTitle("Settings")
                .sheet(isPresented: $connectingGoogle) { GoogleSheetsConnectView { try await model.connectSheets(store: $0) } }
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { settings = false } } }

        }
    }
}
