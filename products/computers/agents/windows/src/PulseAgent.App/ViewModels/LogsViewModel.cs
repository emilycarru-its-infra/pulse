using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using PulseAgent.Core;

namespace PulseAgent.App.ViewModels;

/// <summary>The Logs tab: the agent's daily log files, newest first, with a filter and a live tail.</summary>
public partial class LogsViewModel : ObservableObject
{
    private long loadedLength = -1;

    public ObservableCollection<LogFile> LogFiles { get; } = [];

    [ObservableProperty] private LogFile? _selectedLog;
    [ObservableProperty] private string _logContent = "";
    [ObservableProperty] private string _filterText = "";

    public record LogFile(string Path, DateTime Day, long SizeBytes)
    {
        public string DisplayDate => Day.Date == DateTime.Today ? "Today" : Day.ToString("ddd d MMM yyyy");
        public string DisplaySize => SizeBytes switch
        {
            < 1024 => $"{SizeBytes} B",
            < 1024 * 1024 => $"{SizeBytes / 1024.0:0.#} KB",
            _ => $"{SizeBytes / (1024.0 * 1024):0.#} MB",
        };
    }

    public record LogLine(string Text, LogLineColor Color);

    public enum LogLineColor { Default, Error, Warning, Debug }

    public IEnumerable<LogLine> FilteredLines =>
        LogContent.Split('\n')
            .Select(l => l.TrimEnd('\r'))
            .Where(l => l.Length > 0 && (FilterText.Length == 0 || l.Contains(FilterText, StringComparison.OrdinalIgnoreCase)))
            .Select(l => new LogLine(l, ColorFor(l)));

    public void Refresh()
    {
        LogFiles.Clear();
        if (!Directory.Exists(Identity.LogDirectory)) return;
        var prefix = $"{Identity.CliName}-";
        foreach (var path in Directory.GetFiles(Identity.LogDirectory, $"{prefix}*.log"))
        {
            var stamp = System.IO.Path.GetFileNameWithoutExtension(path)[prefix.Length..];
            if (DateTime.TryParseExact(stamp, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var day))
                LogFiles.Add(new LogFile(path, day, new FileInfo(path).Length));
        }
        var sorted = LogFiles.OrderByDescending(f => f.Day).ToList();
        LogFiles.Clear();
        foreach (var f in sorted) LogFiles.Add(f);
        SelectedLog = LogFiles.FirstOrDefault(f => f.Path == SelectedLog?.Path) ?? LogFiles.FirstOrDefault();
        Load(force: true);
    }

    /// <summary>Re-reads the selected log when it has grown.</summary>
    public void ReloadIfChanged() => Load(force: false);

    partial void OnSelectedLogChanged(LogFile? value) => Load(force: true);
    partial void OnLogContentChanged(string value) => OnPropertyChanged(nameof(FilteredLines));
    partial void OnFilterTextChanged(string value) => OnPropertyChanged(nameof(FilteredLines));

    private void Load(bool force)
    {
        if (SelectedLog is null)
        {
            LogContent = "";
            return;
        }
        try
        {
            var length = new FileInfo(SelectedLog.Path).Length;
            if (!force && length == loadedLength) return;
            using var stream = new FileStream(SelectedLog.Path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            using var reader = new StreamReader(stream);
            LogContent = reader.ReadToEnd();
            loadedLength = length;
        }
        catch
        {
            LogContent = "Unable to read this log.";
        }
    }

    public void OpenInEditor()
    {
        if (SelectedLog is not null) Process.Start(new ProcessStartInfo(SelectedLog.Path) { UseShellExecute = true });
    }

    public void OpenFolder()
    {
        if (Directory.Exists(Identity.LogDirectory)) Process.Start(new ProcessStartInfo(Identity.LogDirectory) { UseShellExecute = true });
    }

    // AgentLog writes "[timestamp] LEVEL message" with a padded, unbracketed level.
    private static LogLineColor ColorFor(string line)
    {
        var close = line.IndexOf("] ", StringComparison.Ordinal);
        var rest = close < 0 ? "" : line[(close + 2)..];
        return rest.StartsWith("ERROR") ? LogLineColor.Error
            : rest.StartsWith("WARN") ? LogLineColor.Warning
            : rest.StartsWith("DEBUG") ? LogLineColor.Debug
            : LogLineColor.Default;
    }
}
