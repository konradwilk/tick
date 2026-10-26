import Foundation

/// Mutable entity rows plus an append-only journal of changed entities for recovery.
/// Protocol is shared with Windows, Android and Linux; never change column offsets independently.
final class SheetsRows {
    private let api: GoogleSheetsAPI
    private let base: String
    private var metadata: [String: Any]
    private struct Record { let index: Int; let row: [Any]; let payload: [String: Any]; let deleted: String }
    private var records: [String: [String: Record]] = [:]
    private var logCount = 0
    init(api: GoogleSheetsAPI, base: String, metadata: [String: Any]) { self.api = api; self.base = base; self.metadata = metadata }
    private func fail(_ text: String = "Invalid Tick row storage. Reload before saving.") -> SheetsError { .message(text) }
    private func json(_ object: Any) throws -> String { String(decoding: try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .fragmentsAllowed]), as: UTF8.self) }
    private func equal(_ a: Any, _ b: Any) -> Bool { (try? json(a)) == (try? json(b)) }
    private func chunks(_ text: String) throws -> [String] {
        let scalars = Array(text.unicodeScalars)
        let values = stride(from: 0, to: scalars.count, by: 20000).map { String(String.UnicodeScalarView(scalars[$0..<min($0+20000, scalars.count)])) }
        guard !values.isEmpty, values.count <= 1000 else { throw fail("This Tick row is too large. Use Local file storage.") }
        return values
    }
    private var tabs: [[String: Any]] { (metadata["sheets"] as? [[String: Any]] ?? []).compactMap { $0["properties"] as? [String: Any] } }
    private func sheet(_ title: String) throws -> [String: Any] { guard let tab = tabs.first(where: { $0["title"] as? String == title }) else { throw fail() }; return tab }
    private func cells(_ rows: [[Any]]) -> [[String: Any]] { rows.map { row in ["values": row.map { value in ["userEnteredValue": [value is String ? "stringValue" : "numberValue": value]] }] } }
    private func update(_ title: String, _ index: Int, _ rows: [[Any]], width: Int? = nil) throws -> [String: Any] {
        ["updateCells": ["range": ["sheetId": try sheet(title)["sheetId"] as? Int ?? 0, "startRowIndex": index, "endRowIndex": index+rows.count, "startColumnIndex": 0, "endColumnIndex": width ?? rows.map(\.count).max()!], "rows": cells(rows), "fields": "userEnteredValue"]]
    }
    func read() throws -> (TrackerState, String?) {
        let ranges = ["TickMeta!A1:B1", "Sessions", "Projects", "TickChanges!A:D"]
        var url = URLComponents(string: base + "/values:batchGet")!
        url.queryItems = ranges.map { URLQueryItem(name: "ranges", value: $0) } + [URLQueryItem(name: "valueRenderOption", value: "UNFORMATTED_VALUE")]
        guard let values = try api.request("GET", url.url!.absoluteString)["valueRanges"] as? [[String: Any]], values.count == 4 else { throw fail() }
        let rows = values.map { $0["values"] as? [[Any]] ?? [] }
        guard rows[0].count == 1, rows[0][0].count == 2, rows[0][0][0] as? String == "tick-rows-v1", let text = rows[0][0][1] as? String,
              var root = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else { throw fail() }
        var next: [String: [String: Record]] = [:]
        for (title, values, offset, key) in [("Sessions", rows[1], 8, "sessionId"), ("Projects", rows[2], 3, "id")] {
            guard let header = values.first, header.count >= offset+4, equal(Array(header[offset..<offset+4]), ["Tick ID", "Version", "Deleted", "Chunks"]) else { throw fail() }
            var entities: [String: Record] = [:]
            for (index, row) in values.enumerated().dropFirst() where !row.isEmpty {
                guard row.count >= offset+5, let id = row[offset] as? String, !id.isEmpty, let version = row[offset+1] as? String, !version.isEmpty,
                      let deleted = row[offset+2] as? String, ["0", "1"].contains(deleted), let count = Int(String(describing: row[offset+3])), (1...1000).contains(count), row.count == offset+4+count,
                      entities[id.lowercased()] == nil else { throw fail() }
                let parts = row.dropFirst(offset+4).compactMap { $0 as? String }
                guard parts.count == count, let payload = try JSONSerialization.jsonObject(with: Data(parts.joined().utf8)) as? [String: Any], (payload[key] as? String)?.lowercased() == id.lowercased() else { throw fail() }
                entities[id.lowercased()] = Record(index: index, row: row, payload: payload, deleted: deleted)
            }
            next[title] = entities
        }
        var latest: String?, position = 0
        var seen = Set<String>()
        let changes = rows[3]
        guard !changes.isEmpty else { throw fail("The Tick change journal is missing. Keep this spreadsheet for recovery.") }
        while position < changes.count {
            let row = changes[position]
            guard row.count == 4, let id = row[0] as? String, !id.isEmpty, seen.insert(id).inserted, let parent = row[1] as? String, parent == (latest ?? ""),
                  let count = Int(String(describing: row[3])), (1...1000).contains(count), position+count <= changes.count else { throw fail("Concurrent Google Sheets changes detected. Both changes remain in TickChanges; recover before continuing.") }
            for n in 0..<count { guard equal(changes[position+n], [id, parent, n, count]) else { throw fail() } }
            latest = id; position += count
        }
        for (title, key) in [("Sessions", "sessions"), ("Projects", "nonprofits")] {
            root[key] = next[title]!.values.sorted { $0.index < $1.index }.filter { $0.deleted == "0" }.map(\.payload)
        }
        let state = try PortableData.decode(JSONSerialization.data(withJSONObject: root))
        let canonical = try JSONSerialization.jsonObject(with: PortableData.encode(state)) as! [String: Any]
        for (title, field, key) in [("Sessions", "sessions", "sessionId"), ("Projects", "nonprofits", "id")] {
            for payload in canonical[field] as! [[String: Any]] {
                let id = (payload[key] as! String).lowercased(), old = next[title]![(payload[key] as! String).lowercased()]!
                next[title]![id] = Record(index: old.index, row: old.row, payload: payload, deleted: old.deleted)
            }
        }
        records = next; logCount = changes.count
        return (state, latest)
    }
    private func initialize(_ state: TrackerState) throws -> [[String: Any]] {
        var properties = tabs, used = Set(tabs.compactMap { $0["sheetId"] as? Int }), requests: [[String: Any]] = []
        for title in ["TickLog", "TickData"] {
            if let old = properties.first(where: { $0["title"] as? String == title }) {
                guard !properties.contains(where: { $0["title"] as? String == title+"Backup" }) else { throw fail("A Tick migration backup already exists. Keep this spreadsheet for recovery.") }
                requests.append(["updateSheetProperties": ["properties": ["sheetId": old["sheetId"] as? Int ?? 0, "title": title+"Backup", "hidden": true], "fields": "title,hidden"]])
            }
        }
        for (index, title) in ["Sessions", "Projects", "TickMeta", "TickChanges"].enumerated() where !properties.contains(where: { $0["title"] as? String == title }) {
            var id = 174001+index; while used.contains(id) { id += 1 }; used.insert(id)
            let props: [String: Any] = ["sheetId": id, "title": title, "gridProperties": ["rowCount": max(1000, state.sessions.count+1, state.nonprofits.count+1), "columnCount": 26]]
            properties.append(props); requests.append(["addSheet": ["properties": props]])
        }
        requests = requests.filter { $0["addSheet"] != nil } + requests.filter { $0["addSheet"] == nil }
        metadata = ["sheets": properties.map { ["properties": $0] }]; records = ["Sessions": [:], "Projects": [:]]; logCount = 0
        var root = try JSONSerialization.jsonObject(with: PortableData.encode(state)) as! [String: Any]
        root.removeValue(forKey: "sessions"); root.removeValue(forKey: "nonprofits")
        requests.append(try update("TickMeta", 0, [["tick-rows-v1", try json(root)]]))
        for (title, header) in [("Sessions", ["Project", "Started (UTC)", "Ended (UTC)", "Duration", "Hours", "Notes", "Status", "Platform"]), ("Projects", ["Project", "Total hours", "Sessions"])] {
            requests.append(try update(title, 0, [header + ["Tick ID", "Version", "Deleted", "Chunks", "Tick data"]]))
            let tab = try sheet(title), id = tab["sheetId"] as? Int ?? 0
            requests.append(["updateSheetProperties": ["properties": ["sheetId": id, "gridProperties": ["frozenRowCount": 1]], "fields": "gridProperties.frozenRowCount"]])
            requests.append(["repeatCell": ["range": ["sheetId": id, "startRowIndex": 0, "endRowIndex": 1], "cell": ["userEnteredFormat": ["textFormat": ["bold": true]]], "fields": "userEnteredFormat.textFormat"]])
            requests.append(["updateDimensionProperties": ["range": ["sheetId": id, "dimension": "COLUMNS", "startIndex": header.count, "endIndex": max(header.count+5, (tab["gridProperties"] as? [String: Int])?["columnCount"] ?? 26)], "properties": ["hiddenByUser": true], "fields": "hiddenByUser"]])
        }
        for title in ["TickMeta", "TickChanges"] { requests.append(["updateSheetProperties": ["properties": ["sheetId": try sheet(title)["sheetId"] as? Int ?? 0, "hidden": true], "fields": "hidden"]]) }
        return requests
    }
    func save(_ state: TrackerState, expected: String?, initializing: Bool) throws -> String {
        var latest = expected
        if !initializing { let result = try read(); latest = result.1; guard latest == expected else { throw fail("Data changed on another device. Reload before saving.") } }
        var requests = initializing ? try initialize(state) : []
        let revision = UUID().uuidString
        let root = try JSONSerialization.jsonObject(with: PortableData.encode(state)) as! [String: Any]
        let projects = root["nonprofits"] as! [[String: Any]], sessions = root["sessions"] as! [[String: Any]]
        let names = Dictionary(uniqueKeysWithValues: projects.map { ($0["id"] as! String, $0["name"] as! String) })
        var totals: [String: (Double, Int)] = [:]
        var sessionViews: [[Any]] = []
        for s in sessions {
            let seconds = s["durationSeconds"] as? Double, ended = s["endTimeUtc"] as? String, n = Int((s["durationSeconds"] as? Double) ?? 0), key = s["projectId"] as! String
            let started = String((s["startTimeUtc"] as! String).prefix(19)).replacingOccurrences(of: "T", with: " ")
            let endLabel = ended.map { String($0.prefix(19)).replacingOccurrences(of: "T", with: " ") } ?? ""
            let duration = seconds == nil ? "" : String(format: "%d:%02d:%02d", n/3600, n/60%60, n%60)
            let hours: Any = seconds.map { $0/3600 as Any } ?? ""
            let view: [Any] = [names[key] ?? (s["project"] as! String), started, endLabel, duration, hours, s["notes"]!, ended == nil ? "Running" : "Completed", s["platform"]!]
            sessionViews.append(view)
            let old = totals[key] ?? (0,0); totals[key] = (old.0+(seconds ?? 0)/3600, old.1+1)
        }
        let projectViews: [[Any]] = projects.map { p in let t = totals[p["id"] as! String] ?? (0,0); return [p["name"]!, t.0, t.1] }
        var changed: [[String: Any]] = []
        for (title, key, items, views) in [("Sessions", "sessionId", sessions, sessionViews), ("Projects", "id", projects, projectViews)] {
            let old = records[title] ?? [:]
            let incoming = Dictionary(uniqueKeysWithValues: zip(items, views).map { (($0.0[key] as! String).lowercased(), ($0.0, $0.1)) })
            var nextIndex = (old.values.map(\.index).max() ?? 0)+1
            for id in Set(old.keys).union(incoming.keys).sorted() {
                let before = old[id], payload = incoming[id]?.0 ?? old[id]!.payload
                let view = incoming[id]?.1 ?? Array(repeating: "" as Any, count: title == "Sessions" ? 8 : 3), deleted = incoming[id] == nil ? "1" : "0"
                let safeView: [Any] = view.map { value in if let text = value as? String { return String(text.unicodeScalars.prefix(20000)) }; return value }
                if let before, before.deleted == deleted, equal(before.payload, payload), equal(Array(before.row.prefix(safeView.count)), safeView) { continue }
                let parts = try chunks(json(payload))
                let row = safeView + [id, revision, deleted, parts.count] + parts
                let index = before?.index ?? nextIndex; if before == nil { nextIndex += 1 }
                requests.append(try update(title, index, [row], width: max(row.count, before?.row.count ?? 0)))
                changed.append(["table": title, "id": id, "row": row])
            }
        }
        if changed.isEmpty && !initializing { return expected! }
        let audit = try chunks(json(["changes": changed]))
        for tab in tabs where ["Sessions", "Projects", "TickChanges"].contains(tab["title"] as? String ?? "") {
            let id = tab["sheetId"] as? Int ?? 0, grid = tab["gridProperties"] as? [String: Int] ?? [:]
            let updates = requests.compactMap { $0["updateCells"] as? [String: Any] }.compactMap { $0["range"] as? [String: Int] }.filter { $0["sheetId"] == id }
            let rows = max(updates.compactMap { $0["endRowIndex"] }.max() ?? 1, tab["title"] as? String == "TickChanges" ? logCount+audit.count : 1)
            let columns = max(updates.compactMap { $0["endColumnIndex"] }.max() ?? 5, 5)
            if rows > (grid["rowCount"] ?? 1000) || columns > (grid["columnCount"] ?? 26) { requests.insert(["updateSheetProperties": ["properties": ["sheetId": id, "gridProperties": ["rowCount": max(rows, grid["rowCount"] ?? 1000), "columnCount": max(columns, grid["columnCount"] ?? 26)]], "fields": "gridProperties.rowCount,gridProperties.columnCount"]], at: requests.firstIndex(where: { $0["updateCells"] != nil }) ?? requests.count) }
        }
        for request in requests {
            guard let props = (request["updateSheetProperties"] as? [String: Any])?["properties"] as? [String: Any], let grid = props["gridProperties"] as? [String: Int], let columns = grid["columnCount"], let id = props["sheetId"] as? Int,
                  let tab = tabs.first(where: { $0["sheetId"] as? Int == id }), let title = tab["title"] as? String, ["Sessions", "Projects"].contains(title) else { continue }
            requests.append(["updateDimensionProperties": ["range": ["sheetId": id, "dimension": "COLUMNS", "startIndex": title == "Sessions" ? 8 : 3, "endIndex": columns], "properties": ["hiddenByUser": true], "fields": "hiddenByUser"]])
        }
        let auditRows: [[Any]] = audit.enumerated().map { [revision, initializing ? "" : (latest ?? ""), $0.offset, audit.count, $0.element] }
        requests.append(["appendCells": ["sheetId": try sheet("TickChanges")["sheetId"] as? Int ?? 0, "rows": cells(auditRows), "fields": "userEnteredValue"]])
        _ = try api.request("POST", base+":batchUpdate", ["requests": requests])
        let (saved, confirmed) = try read()
        // Entity ordering is immaterial; use IDs for comparison after users sort rows.
        let actual = try JSONSerialization.jsonObject(with: PortableData.encode(saved)) as! [String: Any]
        func normalized(_ value: [String: Any]) -> [String: Any] { var value = value; value["nonprofits"] = (value["nonprofits"] as! [[String: Any]]).sorted { ($0["id"] as! String) < ($1["id"] as! String) }; return value }
        let rowsConfirmed = changed.allSatisfy { change in
            guard let title = change["table"] as? String, let id = change["id"] as? String, let actual = records[title]?[id]?.row else { return false }
            return equal(actual, change["row"]!)
        }
        guard confirmed == revision, equal(normalized(actual), normalized(root)), rowsConfirmed else { throw fail("Save could not be confirmed. Reload before retrying.") }
        var properties = tabs
        for request in requests {
            guard let props = (request["updateSheetProperties"] as? [String: Any])?["properties"] as? [String: Any], let grid = props["gridProperties"] as? [String: Int], let index = properties.firstIndex(where: { $0["sheetId"] as? Int == props["sheetId"] as? Int }) else { continue }
            var old = properties[index]["gridProperties"] as? [String: Int] ?? [:]
            old.merge(grid) { _, new in new }; properties[index]["gridProperties"] = old
        }
        metadata = ["sheets": properties.map { ["properties": $0] }]
        return revision
    }
}
