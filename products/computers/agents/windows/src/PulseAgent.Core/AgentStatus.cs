using System.Text.Json;
using System.Text.Json.Serialization;

namespace PulseAgent.Core;

/// <summary>What the agent last saw and sent, written to status.json after every check so the
/// GUI's Run tab can show it without elevation.</summary>
public sealed record AgentStatus
{
    [JsonPropertyName("updatedAt")] public string UpdatedAt { get; init; } = "";
    [JsonPropertyName("agentVersion")] public string AgentVersion { get; init; } = "";
    [JsonPropertyName("hostname")] public string Hostname { get; init; } = "";
    [JsonPropertyName("active")] public bool Active { get; init; }
    [JsonPropertyName("locked")] public bool Locked { get; init; }
    [JsonPropertyName("idleSeconds")] public int IdleSeconds { get; init; }
    [JsonPropertyName("idleSource")] public string IdleSource { get; init; } = "none";
    [JsonPropertyName("seatState")] public string SeatState { get; init; } = "";
    [JsonPropertyName("certificate")] public string? Certificate { get; init; }
    [JsonPropertyName("certificateExpires")] public string? CertificateExpires { get; init; }
    [JsonPropertyName("lastSentAt")] public string? LastSentAt { get; init; }
    [JsonPropertyName("lastSentType")] public string? LastSentType { get; init; }
    [JsonPropertyName("lastResult")] public string? LastResult { get; init; }
    [JsonPropertyName("lastOk")] public bool LastOk { get; init; }

    public static AgentStatus? Read()
    {
        try
        {
            using var stream = new FileStream(Identity.StatusFile, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            return JsonSerializer.Deserialize<AgentStatus>(stream);
        }
        catch
        {
            return null;
        }
    }

    public void Write()
    {
        try
        {
            Directory.CreateDirectory(Identity.DataDirectory);
            var temp = Identity.StatusFile + ".tmp";
            File.WriteAllText(temp, JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(temp, Identity.StatusFile, overwrite: true);
        }
        catch (Exception ex)
        {
            AgentLog.Debug($"status.json not written: {ex.Message}");
        }
    }
}
