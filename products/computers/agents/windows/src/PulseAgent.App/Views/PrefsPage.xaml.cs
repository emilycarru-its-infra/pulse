using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Navigation;
using PulseAgent.App.ViewModels;
using PulseAgent.Core;

namespace PulseAgent.App.Views;

public sealed partial class PrefsPage : Page
{
    public PrefsViewModel ViewModel { get; } = new();

    public PrefsPage()
    {
        InitializeComponent();
        AppName.Text = Identity.GuiName;
        VersionText.Text = Identity.VersionDisplay;
        var icon = Path.Combine(AppContext.BaseDirectory, "Assets", $"{Identity.IconName}.png");
        if (File.Exists(icon)) AppIcon.Source = new BitmapImage(new Uri(icon));
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        ViewModel.Load();
    }
}
