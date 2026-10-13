from datetime import timedelta

import pytest

from certs import MAC_CA, NOW, WIN_CA, header, make, pem
from pulse_computers.deviceauth import (CatalogDeviceMap, CertificateError, authorize, device_id, load_bundle,
                                        parse_certificate, verify)

MAC_ID = "6f1c2d3e-0000-4000-8000-00000000000a"
WIN_ID = "0a9b8c7d-0000-4000-8000-00000000000b"

mac_ca = make(MAC_CA, ca=True)
win_ca = make(WIN_CA, ca=True)
mac_leaf = make(f"IntuneMDMAgent-{MAC_ID.upper()}", mac_ca)[0]
win_leaf = make(WIN_ID, win_ca)[0]
CAS = load_bundle(pem(mac_ca[0], win_ca[0]))

CATALOG = {"spaces": [{"id": "lab", "name": "Lab", "kind": "lab", "seats": [
    {"hostname": "LAB-01", "platform": "mac", "deviceIds": [MAC_ID]},
    {"hostname": "LAB-02", "platform": "windows", "deviceIds": [WIN_ID.upper()]},
    {"hostname": "LAB-03", "platform": "mac"},
]}]}
DEVICES = CatalogDeviceMap(CATALOG)


class Headers(dict):
    """Case-insensitive, like the Functions request headers."""

    def __init__(self, **kw):
        super().__init__({k.lower(): v for k, v in kw.items()})

    def get(self, key, default=None):
        return super().get(key.lower(), default)


def cert_headers(cert, **more):
    return Headers(**{"X-ARR-ClientCert": header(cert)}, **more)


def test_device_ids_from_both_platforms():
    assert device_id(mac_leaf) == MAC_ID
    assert device_id(win_leaf) == WIN_ID


def test_parse_accepts_der_base64_and_pem():
    assert parse_certificate(header(mac_leaf)) == mac_leaf
    assert parse_certificate(pem(mac_leaf)) == mac_leaf
    with pytest.raises(CertificateError):
        parse_certificate("not a certificate")


def test_verify_checks_signature_issuer_and_dates():
    assert verify(mac_leaf, CAS, NOW).subject == mac_ca[0].subject
    assert verify(win_leaf, CAS, NOW).subject == win_ca[0].subject
    impostor = make(MAC_CA, ca=True)  # same name, different key
    forged = make(f"IntuneMDMAgent-{MAC_ID}", impostor)[0]
    with pytest.raises(CertificateError, match="trusted CA"):
        verify(forged, CAS, NOW)
    expired = make(f"IntuneMDMAgent-{MAC_ID}", mac_ca, days=10, start=NOW - timedelta(days=30))[0]
    with pytest.raises(CertificateError, match="expired"):
        verify(expired, CAS, NOW)
    with pytest.raises(CertificateError):
        verify(mac_leaf, [], NOW)


def test_certificate_must_belong_to_the_seat():
    assert authorize(cert_headers(mac_leaf), "lab-01", DEVICES, CAS, now=NOW).ok
    d = authorize(cert_headers(win_leaf), "LAB-02", DEVICES, CAS, now=NOW)
    assert d.ok and d.via == "certificate" and d.device_id == WIN_ID
    wrong = authorize(cert_headers(mac_leaf), "LAB-02", DEVICES, CAS, now=NOW)
    assert not wrong.ok and wrong.status == 403 and "not listed" in wrong.reason
    unlisted = authorize(cert_headers(mac_leaf), "LAB-03", DEVICES, CAS, now=NOW)
    assert not unlisted.ok


def test_unknown_hostnames_are_refused_whatever_the_credential():
    d = authorize(cert_headers(mac_leaf, **{"X-Pulse-Key": "k"}), "ELSEWHERE", DEVICES, CAS, "k", now=NOW)
    assert not d.ok and d.status == 403


def test_ingest_key_only_when_configured():
    keyed = Headers(**{"X-Pulse-Key": "secret"})
    assert not authorize(keyed, "LAB-03", DEVICES, CAS, now=NOW).ok
    assert authorize(keyed, "LAB-03", DEVICES, CAS, "secret", now=NOW).via == "key"
    d = authorize(Headers(**{"X-Pulse-Key": "guess"}), "LAB-03", DEVICES, CAS, "secret", now=NOW)
    assert not d.ok and d.status == 401
    assert authorize(Headers(), "LAB-03", DEVICES, CAS, "secret", now=NOW).status == 401


def test_cli_reports_device_and_chain(tmp_path, capsys):
    from pulse_computers.deviceauth import main
    (tmp_path / "leaf.pem").write_text(pem(win_leaf))
    (tmp_path / "ca.pem").write_text(pem(win_ca[0]))
    assert main([str(tmp_path / "leaf.pem"), "--ca", str(tmp_path / "ca.pem")]) == 0
    out = capsys.readouterr().out
    assert f"device id: {WIN_ID}" in out and f"CN={WIN_CA}" in out


def test_ca_out_of_date_is_not_trusted():
    old_ca = make(MAC_CA, ca=True, days=10, start=NOW - timedelta(days=100))
    leaf = make("IntuneMDMAgent-x", old_ca, start=NOW - timedelta(days=95))[0]
    with pytest.raises(CertificateError):
        verify(leaf, [old_ca[0]], NOW)
