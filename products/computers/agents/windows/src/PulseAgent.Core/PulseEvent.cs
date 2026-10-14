using System.Text.Json;
using System.Text.Json.Serialization;

namespace PulseAgent.Core;

/// <summary>One event, exactly as core/contract/event.schema.json describes it. It carries no
/// username or any other personal data.</summary>
public sealed record PulseEvent(
    [property: JsonPropertyName("v")] int V,
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("ts")] string Ts,
    [property: JsonPropertyName("device")] PulseEvent.DeviceInfo Device,
    [property: JsonPropertyName("session")] PulseEvent.SessionInfo Session,
    [property: JsonPropertyName("agent")] PulseEvent.AgentInfo Agent)
{
    public static readonly string[] Types = ["heartbeat", "login", "logout", "lock", "unlock", "boot", "shutdown"];

    public sealed record DeviceInfo(
        [property: JsonPropertyName("hostname")] string Hostname,
        [property: JsonPropertyName("serial")] string Serial);

    public sealed record SessionInfo(
        [property: JsonPropertyName("active")] bool Active,
        [property: JsonPropertyName("locked")] bool Locked,
        [property: JsonPropertyName("idleSeconds")] int IdleSeconds);

    public sealed record AgentInfo(
        [property: JsonPropertyName("version")] string Version,
        [property: JsonPropertyName("platform")] string Platform);

    public static PulseEvent Create(string type, SessionSnapshot session, string hostname, string serial,
        DateTimeOffset at, string version)
    {
        if (!Types.Contains(type)) throw new ArgumentException($"Unknown event type: {type}", nameof(type));
        return new PulseEvent(1, type, at.UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            new DeviceInfo(hostname, serial),
            new SessionInfo(session.Active, session.Active && session.Locked, Math.Max(0, session.IdleSeconds)),
            new AgentInfo(version.Length > 32 ? version[..32] : version, "windows"));
    }

    public string ToJson(bool indented = false) =>
        JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = indented });
}

/// <summary>Which events a change in the session means.</summary>
public static class Transitions
{
    public static IReadOnlyList<string> Between(SessionSnapshot before, SessionSnapshot now)
    {
        var events = new List<string>();
        if (before.Active && now.Active && before.SessionId != now.SessionId)
        {
            events.Add("logout");
            events.Add("login");
            if (now.Locked) events.Add("lock");
        }
        else if (!before.Active && now.Active)
        {
            events.Add("login");
            if (now.Locked) events.Add("lock");
        }
        else if (before.Active && !now.Active)
        {
            events.Add("logout");
        }
        else if (now.Active && before.Locked != now.Locked)
        {
            events.Add(now.Locked ? "lock" : "unlock");
        }
        return events;
    }

    /// <summary>What the site will show for this reading, mirroring pulse_core.state: free when
    /// nobody is signed in or idle at least 15 minutes, including locked sessions.</summary>
    public static string SeatState(SessionSnapshot s) =>
        !s.Active || s.IdleSeconds >= 15 * 60 ? "available" : "in_use";
}
