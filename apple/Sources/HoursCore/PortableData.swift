import Foundation

public enum PortableData {
    public enum Error: LocalizedError {
        case invalid, changed
        public var errorDescription: String? {
            switch self {
            case .invalid: "Invalid or unsupported saved hours file."
            case .changed: "The data file changed or was removed. Select its data folder again before saving."
            }
        }
    }
    public static func decode(_ data: Data) throws -> TrackerState {
        guard var root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw Error.invalid }
        let legacy = root["schemaVersion"] == nil
        if legacy {
            root["schemaVersion"] = 1
            guard var sessions = root["sessions"] as? [[String: Any]] else { throw Error.invalid }
            for i in sessions.indices {
                sessions[i]["platform"] = sessions[i]["platform"] ?? "android"
                sessions[i]["syncState"] = sessions[i]["syncState"] ?? "pending"
            }
            root["sessions"] = sessions
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let value = try decoder.singleValueContainer()
            if legacy, let seconds = try? value.decode(Double.self), seconds.isFinite {
                return Date(timeIntervalSinceReferenceDate: seconds)
            }
            let text = try value.decode(String.self)
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: text) { return date }
            formatter.formatOptions = [.withInternetDateTime]
            guard let date = formatter.date(from: text) else { throw Error.invalid }
            return date
        }
        let state = try decoder.decode(TrackerState.self, from: JSONSerialization.data(withJSONObject: root))
        try validate(state)
        return state
    }
    public static func encode(_ state: TrackerState) throws -> Data {
        try validate(state)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .custom { date, encoder in
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            var value = encoder.singleValueContainer()
            try value.encode(formatter.string(from: date))
        }
        return try encoder.encode(state)
    }
    private static func validate(_ state: TrackerState) throws {
        let nonprofits = Set(state.nonprofits.map(\.id))
        guard state.schemaVersion == 1, nonprofits.count == state.nonprofits.count,
              Set(state.sessions.map(\.sessionId)).count == state.sessions.count,
              state.sessions.filter({ $0.endTimeUtc == nil }).count <= 1 else { throw Error.invalid }
        for session in state.sessions {
            guard nonprofits.contains(session.nonprofitId),
                  ["android", "ios", "macos", "windows", "linux"].contains(session.platform),
                  ["pending", "synced", "failed"].contains(session.syncState),
                  session.startTimeUtc.timeIntervalSince1970.isFinite,
                  session.updatedAtUtc.timeIntervalSince1970.isFinite else { throw Error.invalid }
            if let end = session.endTimeUtc {
                let actual = end.timeIntervalSince(session.startTimeUtc)
                guard actual.isFinite, actual >= 0, let seconds = session.durationSeconds,
                      seconds >= 0, abs(Double(seconds) - actual) < 1.01 else { throw Error.invalid }
            } else if session.durationSeconds != nil { throw Error.invalid }
        }
    }
}
