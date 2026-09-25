using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace HoursCore;
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
    public TrackerState State { get; private set; }
    private readonly Action<TrackerState> save;
    public Tracker(TrackerState initial, Action<TrackerState> save) { State = initial; this.save = save; }
    private void Commit(TrackerState next) { save(next); State = next; }
    public Guid AddNonprofit(string input)
    {
        var name = input.Trim();
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
        var session = new Session(Guid.NewGuid(), id, nonprofit.Name, date, null, null, notes, State.DeviceId, "windows", date);
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
    public string Csv()
    {
        static string Cell(string value)
        {
            if (value.TrimStart().FirstOrDefault() is '=' or '+' or '-' or '@') value = "'" + value;
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }
        static string Date(DateTimeOffset value) => value.UtcDateTime.ToString("O", CultureInfo.InvariantCulture);
        var rows = new List<string> { "sessionId,nonprofitId,nonprofitName,startTimeUtc,endTimeUtc,durationSeconds,hours,notes,deviceId,platform,updatedAtUtc" };
        foreach (var s in State.Sessions.Where(s => s.EndTimeUtc != null))
            rows.Add(string.Join(",", new[] { s.SessionId.ToString(), s.NonprofitId.ToString(), s.NonprofitName,
                Date(s.StartTimeUtc), Date(s.EndTimeUtc!.Value), s.DurationSeconds!.Value.ToString(CultureInfo.InvariantCulture),
                (s.DurationSeconds.Value / 3600.0).ToString(CultureInfo.InvariantCulture), s.Notes, s.DeviceId.ToString(), s.Platform, Date(s.UpdatedAtUtc) }.Select(Cell)));
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
        var store = new FileStore(path);
        var tracker = new Tracker(store.Load(selected), store.Save);
        CurrentPath = path;
        return tracker;
    }
    public Tracker Select(string folder, TrackerState? copy = null)
    {
        var path = Path.Combine(folder, "nonprofit-hours.json");
        if (!File.Exists(path) && copy != null) FileStore.WriteAtomically(path, PortableData.Encode(copy));
        var store = new FileStore(path);
        var next = new Tracker(store.Load(true), store.Save);
        FileStore.WriteAtomically(settingsPath, JsonSerializer.SerializeToUtf8Bytes(path));
        CurrentPath = path;
        return next;
    }
}
