"""POST /auth/api/request  {"c": slug, "email": string}  ->  always 202 (plan 8.1)."""
from __future__ import annotations

import os
import secrets
import time

import boto3
from botocore.exceptions import ClientError

import authcommon as ac

RATE_MAX = int(os.environ.get("RATE_MAX", "3"))  # per address per window; plan 8.1 specifies 3
RATE_WINDOW = 15 * 60
CODE_TTL = 600
ACCEPTED = {"status": "accepted", "message": "If this address is eligible, a code is on its way."}

_ses = None


def _ses_client():
    global _ses
    if _ses is None:
        _ses = boto3.client("sesv2")
    return _ses


def _rate_limited(e_hmac: str, now: int) -> bool:
    window = now - now % RATE_WINDOW
    try:
        ac.ddb().update_item(
            TableName=os.environ["TABLE_RATELIMIT"],
            Key={"email_hmac": {"S": e_hmac}, "window_start": {"N": str(window)}},
            UpdateExpression="ADD #c :one SET #t = :ttl",
            ConditionExpression="attribute_not_exists(#c) OR #c < :max",
            ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
            ExpressionAttributeValues={
                ":one": {"N": "1"},
                ":max": {"N": str(RATE_MAX)},
                ":ttl": {"N": str(window + RATE_WINDOW + 3600)},
            },
        )
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise


def _allowlisted(slug: str, domain: str) -> bool:
    item = ac.ddb().get_item(
        TableName=os.environ["TABLE_ALLOWLIST"],
        Key={"slug": {"S": slug}, "domain": {"S": domain}},
    ).get("Item")
    return item is not None


def _customer_name(slug: str) -> str:
    return "internal" if slug == "internal" else slug.replace("-", " ").title()


def _send(email: str, slug: str, code: str) -> None:
    name = _customer_name(slug)
    text = (
        f"Your sign-in code for the {name} Claude enablement site is:\n\n"
        f"    {code}\n\n"
        "It expires in 10 minutes and can be used once.\n"
        "If you did not ask for this code, you can ignore this email.\n"
    )
    kwargs = {
        "FromEmailAddress": os.environ["SES_FROM"],
        "Destination": {"ToAddresses": [email]},
        "Content": {"Simple": {
            "Subject": {"Data": f"{code} is your {name} sign-in code"},
            "Body": {"Text": {"Data": text}},
        }},
    }
    if os.environ.get("SES_CONFIG_SET"):
        kwargs["ConfigurationSetName"] = os.environ["SES_CONFIG_SET"]
    _ses_client().send_email(**kwargs)


def handler(event, context):
    rid = getattr(context, "aws_request_id", "-")
    body = ac.parse_body(event)
    slug = body.get("c") if isinstance(body.get("c"), str) else ""
    email = ac.normalise_email(body.get("email", ""))
    if not ac.SLUG_RE.match(slug or "") or not email:
        ac.log(rid, slug[:40] if slug else "-", "bad_request")
        return ac.respond(400, {"status": "invalid", "message": "Enter a valid email address."})

    now = int(time.time())
    e_hmac = ac.email_hmac(email)
    if _rate_limited(e_hmac, now):
        ac.log(rid, slug, "rate_limited")
        return ac.respond(429, {"status": "rate_limited", "message": "Too many requests. Try again in 15 minutes."})

    payload = dict(ACCEPTED)
    domain = email.split("@")[1]
    if _allowlisted(slug, domain):
        code = f"{secrets.randbelow(10**6):06d}"
        expires = now + CODE_TTL
        ac.ddb().put_item(
            TableName=os.environ["TABLE_CODES"],
            Item={
                "pk": {"S": f"{slug}#{e_hmac}"},
                "code_hmac": {"S": ac.code_hmac(slug, e_hmac, code)},
                "expires_at": {"N": str(expires)},
                "attempts": {"N": "0"},
                "ttl": {"N": str(expires + 3600)},
            },
        )
        try:
            _send(email, slug, code)
            outcome = "sent"
        except ClientError as e:
            outcome = f"send_failed:{e.response['Error']['Code']}"
        if os.environ.get("DEMO_SHOW_CODE") == "true":  # DEMO ONLY - technical debt, never in production
            payload["demo_code"] = code
    else:
        outcome = "not_eligible"
    ac.jitter()
    ac.log(rid, slug, outcome)
    return ac.respond(202, payload)
