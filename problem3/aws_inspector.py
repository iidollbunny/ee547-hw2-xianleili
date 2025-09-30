#!/usr/bin/env python3
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    ConnectTimeoutError,
    ReadTimeoutError,
)

# Convert datetime to UTC ISO string
def utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def warn(msg: str): print(f"[WARNING] {msg}", file=sys.stderr)
def error(msg: str): print(f"[ERROR] {msg}", file=sys.stderr)

# Retry once on network errors
def try_once_retry_once(fn, *, on: str):
    try:
        return fn()
    except (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError):
        warn(f"Network issue while {on}, retrying...")
        time.sleep(1.0)
        try: return fn()
        except (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError):
            warn(f"Network issue persisted while {on}, skipping.")
            return None

# Validate region
def validate_region_or_exit(session: boto3.session.Session, region: Optional[str]) -> str:
    if region:
        valid = set(session.get_available_regions("ec2"))
        if region not in valid:
            error(f"Invalid region '{region}'")
            sys.exit(2)
        return region
    return session.region_name or "unknown"

def write_or_print(text: str, path: Optional[str]) -> None:
    if path: open(path, "w", encoding="utf-8").write(text)
    else: print(text)

# Collectors 

# Verify authentication
def get_account_identity(sts_client) -> Tuple[str, str]:
    try:
        ident = sts_client.get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except ClientError as e:
        error(f"Authentication failed: {e}")
        sys.exit(1)

# IAM Users
def collect_iam_users(iam_client) -> List[Dict[str, Any]]:
    out = []
    try: paginator = iam_client.get_paginator("list_users")
    except ClientError: return out

    def _run():
        results = []
        for page in paginator.paginate():
            for u in page.get("Users", []):
                username = u.get("UserName")
                create_date = utc_iso(u.get("CreateDate"))
                last_activity = None
                try:
                    gu = iam_client.get_user(UserName=username)
                    last_activity = utc_iso(gu.get("User", {}).get("PasswordLastUsed"))
                except ClientError: pass

                # Attached policies
                attached = []
                try:
                    pol_paginator = iam_client.get_paginator("list_attached_user_policies")
                    for pol_page in pol_paginator.paginate(UserName=username):
                        for p in pol_page.get("AttachedPolicies", []):
                            attached.append({"policy_name": p.get("PolicyName"),"policy_arn": p.get("PolicyArn")})
                except ClientError: warn(f"Cannot list policies for {username}")

                results.append({
                    "username": username,
                    "user_id": u.get("UserId"),
                    "arn": u.get("Arn"),
                    "create_date": create_date,
                    "last_activity": last_activity,
                    "attached_policies": attached,
                })
        return results
    return try_once_retry_once(_run, on="IAM users") or out

# EC2 Instances
def collect_ec2_instances(ec2_client, ec2_resource) -> List[Dict[str, Any]]:
    out = []
    def _ami_names(ids: List[str]) -> Dict[str, str]:
        if not ids: return {}
        try: return {img["ImageId"]: img.get("Name") for img in ec2_client.describe_images(ImageIds=ids).get("Images", [])}
        except ClientError: return {}

    def _run():
        results, ami_ids = [], set()
        for page in ec2_client.get_paginator("describe_instances").paginate():
            for res in page.get("Reservations", []):
                for inst in res.get("Instances", []):
                    ami_id = inst.get("ImageId")
                    if ami_id: ami_ids.add(ami_id)
                    results.append({
                        "instance_id": inst.get("InstanceId"),
                        "instance_type": inst.get("InstanceType"),
                        "state": (inst.get("State") or {}).get("Name"),
                        "public_ip": inst.get("PublicIpAddress"),
                        "private_ip": inst.get("PrivateIpAddress"),
                        "availability_zone": (inst.get("Placement") or {}).get("AvailabilityZone"),
                        "launch_time": utc_iso(inst.get("LaunchTime")),
                        "ami_id": ami_id,
                        "ami_name": None,
                        "security_groups": [sg.get("GroupId") for sg in inst.get("SecurityGroups", [])],
                        "tags": {t.get("Key"): t.get("Value") for t in inst.get("Tags", [])} if inst.get("Tags") else {},
                    })
        names = _ami_names(list(ami_ids))
        for r in results:
            if r["ami_id"] in names: r["ami_name"] = names[r["ami_id"]]
        return results
    return try_once_retry_once(_run, on="EC2 instances") or out

# S3 Buckets
def collect_s3_buckets(s3_client) -> List[Dict[str, Any]]:
    out = []
    def _bucket_region(name): 
        try: return s3_client.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
        except ClientError: return "unknown"

    def _bucket_stats(name):
        count, total = 0, 0
        def _run():
            nonlocal count, total
            for page in s3_client.get_paginator("list_objects_v2").paginate(Bucket=name):
                for obj in page.get("Contents", []) or []:
                    count += 1; total += int(obj.get("Size", 0))
            return count, total
        return try_once_retry_once(_run, on=f"bucket {name}") or (0,0)

    def _run():
        results = []
        for b in s3_client.list_buckets().get("Buckets", []):
            count, size = _bucket_stats(b["Name"])
            results.append({
                "bucket_name": b["Name"],
                "creation_date": utc_iso(b.get("CreationDate")),
                "region": _bucket_region(b["Name"]),
                "object_count": count,
                "size_bytes": size,
            })
        return results
    return try_once_retry_once(_run, on="S3 buckets") or out

# Security Groups
def collect_security_groups(ec2_client) -> List[Dict[str, Any]]:
    out = []
    def _fmt(p): 
        if p.get("IpProtocol") in ("-1", "all"): return "all"
        return f"{p.get('FromPort')}-{p.get('ToPort')}" if p.get("FromPort")!=p.get("ToPort") else str(p.get("FromPort"))

    def _run():
        results = []
        for page in ec2_client.get_paginator("describe_security_groups").paginate():
            for g in page.get("SecurityGroups", []):
                inbound = [{"protocol": p.get("IpProtocol") if p.get("IpProtocol")!="-1" else "all","port_range": _fmt(p),"source": ", ".join([r.get("CidrIp") or "" for r in p.get("IpRanges", [])])} for p in g.get("IpPermissions", [])]
                outbound = [{"protocol": p.get("IpProtocol") if p.get("IpProtocol")!="-1" else "all","port_range": _fmt(p),"destination": ", ".join([r.get("CidrIp") or "" for r in p.get("IpRanges", [])])} for p in g.get("IpPermissionsEgress", [])]
                results.append({"group_id": g.get("GroupId"),"group_name": g.get("GroupName"),"description": g.get("Description"),"vpc_id": g.get("VpcId"),"inbound_rules": inbound,"outbound_rules": outbound})
        return results
    return try_once_retry_once(_run, on="security groups") or out

# Formatting
def to_json_blob(payload): return json.dumps(payload, indent=2)
def to_table(payload):
    acc, res, s = payload["account_info"], payload["resources"], payload["summary"]
    lines = [f"AWS Account: {acc['account_id']} ({acc['region']})",f"Scan Time: {acc['scan_timestamp']}",""]
    lines.append(f"IAM USERS ({s['total_users']} total)")
    for u in res["iam_users"]:
        lines.append(f"{u['username']} {u['create_date']} {u['last_activity'] or '-'}")
    return "\n".join(lines)

# Main
def build_boto3_clients(region):
    cfg = Config(retries={"max_attempts": 3,"mode": "standard"})
    return (boto3.client("sts", region_name=region, config=cfg),
            boto3.client("iam", region_name=region, config=cfg),
            boto3.client("ec2", region_name=region, config=cfg),
            boto3.client("s3", region_name=region, config=cfg),
            boto3.resource("ec2", region_name=region, config=cfg))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region"); parser.add_argument("--output")
    parser.add_argument("--format", choices=["json","table"], default="json")
    args = parser.parse_args()

    session = boto3.session.Session()
    region = validate_region_or_exit(session, args.region)
    sts, iam, ec2c, s3, ec2r = build_boto3_clients(args.region)

    account_id, user_arn = get_account_identity(sts)
    iam_users, ec2_instances = collect_iam_users(iam), collect_ec2_instances(ec2c, ec2r)
    s3_buckets, sec_groups = collect_s3_buckets(s3), collect_security_groups(ec2c)

    payload = {
        "account_info": {"account_id": account_id,"user_arn": user_arn,"region": region,"scan_timestamp": utc_iso(datetime.now(timezone.utc))},
        "resources": {"iam_users": iam_users,"ec2_instances": ec2_instances,"s3_buckets": s3_buckets,"security_groups": sec_groups},
        "summary": {"total_users": len(iam_users),"running_instances": sum(1 for i in ec2_instances if i.get("state")=="running"),"total_buckets": len(s3_buckets),"security_groups": len(sec_groups)},
    }

    out = to_json_blob(payload) if args.format=="json" else to_table(payload)
    write_or_print(out, args.output)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: sys.exit(130)
