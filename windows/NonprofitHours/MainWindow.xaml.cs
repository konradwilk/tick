using HoursCore;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.Storage.Pickers;
namespace NonprofitHours;
public sealed partial class MainWindow : Window
{
    private Tracker? tracker;
    private readonly StorageLocation location = new(
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "NonprofitHours", "location.json"),
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "NonprofitHours", "sessions.json"));
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(1) };
    public MainWindow()
    {
        InitializeComponent();
        timer.Tick += (_, _) => UpdateClock();
        timer.Start();
        Closed += (_, _) => timer.Stop();
        try
        {
            tracker = location.Open();
            Refresh();
            Nonprofits.SelectedItem = tracker.State.Nonprofits.FirstOrDefault(n => n.Id == tracker.State.Active?.NonprofitId) ?? tracker.State.Nonprofits.FirstOrDefault();
            Notes.Text = tracker.State.Active?.Notes ?? "";

        }
        catch (Exception e)
        {
            Nonprofits.IsEnabled = Notes.IsEnabled = NewName.IsEnabled = AddButton.IsEnabled =
                Toggle.IsEnabled = ExportButton.IsEnabled = false;
            ErrorText.Text = "Could not load saved hours. Your file was not changed. " + e.Message;
        }
    }
    private void Perform(Action action)
    {
        try { action(); ErrorText.Text = ""; Refresh(); }
        catch (Exception e) { ErrorText.Text = e.Message; }
    }
    private void AddNonprofit(object sender, RoutedEventArgs args) => Perform(() =>
    {
        var id = tracker!.AddNonprofit(NewName.Text);
        NewName.Text = "";
        Refresh();
        Nonprofits.SelectedItem = tracker.State.Nonprofits.First(n => n.Id == id);
    });
    private void ToggleTracking(object sender, RoutedEventArgs args) => Perform(() =>
    {
        if (tracker!.State.Active != null) { tracker.Stop(); Notes.Text = ""; }
        else if (Nonprofits.SelectedItem is Nonprofit nonprofit) tracker.Start(nonprofit.Id, Notes.Text);
        else throw new InvalidOperationException("Select a nonprofit first.");
    });
    private void Refresh()
    {
        Toggle.IsEnabled = true;
        DataLocation.Text = Path.GetDirectoryName(location.CurrentPath);
        var state = tracker!.State;
        var selected = (Nonprofits.SelectedItem as Nonprofit)?.Id;
        Nonprofits.ItemsSource = state.Nonprofits;
        Nonprofits.SelectedItem = state.Nonprofits.FirstOrDefault(n => n.Id == selected);
        var active = state.Active != null;
        Nonprofits.IsEnabled = Notes.IsEnabled = NewName.IsEnabled = AddButton.IsEnabled = !active;
        Toggle.Content = active ? "Stop" : "Start";
        Toggle.Background = new SolidColorBrush(active ? Colors.Firebrick : Colors.ForestGreen);
        Total.Text = $"Completed: {state.Sessions.Sum(s => s.DurationSeconds ?? 0) / 3600.0:F2} hours";
        ExportButton.IsEnabled = state.Sessions.Any(s => s.EndTimeUtc != null);
        History.ItemsSource = state.Sessions.Reverse().Select(s => $"{s.NonprofitName} — {s.StartTimeUtc.ToLocalTime():g}\n{(s.DurationSeconds is long seconds ? Elapsed(seconds) : "In progress")}\n{s.Notes}").ToArray();
        UpdateClock();
    }
    private static string Elapsed(long seconds) => $"{seconds / 3600:00}:{seconds % 3600 / 60:00}:{seconds % 60:00}";
    private void UpdateClock()
    {
        var active = tracker?.State.Active;
        Status.Text = active == null ? "Ready when you are" : $"{active.NonprofitName}: {Elapsed(Math.Max(0, (long)(DateTimeOffset.UtcNow - active.StartTimeUtc).TotalSeconds))}";
    }
    private async void ChooseDataLocation(object sender, RoutedEventArgs args)
    {
        try
        {
            var picker = new FolderPicker();
            picker.FileTypeFilter.Add("*");
            WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
            var folder = await picker.PickSingleFolderAsync();
            if (folder == null) return;
            if (string.IsNullOrEmpty(folder.Path)) throw new IOException("Choose a local or mounted cloud folder.");
            var next = location.Select(folder.Path, tracker?.State);
            tracker = next;
            Refresh();
            Nonprofits.SelectedItem = tracker.State.Nonprofits.FirstOrDefault(n => n.Id == tracker.State.Active?.NonprofitId) ?? tracker.State.Nonprofits.FirstOrDefault();
            Notes.Text = tracker.State.Active?.Notes ?? "";
            ErrorText.Text = "";
        }
        catch (Exception e) { ErrorText.Text = e.Message; }
    }
    private async void Export(object sender, RoutedEventArgs args)
    {
        try
        {
            var picker = new FileSavePicker { SuggestedFileName = "nonprofit-hours" };
            picker.FileTypeChoices.Add("CSV", new List<string> { ".csv" });
            WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
            var file = await picker.PickSaveFileAsync();
            if (file != null) await Windows.Storage.FileIO.WriteTextAsync(file, tracker!.Csv());
            ErrorText.Text = "";
        }
        catch (Exception e) { ErrorText.Text = e.Message; }
    }
}
