package org.timeisclearlykept
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.net.URLDecoder

class SheetsStoreTest {
    private class Server(legacy: Boolean=false) {
        private val fixture=Json.parseToJsonElement(javaClass.getResource("/storage/sheets-rows-v1.json")!!.readText()).jsonObject
        private val properties=fixture.getValue("metadata").jsonObject.getValue("sheets").jsonArray.map { it.jsonObject.getValue("properties").jsonObject }.toMutableList()
        val tables=fixture.getValue("tables").jsonObject.mapValues { it.value.jsonArray.toMutableList() }.toMutableMap()
        var requests=listOf<JsonElement>();var calls=0;var failWrite=false;var afterAppend: ((MutableList<JsonElement>)->Unit)?=null
        init { if(legacy) { properties.clear();properties+=buildJsonObject { put("sheetId",0);put("title","TickLog");put("gridProperties",buildJsonObject { put("rowCount",1000);put("columnCount",6) }) };tables.clear();tables["TickLog"]=mutableListOf(buildJsonArray { add("tick-log-v1");add("legacy");add("");add(0);add(1);add(fixture.getValue("state").toString()) }) } }
        fun store()=SheetsStore(GoogleSheetsAPI({error("No network in test")},::request),"test")
        private fun request(method: String,url: String,body: JsonObject?): JsonObject {
            calls++
            if("?fields=" in url)return buildJsonObject { put("sheets",JsonArray(properties.map { buildJsonObject { put("properties",it) } })) }
            if("/values:batchGet?" in url) { val ranges=url.substringAfter('?').split('&').filter { it.startsWith("ranges=") }.map { URLDecoder.decode(it.substringAfter('='),"UTF-8") };return buildJsonObject { put("valueRanges",JsonArray(ranges.map { range -> val title=range.substringBefore('!');val rows=tables[title].orEmpty().map { if(title=="TickChanges")JsonArray(it.jsonArray.take(4)) else it };buildJsonObject { put("values",JsonArray(rows)) } })) } }
            if(method=="GET")return buildJsonObject { put("values",JsonArray(tables[if("TickLog" in url)"TickLog" else "TickData"].orEmpty())) }
            check(!failWrite) { "offline" };requests=body!!.getValue("requests").jsonArray
            requests.forEach { req ->
                req.jsonObject["addSheet"]?.jsonObject?.get("properties")?.jsonObject?.let { properties+=it }
                req.jsonObject["updateSheetProperties"]?.jsonObject?.get("properties")?.jsonObject?.let { props ->
                    val index=properties.indexOfFirst { it["sheetId"]==props["sheetId"] };val old=properties[index]
                    props["title"]?.let { title -> tables[title.jsonPrimitive.content]=tables.remove(old.getValue("title").jsonPrimitive.content) ?: mutableListOf();properties[index]=JsonObject(old+("title" to title)) }
                }
                listOf("updateCells","appendCells").forEach { kind -> req.jsonObject[kind]?.jsonObject?.let { update ->
                    val range=update["range"]?.jsonObject ?: update;val title=properties.first { it["sheetId"]==range["sheetId"] }.getValue("title").jsonPrimitive.content;val table=tables.getOrPut(title){mutableListOf()};val rows=update.getValue("rows").jsonArray.map { row -> JsonArray(row.jsonObject.getValue("values").jsonArray.map { it.jsonObject.getValue("userEnteredValue").jsonObject.values.first() }) }
                    if(kind=="appendCells") { table.addAll(rows);afterAppend?.invoke(table) } else { val start=range["startRowIndex"]?.jsonPrimitive?.int ?: 0;while(table.size<start+rows.size)table.add(JsonArray(emptyList()));rows.forEachIndexed { i,row -> table[start+i]=row } }
                } }
            };return buildJsonObject {}
        }
    }
    @Test fun pythonRowsUpdateOneRowAfterSorting() {
        val server=Server();val store=server.store();var state=store.load()!!;val rows=server.tables.getValue("Sessions");java.util.Collections.swap(rows,1,2)
        state=state.copy(sessions=state.sessions.mapIndexed { i,s -> if(i==0)s.copy(notes="Changed") else s });server.calls=0;store.save(state);assertEquals(3,server.calls)
        val updates=server.requests.mapNotNull { it.jsonObject["updateCells"]?.jsonObject };assertEquals(1,updates.size);assertEquals(2,updates[0].getValue("range").jsonObject.getValue("startRowIndex").jsonPrimitive.int);assertEquals("Changed",rows[2].jsonArray[5].jsonPrimitive.content);assertFalse(server.requests.any { "repeatCell" in it.jsonObject })
        val count=server.tables.getValue("TickChanges").size;store.save(state);assertEquals(count,server.tables.getValue("TickChanges").size)
    }
    @Test fun migrationStaleSaveAndConcurrentRecovery() {
        val server=Server(true);val store=server.store();var state=store.load()!!;val old=server.tables.getValue("TickLog").toList();store.save(state);assertEquals(old,server.tables["TickLogBackup"]);assertNull(server.tables["TickLog"])
        val other=server.store();val stale=other.load()!!;state=state.copy(sessions=state.sessions.mapIndexed { i,s -> if(i==0)s.copy(notes="New") else s });store.save(state);assertThrows(IllegalStateException::class.java){other.save(stale)}
        state=state.copy(sessions=state.sessions.mapIndexed { i,s -> if(i==0)s.copy(notes="Concurrent") else s });server.afterAppend={ rows -> val sibling=rows.last().jsonArray.toMutableList();sibling[0]=JsonPrimitive("sibling");rows.add(JsonArray(sibling)) };assertThrows(IllegalStateException::class.java){store.save(state)};assertThrows(IllegalStateException::class.java){server.store().load()};assertTrue(server.tables.getValue("TickChanges").size>3)
    }
    @Test fun longUnicodeNotesDeletionAndFailure() {
        val server=Server();val store=server.store();var state=store.load()!!;val longText="🍲".repeat(45000);state=state.copy(sessions=state.sessions.mapIndexed { i,s -> if(i==0)s.copy(notes=longText) else s });store.save(state);assertEquals(longText,store.load()!!.sessions[0].notes)
        val width=server.tables.getValue("Sessions")[1].jsonArray.size;state=state.copy(sessions=state.sessions.mapIndexed { i,s -> if(i==0)s.copy(notes="Short") else s });store.save(state);val update=server.requests.first { "updateCells" in it.jsonObject }.jsonObject.getValue("updateCells").jsonObject;assertEquals(width,update.getValue("range").jsonObject.getValue("endColumnIndex").jsonPrimitive.int)
        state=state.copy(sessions=state.sessions.take(1));store.save(state);assertEquals(1,store.load()!!.sessions.size);state=state.copy(sessions=state.sessions.map { it.copy(notes="Offline") });server.failWrite=true;assertThrows(IllegalStateException::class.java){store.save(state)};server.failWrite=false;assertEquals("Short",store.load()!!.sessions[0].notes)
    }
    @Test fun invalidIdIsRejected(){assertThrows(IllegalArgumentException::class.java){SheetsStore(GoogleSheetsAPI({"unused"}),"http://example.com")}}
}
