"""POST /auth/api/verify  {"c", "email", "code", "return"}  ->  200 + signed cookies, or 401 (plan 8.1)."""
from __future__ import annotations

import base64
import datetime as dt
import hmac
import json
import os
import re
import time

from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import authcommon as ac

MAX_ATTEMPTS = 5
COOKIE_TTL = 7 * 24 * 3600
CODE_RE = re.compile(r"^\d{6}$")
UNAUTHORISED = {"status": "invalid_code", "message": "That code is not valid. Check it, or request a new one."}

_key = None


def _private_key():
    global _key
    if _key is None:
        pem = ac.param(os.environ["SIGNING_KEY_PARAM"]).encode()
        _key = serialization.load_pem_private_key(pem, password=None)
    return _key


def cf_b64(data: bytes) -> str:
    """CloudFront-safe base64: + -> -, = -> _, / -> ~."""
    return base64.b64encode(data).decode().replace("+", "-").replace("=", "_").replace("/", "~")


def sign_cookies(domain: str, slug: str, now: int, key=None) -> list[str]:
    policy = json.dumps(
        {"Statement": [{
            "Resource": f"https://{domain}/c/{slug}/*",
            "Condition": {"DateLessThan": {"AWS:EpochTime": now + COOKIE_TTL}},
        }]},
        separators=(",", ":"),
    ).encode()
    # CloudFront signed cookies: RSA with SHA-1, PKCS#1 v1.5 (VERIFY whether SHA-256 is now accepted)
    signature = (key or _private_key()).sign(policy, padding.PKCS1v15(), hashes.SHA1())
    attrs = f"Path=/c/{slug}/; Secure; HttpOnly; SameSite=Lax; Max-Age={COOKIE_TTL}"
    return [
        f"CloudFront-Policy={cf_b64(policy)}; {attrs}",
        f"CloudFront-Signature={cf_b64(signature)}; {attrs}",
        f"CloudFront-Key-Pair-Id={os.environ['KEY_PAIR_ID']}; {attrs}",
    ]


def safe_return(value, slug: str) -> str:
    default = f"/c/{slug}/"
    if not isinstance(value, str) or len(value) >= 512:
        return default
    if not value.startswith(default) or "//" in value or "\\" in value or re.search(r"[a-z][a-z0-9+.-]*:", value, re.I):
        return default
    return value


def delivery_domain() -> str:
    # A parameter, not an env var: the distribution depends on this function's URL, so Terraform
    # cannot pass the distribution's domain into the function without a cycle.
    return os.environ.get("DELIVERY_DOMAIN") or ac.param(os.environ["DELIVERY_DOMAIN_PARAM"])


def _codes_table() -> str:
    return os.environ["TABLE_CODES"]


def handler(event, context):
    rid = getattr(context, "aws_request_id", "-")
    body = ac.parse_body(event)
    slug = body.get("c") if isinstance(body.get("c"), str) else ""
    email = ac.normalise_email(body.get("email", ""))
    code = body.get("code") if isinstance(body.get("code"), str) else ""
    code = code.strip()
    if not ac.SLUG_RE.match(slug or "") or not email or not CODE_RE.match(code):
        ac.log(rid, slug[:40] if slug else "-", "bad_request")
        return ac.respond(400, {"status": "invalid", "message": "Enter the 6-digit code from the email."})

    e_hmac = ac.email_hmac(email)
    pk = {"pk": {"S": f"{slug}#{e_hmac}"}}
    item = ac.ddb().get_item(TableName=_codes_table(), Key=pk, ConsistentRead=True).get("Item")
    now = int(time.time())
    if not item or now > int(item["expires_at"]["N"]) or int(item["attempts"]["N"]) >= MAX_ATTEMPTS:
        ac.log(rid, slug, "no_valid_code")
        return ac.respond(401, UNAUTHORISED)

    expected = item["code_hmac"]["S"]
    if not hmac.compare_digest(expected, ac.code_hmac(slug, e_hmac, code)):
        try:
            ac.ddb().update_item(
                TableName=_codes_table(), Key=pk,
                UpdateExpression="ADD attempts :one",
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeValues={":one": {"N": "1"}},
            )
        except ClientError:
            pass
        ac.log(rid, slug, "mismatch")
        return ac.respond(401, UNAUTHORISED)

    try:  # single use: only one caller can delete the record
        ac.ddb().delete_item(
            TableName=_codes_table(), Key=pk,
            ConditionExpression="attribute_exists(pk) AND code_hmac = :h",
            ExpressionAttributeValues={":h": {"S": expected}},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            ac.log(rid, slug, "race_lost")
            return ac.respond(401, UNAUTHORISED)
        raise

    cookies = sign_cookies(delivery_domain(), slug, now)
    ac.ddb().update_item(
        TableName=os.environ["TABLE_SIGNINS"],
        Key={"slug": {"S": slug}, "date": {"S": dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()}},
        UpdateExpression="ADD #c :one",
        ExpressionAttributeNames={"#c": "count"},
        ExpressionAttributeValues={":one": {"N": "1"}},
    )
    ac.log(rid, slug, "signed_in")
    return ac.respond(200, {"redirect": safe_return(body.get("return"), slug)}, cookies)
