using System.Management;
using System.Net;
using System.Security.Cryptography.X509Certificates;

namespace PulseAgent.Core;

/// <summary>The computer itself: the hostname and serial the inventory knows it by.</summary>
public static class Device
{
    private static readonly Lazy<string> serial = new(ReadSerial);

    /// <summary>The DNS host name without its domain, upper case, as the inventory records it.</summary>
    public static string Hostname
    {
        get
        {
            var name = Dns.GetHostName().Split('.')[0];
            if (string.IsNullOrWhiteSpace(name)) name = Environment.MachineName;
            return name.ToUpperInvariant()[..Math.Min(63, name.Length)];
        }
    }

    /// <summary>The firmware serial number, or UNKNOWN when the firmware does not report one.</summary>
    public static string Serial => serial.Value;

    private static string ReadSerial()
    {
        try
        {
            using var search = new ManagementObjectSearcher("SELECT SerialNumber FROM Win32_BIOS");
            foreach (var item in search.Get())
            {
                if (item["SerialNumber"]?.ToString()?.Trim() is { Length: > 0 } value)
                    return value[..Math.Min(64, value.Length)];
            }
        }
        catch
        {
        }
        return "UNKNOWN";
    }
}

/// <summary>The device's Intune MDM certificate: issued by the Microsoft Intune MDM Device CA when
/// the computer enrolled, held in the machine store, its subject the Intune device id. The agent
/// presents it as its TLS client certificate, as the Mac agent presents the Intune agent's. The
/// Entra device certificate is not used: its issuer is not published, so the service cannot
/// verify the chain.</summary>
public static class DeviceCertificate
{
    public const string Issuer = "Microsoft Intune MDM Device CA";

    /// <summary>The newest valid device certificate, or null. Using its private key needs SYSTEM or
    /// an administrator; finding it does not.</summary>
    public static X509Certificate2? Find(DateTime? now = null)
    {
        var at = now ?? DateTime.Now;
        try
        {
            using var store = new X509Store(StoreName.My, StoreLocation.LocalMachine);
            store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
            return store.Certificates
                .Where(c => IsIssuedByCa(c.Issuer)
                            && c.HasPrivateKey && c.NotBefore <= at && c.NotAfter > at)
                .OrderByDescending(c => c.NotAfter)
                .FirstOrDefault();
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Whether an issuer name is exactly the Intune MDM Device CA, not a CA whose name
    /// merely contains it.</summary>
    public static bool IsIssuedByCa(string issuer) =>
        issuer.Split(',').Select(p => p.Trim()).Contains($"CN={Issuer}", StringComparer.OrdinalIgnoreCase);

    /// <summary>The Intune device id a certificate names.</summary>
    public static string DeviceId(X509Certificate2 cert) => cert.GetNameInfo(X509NameType.SimpleName, false);
}
