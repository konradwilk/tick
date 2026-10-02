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
public record Session(Guid SessionId, Guid NonprofitId, string NonprofitName,
    DateTimeOffset StartTimeUtc, DateTimeOffset? EndTimeUtc, long? DurationSeconds,
    string Notes, Guid DeviceId, string Platform, DateTimeOffset UpdatedAtUtc, string SyncState = "pending");
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
    public Tracker(TrackerState initial, Action<TrackerState> save) { State = initial; this.save = save; }
    private void Commit(TrackerState next) { save(next); State = next; }
    public Guid AddNonprofit(string input)
    {
        var name = CapitalizeEntries(input.Trim());
        if (name.Length == 0 || State.Nonprofits.Any(n => n.Name.Equals(name, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException("Enter a unique nonprofit name.");
        var nonprofit = new Nonprofit(Guid.NewGuid(), name);
        Commit(State with { Nonprofits = [..State.Nonprofits, nonprofit] });
        return nonprofit.Id;
    }
    public void Start(Guid id, string notes = "", DateTimeOffset? now = null)
    {
        if (State.Active != null) throw new InvalidOperationException("Stop the current session first.");
        var nonprofit = State.Nonprofits.FirstOrDefault(n => n.Id == id) ?? throw new InvalidOperationException("Select a nonprofit.");
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
    public void AddSession(Guid id, string notes, DateTimeOffset start, DateTimeOffset end, DateTimeOffset? now = null)
    {
        var nonprofit = State.Nonprofits.FirstOrDefault(n => n.Id == id) ?? throw new InvalidOperationException("Select a nonprofit.");
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
        return string.Join("\n\n", ExportSessions(range, zone).GroupBy(s => s.NonprofitId).Select(group =>
            $"{group.First().NonprofitName} {Duration(group.Sum(s => s.DurationSeconds ?? 0))}:\n" +
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
        var rows = new List<string> { "nonprofitName,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform" };
        foreach (var s in ExportSessions(range, zone))
            rows.Add(string.Join(",", new[] { s.NonprofitName,
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
    public string CurrentPath { get; private set; } = defaultPath;
    public Tracker Open()
    {
        var selected = File.Exists(settingsPath);
        var path = selected ? JsonSerializer.Deserialize<string>(File.ReadAllText(settingsPath)) ?? throw new InvalidDataException("Invalid location setting.") : defaultPath;
        if (selected) path = Path.Combine(Path.GetDirectoryName(path)!, "tick.json");
        var store = new FileStore(path);
        var tracker = new Tracker(store.Load(selected), store.Save);
        CurrentPath = path;
        return tracker;
    }
    public Tracker Select(string folder, TrackerState? copy = null)
    {
        var path = Path.Combine(folder, "tick.json");
        if (!File.Exists(path) && copy != null) FileStore.WriteAtomically(path, PortableData.Encode(copy));
        var store = new FileStore(path);
        var next = new Tracker(store.Load(true), store.Save);
        FileStore.WriteAtomically(settingsPath, JsonSerializer.SerializeToUtf8Bytes(path));
        CurrentPath = path;
        return next;
    }
}
