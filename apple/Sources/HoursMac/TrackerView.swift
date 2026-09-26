import SwiftUI
import HoursCore

struct TrackerView: View {
    @Bindable var model: AppModel
    @State private var newName = ""
    @State private var settings = false
    @State private var editingSession: Session?
    private var active: Session? { model.state.active }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("Nonprofit Hours").font(.title2.bold())
                Spacer()
                Button("Settings") { settings.toggle() }
                    .popover(isPresented: $settings) { settingsView }
            }
            HStack(alignment: .bottom, spacing: 20) {
                Picker("Nonprofit", selection: $model.selected) {
                    Text("Choose a nonprofit").tag(nil as UUID?)
                    ForEach(model.state.nonprofits) { Text($0.name).tag(Optional($0.id)) }
                }.disabled(active != nil || model.tracker == nil)
                Button(action: model.toggleTracking) {
                    Text(active == nil ? "Start" : "Stop").font(.title2.bold()).frame(minWidth: 120).padding(8)
                }.buttonStyle(.borderedProminent).tint(active == nil ? .green : .red)
                    .disabled(model.tracker == nil || (active == nil && model.selected == nil))
            }
            if let active {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text("\(active.nonprofitName): \(elapsed(context.date.timeIntervalSince(active.startTimeUtc)))")
                        .font(.title2.monospacedDigit())
                }
            } else { Text("Ready when you are").foregroundStyle(.secondary) }
            TextField("What are you working on? (optional)", text: $model.notes).disabled(active != nil || model.tracker == nil)
            if model.state.nonprofits.isEmpty { Text("Add your first nonprofit in Settings to begin.").font(.caption) }
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
        .onChange(of: model.reportPeriod) { model.copyStatus = "" }
        .onChange(of: model.reportDate) { model.copyStatus = "" }
        .sheet(item: $editingSession) { SessionNotesEditor(session: $0, model: model) }
        .alert("Unable to complete action", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK") { model.error = nil }
        } message: { Text(model.error ?? "") }
    }
    private var history: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("History").font(.title2.bold())
            Text("Completed: \(Double(model.state.sessions.compactMap(\.durationSeconds).reduce(0, +)) / 3600, specifier: "%.2f") hours").foregroundStyle(.secondary)
            if model.state.sessions.isEmpty { Text("Sessions will appear here.").foregroundStyle(.secondary) }
            ForEach(model.state.sessions.reversed()) { session in
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(session.nonprofitName).font(.headline)
                        Text(session.startTimeUtc.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(.secondary)
                        Text(session.durationSeconds.map { elapsed(Double($0)) } ?? "In progress").monospacedDigit()
                        Text(session.notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "No notes" : session.notes)
                        if session.endTimeUtc != nil { Button("Edit notes") { editingSession = session } }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
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
    private var settingsView: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Settings").font(.title2)
            HStack {
                TextField("New nonprofit", text: $newName)
                Button("Add") { model.perform { model.selected = try $0.addNonprofit(newName); newName = "" } }
                    .disabled(newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }.disabled(active != nil || model.tracker == nil)
            Button("Data location…") { model.chooseDataLocation() }
            Text(model.dataLocation).font(.caption).textSelection(.enabled)
            Text("All changes are saved in this folder. Use one device at a time.").font(.caption)
            Button("Done") { settings = false }
        }.padding(20).frame(width: 360)
    }
    private func elapsed(_ seconds: Double) -> String {
        let value = max(0, Int(seconds))
        return String(format: "%02d:%02d:%02d", value / 3600, value % 3600 / 60, value % 60)
    }
}
