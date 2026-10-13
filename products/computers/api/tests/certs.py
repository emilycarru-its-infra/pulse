"""Throwaway CAs and device certificates for the tests, made with cryptography."""

import base64
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

NOW = datetime(2027, 1, 4, 17, 0, tzinfo=timezone.utc)
START = datetime(2025, 1, 1, tzinfo=timezone.utc)  # before NOW and before today, so both are in date
MAC_CA = "Microsoft Intune MDM Agent CA"
WIN_CA = "MS-Organization-Access"


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make(cn: str, issuer=None, ca: bool = False, days: int = 3650, start: datetime = START):
    """(certificate, private key); issuer is another (certificate, key), or None to self-sign."""
    key = ec.generate_private_key(ec.SECP256R1())
    signer_cert, signer_key = issuer or (None, key)
    builder = (x509.CertificateBuilder()
               .subject_name(_name(cn))
               .issuer_name(signer_cert.subject if signer_cert else _name(cn))
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(start)
               .not_valid_after(start + timedelta(days=days))
               .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    return builder.sign(signer_key, hashes.SHA256()), key


def pem(*certs) -> str:
    return "".join(c.public_bytes(serialization.Encoding.PEM).decode() for c in certs)


def header(cert) -> str:
    """The certificate as App Service forwards it in X-ARR-ClientCert."""
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
