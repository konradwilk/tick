using System.Text;
using System.Text.Json.Nodes;
using HoursCore;
using Xunit;

namespace HoursCore.Tests;

public class PortableDataTests
{
    private static JsonObject Sample() => JsonNode.Parse("""
        {
          "schemaVersion": 1,
          "deviceId": "11111111-1111-1111-1111-111111111111",
          "nonprofits": [{"id": "22222222-2222-2222-2222-222222222222", "name": "Kitchen"}],
          "sessions": [{
            "sessionId": "33333333-3333-3333-3333-333333333333",
            "projectId": "22222222-2222-2222-2222-222222222222",
            "project": "Kitchen", "startTimeUtc": "2001-01-01T01:00:00+01:00",
            "endTimeUtc": "2001-01-01T01:01:00+01:00", "durationSeconds": 60,
            "notes": "Meals 🍲", "deviceId": "11111111-1111-1111-1111-111111111111",
            "platform": "linux", "updatedAtUtc": "2001-01-01T00:01:00Z", "syncState": "pending"
          }]
        }
        """)!.AsObject();

    private static byte[] Bytes(JsonNode node) => Encoding.UTF8.GetBytes(node.ToJsonString());
    private static JsonObject Session(JsonObject root) => root["sessions"]![0]!.AsObject();

    [Fact] public void SharedFileRoundTripsWithUtcDatesAndCamelCaseFields()
    {
        var state = PortableData.Decode(Bytes(Sample()));
        var encoded = PortableData.Encode(state);
        var json = JsonNode.Parse(encoded)!;
        Assert.Equal(1, json["schemaVersion"]!.GetValue<int>());
        Assert.Null(json["active"]);
        Assert.Null(json["DeviceId"]);
        var restored = PortableData.Decode(encoded);
        Assert.Equal(state.DeviceId, restored.DeviceId);
        Assert.Equal(state.Nonprofits, restored.Nonprofits);
        Assert.Equal(state.Sessions, restored.Sessions);
        Assert.Equal(TimeSpan.Zero, restored.Sessions[0].StartTimeUtc.Offset);
        Assert.Equal("Meals 🍲", restored.Sessions[0].Notes);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void LegacyAndroidAndAppleFilesAreMigrated(bool apple)
    {
        var json = Sample();
        json.Remove("schemaVersion");
        var session = Session(json);
        if (apple)
        {
            session["platform"] = "macos";
            session["startTimeUtc"] = 0.0;
            session["endTimeUtc"] = 60.0;
            session["updatedAtUtc"] = 60.5;
        }
        else
        {
            session.Remove("platform");
            session.Remove("syncState");
        }
        var state = PortableData.Decode(Bytes(json));
        Assert.Equal(1, state.SchemaVersion);
        Assert.Equal(apple ? "macos" : "android", state.Sessions[0].Platform);
        Assert.Equal("pending", state.Sessions[0].SyncState);
        Assert.Equal(new DateTimeOffset(2001, 1, 1, 0, 0, 0, TimeSpan.Zero), state.Sessions[0].StartTimeUtc);
        Assert.Equal(state.Sessions, PortableData.Decode(PortableData.Encode(state)).Sessions);
    }

    [Fact] public void OmittedOptionalFieldsRepresentAnActiveSession()
    {
        var json = Sample();
        Session(json).Remove("endTimeUtc");
        Session(json).Remove("durationSeconds");
        var state = PortableData.Decode(Bytes(json));
        Assert.NotNull(state.Active);
        Assert.Null(PortableData.Decode(PortableData.Encode(state)).Active!.DurationSeconds);
    }

    [Theory]
    [InlineData("version")]
    [InlineData("identity")]
    [InlineData("duplicateNonprofit")]
    [InlineData("duplicateSession")]
    [InlineData("unknownNonprofit")]
    [InlineData("duration")]
    [InlineData("negativeDuration")]
    [InlineData("backwardsTime")]
    [InlineData("activeDuration")]
    [InlineData("multipleActive")]
    [InlineData("timezone")]
    [InlineData("numericDate")]
    [InlineData("platform")]
    [InlineData("syncState")]
    [InlineData("missingNotes")]
    [InlineData("missingSessions")]
    public void MalformedHistoryIsRejected(string fault)
    {
        var json = Sample();
        var session = Session(json);
        switch (fault)
        {
            case "version": json["schemaVersion"] = 2; break;
            case "identity": json["deviceId"] = "bad"; break;
            case "duplicateNonprofit": json["nonprofits"]!.AsArray().Add(json["nonprofits"]![0]!.DeepClone()); break;
            case "duplicateSession": json["sessions"]!.AsArray().Add(session.DeepClone()); break;
            case "unknownNonprofit": session["projectId"] = Guid.NewGuid().ToString(); break;
            case "duration": session["durationSeconds"] = 12; break;
            case "negativeDuration": session["durationSeconds"] = -1; break;
            case "backwardsTime": session["endTimeUtc"] = "2000-01-01T00:00:00Z"; break;
            case "activeDuration": session["endTimeUtc"] = null; break;
            case "multipleActive":
                session["endTimeUtc"] = null;
                session["durationSeconds"] = null;
                var second = session.DeepClone();
                second["sessionId"] = Guid.NewGuid().ToString();
                json["sessions"]!.AsArray().Add(second);
                break;
            case "timezone": session["startTimeUtc"] = "2001-01-01T00:00:00"; break;
            case "numericDate": session["startTimeUtc"] = 0; break;
            case "platform": session["platform"] = "other"; break;
            case "syncState": session.Remove("syncState"); break;
            case "missingNotes": session.Remove("notes"); break;
            case "missingSessions": json.Remove("sessions"); break;
        }
        Assert.Throws<InvalidDataException>(() => PortableData.Decode(Bytes(json)));
    }

    [Theory]
    [InlineData("")]
    [InlineData("null")]
    [InlineData("[]")]
    [InlineData("{}")]
    public void InvalidDocumentsAreRejected(string text) =>
        Assert.Throws<InvalidDataException>(() => PortableData.Decode(Encoding.UTF8.GetBytes(text)));

    [Fact] public void InvalidSavePreservesExistingFile()
    {
        var directory = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        try
        {
            Directory.CreateDirectory(directory);
            var path = Path.Combine(directory, "sessions.json");
            var original = Bytes(Sample());
            File.WriteAllBytes(path, original);
            var store = new FileStore(path);
            var state = store.Load();
            Assert.Throws<InvalidDataException>(() => store.Save(state with { SchemaVersion = 2 }));
            Assert.Equal(original, File.ReadAllBytes(path));
        }
        finally { if (Directory.Exists(directory)) Directory.Delete(directory, true); }
    }
}
