using System.Text.Json.Nodes;
using HoursCore;
using Xunit;
namespace HoursCore.Tests;
public class SheetsStoreTests
{
    [Fact] public void RoundTripStaleSaveAndConcurrentBranchesPreserveData() {
        var rows=new JsonArray();var tables=new Dictionary<int,JsonArray>();
        var api=new GoogleSheetsAPI(new GoogleAccount(),(method,url,body)=> {
            if(url.Contains("?fields="))return JsonNode.Parse("{\"properties\":{\"title\":\"Time is Clearly Kept\"},\"sheets\":[{\"properties\":{\"title\":\"TickLog\"}}]}")!.AsObject();
            if(method=="GET")return new JsonObject { ["values"]=rows.DeepClone() };
            if(url.Contains(":batchUpdate")){foreach(var req in body!["requests"]!.AsArray()){if(req!["updateCells"] is JsonObject update)tables[update["range"]!["sheetId"]!.GetValue<int>()]=update["rows"]!.DeepClone().AsArray();if(req!["appendCells"] is JsonObject append)foreach(var row in append["rows"]!.AsArray())rows.Add(new JsonArray(row!["values"]!.AsArray().Select(c=>c!["userEnteredValue"]!.AsObject().First().Value!.DeepClone()).ToArray()));}return new JsonObject();}
            if(url.Contains(":append?")){ foreach(var row in body!["values"]!.AsArray())rows.Add(row!.DeepClone());return new JsonObject(); }
            throw new Exception("Unexpected request");
        });
        var store=new SheetsStore(new("test"),api);var state=TrackerState.Empty();store.Save(state);
        var tracker=new Tracker(store.Load()!,store.Save,()=>store.Load()!);var project=tracker.AddNonprofit("Kitchen");tracker.Start(project,"Meals");
        var other=new SheetsStore(new("test"),api);var stale=new Tracker(other.Load()!,other.Save);
        tracker.Stop();
        Assert.Equal(2,tables[174001].Count);
        Assert.Equal("Kitchen",tables[174001][1]!["values"]![0]!["userEnteredValue"]!["stringValue"]!.ToString());
        Assert.Equal("Completed",tables[174001][1]!["values"]![6]!["userEnteredValue"]!["stringValue"]!.ToString());
        Assert.Equal(1,tables[174002][1]!["values"]![2]!["userEnteredValue"]!["numberValue"]!.GetValue<int>());
        var before=PortableData.Encode(stale.State);
        Assert.Throws<InvalidDataException>(()=>stale.UpdateNotes(stale.State.Active!.SessionId,"Wrong"));
        Assert.Equal(before,PortableData.Encode(stale.State));
        var count=rows.Count;var sibling=rows.Last()!.DeepClone();sibling[1]="other-revision";rows.Add(sibling);
        Assert.Throws<InvalidDataException>(()=>store.Load());Assert.Equal(count+1,rows.Count);
    }
    [Fact] public void InvalidIDAndIncompleteLogAreRejected() {
        Assert.Throws<InvalidDataException>(()=>new SheetsStore(new("http://example.com")));
        Assert.Throws<InvalidDataException>(()=>SheetsStore.DecodeLog(JsonNode.Parse("[[\"tick-log-v1\",\"revision\",\"\",0,2,\"{}\"]]")!.AsArray()));
    }
}
