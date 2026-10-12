import XCTest
@testable import HoursCore

final class StorageLocationTests: XCTestCase {
    func testFileBookmarkReopensSameDataFileAndFolderSelectionClearsFileMode() throws {
        let suite = "TickStorageTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("tick.json")
        let tracker = try Tracker(file: file)
        let project = try tracker.addNonprofit("Kitchen")
        try StorageLocation(defaults: defaults).remember(file, isFile: true)
        let reopened = StorageLocation(defaults: defaults)
        let saved = try reopened.resolve(defaultURL: folder)
        XCTAssertTrue(saved.selected)
        XCTAssertTrue(saved.isFile)
        XCTAssertEqual(saved.url.standardizedFileURL, file.standardizedFileURL)
        let restored = try Tracker(file: saved.url, requireExisting: true)
        try restored.start(projectId: project, now: Date(timeIntervalSince1970: 0))
        XCTAssertNotNil(try Tracker(file: file, requireExisting: true).state.active)
        try reopened.remember(folder)
        let folderSelection = try StorageLocation(defaults: defaults).resolve(defaultURL: file)
        XCTAssertTrue(folderSelection.selected)
        XCTAssertFalse(folderSelection.isFile)
    }
}
