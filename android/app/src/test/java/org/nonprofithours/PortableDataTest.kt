package org.nonprofithours

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class PortableDataTest {
    @Test fun encodingOrdersSessionsByInstantWithoutChangingInput() {
        val tracker = Tracker(TrackerState()) {}
        val id = tracker.addNonprofit("Kitchen")
        tracker.start(id, "Early", Instant.EPOCH)
        tracker.stop(Instant.EPOCH.plusSeconds(60))
        val early = tracker.state.sessions.single()
        val late = early.copy(sessionId = java.util.UUID.randomUUID().toString(),
            startTimeUtc = "1970-01-01T02:00:00+01:00", endTimeUtc = "1970-01-01T02:01:00+01:00")
        val input = tracker.state.copy(sessions = listOf(late, early))
        assertEquals(listOf(early, late), PortableData.decode(PortableData.encode(input)).sessions)
        assertEquals(listOf(late, early), input.sessions)
    }

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
