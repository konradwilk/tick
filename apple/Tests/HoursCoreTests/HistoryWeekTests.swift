import XCTest
@testable import HoursCore

final class HistoryWeekTests: XCTestCase {
    func testLocalWeeksAcrossYearAndTimeChange() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let tracker = try Tracker(file: directory.appendingPathComponent("tick.json"))
        let project = try tracker.addNonprofit("Kitchen")
        let format = ISO8601DateFormatter()
        func date(_ value: String) -> Date { format.date(from: value)! }
        // Monday in UTC, but still Sunday in New York; an overnight entry stays
        // with its local start week, including when that week crosses a year.
        let sunday = date("2027-01-04T02:00:00Z")
        let monday = date("2027-01-04T05:00:00Z")
        try tracker.addSession(projectId: project, notes: "Sunday", start: sunday, end: monday.addingTimeInterval(3600))
        try tracker.addSession(projectId: project, notes: "Monday", start: monday, end: monday.addingTimeInterval(3600))
        let zone = TimeZone(identifier: "America/New_York")!
        let weeks = historyWeeks(sessions: tracker.state.sessions, timeZone: zone)
        XCTAssertEqual(weeks.count, 2)
        XCTAssertEqual(weeks.map { $0.sessions.map(\.notes) }, [["Monday"], ["Sunday"]])
        XCTAssertEqual(weeks[1].start, date("2026-12-28T05:00:00Z"))
        XCTAssertEqual(weeks[1].lastDay, date("2027-01-03T05:00:00Z"))
        XCTAssertEqual(historyWeeks(sessions: tracker.state.sessions, timeZone: TimeZone(secondsFromGMT: 0)!).count, 1)
        XCTAssertTrue(historyWeeks(sessions: []).isEmpty)
        let dstStart = date("2026-03-08T07:30:00Z")
        try tracker.addSession(projectId: project, notes: "DST", start: dstStart, end: dstStart.addingTimeInterval(3600))
        let dstWeek = historyWeeks(sessions: tracker.state.sessions, timeZone: zone).last!
        XCTAssertEqual(dstWeek.start, date("2026-03-02T05:00:00Z"))
        XCTAssertEqual(dstWeek.lastDay, date("2026-03-08T05:00:00Z"))
    }
}
