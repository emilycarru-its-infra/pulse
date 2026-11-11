using System.Runtime.InteropServices;

namespace PulseAgent.Core;

/// <summary>
/// Calls back as the computer goes to sleep and as it resumes. Uses the callback form of
/// PowerRegisterSuspendResumeNotification, which needs no window, so it works in the SYSTEM task.
/// Windows waits for the suspend callback to return, briefly, before sleeping.
/// </summary>
public sealed class PowerEvents : IDisposable
{
    private const uint DeviceNotifyCallback = 2;
    private const uint PbtApmSuspend = 0x4;
    private const uint PbtApmResumeSuspend = 0x7;
    private const uint PbtApmResumeAutomatic = 0x12;

    private readonly Callback callback;
    private readonly Action onSleep;
    private readonly Action onWake;
    private IntPtr handle;

    private PowerEvents(Action onSleep, Action onWake)
    {
        this.onSleep = onSleep;
        this.onWake = onWake;
        callback = Notify;
    }

    /// <summary>Registers for sleep and resume, or returns null when Windows refuses.</summary>
    public static PowerEvents? Register(Action onSleep, Action onWake)
    {
        var events = new PowerEvents(onSleep, onWake);
        var parameters = new SubscribeParameters { Callback = events.callback, Context = IntPtr.Zero };
        var error = PowerRegisterSuspendResumeNotification(DeviceNotifyCallback, ref parameters, out events.handle);
        if (error == 0) return events;
        AgentLog.Warn($"Could not register for sleep and wake notifications (error {error}); sleep will not be reported");
        return null;
    }

    /// <summary>The event a power broadcast stands for: sleep, wake, or nothing.</summary>
    public static string? Kind(uint type) => type switch
    {
        PbtApmSuspend => "sleep",
        PbtApmResumeAutomatic => "wake",
        _ => null,
    };

    private uint Notify(IntPtr context, uint type, IntPtr setting)
    {
        // A resume by a person sends PBT_APMRESUMESUSPEND after PBT_APMRESUMEAUTOMATIC; one wake is enough.
        try
        {
            switch (Kind(type))
            {
                case "sleep": onSleep(); break;
                case "wake": onWake(); break;
            }
        }
        catch
        {
        }
        return 0;
    }

    public void Dispose()
    {
        if (handle == IntPtr.Zero) return;
        PowerUnregisterSuspendResumeNotification(handle);
        handle = IntPtr.Zero;
    }

    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate uint Callback(IntPtr context, uint type, IntPtr setting);

    [StructLayout(LayoutKind.Sequential)]
    private struct SubscribeParameters
    {
        public Callback Callback;
        public IntPtr Context;
    }

    [DllImport("powrprof.dll")]
    private static extern uint PowerRegisterSuspendResumeNotification(uint flags, ref SubscribeParameters recipient, out IntPtr handle);

    [DllImport("powrprof.dll")]
    private static extern uint PowerUnregisterSuspendResumeNotification(IntPtr handle);
}
