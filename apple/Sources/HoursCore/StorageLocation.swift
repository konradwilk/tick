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
