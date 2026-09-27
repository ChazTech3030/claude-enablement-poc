"""Deploy and publish (plan 6.7). Needs AWS credentials (GitHub OIDC role in CI).

Configuration comes from the environment, set from Terraform outputs as GitHub repository variables:
  DK_BUCKET, DK_DISTRIBUTION_ID, DK_KVS_ARN, DK_ALLOWLIST_TABLE, AWS_REGION
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import boto3

from .repo import Repo

STATE_SHA = "state/last-deployed-sha"
INTERNAL = "internal"  # allowlist for the reserved slug is owned by Terraform


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"environment variable {name} is required")
    return v


def s3_sync(site_dir: Path, prefix: str, delete: bool = True) -> None:
    bucket = env("DK_BUCKET")
    cmd = ["aws", "s3", "sync", str(site_dir), f"s3://{bucket}/{prefix.strip('/')}/", "--only-show-errors"]
    if delete:
        cmd.append("--delete")
    subprocess.run(cmd, check=True)


def s3_remove_prefix(prefix: str) -> None:
    bucket = env("DK_BUCKET")
    subprocess.run(
        ["aws", "s3", "rm", f"s3://{bucket}/{prefix.strip('/')}/", "--recursive", "--only-show-errors"], check=True
    )


def invalidate(paths: list[str], wait: bool = True) -> str:
    cf = boto3.client("cloudfront")
    dist = env("DK_DISTRIBUTION_ID")
    resp = cf.create_invalidation(
        DistributionId=dist,
        InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths},
            "CallerReference": f"dk-{time.time_ns()}",
        },
    )
    inv_id = resp["Invalidation"]["Id"]
    print(f"invalidation {inv_id}: {', '.join(paths)}")
    if wait:
        cf.get_waiter("invalidation_completed").wait(
            DistributionId=dist, Id=inv_id, WaiterConfig={"Delay": 10, "MaxAttempts": 60}
        )
    return inv_id


def read_state() -> str | None:
    s3 = boto3.client("s3")
    try:
        return s3.get_object(Bucket=env("DK_BUCKET"), Key=STATE_SHA)["Body"].read().decode().strip() or None
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:  # AccessDenied on an empty bucket behaves like "no state"
        print(f"state unavailable ({e.__class__.__name__}); treating as first deploy")
        return None


def write_state(sha: str) -> None:
    boto3.client("s3").put_object(Bucket=env("DK_BUCKET"), Key=STATE_SHA, Body=sha.encode(), ContentType="text/plain")


def publish_allowlists(repo: Repo) -> None:
    """Make the allowlist table match the manifests. Revoked customers have no rows."""
    table = env("DK_ALLOWLIST_TABLE")
    ddb = boto3.client("dynamodb")
    for c in repo.customers.values():
        want = set(c.allowlist) if c.active else set()
        items = ddb.query(
            TableName=table,
            KeyConditionExpression="slug = :s",
            ExpressionAttributeValues={":s": {"S": c.slug}},
        )["Items"]
        have = {i["domain"]["S"] for i in items}
        ops = [{"Delete": {"TableName": table, "Key": {"slug": {"S": c.slug}, "domain": {"S": d}}}} for d in have - want]
        ops += [{"Put": {"TableName": table, "Item": {"slug": {"S": c.slug}, "domain": {"S": d}}}} for d in want - have]
        if ops:
            ddb.transact_write_items(TransactItems=ops)  # single transactional batch per customer
            print(f"allowlist {c.slug}: +{len(want - have)} -{len(have - want)}")


def publish_revocations(repo: Repo) -> None:
    """KVS holds revoked:{slug} for each revoked customer, and nothing else under that prefix."""
    arn = env("DK_KVS_ARN")
    kvs = boto3.client("cloudfront-keyvaluestore", region_name="us-east-1")
    etag = kvs.describe_key_value_store(KvsARN=arn)["ETag"]
    existing: set[str] = set()
    token = None
    while True:
        kwargs = {"KvsARN": arn, "MaxResults": 50}
        if token:
            kwargs["NextToken"] = token
        page = kvs.list_keys(**kwargs)
        existing |= {i["Key"] for i in page.get("Items", []) if i["Key"].startswith("revoked:")}
        token = page.get("NextToken")
        if not token:
            break
    want = {f"revoked:{c.slug}" for c in repo.customers.values() if not c.active}
    puts = [{"Key": k, "Value": "1"} for k in sorted(want - existing)]
    deletes = [{"Key": k} for k in sorted(existing - want)]
    if puts or deletes:
        kvs.update_keys(KvsARN=arn, IfMatch=etag, Puts=puts, Deletes=deletes)
        print(f"kvs: revoked +{[p['Key'] for p in puts]} -{[d['Key'] for d in deletes]}")
    else:
        print("kvs: no revocation changes")
