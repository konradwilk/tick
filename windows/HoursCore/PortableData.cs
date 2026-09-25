using System.Text.Json;

namespace HoursCore;

/// <summary>Reads shared version 1 files and the earlier unversioned mobile files.</summary>
public static class PortableData
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    public static byte[] Encode(TrackerState state)
    {
        // Validate before FileStore replaces any saved history, and normalize dates to UTC.
        var validated = Decode(JsonSerializer.SerializeToUtf8Bytes(state, Options));
        return JsonSerializer.SerializeToUtf8Bytes(validated, Options);
    }

    public static TrackerState Decode(byte[] bytes)
    {
        try
        {
            using var document = JsonDocument.Parse(bytes);
            var root = document.RootElement;
            var legacy = !root.TryGetProperty("schemaVersion", out var version);
            if (!legacy && version.GetInt32() != 1)
                throw new InvalidDataException("Unsupported data file version.");

            var nonprofits = root.GetProperty("nonprofits").EnumerateArray()
                .Select(n => new Nonprofit(Id(n, "id"), Text(n, "name"))).ToArray();
            var ids = new HashSet<Guid>();
            foreach (var nonprofit in nonprofits)
                if (!ids.Add(nonprofit.Id))
                    throw new InvalidDataException("Duplicate nonprofit identity.");

            var sessions = new List<Session>();
            var sessionIds = new HashSet<Guid>();
            var activeCount = 0;
            foreach (var item in root.GetProperty("sessions").EnumerateArray())
            {
                var end = Optional(item, "endTimeUtc");
                var duration = Optional(item, "durationSeconds");
                var session = new Session(Id(item, "sessionId"), Id(item, "nonprofitId"),
                    Text(item, "nonprofitName"), Date(item.GetProperty("startTimeUtc"), legacy),
                    end is null ? null : Date(end.Value, legacy),
                    duration is null ? null : duration.Value.GetInt64(),
                    Text(item, "notes"), Id(item, "deviceId"),
                    legacy && !item.TryGetProperty("platform", out _) ? "android" : Text(item, "platform"),
                    Date(item.GetProperty("updatedAtUtc"), legacy),
                    legacy && !item.TryGetProperty("syncState", out _) ? "pending" : Text(item, "syncState"));

                if (!sessionIds.Add(session.SessionId) || !ids.Contains(session.NonprofitId))
                    throw new InvalidDataException("Invalid saved session identity.");
                if (session.Platform is not ("android" or "ios" or "macos" or "windows" or "linux") ||
                    session.SyncState is not ("pending" or "synced" or "failed"))
                    throw new InvalidDataException("Invalid session platform or sync state.");
                if (session.EndTimeUtc is null)
                {
                    if (++activeCount > 1 || session.DurationSeconds is not null)
                        throw new InvalidDataException("Invalid active session.");
                }
                else
                {
                    var seconds = (session.EndTimeUtc.Value - session.StartTimeUtc).TotalSeconds;
                    if (seconds < 0 || session.DurationSeconds is not long saved || saved < 0 ||
                        Math.Abs(saved - seconds) >= 1.01)
                        throw new InvalidDataException("Invalid saved duration.");
                }
                sessions.Add(session);
            }
            return new TrackerState(Id(root, "deviceId"), nonprofits, sessions.ToArray());
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or
            KeyNotFoundException or FormatException or OverflowException or ArgumentException)
        {
            throw new InvalidDataException("Invalid saved data file.", error);
        }
    }

    private static string Text(JsonElement item, string key) =>
        item.GetProperty(key).GetString() ?? throw new InvalidDataException($"Missing {key}.");

    private static Guid Id(JsonElement item, string key) => Guid.Parse(Text(item, key));

    private static JsonElement? Optional(JsonElement item, string key) =>
        item.TryGetProperty(key, out var value) && value.ValueKind != JsonValueKind.Null ? value : null;

    private static DateTimeOffset Date(JsonElement value, bool legacy)
    {
        // Swift's original JSONEncoder represents Date as seconds since 2001-01-01.
        if (legacy && value.ValueKind == JsonValueKind.Number)
            return new DateTimeOffset(2001, 1, 1, 0, 0, 0, TimeSpan.Zero).AddSeconds(value.GetDouble());
        var text = value.GetString() ?? throw new InvalidDataException("Missing timestamp.");
        if (!(text.EndsWith('Z') || (text.Length >= 6 && text[^3] == ':' && text[^6] is '+' or '-')))
            throw new InvalidDataException("Saved timestamp must include a timezone.");
        return value.GetDateTimeOffset().ToUniversalTime();
    }
}
