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
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    public TrackerState Load() => File.Exists(path)
        ? JsonSerializer.Deserialize<TrackerState>(File.ReadAllText(path), Options) ?? throw new InvalidDataException("Saved hours are empty.")
        : TrackerState.Empty();
    public void Save(TrackerState state)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        var temporary = path + "." + Guid.NewGuid() + ".tmp";
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { JsonSerializer.Serialize(stream, state, Options); stream.Flush(true); }
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
