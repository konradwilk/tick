using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace HoursCore;
public sealed class GoogleAccount
{
    public const string ClientId = "1048312430782-hprvc7al4c9mvfkqgv9cujns0hilees7.apps.googleusercontent.com";
    public const string Scope = "https://www.googleapis.com/auth/drive.file";
    private const string Service = "org.timeisclearlykept.google";
    private static readonly HttpClient Client = new() { Timeout = TimeSpan.FromSeconds(30) };
    private string? token;
    private DateTimeOffset expires;
    private readonly object gate = new();
    private static string Base64(byte[] bytes) => Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    public string AccessToken()
    {
        lock (gate) {
            var refresh = Credentials.Read();
            if (token != null && expires > DateTimeOffset.UtcNow) return token;
            Exchange(new() { ["client_id"] = ClientId, ["refresh_token"] = refresh, ["grant_type"] = "refresh_token" });
            return token!;
        }
    }
    private JsonElement Exchange(Dictionary<string, string> fields)
    {
        if (!string.IsNullOrEmpty(GoogleDesktopClient.Secret)) fields["client_secret"] = GoogleDesktopClient.Secret;
        using var body = new FormUrlEncodedContent(fields);
        using var response = Client.PostAsync("https://oauth2.googleapis.com/token", body).GetAwaiter().GetResult();
        if (!response.IsSuccessStatusCode) throw new InvalidDataException("Google sign-in failed. Reconnect or check the app OAuth configuration.");
        using var document = JsonDocument.Parse(response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult());
        var result = document.RootElement.Clone();
        token = result.GetProperty("access_token").GetString() ?? throw new InvalidDataException("Google did not grant access.");
        if (result.TryGetProperty("scope", out var scope) && !scope.GetString()!.Split(' ').Contains(Scope)) throw new InvalidDataException("Google Sheets permission was not granted.");
        expires = DateTimeOffset.UtcNow.AddSeconds(result.GetProperty("expires_in").GetInt32() - 60);
        return result;
    }
    public async Task SignInAsync(CancellationToken cancellation = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromMinutes(3));
        var verifier = Base64(RandomNumberGenerator.GetBytes(64));
        var challenge = Base64(SHA256.HashData(Encoding.ASCII.GetBytes(verifier)));
        var state = Base64(RandomNumberGenerator.GetBytes(32));
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        try {
            var redirect = "http://127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port + "/oauth2callback";
            var fields = new Dictionary<string,string> { ["client_id"] = ClientId, ["redirect_uri"] = redirect, ["response_type"] = "code", ["scope"] = Scope,
                ["code_challenge"] = challenge, ["code_challenge_method"] = "S256", ["state"] = state, ["access_type"] = "offline", ["prompt"] = "consent select_account" };
            var url = "https://accounts.google.com/o/oauth2/v2/auth?" + string.Join("&", fields.Select(p => Uri.EscapeDataString(p.Key) + "=" + Uri.EscapeDataString(p.Value)));
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            string? code = null;
            while (code == null) {
                using var socket = await listener.AcceptTcpClientAsync(timeout.Token);
                using var stream = socket.GetStream();
                var bytes = new byte[16384]; var count = 0;
                while (count < bytes.Length && !Encoding.UTF8.GetString(bytes, 0, count).Contains("\r\n\r\n")) {
                    var read = await stream.ReadAsync(bytes.AsMemory(count), timeout.Token); if (read == 0) break; count += read;
                }
                var path = Encoding.UTF8.GetString(bytes, 0, count).Split(' ').ElementAtOrDefault(1) ?? "";
                var uri = new Uri("http://127.0.0.1" + path);
                var query = uri.Query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries).Select(p => p.Split('=', 2)).ToDictionary(p => Uri.UnescapeDataString(p[0]), p => p.Length == 2 ? Uri.UnescapeDataString(p[1]) : "");
                var valid = uri.AbsolutePath == "/oauth2callback" && query.GetValueOrDefault("state") == state;
                var reply = valid ? "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nReturn to Tick to finish connecting Google Sheets." : "HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\nInvalid callback.";
                await stream.WriteAsync(Encoding.UTF8.GetBytes(reply), timeout.Token);
                if (!valid) continue;
                if (!query.TryGetValue("code", out code) || string.IsNullOrEmpty(code)) throw new InvalidDataException("Google sign-in was cancelled or denied.");
            }
            await Task.Run(() => {
                lock (gate) {
                    var result = Exchange(new() { ["client_id"] = ClientId, ["redirect_uri"] = redirect, ["grant_type"] = "authorization_code", ["code"] = code, ["code_verifier"] = verifier });
                    Credentials.Write(result.GetProperty("refresh_token").GetString() ?? throw new InvalidDataException("Google did not return persistent sign-in. Try again."));
                }
            }, timeout.Token);
        } finally { listener.Stop(); }
    }
    public void SignOut() { lock (gate) { Credentials.Delete(); token = null; expires = default; } }
    private static class Credentials
    {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct Credential {
            public uint Flags, Type; public string TargetName; public string? Comment; public long LastWritten;
            public uint BlobSize; public IntPtr Blob; public uint Persist, AttributeCount; public IntPtr Attributes;
            public string? TargetAlias, UserName;
        }
        [DllImport("advapi32", EntryPoint="CredReadW", CharSet=CharSet.Unicode, SetLastError=true)] private static extern bool ReadNative(string name, uint type, uint flags, out IntPtr credential);
        [DllImport("advapi32", EntryPoint="CredWriteW", CharSet=CharSet.Unicode, SetLastError=true)] private static extern bool WriteNative(ref Credential credential, uint flags);
        [DllImport("advapi32", EntryPoint="CredDeleteW", CharSet=CharSet.Unicode, SetLastError=true)] private static extern bool DeleteNative(string name, uint type, uint flags);
        [DllImport("advapi32")] private static extern void CredFree(IntPtr value);
        public static string Read() {
            if (!ReadNative(Service, 1, 0, out var pointer)) throw new InvalidDataException("Sign in with Google in Settings to reconnect your spreadsheet.");
            try { var cred = Marshal.PtrToStructure<Credential>(pointer); var bytes = new byte[cred.BlobSize]; Marshal.Copy(cred.Blob, bytes, 0, bytes.Length); return Encoding.UTF8.GetString(bytes); }
            finally { CredFree(pointer); }
        }
        public static void Write(string value) {
            var bytes = Encoding.UTF8.GetBytes(value); var blob = Marshal.AllocHGlobal(bytes.Length);
            try { Marshal.Copy(bytes,0,blob,bytes.Length); var credential = new Credential { Type=1, TargetName=Service, UserName="Tick", Persist=2, Blob=blob, BlobSize=(uint)bytes.Length };
                if (!WriteNative(ref credential,0)) throw new IOException("Could not save Google sign-in in Windows Credential Manager."); }
            finally { Marshal.FreeHGlobal(blob); }
        }
        public static void Delete() { if (!DeleteNative(Service,1,0) && Marshal.GetLastWin32Error()!=1168) throw new IOException("Could not remove Google sign-in."); }
    }
}
