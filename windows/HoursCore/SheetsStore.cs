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
    private SheetsRows? rowStore;
    private JsonObject metadata = new();
    private string Base => "https://sheets.googleapis.com/v4/spreadsheets/"+Configuration.SheetID;
    public SheetsStore(SheetsConfiguration configuration, GoogleSheetsAPI? api=null) {
        if (configuration.SheetID==null || !Regex.IsMatch(configuration.SheetID,@"\A[A-Za-z0-9_-]+\z")) throw new InvalidDataException("Choose a spreadsheet used by Tick.");
        Configuration=configuration; this.api=api??new GoogleSheetsAPI(new GoogleAccount());
    }
    private JsonArray Rows(string range) => api.Request("GET",Base+"/values/"+range)["values"]?.AsArray() ?? new JsonArray();
    private (TrackerState? State,string? Revision) Read() {
        if(rowStore!=null){var result=rowStore.Read();return (result.State,result.Revision);}
        var metadata=api.Request("GET",Base+"?fields=sheets.properties,properties.title");
        this.metadata=metadata;
        var tabs=metadata["sheets"]!.AsArray().Select(s=>s!["properties"]!["title"]!.GetValue<string>()).ToArray();
        if(tabs.Contains("TickMeta")){rowStore=new SheetsRows(api,Base,metadata);var result=rowStore.Read();return (result.State,result.Revision);}
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
        if(rowStore!=null){revision=rowStore.Save(state,revision,false);return;}
        var (_,latest)=Read();
        if(latest!=revision)throw new InvalidDataException("Data changed on another device. Reload before saving.");
        if(rowStore!=null){revision=rowStore.Save(state,revision,false);return;}
        rowStore=new SheetsRows(api,Base,metadata);
        revision=rowStore.Save(state,revision,true);
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
