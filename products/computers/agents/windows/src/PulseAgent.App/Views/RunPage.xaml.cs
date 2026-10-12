using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using PulseAgent.App.ViewModels;

namespace PulseAgent.App.Views;

public sealed partial class RunPage : Page
{
    public RunViewModel ViewModel { get; }

    public RunPage()
    {
        InitializeComponent();
        ViewModel = new RunViewModel(DispatcherQueue);
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        ViewModel.Start();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        base.OnNavigatedFrom(e);
        ViewModel.Stop();
    }

    private void SendNow_Click(object sender, RoutedEventArgs e) => ViewModel.SendNow();
}
