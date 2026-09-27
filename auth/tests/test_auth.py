"""Unit tests for the auth Lambdas with moto (plan P4). Covers AT-05, AT-07, AT-08 and AT-19 logic."""
import base64
import importlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import boto3
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[1] / "lambda"
sys.path[:0] = [str(ROOT / "common"), str(ROOT / "auth_request"), str(ROOT / "auth_verify")]

EMAIL = "Jo.Bloggs@ACME.example"
CTX = SimpleNamespace(aws_request_id="test")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        for k, v in {
            "TABLE_ALLOWLIST": "allowlist", "TABLE_CODES": "codes", "TABLE_RATELIMIT": "ratelimit",
            "TABLE_SIGNINS": "signins", "PEPPER_PARAM": "/t/pepper", "SIGNING_KEY_PARAM": "/t/key",
            "KEY_PAIR_ID": "K123", "DELIVERY_DOMAIN": "learn.example.test", "SES_FROM": "no-reply@mail.example.test",
        }.items():
            monkeypatch.setenv(k, v)
        ddb = boto3.client("dynamodb")
        for name, keys in {
            "allowlist": [("slug", "S", "HASH"), ("domain", "S", "RANGE")],
            "codes": [("pk", "S", "HASH")],
            "ratelimit": [("email_hmac", "S", "HASH"), ("window_start", "N", "RANGE")],
            "signins": [("slug", "S", "HASH"), ("date", "S", "RANGE")],
        }.items():
            ddb.create_table(
                TableName=name, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": n, "KeyType": kt} for n, _, kt in keys],
                AttributeDefinitions=[{"AttributeName": n, "AttributeType": t} for n, t, _ in keys],
            )
        ddb.put_item(TableName="allowlist", Item={"slug": {"S": "acme"}, "domain": {"S": "acme.example"}})
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        ssm = boto3.client("ssm")
        ssm.put_parameter(Name="/t/pepper", Value="p" * 32, Type="SecureString")
        ssm.put_parameter(Name="/t/key", Value=pem, Type="SecureString")

        ac = _load("authcommon", ROOT / "common" / "authcommon.py")
        sys.modules["authcommon"] = ac
        req = _load("auth_request_handler", ROOT / "auth_request" / "handler.py")
        ver = _load("auth_verify_handler", ROOT / "auth_verify" / "handler.py")
        sent = []
        fake_ses = mock.Mock()
        fake_ses.send_email.side_effect = lambda **kw: sent.append(kw)
        req._ses = fake_ses
        with mock.patch.object(ac, "jitter", lambda *a, **k: None):
            yield SimpleNamespace(req=req, ver=ver, ac=ac, ddb=ddb, sent=sent, key=key)


def _ev(body):
    return {"body": json.dumps(body)}


def _code_from(sent):
    return sent[-1]["Content"]["Simple"]["Subject"]["Data"][:6]


def test_happy_path_sets_scoped_signed_cookies(env):
    r = env.req.handler(_ev({"c": "acme", "email": EMAIL}), CTX)
    assert r["statusCode"] == 202 and len(env.sent) == 1
    code = _code_from(env.sent)
    r = env.ver.handler(_ev({"c": "acme", "email": EMAIL, "code": code, "return": "/c/acme/claude-code-intro/"}), CTX)
    assert r["statusCode"] == 200
    assert json.loads(r["body"])["redirect"] == "/c/acme/claude-code-intro/"
    cookies = {c.split("=", 1)[0]: c for c in r["cookies"]}
    assert set(cookies) == {"CloudFront-Policy", "CloudFront-Signature", "CloudFront-Key-Pair-Id"}
    assert all("Path=/c/acme/;" in c and "Secure" in c and "HttpOnly" in c and "Domain" not in c
               for c in r["cookies"])
    # signature verifies against the public key over the exact policy bytes
    def unb64(v):
        return base64.b64decode(v.replace("-", "+").replace("_", "=").replace("~", "/"))
    val = lambda n: cookies[n].split("=", 1)[1].split(";", 1)[0]
    policy = unb64(val("CloudFront-Policy"))
    assert json.loads(policy)["Statement"][0]["Resource"] == "https://learn.example.test/c/acme/*"
    env.key.public_key().verify(unb64(val("CloudFront-Signature")), policy, padding.PKCS1v15(), hashes.SHA1())


def test_non_allowlisted_gets_same_202_and_no_send_or_record(env):  # AT-05
    ok = env.req.handler(_ev({"c": "acme", "email": EMAIL}), CTX)
    env.sent.clear()
    r = env.req.handler(_ev({"c": "acme", "email": "someone@other.example"}), CTX)
    assert r["statusCode"] == 202 and r["body"] == ok["body"]
    assert env.sent == []
    assert env.ddb.scan(TableName="codes")["Count"] == 1  # only the eligible one


def test_code_single_use_expiry_and_attempts(env):  # AT-07
    env.req.handler(_ev({"c": "acme", "email": EMAIL}), CTX)
    code = _code_from(env.sent)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert env.ver.handler(_ev({"c": "acme", "email": EMAIL, "code": wrong}), CTX)["statusCode"] == 401
    # sixth attempt fails even with the right code
    assert env.ver.handler(_ev({"c": "acme", "email": EMAIL, "code": code}), CTX)["statusCode"] == 401

    env.req.handler(_ev({"c": "acme", "email": EMAIL}), CTX)
    code = _code_from(env.sent)
    assert env.ver.handler(_ev({"c": "acme", "email": EMAIL, "code": code}), CTX)["statusCode"] == 200
    assert env.ver.handler(_ev({"c": "acme", "email": EMAIL, "code": code}), CTX)["statusCode"] == 401  # reuse

    env.req.handler(_ev({"c": "acme", "email": "x" + EMAIL}), CTX)
    code = _code_from(env.sent)
    with mock.patch.object(env.ver.time, "time", return_value=time.time() + 601):
        assert env.ver.handler(_ev({"c": "acme", "email": "x" + EMAIL, "code": code}), CTX)["statusCode"] == 401


def test_rate_limit_fourth_request_429(env):  # AT-07
    codes = [env.req.handler(_ev({"c": "acme", "email": EMAIL}), CTX)["statusCode"] for _ in range(4)]
    assert codes == [202, 202, 202, 429]


@pytest.mark.parametrize("ret", ["//evil.example", "https://evil.example", "/c/brightwater/", "/c/acme/..\\x",
                                 "/c/acme//evil", "javascript:alert(1)", None, "/c/acme/" + "a" * 600])
def test_open_redirect(env, ret):  # AT-08
    assert env.ver.safe_return(ret, "acme") == "/c/acme/"


def test_no_plaintext_email_stored(env, capsys):  # AT-19
    env.req.handler(_ev({"c": "acme", "email": EMAIL}), CTX)
    code = _code_from(env.sent)
    env.ver.handler(_ev({"c": "acme", "email": EMAIL, "code": code}), CTX)
    dump = json.dumps([env.ddb.scan(TableName=t)["Items"] for t in ("codes", "ratelimit", "signins", "allowlist")])
    logs = capsys.readouterr().out
    for needle in ("jo.bloggs", "Jo.Bloggs", "@acme.example"):
        assert needle.lower() not in dump.lower()
        assert needle.lower() not in logs.lower()


def test_never_returns_403(env):
    r = env.req.handler({"body": "not json"}, CTX)
    assert r["statusCode"] == 400
