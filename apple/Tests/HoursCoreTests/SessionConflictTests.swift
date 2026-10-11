import XCTest
@testable import HoursCore

final class SessionConflictTests: XCTestCase {
    func testIntervalsAndMultipleProjects() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let tracker = try Tracker(file: directory.appendingPathComponent("tick.json"))
        let first = try tracker.addNonprofit("Kitchen")
        let second = try tracker.addNonprofit("Board")
        func date(_ seconds: Double) -> Date { Date(timeIntervalSince1970: seconds) }
        try tracker.addSession(projectId: first, notes: "Meals", start: date(100), end: date(200))
        // Partial on each side, existing contains proposed, proposed contains existing,
        // exact match, and adjacent boundaries on each side.
        for (start, end, expected) in [(50.0, 150.0, 50.0), (150, 250, 50), (125, 175, 50), (50, 250, 100), (100, 200, 100), (0, 100, 0), (200, 300, 0)] {
            let conflicts = sessionConflicts(sessions: tracker.state.sessions, start: date(start), end: date(end))
            XCTAssertEqual(conflicts.count, expected == 0 ? 0 : 1)
            if expected > 0 {
                XCTAssertEqual(conflicts[0].overlap, expected)
                XCTAssertEqual(conflicts[0].duration, 100)
                XCTAssertEqual(conflicts[0].start, date(max(start, 100)))
                XCTAssertEqual(conflicts[0].end, date(min(end, 200)))
                XCTAssertTrue(conflicts[0].description.contains("Meals — Kitchen"))
            }
        }
        try tracker.addSession(projectId: second, notes: "Meeting", start: date(150), end: date(300))
        let conflicts = sessionConflicts(sessions: tracker.state.sessions, start: date(175), end: date(225))
        XCTAssertEqual(conflicts.map(\.overlap), [25, 50])
        XCTAssertEqual(Set(conflicts.map { $0.session.project }), ["Kitchen", "Board"])
        XCTAssertTrue(sessionConflicts(sessions: tracker.state.sessions, start: date(225), end: date(175)).isEmpty)
        // Intentional overlaps remain persistable, including after restart.
        XCTAssertEqual(try Tracker(file: tracker.file).state.sessions.count, 2)
        try tracker.start(projectId: first, notes: "Running", now: date(400))
        let active = sessionConflicts(sessions: tracker.state.sessions, start: date(425), end: date(600), now: date(500))
        XCTAssertEqual(active[0].overlap, 75)
        XCTAssertEqual(active[0].duration, 100)
        XCTAssertTrue(active[0].description.contains("running, so far"))
    }
}
