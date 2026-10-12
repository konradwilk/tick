using HoursCore;
using Xunit;
namespace HoursCore.Tests;
public class TrackerTests
{
    [Fact] public void ReloadUpdatesStateWithoutSavingAndPreservesStateOnFailure()
    {
        var initial = TrackerState.Empty();
        var latest = initial with { Nonprofits = [new Nonprofit(Guid.NewGuid(), "Remote")] };
        var fail = false;
        var saves = 0;
        var tracker = new Tracker(initial, _ => saves++, () => fail ? throw new IOException("Unavailable") : latest);
        tracker.Reload();
        Assert.Same(latest, tracker.State);
        Assert.Equal(0, saves);
        fail = true;
        Assert.Throws<IOException>(() => tracker.Reload());
        Assert.Same(latest, tracker.State);
    }
    [Fact] public void SessionConflictsCoverBoundariesAndProjects()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => {});
        var first = tracker.AddNonprofit("Kitchen");
        var second = tracker.AddNonprofit("Board");
        DateTimeOffset Time(int seconds) => DateTimeOffset.UnixEpoch.AddSeconds(seconds);
        tracker.AddSession(first, "Meals", Time(100), Time(200));
        foreach (var (start, end, expected) in new[] { (50,150,50), (150,250,50), (125,175,50), (50,250,100), (100,200,100), (0,100,0), (200,300,0) }) {
            var conflicts = tracker.SessionConflicts(Time(start), Time(end));
            Assert.Equal(expected == 0 ? 0 : 1, conflicts.Length);
            if (expected > 0) {
                Assert.Equal(expected, conflicts[0].Overlap.TotalSeconds);
                Assert.Equal(100, conflicts[0].Duration.TotalSeconds);
                Assert.Equal(Time(Math.Max(start, 100)), conflicts[0].Start);
                Assert.Equal(Time(Math.Min(end, 200)), conflicts[0].End);
                Assert.Contains("Meals — Kitchen", conflicts[0].ToString());
            }
        }
        tracker.AddSession(second, "Meeting", Time(150), Time(300));
        Assert.Equal(new double[] {25, 50}, tracker.SessionConflicts(Time(175), Time(225)).Select(c => c.Overlap.TotalSeconds));
        Assert.Equal(2, tracker.State.Sessions.Length);
        Assert.Empty(tracker.SessionConflicts(Time(225), Time(175)));
        tracker.Start(first, "Running", Time(400));
        var active = Assert.Single(tracker.SessionConflicts(Time(425), Time(600), Time(500)));
        Assert.Equal(75, active.Overlap.TotalSeconds);
        Assert.Contains("running, so far", active.ToString());
    }
    [Fact] public void StartReloadsSharedFileBeforeValidation()
    {
        var directory = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString());
        Directory.CreateDirectory(directory);
        try
        {
            var path = Path.Combine(directory, "tick.json");
            var store = new FileStore(path);
            var tracker = new Tracker(store.Load(), store.Save, () => store.Load(true));
            var id = tracker.AddNonprofit("Kitchen");
            var remoteStore = new FileStore(path);
            var other = new Tracker(remoteStore.Load(true), remoteStore.Save, () => remoteStore.Load(true));
            other.Start(id, "Remote", DateTimeOffset.UnixEpoch);
            var before = File.ReadAllBytes(path);
            Assert.Throws<InvalidOperationException>(() => tracker.Start(id));
            Assert.Equal(other.State.Active!.SessionId, tracker.State.Active!.SessionId);
            Assert.Equal(before, File.ReadAllBytes(path));
            other.Stop(DateTimeOffset.UnixEpoch.AddMinutes(1));
            tracker.Start(id, "Local", DateTimeOffset.UnixEpoch.AddMinutes(2));
            Assert.Equal(new[] { "Remote", "Local" }, store.Load(true).Sessions.Select(s => s.Notes));
            File.WriteAllText(path, "broken");
            Assert.ThrowsAny<Exception>(() => tracker.Start(id));
            Assert.Equal("broken", File.ReadAllText(path));
            File.Delete(path);
            Assert.ThrowsAny<IOException>(() => tracker.Start(id));
            Assert.False(File.Exists(path));
        }
        finally { Directory.Delete(directory, true); }
    }
    [Fact] public void EditTimesRecalculatesReportsAndPreservesStateOnFailure()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var id = tracker.AddNonprofit("Kitchen");
        var start = DateTimeOffset.UnixEpoch;
        tracker.AddSession(id, "Meals", start, start.AddHours(1));
        var original = tracker.State.Sessions.Single();
        tracker.Start(id, "Active", start.AddDays(2));
        var active = tracker.State.Active;
        var editedStart = start.AddDays(-1).ToOffset(TimeSpan.FromHours(2));
        tracker.UpdateTimes(original.SessionId, editedStart, editedStart.AddMinutes(30), start.AddDays(3));
        var updated = tracker.State.Sessions[0];
        Assert.Equal(original.SessionId, updated.SessionId);
        Assert.Equal(original.Notes, updated.Notes);
        Assert.Equal(1800L, updated.DurationSeconds);
        Assert.Equal(TimeSpan.Zero, updated.StartTimeUtc.Offset);
        Assert.Equal(active, tracker.State.Active);
        Assert.Contains("00:30:00", tracker.ClipboardText());
        var range = ExportRange.For(ExportPeriod.Daily, DateOnly.FromDateTime(editedStart.UtcDateTime));
        Assert.Single(tracker.ExportSessions(range, TimeZoneInfo.Utc));
        var before = tracker.State;
        Assert.Throws<InvalidOperationException>(() => tracker.UpdateTimes(original.SessionId, start, start));
        Assert.Throws<InvalidOperationException>(() => tracker.UpdateTimes(original.SessionId, start, start.AddSeconds(-1)));
        Assert.Throws<InvalidOperationException>(() => tracker.UpdateTimes(active!.SessionId, start, start.AddMinutes(1)));
        Assert.Throws<InvalidOperationException>(() => tracker.UpdateTimes(Guid.NewGuid(), start, start.AddMinutes(1)));
        Assert.Same(before, tracker.State);
        var failing = new Tracker(before, _ => throw new IOException("Disk full"));
        Assert.Throws<IOException>(() => failing.UpdateTimes(original.SessionId, start, start.AddHours(2)));
        Assert.Same(before, failing.State);
        var restored = PortableData.Decode(PortableData.Encode(before));
        Assert.Equal(updated, restored.Sessions[0]);
    }

    [Fact] public void CapitalizesNewAndEditedActivitiesWithoutChangingOtherLetters()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var id = tracker.AddNonprofit("kitchen");
        Assert.Equal("Kitchen", tracker.State.Nonprofits.Single().Name);
        tracker.Start(id, "  emails, google Fi\n990-EZ review", DateTimeOffset.UnixEpoch);
        Assert.Equal("  Emails, Google Fi\n990-EZ review", tracker.State.Active!.Notes);
        tracker.Stop(DateTimeOffset.UnixEpoch.AddHours(1));
        tracker.UpdateNotes(tracker.State.Sessions.Single().SessionId, "collect payments\r\n\"annual meeting\",MN DOT");
        Assert.Equal("Collect payments\r\n\"Annual meeting\",MN DOT", tracker.State.Sessions.Single().Notes);
        tracker.AddSession(id, "cooking,etc", DateTimeOffset.UnixEpoch, DateTimeOffset.UnixEpoch.AddMinutes(15));
        Assert.Equal("Cooking,Etc", tracker.State.Sessions.Last().Notes);
    }
    [Theory]
    [InlineData(0)] [InlineData(59)] [InlineData(60)]
    public void DeleteOnlyShortCompletedSessions(int seconds)
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => { });
        var id = tracker.AddNonprofit("Kitchen");
        tracker.Start(id, "Short", DateTimeOffset.UnixEpoch);
        var sessionId = tracker.State.Active!.SessionId;
        Assert.Throws<InvalidOperationException>(() => tracker.DeleteSession(sessionId));
        tracker.Stop(DateTimeOffset.UnixEpoch.AddSeconds(seconds));
        var original = tracker.State;
        var failing = new Tracker(original, _ => throw new IOException("Disk full"));
        if (seconds < 60)
        {
            Assert.Throws<IOException>(() => failing.DeleteSession(sessionId));
            Assert.Same(original, failing.State);
            tracker.DeleteSession(sessionId);
            Assert.Empty(PortableData.Decode(PortableData.Encode(tracker.State)).Sessions);
            Assert.Equal("", tracker.ClipboardText());
            Assert.DoesNotContain("Short", tracker.Csv());
        }
        else Assert.Throws<InvalidOperationException>(() => tracker.DeleteSession(sessionId));
        Assert.Throws<InvalidOperationException>(() => tracker.DeleteSession(Guid.NewGuid()));
    }
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
    [Fact] public void SummaryUsesProjectIdInsteadOfStaleSessionName()
    {
        var tracker = new Tracker(TrackerState.Empty(), _ => {});
        var family = tracker.AddNonprofit("Family");
        var volunteer = tracker.AddNonprofit("Volunteer");
        var start = DateTimeOffset.UnixEpoch;
        tracker.AddSession(family, "Cake", start, start.AddSeconds(60));
        tracker.AddSession(volunteer, "Donations", start.AddSeconds(60), start.AddSeconds(180));
        var sessions = tracker.State.Sessions.Select(s => s with { Project = "Family" }).ToArray();
        var restored = new Tracker(tracker.State with { Sessions = sessions }, _ => throw new Exception("Summary must not save"));
        const string expected = "Family 00:01:00:\nCake   00:01:00\n\nVolunteer 00:02:00:\nDonations   00:02:00";
        Assert.Equal(expected, restored.ClipboardText());
        Assert.Equal(expected, restored.ClipboardText(ExportRange.For(ExportPeriod.Weekly, new DateOnly(1970, 1, 1)), TimeZoneInfo.Utc));
        Assert.Equal("Family", restored.State.Sessions[1].Project);
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
        tracker.Start(id, "Meals, \"Served\"\nCleanup 🍲", start);
        tracker.Stop(start.AddHours(25));
        tracker.Start(id, "End boundary", start.AddDays(1));
        tracker.Stop(start.AddDays(1).AddMinutes(1));
        tracker.Start(id, "Active", start.AddMinutes(2));
        var range = ExportRange.For(ExportPeriod.Daily, new DateOnly(2025, 1, 1));
        var zone = TimeZoneInfo.CreateCustomTimeZone("Test", TimeSpan.FromHours(2), "Test", "Test");
        Assert.Single(tracker.ExportSessions(range, zone));
        Assert.Equal("Kitchen 25:00:00:\n\"Served\"   08:20:00\nCleanup 🍲   08:20:00\nMeals   08:20:00", tracker.ClipboardText(range, zone));
        var csv = tracker.Csv(range, zone);
        Assert.Contains("Meals, \"\"Served\"\"\nCleanup 🍲", csv);
        Assert.DoesNotContain("Outside", csv);
        Assert.DoesNotContain("Active", csv);
        Assert.DoesNotContain("End boundary", csv);
        Assert.Equal(2, tracker.ExportSessions(ExportRange.For(ExportPeriod.Monthly, new DateOnly(2025, 1, 1)), zone).Length);
        Assert.Equal(3, tracker.ExportSessions(ExportRange.For(ExportPeriod.Weekly, new DateOnly(2025, 1, 1)), zone).Length);
        Assert.Empty(tracker.ExportSessions(ExportRange.For(ExportPeriod.Daily, new DateOnly(2025, 1, 3)), zone));
        Assert.Equal("", tracker.ClipboardText(ExportRange.For(ExportPeriod.Daily, new DateOnly(2025, 1, 3)), zone));
    }
    [Theory]
    [InlineData("Updated work, \"Details\"\nSecond line")]
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
        tracker.Start(id, "A, \"Quote\"\nLine", DateTimeOffset.UnixEpoch);
        Assert.DoesNotContain("SUM", tracker.Csv());
        Assert.Throws<InvalidOperationException>(() => tracker.Stop(DateTimeOffset.UnixEpoch.AddSeconds(-1)));
        Assert.NotNull(tracker.State.Active);
        tracker.Stop(DateTimeOffset.UnixEpoch.AddMinutes(1));
        Assert.Equal("project,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform", tracker.Csv().Split("\r\n")[0]);
        Assert.DoesNotContain(id.ToString(), tracker.Csv());
        Assert.DoesNotContain(tracker.State.Sessions.Single().SessionId.ToString(), tracker.Csv());
        Assert.Contains("\"'=SUM(1,2)\"", tracker.Csv());
        Assert.Contains("\"A, \"\"Quote\"\"\nLine\"", tracker.Csv());
    }
}
