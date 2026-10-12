using Microsoft.UI.Xaml;
using PulseAgent.Core;

namespace PulseAgent.App;

public partial class App : Application
{
    private static readonly string CrashLog = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), Identity.ProductKey, "startup-crash.log");

    private Window? window;

    public App()
    {
        UnhandledException += (_, e) =>
        {
            e.Handled = true;
            Log($"UnhandledException: {e.Exception}");
        };
        InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            window = new MainWindow();
            window.Activate();
        }
        catch (Exception ex)
        {
            Log($"OnLaunched: {ex}");
        }
    }

    private static void Log(string message)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(CrashLog)!);
            File.WriteAllText(CrashLog, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}]\n{message}\n");
        }
        catch
        {
        }
    }
}
