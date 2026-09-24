package org.nonprofithours

import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.Duration
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
    val nonprofits: List<Nonprofit> = emptyList(), val sessions: List<Session> = emptyList()
) { val active: Session? get() = sessions.firstOrNull { it.endTimeUtc == null } }

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
    fun csv(): String {
        fun cell(value: String): String {
            val safe = if (value.trimStart().firstOrNull() in listOf('=', '+', '-', '@')) "'$value" else value
            return "\"${safe.replace("\"", "\"\"")}\""
        }
        val rows = state.sessions.filter { it.endTimeUtc != null }.map { s ->
            listOf(s.sessionId, s.nonprofitId, s.nonprofitName, s.startTimeUtc, s.endTimeUtc.orEmpty(),
                s.durationSeconds.toString(), ((s.durationSeconds ?: 0) / 3600.0).toString(), s.notes,
                s.deviceId, s.platform, s.updatedAtUtc).joinToString(",") { cell(it) }
        }
        return (listOf("sessionId,nonprofitId,nonprofitName,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform,updatedAtUtc") + rows).joinToString("\r\n") + "\r\n"
    }
}
