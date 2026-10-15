import SwiftUI

/// Shared setup for iPhone, iPad and macOS. App registration is bundled, never entered by the user.
@MainActor public struct GoogleSheetsConnectView: View {
    private let connected: (SheetsStore) async throws -> Void
    @State private var account = GoogleAccount()
    @State private var files: [GoogleSpreadsheet] = []
    @State private var selected = ""
    @State private var name = "Time is Clearly Kept"
    @State private var signedIn = false
    @State private var busy = false
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss
    public init(connected: @escaping (SheetsStore) async throws -> Void) { self.connected = connected }
    public var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Google Sheets").font(.title2.bold())
            Text("Sign in, then create a spreadsheet or open one Tick can access. Internet is required.")
            if signedIn {
                Picker("Spreadsheet", selection: $selected) {
                    Text("Create a new spreadsheet").tag("")
                    ForEach(files) { Text($0.name).tag($0.id) }
                }
                if selected.isEmpty { TextField("Spreadsheet name", text: $name) }
                Text("New spreadsheets receive your current data. Existing Tick data opens without merging. Use one device at a time.").font(.caption)
                Button("Connect") {
                    busy = true; error = nil
                    let api = GoogleSheetsAPI(account: account), selected = selected, name = name
                    let existingName = files.first(where: { $0.id == selected })?.name ?? name
                    Task {
                        do {
                            let store = try await Task.detached {
                                if selected.isEmpty { return try api.create(name: name) }
                                return try SheetsStore(configuration: SheetsConfiguration(sheetID: selected, spreadsheetName: existingName), api: api)
                            }.value
                            try await connected(store)
                            dismiss()
                        } catch { self.error = error.localizedDescription }
                        busy = false
                    }
                }.buttonStyle(.borderedProminent)
                Button("Sign out of Google on this device") {
                    do { try account.signOut(); signedIn = false; files = []; selected = "" }
                    catch { self.error = error.localizedDescription }
                }
            } else {
                Button("Sign in with Google") {
                    busy = true; error = nil
                    Task {
                        do {
                            try await account.signIn()
                            let api = GoogleSheetsAPI(account: account)
                            files = try await Task.detached { try api.spreadsheets() }.value
                            signedIn = true
                        } catch { self.error = error.localizedDescription }
                        busy = false
                    }
                }.buttonStyle(.borderedProminent)
            }
            if busy { ProgressView("Connecting to Google…") }
            if let error { Text(error).foregroundStyle(.red).textSelection(.enabled) }
            Button("Cancel") { dismiss() }
        }.padding(24).frame(minWidth: 280, idealWidth: 420).disabled(busy).interactiveDismissDisabled(busy)
    }
}
