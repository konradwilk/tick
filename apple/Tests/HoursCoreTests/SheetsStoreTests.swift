import XCTest
@testable import HoursCore

final class SheetsStoreTests: XCTestCase {
    final class Server {
        var properties: [[String: Any]], tables: [String: [[Any]]]
        var requests: [[String: Any]] = []
        var calls = 0
        var afterAppend: ((inout [[Any]]) -> Void)?
        var failWrite = false
        init(legacy: Bool = false) throws {
            let path = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("fixtures/storage/sheets-rows-v1.json")
            let fixture = try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as! [String: Any]
            properties = (fixture["metadata"] as! [String: Any])["sheets"] as! [[String: Any]]
            tables = fixture["tables"] as! [String: [[Any]]]
            if legacy {
                properties = [["properties": ["sheetId": 0, "title": "TickLog", "gridProperties": ["rowCount": 1000, "columnCount": 6]]]]
                let raw = String(decoding: try JSONSerialization.data(withJSONObject: fixture["state"]!), as: UTF8.self)
                tables = ["TickLog": [["tick-log-v1", "legacy", "", 0, 1, raw]]]
            }
        }
        func request(_ method: String, _ url: String, _ body: [String: Any]?) throws -> [String: Any] {
            calls += 1
            if url.contains("?fields=") { return ["properties": ["title": "Fixture"], "sheets": properties] }
            if url.contains("/values:batchGet?") {
                let ranges = URLComponents(string: url)!.queryItems!.filter { $0.name == "ranges" }.map { $0.value! }
                return ["valueRanges": ranges.map { range -> [String: Any] in
                    let title = String(range.split(separator: "!")[0]); var values = tables[title] ?? []
                    if title == "TickChanges" { values = values.map { Array($0.prefix(4)) } }
                    return ["values": values]
                }]
            }
            if method == "GET" { return ["values": tables[url.contains("TickLog") ? "TickLog" : "TickData"] ?? []] }
            if failWrite { throw SheetsError.message("offline") }
            requests = body!["requests"] as! [[String: Any]]
            for request in requests {
                if let add = request["addSheet"] as? [String: Any] { properties.append(["properties": add["properties"]!]) }
                if let update = request["updateSheetProperties"] as? [String: Any], let props = update["properties"] as? [String: Any], let id = props["sheetId"] as? Int {
                    let index = properties.firstIndex { ($0["properties"] as! [String: Any])["sheetId"] as? Int == id }!
                    var old = properties[index]["properties"] as! [String: Any]
                    if let title = props["title"] as? String { tables[title] = tables.removeValue(forKey: old["title"] as! String); old["title"] = title }
                    properties[index]["properties"] = old
                }
                for kind in ["updateCells", "appendCells"] {
                    guard let update = request[kind] as? [String: Any] else { continue }
                    let range = update["range"] as? [String: Any] ?? update
                    let id = range["sheetId"] as! Int
                    let title = properties.map { $0["properties"] as! [String: Any] }.first { $0["sheetId"] as? Int == id }!["title"] as! String
                    let values = (update["rows"] as! [[String: Any]]).map { row in (row["values"] as! [[String: Any]]).map { ($0["userEnteredValue"] as! [String: Any]).values.first! } }
                    var table = tables[title] ?? []
                    if kind == "appendCells" { table += values; afterAppend?(&table) }
                    else { let start = range["startRowIndex"] as? Int ?? 0; while table.count < start+values.count { table.append([]) }; for (n, row) in values.enumerated() { table[start+n] = row } }
                    tables[title] = table
                }
            }
            return [:]
        }
        func store() throws -> SheetsStore { try SheetsStore(configuration: SheetsConfiguration(sheetID: "test"), api: GoogleSheetsAPI(transport: request)) }
    }
    func testPythonRowsRoundTripOnlyChangedRowAndReordering() throws {
        let server = try Server(), store = try server.store()
        var state = try XCTUnwrap(store.load())
        server.tables["Sessions"]!.swapAt(1,2)
        state.sessions[0].notes = "Changed"
        server.calls = 0
        try store.save(state)
        XCTAssertEqual(server.calls, 3)
        let updates = server.requests.compactMap { $0["updateCells"] as? [String: Any] }
        XCTAssertEqual(updates.count, 1)
        XCTAssertEqual((updates[0]["range"] as! [String: Int])["startRowIndex"], 2)
        XCTAssertEqual(server.tables["Sessions"]![2][5] as? String, "Changed")
        XCTAssertFalse(server.requests.contains { $0["repeatCell"] != nil })
        let count = server.tables["TickChanges"]!.count
        try store.save(state)
        XCTAssertEqual(server.tables["TickChanges"]!.count, count)
    }
    func testLegacyMigrationStaleWritesAndConcurrentRecovery() throws {
        let server = try Server(legacy: true), store = try server.store()
        var state = try XCTUnwrap(store.load()); let original = server.tables["TickLog"]!
        try store.save(state)
        XCTAssertEqual(server.tables["TickLogBackup"]!.count, original.count)
        XCTAssertNil(server.tables["TickLog"])
        let stale = try server.store(); let old = try XCTUnwrap(stale.load())
        state.sessions[0].notes = "New"; try store.save(state)
        XCTAssertThrowsError(try stale.save(old))
        state.sessions[0].notes = "Concurrent"
        server.afterAppend = { rows in var sibling = rows.last!; sibling[0] = "sibling"; rows.append(sibling) }
        XCTAssertThrowsError(try store.save(state))
        XCTAssertThrowsError(try server.store().load())
        XCTAssertGreaterThan(server.tables["TickChanges"]!.count, 3)
    }
    func testLongUnicodeNotesDeletionAndFailedWrite() throws {
        let server = try Server(), store = try server.store()
        var state = try XCTUnwrap(store.load())
        state.sessions[0].notes = String(repeating: "🍲", count: 45000)
        try store.save(state)
        XCTAssertEqual(try store.load()!.sessions[0].notes, state.sessions[0].notes)
        let width = server.tables["Sessions"]![1].count
        state.sessions[0].notes = "Short"; try store.save(state)
        let update = server.requests.compactMap { $0["updateCells"] as? [String: Any] }[0]
        XCTAssertEqual((update["range"] as! [String: Int])["endColumnIndex"], width)
        state.sessions.removeLast(); try store.save(state)
        XCTAssertEqual(try store.load()!.sessions.count, 1)
        server.failWrite = true; state.sessions[0].notes = "Offline"
        XCTAssertThrowsError(try store.save(state)); server.failWrite = false
        XCTAssertEqual(try store.load()!.sessions[0].notes, "Short")
    }
    func testConfigurationAndBrokenChunkRejection() throws {
        XCTAssertThrowsError(try SheetsConfiguration(sheetID: "https://example.com"))
        XCTAssertThrowsError(try SheetsStore.decodeLog([["tick-log-v1", "revision", "", 0, 2, "{}"]]))
        let server = try Server(); server.tables["Sessions"]![1].removeLast()
        XCTAssertThrowsError(try server.store().load())
    }
}
