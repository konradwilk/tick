import Foundation

public struct Nonprofit: Codable, Identifiable, Equatable, Sendable {
    public var id: UUID
    public var name: String
    public init(id: UUID = UUID(), name: String) { self.id = id; self.name = name }
}

public struct Session: Codable, Identifiable, Sendable {
    public var id: UUID { sessionId }
    public var sessionId: UUID
    public var nonprofitId: UUID
    public var nonprofitName: String
    public var startTimeUtc: Date
    public var endTimeUtc: Date?
    public var durationSeconds: Int?
    public var notes: String
    public var deviceId: UUID
    public var platform: String
    public var updatedAtUtc: Date
    public var syncState: String
}

public struct TrackerState: Codable, Sendable {
    public var deviceId = UUID()
    public var nonprofits: [Nonprofit] = []
    public var sessions: [Session] = []
    public init() {}
    public var active: Session? { sessions.first { $0.endTimeUtc == nil } }
}

public enum TrackerError: LocalizedError {
    case activeSession, noActiveSession, invalidNonprofit, clockChanged
    public var errorDescription: String? {
        switch self {
        case .activeSession: "Stop the current session first."
        case .noActiveSession: "There is no active session."
        case .invalidNonprofit: "Enter a unique nonprofit name and select it before starting."
        case .clockChanged: "The clock is earlier than the session start. Correct the system clock before stopping."
        }
    }
}

/// Each change is saved atomically before it becomes visible to the caller.
public final class Tracker {
    public private(set) var state: TrackerState
    private let file: URL
    public init(file: URL) throws {
        self.file = file
        if FileManager.default.fileExists(atPath: file.path) {
            state = try JSONDecoder().decode(TrackerState.self, from: Data(contentsOf: file))
        } else { state = TrackerState() }
    }
    private func save(_ next: TrackerState) throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try JSONEncoder().encode(next).write(to: file, options: .atomic)
        state = next
    }
    @discardableResult public func addNonprofit(_ name: String) throws -> UUID {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, !state.nonprofits.contains(where: { $0.name.caseInsensitiveCompare(name) == .orderedSame }) else { throw TrackerError.invalidNonprofit }
        let nonprofit = Nonprofit(name: name)
        var next = state
        next.nonprofits.append(nonprofit)
        try save(next)
        return nonprofit.id
    }
    public func start(nonprofitId: UUID, notes: String = "", platform: String = "macos", now: Date = Date()) throws {
        guard state.active == nil else { throw TrackerError.activeSession }
        guard let nonprofit = state.nonprofits.first(where: { $0.id == nonprofitId }) else { throw TrackerError.invalidNonprofit }
        var next = state
        next.sessions.append(Session(sessionId: UUID(), nonprofitId: nonprofit.id, nonprofitName: nonprofit.name, startTimeUtc: now, notes: notes, deviceId: state.deviceId, platform: platform, updatedAtUtc: now, syncState: "pending"))
        try save(next)
    }
    public func stop(now: Date = Date()) throws {
        guard let index = state.sessions.firstIndex(where: { $0.endTimeUtc == nil }) else { throw TrackerError.noActiveSession }
        guard now >= state.sessions[index].startTimeUtc else { throw TrackerError.clockChanged }
        var next = state
        next.sessions[index].endTimeUtc = now
        next.sessions[index].durationSeconds = Int(now.timeIntervalSince(next.sessions[index].startTimeUtc))
        next.sessions[index].updatedAtUtc = now
        try save(next)
    }
    public func csv() -> String {
        let formatter = ISO8601DateFormatter()
        func cell(_ value: String) -> String {
            // Prevent spreadsheet formulas when user-entered values are imported.
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            let safe = ["=", "+", "-", "@"].contains(where: { trimmed.hasPrefix($0) }) ? "'" + value : value
            return "\"" + safe.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        var rows = ["sessionId,nonprofitId,nonprofitName,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform,updatedAtUtc"]
        for s in state.sessions where s.endTimeUtc != nil {
            let values = [s.sessionId.uuidString, s.nonprofitId.uuidString, s.nonprofitName, formatter.string(from: s.startTimeUtc), formatter.string(from: s.endTimeUtc!), String(s.durationSeconds ?? 0), String(Double(s.durationSeconds ?? 0) / 3600), s.notes, s.deviceId.uuidString, s.platform, formatter.string(from: s.updatedAtUtc)]
            rows.append(values.map(cell).joined(separator: ","))
        }
        return rows.joined(separator: "\r\n") + "\r\n"
    }
}
