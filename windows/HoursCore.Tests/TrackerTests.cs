using HoursCore;
using Xunit;
namespace HoursCore.Tests;
public class TrackerTests
{
    [Theory]
    [InlineData("Updated work, \"details\"\nSecond line")]
    [InlineData("")]
    public void EditedNotesPersistWithoutChangingRecordedHours(string notes)
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var id = tracker.AddNonprofit("Kitchen");
        tracker.Start(id, "Original", DateTimeOffset.UnixEpoch);
        tracker.Stop(DateTimeOffset.UnixEpoch.AddHours(1));
        var original = tracker.State.Sessions.Single() with { SyncState = "synced" };
        TrackerState? saved = null;
        tracker = new Tracker(tracker.State with { Sessions = [original] }, state => saved = state);
        var editedAt = DateTimeOffset.UnixEpoch.AddDays(1);

        tracker.UpdateNotes(original.SessionId, notes, editedAt);

        var restored = PortableData.Decode(PortableData.Encode(saved!));
        Assert.Equal(original with { Notes = notes, UpdatedAtUtc = editedAt, SyncState = "pending" }, restored.Sessions.Single());
        Assert.Equal(restored.Sessions, tracker.State.Sessions);
        Assert.Contains("\"" + notes.Replace("\"", "\"\"") + "\"", tracker.Csv());
    }
    [Fact] public void FailedNoteEditPreservesOriginalSession()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var id = tracker.AddNonprofit("Kitchen");
        tracker.Start(id, "Original", DateTimeOffset.UnixEpoch);
        tracker.Stop(DateTimeOffset.UnixEpoch.AddHours(1));
        var original = tracker.State;
        tracker = new Tracker(original, _ => throw new IOException("Disk full"));

        Assert.Throws<IOException>(() => tracker.UpdateNotes(original.Sessions.Single().SessionId, "Edited"));
        Assert.Same(original, tracker.State);
        Assert.Throws<InvalidOperationException>(() => tracker.UpdateNotes(Guid.NewGuid(), "Edited"));
        Assert.Same(original, tracker.State);
    }
    [Fact] public void RestartRetainsActiveSession()
    {
        var directory = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        try
        {
            var store = new FileStore(Path.Combine(directory, "sessions.json"));
            var tracker = new Tracker(store.Load(), store.Save);
            var id = tracker.AddNonprofit("Kitchen");
            tracker.Start(id, now: DateTimeOffset.UnixEpoch);
            Assert.Throws<InvalidOperationException>(() => tracker.Start(id));
            var restored = new Tracker(store.Load(), store.Save);
            Assert.Equal(tracker.State.Active!.SessionId, restored.State.Active!.SessionId);
            restored.Stop(DateTimeOffset.UnixEpoch.AddHours(1));
            Assert.Equal(3600L, restored.State.Sessions.Single().DurationSeconds);
            Assert.Null(store.Load().Active);
        }
        finally { if (Directory.Exists(directory)) Directory.Delete(directory, true); }
    }
    [Fact] public void FailedSaveDoesNotPublishState()
    {
        var nonprofit = new Nonprofit(Guid.NewGuid(), "Kitchen");
        var tracker = new Tracker(TrackerState.Empty() with { Nonprofits = [nonprofit] }, _ => throw new IOException("Disk full"));
        Assert.Throws<IOException>(() => tracker.Start(nonprofit.Id));
        Assert.Null(tracker.State.Active);
    }
    [Fact] public void ValidationAndExport()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        Assert.Throws<InvalidOperationException>(() => tracker.AddNonprofit(" "));
        var id = tracker.AddNonprofit("=SUM(1,2)");
        Assert.Throws<InvalidOperationException>(() => tracker.AddNonprofit("=sum(1,2)"));
        tracker.Start(id, "A, \"quote\"\nline", DateTimeOffset.UnixEpoch);
        Assert.DoesNotContain("SUM", tracker.Csv());
        Assert.Throws<InvalidOperationException>(() => tracker.Stop(DateTimeOffset.UnixEpoch.AddSeconds(-1)));
        Assert.NotNull(tracker.State.Active);
        tracker.Stop(DateTimeOffset.UnixEpoch.AddMinutes(1));
        Assert.Contains("\"'=SUM(1,2)\"", tracker.Csv());
        Assert.Contains("\"A, \"\"quote\"\"\nline\"", tracker.Csv());
    }
}
