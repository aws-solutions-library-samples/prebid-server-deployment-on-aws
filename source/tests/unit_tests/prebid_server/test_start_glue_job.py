# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for infrastructure/prebid_server/glue_trigger_lambda/start_glue_job.py.
# USAGE:
#   ./run-unit-tests.sh --test-file-name prebid_server/test_start_glue_job.py
###############################################################################

import os
import json

from unittest.mock import patch

GLUE_JOB_NAME = "test-glue-job"

test_environ = {
    "GLUE_JOB_NAME": GLUE_JOB_NAME,
    "DATASYNC_REPORT_BUCKET": "test-report-bucket",
    "AWS_ACCOUNT_ID": "9111122223333",
    "METRICS_NAMESPACE": "test-namespace",
    "RESOURCE_PREFIX": "test-prefix",
    "SOLUTION_VERSION": "v0.0.0",
    "SOLUTION_ID": "SO0248",
    "AWS_REGION": "us-east-1"
}

@patch.dict(os.environ, test_environ, clear=True)
@patch('cloudwatch_metrics.metrics.Metrics.put_metrics_count_value_1')
@patch('datasync_reports.reports.get_transferred_object_keys')
@patch('boto3.client')
def test_event_handler(
    mock_boto3, 
    mock_get_transferred_object_keys,
    mock_metrics 
    ):
    from prebid_server.glue_trigger_lambda.start_glue_job import event_handler

    mock_metrics.return_value = None

    # test starting glue job with returned object keys
    mock_get_transferred_object_keys.return_value = ["key1", "key2"]
    test_event_1 = {
        "resources": ["arn:aws:sync:us-west-2:9111122223333:task/task-example2/execution/exec-example316440271f"]
    }
    event_handler(test_event_1, None)
    mock_boto3.return_value.start_job_run.assert_called_with(
        JobName=GLUE_JOB_NAME,
        Arguments={
            "--object_keys":  json.dumps(["key1", "key2"])
        }
    )
    mock_metrics.assert_called_with(metric_name="StartGlueJob")

    # test skipping glue job when no object keys returned
    mock_boto3.reset_mock()
    mock_get_transferred_object_keys.return_value = []
    test_event_1 = {
        "resources": ["arn:aws:sync:us-west-2:9111122223333:task/task-example2/execution/exec-example316440271f"]
    }
    event_handler(test_event_1, None)
    mock_boto3.return_value.start_job_run.assert_not_called()
