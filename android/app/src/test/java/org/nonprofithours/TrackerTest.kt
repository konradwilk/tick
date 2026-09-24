package org.nonprofithours
import org.junit.Assert.*
import org.junit.Test
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.time.Instant

class TrackerTest {
    @Test fun restartStopAndDuplicateStart() {
        var saved = ""
        val tracker = Tracker(TrackerState()) { saved = Json.encodeToString(it) }
        val id = tracker.addNonprofit("Kitchen")
        tracker.start(id, now = Instant.EPOCH)
        assertThrows(IllegalStateException::class.java) { tracker.start(id) }
        val restored = Tracker(Json.decodeFromString<TrackerState>(saved)) {}
        restored.stop(Instant.EPOCH.plusSeconds(3600))
        assertEquals(3600L, restored.state.sessions.single().durationSeconds)
        assertEquals(tracker.state.active?.sessionId, restored.state.sessions.single().sessionId)
        assertNull(restored.state.active)
    }
    @Test fun failedSaveDoesNotPublishState() {
        val nonprofit = Nonprofit(name = "Kitchen")
        val tracker = Tracker(TrackerState(nonprofits = listOf(nonprofit))) { error("Disk full") }
        assertThrows(IllegalStateException::class.java) { tracker.start(nonprofit.id) }
        assertNull(tracker.state.active)
    }
    @Test fun invalidActionsAndExport() {
        val tracker = Tracker(TrackerState()) {}
        assertThrows(IllegalArgumentException::class.java) { tracker.addNonprofit(" ") }
        val id = tracker.addNonprofit("=SUM(1,2)")
        assertThrows(IllegalArgumentException::class.java) { tracker.addNonprofit("=sum(1,2)") }
        tracker.start(id, "A, \"quote\"\nline", Instant.EPOCH)
        assertFalse(tracker.csv().contains("SUM"))
        assertThrows(IllegalArgumentException::class.java) { tracker.stop(Instant.EPOCH.minusSeconds(1)) }
        assertNotNull(tracker.state.active)
        tracker.stop(Instant.EPOCH.plusSeconds(60))
        assertTrue(tracker.csv().contains("\"'=SUM(1,2)\""))
        assertTrue(tracker.csv().contains("\"A, \"\"quote\"\"\nline\""))
    }
}
