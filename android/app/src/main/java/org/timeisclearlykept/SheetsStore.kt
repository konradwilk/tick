package org.timeisclearlykept

import kotlinx.serialization.json.*
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.UUID

internal data class GoogleSpreadsheet(val id: String, val name: String)
internal class GoogleSheetsAPI(private val token: () -> String,
    private val transport: ((String, String, JsonObject?) -> JsonObject)? = null) {
    fun request(method: String, url: String, body: JsonObject? = null): JsonObject {
        transport?.let { return it(method, url, body) }
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 15000; connection.readTimeout = 15000
            connection.requestMethod = method; connection.instanceFollowRedirects = false
            connection.setRequestProperty("Authorization", "Bearer " + token())
            connection.setRequestProperty("Content-Type", "application/json")
            if (body != null) { connection.doOutput = true; connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) } }
            check(connection.responseCode in 200..299) { "Google could not authorize or confirm the request. Reconnect and reload before retrying a save." }
            return connection.inputStream.use { Json.parseToJsonElement(it.readBytes().toString(Charsets.UTF_8)).jsonObject }
        } finally { connection.disconnect() }
    }
    fun spreadsheets(): List<GoogleSpreadsheet> {
        val files = mutableListOf<GoogleSpreadsheet>(); var page: String? = null
        do {
            var url = "https://www.googleapis.com/drive/v3/files?q=" + URLEncoder.encode("mimeType='application/vnd.google-apps.spreadsheet' and trashed=false", "UTF-8") + "&fields=nextPageToken,files(id,name)&pageSize=100"
            page?.let { url += "&pageToken=" + URLEncoder.encode(it, "UTF-8") }
            val response = request("GET", url)
            response["files"]?.jsonArray?.forEach { val f = it.jsonObject; files += GoogleSpreadsheet(f.getValue("id").jsonPrimitive.content, f.getValue("name").jsonPrimitive.content) }
            page = response["nextPageToken"]?.jsonPrimitive?.contentOrNull
        } while (page != null)
        return files.sortedBy { it.name.lowercase() }
    }
    fun create(name: String): SheetsStore {
        val title = name.trim(); require(title.isNotEmpty() && title.length <= 200) { "Enter a spreadsheet name (1–200 characters)." }
        val body = buildJsonObject {
            put("properties", buildJsonObject { put("title", title) })
            put("sheets", buildJsonArray { add(buildJsonObject { put("properties", buildJsonObject {
                put("title", "TickLog"); put("gridProperties", buildJsonObject { put("rowCount", 1000); put("columnCount", 6) })
            }) }) })
        }
        val result = request("POST", "https://sheets.googleapis.com/v4/spreadsheets", body)
        return SheetsStore(this, result.getValue("spreadsheetId").jsonPrimitive.content, title)
    }
}
internal class SheetsStore(private val api: GoogleSheetsAPI, val sheetId: String, val spreadsheetName: String = "Time is Clearly Kept") {
    private var revision: String? = null
    private var hasLog = false
    private var rowStore: SheetsRows? = null
    private var metadata = buildJsonObject {}
    init { require(Regex("[A-Za-z0-9_-]+").matches(sheetId)) { "Choose a spreadsheet used by Tick." } }
    private val base get() = "https://sheets.googleapis.com/v4/spreadsheets/$sheetId"
    private fun rows(range: String) = api.request("GET", "$base/values/$range")["values"]?.jsonArray ?: JsonArray(emptyList())
    private fun read(): Pair<TrackerState?, String?> {
        rowStore?.let { return it.read() }
        val meta = api.request("GET", "$base?fields=sheets.properties,properties.title")
        metadata = meta
        val tabs = meta["sheets"]?.jsonArray?.map { it.jsonObject.getValue("properties").jsonObject.getValue("title").jsonPrimitive.content }.orEmpty()
        if("TickMeta" in tabs) { val rows=SheetsRows(api,base,meta);rowStore=rows;return rows.read() }
        hasLog = "TickLog" in tabs
        if (hasLog) { val values = rows("TickLog!A:F"); if (values.isNotEmpty()) return decodeLog(values) }
        if ("TickData" in tabs) {
            val values = rows("TickData!A1:A1002")
            if (values.isNotEmpty()) {
                require(values.size > 2) { "Invalid previous Tick dataset." }
                val count = values[1].jsonArray[0].jsonPrimitive.int
                require(count in 1..1000 && values.size >= count+2) { "Invalid previous Tick dataset." }
                val raw = values.drop(2).take(count).joinToString("") { it.jsonArray[0].jsonPrimitive.content }
                return PortableData.decode(raw.toByteArray(Charsets.UTF_8)) to values[0].jsonArray[0].jsonPrimitive.content
            }
        }
        require(tabs.all { it in listOf("TickLog", "TickData") }) { "This spreadsheet has no Tick dataset. Create a new Tick spreadsheet instead." }
        return null to null
    }
    fun load(requireExisting: Boolean = true): TrackerState? {
        val (state, latest) = read()
        check(state != null || !requireExisting) { "The Tick dataset is missing. Reconnect in Settings." }
        revision = latest; return state
    }
    fun save(state: TrackerState) {
        rowStore?.let { revision=it.save(state,revision,false);return }
        check(read().second==revision) { "Data changed on another device. Reload before saving." }
        rowStore?.let { revision=it.save(state,revision,false);return }
        val rows=SheetsRows(api,base,metadata);rowStore=rows
        revision=rows.save(state,revision,true)
    }

    companion object {
        fun decodeLog(rows: JsonArray): Pair<TrackerState?, String?> {
            var position = 0; var latest: String? = null; var state: TrackerState? = null; val seen = mutableSetOf<String>()
            while (position < rows.size) {
                val row = rows[position].jsonArray
                require(row.size == 6 && row[0].jsonPrimitive.content == "tick-log-v1") { "Invalid Tick history." }
                val id = row[1].jsonPrimitive.content; val parent = row[2].jsonPrimitive.content; val count = row[4].jsonPrimitive.int
                require(id.isNotEmpty() && seen.add(id) && count in 1..1000 && position+count <= rows.size) { "Incomplete Tick history. Keep the spreadsheet for recovery." }
                check(latest == null || parent == latest) { "Concurrent Google Sheets changes detected. Both versions are preserved in TickLog; recover before continuing." }
                val raw = (0 until count).joinToString("") { index ->
                    val chunk = rows[position+index].jsonArray
                    require(chunk.size == 6 && chunk.take(3) == row.take(3) && chunk[3].jsonPrimitive.int == index && chunk[4].jsonPrimitive.int == count) { "Invalid Tick history chunks." }
                    chunk[5].jsonPrimitive.content
                }
                state = PortableData.decode(raw.toByteArray(Charsets.UTF_8)); latest = id; position += count
            }
            return state to latest
        }
    }
}
