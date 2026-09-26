package org.nonprofithours

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class PortableDataTest {
    @Test fun sharedDataRoundTripsAndRejectsInvalidDurations() {
        val tracker = Tracker(TrackerState()) {}
        val id = tracker.addNonprofit("Kitchen")
        tracker.start(id, "Meals 🍲", Instant.EPOCH)
        tracker.stop(Instant.EPOCH.plusSeconds(60))
        assertEquals(tracker.state, PortableData.decode(PortableData.encode(tracker.state)))
        val original = tracker.state.sessions.single()
        assertThrows(IllegalArgumentException::class.java) {
            PortableData.encode(tracker.state.copy(sessions = listOf(original.copy(durationSeconds = 999))))
        }
        assertThrows(IllegalArgumentException::class.java) {
            PortableData.encode(tracker.state.copy(sessions = listOf(original, original)))
        }
        assertThrows(IllegalArgumentException::class.java) { PortableData.encode(tracker.state.copy(schemaVersion = 99)) }
    }
}
