using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using Forms = System.Windows.Forms;

namespace Tick;

/// <summary>Owns the notification icon and its native resources on the UI thread.</summary>
internal sealed class TrayIcon : IDisposable
{
    private readonly Forms.ContextMenuStrip menu = new();
    private readonly Icon icon;
    private readonly Forms.NotifyIcon notification;

    public TrayIcon(Action open, Action quit)
    {
        icon = CreateClockIcon();
        menu.Items.Add("Open Time is Clearly Kept", null, (_, _) => open());
        menu.Items.Add(new Forms.ToolStripSeparator());
        menu.Items.Add("Quit", null, (_, _) => quit());
        notification = new Forms.NotifyIcon
        {
            Icon = icon,
            Text = "Time is Clearly Kept",
            ContextMenuStrip = menu,
            Visible = true
        };
        notification.MouseClick += (_, args) =>
        {
            if (args.Button == Forms.MouseButtons.Left) open();
        };
    }

    private static Icon CreateClockIcon()
    {
        using var bitmap = new Bitmap(32, 32);
        using var graphics = Graphics.FromImage(bitmap);
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
        graphics.Clear(Color.Transparent);
        using var background = new SolidBrush(Color.ForestGreen);
        using var hands = new Pen(Color.White, 2.5f) { StartCap = LineCap.Round, EndCap = LineCap.Round };
        graphics.FillEllipse(background, 1, 1, 30, 30);
        graphics.DrawEllipse(hands, 5, 5, 22, 22);
        graphics.DrawLines(hands, new Point[] { new(16, 9), new(16, 16), new(22, 19) });
        var handle = bitmap.GetHicon();
        try
        {
            using var borrowed = Icon.FromHandle(handle);
            return (Icon)borrowed.Clone();
        }
        finally { DestroyIcon(handle); }
    }

    public void Dispose()
    {
        notification.Visible = false;
        notification.Dispose();
        menu.Dispose();
        icon.Dispose();
    }

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DestroyIcon(IntPtr icon);
}
