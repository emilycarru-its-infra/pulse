using PulseAgent.Core;

// The command-line agent. The scheduled task runs it with no arguments as SYSTEM at boot.
//   <cli>                 run the agent loop
//   <cli> status [--json] show what the agent sees and the event it would send
//   <cli> send [--type T] send one event now (heartbeat by default)
//   <cli> --version

var command = args.FirstOrDefault()?.ToLowerInvariant() ?? "run";
var cli = Identity.CliName;

switch (command)
{
    case "run":
    {
        AgentLog.Echo = Environment.UserInteractive;
        using var stop = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) => { e.Cancel = true; stop.Cancel(); };
        await new Agent().RunAsync(stop.Token);
        return 0;
    }
    case "status":
        return Status(args.Contains("--json"));
    case "send":
    {
        var type = Option("--type") ?? "heartbeat";
        if (!PulseEvent.Types.Contains(type))
        {
            Console.Error.WriteLine($"{cli}: --type must be one of {string.Join(", ", PulseEvent.Types)}");
            return 2;
        }
        AgentLog.Echo = true;
        var result = await new Agent().SendOnceAsync(type, CancellationToken.None);
        return result.Ok ? 0 : 1;
    }
    case "--version" or "version":
        Console.WriteLine(Identity.Version);
        return 0;
    case "--help" or "-h" or "help":
        Console.WriteLine($"{Identity.GuiName} agent {Identity.VersionDisplay}");
        Console.WriteLine($"usage: {cli} [run | status [--json] | send [--type heartbeat|login|logout|lock|unlock|boot|shutdown] | --version]");
        return 0;
    default:
        Console.Error.WriteLine($"{cli}: unknown command '{command}'; try {cli} --help");
        return 2;
}

string? Option(string name)
{
    var i = Array.IndexOf(args, name);
    return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
}

static int Status(bool json)
{
    var settings = SettingsStore.Load();
    var managed = SettingsStore.ManagedKeys();
    var session = SessionProbe.Read();
    var pulse = PulseEvent.Create("heartbeat", session, Device.Hostname, Device.Serial, DateTimeOffset.UtcNow, Identity.Version);
    if (json)
    {
        Console.WriteLine(pulse.ToJson(indented: true));
        return 0;
    }
    var cert = settings.UseDeviceCertificate ? DeviceCertificate.Find() : null;
    string Tag(string key) => managed.Contains(key) ? " (managed)" : "";
    Console.WriteLine($"{Identity.GuiName} {Identity.VersionDisplay}");
    Console.WriteLine();
    Console.WriteLine($"Device       {pulse.Device.Hostname}, serial {pulse.Device.Serial}");
    Console.WriteLine($"Certificate  {(cert is null ? (settings.UseDeviceCertificate ? "none found" : "off") : $"{DeviceCertificate.DeviceId(cert)}, expires {cert.NotAfter:yyyy-MM-dd}")}{Tag(SettingsStore.UseDeviceCertificate)}");
    Console.WriteLine($"Ingest       {settings.IngestUrl ?? "(not set)"}{Tag(SettingsStore.IngestUrl)}");
    Console.WriteLine($"Shared key   {(string.IsNullOrWhiteSpace(settings.IngestKey) ? "not set" : "set")}{Tag(SettingsStore.IngestKey)}");
    Console.WriteLine($"Intervals    check {settings.CheckIntervalSeconds}s{Tag(SettingsStore.CheckIntervalSeconds)}, heartbeat {settings.HeartbeatIntervalSeconds}s{Tag(SettingsStore.HeartbeatIntervalSeconds)}");
    Console.WriteLine();
    Console.WriteLine($"Signed in    {(session.Active ? $"yes, session {session.SessionId}" : "no")}");
    Console.WriteLine($"Locked       {(session.Locked ? "yes" : "no")}");
    Console.WriteLine($"Idle         {session.IdleSeconds}s (from {session.IdleSource})");
    Console.WriteLine($"Seat         {Transitions.SeatState(session)}");
    if (AgentStatus.Read() is { } status)
        Console.WriteLine($"Last send    {status.LastSentType} at {status.LastSentAt}: {status.LastResult}");
    Console.WriteLine();
    Console.WriteLine(pulse.ToJson(indented: true));
    return 0;
}
