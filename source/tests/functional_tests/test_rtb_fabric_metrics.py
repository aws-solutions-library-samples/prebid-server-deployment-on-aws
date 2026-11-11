# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import datetime
import boto3
import pytest
from botocore.exceptions import ClientError
from conftest import SKIP_REASON, TEST_REGIONS, logging


logger = logging.getLogger(__name__)

RTB_FABRIC_NAMESPACE = "AWS/RTBFabric"

# Configurable thresholds (env overridable)
LOOKBACK_HOURS = int(os.environ.get("RTB_METRICS_LOOKBACK_HOURS", "6"))
MIN_SUCCESS_RATE = float(os.environ.get("RTB_MIN_SUCCESS_RATE", "0.95"))
MAX_AVG_LATENCY_MS = float(os.environ.get("RTB_MAX_AVG_LATENCY_MS", "60000"))

# HttpStatusCode dimension value for a 2xx response, as emitted by RTB Fabric.
STATUS_200_DIMENSION = "200 OK"


@pytest.fixture
def cloudwatch_client():
    session = boto3.Session(
        region_name=os.environ["TEST_AWS_REGION"],
        profile_name=os.environ["TEST_AWS_PROFILE"]
    )
    return session.client('cloudwatch')


@pytest.fixture
def ssm_client():
    session = boto3.Session(
        region_name=os.environ["TEST_AWS_REGION"],
        profile_name=os.environ["TEST_AWS_PROFILE"]
    )
    return session.client('ssm')


def _stack_name():
    # PREBID_STACK_NAME is preferred because the suite's pytest.ini reserves
    # (and overrides) STACK_NAME via pytest-env. Fall back to STACK_NAME, then
    # the documented default.
    return (
        os.environ.get("PREBID_STACK_NAME")
        or os.environ.get("STACK_NAME")
        or "prebid-server-deployment-on-aws"
    )


def resolve_link_id(ssm_client):
    """Resolve the RTB Fabric link id from SSM.

    Mirrors deployment/simulator_fabric_link.py:ssm_get_link_id. Reads the
    param at /{stack_name}/fabric-link/link-id. If the param is absent the
    stack was not deployed with RTB Fabric, so the caller should cleanly skip.
    """
    param_path = f"/{_stack_name()}/fabric-link/link-id"
    try:
        resp = ssm_client.get_parameter(Name=param_path)
        value = resp["Parameter"]["Value"]
        link_id = value if value and value != "None" else None
    except ClientError as e:
        if e.response["Error"]["Code"] == "ParameterNotFound":
            link_id = None
        else:
            raise

    if not link_id:
        pytest.skip(
            "RTB Fabric link not configured (SSM param missing) — "
            "stack not deployed with RTB Fabric"
        )
    logger.info(f"Resolved RTB Fabric link id from SSM ({param_path}): {link_id}")
    return link_id


def _window():
    """Return (start, end, period_seconds) for the lookback window."""
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=LOOKBACK_HOURS)
    period = LOOKBACK_HOURS * 3600
    return start, end, period


def sum_count_metric(cloudwatch_client, metric_name, dimensions):
    """Sum a Count metric over the lookback window.

    RTB Fabric Count metrics are emitted as multiple datapoints per minute, so
    Sum is required for true volume. We sum all datapoints in the window.
    """
    start, end, period = _window()
    resp = cloudwatch_client.get_metric_statistics(
        Namespace=RTB_FABRIC_NAMESPACE,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start,
        EndTime=end,
        Period=period,
        Statistics=["Sum"],
    )
    return sum(dp["Sum"] for dp in resp.get("Datapoints", []))


def average_latency_us(cloudwatch_client, metric_name, dimensions):
    """Return the average of a latency metric (in MICROSECONDS) over the window.

    RTB Fabric latency metrics are published in microseconds. Returns None if
    no datapoints are present.
    """
    start, end, period = _window()
    resp = cloudwatch_client.get_metric_statistics(
        Namespace=RTB_FABRIC_NAMESPACE,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start,
        EndTime=end,
        Period=period,
        Statistics=["Average"],
    )
    datapoints = resp.get("Datapoints", [])
    if not datapoints:
        return None
    return sum(dp["Average"] for dp in datapoints) / len(datapoints)


def resolve_status_200_dimension_value(cloudwatch_client, link_id):
    """Confirm the exact HttpStatusCode dimension value for a 2xx response.

    Defaults to "200 OK" but discovers the real value via list_metrics if the
    default is not present, picking the first 2xx code found.
    """
    paginator = cloudwatch_client.get_paginator("list_metrics")
    found_codes = []
    for page in paginator.paginate(
        Namespace=RTB_FABRIC_NAMESPACE,
        MetricName="request-status-count",
        Dimensions=[{"Name": "Link", "Value": link_id}],
    ):
        for metric in page.get("Metrics", []):
            for dim in metric.get("Dimensions", []):
                if dim["Name"] == "HttpStatusCode":
                    found_codes.append(dim["Value"])

    if STATUS_200_DIMENSION in found_codes:
        return STATUS_200_DIMENSION

    for code in found_codes:
        if code.strip().startswith("2"):
            logger.info(f"Discovered 2xx HttpStatusCode dimension value: {code}")
            return code

    # Fall back to the documented default; the assertion will surface absence.
    logger.info(
        f"No 2xx HttpStatusCode dimension discovered (found: {found_codes}); "
        f"falling back to '{STATUS_200_DIMENSION}'"
    )
    return STATUS_200_DIMENSION


@pytest.mark.skipif(
    os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
    reason=SKIP_REASON
)
@pytest.mark.skipif(
    not (os.environ.get("AMT_ADAPTER_ENABLED") and
    os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT")),
    reason="RTB Fabric metrics test runs with amt adapter enabled."
)
@pytest.mark.run(order=6)
def test_fabric_link_received_requests(cloudwatch_client, ssm_client):
    """The Fabric link carried traffic: total-request-count Sum > 0."""
    link_id = resolve_link_id(ssm_client)
    dimensions = [{"Name": "Link", "Value": link_id}]
    total = sum_count_metric(cloudwatch_client, "total-request-count", dimensions)
    logger.info(
        f"RTB Fabric total-request-count (Sum over {LOOKBACK_HOURS}h) "
        f"for link {link_id}: {total}"
    )
    assert total > 0, (
        f"No traffic recorded on RTB Fabric link {link_id} in the last "
        f"{LOOKBACK_HOURS}h. Run the functional suite or a DLT load test first."
    )


@pytest.mark.skipif(
    os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
    reason=SKIP_REASON
)
@pytest.mark.skipif(
    not (os.environ.get("AMT_ADAPTER_ENABLED") and
    os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT")),
    reason="RTB Fabric metrics test runs with amt adapter enabled."
)
@pytest.mark.run(order=6)
def test_fabric_link_success_rate(cloudwatch_client, ssm_client):
    """success-request-count > 0 and success rate >= threshold."""
    link_id = resolve_link_id(ssm_client)
    dimensions = [{"Name": "Link", "Value": link_id}]
    success = sum_count_metric(cloudwatch_client, "success-request-count", dimensions)
    failure = sum_count_metric(cloudwatch_client, "failure-request-count", dimensions)
    total = success + failure
    rate = (success / total) if total > 0 else 0.0
    logger.info(
        f"RTB Fabric link {link_id}: success={success}, failure={failure}, "
        f"success_rate={rate:.4f} (min required {MIN_SUCCESS_RATE})"
    )
    assert success > 0, (
        f"No successful requests recorded on RTB Fabric link {link_id} in the "
        f"last {LOOKBACK_HOURS}h."
    )
    assert rate >= MIN_SUCCESS_RATE, (
        f"RTB Fabric link {link_id} success rate {rate:.4f} is below the "
        f"minimum threshold {MIN_SUCCESS_RATE}."
    )


@pytest.mark.skipif(
    os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
    reason=SKIP_REASON
)
@pytest.mark.skipif(
    not (os.environ.get("AMT_ADAPTER_ENABLED") and
    os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT")),
    reason="RTB Fabric metrics test runs with amt adapter enabled."
)
@pytest.mark.run(order=6)
def test_fabric_link_status_200(cloudwatch_client, ssm_client):
    """request-status-count for a 2xx response Sum > 0."""
    link_id = resolve_link_id(ssm_client)
    status_value = resolve_status_200_dimension_value(cloudwatch_client, link_id)
    dimensions = [
        {"Name": "HttpStatusCode", "Value": status_value},
        {"Name": "Link", "Value": link_id},
    ]
    count = sum_count_metric(cloudwatch_client, "request-status-count", dimensions)
    logger.info(
        f"RTB Fabric link {link_id}: request-status-count "
        f"(HttpStatusCode={status_value}) Sum over {LOOKBACK_HOURS}h = {count}"
    )
    assert count > 0, (
        f"No {status_value} responses recorded on RTB Fabric link {link_id} in "
        f"the last {LOOKBACK_HOURS}h."
    )


@pytest.mark.skipif(
    os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
    reason=SKIP_REASON
)
@pytest.mark.skipif(
    not (os.environ.get("AMT_ADAPTER_ENABLED") and
    os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT")),
    reason="RTB Fabric metrics test runs with amt adapter enabled."
)
@pytest.mark.run(order=6)
def test_fabric_link_latency_healthy(cloudwatch_client, ssm_client):
    """total-latency is published and within a sane ceiling (units: microseconds)."""
    link_id = resolve_link_id(ssm_client)
    dimensions = [{"Name": "Link", "Value": link_id}]
    avg_us = average_latency_us(cloudwatch_client, "total-latency", dimensions)
    assert avg_us is not None, (
        f"No total-latency datapoints recorded on RTB Fabric link {link_id} in "
        f"the last {LOOKBACK_HOURS}h."
    )
    avg_ms = avg_us / 1000.0
    logger.info(
        f"RTB Fabric link {link_id}: total-latency avg = {avg_ms:.2f} ms "
        f"({avg_us:.0f} us) over {LOOKBACK_HOURS}h (ceiling {MAX_AVG_LATENCY_MS} ms)"
    )
    assert 0 < avg_ms < MAX_AVG_LATENCY_MS, (
        f"RTB Fabric link {link_id} average latency {avg_ms:.2f} ms is outside "
        f"the sane range (0, {MAX_AVG_LATENCY_MS} ms)."
    )
