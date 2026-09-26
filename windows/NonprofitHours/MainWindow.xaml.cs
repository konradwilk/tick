using HoursCore;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
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
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1100, 800));
        ReportDate.Date = DateTimeOffset.Now;
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
                Toggle.IsEnabled = ExportButton.IsEnabled = CopyButton.IsEnabled = false;
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
        FirstRun.Visibility = state.Nonprofits.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        EmptyHistory.Visibility = state.Sessions.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        var selected = (Nonprofits.SelectedItem as Nonprofit)?.Id;
        Nonprofits.ItemsSource = state.Nonprofits;
        Nonprofits.SelectedItem = state.Nonprofits.FirstOrDefault(n => n.Id == selected);
        var active = state.Active != null;
        Nonprofits.IsEnabled = Notes.IsEnabled = NewName.IsEnabled = AddButton.IsEnabled = !active;
        Toggle.Content = active ? "Stop" : "Start";
        Toggle.Background = new SolidColorBrush(active ? Colors.Firebrick : Colors.ForestGreen);
        Total.Text = $"Completed: {state.Sessions.Sum(s => s.DurationSeconds ?? 0) / 3600.0:F2} hours";
        UpdateReport();
        History.ItemsSource = state.Sessions.Reverse().Select(s => new HistoryEntry(s.SessionId,
            $"{s.NonprofitName} — {s.StartTimeUtc.ToLocalTime():g}\n{(s.DurationSeconds is long seconds ? Elapsed(seconds) : "In progress")}\n{s.Notes}", s.EndTimeUtc != null)).ToArray();
        UpdateClock();
    }
    public record HistoryEntry(Guid SessionId, string Summary, bool CanEdit);
    private async void EditNotes(object sender, RoutedEventArgs args)
    {
        if (tracker == null || sender is not Button { Tag: Guid sessionId }) return;
        var session = tracker.State.Sessions.FirstOrDefault(s => s.SessionId == sessionId);
        if (session == null || session.EndTimeUtc == null) return;
        var editor = new TextBox
        {
            Header = "What did you work on?", Text = session.Notes,
            AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MinHeight = 120
        };
        var error = new TextBlock { TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Colors.Firebrick) };
        var content = new StackPanel { Spacing = 12 };
        content.Children.Add(new TextBlock { Text = $"{session.NonprofitName} — {session.StartTimeUtc.ToLocalTime():g}", TextWrapping = TextWrapping.Wrap });
        content.Children.Add(editor);
        content.Children.Add(error);
        var dialog = new ContentDialog
        {
            XamlRoot = Controls.XamlRoot, Title = "Edit session notes", Content = content,
            PrimaryButtonText = "Save", CloseButtonText = "Cancel"
        };
        dialog.PrimaryButtonClick += (_, eventArgs) =>
        {
            try { tracker.UpdateNotes(sessionId, editor.Text); ErrorText.Text = ""; Refresh(); }
            catch (Exception e) { eventArgs.Cancel = true; error.Text = "Could not save notes. " + e.Message; }
        };
        await dialog.ShowAsync();
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
            var range = SelectedRange();
            var snapshot = tracker!.Csv(range);
            var picker = new FileSavePicker { SuggestedFileName = $"nonprofit-hours-{((ExportPeriod)ReportPeriod.SelectedIndex).ToString().ToLowerInvariant()}-{range.Start:yyyy-MM-dd}" };
            picker.FileTypeChoices.Add("CSV", new List<string> { ".csv" });
            WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
            var file = await picker.PickSaveFileAsync();
            if (file != null) await Windows.Storage.FileIO.WriteTextAsync(file, snapshot);
            ErrorText.Text = "";
        }
        catch (Exception e) { ErrorText.Text = e.Message; }
    }
    private ExportRange SelectedRange() => ExportRange.For((ExportPeriod)ReportPeriod.SelectedIndex,
        DateOnly.FromDateTime((ReportDate.Date ?? DateTimeOffset.Now).DateTime));
    private void ReportChanged(object sender, SelectionChangedEventArgs args) => UpdateReport();
    private void NonprofitChanged(object sender, SelectionChangedEventArgs args)
    {
        if (Toggle != null) Toggle.IsEnabled = tracker?.State.Active != null || Nonprofits.SelectedItem != null;
    }
    private void ReportDateChanged(CalendarDatePicker sender, CalendarDatePickerDateChangedEventArgs args) => UpdateReport();
    private void UpdateReport()
    {
        if (ReportSummary == null || CopyButton == null || tracker == null) return;
        var range = SelectedRange();
        var count = tracker.ExportSessions(range).Length;
        ReportSummary.Text = $"{range.Start:yyyy-MM-dd} – {range.End.AddDays(-1):yyyy-MM-dd}: {count} completed sessions";
        ReportPreview.Text = count == 0 ? "No completed sessions in this period." : tracker.ClipboardText(range);
        ExportButton.IsEnabled = CopyButton.IsEnabled = count > 0;
        CopyStatus.Text = "";
    }
    private void CopyReport(object sender, RoutedEventArgs args)
    {
        try
        {
            var text = tracker!.ClipboardText(SelectedRange());
            if (text.Length == 0) return;
            var data = new Windows.ApplicationModel.DataTransfer.DataPackage();
            data.SetText(text);
            Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(data);
            Windows.ApplicationModel.DataTransfer.Clipboard.Flush();
            CopyStatus.Text = "Copied durations and notes.";
            ErrorText.Text = "";
        }
        catch (Exception e) { ErrorText.Text = "Could not copy. " + e.Message; }
    }
    private void ShowSettings(object sender, RoutedEventArgs args) => SettingsPanel.Visibility =
        SettingsPanel.Visibility == Visibility.Visible ? Visibility.Collapsed : Visibility.Visible;
    private void WorkspaceResized(object sender, SizeChangedEventArgs args)
    {
        if (ReportPanel == null) return;
        var narrow = args.NewSize.Width < 760;
        Grid.SetColumn(ReportPanel, narrow ? 0 : 1);
        Grid.SetRow(ReportPanel, narrow ? 1 : 0);
        ReportColumn.Width = narrow ? new GridLength(0) : new GridLength(1, GridUnitType.Star);
    }
    private void CaptureResized(object sender, SizeChangedEventArgs args)
    {
        if (Toggle == null) return;
        var narrow = args.NewSize.Width < 500;
        Grid.SetColumn(Toggle, narrow ? 0 : 1);
        Grid.SetRow(Toggle, narrow ? 1 : 0);
        Grid.SetColumnSpan(Toggle, narrow ? 2 : 1);
    }
}
