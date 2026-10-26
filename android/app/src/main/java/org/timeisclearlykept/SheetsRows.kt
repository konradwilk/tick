package org.timeisclearlykept

import kotlinx.serialization.json.*
import java.net.URLEncoder
import java.util.UUID

/** Shared row protocol; full text is chunked across hidden cells in the same entity row. */
internal class SheetsRows(private val api: GoogleSheetsAPI, private val base: String, private var metadata: JsonObject) {
    private data class Row(val index: Int, val cells: JsonArray, val payload: JsonObject, val deleted: String)
    private var records = mapOf<String, Map<String, Row>>()
    private var logCount = 0
    private fun invalid(message: String = "Invalid Tick row storage. Reload before saving."): Nothing = error(message)
    private val tabs get() = metadata.getValue("sheets").jsonArray.map { it.jsonObject.getValue("properties").jsonObject }
    private fun tab(title: String) = tabs.firstOrNull { it.getValue("title").jsonPrimitive.content == title } ?: invalid()
    private fun id(title: String) = tab(title)["sheetId"]?.jsonPrimitive?.int ?: 0
    private fun array(vararg values: Any): JsonArray = JsonArray(values.map { when(it) { is JsonElement -> it; is Int -> JsonPrimitive(it); is Double -> JsonPrimitive(it); else -> JsonPrimitive(it.toString()) } })
    private fun chunks(text: String): List<String> {
        val result = mutableListOf<String>(); var start = 0
        while(start < text.length) { var end = minOf(start+20000,text.length); if(end<text.length && text[end-1].isHighSurrogate())end--; result += text.substring(start,end);start=end }
        require(result.size in 1..1000) { "This Tick row is too large. Use Local file storage." };return result
    }
    private fun cells(rows: List<JsonArray>) = buildJsonArray { rows.forEach { row -> add(buildJsonObject { put("values",buildJsonArray { row.forEach { value -> add(buildJsonObject { put("userEnteredValue",buildJsonObject { put(if(value.jsonPrimitive.isString) "stringValue" else "numberValue",value) }) }) } }) }) } }
    private fun update(title: String,index: Int,rows: List<JsonArray>,width: Int = rows.maxOf { it.size }) = buildJsonObject { put("updateCells",buildJsonObject {
        put("range",buildJsonObject { put("sheetId",id(title));put("startRowIndex",index);put("endRowIndex",index+rows.size);put("startColumnIndex",0);put("endColumnIndex",width) });put("rows",cells(rows));put("fields","userEnteredValue")
    }) }
    fun read(): Pair<TrackerState, String?> {
        val ranges=listOf("TickMeta!A1:B1","Sessions","Projects","TickChanges!A:D")
        val response=api.request("GET",base+"/values:batchGet?"+ranges.joinToString("&") { "ranges="+URLEncoder.encode(it,"UTF-8") }+"&valueRenderOption=UNFORMATTED_VALUE")["valueRanges"]?.jsonArray ?: invalid()
        if(response.size!=4)invalid()
        val values=response.map { it.jsonObject["values"]?.jsonArray ?: JsonArray(emptyList()) }
        if(values[0].size!=1 || values[0][0].jsonArray.size!=2 || values[0][0].jsonArray[0].jsonPrimitive.content!="tick-rows-v1")invalid()
        val root=Json.parseToJsonElement(values[0][0].jsonArray[1].jsonPrimitive.content).jsonObject.toMutableMap()
        val next=mutableMapOf<String,Map<String,Row>>()
        listOf(Triple("Sessions",8,"sessionId"),Triple("Projects",3,"id")).forEachIndexed { table,(title,offset,key) ->
            val rows=values[table+1]
            if(rows.isEmpty() || JsonArray(rows[0].jsonArray.drop(offset).take(4))!=array("Tick ID","Version","Deleted","Chunks"))invalid()
            val entities=mutableMapOf<String,Row>()
            rows.drop(1).forEachIndexed { index,element ->
                val row=element.jsonArray
                if(row.isNotEmpty()) {
                    if(row.size<offset+5)invalid()
                    val identity=row[offset].jsonPrimitive.content.lowercase();val version=row[offset+1].jsonPrimitive.content;val deleted=row[offset+2].jsonPrimitive.content;val count=row[offset+3].jsonPrimitive.int
                    if(identity.isEmpty() || version.isEmpty() || identity in entities || deleted !in listOf("0","1") || count !in 1..1000 || row.size!=offset+4+count)invalid()
                    val payload=Json.parseToJsonElement(row.drop(offset+4).joinToString("") { it.jsonPrimitive.content }).jsonObject
                    if(payload.getValue(key).jsonPrimitive.content.lowercase()!=identity)invalid()
                    entities[identity]=Row(index+1,row,payload,deleted)
                }
            }
            next[title]=entities
        }
        var latest: String?=null;var position=0;val changes=values[3];val seen=mutableSetOf<String>()
        if(changes.isEmpty())invalid("The Tick change journal is missing. Keep this spreadsheet for recovery.")
        while(position<changes.size) {
            val row=changes[position].jsonArray;if(row.size!=4)invalid()
            val identity=row[0].jsonPrimitive.content;val parent=row[1].jsonPrimitive.content;val count=row[3].jsonPrimitive.int
            if(identity.isEmpty() || !seen.add(identity) || parent!=(latest ?: "") || count !in 1..1000 || position+count>changes.size)invalid("Concurrent Google Sheets changes detected. Both changes remain in TickChanges; recover before continuing.")
            for(n in 0 until count)if(changes[position+n]!=array(identity,parent,n,count))invalid()
            latest=identity;position+=count
        }
        root["sessions"]=JsonArray(next.getValue("Sessions").values.sortedBy { it.index }.filter { it.deleted=="0" }.map { it.payload })
        root["nonprofits"]=JsonArray(next.getValue("Projects").values.sortedBy { it.index }.filter { it.deleted=="0" }.map { it.payload })
        val state=PortableData.decode(JsonObject(root).toString().toByteArray(Charsets.UTF_8))
        val canonical=Json.parseToJsonElement(PortableData.encode(state).toString(Charsets.UTF_8)).jsonObject
        listOf(Triple("Sessions","sessions","sessionId"),Triple("Projects","nonprofits","id")).forEach { (title,field,key) ->
            val entities=next.getValue(title).toMutableMap()
            canonical.getValue(field).jsonArray.forEach { payload -> val identity=payload.jsonObject.getValue(key).jsonPrimitive.content.lowercase();entities[identity]=entities.getValue(identity).copy(payload=payload.jsonObject) }
            next[title]=entities
        }
        records=next;logCount=changes.size;return state to latest
    }
    private fun initialize(state: TrackerState): MutableList<JsonElement> {
        val properties=tabs.toMutableList();val used=tabs.map { it["sheetId"]?.jsonPrimitive?.int ?: 0 }.toMutableSet();val requests=mutableListOf<JsonElement>()
        listOf("TickLog","TickData").forEach { title -> properties.firstOrNull { it.getValue("title").jsonPrimitive.content==title }?.let { old ->
            check(properties.none { it.getValue("title").jsonPrimitive.content==title+"Backup" }) { "A Tick migration backup already exists. Keep this spreadsheet for recovery." }
            requests += buildJsonObject { put("updateSheetProperties",buildJsonObject { put("properties",buildJsonObject { put("sheetId",old["sheetId"]?.jsonPrimitive?.int ?: 0);put("title",title+"Backup");put("hidden",true) });put("fields","title,hidden") }) }
        } }
        listOf("Sessions","Projects","TickMeta","TickChanges").forEachIndexed { index,title -> if(properties.none { it.getValue("title").jsonPrimitive.content==title }) {
            var identity=174001+index;while(identity in used)identity++;used+=identity
            val props=buildJsonObject { put("sheetId",identity);put("title",title);put("gridProperties",buildJsonObject { put("rowCount",maxOf(1000,state.sessions.size+1,state.nonprofits.size+1));put("columnCount",26) }) }
            properties+=props;requests+=buildJsonObject { put("addSheet",buildJsonObject { put("properties",props) }) }
        } }
        requests.sortBy { if("addSheet" in it.jsonObject)0 else 1 }
        metadata=buildJsonObject { put("sheets",JsonArray(properties.map { buildJsonObject { put("properties",it) } })) };records=mapOf("Sessions" to emptyMap(),"Projects" to emptyMap());logCount=0
        val root=Json.parseToJsonElement(PortableData.encode(state).toString(Charsets.UTF_8)).jsonObject.filterKeys { it !in listOf("sessions","nonprofits") }
        requests+=update("TickMeta",0,listOf(array("tick-rows-v1",JsonObject(root).toString())))
        listOf("Sessions" to listOf("Project","Started (UTC)","Ended (UTC)","Duration","Hours","Notes","Status","Platform"),"Projects" to listOf("Project","Total hours","Sessions")).forEach { (title,header) ->
            requests+=update(title,0,listOf(JsonArray((header+listOf("Tick ID","Version","Deleted","Chunks","Tick data")).map { JsonPrimitive(it) })))
            val identity=id(title);val columns=maxOf(header.size+5,tab(title)["gridProperties"]?.jsonObject?.get("columnCount")?.jsonPrimitive?.int ?: 26)
            requests+=Json.parseToJsonElement("""{"updateSheetProperties":{"properties":{"sheetId":$identity,"gridProperties":{"frozenRowCount":1}},"fields":"gridProperties.frozenRowCount"}}""")
            requests+=Json.parseToJsonElement("""{"repeatCell":{"range":{"sheetId":$identity,"startRowIndex":0,"endRowIndex":1},"cell":{"userEnteredFormat":{"textFormat":{"bold":true}}},"fields":"userEnteredFormat.textFormat"}}""")
            requests+=Json.parseToJsonElement("""{"updateDimensionProperties":{"range":{"sheetId":$identity,"dimension":"COLUMNS","startIndex":${header.size},"endIndex":$columns},"properties":{"hiddenByUser":true},"fields":"hiddenByUser"}}""")
        }
        listOf("TickMeta","TickChanges").forEach { title -> requests+=Json.parseToJsonElement("""{"updateSheetProperties":{"properties":{"sheetId":${id(title)},"hidden":true},"fields":"hidden"}}""") }
        return requests
    }
    fun save(state: TrackerState,expected: String?,initializing: Boolean): String {
        check(initializing || read().second==expected) { "Data changed on another device. Reload before saving." }
        val requests=if(initializing)initialize(state) else mutableListOf();val revision=UUID.randomUUID().toString();val root=Json.parseToJsonElement(PortableData.encode(state).toString(Charsets.UTF_8)).jsonObject
        val projects=root.getValue("nonprofits").jsonArray.map { it.jsonObject };val sessions=root.getValue("sessions").jsonArray.map { it.jsonObject };val names=projects.associate { it.getValue("id").jsonPrimitive.content to it.getValue("name").jsonPrimitive.content };val totals=names.keys.associateWith { 0.0 to 0 }.toMutableMap()
        val sessionViews=sessions.map { s ->
            val key=s.getValue("projectId").jsonPrimitive.content;val seconds=s["durationSeconds"]?.jsonPrimitive?.doubleOrNull;val ended=s["endTimeUtc"]?.jsonPrimitive?.contentOrNull;val n=(seconds ?: 0.0).toLong();val t=totals.getValue(key);totals[key]=t.first+(seconds ?: 0.0)/3600 to t.second+1
            array(names[key] ?: s.getValue("project").jsonPrimitive.content,s.getValue("startTimeUtc").jsonPrimitive.content.take(19).replace('T',' '),ended?.take(19)?.replace('T',' ') ?: "",if(seconds==null) "" else "%d:%02d:%02d".format(java.util.Locale.ROOT,n/3600,n/60%60,n%60),if(seconds==null)JsonPrimitive("") else JsonPrimitive(seconds/3600),s.getValue("notes"),if(ended==null)"Running" else "Completed",s.getValue("platform"))
        }
        val projectViews=projects.map { p -> val t=totals.getValue(p.getValue("id").jsonPrimitive.content);array(p.getValue("name"),t.first,t.second) };val changed=mutableListOf<JsonElement>()
        listOf(Triple("Sessions","sessionId",sessions.zip(sessionViews)),Triple("Projects","id",projects.zip(projectViews))).forEach { (title,key,items) ->
            val old=records.getValue(title);val incoming=items.associateBy { it.first.getValue(key).jsonPrimitive.content.lowercase() };var nextIndex=(old.values.maxOfOrNull { it.index } ?: 0)+1
            (old.keys+incoming.keys).sorted().forEach entity@ { identity ->
                val before=old[identity];val payload=incoming[identity]?.first ?: before!!.payload;val view=incoming[identity]?.second ?: JsonArray(List(if(title=="Sessions")8 else 3) { JsonPrimitive("") });val deleted=if(identity in incoming)"0" else "1"
                val safe=view.map { v -> if(v.jsonPrimitive.isString) { val text=v.jsonPrimitive.content;var end=minOf(20000,text.length);if(end<text.length && end>0 && text[end-1].isHighSurrogate())end--;JsonPrimitive(text.substring(0,end)) } else v }
                if(before!=null && before.deleted==deleted && before.payload==payload && JsonArray(before.cells.take(safe.size))==JsonArray(safe))return@entity
                val parts=chunks(payload.toString())
                val row=JsonArray(safe+array(identity,revision,deleted,parts.size)+parts.map { JsonPrimitive(it) });val index=before?.index ?: nextIndex++
                requests+=update(title,index,listOf(row),maxOf(row.size,before?.cells?.size ?: 0));changed+=buildJsonObject { put("table",title);put("id",identity);put("row",row) }
            }
        }
        if(changed.isEmpty() && !initializing)return expected!!
        val audit=chunks(buildJsonObject { put("changes",JsonArray(changed)) }.toString())
        tabs.filter { it.getValue("title").jsonPrimitive.content in listOf("Sessions","Projects","TickChanges") }.forEach { tab ->
            val identity=tab.getValue("sheetId").jsonPrimitive.int;val grid=tab["gridProperties"]?.jsonObject;val updates=requests.mapNotNull { it.jsonObject["updateCells"]?.jsonObject?.get("range")?.jsonObject }.filter { it.getValue("sheetId").jsonPrimitive.int==identity }
            val rows=maxOf(updates.maxOfOrNull { it.getValue("endRowIndex").jsonPrimitive.int } ?: 1,if(tab.getValue("title").jsonPrimitive.content=="TickChanges")logCount+audit.size else 1);val columns=updates.maxOfOrNull { it.getValue("endColumnIndex").jsonPrimitive.int } ?: 5;val oldRows=grid?.get("rowCount")?.jsonPrimitive?.int ?: 1000;val oldColumns=grid?.get("columnCount")?.jsonPrimitive?.int ?: 26
            if(rows>oldRows || columns>oldColumns) { val grow=Json.parseToJsonElement("""{"updateSheetProperties":{"properties":{"sheetId":$identity,"gridProperties":{"rowCount":${maxOf(rows,oldRows)},"columnCount":${maxOf(columns,oldColumns)}}},"fields":"gridProperties.rowCount,gridProperties.columnCount"}}""");val at=requests.indexOfFirst { "updateCells" in it.jsonObject }.let { if(it<0)requests.size else it };requests.add(at,grow) }
        }
        requests.toList().forEach { request ->
            val props=request.jsonObject["updateSheetProperties"]?.jsonObject?.get("properties")?.jsonObject
            val columns=props?.get("gridProperties")?.jsonObject?.get("columnCount")?.jsonPrimitive?.int
            if(columns!=null) { val identity=props.getValue("sheetId").jsonPrimitive.int;val title=tabs.first { it["sheetId"]==props["sheetId"] }.getValue("title").jsonPrimitive.content
                if(title in listOf("Sessions","Projects"))requests+=Json.parseToJsonElement("""{"updateDimensionProperties":{"range":{"sheetId":$identity,"dimension":"COLUMNS","startIndex":${if(title=="Sessions")8 else 3},"endIndex":$columns},"properties":{"hiddenByUser":true},"fields":"hiddenByUser"}}""")
            }
        }
        requests+=buildJsonObject { put("appendCells",buildJsonObject { put("sheetId",id("TickChanges"));put("rows",cells(audit.mapIndexed { index,c -> array(revision,if(initializing)"" else expected ?: "",index,audit.size,c) }));put("fields","userEnteredValue") }) }
        api.request("POST",base+":batchUpdate",buildJsonObject { put("requests",JsonArray(requests)) });val (saved,confirmed)=read()
        fun normalize(value: TrackerState): JsonObject { val v=Json.parseToJsonElement(PortableData.encode(value).toString(Charsets.UTF_8)).jsonObject;return JsonObject(v+("nonprofits" to JsonArray(v.getValue("nonprofits").jsonArray.sortedBy { it.jsonObject.getValue("id").jsonPrimitive.content }))) }
        val rowsConfirmed=changed.all { change -> val c=change.jsonObject;records[c.getValue("table").jsonPrimitive.content]?.get(c.getValue("id").jsonPrimitive.content)?.cells==c["row"] }
        check(confirmed==revision && normalize(saved)==normalize(state) && rowsConfirmed) { "Save could not be confirmed. Reload before retrying." }
        val properties=tabs.map { tab -> var current=tab;requests.forEach { request -> val props=request.jsonObject["updateSheetProperties"]?.jsonObject?.get("properties")?.jsonObject;if(props?.get("sheetId")==tab["sheetId"])props?.get("gridProperties")?.jsonObject?.let { grid -> current=JsonObject(current+("gridProperties" to JsonObject(current["gridProperties"]?.jsonObject.orEmpty()+grid))) } };current }
        metadata=buildJsonObject { put("sheets",JsonArray(properties.map { buildJsonObject { put("properties",it) } })) }
        return revision
    }
}
