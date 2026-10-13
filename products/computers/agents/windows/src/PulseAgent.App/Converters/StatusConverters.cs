using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Media;
using PulseAgent.Core;

namespace PulseAgent.App.Converters;

/// <summary>A task's state dot: the system success colour, the critical colour only for a failed
/// run, and a neutral gray for disabled, not installed or unknown.</summary>
public sealed class StatusToneToBrushConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language) =>
        Application.Current.Resources[value switch
        {
            StatusTone.Healthy => "SystemFillColorSuccessBrush",
            StatusTone.Failed => "SystemFillColorCriticalBrush",
            _ => "ControlStrongFillColorDefaultBrush",
        }];

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}

/// <summary>Cascadia Mono, falling back to Consolas, for paths and command lines; the theme's text
/// font otherwise.</summary>
public sealed class MonospaceConverter : IValueConverter
{
    public static readonly FontFamily Monospace = new("Cascadia Mono, Consolas");

    public object Convert(object value, Type targetType, object parameter, string language) =>
        value is true ? Monospace : Application.Current.Resources["ContentControlThemeFontFamily"];

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}
