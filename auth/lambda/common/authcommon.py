"""Shared helpers for the auth Lambdas (plan 8.1). Never log or persist a plaintext email address."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import re
import time

import boto3

EMAIL_RE = re.compile(r"^[^\s@]{1,64}@([a-z0-9-]+\.)+[a-z]{2,63}$")
SLUG_RE = re.compile(r"^[a-z0-9-]{3,32}$")

_ssm = None
_cache: dict[str, str] = {}
_ddb = None


def ddb():
    global _ddb
    if _ddb is None:
        _ddb = boto3.client("dynamodb")
    return _ddb


def param(name: str) -> str:
    """SecureString from Parameter Store, cached for the life of the container."""
    global _ssm
    if name not in _cache:
        if _ssm is None:
            _ssm = boto3.client("ssm")
        _cache[name] = _ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return _cache[name]


def pepper() -> bytes:
    return param(os.environ["PEPPER_PARAM"]).encode()


def normalise_email(raw: str) -> str | None:
    """Trim, lower-case the domain part, basic syntax check. Returns None if invalid."""
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if raw.count("@") != 1 or len(raw) > 254:
        return None
    local, domain = raw.split("@")
    email = f"{local}@{domain.lower()}"
    return email if EMAIL_RE.match(email) else None


def email_hmac(email: str) -> str:
    return hmac.new(pepper(), email.lower().encode(), hashlib.sha256).hexdigest()


def code_hmac(slug: str, e_hmac: str, code: str) -> str:
    return hmac.new(pepper(), f"{slug}|{e_hmac}|{code}".encode(), hashlib.sha256).hexdigest()


def parse_body(event: dict) -> dict:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", "replace")
    try:
        data = json.loads(body)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def respond(status: int, payload: dict, cookies: list[str] | None = None) -> dict:
    # Never 403: the distribution maps 403 to the gate page (plan 7.4).
    assert status != 403
    resp = {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(payload),
    }
    if cookies:
        resp["cookies"] = cookies
    return resp


def jitter(lo: float = 0.15, hi: float = 0.45) -> None:
    """Small random delay so response timing does not reveal allowlist or SES outcomes."""
    time.sleep(random.uniform(lo, hi))


def log(request_id: str, slug: str, outcome: str) -> None:
    """The only log line the handlers emit: slug, outcome class, request id. No email address."""
    print(json.dumps({"request_id": request_id, "slug": slug, "outcome": outcome}))
