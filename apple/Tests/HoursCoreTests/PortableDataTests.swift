import XCTest
@testable import HoursCore

final class PortableDataTests: XCTestCase {
    func testDecodingErrorsIdentifySessionField() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: folder) }
        let tracker = try Tracker(file: folder.appendingPathComponent("tick.json"))
        let id = try tracker.addNonprofit("Example")
        try tracker.start(projectId: id)
        let encoded = try PortableData.encode(tracker.state)
        let original = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        let cases: [(String, Any?, String)] = [
            ("project", nil, "Missing required field: sessions[0].project."),
            ("project", NSNull(), "Null is not allowed at sessions[0].project."),
            ("project", 123, "Wrong value type at sessions[0].project: expected String."),
            ("projectId", "not-a-uuid", "Invalid value at sessions[0].projectId:"),
            ("startTimeUtc", "not-a-date", "Invalid timestamp at sessions[0].startTimeUtc:")
        ]
        for (field, value, expected) in cases {
            var root = original
            var sessions = try XCTUnwrap(root["sessions"] as? [[String: Any]])
            sessions[0][field] = value
            root["sessions"] = sessions
            let data = try JSONSerialization.data(withJSONObject: root)
            XCTAssertThrowsError(try PortableData.decode(data)) { error in
                XCTAssertTrue(error.localizedDescription.hasPrefix(expected), error.localizedDescription)
            }
        }
    }

    func testInvalidJSONReportsSyntaxError() {
        XCTAssertThrowsError(try PortableData.decode(Data("{".utf8))) { error in
            XCTAssertTrue(error.localizedDescription.hasPrefix("Invalid JSON syntax:"))
        }
    }

    func testFirstRunCreatesEmptyFileBeforeTracking() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("tick.json")
        let fresh = try Tracker(file: file)
        XCTAssertFalse(FileManager.default.fileExists(atPath: file.path))
        let saved = try fresh.saveAs(file)
        let reopened = try Tracker(file: file, requireExisting: true)
        XCTAssertEqual(saved.state.deviceId, reopened.state.deviceId)
        XCTAssertTrue(reopened.state.sessions.isEmpty)
        XCTAssertTrue(reopened.state.nonprofits.isEmpty)
    }

    func testSharedFileRoundTripAndLegacyDates() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString).appendingPathComponent("sessions.json")
        defer { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()) }
        let tracker = try Tracker(file: file)
        let id = try tracker.addNonprofit("Kitchen")
        try tracker.start(projectId: id, notes: "Meals 🍲", platform: "ios", now: Date(timeIntervalSinceReferenceDate: 0))
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
