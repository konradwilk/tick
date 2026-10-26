using System.Text;
using System.Text.Json.Nodes;
namespace HoursCore;

// Shared row protocol: Sessions offset 8, Projects offset 3; chunked JSON retains full text.
internal sealed class SheetsRows(GoogleSheetsAPI api, string baseUrl, JsonObject metadata)
{
    private sealed record Row(int Index, JsonArray Cells, JsonObject Payload, string Deleted);
    private readonly Dictionary<string, Dictionary<string, Row>> records = new();
    private int logCount;
    private static InvalidDataException Invalid(string message = "Invalid Tick row storage. Reload before saving.") => new(message);
    private JsonObject[] Tabs => metadata["sheets"]!.AsArray().Select(x => x!["properties"]!.AsObject()).ToArray();
    private JsonObject Tab(string title) => Tabs.FirstOrDefault(x => x["title"]!.ToString() == title) ?? throw Invalid();
    private static bool Equal(JsonNode? a, JsonNode? b) => JsonNode.DeepEquals(a,b);
    private static string[] Chunks(string text) {
        var result = new List<string>();
        for (var start=0;start<text.Length;) { var end=Math.Min(start+20000,text.Length); if(end<text.Length && char.IsHighSurrogate(text[end-1]))end--;result.Add(text[start..end]);start=end; }
        if(result.Count is <1 or >1000)throw Invalid("This Tick row is too large. Use Local file storage.");
        return result.ToArray();
    }
    private static JsonArray Cells(JsonArray rows) => new(rows.Select(row => (JsonNode)new JsonObject { ["values"] = new JsonArray(row!.AsArray().Select(value => (JsonNode)new JsonObject { ["userEnteredValue"] = new JsonObject { [value is JsonValue v && v.TryGetValue<string>(out _) ? "stringValue" : "numberValue"] = value!.DeepClone() } }).ToArray()) }).ToArray());
    private JsonObject Update(string title, int index, JsonArray rows, int? width=null) => new() { ["updateCells"] = new JsonObject { ["range"] = new JsonObject { ["sheetId"]=Tab(title)["sheetId"]?.GetValue<int>()??0,["startRowIndex"]=index,["endRowIndex"]=index+rows.Count,["startColumnIndex"]=0,["endColumnIndex"]=width??rows.Max(x=>x!.AsArray().Count) },["rows"]=Cells(rows),["fields"]="userEnteredValue" } };
    public (TrackerState State, string? Revision) Read() {
        var ranges=new[]{"TickMeta!A1:B1","Sessions","Projects","TickChanges!A:D"};
        var response=api.Request("GET",baseUrl+"/values:batchGet?"+string.Join("&",ranges.Select(r=>"ranges="+Uri.EscapeDataString(r)))+"&valueRenderOption=UNFORMATTED_VALUE")["valueRanges"]?.AsArray();
        if(response?.Count!=4)throw Invalid();
        var values=response.Select(v=>v?["values"]?.AsArray()??new JsonArray()).ToArray();
        if(values[0].Count!=1 || values[0][0]!.AsArray().Count!=2 || values[0][0]![0]!.ToString()!="tick-rows-v1")throw Invalid();
        var root=JsonNode.Parse(values[0][0]![1]!.GetValue<string>())!.AsObject();
        var next=new Dictionary<string,Dictionary<string,Row>>();
        foreach(var (title,rows,offset,key) in new[]{("Sessions",values[1],8,"sessionId"),("Projects",values[2],3,"id")}) {
            if(rows.Count==0 || !Equal(new JsonArray(rows[0]!.AsArray().Skip(offset).Take(4).Select(x=>x!.DeepClone()).ToArray()),new JsonArray("Tick ID","Version","Deleted","Chunks")))throw Invalid();
            var entities=new Dictionary<string,Row>();
            for(var i=1;i<rows.Count;i++) {
                var row=rows[i]!.AsArray();if(row.Count==0)continue;
                if(row.Count<offset+5)throw Invalid();
                var id=row[offset]!.GetValue<string>().ToLowerInvariant();var version=row[offset+1]!.ToString();var deleted=row[offset+2]!.ToString();
                if(string.IsNullOrEmpty(id)||string.IsNullOrEmpty(version)||entities.ContainsKey(id)||deleted is not ("0" or "1")||!int.TryParse(row[offset+3]!.ToString(),out var count)||count is <1 or >1000||row.Count!=offset+4+count)throw Invalid();
                var payload=JsonNode.Parse(string.Concat(row.Skip(offset+4).Select(x=>x!.GetValue<string>())))!.AsObject();
                if(payload[key]!.ToString().ToLowerInvariant()!=id)throw Invalid();
                entities[id]=new(i,row.DeepClone().AsArray(),payload,deleted);
            }
            next[title]=entities;
        }
        string? latest=null;var changes=values[3];var position=0;var seen=new HashSet<string>();
        if(changes.Count==0)throw Invalid("The Tick change journal is missing. Keep this spreadsheet for recovery.");
        while(position<changes.Count) {
            var row=changes[position]!.AsArray();
            if(row.Count!=4)throw Invalid();
            var id=row[0]!.ToString();var parent=row[1]!.ToString();
            if(string.IsNullOrEmpty(id)||!seen.Add(id)||parent!=(latest??"")||!int.TryParse(row[3]!.ToString(),out var count)||count is <1 or >1000||position+count>changes.Count)throw Invalid("Concurrent Google Sheets changes detected. Both changes remain in TickChanges; recover before continuing.");
            for(var n=0;n<count;n++)if(!Equal(changes[position+n],new JsonArray(id,parent,n,count)))throw Invalid();
            latest=id;position+=count;
        }
        root["sessions"]=new JsonArray(next["Sessions"].Values.OrderBy(x=>x.Index).Where(x=>x.Deleted=="0").Select(x=>(JsonNode)x.Payload.DeepClone()).ToArray());
        root["nonprofits"]=new JsonArray(next["Projects"].Values.OrderBy(x=>x.Index).Where(x=>x.Deleted=="0").Select(x=>(JsonNode)x.Payload.DeepClone()).ToArray());
        var state=PortableData.Decode(Encoding.UTF8.GetBytes(root.ToJsonString()));
        var canonical=JsonNode.Parse(PortableData.Encode(state))!.AsObject();
        foreach(var (title,field,key) in new[]{("Sessions","sessions","sessionId"),("Projects","nonprofits","id")})foreach(var payload in canonical[field]!.AsArray()) {
            var id=payload![key]!.ToString().ToLowerInvariant();var old=next[title][id];next[title][id]=old with { Payload=payload.AsObject() };
        }
        records.Clear();foreach(var pair in next)records[pair.Key]=pair.Value;logCount=changes.Count;
        return (state,latest);
    }
    private JsonArray Initialize(TrackerState state) {
        var tabs=Tabs.Select(t=>t.DeepClone().AsObject()).ToList();var used=tabs.Select(t=>t["sheetId"]?.GetValue<int>()??0).ToHashSet();var requests=new JsonArray();
        foreach(var title in new[]{"TickLog","TickData"})if(tabs.FirstOrDefault(t=>t["title"]!.ToString()==title) is {} old) {
            if(tabs.Any(t=>t["title"]!.ToString()==title+"Backup"))throw Invalid("A Tick migration backup already exists. Keep this spreadsheet for recovery.");
            requests.Add(new JsonObject { ["updateSheetProperties"]=new JsonObject { ["properties"]=new JsonObject { ["sheetId"]=old["sheetId"]?.GetValue<int>()??0,["title"]=title+"Backup",["hidden"]=true },["fields"]="title,hidden" } });
        }
        var titles=new[]{"Sessions","Projects","TickMeta","TickChanges"};
        for(var i=0;i<titles.Length;i++)if(!tabs.Any(t=>t["title"]!.ToString()==titles[i])) {
            var id=174001+i;while(used.Contains(id))id++;used.Add(id);
            var props=new JsonObject { ["sheetId"]=id,["title"]=titles[i],["gridProperties"]=new JsonObject { ["rowCount"]=Math.Max(1000,Math.Max(state.Sessions.Length+1,state.Nonprofits.Length+1)),["columnCount"]=26 } };
            tabs.Add(props);requests.Add(new JsonObject { ["addSheet"]=new JsonObject { ["properties"]=props.DeepClone() } });
        }
        requests=new JsonArray(requests.OrderBy(r=>r?["addSheet"]==null?1:0).Select(r=>r!.DeepClone()).ToArray());
        metadata=new JsonObject { ["sheets"]=new JsonArray(tabs.Select(t=>(JsonNode)new JsonObject { ["properties"]=t }).ToArray()) };records.Clear();records["Sessions"]=new();records["Projects"]=new();logCount=0;
        var root=JsonNode.Parse(PortableData.Encode(state))!.AsObject();root.Remove("sessions");root.Remove("nonprofits");requests.Add(Update("TickMeta",0,new JsonArray(new JsonArray("tick-rows-v1",root.ToJsonString()))));
        foreach(var (title,header) in new[]{("Sessions",new JsonArray("Project","Started (UTC)","Ended (UTC)","Duration","Hours","Notes","Status","Platform")),("Projects",new JsonArray("Project","Total hours","Sessions"))}) {
            var offset=header.Count;foreach(var h in new[]{"Tick ID","Version","Deleted","Chunks","Tick data"})header.Add(h);
            requests.Add(Update(title,0,new JsonArray(header)));var tab=Tab(title);var id=tab["sheetId"]!.GetValue<int>();
            requests.Add(new JsonObject { ["updateSheetProperties"]=new JsonObject { ["properties"]=new JsonObject { ["sheetId"]=id,["gridProperties"]=new JsonObject { ["frozenRowCount"]=1 } },["fields"]="gridProperties.frozenRowCount" } });
            requests.Add(JsonNode.Parse($$$$"""{"repeatCell":{"range":{"sheetId":{{{{id}}}},"startRowIndex":0,"endRowIndex":1},"cell":{"userEnteredFormat":{"textFormat":{"bold":true}}},"fields":"userEnteredFormat.textFormat"}}"""));
            requests.Add(JsonNode.Parse($$$$"""{"updateDimensionProperties":{"range":{"sheetId":{{{{id}}}},"dimension":"COLUMNS","startIndex":{{{{offset}}}},"endIndex":{{{{Math.Max(offset+5,tab["gridProperties"]?["columnCount"]?.GetValue<int>()??26)}}}}},"properties":{"hiddenByUser":true},"fields":"hiddenByUser"}}"""));
        }
        foreach(var title in new[]{"TickMeta","TickChanges"})requests.Add(new JsonObject { ["updateSheetProperties"]=new JsonObject { ["properties"]=new JsonObject { ["sheetId"]=Tab(title)["sheetId"]!.DeepClone(),["hidden"]=true },["fields"]="hidden" } });
        return requests;
    }
    public string Save(TrackerState state,string? expected,bool initializing) {
        if(!initializing && Read().Revision!=expected)throw Invalid("Data changed on another device. Reload before saving.");
        var requests=initializing?Initialize(state):new JsonArray();var revision=Guid.NewGuid().ToString();var root=JsonNode.Parse(PortableData.Encode(state))!.AsObject();var projects=root["nonprofits"]!.AsArray();var sessions=root["sessions"]!.AsArray();
        var names=projects.ToDictionary(p=>p!["id"]!.ToString(),p=>p!["name"]!.ToString());var totals=names.Keys.ToDictionary(k=>k,k=>(Hours:0.0,Count:0));var sessionViews=new List<JsonArray>();
        foreach(var s in sessions) {
            var key=s!["projectId"]!.ToString();var seconds=s["durationSeconds"]?.GetValue<double>();var n=(long)(seconds??0);var ended=s["endTimeUtc"]?.ToString();
            sessionViews.Add(new JsonArray(names.GetValueOrDefault(key,s["project"]!.ToString()),s["startTimeUtc"]!.ToString()[..19].Replace('T',' '),ended==null?"":ended[..19].Replace('T',' '),seconds==null?"":$"{n/3600}:{n/60%60:00}:{n%60:00}",seconds==null?JsonValue.Create(""):JsonValue.Create(seconds/3600),s["notes"]!.ToString(),ended==null?"Running":"Completed",s["platform"]!.ToString()));
            var t=totals[key];totals[key]=(t.Hours+(seconds??0)/3600,t.Count+1);
        }
        var projectViews=projects.Select(p=> { var t=totals[p!["id"]!.ToString()];return new JsonArray(p["name"]!.ToString(),t.Hours,t.Count); }).ToList();var changed=new JsonArray();
        foreach(var (title,key,items,views) in new[]{("Sessions","sessionId",sessions,sessionViews),("Projects","id",projects,projectViews)}) {
            var old=records[title];var incoming=items.Select((p,i)=>(Id:p![key]!.ToString().ToLowerInvariant(),Payload:p!.AsObject(),View:views[i])).ToDictionary(x=>x.Id);var nextIndex=old.Values.Select(x=>x.Index).DefaultIfEmpty(0).Max()+1;
            foreach(var id in old.Keys.Union(incoming.Keys).OrderBy(x=>x,StringComparer.Ordinal)) {
                old.TryGetValue(id,out var before);var exists=incoming.TryGetValue(id,out var entry);var payload=exists?entry.Payload:before!.Payload;var view=exists?entry.View:new JsonArray(Enumerable.Repeat("",title=="Sessions"?8:3).Select(x=>(JsonNode)JsonValue.Create(x)!).ToArray());var deleted=exists?"0":"1";
                var safe=new JsonArray(view.Select(v=> { if(v is JsonValue value&&value.TryGetValue<string>(out var text)&&text.Length>20000){var end=20000;if(char.IsHighSurrogate(text[end-1]))end--;return (JsonNode)JsonValue.Create(text[..end])!;}return v!.DeepClone(); }).ToArray());
                if(before!=null&&before.Deleted==deleted&&Equal(before.Payload,payload)&&Equal(new JsonArray(before.Cells.Take(safe.Count).Select(x=>x!.DeepClone()).ToArray()),safe))continue;
                var parts=Chunks(payload.ToJsonString());var row=safe;
                row.Add(id);row.Add(revision);row.Add(deleted);row.Add(parts.Length);foreach(var part in parts)row.Add(part);var index=before?.Index??nextIndex++;requests.Add(Update(title,index,new JsonArray(row.DeepClone()),Math.Max(row.Count,before?.Cells.Count??0)));changed.Add(new JsonObject { ["table"]=title,["id"]=id,["row"]=row });
            }
        }
        if(changed.Count==0&&!initializing)return expected!;
        var audit=Chunks(new JsonObject { ["changes"]=changed }.ToJsonString());
        foreach(var tab in Tabs.Where(t=>t["title"]!.ToString() is "Sessions" or "Projects" or "TickChanges")) {
            var id=tab["sheetId"]!.GetValue<int>();var grid=tab["gridProperties"]?.AsObject();var updates=requests.Select(r=>r?["updateCells"]?["range"]?.AsObject()).Where(r=>r?["sheetId"]?.GetValue<int>()==id).ToArray();var rows=Math.Max(updates.Select(r=>r!["endRowIndex"]!.GetValue<int>()).DefaultIfEmpty(1).Max(),tab["title"]!.ToString()=="TickChanges"?logCount+audit.Length:1);var columns=updates.Select(r=>r!["endColumnIndex"]!.GetValue<int>()).DefaultIfEmpty(5).Max();var oldRows=grid?["rowCount"]?.GetValue<int>()??1000;var oldColumns=grid?["columnCount"]?.GetValue<int>()??26;
            if(rows>oldRows||columns>oldColumns){var grow=new JsonObject { ["updateSheetProperties"]=new JsonObject { ["properties"]=new JsonObject { ["sheetId"]=id,["gridProperties"]=new JsonObject { ["rowCount"]=Math.Max(rows,oldRows),["columnCount"]=Math.Max(columns,oldColumns) } },["fields"]="gridProperties.rowCount,gridProperties.columnCount" } };var insertion=requests.TakeWhile(r=>r?["updateCells"]==null).Count();requests.Insert(insertion,grow);}
        }
        foreach(var req in requests.ToArray())if(req?["updateSheetProperties"]?["properties"] is JsonObject props && props["gridProperties"]?["columnCount"] is {} columns) {
            var title=Tabs.First(t=>t["sheetId"]!.ToString()==props["sheetId"]!.ToString())["title"]!.ToString();
            if(title is "Sessions" or "Projects")requests.Add(new JsonObject { ["updateDimensionProperties"]=new JsonObject { ["range"]=new JsonObject { ["sheetId"]=props["sheetId"]!.DeepClone(),["dimension"]="COLUMNS",["startIndex"]=title=="Sessions"?8:3,["endIndex"]=columns.DeepClone() },["properties"]=new JsonObject { ["hiddenByUser"]=true },["fields"]="hiddenByUser" } });
        }
        var auditRows=new JsonArray(audit.Select((c,i)=>(JsonNode)new JsonArray(revision,initializing?"":expected??"",i,audit.Length,c)).ToArray());requests.Add(new JsonObject { ["appendCells"]=new JsonObject { ["sheetId"]=Tab("TickChanges")["sheetId"]!.DeepClone(),["rows"]=Cells(auditRows),["fields"]="userEnteredValue" } });
        api.Request("POST",baseUrl+":batchUpdate",new JsonObject { ["requests"]=requests });var (saved,confirmed)=Read();
        static JsonObject Normalize(TrackerState value){var v=JsonNode.Parse(PortableData.Encode(value))!.AsObject();var p=v["nonprofits"]!.AsArray().OrderBy(x=>x!["id"]!.ToString(),StringComparer.Ordinal).Select(x=>x!.DeepClone()).ToArray();v["nonprofits"]=new JsonArray(p);return v;}
        if(confirmed!=revision||!Equal(Normalize(saved),Normalize(state))||!changed.All(c=>records[c!["table"]!.ToString()].TryGetValue(c["id"]!.ToString(),out var row)&&Equal(row.Cells,c["row"])))throw Invalid("Save could not be confirmed. Reload before retrying.");
        foreach(var req in requests)if(req?["updateSheetProperties"]?["properties"] is JsonObject props && props["gridProperties"] is JsonObject grid) {
            var tab=Tabs.First(t=>t["sheetId"]!.ToString()==props["sheetId"]!.ToString());if(tab["gridProperties"]==null)tab["gridProperties"]=new JsonObject();foreach(var pair in grid)tab["gridProperties"]![pair.Key]=pair.Value!.DeepClone();
        }
        return revision;
    }
}
