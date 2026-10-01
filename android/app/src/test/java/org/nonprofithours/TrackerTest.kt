package org.nonprofithours
import org.junit.Assert.*
import org.junit.Test
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

class TrackerTest {
    @Test fun manualSessionPersistsAndPreservesTimer() {
        val tracker = Tracker(TrackerState()) {}
        val id = tracker.addNonprofit("Kitchen")
        tracker.start(id, "Active", Instant.EPOCH)
        val active = tracker.state.active
        val end = Instant.EPOCH.plusSeconds(7200)
        tracker.addSession(id, "Meals", Instant.EPOCH, end)
        val restored = PortableData.decode(PortableData.encode(tracker.state))
        assertEquals(active, restored.active)
        assertEquals(7200L, tracker.exportSessions().single().durationSeconds)
        assertTrue(tracker.csv().contains("Meals"))
        assertEquals("Kitchen 02:00:00:\nMeals   02:00:00", tracker.clipboardText())
        val original = tracker.state
        for ((key, notes, start, stop) in listOf(
            listOf(id, "Meals", end.toString(), Instant.EPOCH.toString()),
            listOf(id, "Meals", Instant.EPOCH.toString(), Instant.EPOCH.toString()),
            listOf(id, " ", Instant.EPOCH.toString(), end.toString()),
            listOf("missing", "Meals", Instant.EPOCH.toString(), end.toString()))) {
            try { tracker.addSession(key, notes, Instant.parse(start), Instant.parse(stop)); fail("Expected validation error") }
            catch (_: IllegalArgumentException) {}
        }
        assertEquals(original, tracker.state)
        val failing = Tracker(original) { throw java.io.IOException("Disk full") }
        try { failing.addSession(id, "Meals", Instant.EPOCH, end); fail("Expected save error") }
        catch (_: java.io.IOException) {}
        assertEquals(original, failing.state)
    }
    @Test fun clipboardNormalizesNotesWithoutChangingStoredText() {
        for ((notes, expected) in listOf("" to "No notes", " \t\r\n " to "No notes",
            "Annual meeting\nGoogle Fi" to "Annual meeting, Google Fi",
            "Annual meeting\rGoogle Fi" to "Annual meeting, Google Fi",
            " Annual meeting\r\n \r\nGoogle Fi " to "Annual meeting, Google Fi")) {
            val tracker = Tracker(TrackerState()) {}
            val id = tracker.addNonprofit("NEST")
            tracker.start(id, notes, Instant.EPOCH)
            tracker.stop(Instant.EPOCH.plusSeconds(1423))
            assertEquals("NEST 00:23:43:\n$expected   00:23:43", tracker.clipboardText())
            assertEquals(notes, tracker.state.sessions.single().notes)
        }
    }
    @Test fun clipboardGroupsTotalsAndListsEachNoteInTimeOrder() {
        val tracker = Tracker(TrackerState()) {}
        val kitchen = tracker.addNonprofit("Kitchen")
        val garden = tracker.addNonprofit("Garden")
        var start = Instant.EPOCH
        for ((id, notes, seconds) in listOf(Triple(kitchen, "Meals", 3600L), Triple(garden, "Planting", 1800L), Triple(kitchen, "Cleanup", 2700L))) {
            tracker.start(id, notes, start)
            start = start.plusSeconds(seconds)
            tracker.stop(start)
        }
        assertEquals("Kitchen 01:45:00:\nMeals   01:00:00\nCleanup   00:45:00\n\nGarden 00:30:00:\nPlanting   00:30:00", tracker.clipboardText())
    }
    @Test fun exportPeriodsAndClipboard() {
        assertEquals(ExportRange(LocalDate.parse("2024-12-30"), LocalDate.parse("2025-01-06")),
            ExportRange.forDate(ExportPeriod.Weekly, LocalDate.parse("2025-01-05")))
        assertEquals(LocalDate.parse("2025-01-01"), ExportRange.forDate(ExportPeriod.Monthly, LocalDate.parse("2024-12-12")).end)
        assertEquals(LocalDate.parse("2024-03-01"), ExportRange.forDate(ExportPeriod.Daily, LocalDate.parse("2024-02-29")).end)
        val tracker = Tracker(TrackerState()) {}
        val id = tracker.addNonprofit("Kitchen")
        val start = Instant.parse("2024-12-31T22:00:00Z")
        tracker.start(id, "Outside", start.minusSeconds(1))
        tracker.stop(start)
        val notes = "Meals, \"served\"\nCleanup 🍲"
        tracker.start(id, notes, start)
        tracker.stop(start.plusSeconds(90000))
        tracker.start(id, "End boundary", start.plusSeconds(86400))
        tracker.stop(start.plusSeconds(86460))
        tracker.start(id, "Active", start.plusSeconds(120))
        val range = ExportRange.forDate(ExportPeriod.Daily, LocalDate.parse("2025-01-01"))
        val zone = ZoneId.of("+02:00")
        assertEquals(1, tracker.exportSessions(range, zone).size)
        assertEquals("Kitchen 25:00:00:\nMeals, \"served\", Cleanup 🍲   25:00:00", tracker.clipboardText(range, zone))
        assertFalse(tracker.csv(range, zone).contains("Outside"))
        assertFalse(tracker.csv(range, zone).contains("Active"))
        assertFalse(tracker.csv(range, zone).contains("End boundary"))
        assertEquals("", tracker.clipboardText(ExportRange.forDate(ExportPeriod.Daily, LocalDate.parse("2025-01-03")), zone))
    }
    @Test fun editNotesPersistsWithoutChangingHours() {
        val tracker = Tracker(TrackerState()) {}
        val id = tracker.addNonprofit("Kitchen")
        tracker.start(id, "Original", Instant.EPOCH)
        tracker.stop(Instant.EPOCH.plusSeconds(3600))
        val original = tracker.state.sessions.single().copy(syncState = "synced")
        var saved = ""
        val editor = Tracker(tracker.state.copy(sessions = listOf(original))) { saved = Json.encodeToString(it) }
        val editedAt = Instant.EPOCH.plusSeconds(7200)
        for (notes in listOf("Meals, \"served\"\nCleanup 🍲", "")) {
            editor.updateNotes(original.sessionId, notes, editedAt)
            val restored = Json.decodeFromString<TrackerState>(saved)
            assertEquals(original.copy(notes = notes, updatedAtUtc = editedAt.toString(), syncState = "pending"), restored.sessions.single())
            assertTrue(editor.csv().contains("\"" + notes.replace("\"", "\"\"") + "\""))
        }
        val before = editor.state
        val failing = Tracker(before) { error("Disk full") }
        assertThrows(IllegalStateException::class.java) { failing.updateNotes(original.sessionId, "Unsaved") }
        assertThrows(IllegalArgumentException::class.java) { failing.updateNotes("missing", "Unsaved") }
        assertEquals(before, failing.state)
    }
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
        assertEquals("nonprofitName,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform", tracker.csv().substringBefore("\r\n"))
        assertFalse(tracker.csv().contains(id))
        assertFalse(tracker.csv().contains(tracker.state.sessions.single().sessionId))
        assertTrue(tracker.csv().contains("\"'=SUM(1,2)\""))
        assertTrue(tracker.csv().contains("\"A, \"\"quote\"\"\nline\""))
    }
}
