import XCTest
@testable import HoursCore

final class PortableDataTests: XCTestCase {
    func testSharedFileRoundTripAndLegacyDates() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathComponent("sessions.json")
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("Kitchen")
        try tracker.start(nonprofitId: id, notes: "Meals 🍲", platform: "ios", now: Date(timeIntervalSinceReferenceDate: 0))
        try tracker.stop(now: Date(timeIntervalSinceReferenceDate: 60))
        let data = try PortableData.encode(tracker.state)
        let restored = try PortableData.decode(data)
        XCTAssertEqual(restored.sessions.first?.notes, "Meals 🍲")
        XCTAssertEqual(restored.sessions.first?.durationSeconds, 60)
        XCTAssertEqual(restored.sessions.first?.platform, "ios")
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(json["schemaVersion"] as? Int, 1)
        var sessions = try XCTUnwrap(json["sessions"] as? [[String: Any]])
        XCTAssertTrue(sessions[0]["startTimeUtc"] is String)
        json.removeValue(forKey: "schemaVersion")
        sessions[0]["startTimeUtc"] = 0
        sessions[0]["endTimeUtc"] = 60
        sessions[0]["updatedAtUtc"] = 60
        json["sessions"] = sessions
        let legacy = try PortableData.decode(JSONSerialization.data(withJSONObject: json))
        XCTAssertEqual(legacy.sessions.first?.startTimeUtc, Date(timeIntervalSinceReferenceDate: 0))
        XCTAssertEqual(legacy.sessions.first?.durationSeconds, 60)
        json["schemaVersion"] = 99
        XCTAssertThrowsError(try PortableData.decode(JSONSerialization.data(withJSONObject: json)))
        var invalid = tracker.state
        invalid.sessions.append(invalid.sessions[0])
        XCTAssertThrowsError(try PortableData.encode(invalid))
        invalid = tracker.state
        invalid.sessions[0].durationSeconds = 999
        XCTAssertThrowsError(try PortableData.encode(invalid))
    }
}
