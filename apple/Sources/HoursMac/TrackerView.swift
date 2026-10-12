import SwiftUI
import HoursCore

struct TrackerView: View {
    @Bindable var model: AppModel
    @State private var newName = ""
    @State private var settings = false
    @State private var manualNonprofit: UUID?
    @State private var manualNotes = ""
    @State private var manualStart = Date().addingTimeInterval(-3600)
    @State private var manualEnd = Date()
    @State private var manualDatesInitialized = false
    @State private var manualEndEdited = false
    @State private var manualStatus = ""
    @State private var manualConfirmation: String?
    @State private var editingSession: Session?
    @State private var editingTimes: Session?
    private var active: Session? { model.state.active }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("Time is Clearly Kept").font(.title2.bold())
                Spacer()
                Button("Settings") { settings.toggle() }
                    .popover(isPresented: $settings) { settingsView }
            }
            if model.needsDataLocation {
                Text("Choose where to save tick.json to get started.")
                Button("Choose data folder…") { model.chooseDataLocation() }
            }
            HStack(alignment: .bottom, spacing: 20) {
                Picker("Project", selection: $model.selected) {
                    Text("Choose a project").tag(nil as UUID?)
                    ForEach(model.state.nonprofits) { Text($0.name).tag(Optional($0.id)) }
                }.disabled(active != nil || model.tracker == nil)
                Button(action: model.toggleTracking) {
                    Text(active == nil ? "Start" : "Stop").font(.title2.bold()).frame(minWidth: 120).padding(8)
                }.buttonStyle(.borderedProminent).tint(active == nil ? .green : .red)
                    .disabled(model.tracker == nil || (active == nil && model.selected == nil))
            }
            if let active {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text("\(active.project): \(elapsed(context.date.timeIntervalSince(active.startTimeUtc)))")
                        .font(.title2.monospacedDigit())
                }
            } else { Text("Ready when you are").foregroundStyle(.secondary) }
            TextField("What are you working on? (optional)", text: $model.notes).disabled(active != nil || model.tracker == nil)
            if model.state.nonprofits.isEmpty { Text("Add your first project in Settings.").font(.caption) }
            Divider()
            GeometryReader { geometry in
                ScrollView {
                    let layout = geometry.size.width >= 780 ? AnyLayout(HStackLayout(alignment: .top, spacing: 24)) : AnyLayout(VStackLayout(alignment: .leading, spacing: 24))
                    layout {
                        history.frame(maxWidth: .infinity, alignment: .topLeading)
                        report.frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                }
            }
        }.padding(24).frame(minWidth: 420, minHeight: 580)
        .task {
            if model.needsDataLocation && !model.promptedForDataLocation {
                model.promptedForDataLocation = true
                model.chooseDataLocation()
            }
        }
        .onChange(of: model.needsDataLocation) { wasNeeded, isNeeded in
            if wasNeeded && !isNeeded && model.state.nonprofits.isEmpty {
                settings = true
            }
        }
        .onChange(of: model.reportPeriod) { model.copyStatus = "" }
        .onChange(of: model.reportDate) { model.copyStatus = "" }
        .sheet(item: $editingSession) { SessionNotesEditor(session: $0, model: model) }
        .sheet(item: $editingTimes) { SessionTimesEditor(session: $0, model: model) }
        .alert("Unable to complete action", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK") { model.error = nil }
        } message: { Text(model.error ?? "") }
    }
    private var history: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("History").font(.title2.bold())
            Text("Completed: \(Double(model.state.sessions.compactMap(\.durationSeconds).reduce(0, +)) / 3600, specifier: "%.2f") hours").foregroundStyle(.secondary)
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
                                Text(session.startTimeUtc.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(.secondary)
                                Text(session.durationSeconds.map { elapsed(Double($0)) } ?? "In progress").monospacedDigit()
                                Text(session.notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "No notes" : session.notes)
                                if session.endTimeUtc != nil {
                                    HStack {
                                        Button("Edit notes") { editingSession = session }
                                        Button("Edit times") { editingTimes = session }
                                        if let seconds = session.durationSeconds, seconds >= 0, seconds < 60 {
                                            Button("Delete", role: .destructive) { model.perform { try $0.deleteSession(sessionId: session.sessionId) } }
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
                Picker("Period", selection: $model.reportPeriod) {
                    ForEach(ExportPeriod.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.segmented)
                DatePicker("Date in period", selection: $model.reportDate, displayedComponents: .date)
                Text("\(model.reportRange.start.formatted(date: .abbreviated, time: .omitted)) – \(model.reportRange.end.addingTimeInterval(-1).formatted(date: .abbreviated, time: .omitted)): \(model.reportCount) completed sessions").font(.caption)
                Text("Completed sessions by local start date. Weeks run Monday–Sunday.").font(.caption).foregroundStyle(.secondary)
                Text("Summary preview").font(.headline)
                Text(model.reportCount == 0 ? "No completed sessions in this period." : model.tracker?.clipboardText(range: model.reportRange) ?? "")
                    .font(.system(.body, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                HStack {
                    Button("Export CSV…") { model.export() }
                    Button("Copy summary") { model.copyReport() }
                }.disabled(model.reportCount == 0)
                Text(model.copyStatus).font(.caption)
            }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
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
                        try tracker.addSession(projectId: id, notes: manualNotes, start: manualStart, end: manualEnd, platform: "macos")
                        manualConfirmation = nil
                        manualNotes = ""
                        manualStatus = "Session saved."
                    }
                }.disabled(manualNonprofit == nil || manualNotes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || manualEnd <= manualStart)
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
        ScrollView {
        VStack(alignment: .leading, spacing: 14) {
            Text("Settings").font(.title2)
            HStack {
                TextField("New project", text: $newName)
                Button("Add project") { model.perform { model.selected = try $0.addNonprofit(newName); newName = "" } }
                    .disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }.disabled(active != nil || model.tracker == nil)
            manualSessionForm
            Button("Data location…") { model.chooseDataLocation() }
            Text(model.dataLocation).font(.caption).textSelection(.enabled)
            Text("All changes are saved in this folder. Use one device at a time.").font(.caption)
            Button("Done") { settings = false }
        }.padding(20).frame(width: 440)
        }.frame(maxHeight: 560)
    }
    private func elapsed(_ seconds: Double) -> String {
        let value = max(0, Int(seconds))
        return String(format: "%02d:%02d:%02d", value / 3600, value % 3600 / 60, value % 60)
    }
}
