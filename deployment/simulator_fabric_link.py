#!/usr/bin/env python3
"""
simulator_fabric_link.py — Manages RTB Fabric Link lifecycle for the Bidder Simulator.

Usage:
    simulator_fabric_link.py <subcommand> [options]

Subcommands:
    create    Create a Fabric Link and wait for it to become active
    delete    Delete an existing Fabric Link
    status    Check the status of the current Fabric Link

Options:
    --stack-name NAME              PrebidServerStack name (required)
    --responder-gateway-id ID      Responder Gateway ID (required for create)
    --profile PROFILE              AWS CLI profile
    --region REGION                AWS region

Exit Codes:
    0    Success
    1    General error (API failure, timeout, invalid arguments)
"""

import argparse
import copy
import json
import subprocess
import sys
import time

import boto3
from botocore.exceptions import ClientError


# --- Configuration ---
INITIAL_INTERVAL = 5       # seconds
MULTIPLIER = 2             # doubling factor
MAX_INTERVAL = 30          # seconds (cap)
TOTAL_TIMEOUT = 600        # seconds (10 minutes)

LOG_SETTINGS = {"applicationLogs": {"sampling": {"errorLog": 0.0, "filterLog": 0.0}}}

# Fields accepted by register-task-definition (strip everything else)
REGISTER_TASK_DEF_KEYS = [
    "family", "taskRoleArn", "executionRoleArn", "networkMode",
    "containerDefinitions", "volumes", "placementConstraints",
    "requiresCompatibilities", "cpu", "memory", "pidMode", "ipcMode",
    "proxyConfiguration", "inferenceAccelerators", "ephemeralStorage",
    "runtimePlatform",
]


# --- Logging ---
def info(msg: str):
    print(f"INFO: {msg}", file=sys.stderr)


def error(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)


# --- Backoff ---
def backoff_interval(attempt: int) -> int:
    return min(INITIAL_INTERVAL * (MULTIPLIER ** attempt), MAX_INTERVAL)


# Number of CONSECUTIVE None (link-not-found) polls tolerated before treating
# the link as gone, when terminal_on_none is set (create path only). A single
# None is normal early in create (the link has not appeared in list-links yet),
# so we only fail fast once None persists across this many polls.
NONE_GRACE_POLLS = 3


def poll_until(
    check_fn,
    success_states: set,
    failure_states: set,
    label: str,
    terminal_on_none: bool = False,
) -> str:
    """Poll check_fn() until status is in success_states or timeout.

    When terminal_on_none is True (used on the create path, where the link is
    expected to exist and progress toward ACTIVE), a status of None means the
    link was not found. A single None is tolerated as a normal early-create
    transient, but None persisting for NONE_GRACE_POLLS consecutive polls is
    treated as a terminal failure (the link disappeared / was deleted out from
    under us) so we fail fast instead of hanging for the full TOTAL_TIMEOUT.

    The delete path leaves terminal_on_none False and maps None -> "DELETED" in
    its check_fn, so this guard does not affect deletion.
    """
    elapsed = 0
    attempt = 0
    consecutive_none = 0
    while elapsed < TOTAL_TIMEOUT:
        status = check_fn()
        interval = backoff_interval(attempt)
        info(f"  {label} attempt {attempt}: status={status} (elapsed={elapsed}s, next poll in {interval}s)")
        if status in success_states:
            return status
        if status in failure_states:
            error(f"Link entered {status} state")
            sys.exit(1)
        if terminal_on_none and status is None:
            consecutive_none += 1
            if consecutive_none >= NONE_GRACE_POLLS:
                error(
                    f"Link not found for {consecutive_none} consecutive polls "
                    f"(status=None); it appears to have been deleted. Failing fast."
                )
                sys.exit(1)
        else:
            consecutive_none = 0
        time.sleep(interval)
        elapsed += interval
        attempt += 1
    error(f"Timeout after {TOTAL_TIMEOUT}s. Last status: {status}")
    sys.exit(1)


# --- AWS Client Factory ---
def create_session(profile: str = None, region: str = None) -> boto3.Session:
    kwargs = {}
    if profile:
        kwargs["profile_name"] = profile
    if region:
        kwargs["region_name"] = region
    return boto3.Session(**kwargs)


# --- Stack Helpers ---
def get_stack_outputs(cf_client, stack_name: str) -> dict:
    """Returns {OutputKey: OutputValue} dict from stack outputs."""
    resp = cf_client.describe_stacks(StackName=stack_name)
    outputs = resp["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def get_stack_output(cf_client, stack_name: str, key: str) -> str:
    outputs = get_stack_outputs(cf_client, stack_name)
    if key not in outputs:
        error(f"{key} not found in stack outputs for {stack_name}")
        sys.exit(1)
    return outputs[key]


# --- SSM Helpers ---
def ssm_get_link_id(ssm_client, param_path: str) -> str | None:
    """Returns link ID from SSM or None if not found."""
    try:
        resp = ssm_client.get_parameter(Name=param_path)
        value = resp["Parameter"]["Value"]
        return value if value and value != "None" else None
    except ClientError as e:
        if e.response["Error"]["Code"] == "ParameterNotFound":
            return None
        raise


def ssm_put_link_id(ssm_client, param_path: str, link_id: str):
    ssm_client.put_parameter(Name=param_path, Value=link_id, Type="String", Overwrite=True)


def ssm_delete_link_id(ssm_client, param_path: str):
    try:
        ssm_client.delete_parameter(Name=param_path)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ParameterNotFound":
            return
        raise


# --- RTB Fabric Helpers (via AWS CLI — not in boto3 SDK) ---
_aws_cli_base_args = []  # populated by main() with --profile/--region


def _aws_cli(service: str, command: list, parse_json=True):
    """Run an AWS CLI command and return parsed JSON or raw output."""
    cmd = ["aws", service] + command + _aws_cli_base_args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    if parse_json and result.stdout.strip():
        return json.loads(result.stdout)
    return result.stdout.strip()


def get_link_status(gateway_id: str, link_id: str) -> str | None:
    """Returns link status or None if not found."""
    try:
        resp = _aws_cli("rtbfabric", ["list-links", "--gateway-id", gateway_id, "--output", "json"])
        for link in resp.get("links", []):
            if link["linkId"] == link_id:
                return link["status"]
        return None  # Link not in list
    except RuntimeError as e:
        if "not found" in str(e).lower() or "resourcenotfound" in str(e).lower():
            return None
        raise  # Re-raise unexpected errors (permissions, throttling, network)


def get_gateway_domain(gateway_id: str) -> str:
    resp = _aws_cli("rtbfabric", ["get-requester-gateway", "--gateway-id", gateway_id, "--output", "json"])
    return resp["domainName"]


def find_orphan_link(gateway_id: str, peer_gateway_id: str) -> tuple[str, str] | None:
    """Find an existing link to the same peer gateway in a resumable state."""
    resumable = {"PENDING_CREATION", "PENDING_REQUEST", "REQUESTED", "ACCEPTED", "ACTIVE"}
    try:
        resp = _aws_cli("rtbfabric", ["list-links", "--gateway-id", gateway_id, "--output", "json"])
        for link in resp.get("links", []):
            if link["peerGatewayId"] == peer_gateway_id and link["status"] in resumable:
                return link["linkId"], link["status"]
        return None  # No matching link found
    except RuntimeError as e:
        if "not found" in str(e).lower() or "resourcenotfound" in str(e).lower():
            return None
        raise  # Re-raise unexpected errors (permissions, throttling, network)


def create_link(gateway_id: str, peer_gateway_id: str) -> tuple[str, str]:
    """Create a link and return (link_id, status)."""
    resp = _aws_cli("rtbfabric", [
        "create-link",
        "--gateway-id", gateway_id,
        "--peer-gateway-id", peer_gateway_id,
        "--log-settings", json.dumps(LOG_SETTINGS),
        "--output", "json",
    ])
    return resp["linkId"], resp.get("status", "PENDING_CREATION")


def accept_link(gateway_id: str, link_id: str):
    """Accept a link from the responder side."""
    _aws_cli("rtbfabric", [
        "accept-link",
        "--gateway-id", gateway_id,
        "--link-id", link_id,
        "--log-settings", json.dumps(LOG_SETTINGS),
    ])


def delete_link(gateway_id: str, link_id: str):
    """Delete a link. Raises RuntimeError on failure."""
    _aws_cli("rtbfabric", [
        "delete-link",
        "--gateway-id", gateway_id,
        "--link-id", link_id,
    ])


def get_link_details(gateway_id: str, link_id: str) -> dict:
    """Get full link details."""
    return _aws_cli("rtbfabric", [
        "get-link",
        "--gateway-id", gateway_id,
        "--link-id", link_id,
        "--output", "json",
    ])


# --- ECS Helpers ---
def get_current_task_def_arn(ecs_client, cluster: str, service: str) -> str:
    resp = ecs_client.describe_services(cluster=cluster, services=[service])
    return resp["services"][0]["taskDefinition"]


def get_task_def_endpoint(ecs_client, task_def_arn: str) -> str:
    """Get current AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT from task def."""
    resp = ecs_client.describe_task_definition(taskDefinition=task_def_arn)
    task_def = resp["taskDefinition"]
    for container in task_def.get("containerDefinitions", []):
        for env in container.get("environment", []):
            if env["name"] == "AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT":
                return env["value"]
    return ""


def update_ecs_task_and_service(ecs_client, cluster: str, service: str, task_def_arn: str, link_url: str) -> str:
    """Register new task def revision with link URL and update service. Returns new ARN."""
    resp = ecs_client.describe_task_definition(taskDefinition=task_def_arn)
    task_def = resp["taskDefinition"]

    # Update environment variables
    for container in task_def.get("containerDefinitions", []):
        env_vars = container.get("environment", [])
        endpoint_found = adapter_found = False
        for env in env_vars:
            if env["name"] == "AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT":
                env["value"] = link_url
                endpoint_found = True
            if env["name"] == "AMT_ADAPTER_ENABLED":
                env["value"] = "true"
                adapter_found = True
        if not endpoint_found:
            env_vars.append({"name": "AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT", "value": link_url})
        if not adapter_found:
            env_vars.append({"name": "AMT_ADAPTER_ENABLED", "value": "true"})
        container["environment"] = env_vars

    # Build register input (only accepted fields)
    register_input = {k: task_def[k] for k in REGISTER_TASK_DEF_KEYS if k in task_def}

    # Register new revision
    reg_resp = ecs_client.register_task_definition(**register_input)
    new_arn = reg_resp["taskDefinition"]["taskDefinitionArn"]
    info(f"Registered new task definition: {new_arn}")

    # Update service
    ecs_client.update_service(cluster=cluster, service=service, taskDefinition=new_arn)
    info("ECS service updated — rolling deployment triggered")
    return new_arn


# --- Subcommands ---

def do_create(args):
    session = create_session(args.profile, args.region)
    cf_client = session.client("cloudformation")
    ssm_client = session.client("ssm")
    ecs_client = session.client("ecs")

    ssm_param_path = f"/{args.stack_name}/fabric-link/link-id"

    # Step 1: Get stack outputs
    info(f"Retrieving stack outputs from {args.stack_name}...")
    outputs = get_stack_outputs(cf_client, args.stack_name)

    requester_gw_id = outputs.get("RequesterGatewayId")
    ecs_cluster = outputs.get("EcsClusterName")
    ecs_service = outputs.get("EcsServiceName")

    if not requester_gw_id:
        error("RequesterGatewayId not found in stack outputs")
        sys.exit(1)
    if not ecs_cluster:
        error("EcsClusterName not found in stack outputs")
        sys.exit(1)
    if not ecs_service:
        error("EcsServiceName not found in stack outputs")
        sys.exit(1)

    info(f"Requester Gateway ID: {requester_gw_id}")
    info(f"ECS Cluster: {ecs_cluster}")
    info(f"ECS Service: {ecs_service}")

    # Step 2: Check for existing link (idempotent)
    info("Checking for existing Fabric Link...")
    link_id = ssm_get_link_id(ssm_client, ssm_param_path)
    link_status = None

    if link_id:
        info(f"Found existing link ID in SSM: {link_id}")
        link_status = get_link_status(requester_gw_id, link_id)
        info(f"  Existing link status: {link_status or 'NOT_FOUND'}")

        if link_status in (None, "DELETED", "PENDING_DELETION"):
            info(f"Existing link is gone ({link_status}). Cleaning up SSM and creating new link.")
            ssm_delete_link_id(ssm_client, ssm_param_path)
            link_id = None
            link_status = None
        elif link_status in ("FAILED", "REJECTED"):
            info(f"Existing link in {link_status} state. Cleaning up SSM and creating new link.")
            ssm_delete_link_id(ssm_client, ssm_param_path)
            link_id = None
            link_status = None
        else:
            info(f"Resuming with existing link (status: {link_status})")

    # Check for orphaned links if no link found
    if not link_id:
        orphan = find_orphan_link(requester_gw_id, args.responder_gateway_id)
        if orphan:
            link_id, link_status = orphan
            info(f"Found orphaned link to same responder: {link_id} (status: {link_status})")

    # Step 3: Create link if needed
    if not link_id:
        info("Creating Fabric Link...")
        info(f"  Requester Gateway: {requester_gw_id}")
        info(f"  Responder Gateway: {args.responder_gateway_id}")
        link_id, link_status = create_link(requester_gw_id, args.responder_gateway_id)
        info(f"Fabric Link created: {link_id}")

    # Step 4: Poll until REQUESTED (skip if already ACTIVE)
    if link_status != "ACTIVE":
        if link_status not in ("REQUESTED", "ACCEPTED"):
            info("Waiting for Fabric Link to reach REQUESTED state...")
            info("  (States: PENDING_CREATION → PENDING_REQUEST → REQUESTED)")

            def check_status():
                return get_link_status(requester_gw_id, link_id)

            link_status = poll_until(
                check_status,
                success_states={"REQUESTED", "ACCEPTED", "ACTIVE"},
                # create path: a link that vanishes mid-poll should fail fast.
                failure_states={"FAILED", "REJECTED"},
                label="Poll",
                terminal_on_none=True,
            )

        # Step 5: Accept the link (skip if already ACCEPTED/ACTIVE)
        if link_status == "REQUESTED":
            info("Accepting Fabric Link from responder side...")
            time.sleep(5)  # Brief pause for propagation
            accept_link(args.responder_gateway_id, link_id)
            info("Fabric Link accepted")

        # Poll until ACTIVE
        if link_status != "ACTIVE":
            info("Waiting for link to transition to ACTIVE...")

            def check_active():
                return get_link_status(requester_gw_id, link_id)

            link_status = poll_until(
                check_active,
                success_states={"ACTIVE"},
                # create path: a link that vanishes mid-poll should fail fast.
                failure_states={"FAILED", "REJECTED"},
                label="Post-accept",
                terminal_on_none=True,
            )

    info("Fabric Link is ACTIVE")

    # Step 6: Store link ID in SSM
    info(f"Storing Link ID in SSM: {ssm_param_path}")
    ssm_put_link_id(ssm_client, ssm_param_path, link_id)

    # Step 7: Get gateway domain and construct URL
    info("Retrieving requester gateway domain...")
    domain = get_gateway_domain(requester_gw_id)
    link_url = f"https://{domain}/link/{link_id}"
    info(f"Link URL: {link_url}")

    # Step 8: Update ECS task definition (idempotent)
    info("Checking ECS task definition...")
    task_def_arn = get_current_task_def_arn(ecs_client, ecs_cluster, ecs_service)
    info(f"Current task definition: {task_def_arn}")

    current_endpoint = get_task_def_endpoint(ecs_client, task_def_arn)
    if current_endpoint == link_url:
        info("ECS task definition already has the correct Link URL. Skipping update.")
    else:
        info(f"Current endpoint: '{current_endpoint}' → updating to: '{link_url}'")
        update_ecs_task_and_service(ecs_client, ecs_cluster, ecs_service, task_def_arn, link_url)

    # Output URL to stdout
    print(link_url)


def do_delete(args):
    session = create_session(args.profile, args.region)
    cf_client = session.client("cloudformation")
    ssm_client = session.client("ssm")

    ssm_param_path = f"/{args.stack_name}/fabric-link/link-id"

    # Step 1: Read link ID from SSM
    link_id = ssm_get_link_id(ssm_client, ssm_param_path)
    if not link_id:
        info("No Fabric Link found (SSM parameter does not exist). Nothing to delete.")
        return

    info(f"Found Fabric Link: {link_id}")

    # Step 2: Get requester gateway ID
    try:
        req_gw_id = get_stack_output(cf_client, args.stack_name, "RequesterGatewayId")
    except SystemExit:
        info("Cannot retrieve RequesterGatewayId (stack may be deleted). Cleaning up SSM only.")
        ssm_delete_link_id(ssm_client, ssm_param_path)
        info("Delete complete.")
        return

    # Step 3: Check current status
    current_status = get_link_status(req_gw_id, link_id)
    info(f"Current link status: {current_status or 'NOT_FOUND'}")

    if current_status in (None, "DELETED"):
        info(f"Fabric Link {link_id} is already deleted. Cleaning up SSM parameter.")
        ssm_delete_link_id(ssm_client, ssm_param_path)
        info("Delete complete.")
        return

    # Step 4: Call delete-link (skip if already PENDING_DELETION)
    if current_status != "PENDING_DELETION":
        info(f"Deleting Fabric Link {link_id}...")
        try:
            delete_link(req_gw_id, link_id)
            info("Delete-link API call succeeded.")
        except RuntimeError as e:
            msg = str(e).lower()
            if "not found" in msg or "resourcenotfoundexception" in msg:
                info(f"Fabric Link {link_id} already deleted (not found). Cleaning up SSM.")
                ssm_delete_link_id(ssm_client, ssm_param_path)
                info("Delete complete.")
                return
            elif "pending_deletion" in msg or "conflictexception" in msg:
                info("Link is already being deleted. Waiting for completion...")
            else:
                error(f"Failed to delete Fabric Link: {e}")
                sys.exit(1)
    else:
        info("Link is already in PENDING_DELETION state. Waiting for completion...")

    # Step 5: Poll until DELETED
    info("Polling until link reaches DELETED state...")
    info("  (States: PENDING_DELETION → DELETED)")

    def check_deleted():
        status = get_link_status(req_gw_id, link_id)
        return status if status else "DELETED"

    poll_until(
        check_deleted,
        success_states={"DELETED"},
        failure_states=set(),
        label="Delete",
    )

    # Step 6: Clean up SSM
    info("Cleaning up SSM parameter...")
    ssm_delete_link_id(ssm_client, ssm_param_path)
    info("Delete complete.")


def do_status(args):
    session = create_session(args.profile, args.region)
    cf_client = session.client("cloudformation")
    ssm_client = session.client("ssm")

    ssm_param_path = f"/{args.stack_name}/fabric-link/link-id"

    # Read link ID
    link_id = ssm_get_link_id(ssm_client, ssm_param_path)
    if not link_id:
        info(f"No Fabric Link configured for stack '{args.stack_name}'")
        return

    # Get gateway ID
    try:
        req_gw_id = get_stack_output(cf_client, args.stack_name, "RequesterGatewayId")
    except SystemExit:
        info("Cannot retrieve RequesterGatewayId from stack outputs")
        return

    # Get link details
    try:
        resp = get_link_details(req_gw_id, link_id)
    except RuntimeError as e:
        error(f"Failed to describe Fabric Link '{link_id}': {e}")
        sys.exit(1)

    status = resp.get("status", "UNKNOWN")
    gateway_id = resp.get("gatewayId", "N/A")
    peer_gateway_id = resp.get("peerGatewayId", "N/A")

    info("Fabric Link Status:")
    info(f"  Link ID:                {link_id}")
    info(f"  Status:                 {status}")
    info(f"  Requester Gateway ID:   {gateway_id}")
    info(f"  Responder Gateway ID:   {peer_gateway_id}")

    if status == "ACTIVE":
        domain = get_gateway_domain(gateway_id)
        link_url = f"https://{domain}/link/{link_id}"
        info(f"  Link URL:               {link_url}")


# --- Main ---
def main():
    parser = argparse.ArgumentParser(
        description="Manage RTB Fabric Link lifecycle for the Bidder Simulator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Common options
    def add_common_args(p):
        p.add_argument("--stack-name", required=True, help="PrebidServerStack name")
        p.add_argument("--profile", default=None, help="AWS CLI profile")
        p.add_argument("--region", default=None, help="AWS region")

    # create
    create_parser = subparsers.add_parser("create", help="Create a Fabric Link")
    add_common_args(create_parser)
    create_parser.add_argument("--responder-gateway-id", required=True, help="Responder Gateway ID")

    # delete
    delete_parser = subparsers.add_parser("delete", help="Delete a Fabric Link")
    add_common_args(delete_parser)

    # status
    status_parser = subparsers.add_parser("status", help="Check Fabric Link status")
    add_common_args(status_parser)

    args = parser.parse_args()

    # Set up AWS CLI base args for rtbfabric calls
    global _aws_cli_base_args
    _aws_cli_base_args = []
    if args.profile:
        _aws_cli_base_args += ["--profile", args.profile]
    if args.region:
        _aws_cli_base_args += ["--region", args.region]

    try:
        if args.subcommand == "create":
            do_create(args)
        elif args.subcommand == "delete":
            do_delete(args)
        elif args.subcommand == "status":
            do_status(args)
    except ClientError as e:
        error(f"AWS API error: {e.response['Error']['Code']} - {e.response['Error']['Message']}")
        sys.exit(1)
    except Exception as e:
        error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
