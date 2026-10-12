using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;

namespace PulseAgent.Core;

/// <summary>
/// The agent loop. Every check interval it reads the session; a sign-in, sign-out, lock or unlock
/// is sent at once, and otherwise a heartbeat goes every heartbeat interval. A failed send is
/// dropped: the next heartbeat brings the seat up to date, and the server marks a silent seat off
/// after five minutes. The GUI's Send now button signals a named event that wakes the loop.
/// </summary>
public sealed class Agent
{
    private AgentSettings settings = SettingsStore.Load();
    private IngestClient? client;
    private SessionSnapshot last = SessionSnapshot.Nobody;
    private DateTimeOffset lastSentAt = DateTimeOffset.MinValue;
    private string? lastSentType;
    private SendResult? lastResult;

    public async Task RunAsync(CancellationToken cancel)
    {
        AgentLog.Prune();
        Configure(settings);
        AgentLog.Info($"{Identity.CliName} {Identity.Version} started on {Device.Hostname}");

        last = SessionProbe.Read();
        // A boot event when the computer has just started, a heartbeat when only the agent did.
        await SendAsync(Environment.TickCount64 < 10 * 60 * 1000 ? "boot" : "heartbeat", last, cancel);
        WriteStatus();

        using var shutdown = PosixSignalRegistration.Create(PosixSignal.SIGTERM, _ => SendShutdown());
        using var sendNow = OpenSendNowEvent();
        var handles = sendNow is null ? new[] { cancel.WaitHandle } : new[] { cancel.WaitHandle, sendNow };

        while (!cancel.IsCancellationRequested)
        {
            var woke = WaitHandle.WaitAny(handles, TimeSpan.FromSeconds(settings.CheckIntervalSeconds));
            if (cancel.IsCancellationRequested) break;
            // Any signed-in user may signal Send now, so it is honoured at most every 10 seconds.
            var forced = woke == 1 && DateTimeOffset.UtcNow - lastSentAt >= TimeSpan.FromSeconds(10);
            if (forced) AgentLog.Info("Send now requested");

            var fresh = SettingsStore.Load();
            if (fresh != settings) Configure(fresh);

            var now = SessionProbe.Read();
            var events = Transitions.Between(last, now);
            foreach (var type in events) await SendAsync(type, now, cancel);
            if (events.Count == 0 && (forced || DateTimeOffset.UtcNow - lastSentAt >= TimeSpan.FromSeconds(settings.HeartbeatIntervalSeconds)))
                await SendAsync("heartbeat", now, cancel);
            last = now;
            WriteStatus();
        }
        AgentLog.Info("Stopped");
    }

    /// <summary>Sends one event of <paramref name="type"/> for the session as it is now.</summary>
    public async Task<SendResult> SendOnceAsync(string type, CancellationToken cancel)
    {
        Configure(settings);
        last = SessionProbe.Read();
        var result = await SendAsync(type, last, cancel);
        WriteStatus();
        return result;
    }

    private void Configure(AgentSettings next)
    {
        settings = next;
        AgentLog.Verbose = next.VerboseLogging;
        var cert = next.UseDeviceCertificate ? DeviceCertificate.Find() : null;
        client?.Dispose();
        client = new IngestClient(next, cert);
        AgentLog.Info($"Ingest {(next.IngestUrl ?? "(not set)")}; check {next.CheckIntervalSeconds}s, heartbeat {next.HeartbeatIntervalSeconds}s; "
            + (cert is null ? "no device certificate" : $"device certificate {DeviceCertificate.DeviceId(cert)}")
            + (string.IsNullOrWhiteSpace(next.IngestKey) ? "" : "; shared key set"));
    }

    private async Task<SendResult> SendAsync(string type, SessionSnapshot session, CancellationToken cancel)
    {
        var pulse = PulseEvent.Create(type, session, Device.Hostname, Device.Serial, DateTimeOffset.UtcNow, Identity.Version);
        var result = await client!.SendAsync(pulse, cancel);
        lastSentAt = DateTimeOffset.UtcNow;
        lastSentType = type;
        lastResult = result;
        var line = $"{type}: active={session.Active} locked={session.Locked} idle={session.IdleSeconds}s ({session.IdleSource}) -> {result}";
        if (result.Ok) AgentLog.Info(line); else AgentLog.Warn(line);
        AgentLog.Debug(pulse.ToJson());
        return result;
    }

    private void SendShutdown()
    {
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            SendAsync("shutdown", last, timeout.Token).GetAwaiter().GetResult();
        }
        catch
        {
        }
    }

    private void WriteStatus()
    {
        var cert = client?.Certificate;
        new AgentStatus
        {
            UpdatedAt = DateTimeOffset.UtcNow.UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            AgentVersion = Identity.Version,
            Hostname = Device.Hostname,
            Active = last.Active,
            Locked = last.Locked,
            IdleSeconds = last.IdleSeconds,
            IdleSource = last.IdleSource,
            SeatState = Transitions.SeatState(last),
            Certificate = cert is null ? null : DeviceCertificate.DeviceId(cert),
            CertificateExpires = cert?.NotAfter.ToUniversalTime().ToString("yyyy-MM-dd"),
            LastSentAt = lastSentAt == DateTimeOffset.MinValue ? null : lastSentAt.UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            LastSentType = lastSentType,
            LastResult = lastResult?.ToString(),
            LastOk = lastResult?.Ok ?? false,
        }.Write();
    }

    /// <summary>The Send now event, which any signed-in user may signal and only the agent waits on.</summary>
    private static EventWaitHandle? OpenSendNowEvent()
    {
        try
        {
            var security = new EventWaitHandleSecurity();
            security.AddAccessRule(new EventWaitHandleAccessRule(
                new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), EventWaitHandleRights.FullControl, AccessControlType.Allow));
            security.AddAccessRule(new EventWaitHandleAccessRule(
                new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null), EventWaitHandleRights.FullControl, AccessControlType.Allow));
            security.AddAccessRule(new EventWaitHandleAccessRule(
                new SecurityIdentifier(WellKnownSidType.AuthenticatedUserSid, null),
                EventWaitHandleRights.Modify | EventWaitHandleRights.Synchronize, AccessControlType.Allow));
            return EventWaitHandleAcl.Create(false, EventResetMode.AutoReset, Identity.SendNowEventName, out _, security);
        }
        catch (Exception ex)
        {
            AgentLog.Warn($"Send now is unavailable: {ex.Message}");
            return null;
        }
    }

    /// <summary>Asks the running agent to send a heartbeat now. False when no agent is running.</summary>
    public static bool RequestSendNow()
    {
        try
        {
            using var handle = EventWaitHandle.OpenExisting(Identity.SendNowEventName);
            return handle.Set();
        }
        catch
        {
            return false;
        }
    }
}
