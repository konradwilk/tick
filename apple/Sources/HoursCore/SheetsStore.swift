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
    private var metadata: [String: Any] = [:]
    public init(configuration: SheetsConfiguration, api: GoogleSheetsAPI = GoogleSheetsAPI()) throws { self.configuration = configuration; self.api = api }
    private var base: String { "https://sheets.googleapis.com/v4/spreadsheets/" + configuration.sheetID }
    private func rows(_ tab: String) throws -> [[Any]] { try api.request("GET", base + "/values/" + tab)["values"] as? [[Any]] ?? [] }
    private func read() throws -> (TrackerState?, String?) {
        let meta = try api.request("GET", base + "?fields=sheets.properties,properties.title")
        metadata = meta
        let tabs = (meta["sheets"] as? [[String: Any]] ?? []).compactMap { ($0["properties"] as? [String: Any])?["title"] as? String }
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
        let bytes = try PortableData.encode(state)
        let (_, latest) = try read()
        guard latest == revision else { throw SheetsError.message("Data changed on another device. Reload before saving.") }
        if !hasLog {
            _ = try api.request("POST", base + ":batchUpdate", ["requests": [["addSheet": ["properties": ["title": "TickLog", "gridProperties": ["rowCount": 1000, "columnCount": 6]]]]]])
            _ = try read()
        }
        let id = UUID().uuidString
        let characters = Array(String(decoding: bytes, as: UTF8.self).unicodeScalars)
        let chunks = stride(from: 0, to: characters.count, by: 20000).map { String(String.UnicodeScalarView(characters[$0..<min($0+20000, characters.count)])) }
        guard chunks.count <= 1000 else { throw SheetsError.message("This dataset is too large for a Tick revision in Google Sheets. Use Local file storage.") }
        let values: [[Any]] = chunks.enumerated().map { ["tick-log-v1", id, revision ?? "", $0.offset, chunks.count, $0.element] }
        var requests = try tableRequests(bytes)
        let tabs = metadata["sheets"] as? [[String: Any]] ?? []
        let log = tabs.compactMap { $0["properties"] as? [String: Any] }.first { $0["title"] as? String == "TickLog" }!
        requests.append(["appendCells": ["sheetId": log["sheetId"] as? Int ?? 0, "rows": Self.cells(values), "fields": "userEnteredValue"]])
        _ = try api.request("POST", base + ":batchUpdate", ["requests": requests])
        let (saved, confirmed) = try read()
        guard confirmed == id, let saved, try PortableData.encode(saved) == bytes else { throw SheetsError.message("Save could not be confirmed. Reload before retrying.") }
        revision = id
    }

    private static func cells(_ rows: [[Any]]) -> [[String: Any]] {
        rows.map { ["values": $0.map { value -> [String: Any] in
            if let text = value as? String { return ["userEnteredValue": ["stringValue": String(text.unicodeScalars.prefix(20000))]] }
            return ["userEnteredValue": ["numberValue": value]]
        }] }
    }
    private func tableRequests(_ bytes: Data) throws -> [[String: Any]] {
        let data = try JSONSerialization.jsonObject(with: bytes) as! [String: Any]
        let projects = data["nonprofits"] as! [[String: Any]], sessions = data["sessions"] as! [[String: Any]]
        let names = Dictionary(uniqueKeysWithValues: projects.map { ($0["id"] as! String, $0["name"] as! String) })
        var totals: [String: (Double, Int)] = [:]
        var rows: [[Any]] = [["Project", "Started (UTC)", "Ended (UTC)", "Duration", "Hours", "Notes", "Status", "Platform"]]
        for session in sessions.sorted(by: { ($0["startTimeUtc"] as! String) < ($1["startTimeUtc"] as! String) }) {
            let key = session["projectId"] as! String, seconds = session["durationSeconds"] as? Double
            let n = Int(seconds ?? 0), ended = session["endTimeUtc"] as? String
            let duration = seconds == nil ? "" : String(format: "%d:%02d:%02d", n/3600, n/60%60, n%60)
            rows.append([names[key] ?? session["project"] as! String, String((session["startTimeUtc"] as! String).prefix(19)).replacingOccurrences(of: "T", with: " "), ended.map { String($0.prefix(19)).replacingOccurrences(of: "T", with: " ") } ?? "", duration, seconds.map { $0/3600 as Any } ?? "", session["notes"]!, ended == nil ? "Running" : "Completed", session["platform"]!])
            let old = totals[key] ?? (0, 0); totals[key] = (old.0 + (seconds ?? 0)/3600, old.1 + 1)
        }
        let summary: [[Any]] = [["Project", "Total hours", "Sessions"]] + projects.map { p in let t = totals[p["id"] as! String] ?? (0, 0); return [p["name"]!, t.0, t.1] }
        let tabs = (metadata["sheets"] as? [[String: Any]] ?? []).compactMap { $0["properties"] as? [String: Any] }
        var used = Set(tabs.map { $0["sheetId"] as? Int ?? 0 }), requests: [[String: Any]] = []
        let styleText = #"[[{"updateSheetProperties":{"properties":{"sheetId":0,"index":0,"hidden":false,"gridProperties":{"frozenRowCount":1}},"fields":"index,hidden,gridProperties.frozenRowCount"}},{"updateCells":{"range":{"sheetId":0},"rows":[],"fields":"userEnteredValue,note"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.92,"green":0.93,"blue":0.94},"textFormat":{"bold":true,"foregroundColor":{"red":0,"green":0,"blue":0}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":1},"cell":{"userEnteredFormat":{"verticalAlignment":"TOP","wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"updateDimensionProperties":{"range":{"sheetId":0,"dimension":"COLUMNS","startIndex":0,"endIndex":8},"properties":{"pixelSize":160},"fields":"pixelSize"}},{"setBasicFilter":{"filter":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1,"startColumnIndex":0,"endColumnIndex":8}}}}],[{"updateSheetProperties":{"properties":{"sheetId":0,"index":1,"hidden":false,"gridProperties":{"frozenRowCount":1}},"fields":"index,hidden,gridProperties.frozenRowCount"}},{"updateCells":{"range":{"sheetId":0},"rows":[],"fields":"userEnteredValue,note"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.92,"green":0.93,"blue":0.94},"textFormat":{"bold":true,"foregroundColor":{"red":0,"green":0,"blue":0}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":1},"cell":{"userEnteredFormat":{"verticalAlignment":"TOP","wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"updateDimensionProperties":{"range":{"sheetId":0,"dimension":"COLUMNS","startIndex":0,"endIndex":3},"properties":{"pixelSize":160},"fields":"pixelSize"}},{"setBasicFilter":{"filter":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1,"startColumnIndex":0,"endColumnIndex":3}}}}]]"#
        for (index, values) in [rows, summary].enumerated() {
            let title = index == 0 ? "Sessions" : "Projects", tab = tabs.first { $0["title"] as? String == title }
            var id = tab?["sheetId"] as? Int ?? (174001 + index)
            if tab == nil {
                while used.contains(id) { id += 1 }; used.insert(id)
                requests.append(["addSheet": ["properties": ["sheetId": id, "title": title, "gridProperties": ["rowCount": max(1000, values.count), "columnCount": values[0].count]]]])
            }
            let size = max((tab?["gridProperties"] as? [String: Any])?["rowCount"] as? Int ?? 1000, values.count, 2)
            requests.append(["updateSheetProperties": ["properties": ["sheetId": id, "gridProperties": ["rowCount": size]], "fields": "gridProperties.rowCount"]])
            let styles = try JSONSerialization.jsonObject(with: Data(styleText.utf8)) as! [[[String: Any]]]
            var parts = styles[index]
            for i in parts.indices {
                let name = parts[i].keys.first!; var payload = parts[i][name] as! [String: Any]
                if var props = payload["properties"] as? [String: Any], props["sheetId"] != nil { props["sheetId"] = id; payload["properties"] = props }
                if var range = payload["range"] as? [String: Any] { range["sheetId"] = id; payload["range"] = range }
                if var filter = payload["filter"] as? [String: Any], var range = filter["range"] as? [String: Any] { range["sheetId"] = id; range["endRowIndex"] = max(2, values.count); filter["range"] = range; payload["filter"] = filter }
                if name == "updateCells" { var cells = Self.cells(values); var header = cells[0]["values"] as! [[String: Any]]; header[0]["note"] = "Generated by Tick. Edit projects and sessions in Tick; these tables refresh on every save."; cells[0]["values"] = header; payload["rows"] = cells }
                parts[i][name] = payload
            }
            requests += parts
            let column = index == 0 ? 4 : 1
            requests.append(["repeatCell": ["range": ["sheetId": id, "startRowIndex": 1, "startColumnIndex": column, "endColumnIndex": column+1], "cell": ["userEnteredFormat": ["numberFormat": ["type": "NUMBER", "pattern": "0.00"]]], "fields": "userEnteredFormat.numberFormat"]])
            if index == 0 { requests.append(["updateDimensionProperties": ["range": ["sheetId": id, "dimension": "COLUMNS", "startIndex": 5, "endIndex": 6], "properties": ["pixelSize": 420], "fields": "pixelSize"]]) }
        }
        for tab in tabs where ["TickLog", "TickData"].contains(tab["title"] as? String ?? "") { requests.append(["updateSheetProperties": ["properties": ["sheetId": tab["sheetId"] as? Int ?? 0, "hidden": true], "fields": "hidden"]]) }
        return requests
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
