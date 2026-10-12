package org.nonprofithours

import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.Duration
import java.time.LocalDate
import java.time.ZoneId
import java.util.UUID

@Serializable data class Nonprofit(val id: String = UUID.randomUUID().toString(), val name: String)
@Serializable data class Session(
    val sessionId: String = UUID.randomUUID().toString(), val projectId: String,
    val project: String, val startTimeUtc: String, val endTimeUtc: String? = null,
    val durationSeconds: Long? = null, val notes: String, val deviceId: String,
    val platform: String = "android", val updatedAtUtc: String, val syncState: String = "pending"
)
data class SessionConflict(val session: Session, val start: Instant, val end: Instant, val existingEnd: Instant) {
    val duration: Duration get() = Duration.between(Instant.parse(session.startTimeUtc), existingEnd)
    val overlap: Duration get() = Duration.between(start, end)
    override fun toString(): String {
        fun durationText(value: Duration): String = "%02d:%02d:%02d".format(value.seconds / 3600, value.seconds / 60 % 60, value.seconds % 60)
        val format = java.time.format.DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss z").withZone(ZoneId.systemDefault())
        return "${session.notes.trim().ifEmpty { "No notes" }} — ${session.project}\nDuration: ${durationText(duration)}${if (session.endTimeUtc == null) " (running, so far)" else ""}\nOverlap: ${durationText(overlap)}\n${format.format(start)} – ${format.format(end)}"
    }
}
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
class Tracker(initial: TrackerState, private val reload: (() -> TrackerState)? = null, private val save: (TrackerState) -> Unit) {
    private fun capitalizeEntries(value: String): String {
        var first = true
        return buildString {
            value.forEach { character ->
                append(if (first && character.isLetter()) character.uppercaseChar() else character)
                if (character.isLetter()) first = false
                if (character in listOf(',', '\r', '\n')) first = true
            }
        }
    }
    var state = initial
        private set
    private fun commit(next: TrackerState) { save(next); state = next }
    fun addNonprofit(input: String): String {
        val name = capitalizeEntries(input.trim())
        require(name.isNotEmpty() && state.nonprofits.none { it.name.equals(name, true) }) { "Enter a unique project name." }
        val nonprofit = Nonprofit(name = name)
        commit(state.copy(nonprofits = state.nonprofits + nonprofit))
        return nonprofit.id
    }
    fun start(id: String, notes: String = "", now: Instant = Instant.now()) {
        reload?.let { state = it() }
        check(state.active == null) { "Stop the current session first." }
        val nonprofit = requireNotNull(state.nonprofits.find { it.id == id }) { "Select a project." }
        val session = Session(projectId = id, project = nonprofit.name, startTimeUtc = now.toString(),
            notes = capitalizeEntries(notes), deviceId = state.deviceId, updatedAtUtc = now.toString())
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
    fun sessionConflicts(start: Instant, end: Instant, now: Instant = Instant.now()): List<SessionConflict> {
        if (end <= start) return emptyList()
        return state.sessions.mapNotNull { session ->
            val existingEnd = session.endTimeUtc?.let { Instant.parse(it) } ?: now
            val lower = maxOf(start, Instant.parse(session.startTimeUtc))
            val upper = minOf(end, existingEnd)
            if (upper > lower) SessionConflict(session, lower, upper, existingEnd) else null
        }.sortedBy { it.start }
    }
    fun addSession(id: String, notes: String, start: Instant, end: Instant, now: Instant = Instant.now()) {
        val nonprofit = requireNotNull(state.nonprofits.find { it.id == id }) { "Select a project." }
        require(notes.isNotBlank()) { "Enter what you worked on." }
        require(end.isAfter(start)) { "End must be after start." }
        val session = Session(projectId = id, project = nonprofit.name, startTimeUtc = start.toString(),
            endTimeUtc = end.toString(), durationSeconds = Duration.between(start, end).seconds,
            notes = capitalizeEntries(notes), deviceId = state.deviceId, updatedAtUtc = now.toString())
        commit(state.copy(sessions = state.sessions + session))
    }
    fun deleteSession(sessionId: String) {
        val session = requireNotNull(state.sessions.find { it.sessionId == sessionId }) { "The session could not be found." }
        require(session.endTimeUtc != null && session.durationSeconds != null && session.durationSeconds in 0L..59L) { "Only completed sessions under one minute can be deleted." }
        commit(state.copy(sessions = state.sessions.filter { it.sessionId != sessionId }))
    }
    fun updateTimes(sessionId: String, start: Instant, end: Instant, now: Instant = Instant.now()) {
        val session = state.sessions.find { it.sessionId == sessionId }
            ?: throw IllegalArgumentException("The session could not be found.")
        require(session.endTimeUtc != null) { "Stop the session before editing its times." }
        require(end > start) { "End must be after start." }
        val updated = session.copy(startTimeUtc = start.toString(), endTimeUtc = end.toString(),
            durationSeconds = Duration.between(start, end).seconds, updatedAtUtc = now.toString(), syncState = "pending")
        commit(state.copy(sessions = state.sessions.map { if (it.sessionId == sessionId) updated else it }))
    }
    fun updateNotes(sessionId: String, notes: String, now: Instant = Instant.now()) {
        require(state.sessions.any { it.sessionId == sessionId }) { "The session could not be found." }
        commit(state.copy(sessions = state.sessions.map {
            if (it.sessionId != sessionId) it else it.copy(notes = capitalizeEntries(notes), updatedAtUtc = now.toString(), syncState = "pending")
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
        val projectNames = state.nonprofits.associate { it.id to it.name }
        return exportSessions(range, zone).groupBy { it.projectId }.values.joinToString("\n\n") { sessions ->
            "${projectNames[sessions.first().projectId] ?: sessions.first().project} ${duration(sessions.sumOf { it.durationSeconds ?: 0 })}:\n" +
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
            listOf(s.project, s.startTimeUtc, s.endTimeUtc.orEmpty(),
                s.durationSeconds.toString(), ((s.durationSeconds ?: 0) / 3600.0).toString(), s.notes,
                s.deviceId, s.platform).joinToString(",") { cell(it) }
        }
        return (listOf("project,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform") + rows).joinToString("\r\n") + "\r\n"
    }
}
