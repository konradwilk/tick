package org.timeisclearlykept

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import android.system.Os
import android.system.OsConstants
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
        val ordered = state.copy(sessions = state.sessions.sortedBy { Instant.parse(it.startTimeUtc) })
        return json.encodeToString(ordered).toByteArray(Charsets.UTF_8)
    }
    private fun validate(state: TrackerState) {
        require(state.schemaVersion == 1) { "Unsupported data file version." }
        UUID.fromString(state.deviceId)
        val nonprofits = state.nonprofits.map { UUID.fromString(it.id) }.toSet()
        require(nonprofits.size == state.nonprofits.size) { "Duplicate project identity." }
        require(state.sessions.map { UUID.fromString(it.sessionId) }.toSet().size == state.sessions.size) { "Duplicate session identity." }
        require(state.sessions.count { it.endTimeUtc == null } <= 1) { "Multiple active sessions." }
        state.sessions.forEach { session ->
            UUID.fromString(session.deviceId)
            require(UUID.fromString(session.projectId) in nonprofits) { "Unknown project." }
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

    internal fun selectSheets(store: SheetsStore, current: Tracker?): Tracker {
        val loaded = store.load(false)
        val state = loaded ?: (current?.state ?: TrackerState()).also { store.save(it) }
        val next = Tracker(state, reload = { requireNotNull(store.load()) }, save = store::save)
        check(preferences.edit().putString("sheetId", store.sheetId).putString("sheetsName", store.spreadsheetName).remove("sheetsEndpoint").remove("sheetsKey").commit()) { "Could not remember your spreadsheet." }
        label = "Google Sheets (online)"; return next
    }
    fun open(): Tracker? {
        preferences.getString("sheetId", null)?.let { id ->
            val account = GoogleAccount(context)
            val store = SheetsStore(GoogleSheetsAPI(account::accessToken), id, preferences.getString("sheetsName", "Time is Clearly Kept")!!)
            val next = Tracker(requireNotNull(store.load()), reload = { requireNotNull(store.load()) }, save = store::save)
            label = "Google Sheets (online)"; return next
        }
        check(!preferences.contains("sheetsEndpoint")) { "Reconnect with Google sign-in in Settings. Your previous spreadsheet is unchanged." }

        val saved = preferences.getString("tree", null)
        if (saved != null) {
            val tree = Uri.parse(saved)
            val file = findData(tree) ?: return null
            val tracker = documentTracker(file)
            label = tree.toString()
            return tracker
        }
        val file = AtomicFile(File(context.filesDir, "tick.json"))
        if (!file.baseFile.exists()) return null
        fun read(): ByteArray? = try { file.readFully() } catch (error: java.io.FileNotFoundException) {
            if (file.baseFile.exists()) throw error else null
        }
        return tracker(::read) { bytes ->
            val stream = file.startWrite()
            try { stream.write(bytes); stream.flush(); stream.fd.sync(); file.finishWrite(stream) }
            catch (error: Exception) { file.failWrite(stream); throw error }
        }
    }
    fun select(tree: Uri, current: Tracker?): Tracker {
        context.contentResolver.takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        val file = findData(tree) ?: run {
            val bytes = PortableData.encode(current?.state ?: TrackerState())
            val parent = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
            val created = requireNotNull(DocumentsContract.createDocument(context.contentResolver, parent, "application/json", "tick.json")) { "Could not create data file." }
            try { writeDocument(created, bytes) }
            catch (error: Exception) {
                runCatching { DocumentsContract.deleteDocument(context.contentResolver, created) }
                throw error
            }
            created
        }
        val next = documentTracker(file)
        check(preferences.edit().putString("tree", tree.toString()).remove("sheetId").remove("sheetsEndpoint").remove("sheetsKey").commit()) { "Could not remember the data folder." }
        label = tree.toString()
        return next
    }
    private fun findData(tree: Uri): Uri? {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val columns = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME)
        requireNotNull(context.contentResolver.query(children, columns, null, null, null)) { "Could not read the selected folder." }.use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getString(1) == "tick.json")
                    return DocumentsContract.buildDocumentUriUsingTree(tree, cursor.getString(0))
            }
        }
        return null
    }
    private fun readDocument(file: Uri): ByteArray = requireNotNull(context.contentResolver.openInputStream(file)) { "Could not read data file." }.use { it.readBytes() }
    private fun writeDocument(file: Uri, bytes: ByteArray) {
        val descriptor = requireNotNull(context.contentResolver.openFileDescriptor(file, "wt")) { "Could not write data file." }
        ParcelFileDescriptor.AutoCloseOutputStream(descriptor).use { stream ->
            stream.write(bytes)
            stream.flush()
            // Cloud providers may return a pipe; only regular files support a disk flush.
            if (OsConstants.S_ISREG(Os.fstat(stream.fd).st_mode)) stream.fd.sync()
        }
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
        return Tracker(initial, reload = {
            val bytes = requireNotNull(read()) { "The data file was removed. Select its folder again." }
            val latest = PortableData.decode(bytes)
            snapshot = bytes
            latest
        }) { next ->
            check(read().contentEquals(snapshot)) { "The data file changed or was removed. Select its folder again before saving." }
            val bytes = PortableData.encode(next)
            write(bytes)
            snapshot = bytes
        }
    }
}
