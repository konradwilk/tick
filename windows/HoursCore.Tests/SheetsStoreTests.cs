using System.Text.Json.Nodes;
using HoursCore;
using Xunit;
namespace HoursCore.Tests;
public class SheetsStoreTests
{
    private sealed class Server
    {
        public JsonObject Metadata;
        public JsonObject Tables;
        public JsonArray Requests = new();
        public int Calls;
        public bool FailWrite;
        public Action<JsonArray>? AfterAppend;
        public Server(bool legacy=false) {
            var fixture=JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"storage","sheets-rows-v1.json")))!.AsObject();
            Metadata=fixture["metadata"]!.DeepClone().AsObject();Tables=fixture["tables"]!.DeepClone().AsObject();
            if(legacy) { Metadata=JsonNode.Parse("""{"sheets":[{"properties":{"sheetId":0,"title":"TickLog","gridProperties":{"rowCount":1000,"columnCount":6}}}]}""")!.AsObject();Tables=new JsonObject { ["TickLog"]=new JsonArray(new JsonArray("tick-log-v1","legacy","",0,1,fixture["state"]!.ToJsonString())) }; }
        }
        public SheetsStore Store() => new(new("test"),new GoogleSheetsAPI(new GoogleAccount(),Request));
        private JsonObject Request(string method,string url,JsonObject? body) {
            Calls++;
            if(url.Contains("?fields="))return Metadata.DeepClone().AsObject();
            if(url.Contains("/values:batchGet?")) {
                var ranges=new Uri(url).Query.TrimStart('?').Split('&').Where(x=>x.StartsWith("ranges=")).Select(x=>Uri.UnescapeDataString(x[7..].Replace('+',' ')));
                return new JsonObject { ["valueRanges"]=new JsonArray(ranges.Select(range=> { var title=range.Split('!')[0];var rows=Tables[title]?.DeepClone().AsArray()??new JsonArray();if(title=="TickChanges")rows=new JsonArray(rows.Select(r=>(JsonNode)new JsonArray(r!.AsArray().Take(4).Select(x=>x!.DeepClone()).ToArray())).ToArray());return (JsonNode)new JsonObject { ["values"]=rows }; }).ToArray()) };
            }
            if(method=="GET")return new JsonObject { ["values"]=Tables[url.Contains("TickLog")?"TickLog":"TickData"]?.DeepClone()??new JsonArray() };
            if(FailWrite)throw new IOException("offline");
            Requests=body!["requests"]!.DeepClone().AsArray();
            foreach(var req in Requests) {
                if(req!["addSheet"] is JsonObject add)Metadata["sheets"]!.AsArray().Add(new JsonObject { ["properties"]=add["properties"]!.DeepClone() });
                if(req["updateSheetProperties"] is JsonObject update && update["properties"] is JsonObject props) {
                    var old=Metadata["sheets"]!.AsArray().Select(x=>x!["properties"]!.AsObject()).First(x=>x["sheetId"]!.ToString()==props["sheetId"]!.ToString());
                    if(props["title"] is {} title){var previous=old["title"]!.ToString();Tables[title.ToString()]=Tables[previous]?.DeepClone();Tables.Remove(previous);old["title"]=title.DeepClone();}
                }
                foreach(var kind in new[]{"updateCells","appendCells"})if(req[kind] is JsonObject cells) {
                    var range=cells["range"]?.AsObject()??cells;var id=range["sheetId"]!.ToString();var title=Metadata["sheets"]!.AsArray().Select(x=>x!["properties"]!).First(x=>x["sheetId"]!.ToString()==id)["title"]!.ToString();
                    if(Tables[title]==null)Tables[title]=new JsonArray();var table=Tables[title]!.AsArray();
                    var rows=cells["rows"]!.AsArray().Select(r=>(JsonNode)new JsonArray(r!["values"]!.AsArray().Select(c=>c!["userEnteredValue"]!.AsObject().First().Value!.DeepClone()).ToArray())).ToArray();
                    if(kind=="appendCells"){foreach(var row in rows)table.Add(row);AfterAppend?.Invoke(table);}
                    else {var start=range["startRowIndex"]?.GetValue<int>()??0;while(table.Count<start+rows.Length)table.Add(new JsonArray());for(var i=0;i<rows.Length;i++)table[start+i]=rows[i];}
                }
            }
            return new JsonObject();
        }
    }
    [Fact] public void PythonRowsUpdateOneRowAfterSorting() {
        var server=new Server();var store=server.Store();var state=store.Load()!;
        var rows=server.Tables["Sessions"]!.AsArray();var first=rows[1]!.DeepClone();rows[1]=rows[2]!.DeepClone();rows[2]=first;
        var sessions=state.Sessions.ToArray();sessions[0]=sessions[0] with { Notes="Changed" };state=state with { Sessions=sessions };
        server.Calls=0;store.Save(state);Assert.Equal(3,server.Calls);
        var updates=server.Requests.Where(r=>r?["updateCells"]!=null).ToArray();Assert.Single(updates);Assert.Equal(2,updates[0]!["updateCells"]!["range"]!["startRowIndex"]!.GetValue<int>());Assert.Equal("Changed",rows[2]![5]!.ToString());
        Assert.DoesNotContain(server.Requests,r=>r?["repeatCell"]!=null);
        var count=server.Tables["TickChanges"]!.AsArray().Count;store.Save(state);Assert.Equal(count,server.Tables["TickChanges"]!.AsArray().Count);
    }
    [Fact] public void MigrationStaleSaveAndConcurrentBranchesPreserveData() {
        var server=new Server(true);var store=server.Store();var state=store.Load()!;var backup=server.Tables["TickLog"]!.DeepClone();store.Save(state);
        Assert.True(JsonNode.DeepEquals(backup,server.Tables["TickLogBackup"]));Assert.Null(server.Tables["TickLog"]);
        var other=server.Store();var stale=other.Load()!;var sessions=state.Sessions.ToArray();sessions[0]=sessions[0] with { Notes="New" };state=state with { Sessions=sessions };store.Save(state);
        Assert.Throws<InvalidDataException>(()=>other.Save(stale));
        sessions=state.Sessions.ToArray();sessions[0]=sessions[0] with { Notes="Concurrent" };state=state with { Sessions=sessions };
        server.AfterAppend=rows=> { var sibling=rows.Last()!.DeepClone();sibling[0]="sibling";rows.Add(sibling); };
        Assert.Throws<InvalidDataException>(()=>store.Save(state));Assert.Throws<InvalidDataException>(()=>server.Store().Load());Assert.True(server.Tables["TickChanges"]!.AsArray().Count>3);
    }
    [Fact] public void LongUnicodeNotesDeletionAndFailure() {
        var server=new Server();var store=server.Store();var state=store.Load()!;var sessions=state.Sessions.ToArray();var longText=string.Concat(Enumerable.Repeat("🍲",45000));sessions[0]=sessions[0] with { Notes=longText };state=state with { Sessions=sessions };store.Save(state);Assert.Equal(longText,store.Load()!.Sessions[0].Notes);
        var width=server.Tables["Sessions"]![1]!.AsArray().Count;sessions=state.Sessions.ToArray();sessions[0]=sessions[0] with { Notes="Short" };state=state with { Sessions=sessions };store.Save(state);Assert.Equal(width,server.Requests.First(r=>r?["updateCells"]!=null)!["updateCells"]!["range"]!["endColumnIndex"]!.GetValue<int>());
        state=state with { Sessions=state.Sessions.Take(1).ToArray() };store.Save(state);Assert.Single(store.Load()!.Sessions);
        sessions=state.Sessions.ToArray();sessions[0]=sessions[0] with { Notes="Offline" };state=state with { Sessions=sessions };server.FailWrite=true;Assert.Throws<IOException>(()=>store.Save(state));server.FailWrite=false;Assert.Equal("Short",store.Load()!.Sessions[0].Notes);
    }
    [Fact] public void InvalidIDAndIncompleteLogAreRejected() {
        Assert.Throws<InvalidDataException>(()=>new SheetsStore(new("http://example.com")));
        Assert.Throws<InvalidDataException>(()=>SheetsStore.DecodeLog(JsonNode.Parse("[[\"tick-log-v1\",\"revision\",\"\",0,2,\"{}\"]]")!.AsArray()));
    }
}
