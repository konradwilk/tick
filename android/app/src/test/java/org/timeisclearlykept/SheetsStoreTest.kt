package org.timeisclearlykept
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SheetsStoreTest {
    @Test fun roundTripStaleSaveAndConcurrentBranchesPreserveData() {
        val rows=mutableListOf<JsonElement>()
        val tables=mutableMapOf<Int,JsonArray>()
        val api=GoogleSheetsAPI({error("No network in test")}) { method,url,body ->
            when {
                "?fields=" in url -> Json.parseToJsonElement("""{"properties":{"title":"Time is Clearly Kept"},"sheets":[{"properties":{"title":"TickLog"}}]}""").jsonObject
                method=="GET" -> buildJsonObject { put("values",JsonArray(rows.toList())) }
                ":batchUpdate" in url -> {body!!.getValue("requests").jsonArray.forEach { req -> req.jsonObject["updateCells"]?.jsonObject?.let { update -> tables[update.getValue("range").jsonObject.getValue("sheetId").jsonPrimitive.int]=update.getValue("rows").jsonArray }; req.jsonObject["appendCells"]?.jsonObject?.getValue("rows")?.jsonArray?.forEach { row -> rows.add(JsonArray(row.jsonObject.getValue("values").jsonArray.map { it.jsonObject.getValue("userEnteredValue").jsonObject.values.first() })) } };buildJsonObject {} }
                ":append?" in url -> {rows.addAll(body!!.getValue("values").jsonArray);buildJsonObject {}}
                else -> error("Unexpected API request")
            }
        }
        val store=SheetsStore(api,"test");store.save(TrackerState())
        val tracker=Tracker(store.load()!!,reload={store.load()!!},save=store::save)
        val id=tracker.addNonprofit("Kitchen");tracker.start(id,"Meals")
        val other=SheetsStore(api,"test");val stale=Tracker(other.load()!!,save=other::save)
        tracker.stop()
        assertEquals(2,tables.getValue(174001).size)
        val session=tables.getValue(174001)[1].jsonObject.getValue("values").jsonArray
        assertEquals("Kitchen",session[0].jsonObject.getValue("userEnteredValue").jsonObject.getValue("stringValue").jsonPrimitive.content)
        assertEquals("Completed",session[6].jsonObject.getValue("userEnteredValue").jsonObject.getValue("stringValue").jsonPrimitive.content)
        assertEquals(1,tables.getValue(174002)[1].jsonObject.getValue("values").jsonArray[2].jsonObject.getValue("userEnteredValue").jsonObject.getValue("numberValue").jsonPrimitive.int)
        val before=stale.state
        assertThrows(IllegalStateException::class.java){stale.updateNotes(stale.state.active!!.sessionId,"Wrong")}
        assertEquals(before,stale.state)
        val count=rows.size;val sibling=rows.last().jsonArray.toMutableList();sibling[1]=JsonPrimitive("other-revision");rows.add(JsonArray(sibling))
        assertThrows(IllegalStateException::class.java){store.load()};assertEquals(count+1,rows.size)
    }
    @Test fun invalidIdIsRejected(){assertThrows(IllegalArgumentException::class.java){SheetsStore(GoogleSheetsAPI({"unused"}),"http://example.com")}}
}
