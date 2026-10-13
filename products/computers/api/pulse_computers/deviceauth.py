"""Decide whether an ingest request may report for the seat it names.

An agent proves which computer it is with a TLS client certificate its management system
issued: on a Mac the Intune agent's (subject `IntuneMDMAgent-<Intune device id>`, issuer
`Microsoft Intune MDM Agent CA`), on Windows the Entra device certificate (subject the
Entra device id, issuer `MS-Organization-Access`). App Service requires a client certificate
on the ingest path, ends TLS only when the client proves it holds the key, and forwards that
certificate, base64 DER, in `X-ARR-ClientCert`. It does not check the issuer, so this
module does:

1. the certificate is signed by one of the configured issuing CAs and is in date,
2. its subject gives a device id, and
3. a device map says that id belongs to the hostname the event names.

Both issuing CAs serve every Microsoft tenant, so the chain alone proves only "some managed
device". Step 3 is what ties the certificate to a seat here: device ids are unique, and
only ids the site lists are accepted. The map is pluggable; CatalogDeviceMap reads each
seat's `deviceIds` from the catalog, and a directory lookup can replace it later.

A shared ingest key (`X-Pulse-Key`) is accepted instead only when one is configured.

    python -m pulse_computers.deviceauth device.pem [--ca bundle.pem]

prints what the service reads from a certificate, and whether it chains to the bundle.
"""

import argparse
import base64
import hmac
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID, NameOID

CERT_HEADER = "X-ARR-ClientCert"
KEY_HEADER = "X-Pulse-Key"
MAC_PREFIX = "IntuneMDMAgent-"


class CertificateError(ValueError):
    pass


def parse_certificate(value: str) -> x509.Certificate:
    """A certificate as App Service forwards it (base64 DER), or as PEM, possibly URL-encoded."""
    value = value.strip()
    if "%" in value:
        value = urllib.parse.unquote(value)
    try:
        if value.startswith("-----BEGIN"):
            return x509.load_pem_x509_certificate(value.encode())
        return x509.load_der_x509_certificate(base64.b64decode(value))
    except ValueError as e:
        raise CertificateError(f"unreadable client certificate: {e}") from None


def load_bundle(pem: str) -> list[x509.Certificate]:
    try:
        return x509.load_pem_x509_certificates(pem.encode()) if pem.strip() else []
    except ValueError as e:
        raise CertificateError(f"unreadable CA bundle: {e}") from None


def _in_date(cert: x509.Certificate, now: datetime) -> bool:
    return cert.not_valid_before_utc <= now <= cert.not_valid_after_utc


def verify(cert: x509.Certificate, cas: list[x509.Certificate], now: datetime | None = None) -> x509.Certificate:
    """The CA that signed cert. The agents send only their own certificate, so the bundle
    holds the issuing CAs themselves and each one is a trust anchor."""
    now = now or datetime.now(timezone.utc)
    if not _in_date(cert, now):
        raise CertificateError("client certificate is expired or not yet valid")
    for ca in cas:
        if ca.subject != cert.issuer or not _in_date(ca, now):
            continue
        try:
            cert.verify_directly_issued_by(ca)
        except (InvalidSignature, ValueError, TypeError):
            continue
        return ca
    raise CertificateError(f"client certificate is not issued by a trusted CA ({cert.issuer.rfc4514_string()})")


def device_id(cert: x509.Certificate) -> str:
    """The Intune device id (Mac) or Entra device id (Windows) a certificate names, lowercase."""
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cn = str(names[0].value).strip() if names else ""
    if cn.startswith(MAC_PREFIX):
        cn = cn[len(MAC_PREFIX):]
    if not cn:
        raise CertificateError("client certificate names no device")
    return cn.lower()


class DeviceMap(Protocol):
    def known(self, hostname: str) -> bool: ...
    def allows(self, hostname: str, device_id: str) -> bool: ...


class CatalogDeviceMap:
    """Seats and their device ids from the catalog: each seat's `deviceIds`, which the
    catalog build fills from inventory fields (`device_id_fields` in pulse_core.inventory)."""

    def __init__(self, catalog: dict):
        self.seats = {seat["hostname"].upper(): {d.lower() for d in seat.get("deviceIds", [])}
                      for space in catalog["spaces"] for seat in space["seats"]}

    def known(self, hostname: str) -> bool:
        return hostname.upper() in self.seats

    def allows(self, hostname: str, device_id: str) -> bool:
        return device_id.lower() in self.seats.get(hostname.upper(), set())


@dataclass(frozen=True)
class Decision:
    ok: bool
    status: int = 202
    reason: str = ""
    device_id: str | None = None
    via: str = ""  # "certificate" or "key"


def authorize(headers: Mapping[str, str], hostname: str, devices: DeviceMap, cas: list[x509.Certificate],
              ingest_key: str = "", now: datetime | None = None) -> Decision:
    """Whether a request whose event names hostname may be stored. headers must look names
    up case-insensitively, as the Functions and http.server request headers do."""
    if not devices.known(hostname):
        return Decision(False, 403, f"{hostname} is not a seat in the catalog")
    reason = "no client certificate"
    raw = headers.get(CERT_HEADER)
    if raw:
        try:
            cert = parse_certificate(raw)
            verify(cert, cas, now)
            found = device_id(cert)
            if devices.allows(hostname, found):
                return Decision(True, device_id=found, via="certificate")
            reason = f"device {found} is not listed for {hostname}"
        except CertificateError as e:
            reason = str(e)
    sent = headers.get(KEY_HEADER) or ""
    if ingest_key and sent and hmac.compare_digest(sent.encode(), ingest_key.encode()):
        return Decision(True, via="key")
    return Decision(False, 403 if raw else 401, reason)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show what the ingest service reads from a device certificate.")
    parser.add_argument("cert", help="the device certificate, PEM or DER")
    parser.add_argument("--ca", help="PEM bundle of issuing CAs to check it against")
    args = parser.parse_args(argv)
    with open(args.cert, "rb") as f:
        data = f.read()
    cert = (x509.load_pem_x509_certificate(data) if data.lstrip().startswith(b"-----BEGIN")
            else x509.load_der_x509_certificate(data))
    print(f"subject:   {cert.subject.rfc4514_string()}")
    print(f"issuer:    {cert.issuer.rfc4514_string()}")
    print(f"valid:     {cert.not_valid_before_utc:%Y-%m-%d} to {cert.not_valid_after_utc:%Y-%m-%d}")
    try:
        print(f"device id: {device_id(cert)}")
    except CertificateError as e:
        print(f"device id: none ({e})")
    try:
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
        for d in aia:
            if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS:
                print(f"issuer certificate: {d.access_location.value}")
    except x509.ExtensionNotFound:
        pass
    if args.ca:
        with open(args.ca) as f:
            bundle = f.read()
        try:
            ca = verify(cert, load_bundle(bundle))
        except CertificateError as e:
            print(f"does not verify: {e}")
            return 1
        print(f"chains to: {ca.subject.rfc4514_string()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
