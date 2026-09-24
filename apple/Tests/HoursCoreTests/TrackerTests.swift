import XCTest
@testable import HoursCore

final class TrackerTests: XCTestCase {
    private func location() -> URL { FileManager.default.temporaryDirectory.appending(path: UUID().uuidString + "/sessions.json") }
    func testRestartPreservesActiveSessionAndNonprofit() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("Community Kitchen")
        let start = Date(timeIntervalSince1970: 1_000)
        try tracker.start(nonprofitId: id, notes: "Dinner", now: start)
        let sessionID = tracker.state.active?.sessionId
        XCTAssertThrowsError(try tracker.start(nonprofitId: id))
        let restored = try Tracker(file: file)
        XCTAssertEqual(restored.state.active?.sessionId, sessionID)
        try restored.stop(now: start.addingTimeInterval(3600))
        XCTAssertEqual(restored.state.sessions.first?.durationSeconds, 3600)
        XCTAssertNil(try Tracker(file: file).state.active)
        XCTAssertEqual(restored.state.sessions.first?.nonprofitId, id)
    }
    func testCSVQuotesUserTextAndExcludesActiveSessions() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("=SUM(1,2)")
        let start = Date(timeIntervalSince1970: 0)
        try tracker.start(nonprofitId: id, notes: "A, \"quote\"\nand newline", now: start)
        XCTAssertFalse(tracker.csv().contains("SUM"))
        try tracker.stop(now: start.addingTimeInterval(60))
        XCTAssertTrue(tracker.csv().contains("\"'=SUM(1,2)\""))
        XCTAssertTrue(tracker.csv().contains("\"A, \"\"quote\"\"\nand newline\""))
        XCTAssertTrue(tracker.csv().contains("1970-01-01T00:01:00Z"))
    }
    func testInvalidActionsAndBackwardClockDoNotChangeSession() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        XCTAssertThrowsError(try tracker.addNonprofit("  "))
        let id = try tracker.addNonprofit("Kitchen")
        XCTAssertThrowsError(try tracker.addNonprofit(" kitchen "))
        XCTAssertThrowsError(try tracker.stop())
        XCTAssertThrowsError(try tracker.start(nonprofitId: UUID()))
        try tracker.start(nonprofitId: id, now: Date(timeIntervalSince1970: 100))
        XCTAssertThrowsError(try tracker.stop(now: Date(timeIntervalSince1970: 99)))
        XCTAssertNotNil(tracker.state.active)
    }
    func testCorruptFileIsNotOverwritten() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        let original = Data("broken".utf8)
        try original.write(to: file)
        XCTAssertThrowsError(try Tracker(file: file))
        XCTAssertEqual(try Data(contentsOf: file), original)
    }
    func testFailedSaveDoesNotStartSession() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("Kitchen")
        try FileManager.default.removeItem(at: file)
        try FileManager.default.createDirectory(at: file, withIntermediateDirectories: true)
        XCTAssertThrowsError(try tracker.start(nonprofitId: id))
        XCTAssertNil(tracker.state.active)
    }
}
