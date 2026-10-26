import Foundation

public struct SheetsConfiguration: Codable, Sendable {
    public let sheetID: String
    public var spreadsheetName: String
    public init(sheetID: String, spreadsheetName: String = "Time is Clearly Kept") throws {
        guard sheetID.range(of: #"^[A-Za-z0-9_-]+$"#, options: .regularExpression) != nil else { throw SheetsError.message("Choose a spreadsheet used by Tick.") }
        self.sheetID = sheetID; self.spreadsheetName = spreadsheetName
    }
}
public struct GoogleSpreadsheet: Identifiable, Sendable { public let id: String; public let name: String }
public final class GoogleSheetsAPI: @unchecked Sendable {
    private let account: GoogleAccount
    private let transport: ((String, String, [String: Any]?) throws -> [String: Any])?
    public init(account: GoogleAccount = GoogleAccount(), transport: ((String, String, [String: Any]?) throws -> [String: Any])? = nil) { self.account = account; self.transport = transport }
    public func request(_ method: String, _ url: String, _ body: [String: Any]? = nil) throws -> [String: Any] {
        if let transport { return try transport(method, url, body) }
        guard let url = URL(string: url) else { throw SheetsError.message("Invalid Google request.") }
        var request = URLRequest(url: url); request.httpMethod = method; request.timeoutInterval = 30
        request.setValue("Bearer " + (try account.accessToken()), forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body { request.httpBody = try JSONSerialization.data(withJSONObject: body) }
        guard let response = try JSONSerialization.jsonObject(with: GoogleHTTP.send(request)) as? [String: Any] else { throw SheetsError.message("Invalid Google Sheets response.") }
        return response
    }
    public func spreadsheets() throws -> [GoogleSpreadsheet] {
        var files: [GoogleSpreadsheet] = [], page: String?
        repeat {
            var query = URLComponents(string: "https://www.googleapis.com/drive/v3/files")!
            query.queryItems = [URLQueryItem(name: "q", value: "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"), URLQueryItem(name: "fields", value: "nextPageToken,files(id,name)"), URLQueryItem(name: "pageSize", value: "100")]
            if let page { query.queryItems!.append(URLQueryItem(name: "pageToken", value: page)) }
            let response = try request("GET", query.url!.absoluteString)
            for file in response["files"] as? [[String: String]] ?? [] { if let id = file["id"], let name = file["name"] { files.append(GoogleSpreadsheet(id: id, name: name)) } }
            page = response["nextPageToken"] as? String
        } while page != nil
        return files.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }
    public func create(name: String) throws -> SheetsStore {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.count <= 200 else { throw SheetsError.message("Enter a spreadsheet name (1–200 characters).") }
        let result = try request("POST", "https://sheets.googleapis.com/v4/spreadsheets", ["properties": ["title": name], "sheets": [["properties": ["title": "TickLog", "gridProperties": ["rowCount": 1000, "columnCount": 6]]]]])
        guard let id = result["spreadsheetId"] as? String else { throw SheetsError.message("Could not create the spreadsheet.") }
        return try SheetsStore(configuration: SheetsConfiguration(sheetID: id, spreadsheetName: name), api: self)
    }
}
public final class SheetsStore: @unchecked Sendable {
    public let configuration: SheetsConfiguration
    private let api: GoogleSheetsAPI
    private var revision: String?
    private var hasLog = false
    private var rowStore: SheetsRows?
    private var metadata: [String: Any] = [:]
    public init(configuration: SheetsConfiguration, api: GoogleSheetsAPI = GoogleSheetsAPI()) throws { self.configuration = configuration; self.api = api }
    private var base: String { "https://sheets.googleapis.com/v4/spreadsheets/" + configuration.sheetID }
    private func rows(_ tab: String) throws -> [[Any]] { try api.request("GET", base + "/values/" + tab)["values"] as? [[Any]] ?? [] }
    private func read() throws -> (TrackerState?, String?) {
        if let rowStore { let result = try rowStore.read(); return (result.0, result.1) }
        let meta = try api.request("GET", base + "?fields=sheets.properties,properties.title")
        metadata = meta
        let tabs = (meta["sheets"] as? [[String: Any]] ?? []).compactMap { ($0["properties"] as? [String: Any])?["title"] as? String }
        if tabs.contains("TickMeta") {
            let rows = SheetsRows(api: api, base: base, metadata: meta); rowStore = rows
            let result = try rows.read(); return (result.0, result.1)
        }
        hasLog = tabs.contains("TickLog")
        if hasLog {
            let values = try rows("TickLog!A:F")
            if !values.isEmpty { return try Self.decodeLog(values) }
        }
        if tabs.contains("TickData") {
            let values = try rows("TickData!A1:A1002")
            if !values.isEmpty {
                guard values.count > 2, let first = values[0].first, let countText = values[1].first, let count = Int(String(describing: countText)), count > 0, count <= 1000, values.count >= count + 2 else { throw SheetsError.message("Invalid previous Tick dataset.") }
                let text = values[2..<(count+2)].compactMap { $0.first as? String }.joined()
                return (try PortableData.decode(Data(text.utf8)), String(describing: first))
            }
        }
        guard tabs.allSatisfy({ ["TickLog", "TickData"].contains($0) }) else { throw SheetsError.message("This spreadsheet has no Tick dataset. Create a new Tick spreadsheet instead.") }
        return (nil, nil)
    }
    public func load(requireExisting: Bool = true, connect: Bool = false) throws -> TrackerState? {
        let (state, latest) = try read()
        if state == nil && requireExisting { throw SheetsError.message("The Tick dataset is missing. Reconnect in Settings.") }
        revision = latest; return state
    }
    public func save(_ state: TrackerState) throws {
        if let rowStore {
            revision = try rowStore.save(state, expected: revision, initializing: false)
            return
        }
        let (_, latest) = try read()
        guard latest == revision else { throw SheetsError.message("Data changed on another device. Reload before saving.") }
        if let rowStore { revision = try rowStore.save(state, expected: revision, initializing: false); return }
        let rows = SheetsRows(api: api, base: base, metadata: metadata)
        // Retain the engine even after an ambiguous response, so retries validate row storage.
        rowStore = rows
        revision = try rows.save(state, expected: revision, initializing: true)
    }

    static func decodeLog(_ rows: [[Any]]) throws -> (TrackerState?, String?) {
        var position = 0, latest: String?, state: TrackerState?, seen = Set<String>()
        func invalid() -> SheetsError { .message("Invalid or incomplete Tick history. Keep the spreadsheet for recovery.") }
        while position < rows.count {
            let row = rows[position]
            guard row.count == 6, row[0] as? String == "tick-log-v1", let id = row[1] as? String, !id.isEmpty, !seen.contains(id), let parent = row[2] as? String, let count = Int(String(describing: row[4])), count > 0, count <= 1000, position+count <= rows.count else { throw invalid() }
            if let latest, parent != latest { throw SheetsError.message("Concurrent Google Sheets changes detected. Both versions are preserved in TickLog; recover before continuing.") }
            var text = ""
            for index in 0..<count {
                let chunk = rows[position+index]
                guard chunk.count == 6, chunk[0] as? String == "tick-log-v1", chunk[1] as? String == id, chunk[2] as? String == parent, Int(String(describing: chunk[3])) == index, Int(String(describing: chunk[4])) == count, let part = chunk[5] as? String else { throw invalid() }
                text += part
            }
            state = try PortableData.decode(Data(text.utf8)); latest = id; seen.insert(id); position += count
        }
        return (state, latest)
    }
}
