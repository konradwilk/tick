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
    private var metadata = buildJsonObject {}
    init { require(Regex("[A-Za-z0-9_-]+").matches(sheetId)) { "Choose a spreadsheet used by Tick." } }
    private val base get() = "https://sheets.googleapis.com/v4/spreadsheets/$sheetId"
    private fun rows(range: String) = api.request("GET", "$base/values/$range")["values"]?.jsonArray ?: JsonArray(emptyList())
    private fun read(): Pair<TrackerState?, String?> {
        val meta = api.request("GET", "$base?fields=sheets.properties,properties.title")
        metadata = meta
        val tabs = meta["sheets"]?.jsonArray?.map { it.jsonObject.getValue("properties").jsonObject.getValue("title").jsonPrimitive.content }.orEmpty()
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
        val raw = PortableData.encode(state).toString(Charsets.UTF_8)
        check(read().second == revision) { "Data changed on another device. Reload before saving." }
        if (!hasLog) {
            val request = Json.parseToJsonElement("""{"requests":[{"addSheet":{"properties":{"title":"TickLog","gridProperties":{"rowCount":1000,"columnCount":6}}}}]}""").jsonObject
            api.request("POST", "$base:batchUpdate", request); read()
        }
        val id = UUID.randomUUID().toString()
        val chunks = mutableListOf<String>(); var start = 0
        while (start < raw.length) { var end = minOf(start + 40000, raw.length)
            if (end < raw.length && raw[end-1].isHighSurrogate() && raw[end].isLowSurrogate()) end--
            chunks += raw.substring(start, end); start = end
        }
        require(chunks.size <= 1000) { "This dataset is too large for a Tick revision in Google Sheets. Use Local file storage." }
        val values = buildJsonArray { chunks.forEachIndexed { index, text -> add(buildJsonArray {
            add("tick-log-v1"); add(id); add(revision ?: ""); add(index); add(chunks.size); add(text)
        }) } }
        val requests = tableRequests(raw).toMutableList()
        val log = metadata.getValue("sheets").jsonArray.map { it.jsonObject.getValue("properties").jsonObject }.first { it.getValue("title").jsonPrimitive.content == "TickLog" }
        requests += buildJsonObject { put("appendCells", buildJsonObject { put("sheetId", log["sheetId"]?.jsonPrimitive?.int ?: 0); put("rows", cells(values)); put("fields", "userEnteredValue") }) }
        api.request("POST", "$base:batchUpdate", buildJsonObject { put("requests", JsonArray(requests)) })
        val (saved, confirmed) = read()
        check(confirmed == id && saved != null && PortableData.encode(saved).contentEquals(PortableData.encode(state))) { "Save could not be confirmed. Reload before retrying." }
        revision = id
    }

    private fun cells(rows: JsonArray) = buildJsonArray { rows.forEach { row -> add(buildJsonObject { put("values", buildJsonArray { row.jsonArray.forEach { value -> add(buildJsonObject { put("userEnteredValue", buildJsonObject { put(if (value.jsonPrimitive.isString) "stringValue" else "numberValue", value) }) }) } }) }) } }
    private fun tableRequests(raw: String): JsonArray {
        val data = Json.parseToJsonElement(raw).jsonObject
        val projects = data.getValue("nonprofits").jsonArray.map { it.jsonObject }
        val names = projects.associate { it.getValue("id").jsonPrimitive.content to it.getValue("name").jsonPrimitive.content }
        val totals = names.keys.associateWith { 0.0 to 0 }.toMutableMap()
        val rows = mutableListOf<JsonElement>(buildJsonArray { listOf("Project", "Started (UTC)", "Ended (UTC)", "Duration", "Hours", "Notes", "Status", "Platform").forEach { add(it) } })
        for (s in data.getValue("sessions").jsonArray.map { it.jsonObject }.sortedBy { it.getValue("startTimeUtc").jsonPrimitive.content }) {
            val key = s.getValue("projectId").jsonPrimitive.content
            val seconds = s["durationSeconds"]?.jsonPrimitive?.doubleOrNull
            val n = (seconds ?: 0.0).toLong(); val ended = s["endTimeUtc"]?.jsonPrimitive?.contentOrNull
            rows.add(buildJsonArray { add(names[key] ?: s.getValue("project").jsonPrimitive.content); add(java.time.Instant.parse(s.getValue("startTimeUtc").jsonPrimitive.content).atOffset(java.time.ZoneOffset.UTC).format(java.time.format.DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss",java.util.Locale.ROOT))); add(ended?.let { java.time.Instant.parse(it).atOffset(java.time.ZoneOffset.UTC).format(java.time.format.DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss",java.util.Locale.ROOT)) } ?: ""); add(if (seconds == null) "" else "%d:%02d:%02d".format(java.util.Locale.ROOT,n/3600,n/60%60,n%60)); if(seconds == null) add("") else add(seconds/3600); add(s.getValue("notes")); add(if(ended == null) "Running" else "Completed"); add(s.getValue("platform")) })
            totals[key]?.let { totals[key] = (it.first+(seconds ?: 0.0)/3600) to (it.second+1) }
        }
        val summary = buildJsonArray { add(buildJsonArray { add("Project"); add("Total hours"); add("Sessions") }); projects.forEach { p -> val t=totals.getValue(p.getValue("id").jsonPrimitive.content); add(buildJsonArray { add(p.getValue("name")); add(t.first); add(t.second) }) } }
        val tabs = metadata.getValue("sheets").jsonArray.map { it.jsonObject.getValue("properties").jsonObject }
        val used = tabs.map { it["sheetId"]?.jsonPrimitive?.int ?: 0 }.toMutableSet()
        val requests = mutableListOf<JsonElement>()
        val styles = Json.parseToJsonElement("""[[{"updateSheetProperties":{"properties":{"sheetId":0,"index":0,"hidden":false,"gridProperties":{"frozenRowCount":1}},"fields":"index,hidden,gridProperties.frozenRowCount"}},{"updateCells":{"range":{"sheetId":0},"rows":[],"fields":"userEnteredValue,note"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.92,"green":0.93,"blue":0.94},"textFormat":{"bold":true,"foregroundColor":{"red":0,"green":0,"blue":0}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":1},"cell":{"userEnteredFormat":{"verticalAlignment":"TOP","wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"updateDimensionProperties":{"range":{"sheetId":0,"dimension":"COLUMNS","startIndex":0,"endIndex":8},"properties":{"pixelSize":160},"fields":"pixelSize"}},{"setBasicFilter":{"filter":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1,"startColumnIndex":0,"endColumnIndex":8}}}}],[{"updateSheetProperties":{"properties":{"sheetId":0,"index":1,"hidden":false,"gridProperties":{"frozenRowCount":1}},"fields":"index,hidden,gridProperties.frozenRowCount"}},{"updateCells":{"range":{"sheetId":0},"rows":[],"fields":"userEnteredValue,note"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.92,"green":0.93,"blue":0.94},"textFormat":{"bold":true,"foregroundColor":{"red":0,"green":0,"blue":0}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":1},"cell":{"userEnteredFormat":{"verticalAlignment":"TOP","wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"updateDimensionProperties":{"range":{"sheetId":0,"dimension":"COLUMNS","startIndex":0,"endIndex":3},"properties":{"pixelSize":160},"fields":"pixelSize"}},{"setBasicFilter":{"filter":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1,"startColumnIndex":0,"endColumnIndex":3}}}}]]""").jsonArray
        listOf(JsonArray(rows), summary).forEachIndexed { index, values ->
            val title = if(index == 0) "Sessions" else "Projects"
            val tab = tabs.firstOrNull { it.getValue("title").jsonPrimitive.content == title }
            var id = tab?.get("sheetId")?.jsonPrimitive?.int ?: (174001+index)
            if(tab == null) { while(id in used) id++; used += id; requests += Json.parseToJsonElement("""{"addSheet":{"properties":{"sheetId":$id,"title":"$title","gridProperties":{"rowCount":${maxOf(1000,values.size)},"columnCount":${values[0].jsonArray.size}}}}}""") }
            val size = maxOf(tab?.get("gridProperties")?.jsonObject?.get("rowCount")?.jsonPrimitive?.int ?: 1000, values.size, 2)
            requests += Json.parseToJsonElement("""{"updateSheetProperties":{"properties":{"sheetId":$id,"gridProperties":{"rowCount":$size}},"fields":"gridProperties.rowCount"}}""")
            val safe = JsonArray(values.map { row -> JsonArray(row.jsonArray.map { v -> if(v.jsonPrimitive.isString) { val text=v.jsonPrimitive.content; var end=minOf(20000,text.length); if(end<text.length && end>0 && text[end-1].isHighSurrogate())end--; JsonPrimitive(text.substring(0,end)) } else v }) })
            fun replace(element: JsonElement): JsonElement = when(element) {
                is JsonObject -> JsonObject(element.mapValues { (key,value) -> if(key == "sheetId") JsonPrimitive(id) else if(key == "endRowIndex" && value.jsonPrimitive.int == 1) JsonPrimitive(maxOf(2,values.size)) else replace(value) })
                is JsonArray -> JsonArray(element.map { replace(it) })
                else -> element
            }
            styles[index].jsonArray.forEach { part ->
                // Header formatting ends at row 1; only the filter should extend through the data.
                val name=part.jsonObject.keys.first()
                var payload=replace(part.jsonObject.getValue(name)).jsonObject
                if(name == "repeatCell") { val original=part.jsonObject.getValue(name).jsonObject.getValue("range").jsonObject; if(original["endRowIndex"]!=null) payload=JsonObject(payload + ("range" to JsonObject(payload.getValue("range").jsonObject + ("endRowIndex" to JsonPrimitive(1))))) }
                if(name == "updateCells") { val cellRows=cells(safe).toMutableList(); val header=cellRows[0].jsonObject.getValue("values").jsonArray.toMutableList(); header[0]=JsonObject(header[0].jsonObject + ("note" to JsonPrimitive("Generated by Tick. Edit projects and sessions in Tick; these tables refresh on every save."))); cellRows[0]=buildJsonObject { put("values",JsonArray(header)) }; payload=JsonObject(payload + ("rows" to JsonArray(cellRows))) }
                requests += buildJsonObject { put(name,payload) }
            }
            val column=if(index == 0) 4 else 1
            requests += Json.parseToJsonElement("""{"repeatCell":{"range":{"sheetId":$id,"startRowIndex":1,"startColumnIndex":$column,"endColumnIndex":${column+1}},"cell":{"userEnteredFormat":{"numberFormat":{"type":"NUMBER","pattern":"0.00"}}},"fields":"userEnteredFormat.numberFormat"}}""")
            if(index == 0) requests += Json.parseToJsonElement("""{"updateDimensionProperties":{"range":{"sheetId":$id,"dimension":"COLUMNS","startIndex":5,"endIndex":6},"properties":{"pixelSize":420},"fields":"pixelSize"}}""")
        }
        tabs.filter { it.getValue("title").jsonPrimitive.content in listOf("TickLog","TickData") }.forEach { tab -> val id=tab["sheetId"]?.jsonPrimitive?.int ?: 0; requests += Json.parseToJsonElement("""{"updateSheetProperties":{"properties":{"sheetId":$id,"hidden":true},"fields":"hidden"}}""") }
        return JsonArray(requests)
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
