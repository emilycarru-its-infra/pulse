using System.Net.Http.Headers;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace PulseAgent.Core;

/// <summary>The outcome of one send: the HTTP status when the server answered, else the error.</summary>
public sealed record SendResult(int? Status, string? Error)
{
    public bool Ok => Status is >= 200 and < 300;
    public override string ToString() => Ok ? $"HTTP {Status}" : Status is { } s ? $"HTTP {s}: {Error}" : Error ?? "failed";
}

/// <summary>Posts events to the ingest address, presenting the device certificate and, when one is
/// set, the shared key.</summary>
public sealed class IngestClient : IDisposable
{
    public const string KeyHeader = "X-Pulse-Key";
    private readonly HttpClient http;
    private readonly AgentSettings settings;

    public X509Certificate2? Certificate { get; }

    public IngestClient(AgentSettings settings, X509Certificate2? certificate)
    {
        this.settings = settings;
        Certificate = settings.UseDeviceCertificate ? certificate : null;
        var handler = new SocketsHttpHandler
        {
            ConnectTimeout = TimeSpan.FromSeconds(10),
            PooledConnectionLifetime = TimeSpan.FromMinutes(10),
        };
        if (Certificate is not null)
            handler.SslOptions = new SslClientAuthenticationOptions { ClientCertificates = [Certificate] };
        http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(15) };
        http.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue(Identity.ProductKey, Identity.Version));
    }

    public async Task<SendResult> SendAsync(PulseEvent pulse, CancellationToken cancel = default)
    {
        if (string.IsNullOrWhiteSpace(settings.IngestUrl))
            return new SendResult(null, "no ingest address is set");
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, settings.IngestUrl)
            {
                Content = new StringContent(pulse.ToJson(), Encoding.UTF8, "application/json"),
            };
            if (!string.IsNullOrWhiteSpace(settings.IngestKey))
                request.Headers.TryAddWithoutValidation(KeyHeader, settings.IngestKey);
            using var response = await http.SendAsync(request, cancel);
            if (response.IsSuccessStatusCode) return new SendResult((int)response.StatusCode, null);
            var body = await response.Content.ReadAsStringAsync(cancel);
            return new SendResult((int)response.StatusCode, body.Length > 200 ? body[..200] : body);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or InvalidOperationException)
        {
            return new SendResult(null, ex.InnerException?.Message ?? ex.Message);
        }
    }

    public void Dispose() => http.Dispose();
}
