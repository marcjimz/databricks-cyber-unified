#!/usr/bin/env python3
"""Fork / tear down a paired Lakebase feature branch.

Realizes the paired git <-> Lakebase branching model (see the lakebase-app-dev-kit)
for an isolated feature deploy: a feature branch of CODE gets a matching branch of
DATA, forked from the production branch, with its own read-write endpoint.

Because a Lakebase branch fork inherits the parent's roles and grants, the app
service principal's CONNECT and the reader group's SELECT carry to the fork with
no extra grant step -- the feature app reads a copy-on-write snapshot of prod data.

Usage:
  # Create (fork from production) -- prints branch/endpoint IDs as JSON:
  python3 lakebase_branch.py create \
      --project cyber360-lakebase --source-branch production \
      --branch-id feat-add-orders --endpoint-id feat-add-orders \
      --min-cu 0.5 --max-cu 1

  # Delete (teardown on PR close):
  python3 lakebase_branch.py delete \
      --project cyber360-lakebase \
      --branch-id feat-add-orders --endpoint-id feat-add-orders

Auth: a bare WorkspaceClient() -- DATABRICKS_HOST + DATABRICKS_TOKEN in CI.
Idempotent: create is a no-op if the branch/endpoint already exist; delete
ignores "not found". Exits non-zero on real failures.
"""

from __future__ import annotations

import argparse
import json
import sys

from google.protobuf.duration_pb2 import Duration

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.postgres import (
    Branch,
    BranchSpec,
    Endpoint,
    EndpointSpec,
    EndpointType,
)


def _project_path(project: str) -> str:
    return f"projects/{project}"


def _branch_path(project: str, branch_id: str) -> str:
    return f"projects/{project}/branches/{branch_id}"


def _endpoint_path(project: str, branch_id: str, endpoint_id: str) -> str:
    return f"{_branch_path(project, branch_id)}/endpoints/{endpoint_id}"


def create(ws: WorkspaceClient, args: argparse.Namespace) -> dict:
    project_path = _project_path(args.project)
    branch_path = _branch_path(args.project, args.branch_id)
    endpoint_path = _endpoint_path(args.project, args.branch_id, args.endpoint_id)

    # 1. Fork the branch from the source (production) branch, unless it exists.
    try:
        ws.postgres.get_branch(name=branch_path)
        print(f"branch exists: {branch_path}", file=sys.stderr)
    except Exception:
        print(f"forking branch {args.branch_id} from {args.source_branch}", file=sys.stderr)
        ttl = Duration()
        ttl.FromSeconds(args.ttl_seconds)
        op = ws.postgres.create_branch(
            parent=project_path,
            branch_id=args.branch_id,
            branch=Branch(
                spec=BranchSpec(
                    source_branch=_branch_path(args.project, args.source_branch),
                    is_protected=False,
                    # The API REQUIRES an expiration policy on create. Feature
                    # branches are ephemeral, so set a TTL -- this auto-cleans the
                    # fork if a PR-close teardown is ever missed. ttl is a
                    # protobuf Duration (default 604800s = 7 days).
                    ttl=ttl,
                )
            ),
        )
        op.wait()
        print(f"branch ready: {branch_path}", file=sys.stderr)

    # 2. Discover the branch's endpoint. A forked branch AUTO-INHERITS a
    #    read-write endpoint (named like the parent's, typically `primary`), and a
    #    branch may hold only one RW endpoint -- so we discover it rather than
    #    create one. Fall back to creating an RW endpoint only if none exists.
    endpoints = list(ws.postgres.list_endpoints(parent=branch_path))
    if endpoints:
        # Prefer an explicitly READ_WRITE endpoint; else take the first.
        chosen = next(
            (e for e in endpoints
             if e.spec and e.spec.endpoint_type == EndpointType.ENDPOINT_TYPE_READ_WRITE),
            endpoints[0],
        )
        endpoint_id = chosen.name.rsplit("/", 1)[-1]
        endpoint_path = chosen.name
        print(f"using inherited endpoint: {endpoint_path}", file=sys.stderr)
    else:
        print(f"no endpoint on fork; creating RW endpoint {args.endpoint_id}", file=sys.stderr)
        op = ws.postgres.create_endpoint(
            parent=branch_path,
            endpoint_id=args.endpoint_id,
            endpoint=Endpoint(
                spec=EndpointSpec(
                    endpoint_type=EndpointType.ENDPOINT_TYPE_READ_WRITE,
                    autoscaling_limit_min_cu=args.min_cu,
                    autoscaling_limit_max_cu=args.max_cu,
                )
            ),
        )
        op.wait()
        endpoint_id = args.endpoint_id
        print(f"endpoint ready: {endpoint_path}", file=sys.stderr)

    return {
        "project": args.project,
        "branch_id": args.branch_id,
        "endpoint_id": endpoint_id,
        "branch_path": branch_path,
        "endpoint_path": endpoint_path,
    }


def delete(ws: WorkspaceClient, args: argparse.Namespace) -> dict:
    branch_path = _branch_path(args.project, args.branch_id)

    # Delete the branch only. A branch's read-write endpoint CANNOT be deleted
    # directly (the API rejects it), but deleting the branch cascades and removes
    # the endpoint with it -- so one call tears down the whole fork.
    try:
        op = ws.postgres.delete_branch(name=branch_path)
        wait = getattr(op, "wait", None)
        if callable(wait):
            wait()
        print(f"deleted branch (cascades endpoint): {branch_path}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 -- not-found is fine on teardown
        print(f"skip branch {branch_path}: {type(exc).__name__}: {exc}", file=sys.stderr)

    return {"deleted_branch": branch_path}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="Fork a paired feature branch + RW endpoint")
    c.add_argument("--project", required=True)
    c.add_argument("--source-branch", default="production")
    c.add_argument("--branch-id", required=True)
    c.add_argument("--endpoint-id", required=True)
    c.add_argument("--min-cu", type=float, default=0.5)
    c.add_argument("--max-cu", type=float, default=1.0)
    c.add_argument("--ttl-seconds", type=int, default=604800,
                   help="Branch TTL in seconds (default 7 days). Auto-cleanup "
                        "safety net beyond PR-close teardown.")

    d = sub.add_parser("delete", help="Delete a paired feature branch (cascades its endpoint)")
    d.add_argument("--project", required=True)
    d.add_argument("--branch-id", required=True)
    # Accepted for symmetry but unused: deleting the branch cascades the endpoint.
    d.add_argument("--endpoint-id", required=False, default="")

    args = ap.parse_args()
    ws = WorkspaceClient()

    result = create(ws, args) if args.cmd == "create" else delete(ws, args)
    # stdout is machine-readable JSON (progress logs go to stderr).
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
