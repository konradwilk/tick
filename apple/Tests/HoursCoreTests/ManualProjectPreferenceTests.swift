import Foundation
import XCTest
@testable import HoursCore

final class ManualProjectPreferenceTests: XCTestCase {
    func testSelectionSurvivesReopeningAndStaysIndependentOfTracking() throws {
        let suite = "ManualProjectPreferenceTests-\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let tracking = UUID(), first = UUID(), second = UUID()
        defaults.set(tracking.uuidString, forKey: "lastSelectedProject")
        XCTAssertNil(ManualProjectPreference.selection(projectIDs: [first, second], defaults: defaults))
        ManualProjectPreference.remember(first, defaults: defaults)
        let reopened = try XCTUnwrap(UserDefaults(suiteName: suite))
        XCTAssertEqual(ManualProjectPreference.selection(projectIDs: [first, second], defaults: reopened), first)
        ManualProjectPreference.remember(second, defaults: reopened)
        XCTAssertEqual(ManualProjectPreference.selection(projectIDs: [first, second], defaults: defaults), second)
        XCTAssertEqual(defaults.string(forKey: "lastSelectedProject"), tracking.uuidString)
        XCTAssertNil(ManualProjectPreference.selection(projectIDs: [first], defaults: defaults))
        XCTAssertNil(ManualProjectPreference.selection(projectIDs: [], defaults: defaults))
        defaults.set("invalid", forKey: "lastManualProject")
        XCTAssertNil(ManualProjectPreference.selection(projectIDs: [first], defaults: defaults))
        ManualProjectPreference.remember(first, defaults: defaults)
        ManualProjectPreference.remember(nil, defaults: defaults)
        XCTAssertNil(ManualProjectPreference.selection(projectIDs: [first], defaults: reopened))
    }
}
