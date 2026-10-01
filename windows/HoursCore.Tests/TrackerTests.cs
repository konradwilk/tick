using HoursCore;
using Xunit;
namespace HoursCore.Tests;
public class TrackerTests
{
    [Fact] public void ManualSessionPersistsAndExportsWithoutStoppingTimer()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var id = tracker.AddNonprofit("Kitchen");
        tracker.Start(id, "Active", DateTimeOffset.UnixEpoch);
        var active = tracker.State.Active;
        var start = DateTimeOffset.Parse("2025-01-01T23:00:00-05:00");
        var end = start.AddHours(2);
        tracker.AddSession(id, "Meals", start, end);
        var restored = PortableData.Decode(PortableData.Encode(tracker.State));
        var manual = restored.Sessions.Single(s => s.EndTimeUtc != null);
        Assert.Equal(7200L, manual.DurationSeconds);
        Assert.Equal(start.ToUniversalTime(), manual.StartTimeUtc);
        Assert.Equal(active, tracker.State.Active);
        Assert.Contains("Meals", tracker.Csv());
        Assert.Equal("Kitchen 02:00:00:\nMeals   02:00:00", tracker.ClipboardText());
        var original = tracker.State;
        Assert.Throws<InvalidOperationException>(() => tracker.AddSession(id, "Meals", end, start));
        Assert.Throws<InvalidOperationException>(() => tracker.AddSession(id, "Meals", start, start));
        Assert.Throws<InvalidOperationException>(() => tracker.AddSession(id, " ", start, end));
        Assert.Throws<InvalidOperationException>(() => tracker.AddSession(Guid.NewGuid(), "Meals", start, end));
        Assert.Same(original, tracker.State);
        tracker = new Tracker(original, _ => throw new IOException("Disk full"));
        Assert.Throws<IOException>(() => tracker.AddSession(id, "Meals", start, end));
        Assert.Same(original, tracker.State);
    }
    [Theory]
    [InlineData("", "No notes   00:23:43")]
    [InlineData("Annual meeting, Google Fi,Cooking,Etc", "Annual meeting   00:05:56\nCooking   00:05:56\nEtc   00:05:55\nGoogle Fi   00:05:56")]
    [InlineData("Meals,, Meals, ", "Meals   00:23:43")]
    [InlineData(", ,", "No notes   00:23:43")]
    [InlineData(" \t\r\n ", "No notes   00:23:43")]
    [InlineData("Annual meeting\nGoogle Fi", "Annual meeting   00:11:52\nGoogle Fi   00:11:51")]
    [InlineData("Annual meeting\rGoogle Fi", "Annual meeting   00:11:52\nGoogle Fi   00:11:51")]
    [InlineData(" Annual meeting\r\n \r\nGoogle Fi ", "Annual meeting   00:11:52\nGoogle Fi   00:11:51")]
    public void ClipboardNormalizesNotesWithoutChangingStoredText(string notes, string expected)
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var id = tracker.AddNonprofit("NEST");
        tracker.Start(id, notes, DateTimeOffset.UnixEpoch);
        tracker.Stop(DateTimeOffset.UnixEpoch.AddSeconds(1423));
        Assert.Equal($"NEST 00:23:43:\n{expected}", tracker.ClipboardText());
        Assert.Equal(notes, tracker.State.Sessions.Single().Notes);
    }
    [Fact] public void ClipboardCombinesDescriptionsAndSortsAlphabetically()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var kitchen = tracker.AddNonprofit("Kitchen");
        var garden = tracker.AddNonprofit("Garden");
        var start = DateTimeOffset.UnixEpoch;
        foreach (var (id, notes, seconds) in new[] { (kitchen, "Meals", 3600), (garden, "Planting", 1800), (kitchen, "Cleanup", 2700), (kitchen, " Cleanup ", 60), (kitchen, "", 1), (kitchen, " \n ", 2), (garden, "Cleanup", 120) })
        {
            tracker.Start(id, notes, start);
            start = start.AddSeconds(seconds);
            tracker.Stop(start);
        }
        Assert.Equal("Kitchen 01:46:03:\nCleanup   00:46:00\nMeals   01:00:00\nNo notes   00:00:03\n\nGarden 00:32:00:\nCleanup   00:02:00\nPlanting   00:30:00", tracker.ClipboardText());
        Assert.Equal(7, tracker.ExportSessions().Length);
        Assert.Contains(" Cleanup ", tracker.Csv());
    }
    [Theory]
    [InlineData(ExportPeriod.Daily, "2024-02-29", "2024-02-29", "2024-03-01")]
    [InlineData(ExportPeriod.Weekly, "2025-01-01", "2024-12-30", "2025-01-06")]
    [InlineData(ExportPeriod.Weekly, "2025-01-05", "2024-12-30", "2025-01-06")]
    [InlineData(ExportPeriod.Monthly, "2024-12-12", "2024-12-01", "2025-01-01")]
    public void ExportPeriodsUseCalendarBoundaries(ExportPeriod period, string date, string start, string end)
    {
        Assert.Equal(new ExportRange(DateOnly.Parse(start), DateOnly.Parse(end)), ExportRange.For(period, DateOnly.Parse(date)));
    }
    [Fact] public void CsvAndClipboardUseLocalStartDateAndExcludeActiveSessions()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var id = tracker.AddNonprofit("Kitchen");
        var start = DateTimeOffset.Parse("2024-12-31T22:00:00Z");
        tracker.Start(id, "Outside", start.AddSeconds(-1));
        tracker.Stop(start);
        tracker.Start(id, "Meals, \"served\"\nCleanup 🍲", start);
        tracker.Stop(start.AddHours(25));
        tracker.Start(id, "End boundary", start.AddDays(1));
        tracker.Stop(start.AddDays(1).AddMinutes(1));
        tracker.Start(id, "Active", start.AddMinutes(2));
        var range = ExportRange.For(ExportPeriod.Daily, new DateOnly(2025, 1, 1));
        var zone = TimeZoneInfo.CreateCustomTimeZone("Test", TimeSpan.FromHours(2), "Test", "Test");
        Assert.Single(tracker.ExportSessions(range, zone));
        Assert.Equal("Kitchen 25:00:00:\n\"served\"   08:20:00\nCleanup 🍲   08:20:00\nMeals   08:20:00", tracker.ClipboardText(range, zone));
        var csv = tracker.Csv(range, zone);
        Assert.Contains("Meals, \"\"served\"\"\nCleanup 🍲", csv);
        Assert.DoesNotContain("Outside", csv);
        Assert.DoesNotContain("Active", csv);
        Assert.DoesNotContain("End boundary", csv);
        Assert.Equal(2, tracker.ExportSessions(ExportRange.For(ExportPeriod.Monthly, new DateOnly(2025, 1, 1)), zone).Length);
        Assert.Equal(3, tracker.ExportSessions(ExportRange.For(ExportPeriod.Weekly, new DateOnly(2025, 1, 1)), zone).Length);
        Assert.Empty(tracker.ExportSessions(ExportRange.For(ExportPeriod.Daily, new DateOnly(2025, 1, 3)), zone));
        Assert.Equal("", tracker.ClipboardText(ExportRange.For(ExportPeriod.Daily, new DateOnly(2025, 1, 3)), zone));
    }
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
        Assert.Equal("nonprofitName,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform", tracker.Csv().Split("\r\n")[0]);
        Assert.DoesNotContain(id.ToString(), tracker.Csv());
        Assert.DoesNotContain(tracker.State.Sessions.Single().SessionId.ToString(), tracker.Csv());
        Assert.Contains("\"'=SUM(1,2)\"", tracker.Csv());
        Assert.Contains("\"A, \"\"quote\"\"\nline\"", tracker.Csv());
    }
}
