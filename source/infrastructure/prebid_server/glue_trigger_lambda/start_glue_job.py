# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
This module is a Lambda function that starts the Metrics ETL Glue Job with a list of object keys to be ingested.
It is triggered by EventBridge after a successful DataSync task execution of the metrics transfer task.
"""

import json
import os

import boto3
from botocore import config
from aws_lambda_powertools import Logger
from cloudwatch_metrics import metrics
from datasync_reports import reports


logger = Logger(utc=True, service="glue-trigger-lambda")

GLUE_JOB_NAME = os.environ["GLUE_JOB_NAME"]
METRICS_NAMESPACE = os.environ['METRICS_NAMESPACE']
RESOURCE_PREFIX = os.environ['RESOURCE_PREFIX']
DATASYNC_REPORT_BUCKET = os.environ['DATASYNC_REPORT_BUCKET']
AWS_ACCOUNT_ID = os.environ["AWS_ACCOUNT_ID"]
SOLUTION_VERSION = os.environ.get("SOLUTION_VERSION")
SOLUTION_ID = os.environ.get("SOLUTION_ID")
append_solution_identifier = {
    "user_agent_extra": f"AwsSolution/{SOLUTION_ID}/{SOLUTION_VERSION}"
}
default_config = config.Config(**append_solution_identifier)
glue_client = boto3.client("glue", config=default_config)
s3_client = boto3.client("s3", config=default_config)

def event_handler(event, _):
    """
    This function is the entry point for the Lambda and handles retrieving transferred S3 object keys and starting the Glue Job.
    """
    metrics.Metrics(METRICS_NAMESPACE, RESOURCE_PREFIX, logger).put_metrics_count_value_1(metric_name="StartGlueJob")
    
    object_keys = reports.get_transferred_object_keys(
        event=event, 
        datasync_report_bucket=DATASYNC_REPORT_BUCKET, 
        aws_account_id=AWS_ACCOUNT_ID,
        s3_client=s3_client
    )

    if len(object_keys) > 0:
        logger.info(f"{len(object_keys)} new files to process: {object_keys}")
        try:
            response = glue_client.start_job_run(
                JobName=GLUE_JOB_NAME,
                Arguments={
                    "--object_keys": json.dumps(object_keys)
                }
            )
            logger.info(f"Glue Job response: {response}")

        except Exception as err:
            logger.error(f"Error starting Glue Job: {err}")
            raise err
    else:
        logger.info("No new files to send to Glue.")
    
