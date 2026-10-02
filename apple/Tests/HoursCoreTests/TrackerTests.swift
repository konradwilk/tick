import XCTest
@testable import HoursCore

final class TrackerTests: XCTestCase {
    func testCapitalizesNewAndEditedActivities() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("kitchen")
        XCTAssertEqual(tracker.state.nonprofits.first?.name, "Kitchen")
        let start = Date(timeIntervalSince1970: 0)
        try tracker.start(nonprofitId: id, notes: "  emails, google Fi\n990-EZ review", now: start)
        XCTAssertEqual(tracker.state.active?.notes, "  Emails, Google Fi\n990-EZ review")
        try tracker.stop(now: start.addingTimeInterval(3600))
        try tracker.updateNotes(sessionId: tracker.state.sessions[0].sessionId, notes: "collect payments\r\n\"annual meeting\",MN DOT")
        XCTAssertEqual(tracker.state.sessions[0].notes, "Collect payments\r\n\"Annual meeting\",MN DOT")
        try tracker.addSession(nonprofitId: id, notes: "cooking,etc", start: start, end: start.addingTimeInterval(900))
        XCTAssertEqual(tracker.state.sessions.last?.notes, "Cooking,Etc")
    }
    func testDeleteOnlyShortCompletedSessions() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("Kitchen")
        let start = Date(timeIntervalSince1970: 0)
        for seconds in [0, 59, 60] {
            try tracker.start(nonprofitId: id, notes: "Short", now: start)
            let sessionId = try XCTUnwrap(tracker.state.active?.sessionId)
            XCTAssertThrowsError(try tracker.deleteSession(sessionId: sessionId))
            try tracker.stop(now: start.addingTimeInterval(Double(seconds)))
            if seconds < 60 {
                try tracker.deleteSession(sessionId: sessionId)
                XCTAssertTrue(try Tracker(file: file).state.sessions.isEmpty)
                XCTAssertEqual(tracker.clipboardText(), "")
                XCTAssertFalse(tracker.csv().contains("Short"))
            } else { XCTAssertThrowsError(try tracker.deleteSession(sessionId: sessionId)) }
        }
        XCTAssertThrowsError(try tracker.deleteSession(sessionId: UUID()))
    }
    func testManualSessionPersistsWithoutStoppingTimer() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("Kitchen")
        let start = Date(timeIntervalSince1970: 0)
        let end = start.addingTimeInterval(7200)
        try tracker.start(nonprofitId: id, notes: "Active", now: start)
        let active = tracker.state.active?.sessionId
        try tracker.addSession(nonprofitId: id, notes: "Meals", start: start, end: end, platform: "ios")
        let restored = try Tracker(file: file)
        XCTAssertEqual(restored.state.active?.sessionId, active)
        XCTAssertEqual(restored.exportSessions().first?.durationSeconds, 7200)
        XCTAssertEqual(restored.exportSessions().first?.platform, "ios")
        XCTAssertTrue(restored.csv().contains("Meals"))
        XCTAssertEqual(restored.clipboardText(), "Kitchen 02:00:00:\nMeals   02:00:00")
        XCTAssertThrowsError(try tracker.addSession(nonprofitId: id, notes: "Meals", start: end, end: start))
        XCTAssertThrowsError(try tracker.addSession(nonprofitId: id, notes: "Meals", start: start, end: start))
        XCTAssertThrowsError(try tracker.addSession(nonprofitId: id, notes: " ", start: start, end: end))
        XCTAssertThrowsError(try tracker.addSession(nonprofitId: UUID(), notes: "Meals", start: start, end: end))
        XCTAssertEqual(tracker.state.sessions.count, 2)
        try Data("changed".utf8).write(to: file)
        XCTAssertThrowsError(try tracker.addSession(nonprofitId: id, notes: "Meals", start: start, end: end))
        XCTAssertEqual(tracker.state.sessions.count, 2)
    }
    func testClipboardNormalizesNotesWithoutChangingStoredText() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("NEST")
        try tracker.start(nonprofitId: id, now: Date(timeIntervalSince1970: 0))
        try tracker.stop(now: Date(timeIntervalSince1970: 1423))
        let sessionId = try XCTUnwrap(tracker.state.sessions.first?.sessionId)
        for (notes, expected) in [("", "No notes   00:23:43"), (" \t\r\n ", "No notes   00:23:43"),
            ("Annual meeting, Google Fi,Cooking,Etc", "Annual meeting   00:05:56\nCooking   00:05:56\nEtc   00:05:55\nGoogle Fi   00:05:56"),
            ("Meals,, Meals, ", "Meals   00:23:43"), (", ,", "No notes   00:23:43"),
            ("Annual meeting\nGoogle Fi", "Annual meeting   00:11:52\nGoogle Fi   00:11:51"),
            ("Annual meeting\rGoogle Fi", "Annual meeting   00:11:52\nGoogle Fi   00:11:51"),
            (" Annual meeting\r\n \r\nGoogle Fi ", "Annual meeting   00:11:52\nGoogle Fi   00:11:51")] {
            try tracker.updateNotes(sessionId: sessionId, notes: notes)
            XCTAssertEqual(tracker.clipboardText(), "NEST 00:23:43:\n\(expected)")
            XCTAssertEqual(tracker.state.sessions.first?.notes, notes)
        }
    }
    func testClipboardCombinesDescriptionsAndSortsAlphabetically() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let kitchen = try tracker.addNonprofit("Kitchen")
        let garden = try tracker.addNonprofit("Garden")
        var start = Date(timeIntervalSince1970: 0)
        for (id, notes, seconds) in [(kitchen, "Meals", 3600.0), (garden, "Planting", 1800.0), (kitchen, "Cleanup", 2700.0), (kitchen, " Cleanup ", 60.0), (kitchen, "", 1.0), (kitchen, " \n ", 2.0), (garden, "Cleanup", 120.0)] {
            try tracker.start(nonprofitId: id, notes: notes, now: start)
            start = start.addingTimeInterval(seconds)
            try tracker.stop(now: start)
        }
        XCTAssertEqual(tracker.clipboardText(), "Kitchen 01:46:03:\nCleanup   00:46:00\nMeals   01:00:00\nNo notes   00:00:03\n\nGarden 00:32:00:\nCleanup   00:02:00\nPlanting   00:30:00")
        XCTAssertEqual(tracker.exportSessions().count, 7)
        XCTAssertTrue(tracker.csv().contains(" Cleanup "))
    }
    func testPeriodExportsAndClipboard() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("Kitchen")
        let formatter = ISO8601DateFormatter()
        let start = try XCTUnwrap(formatter.date(from: "2024-12-31T22:00:00Z"))
        try tracker.start(nonprofitId: id, notes: "Outside", now: start.addingTimeInterval(-1))
        try tracker.stop(now: start)
        let notes = "Meals, \"Served\"\nCleanup 🍲"
        try tracker.start(nonprofitId: id, notes: notes, now: start)
        try tracker.stop(now: start.addingTimeInterval(90000))
        try tracker.start(nonprofitId: id, notes: "End boundary", now: start.addingTimeInterval(86400))
        try tracker.stop(now: start.addingTimeInterval(86460))
        try tracker.start(nonprofitId: id, notes: "Active", now: start.addingTimeInterval(120))
        let zone = try XCTUnwrap(TimeZone(secondsFromGMT: 7200))
        let range = ExportRange(period: .daily, date: start, timeZone: zone)
        XCTAssertEqual(tracker.exportSessions(range: range).count, 1)
        XCTAssertEqual(tracker.clipboardText(range: range), "Kitchen 25:00:00:\n\"Served\"   08:20:00\nCleanup 🍲   08:20:00\nMeals   08:20:00")
        XCTAssertFalse(tracker.csv(range: range).contains("Outside"))
        XCTAssertFalse(tracker.csv(range: range).contains("End boundary"))
        XCTAssertFalse(tracker.csv(range: range).contains("Active"))
        XCTAssertEqual(tracker.clipboardText(range: ExportRange(period: .daily, date: start.addingTimeInterval(172800), timeZone: zone)), "")
        let week = ExportRange(period: .weekly, date: start, timeZone: zone)
        XCTAssertEqual(formatter.string(from: week.start), "2024-12-29T22:00:00Z")
        XCTAssertEqual(formatter.string(from: week.end), "2025-01-05T22:00:00Z")
        let month = ExportRange(period: .monthly, date: start, timeZone: zone)
        XCTAssertEqual(formatter.string(from: month.end), "2025-01-31T22:00:00Z")
        let spring = try XCTUnwrap(formatter.date(from: "2025-03-09T12:00:00Z"))
        let dst = ExportRange(period: .daily, date: spring, timeZone: try XCTUnwrap(TimeZone(identifier: "America/New_York")))
        XCTAssertEqual(dst.end.timeIntervalSince(dst.start), 23 * 3600)
    }
    private func location() -> URL { FileManager.default.temporaryDirectory.appending(path: UUID().uuidString + "/sessions.json") }
    func testEditedNotesPersistWithoutChangingHours() throws {
        let file = location()
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("Kitchen")
        let start = Date(timeIntervalSince1970: 1000)
        try tracker.start(nonprofitId: id, notes: "Original", now: start)
        try tracker.stop(now: start.addingTimeInterval(3600))
        let original = try XCTUnwrap(tracker.state.sessions.first)
        let editedAt = start.addingTimeInterval(7200)
        for notes in ["Meals, \"Served\"\nCleanup 🍲", ""] {
            try tracker.updateNotes(sessionId: original.sessionId, notes: notes, now: editedAt)
            let restored = try XCTUnwrap(Tracker(file: file).state.sessions.first)
            XCTAssertEqual(restored.notes, notes)
            XCTAssertEqual(restored.sessionId, original.sessionId)
            XCTAssertEqual(restored.startTimeUtc, original.startTimeUtc)
            XCTAssertEqual(restored.endTimeUtc, original.endTimeUtc)
            XCTAssertEqual(restored.durationSeconds, original.durationSeconds)
            XCTAssertEqual(restored.updatedAtUtc, editedAt)
            XCTAssertEqual(restored.syncState, "pending")
            XCTAssertTrue(tracker.csv().contains("\"" + notes.replacingOccurrences(of: "\"", with: "\"\"") + "\""))
        }
        let before = try Data(contentsOf: file)
        XCTAssertThrowsError(try tracker.updateNotes(sessionId: UUID(), notes: "Missing"))
        XCTAssertEqual(try Data(contentsOf: file), before)
        try Data("external change".utf8).write(to: file)
        XCTAssertThrowsError(try tracker.updateNotes(sessionId: original.sessionId, notes: "Unsaved"))
        XCTAssertEqual(tracker.state.sessions.first?.notes, "")
        XCTAssertEqual(try Data(contentsOf: file), Data("external change".utf8))
    }
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
        try tracker.start(nonprofitId: id, notes: "A, \"Quote\"\nand newline", now: start)
        XCTAssertFalse(tracker.csv().contains("SUM"))
        try tracker.stop(now: start.addingTimeInterval(60))
        XCTAssertEqual(tracker.csv().components(separatedBy: "\r\n").first, "nonprofitName,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform")
        XCTAssertFalse(tracker.csv().contains(id.uuidString))
        XCTAssertFalse(tracker.csv().contains(try XCTUnwrap(tracker.state.sessions.first?.sessionId).uuidString))
        XCTAssertTrue(tracker.csv().contains("\"'=SUM(1,2)\""))
        XCTAssertTrue(tracker.csv().contains("\"A, \"\"Quote\"\"\nand newline\""))
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
