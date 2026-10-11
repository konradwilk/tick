import Foundation

/// Retains security-scoped access for the lifetime of the selected data folder.
public final class StorageLocation {
    private let defaults: UserDefaults
    private var accessed: URL?
    public init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    deinit { accessed?.stopAccessingSecurityScopedResource() }
    public func resolve(defaultURL: URL) throws -> (url: URL, selected: Bool) {
        guard let bookmark = defaults.data(forKey: "hours.dataFolder") else { return (defaultURL, false) }
        var stale = false
        #if os(macOS)
        let options: URL.BookmarkResolutionOptions = [.withSecurityScope, .withoutUI]
        #else
        let options: URL.BookmarkResolutionOptions = [.withoutUI]
        #endif
        let url = try URL(resolvingBookmarkData: bookmark, options: options, relativeTo: nil, bookmarkDataIsStale: &stale)
        if url.startAccessingSecurityScopedResource() { accessed = url }
        if stale { try remember(url) }
        return (url, true)
    }
    public func remember(_ url: URL) throws {
        #if os(macOS)
        let options: URL.BookmarkCreationOptions = [.withSecurityScope]
        #else
        let options: URL.BookmarkCreationOptions = []
        #endif
        let bookmark = try url.bookmarkData(options: options, includingResourceValuesForKeys: nil, relativeTo: nil)
        let granted = url.startAccessingSecurityScopedResource()
        accessed?.stopAccessingSecurityScopedResource()
        accessed = granted ? url : nil
        defaults.set(bookmark, forKey: "hours.dataFolder")
    }
}


/// Manual entry keeps its own preference, independent of the running timer.
public enum ManualProjectPreference {
    private static let key = "lastManualProject"

    public static func selection(projectIDs: [UUID], defaults: UserDefaults = .standard) -> UUID? {
        guard let value = defaults.string(forKey: key), let id = UUID(uuidString: value),
              projectIDs.contains(id) else { return nil }
        return id
    }

    public static func remember(_ id: UUID?, defaults: UserDefaults = .standard) {
        if let id { defaults.set(id.uuidString, forKey: key) }
        else { defaults.removeObject(forKey: key) }
    }
}
