import Foundation

public enum ExportPeriod: String, CaseIterable, Sendable { case daily = "Daily", weekly = "Weekly", monthly = "Monthly" }
public struct ExportRange: Sendable {
    public let start: Date
    public let end: Date
    public init(period: ExportPeriod, date: Date, timeZone: TimeZone = .current) {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let day = calendar.startOfDay(for: date)
        switch period {
        case .daily:
            start = day
            end = calendar.date(byAdding: .day, value: 1, to: day)!
        case .weekly:
            let offset = (calendar.component(.weekday, from: day) + 5) % 7
            start = calendar.date(byAdding: .day, value: -offset, to: day)!
            end = calendar.date(byAdding: .day, value: 7, to: start)!
        case .monthly:
            start = calendar.date(from: calendar.dateComponents([.year, .month], from: day))!
            end = calendar.date(byAdding: .month, value: 1, to: start)!
        }
    }
}

public struct Nonprofit: Codable, Identifiable, Equatable, Sendable {
    public var id: UUID
    public var name: String
    public init(id: UUID = UUID(), name: String) { self.id = id; self.name = name }
}

public struct Session: Codable, Identifiable, Sendable {
    public var id: UUID { sessionId }
    public var sessionId: UUID
    public var projectId: UUID
    public var project: String
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
    public var schemaVersion = 1
    public var deviceId = UUID()
    public var nonprofits: [Nonprofit] = []
    public var sessions: [Session] = []
    public init() {}
    public var active: Session? { sessions.first { $0.endTimeUtc == nil } }
}

public enum TrackerError: LocalizedError {
    case activeSession, noActiveSession, invalidNonprofit, clockChanged, missingSession, missingActivity, invalidInterval, cannotDelete
    public var errorDescription: String? {
        switch self {
        case .activeSession: "Stop the current session first."
        case .noActiveSession: "There is no active session."
        case .missingSession: "The session could not be found."
        case .cannotDelete: "Only completed sessions under one minute can be deleted."
        case .missingActivity: "Enter what you worked on."
        case .invalidInterval: "End must be after start."
        case .invalidNonprofit: "Enter a unique project name and select it before starting."
        case .clockChanged: "The clock is earlier than the session start. Correct the system clock before stopping."
        }
    }
}

/// Each change is saved atomically before it becomes visible to the caller.
public final class Tracker {
    private func capitalizeEntries(_ value: String) -> String {
        var first = true
        var result = ""
        for character in value {
            result += first && character.isLetter ? String(character).uppercased() : String(character)
            if character.isLetter { first = false }
            if character == "," || character == "\r" || character == "\n" || character == "\r\n" { first = true }
        }
        return result
    }
    public private(set) var state: TrackerState
    public let file: URL
    private var snapshot: Data?
    public init(file: URL, requireExisting: Bool = false) throws {
        self.file = file
        if FileManager.default.fileExists(atPath: file.path) {
            let data = try Data(contentsOf: file)
            state = try PortableData.decode(data)
            snapshot = data
        } else {
            if requireExisting { throw CocoaError(.fileNoSuchFile) }
            state = TrackerState()
        }
    }
    private func save(_ next: TrackerState) throws {
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        let current = FileManager.default.fileExists(atPath: file.path) ? try Data(contentsOf: file) : nil
        guard current == snapshot else { throw PortableData.Error.changed }
        let data = try PortableData.encode(next)
        try data.write(to: file, options: .atomic)
        snapshot = data
        state = next
    }
    public func saveAs(_ destination: URL) throws -> Tracker {
        if destination.standardizedFileURL == file.standardizedFileURL {
            try save(state)
            return self
        }
        let data = try PortableData.encode(state)
        try data.write(to: destination, options: .atomic)
        return try Tracker(file: destination, requireExisting: true)
    }
    @discardableResult public func addNonprofit(_ name: String) throws -> UUID {
        let name = capitalizeEntries(name.trimmingCharacters(in: .whitespacesAndNewlines))
        guard !name.isEmpty, !state.nonprofits.contains(where: { $0.name.caseInsensitiveCompare(name) == .orderedSame }) else { throw TrackerError.invalidNonprofit }
        let nonprofit = Nonprofit(name: name)
        var next = state
        next.nonprofits.append(nonprofit)
        try save(next)
        return nonprofit.id
    }
    public func start(projectId: UUID, notes: String = "", platform: String = "macos", now: Date = Date()) throws {
        guard state.active == nil else { throw TrackerError.activeSession }
        guard let nonprofit = state.nonprofits.first(where: { $0.id == projectId }) else { throw TrackerError.invalidNonprofit }
        var next = state
        next.sessions.append(Session(sessionId: UUID(), projectId: nonprofit.id, project: nonprofit.name, startTimeUtc: now, notes: capitalizeEntries(notes), deviceId: state.deviceId, platform: platform, updatedAtUtc: now, syncState: "pending"))
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
    public func addSession(projectId: UUID, notes: String, start: Date, end: Date, platform: String = "macos", now: Date = Date()) throws {
        guard let nonprofit = state.nonprofits.first(where: { $0.id == projectId }) else { throw TrackerError.invalidNonprofit }
        guard !notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw TrackerError.missingActivity }
        guard end > start else { throw TrackerError.invalidInterval }
        var next = state
        next.sessions.append(Session(sessionId: UUID(), projectId: nonprofit.id, project: nonprofit.name,
            startTimeUtc: start, endTimeUtc: end, durationSeconds: Int(end.timeIntervalSince(start)), notes: capitalizeEntries(notes),
            deviceId: state.deviceId, platform: platform, updatedAtUtc: now, syncState: "pending"))
        try save(next)
    }
    public func deleteSession(sessionId: UUID) throws {
        guard let session = state.sessions.first(where: { $0.sessionId == sessionId }) else { throw TrackerError.missingSession }
        guard session.endTimeUtc != nil, let seconds = session.durationSeconds, seconds >= 0, seconds < 60 else { throw TrackerError.cannotDelete }
        var next = state
        next.sessions.removeAll { $0.sessionId == sessionId }
        try save(next)
    }
    public func updateTimes(sessionId: UUID, start: Date, end: Date, now: Date = Date()) throws {
        guard let index = state.sessions.firstIndex(where: { $0.sessionId == sessionId }) else { throw TrackerError.missingSession }
        guard state.sessions[index].endTimeUtc != nil else { throw TrackerError.activeSession }
        let seconds = end.timeIntervalSince(start)
        guard start.timeIntervalSince1970.isFinite, end.timeIntervalSince1970.isFinite,
              seconds.isFinite, seconds > 0, seconds < Double(Int.max) else { throw TrackerError.invalidInterval }
        var next = state
        next.sessions[index].startTimeUtc = start
        next.sessions[index].endTimeUtc = end
        next.sessions[index].durationSeconds = Int(seconds)
        next.sessions[index].updatedAtUtc = now
        next.sessions[index].syncState = "pending"
        try save(next)
    }
    public func updateNotes(sessionId: UUID, notes: String, now: Date = Date()) throws {
        guard let index = state.sessions.firstIndex(where: { $0.sessionId == sessionId }) else { throw TrackerError.missingSession }
        var next = state
        next.sessions[index].notes = capitalizeEntries(notes)
        next.sessions[index].updatedAtUtc = now
        next.sessions[index].syncState = "pending"
        try save(next)
    }
    public func exportSessions(range: ExportRange? = nil) -> [Session] {
        state.sessions.filter { session in
            session.endTimeUtc != nil && (range.map { session.startTimeUtc >= $0.start && session.startTimeUtc < $0.end } ?? true)
        }.sorted { $0.startTimeUtc < $1.startTimeUtc }
    }
    public func clipboardText(range: ExportRange? = nil) -> String {
        func activities(_ value: String) -> [String] {
            let lines = value.components(separatedBy: CharacterSet.newlines.union(CharacterSet(charactersIn: ",")))
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            return lines.isEmpty ? ["No notes"] : lines
        }
        func duration(_ seconds: Int) -> String {
            String(format: "%02d:%02d:%02d", seconds / 3600, seconds % 3600 / 60, seconds % 60)
        }
        let sessions = exportSessions(range: range)
        let groups = Dictionary(grouping: sessions, by: \.projectId)
        var seen = Set<UUID>()
        return sessions.compactMap { session -> String? in
            guard seen.insert(session.projectId).inserted else { return nil }
            let group = groups[session.projectId]!
            let total = group.reduce(0) { $0 + ($1.durationSeconds ?? 0) }
            var descriptions: [String: Int] = [:]
            for entry in group {
                let names = activities(entry.notes)
                let seconds = entry.durationSeconds ?? 0
                for (index, name) in names.enumerated() {
                    descriptions[name, default: 0] += seconds / names.count + (index < seconds % names.count ? 1 : 0)
                }
            }
            let names = descriptions.keys.sorted {
                let left = $0.lowercased(), right = $1.lowercased()
                return left == right ? $0 < $1 : left < right
            }
            return "\(session.project) \(duration(total)):\n" + names.map { name in
                let seconds = descriptions[name]!
                return "\(name)   \(duration(seconds))"
            }.joined(separator: "\n")
        }.joined(separator: "\n\n")
    }
    public func csv(range: ExportRange? = nil) -> String {
        let formatter = ISO8601DateFormatter()
        func cell(_ value: String) -> String {
            // Prevent spreadsheet formulas when user-entered values are imported.
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            let safe = ["=", "+", "-", "@"].contains(where: { trimmed.hasPrefix($0) }) ? "'" + value : value
            return "\"" + safe.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        var rows = ["project,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform"]
        for s in exportSessions(range: range) {
            let values = [s.project, formatter.string(from: s.startTimeUtc), formatter.string(from: s.endTimeUtc!), String(s.durationSeconds ?? 0), String(Double(s.durationSeconds ?? 0) / 3600), s.notes, s.deviceId.uuidString, s.platform]
            rows.append(values.map(cell).joined(separator: ","))
        }
        return rows.joined(separator: "\r\n") + "\r\n"
    }
}
