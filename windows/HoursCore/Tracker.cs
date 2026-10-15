using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace HoursCore;
public enum ExportPeriod { Daily, Weekly, Monthly }
public record ExportRange(DateOnly Start, DateOnly End)
{
    public static ExportRange For(ExportPeriod period, DateOnly date)
    {
        var start = period switch {
            ExportPeriod.Daily => date,
            ExportPeriod.Weekly => date.AddDays(-((int)date.DayOfWeek + 6) % 7),
            ExportPeriod.Monthly => new DateOnly(date.Year, date.Month, 1),
            _ => throw new ArgumentOutOfRangeException(nameof(period))
        };
        return new(start, period == ExportPeriod.Monthly ? start.AddMonths(1) : start.AddDays(period == ExportPeriod.Weekly ? 7 : 1));
    }
}
public record Nonprofit(Guid Id, string Name);
public record Session(Guid SessionId, Guid ProjectId, string Project,
    DateTimeOffset StartTimeUtc, DateTimeOffset? EndTimeUtc, long? DurationSeconds,
    string Notes, Guid DeviceId, string Platform, DateTimeOffset UpdatedAtUtc, string SyncState = "pending");
public record SessionConflict(Session Session, DateTimeOffset Start, DateTimeOffset End, DateTimeOffset ExistingEnd)
{
    public TimeSpan Duration => ExistingEnd - Session.StartTimeUtc;
    public TimeSpan Overlap => End - Start;
    private static string DurationText(TimeSpan value) => $"{(long)value.TotalHours:00}:{value.Minutes:00}:{value.Seconds:00}";
    public override string ToString() => $"{(string.IsNullOrWhiteSpace(Session.Notes) ? "No notes" : Session.Notes.Trim())} — {Session.Project}\nDuration: {DurationText(Duration)}{(Session.EndTimeUtc == null ? " (running, so far)" : "")}\nOverlap: {DurationText(Overlap)}\n{Start.ToLocalTime():G} – {End.ToLocalTime():G}";
}
public record TrackerState(Guid DeviceId, Nonprofit[] Nonprofits, Session[] Sessions)
{
    public int SchemaVersion { get; init; } = 1;
    [JsonIgnore] public Session? Active => Sessions.FirstOrDefault(s => s.EndTimeUtc == null);
    public static TrackerState Empty() => new(Guid.NewGuid(), [], []);
}
public sealed class Tracker
{
    private static string CapitalizeEntries(string value)
    {
        var result = new System.Text.StringBuilder();
        var first = true;
        foreach (var character in value)
        {
            result.Append(first && char.IsLetter(character) ? char.ToUpperInvariant(character) : character);
            if (char.IsLetter(character)) first = false;
            if (character is ',' or '\r' or '\n') first = true;
        }
        return result.ToString();
    }
    public TrackerState State { get; private set; }
    private readonly Action<TrackerState> save;
    private readonly Func<TrackerState>? reload;
    public Tracker(TrackerState initial, Action<TrackerState> save, Func<TrackerState>? reload = null)
    { State = initial; this.save = save; this.reload = reload; }
    public void Reload() { if (reload != null) State = reload(); }
    private void Commit(TrackerState next) { save(next); State = next; }
    public Guid AddNonprofit(string input)
    {
        var name = CapitalizeEntries(input.Trim());
        if (name.Length == 0 || State.Nonprofits.Any(n => n.Name.Equals(name, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException("Enter a unique project name.");
        var nonprofit = new Nonprofit(Guid.NewGuid(), name);
        Commit(State with { Nonprofits = [..State.Nonprofits, nonprofit] });
        return nonprofit.Id;
    }
    public void Start(Guid id, string notes = "", DateTimeOffset? now = null)
    {
        Reload();
        if (State.Active != null) throw new InvalidOperationException("Stop the current session first.");
        var nonprofit = State.Nonprofits.FirstOrDefault(n => n.Id == id) ?? throw new InvalidOperationException("Select a project.");
        var date = (now ?? DateTimeOffset.UtcNow).ToUniversalTime();
        var session = new Session(Guid.NewGuid(), id, nonprofit.Name, date, null, null, CapitalizeEntries(notes), State.DeviceId, "windows", date);
        Commit(State with { Sessions = [..State.Sessions, session] });
    }
    public void Stop(DateTimeOffset? now = null)
    {
        var active = State.Active ?? throw new InvalidOperationException("There is no active session.");
        var date = (now ?? DateTimeOffset.UtcNow).ToUniversalTime();
        if (date < active.StartTimeUtc) throw new InvalidOperationException("Correct the system clock before stopping.");
        var completed = active with { EndTimeUtc = date, DurationSeconds = (long)(date - active.StartTimeUtc).TotalSeconds, UpdatedAtUtc = date };
        Commit(State with { Sessions = State.Sessions.Select(s => s.SessionId == active.SessionId ? completed : s).ToArray() });
    }
    public SessionConflict[] SessionConflicts(DateTimeOffset start, DateTimeOffset end, DateTimeOffset? now = null)
    {
        if (end <= start) return [];
        return State.Sessions.Select(session => {
            var existingEnd = session.EndTimeUtc ?? now ?? DateTimeOffset.UtcNow;
            var lower = start > session.StartTimeUtc ? start : session.StartTimeUtc;
            var upper = end < existingEnd ? end : existingEnd;
            return new SessionConflict(session, lower, upper, existingEnd);
        }).Where(c => c.End > c.Start).OrderBy(c => c.Start).ToArray();
    }
    public void AddSession(Guid id, string notes, DateTimeOffset start, DateTimeOffset end, DateTimeOffset? now = null)
    {
        var nonprofit = State.Nonprofits.FirstOrDefault(n => n.Id == id) ?? throw new InvalidOperationException("Select a project.");
        if (string.IsNullOrWhiteSpace(notes)) throw new InvalidOperationException("Enter what you worked on.");
        if (end <= start) throw new InvalidOperationException("End must be after start.");
        var session = new Session(Guid.NewGuid(), id, nonprofit.Name, start.ToUniversalTime(), end.ToUniversalTime(),
            (long)(end - start).TotalSeconds, CapitalizeEntries(notes), State.DeviceId, "windows", (now ?? DateTimeOffset.UtcNow).ToUniversalTime());
        Commit(State with { Sessions = [..State.Sessions, session] });
    }
    public void DeleteSession(Guid sessionId)
    {
        var session = State.Sessions.FirstOrDefault(s => s.SessionId == sessionId) ?? throw new InvalidOperationException("The session could not be found.");
        if (session.EndTimeUtc == null || session.DurationSeconds is not (>= 0 and < 60))
            throw new InvalidOperationException("Only completed sessions under one minute can be deleted.");
        Commit(State with { Sessions = State.Sessions.Where(s => s.SessionId != sessionId).ToArray() });
    }
    public void UpdateTimes(Guid sessionId, DateTimeOffset start, DateTimeOffset end, DateTimeOffset? now = null)
    {
        var session = State.Sessions.FirstOrDefault(s => s.SessionId == sessionId)
            ?? throw new InvalidOperationException("The session could not be found.");
        if (session.EndTimeUtc == null) throw new InvalidOperationException("Stop the session before editing its times.");
        if (end <= start) throw new InvalidOperationException("End must be after start.");
        var updated = session with { StartTimeUtc = start.ToUniversalTime(), EndTimeUtc = end.ToUniversalTime(),
            DurationSeconds = (long)(end - start).TotalSeconds, UpdatedAtUtc = (now ?? DateTimeOffset.UtcNow).ToUniversalTime(), SyncState = "pending" };
        Commit(State with { Sessions = State.Sessions.Select(s => s.SessionId == sessionId ? updated : s).ToArray() });
    }
    public void UpdateNotes(Guid sessionId, string notes, DateTimeOffset? now = null)
    {
        var session = State.Sessions.FirstOrDefault(s => s.SessionId == sessionId)
            ?? throw new InvalidOperationException("The session could not be found.");
        var updated = session with { Notes = CapitalizeEntries(notes), UpdatedAtUtc = (now ?? DateTimeOffset.UtcNow).ToUniversalTime(), SyncState = "pending" };
        Commit(State with { Sessions = State.Sessions.Select(s => s.SessionId == sessionId ? updated : s).ToArray() });
    }
    public Session[] ExportSessions(ExportRange? range = null, TimeZoneInfo? zone = null) => State.Sessions
        .Where(s => s.EndTimeUtc != null && (range == null || InRange(s, range, zone ?? TimeZoneInfo.Local)))
        .OrderBy(s => s.StartTimeUtc).ToArray();
    private static bool InRange(Session session, ExportRange range, TimeZoneInfo zone)
    {
        var day = DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(session.StartTimeUtc, zone).DateTime);
        return day >= range.Start && day < range.End;
    }
    public string ClipboardText(ExportRange? range = null, TimeZoneInfo? zone = null)
    {
        static string Duration(long seconds) => $"{seconds / 3600:00}:{seconds % 3600 / 60:00}:{seconds % 60:00}";
        static IEnumerable<(string Name, long Seconds)> Activities(Session session)
        {
            var names = session.Notes.Split(new[] { ',', '\r', '\n' }, StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
            if (names.Length == 0) names = ["No notes"];
            var seconds = session.DurationSeconds ?? 0;
            return names.Select((name, index) => (name, seconds / names.Length + (index < seconds % names.Length ? 1 : 0)));
        }
        var projectNames = State.Nonprofits.ToDictionary(n => n.Id, n => n.Name);
        return string.Join("\n\n", ExportSessions(range, zone).GroupBy(s => s.ProjectId).Select(group =>
            $"{projectNames.GetValueOrDefault(group.Key, group.First().Project)} {Duration(group.Sum(s => s.DurationSeconds ?? 0))}:\n" +
            string.Join("\n", group.SelectMany(Activities).GroupBy(s => s.Name, StringComparer.Ordinal)
                .OrderBy(g => g.Key, StringComparer.OrdinalIgnoreCase).ThenBy(g => g.Key, StringComparer.Ordinal)
                .Select(g => $"{g.Key}   {Duration(g.Sum(s => s.Seconds))}"))));
    }
    public string Csv(ExportRange? range = null, TimeZoneInfo? zone = null)
    {
        static string Cell(string value)
        {
            if (value.TrimStart().FirstOrDefault() is '=' or '+' or '-' or '@') value = "'" + value;
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }
        static string Date(DateTimeOffset value) => value.UtcDateTime.ToString("O", CultureInfo.InvariantCulture);
        var rows = new List<string> { "project,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform" };
        foreach (var s in ExportSessions(range, zone))
            rows.Add(string.Join(",", new[] { s.Project,
                Date(s.StartTimeUtc), Date(s.EndTimeUtc!.Value), s.DurationSeconds!.Value.ToString(CultureInfo.InvariantCulture),
                (s.DurationSeconds.Value / 3600.0).ToString(CultureInfo.InvariantCulture), s.Notes, s.DeviceId.ToString(), s.Platform }.Select(Cell)));
        return string.Join("\r\n", rows) + "\r\n";
    }
}
public sealed class FileStore(string path)
{
    private byte[]? snapshot;
    public string PathName => path;
    public TrackerState Load(bool requireExisting = false)
    {
        if (!File.Exists(path) && !requireExisting) { snapshot = null; return TrackerState.Empty(); }
        var bytes = File.ReadAllBytes(path);
        var state = PortableData.Decode(bytes);
        snapshot = bytes;
        return state;
    }
    public void Save(TrackerState state)
    {
        var current = File.Exists(path) ? File.ReadAllBytes(path) : null;
        if (!(current == null && snapshot == null) && (current == null || snapshot == null || !current.SequenceEqual(snapshot)))
            throw new IOException("The data file changed or was removed. Select its data folder again before saving.");
        var bytes = PortableData.Encode(state);
        WriteAtomically(path, bytes);
        snapshot = bytes;
    }
    public static void WriteAtomically(string path, byte[] bytes)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        var temporary = path + "." + Guid.NewGuid() + ".tmp";
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(bytes); stream.Flush(true); }
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}

public sealed class StorageLocation(string settingsPath, string defaultPath)
{
    private readonly string defaultDataPath = defaultPath;
    public string CurrentPath { get; private set; } = defaultPath;
    private string SheetsSettingsPath => settingsPath + ".sheets";
    public string Label => File.Exists(SheetsSettingsPath) ? "Google Sheets (online)" : "Local file: " + CurrentPath;
    public Tracker SelectSheets(SheetsStore store, TrackerState? copy = null)
    {
        var state = store.Load(false);
        if (state == null) { state = copy ?? TrackerState.Empty(); store.Save(state); }
        var tracker = new Tracker(state, store.Save, () => store.Load()!);
        FileStore.WriteAtomically(SheetsSettingsPath, JsonSerializer.SerializeToUtf8Bytes(store.Configuration));
        return tracker;
    }
    public Tracker Open()
    {
        if (File.Exists(SheetsSettingsPath)) {
            var config = JsonSerializer.Deserialize<SheetsConfiguration>(File.ReadAllText(SheetsSettingsPath)) ?? throw new InvalidDataException("Invalid Sheets settings.");
            var sheets = new SheetsStore(config);
            return new Tracker(sheets.Load()!, sheets.Save, () => sheets.Load()!);
        }

        var selected = File.Exists(settingsPath);
        var path = selected ? JsonSerializer.Deserialize<string>(File.ReadAllText(settingsPath)) ?? throw new InvalidDataException("Invalid location setting.") : defaultDataPath;
        if (selected) path = Path.Combine(Path.GetDirectoryName(path)!, "tick.json");
        var store = new FileStore(path);
        var tracker = new Tracker(store.Load(true), store.Save, () => store.Load(true));
        CurrentPath = path;
        return tracker;
    }
    public Tracker Select(string folder, TrackerState? copy = null)
    {
        var path = Path.Combine(folder, "tick.json");
        if (!File.Exists(path)) FileStore.WriteAtomically(path, PortableData.Encode(copy ?? TrackerState.Empty()));
        var store = new FileStore(path);
        var next = new Tracker(store.Load(true), store.Save, () => store.Load(true));
        FileStore.WriteAtomically(settingsPath, JsonSerializer.SerializeToUtf8Bytes(path));
        if (File.Exists(SheetsSettingsPath)) File.Delete(SheetsSettingsPath);
        CurrentPath = path;
        return next;
    }
}
