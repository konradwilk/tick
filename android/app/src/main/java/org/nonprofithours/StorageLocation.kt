package org.nonprofithours

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.util.AtomicFile
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import java.io.File
import java.time.Duration
import java.time.Instant
import java.util.UUID

internal object PortableData {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true; prettyPrint = true }
    fun decode(bytes: ByteArray): TrackerState {
        val root = json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject.toMutableMap()
        if ("schemaVersion" !in root) {
            root["schemaVersion"] = JsonPrimitive(1)
            root["sessions"] = JsonArray(root.getValue("sessions").jsonArray.map { item ->
                val session = item.jsonObject.toMutableMap()
                for (key in listOf("startTimeUtc", "endTimeUtc", "updatedAtUtc")) {
                    val value = session[key] as? JsonPrimitive
                    if (value != null && value !is JsonNull && !value.isString) {
                        val seconds = value.double
                        require(seconds.isFinite()) { "Invalid saved timestamp." }
                        val whole = kotlin.math.floor(seconds).toLong()
                        session[key] = JsonPrimitive(Instant.parse("2001-01-01T00:00:00Z")
                            .plusSeconds(whole).plusNanos(((seconds - whole) * 1_000_000_000).toLong()).toString())
                    }
                }
                JsonObject(session)
            })
        }
        return json.decodeFromJsonElement<TrackerState>(JsonObject(root)).also { validate(it) }
    }
    fun encode(state: TrackerState): ByteArray {
        validate(state)
        return json.encodeToString(state).toByteArray(Charsets.UTF_8)
    }
    private fun validate(state: TrackerState) {
        require(state.schemaVersion == 1) { "Unsupported data file version." }
        UUID.fromString(state.deviceId)
        val nonprofits = state.nonprofits.map { UUID.fromString(it.id) }.toSet()
        require(nonprofits.size == state.nonprofits.size) { "Duplicate nonprofit identity." }
        require(state.sessions.map { UUID.fromString(it.sessionId) }.toSet().size == state.sessions.size) { "Duplicate session identity." }
        require(state.sessions.count { it.endTimeUtc == null } <= 1) { "Multiple active sessions." }
        state.sessions.forEach { session ->
            UUID.fromString(session.deviceId)
            require(UUID.fromString(session.nonprofitId) in nonprofits) { "Unknown nonprofit." }
            require(session.platform in listOf("android", "ios", "macos", "windows", "linux")) { "Invalid platform." }
            require(session.syncState in listOf("pending", "synced", "failed")) { "Invalid sync state." }
            val start = Instant.parse(session.startTimeUtc)
            Instant.parse(session.updatedAtUtc)
            if (session.endTimeUtc == null) require(session.durationSeconds == null) { "Active session has a duration." }
            else {
                val elapsed = Duration.between(start, Instant.parse(session.endTimeUtc))
                val seconds = requireNotNull(session.durationSeconds) { "Missing duration." }
                require(!elapsed.isNegative && seconds >= 0 && kotlin.math.abs(seconds.toDouble() - elapsed.seconds - elapsed.nano / 1e9) < 1.01) { "Invalid duration." }
            }
        }
    }
}

class StorageLocation(private val context: Context) {
    private val preferences = context.getSharedPreferences("hours-location", Context.MODE_PRIVATE)
    var label: String = "Private app storage"
        private set

    fun open(): Tracker {
        val saved = preferences.getString("tree", null)
        if (saved != null) {
            val tree = Uri.parse(saved)
            val file = requireNotNull(findData(tree)) { "The selected data file is missing. Select its folder again." }
            val tracker = documentTracker(file)
            label = tree.toString()
            return tracker
        }
        val file = AtomicFile(File(context.filesDir, "sessions.json"))
        fun read(): ByteArray? = try { file.readFully() } catch (error: java.io.FileNotFoundException) {
            if (file.baseFile.exists()) throw error else null
        }
        return tracker(::read) { bytes ->
            val stream = file.startWrite()
            try { stream.write(bytes); file.finishWrite(stream) }
            catch (error: Exception) { file.failWrite(stream); throw error }
        }
    }
    fun select(tree: Uri, current: Tracker?): Tracker {
        context.contentResolver.takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        val file = findData(tree) ?: run {
            val bytes = PortableData.encode(requireNotNull(current) { "Choose a folder containing saved hours." }.state)
            val parent = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
            val created = requireNotNull(DocumentsContract.createDocument(context.contentResolver, parent, "application/json", "nonprofit-hours.json")) { "Could not create data file." }
            try { writeDocument(created, bytes) }
            catch (error: Exception) {
                runCatching { DocumentsContract.deleteDocument(context.contentResolver, created) }
                throw error
            }
            created
        }
        val next = documentTracker(file)
        check(preferences.edit().putString("tree", tree.toString()).commit()) { "Could not remember the data folder." }
        label = tree.toString()
        return next
    }
    private fun findData(tree: Uri): Uri? {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val columns = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME)
        requireNotNull(context.contentResolver.query(children, columns, null, null, null)) { "Could not read the selected folder." }.use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getString(1) == "nonprofit-hours.json")
                    return DocumentsContract.buildDocumentUriUsingTree(tree, cursor.getString(0))
            }
        }
        return null
    }
    private fun readDocument(file: Uri): ByteArray = requireNotNull(context.contentResolver.openInputStream(file)) { "Could not read data file." }.use { it.readBytes() }
    private fun writeDocument(file: Uri, bytes: ByteArray) {
        requireNotNull(context.contentResolver.openOutputStream(file, "wt")) { "Could not write data file." }.use { it.write(bytes); it.flush() }
    }
    private fun documentTracker(file: Uri): Tracker = tracker({ readDocument(file) }) { bytes ->
        val original = readDocument(file)
        try { writeDocument(file, bytes) }
        catch (error: Exception) {
            try { writeDocument(file, original) } catch (restore: Exception) { error.addSuppressed(restore) }
            throw error
        }
    }
    private fun tracker(read: () -> ByteArray?, write: (ByteArray) -> Unit): Tracker {
        var snapshot = read()
        val initial = snapshot?.let { PortableData.decode(it) } ?: TrackerState()
        return Tracker(initial) { next ->
            check(read().contentEquals(snapshot)) { "The data file changed or was removed. Select its folder again before saving." }
            val bytes = PortableData.encode(next)
            write(bytes)
            snapshot = bytes
        }
    }
}
