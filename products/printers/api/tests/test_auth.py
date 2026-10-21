import time

import pytest

jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from pulse_printers import auth  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000001"
AUD = "11111111-1111-1111-1111-111111111111"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key=KEY, **claims):
    now = int(time.time())
    body = {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": AUD, "tid": TENANT,
            "iat": now, "exp": now + 600, "roles": [auth.INGEST_ROLE], "idtyp": "app", **claims}
    return jwt.encode(body, key, algorithm="RS256")


def check(tok):
    return auth.check_ingest_token(tok, TENANT, [AUD], key=KEY.public_key())


def test_a_valid_app_token_passes():
    assert check(token())["aud"] == AUD
    assert check(token(iss=f"https://sts.windows.net/{TENANT}/"))["aud"] == AUD


@pytest.mark.parametrize("tok", [
    token(key=OTHER),
    token(aud="someone-else"),
    token(iss="https://login.microsoftonline.com/another/v2.0"),
    token(tid="another"),
    token(roles=["Pulse.Alerts"]),
    token(roles=[]),
    token(idtyp="user"),
    token(scp="User.Read"),
    token(exp=int(time.time()) - 3600),
])
def test_bad_tokens_are_refused(tok):
    with pytest.raises(auth.Unauthorized):
        check(tok)


def test_bearer_header_is_required():
    for header in (None, "", "Basic abc", "Bearer "):
        with pytest.raises(auth.Unauthorized):
            auth.bearer(header)


def test_unconfigured_ingest_refuses():
    with pytest.raises(auth.Unauthorized):
        auth.check_ingest_token(token(), "", [AUD], key=KEY.public_key())
    with pytest.raises(auth.Unauthorized):
        auth.check_ingest_token(token(), TENANT, [], key=KEY.public_key())
