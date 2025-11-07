# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import boto3
import pytest
import re
import gzip
from conftest import SKIP_REASON, TEST_REGIONS, logging


logger = logging.getLogger(__name__)


@pytest.fixture
def s3_client():
    session = boto3.Session(
        region_name=os.environ["TEST_AWS_REGION"],
        profile_name=os.environ["TEST_AWS_PROFILE"]
    )
    return session.client('s3')

def check_bucket_for_log_files(s3_client, bucket_name, expected_contents):
    """Check if bucket contains .log.gz files with expected content and log pattern"""
    
    paginator = s3_client.get_paginator('list_objects_v2')
    
    # Pattern to match the log format
    log_pattern = r'{"timestamp":"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{4}", "level":"[A-Z]+", "logger":"[^"]+", "thread":"[^"]+", "message":.+, "containerId":"[^"]+"}'
    
    for page in paginator.paginate(Bucket=bucket_name):
        if 'Contents' not in page:
            continue
            
        for obj in page['Contents']:
            if any(obj['Key'].endswith(f'.{i}.log.gz') for i in range(10)) and obj['Size'] > 0:
                
                # Download and check content
                response = s3_client.get_object(Bucket=bucket_name, Key=obj['Key'])
                with gzip.open(response['Body'], 'rt') as f:
                    content = f.read()
                    if all(expected in content for expected in expected_contents) and re.search(log_pattern, content):
                        logger.info(f"Found log file: s3://{bucket_name}/{obj['Key']}")
                        logger.debug(content)
                        return True
    return False


@pytest.mark.skipif(
    os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
    reason=SKIP_REASON
)
@pytest.mark.skipif(
    not (os.environ.get("AMT_ADAPTER_ENABLED") and 
    os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT")),
    reason="Metrics test runs with amt adapter enabled."
)
@pytest.mark.order(after="test_prebid_auction.py::test_auction_request")
def test_metrics_bucket_has_data(s3_client):
    """Test that METRICS_BUCKET contains log files with metrics data"""
    bucket_name = os.environ['METRICS_BUCKET']
    expected_contents = ['"logger":"METRICS"', 'type=TIMER', 'type=COUNTER', 'type=METER', 'type=HISTOGRAM']
    assert check_bucket_for_log_files(s3_client, bucket_name, expected_contents)


@pytest.mark.skipif(
    os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
    reason=SKIP_REASON
)
@pytest.mark.skipif(
    not (os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT") and
    os.environ.get("LOG_ANALYTICS_ENABLED")),
    reason="Analytic test runs with analytics logs reporter enabled."
)
@pytest.mark.order(after="test_prebid_auction.py::test_auction_request")
def test_analytics_bucket_has_data(s3_client):
    """Test that ANALYTICS_BUCKET contains log files with analytics data"""
    bucket_name = os.environ['ANALYTICS_BUCKET']
    expected_contents = ['"type":"/openrtb2/auction"', '"userAgent"', '"bidRequest"', '"bidResponse"', '"headers"', '"cacheId":']
    assert check_bucket_for_log_files(s3_client, bucket_name, expected_contents)
