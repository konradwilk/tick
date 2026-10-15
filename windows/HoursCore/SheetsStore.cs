using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace HoursCore;
public sealed record SheetsConfiguration(string SheetID, string SpreadsheetName = "Time is Clearly Kept");
public sealed record GoogleSpreadsheet(string Id, string Name) { public override string ToString() => Name; }
public sealed class GoogleSheetsAPI(GoogleAccount account, Func<string,string,JsonObject?,JsonObject>? transport = null)
{
    private static readonly HttpClient Client = new() { Timeout = TimeSpan.FromSeconds(30) };
    public JsonObject Request(string method, string url, JsonObject? body = null) {
        if (transport != null) return transport(method,url,body);
        using var request = new HttpRequestMessage(new HttpMethod(method),url);
        request.Headers.Authorization = new("Bearer",account.AccessToken());
        if (body != null) request.Content = new StringContent(body.ToJsonString(),Encoding.UTF8,"application/json");
        using var response = Client.SendAsync(request).GetAwaiter().GetResult();
        if (!response.IsSuccessStatusCode) throw new IOException("Google could not authorize or confirm the request. Reconnect and reload before retrying a save.");
        return JsonNode.Parse(response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()) as JsonObject ?? throw new InvalidDataException("Invalid Google response.");
    }
    public GoogleSpreadsheet[] List() {
        var files = new List<GoogleSpreadsheet>(); string? page = null;
        do {
            var url = "https://www.googleapis.com/drive/v3/files?q=" + Uri.EscapeDataString("mimeType='application/vnd.google-apps.spreadsheet' and trashed=false") + "&fields=nextPageToken,files(id,name)&pageSize=100";
            if (page != null) url += "&pageToken=" + Uri.EscapeDataString(page);
            var result = Request("GET",url);
            foreach (var item in result["files"]!.AsArray()) files.Add(new(item!["id"]!.GetValue<string>(),item["name"]!.GetValue<string>()));
            page = result["nextPageToken"]?.GetValue<string>();
        } while (page != null);
        return files.OrderBy(f=>f.Name,StringComparer.OrdinalIgnoreCase).ToArray();
    }
    public SheetsStore Create(string name) {
        name = name.Trim(); if (name.Length is 0 or >200) throw new InvalidDataException("Enter a spreadsheet name (1–200 characters).");
        var body = new JsonObject { ["properties"] = new JsonObject { ["title"]=name }, ["sheets"]=new JsonArray(new JsonObject { ["properties"]=new JsonObject { ["title"]="TickLog", ["gridProperties"]=new JsonObject { ["rowCount"]=1000,["columnCount"]=6 } } }) };
        var result = Request("POST","https://sheets.googleapis.com/v4/spreadsheets",body);
        return new(new(result["spreadsheetId"]!.GetValue<string>(),name),this);
    }
}
public sealed class SheetsStore
{
    public SheetsConfiguration Configuration { get; }
    private readonly GoogleSheetsAPI api;
    private string? revision;
    private bool hasLog;
    private JsonObject metadata = new();
    private string Base => "https://sheets.googleapis.com/v4/spreadsheets/"+Configuration.SheetID;
    public SheetsStore(SheetsConfiguration configuration, GoogleSheetsAPI? api=null) {
        if (configuration.SheetID==null || !Regex.IsMatch(configuration.SheetID,@"\A[A-Za-z0-9_-]+\z")) throw new InvalidDataException("Choose a spreadsheet used by Tick.");
        Configuration=configuration; this.api=api??new GoogleSheetsAPI(new GoogleAccount());
    }
    private JsonArray Rows(string range) => api.Request("GET",Base+"/values/"+range)["values"]?.AsArray() ?? new JsonArray();
    private (TrackerState? State,string? Revision) Read() {
        var metadata=api.Request("GET",Base+"?fields=sheets.properties,properties.title");
        this.metadata=metadata;
        var tabs=metadata["sheets"]!.AsArray().Select(s=>s!["properties"]!["title"]!.GetValue<string>()).ToArray();
        hasLog=tabs.Contains("TickLog");
        if (hasLog) { var rows=Rows("TickLog!A:F"); if (rows.Count>0) return DecodeLog(rows); }
        if (tabs.Contains("TickData")) {
            var rows=Rows("TickData!A1:A1002");
            if (rows.Count>0) {
                if (rows.Count<3 || !int.TryParse(rows[1]![0]!.ToString(),out var count) || count<1 || count>1000 || rows.Count<count+2) throw new InvalidDataException("Invalid previous Tick dataset.");
                return (PortableData.Decode(Encoding.UTF8.GetBytes(string.Concat(rows.Skip(2).Take(count).Select(r=>r![0]!.GetValue<string>())))),rows[0]![0]!.ToString());
            }
        }
        if (tabs.Any(t=>t is not ("TickLog" or "TickData"))) throw new InvalidDataException("This spreadsheet has no Tick dataset. Create a new Tick spreadsheet instead.");
        return (null,null);
    }
    public TrackerState? Load(bool requireExisting=true) {
        var (state, latest)=Read();
        if (state==null && requireExisting) throw new InvalidDataException("The Tick dataset is missing. Reconnect in Settings.");
        revision=latest; return state;
    }
    public void Save(TrackerState state) {
        var raw=PortableData.Encode(state); var (_, latest)=Read();
        if (latest!=revision) throw new InvalidDataException("Data changed on another device. Reload before saving.");
        if (!hasLog) {
            api.Request("POST",Base+":batchUpdate",JsonNode.Parse("{\"requests\":[{\"addSheet\":{\"properties\":{\"title\":\"TickLog\",\"gridProperties\":{\"rowCount\":1000,\"columnCount\":6}}}}]}")!.AsObject());
            Read();
        }
        var id=Guid.NewGuid().ToString(); var text=Encoding.UTF8.GetString(raw); var chunks=new List<string>();
        for (var start=0;start<text.Length;) { var end=Math.Min(start+40000,text.Length); if (end<text.Length && char.IsHighSurrogate(text[end-1]) && char.IsLowSurrogate(text[end])) end--; chunks.Add(text[start..end]);start=end; }
        if (chunks.Count>1000) throw new InvalidDataException("This dataset is too large for a Tick revision in Google Sheets. Use Local file storage.");
        var rows=new JsonArray();
        for (var i=0;i<chunks.Count;i++) rows.Add(new JsonArray("tick-log-v1",id,revision??"",i,chunks.Count,chunks[i]));
        var requests=TableRequests(raw);
        var log=metadata["sheets"]!.AsArray().Select(t=>t!["properties"]!).First(t=>t["title"]!.ToString()=="TickLog");
        requests.Add(new JsonObject { ["appendCells"]=new JsonObject { ["sheetId"]=log["sheetId"]?.GetValue<int>()??0,["rows"]=Cells(rows),["fields"]="userEnteredValue" } });
        api.Request("POST",Base+":batchUpdate",new JsonObject { ["requests"]=requests });
        var (saved, confirmed)=Read();
        if (confirmed!=id || saved==null || !PortableData.Encode(saved).SequenceEqual(raw)) throw new IOException("Save could not be confirmed. Reload before retrying.");
        revision=id;
    }

    private static JsonArray Cells(JsonArray rows) => new(rows.Select(row=>(JsonNode)new JsonObject { ["values"]=new JsonArray(row!.AsArray().Select(value=>(JsonNode)new JsonObject { ["userEnteredValue"]=new JsonObject { [value is JsonValue v && v.TryGetValue<string>(out _) ? "stringValue" : "numberValue"]=value!.DeepClone() } }).ToArray()) }).ToArray());
    private JsonArray TableRequests(byte[] raw) {
        var data=JsonNode.Parse(raw)!; var projects=data["nonprofits"]!.AsArray(); var sessions=data["sessions"]!.AsArray();
        var names=projects.ToDictionary(p=>p!["id"]!.ToString(),p=>p!["name"]!.ToString());
        var totals=names.Keys.ToDictionary(k=>k,k=>(Hours:0.0,Count:0));
        var rows=new JsonArray(new JsonArray("Project","Started (UTC)","Ended (UTC)","Duration","Hours","Notes","Status","Platform"));
        foreach(var session in sessions.OrderBy(s=>s!["startTimeUtc"]!.ToString(),StringComparer.Ordinal)) {
            var key=session!["projectId"]!.ToString(); var seconds=session["durationSeconds"]?.GetValue<double>(); var n=(long)(seconds??0); var ended=session["endTimeUtc"]?.ToString();
            rows.Add(new JsonArray(names.GetValueOrDefault(key,session["project"]!.ToString()),DateTimeOffset.Parse(session["startTimeUtc"]!.ToString(),System.Globalization.CultureInfo.InvariantCulture).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss",System.Globalization.CultureInfo.InvariantCulture),ended==null?"":DateTimeOffset.Parse(ended,System.Globalization.CultureInfo.InvariantCulture).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss",System.Globalization.CultureInfo.InvariantCulture),seconds==null?"":$"{n/3600}:{n/60%60:00}:{n%60:00}",seconds==null?JsonValue.Create(""):JsonValue.Create(seconds.Value/3600),session["notes"]!.ToString(),ended==null?"Running":"Completed",session["platform"]!.ToString()));
            if(totals.TryGetValue(key,out var old))totals[key]=(old.Hours+(seconds??0)/3600,old.Count+1);
        }
        var summary=new JsonArray(new JsonArray("Project","Total hours","Sessions"));
        foreach(var p in projects){var t=totals[p!["id"]!.ToString()];summary.Add(new JsonArray(p["name"]!.ToString(),t.Hours,t.Count));}
        var tabs=metadata["sheets"]!.AsArray().Select(t=>t!["properties"]!.AsObject()).ToArray();var used=tabs.Select(t=>t["sheetId"]?.GetValue<int>()??0).ToHashSet();var requests=new JsonArray();
        var allStyles=JsonNode.Parse("""[[{"updateSheetProperties":{"properties":{"sheetId":0,"index":0,"hidden":false,"gridProperties":{"frozenRowCount":1}},"fields":"index,hidden,gridProperties.frozenRowCount"}},{"updateCells":{"range":{"sheetId":0},"rows":[],"fields":"userEnteredValue,note"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.92,"green":0.93,"blue":0.94},"textFormat":{"bold":true,"foregroundColor":{"red":0,"green":0,"blue":0}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":1},"cell":{"userEnteredFormat":{"verticalAlignment":"TOP","wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"updateDimensionProperties":{"range":{"sheetId":0,"dimension":"COLUMNS","startIndex":0,"endIndex":8},"properties":{"pixelSize":160},"fields":"pixelSize"}},{"setBasicFilter":{"filter":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1,"startColumnIndex":0,"endColumnIndex":8}}}}],[{"updateSheetProperties":{"properties":{"sheetId":0,"index":1,"hidden":false,"gridProperties":{"frozenRowCount":1}},"fields":"index,hidden,gridProperties.frozenRowCount"}},{"updateCells":{"range":{"sheetId":0},"rows":[],"fields":"userEnteredValue,note"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1},"cell":{"userEnteredFormat":{"backgroundColor":{"red":0.92,"green":0.93,"blue":0.94},"textFormat":{"bold":true,"foregroundColor":{"red":0,"green":0,"blue":0}},"wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"repeatCell":{"range":{"sheetId":0,"startRowIndex":1},"cell":{"userEnteredFormat":{"verticalAlignment":"TOP","wrapStrategy":"WRAP"}},"fields":"userEnteredFormat"}},{"updateDimensionProperties":{"range":{"sheetId":0,"dimension":"COLUMNS","startIndex":0,"endIndex":3},"properties":{"pixelSize":160},"fields":"pixelSize"}},{"setBasicFilter":{"filter":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1,"startColumnIndex":0,"endColumnIndex":3}}}}]]""")!.AsArray();
        var tables=new[]{rows,summary};
        for(var index=0;index<2;index++) {
            var values=tables[index];var title=index==0?"Sessions":"Projects";var tab=tabs.FirstOrDefault(t=>t["title"]!.ToString()==title);var id=tab?["sheetId"]?.GetValue<int>()??(174001+index);
            if(tab==null){while(used.Contains(id))id++;used.Add(id);requests.Add(new JsonObject{["addSheet"]=new JsonObject{["properties"]=new JsonObject{["sheetId"]=id,["title"]=title,["gridProperties"]=new JsonObject{["rowCount"]=Math.Max(1000,values.Count),["columnCount"]=values[0]!.AsArray().Count}}}});}
            var size=Math.Max(tab?["gridProperties"]?["rowCount"]?.GetValue<int>()??1000,Math.Max(2,values.Count));
            requests.Add(new JsonObject{["updateSheetProperties"]=new JsonObject{["properties"]=new JsonObject{["sheetId"]=id,["gridProperties"]=new JsonObject{["rowCount"]=size}},["fields"]="gridProperties.rowCount"}});
            // Keep complete text in recovery history; generated cells stay within Google's cell limit.
            foreach(var row in values)foreach(var cell in row!.AsArray().ToArray())if(cell is JsonValue v && v.TryGetValue<string>(out var text) && text.Length>20000){var position=row.AsArray().IndexOf(cell);var end=20000;if(char.IsHighSurrogate(text[end-1]))end--;row[position]=text[..end];}
            var parts=allStyles[index]!.DeepClone().AsArray();
            foreach(var part in parts){var pair=part!.AsObject().First();var payload=pair.Value!.AsObject();if(payload["properties"]?["sheetId"]!=null)payload["properties"]!["sheetId"]=id;if(payload["range"]!=null)payload["range"]!["sheetId"]=id;if(payload["filter"]!=null){payload["filter"]!["range"]!["sheetId"]=id;payload["filter"]!["range"]!["endRowIndex"]=Math.Max(2,values.Count);}if(pair.Key=="updateCells"){var cells=Cells(values);cells[0]!["values"]![0]!["note"]="Generated by Tick. Edit projects and sessions in Tick; these tables refresh on every save.";payload["rows"]=cells;}requests.Add(part.DeepClone());}
            var column=index==0?4:1;
            requests.Add(JsonNode.Parse($$$$"""{"repeatCell":{"range":{"sheetId":{{{{id}}}},"startRowIndex":1,"startColumnIndex":{{{{column}}}},"endColumnIndex":{{{{column+1}}}}},"cell":{"userEnteredFormat":{"numberFormat":{"type":"NUMBER","pattern":"0.00"}}},"fields":"userEnteredFormat.numberFormat"}}"""));
            if(index==0)requests.Add(JsonNode.Parse($$$$"""{"updateDimensionProperties":{"range":{"sheetId":{{{{id}}}},"dimension":"COLUMNS","startIndex":5,"endIndex":6},"properties":{"pixelSize":420},"fields":"pixelSize"}}"""));
        }
        foreach(var tab in tabs.Where(t=>t["title"]!.ToString() is "TickLog" or "TickData"))requests.Add(new JsonObject{["updateSheetProperties"]=new JsonObject{["properties"]=new JsonObject{["sheetId"]=tab["sheetId"]?.GetValue<int>()??0,["hidden"]=true},["fields"]="hidden"}});
        return requests;
    }

    public static (TrackerState? State,string? Revision) DecodeLog(JsonArray rows) {
        int position=0; string? latest=null; TrackerState? state=null; var seen=new HashSet<string>();
        while (position<rows.Count) {
            var row=rows[position]!.AsArray();
            if (row.Count!=6 || row[0]!.ToString()!="tick-log-v1" || !int.TryParse(row[4]!.ToString(),out var count) || count<1 || count>1000 || position+count>rows.Count) throw new InvalidDataException("Invalid or incomplete Tick history.");
            var id=row[1]!.GetValue<string>(); var parent=row[2]!.GetValue<string>();
            if (string.IsNullOrEmpty(id)||!seen.Add(id)) throw new InvalidDataException("Invalid Tick revision.");
            if (latest!=null && parent!=latest) throw new InvalidDataException("Concurrent Google Sheets changes detected. Both versions are preserved in TickLog; recover before continuing.");
            var text=new StringBuilder();
            for (var i=0;i<count;i++) {
                var part=rows[position+i]!.AsArray();
                if (part.Count!=6 || part[0]!.ToString()!="tick-log-v1" || part[1]!.ToString()!=id || part[2]!.ToString()!=parent || part[3]!.ToString()!=i.ToString() || part[4]!.ToString()!=count.ToString()) throw new InvalidDataException("Invalid Tick history chunks.");
                text.Append(part[5]!.GetValue<string>());
            }
            state=PortableData.Decode(Encoding.UTF8.GetBytes(text.ToString())); latest=id;position+=count;
        }
        return (state,latest);
    }
}
