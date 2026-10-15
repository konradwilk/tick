import XCTest
@testable import HoursCore

final class SheetsStoreTests: XCTestCase {
    func testRoundTripStaleSaveAndPreservedConcurrentBranches() throws {
        var rows: [[Any]] = []
        var tables: [Int: [[Any]]] = [:]
        let api = GoogleSheetsAPI(transport: { method,url,body in
            if url.contains("?fields=") { return ["properties": ["title":"Time is Clearly Kept"],"sheets": [["properties":["title":"TickLog"]]]] }
            if method == "GET" { return ["values":rows] }
            if url.contains(":batchUpdate") {
                for request in body!["requests"] as! [[String: Any]] {
                    if let update = request["updateCells"] as? [String: Any], let range = update["range"] as? [String: Any], let id = range["sheetId"] as? Int {
                        tables[id] = (update["rows"] as! [[String: Any]]).map { ($0["values"] as! [[String: Any]]).map { ($0["userEnteredValue"] as! [String: Any]).values.first! } }
                    }
                    if let append = request["appendCells"] as? [String: Any] {
                        rows += (append["rows"] as! [[String: Any]]).map { ($0["values"] as! [[String: Any]]).map { ($0["userEnteredValue"] as! [String: Any]).values.first! } }
                    }
                }
                return [:]
            }
            if url.contains(":append?") { rows += body!["values"] as! [[Any]]; return [:] }
            XCTFail("Unexpected API request"); return [:]
        })
        let config = try SheetsConfiguration(sheetID:"test")
        let store = try SheetsStore(configuration:config,api:api)
        let tracker = try Tracker(sheets:store)
        let project = try tracker.addNonprofit("Kitchen 🍲")
        try tracker.start(projectId:project)
        let stale = try Tracker(sheets:SheetsStore(configuration:config,api:api),requireExisting:true)
        try tracker.stop()
        XCTAssertEqual(tables[174001]?.count, 2)
        XCTAssertEqual(tables[174001]?[1][0] as? String, "Kitchen 🍲")
        XCTAssertEqual(tables[174001]?[1][6] as? String, "Completed")
        XCTAssertEqual(tables[174002]?[1][2] as? Int, 1)
        let before = try PortableData.encode(stale.state)
        XCTAssertThrowsError(try stale.updateNotes(sessionId:stale.state.sessions[0].sessionId,notes:"Wrong"))
        XCTAssertEqual(try PortableData.encode(stale.state),before)
        let oldRows = rows.count
        var sibling = rows.last!; sibling[1] = "other-revision"; rows.append(sibling)
        XCTAssertThrowsError(try store.load())
        XCTAssertEqual(rows.count,oldRows+1)
    }
    func testConfigurationCallbackAndBrokenChunkRejection() throws {
        XCTAssertThrowsError(try SheetsConfiguration(sheetID:"https://example.com"))
        XCTAssertEqual(try authorizationCode(URL(string:"com.example.app:/oauth?state=valid&code=accepted")!,state:"valid"),"accepted")
        XCTAssertThrowsError(try authorizationCode(URL(string:"com.example.app:/oauth?state=wrong&code=attacker")!,state:"valid"))
        XCTAssertThrowsError(try SheetsStore.decodeLog([["tick-log-v1","revision","",0,2,"{}"]]))
    }
}
