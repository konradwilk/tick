package org.nonprofithours

import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.Duration
import java.time.LocalDate
import java.time.ZoneId
import java.util.UUID

@Serializable data class Nonprofit(val id: String = UUID.randomUUID().toString(), val name: String)
@Serializable data class Session(
    val sessionId: String = UUID.randomUUID().toString(), val nonprofitId: String,
    val nonprofitName: String, val startTimeUtc: String, val endTimeUtc: String? = null,
    val durationSeconds: Long? = null, val notes: String, val deviceId: String,
    val platform: String = "android", val updatedAtUtc: String, val syncState: String = "pending"
)
@Serializable data class TrackerState(
    val deviceId: String = UUID.randomUUID().toString(),
    val nonprofits: List<Nonprofit> = emptyList(), val sessions: List<Session> = emptyList(),
    val schemaVersion: Int = 1
) { val active: Session? get() = sessions.firstOrNull { it.endTimeUtc == null } }

enum class ExportPeriod { Daily, Weekly, Monthly }
data class ExportRange(val start: LocalDate, val end: LocalDate) {
    companion object {
        fun forDate(period: ExportPeriod, date: LocalDate): ExportRange {
            val start = when (period) {
                ExportPeriod.Daily -> date
                ExportPeriod.Weekly -> date.minusDays((date.dayOfWeek.value - 1).toLong())
                ExportPeriod.Monthly -> date.withDayOfMonth(1)
            }
            return ExportRange(start, when (period) {
                ExportPeriod.Daily -> start.plusDays(1)
                ExportPeriod.Weekly -> start.plusDays(7)
                ExportPeriod.Monthly -> start.plusMonths(1)
            })
        }
    }
}
class Tracker(initial: TrackerState, private val save: (TrackerState) -> Unit) {
    var state = initial
        private set
    private fun commit(next: TrackerState) { save(next); state = next }
    fun addNonprofit(input: String): String {
        val name = input.trim()
        require(name.isNotEmpty() && state.nonprofits.none { it.name.equals(name, true) }) { "Enter a unique nonprofit name." }
        val nonprofit = Nonprofit(name = name)
        commit(state.copy(nonprofits = state.nonprofits + nonprofit))
        return nonprofit.id
    }
    fun start(id: String, notes: String = "", now: Instant = Instant.now()) {
        check(state.active == null) { "Stop the current session first." }
        val nonprofit = requireNotNull(state.nonprofits.find { it.id == id }) { "Select a nonprofit." }
        val session = Session(nonprofitId = id, nonprofitName = nonprofit.name, startTimeUtc = now.toString(),
            notes = notes, deviceId = state.deviceId, updatedAtUtc = now.toString())
        commit(state.copy(sessions = state.sessions + session))
    }
    fun stop(now: Instant = Instant.now()) {
        val active = checkNotNull(state.active) { "There is no active session." }
        val start = Instant.parse(active.startTimeUtc)
        require(!now.isBefore(start)) { "Correct the system clock before stopping." }
        commit(state.copy(sessions = state.sessions.map {
            if (it.sessionId != active.sessionId) it else it.copy(endTimeUtc = now.toString(),
                durationSeconds = Duration.between(start, now).seconds, updatedAtUtc = now.toString())
        }))
    }
    fun addSession(id: String, notes: String, start: Instant, end: Instant, now: Instant = Instant.now()) {
        val nonprofit = requireNotNull(state.nonprofits.find { it.id == id }) { "Select a nonprofit." }
        require(notes.isNotBlank()) { "Enter what you worked on." }
        require(end.isAfter(start)) { "End must be after start." }
        val session = Session(nonprofitId = id, nonprofitName = nonprofit.name, startTimeUtc = start.toString(),
            endTimeUtc = end.toString(), durationSeconds = Duration.between(start, end).seconds,
            notes = notes, deviceId = state.deviceId, updatedAtUtc = now.toString())
        commit(state.copy(sessions = state.sessions + session))
    }
    fun updateNotes(sessionId: String, notes: String, now: Instant = Instant.now()) {
        require(state.sessions.any { it.sessionId == sessionId }) { "The session could not be found." }
        commit(state.copy(sessions = state.sessions.map {
            if (it.sessionId != sessionId) it else it.copy(notes = notes, updatedAtUtc = now.toString(), syncState = "pending")
        }))
    }
    fun exportSessions(range: ExportRange? = null, zone: ZoneId = ZoneId.systemDefault()): List<Session> =
        state.sessions.filter {
            val day = Instant.parse(it.startTimeUtc).atZone(zone).toLocalDate()
            it.endTimeUtc != null && (range == null || (!day.isBefore(range.start) && day.isBefore(range.end)))
        }.sortedBy { Instant.parse(it.startTimeUtc) }
    fun clipboardText(range: ExportRange? = null, zone: ZoneId = ZoneId.systemDefault()): String {
        fun activities(session: Session): List<Pair<String, Long>> {
            val names = session.notes.split(',', '\r', '\n').map { it.trim() }.filter { it.isNotEmpty() }.ifEmpty { listOf("No notes") }
            val seconds = session.durationSeconds ?: 0
            return names.mapIndexed { index, name -> name to (seconds / names.size + if (index < seconds % names.size) 1 else 0) }
        }
        fun duration(seconds: Long) = "%02d:%02d:%02d".format(java.util.Locale.ROOT,
            seconds / 3600, seconds % 3600 / 60, seconds % 60)
        return exportSessions(range, zone).groupBy { it.nonprofitId }.values.joinToString("\n\n") { sessions ->
            "${sessions.first().nonprofitName} ${duration(sessions.sumOf { it.durationSeconds ?: 0 })}:\n" +
                sessions.flatMap { activities(it) }.groupBy { it.first }.entries
                    .sortedWith(compareBy<Map.Entry<String, List<Pair<String, Long>>>> { it.key.lowercase(java.util.Locale.ROOT) }.thenBy { it.key })
                    .joinToString("\n") { "${it.key}   ${duration(it.value.sumOf { s -> s.second })}" }
        }
    }
    fun csv(range: ExportRange? = null, zone: ZoneId = ZoneId.systemDefault()): String {
        fun cell(value: String): String {
            val safe = if (value.trimStart().firstOrNull() in listOf('=', '+', '-', '@')) "'$value" else value
            return "\"${safe.replace("\"", "\"\"")}\""
        }
        val rows = exportSessions(range, zone).map { s ->
            listOf(s.nonprofitName, s.startTimeUtc, s.endTimeUtc.orEmpty(),
                s.durationSeconds.toString(), ((s.durationSeconds ?: 0) / 3600.0).toString(), s.notes,
                s.deviceId, s.platform).joinToString(",") { cell(it) }
        }
        return (listOf("nonprofitName,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform") + rows).joinToString("\r\n") + "\r\n"
    }
}
