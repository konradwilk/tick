package org.nonprofithours
import org.junit.Assert.*
import org.junit.Test
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

class TrackerTest {
    @Test fun editTimesRecalculatesDurationAndRejectsInvalidChanges() {
        val tracker = Tracker(TrackerState()) {}
        val id = tracker.addNonprofit("Kitchen")
        val start = Instant.EPOCH
        tracker.addSession(id, "Meals", start, start.plusSeconds(3600))
        val original = tracker.state.sessions.single()
        tracker.start(id, "Active", start.plusSeconds(172800))
        val active = tracker.state.active
        tracker.updateTimes(original.sessionId, start.minusSeconds(86400), start.minusSeconds(84600))
        val updated = tracker.state.sessions.first()
        assertEquals(1800L, updated.durationSeconds)
        assertEquals(original.notes, updated.notes)
        assertEquals(original.sessionId, updated.sessionId)
        assertEquals(active, tracker.state.active)
        assertTrue(tracker.clipboardText().contains("00:30:00"))
        val before = tracker.state
        assertThrows(IllegalArgumentException::class.java) { tracker.updateTimes(original.sessionId, start, start) }
        assertThrows(IllegalArgumentException::class.java) { tracker.updateTimes(original.sessionId, start, start.minusSeconds(1)) }
        assertThrows(IllegalArgumentException::class.java) { tracker.updateTimes(active!!.sessionId, start, start.plusSeconds(60)) }
        assertThrows(IllegalArgumentException::class.java) { tracker.updateTimes("missing", start, start.plusSeconds(60)) }
        assertEquals(before, tracker.state)
        val failing = Tracker(before) { throw java.io.IOException("Disk full") }
        assertThrows(java.io.IOException::class.java) { failing.updateTimes(original.sessionId, start, start.plusSeconds(7200)) }
        assertEquals(before, failing.state)
        assertEquals(updated, PortableData.decode(PortableData.encode(before)).sessions.first())
    }

    @Test fun capitalizesNewAndEditedActivities() {
        val tracker = Tracker(TrackerState()) {}
        val id = tracker.addNonprofit("kitchen")
        assertEquals("Kitchen", tracker.state.nonprofits.single().name)
        tracker.start(id, "  emails, google Fi\n990-EZ review", Instant.EPOCH)
        assertEquals("  Emails, Google Fi\n990-EZ review", tracker.state.active!!.notes)
        tracker.stop(Instant.EPOCH.plusSeconds(3600))
        tracker.updateNotes(tracker.state.sessions.single().sessionId, "collect payments\r\n\"annual meeting\",MN DOT")
        assertEquals("Collect payments\r\n\"Annual meeting\",MN DOT", tracker.state.sessions.single().notes)
        tracker.addSession(id, "cooking,etc", Instant.EPOCH, Instant.EPOCH.plusSeconds(900))
        assertEquals("Cooking,Etc", tracker.state.sessions.last().notes)
    }
    @Test fun deleteOnlyShortCompletedSessions() {
        val tracker = Tracker(TrackerState()) {}
        val id = tracker.addNonprofit("Kitchen")
        for (seconds in listOf(0L, 59L, 60L)) {
            tracker.start(id, "Short", Instant.EPOCH)
            val sessionId = tracker.state.active!!.sessionId
            try { tracker.deleteSession(sessionId); fail("Active session") } catch (_: IllegalArgumentException) {}
            tracker.stop(Instant.EPOCH.plusSeconds(seconds))
            val original = tracker.state
            if (seconds < 60) {
                val failing = Tracker(original) { throw java.io.IOException("Disk full") }
                try { failing.deleteSession(sessionId); fail("Save failure") } catch (_: java.io.IOException) {}
                assertEquals(original, failing.state)
                tracker.deleteSession(sessionId)
                assertTrue(PortableData.decode(PortableData.encode(tracker.state)).sessions.isEmpty())
                assertEquals("", tracker.clipboardText())
                assertFalse(tracker.csv().contains("Short"))
            } else {
                try { tracker.deleteSession(sessionId); fail("One minute") } catch (_: IllegalArgumentException) {}
            }
        }
        try { tracker.deleteSession("missing"); fail("Missing session") } catch (_: IllegalArgumentException) {}
    }
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
        for ((notes, expected) in listOf("" to "No notes   00:23:43", " \t\r\n " to "No notes   00:23:43",
            "Annual meeting, Google Fi,Cooking,Etc" to "Annual meeting   00:05:56\nCooking   00:05:56\nEtc   00:05:55\nGoogle Fi   00:05:56",
            "Meals,, Meals, " to "Meals   00:23:43", ", ," to "No notes   00:23:43",
            "Annual meeting\nGoogle Fi" to "Annual meeting   00:11:52\nGoogle Fi   00:11:51",
            "Annual meeting\rGoogle Fi" to "Annual meeting   00:11:52\nGoogle Fi   00:11:51",
            " Annual meeting\r\n \r\nGoogle Fi " to "Annual meeting   00:11:52\nGoogle Fi   00:11:51")) {
            val tracker = Tracker(TrackerState()) {}
            val id = tracker.addNonprofit("NEST")
            tracker.start(id, notes, Instant.EPOCH)
            tracker.stop(Instant.EPOCH.plusSeconds(1423))
            assertEquals("NEST 00:23:43:\n$expected", tracker.clipboardText())
            assertEquals(notes, tracker.state.sessions.single().notes)
        }
    }
    @Test fun clipboardCombinesDescriptionsAndSortsAlphabetically() {
        val tracker = Tracker(TrackerState()) {}
        val kitchen = tracker.addNonprofit("Kitchen")
        val garden = tracker.addNonprofit("Garden")
        var start = Instant.EPOCH
        for ((id, notes, seconds) in listOf(Triple(kitchen, "Meals", 3600L), Triple(garden, "Planting", 1800L), Triple(kitchen, "Cleanup", 2700L), Triple(kitchen, " Cleanup ", 60L), Triple(kitchen, "", 1L), Triple(kitchen, " \n ", 2L), Triple(garden, "Cleanup", 120L))) {
            tracker.start(id, notes, start)
            start = start.plusSeconds(seconds)
            tracker.stop(start)
        }
        assertEquals("Kitchen 01:46:03:\nCleanup   00:46:00\nMeals   01:00:00\nNo notes   00:00:03\n\nGarden 00:32:00:\nCleanup   00:02:00\nPlanting   00:30:00", tracker.clipboardText())
        assertEquals(7, tracker.exportSessions().size)
        assertTrue(tracker.csv().contains(" Cleanup "))
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
        val notes = "Meals, \"Served\"\nCleanup 🍲"
        tracker.start(id, notes, start)
        tracker.stop(start.plusSeconds(90000))
        tracker.start(id, "End boundary", start.plusSeconds(86400))
        tracker.stop(start.plusSeconds(86460))
        tracker.start(id, "Active", start.plusSeconds(120))
        val range = ExportRange.forDate(ExportPeriod.Daily, LocalDate.parse("2025-01-01"))
        val zone = ZoneId.of("+02:00")
        assertEquals(1, tracker.exportSessions(range, zone).size)
        assertEquals("Kitchen 25:00:00:\n\"Served\"   08:20:00\nCleanup 🍲   08:20:00\nMeals   08:20:00", tracker.clipboardText(range, zone))
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
        for (notes in listOf("Meals, \"Served\"\nCleanup 🍲", "")) {
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
        tracker.start(id, "A, \"Quote\"\nLine", Instant.EPOCH)
        assertFalse(tracker.csv().contains("SUM"))
        assertThrows(IllegalArgumentException::class.java) { tracker.stop(Instant.EPOCH.minusSeconds(1)) }
        assertNotNull(tracker.state.active)
        tracker.stop(Instant.EPOCH.plusSeconds(60))
        assertEquals("project,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform", tracker.csv().substringBefore("\r\n"))
        assertFalse(tracker.csv().contains(id))
        assertFalse(tracker.csv().contains(tracker.state.sessions.single().sessionId))
        assertTrue(tracker.csv().contains("\"'=SUM(1,2)\""))
        assertTrue(tracker.csv().contains("\"A, \"\"Quote\"\"\nLine\""))
    }
}
