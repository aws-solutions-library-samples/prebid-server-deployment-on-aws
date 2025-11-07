# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
This module is a Lambda function that deletes files from EFS after they have been transferred to S3 for longterm storage.
It is triggered by EventBridge after a successful DataSync task execution of the metrics or logs transfer tasks.
"""

import os

import boto3
from botocore import config
from aws_lambda_powertools import Logger
from cloudwatch_metrics import metrics
from datasync_reports import reports


logger = Logger(utc=True, service="efs-cleanup-lambda")

EFS_MOUNT_PATH = os.environ["EFS_MOUNT_PATH"]
METRICS_TASK_ARN = os.environ["METRICS_TASK_ARN"]
ANALYTICS_TASK_ARN = os.environ["ANALYTICS_TASK_ARN"]
METRICS_NAMESPACE = os.environ['METRICS_NAMESPACE']
RESOURCE_PREFIX = os.environ['RESOURCE_PREFIX']
DATASYNC_REPORT_BUCKET = os.environ["DATASYNC_REPORT_BUCKET"]
AWS_ACCOUNT_ID = os.environ["AWS_ACCOUNT_ID"]
EFS_METRICS = os.environ["EFS_METRICS"]
EFS_LOGS = os.environ["EFS_LOGS"]
EFS_ANALYTICS = os.environ["EFS_ANALYTICS"]

DIRECTORY_MAP = {
    METRICS_TASK_ARN: EFS_METRICS,
    ANALYTICS_TASK_ARN: EFS_ANALYTICS
}
SOLUTION_VERSION = os.environ["SOLUTION_VERSION"]
SOLUTION_ID = os.environ["SOLUTION_ID"]
append_solution_identifier = {
    "user_agent_extra": f"AwsSolution/{SOLUTION_ID}/{SOLUTION_VERSION}"
}
default_config = config.Config(**append_solution_identifier)
s3_client = boto3.client("s3", config=default_config)

def event_handler(event, _):
    """
    This function is the entry point for the Lambda and handles retrieving transferred S3 object keys and deleting them from the mounted EFS filesystem.
    """
    metrics.Metrics(METRICS_NAMESPACE, RESOURCE_PREFIX, logger).put_metrics_count_value_1(metric_name="DeleteEfsFiles")
    
    object_keys = reports.get_transferred_object_keys(
        event=event, 
        datasync_report_bucket=DATASYNC_REPORT_BUCKET, 
        aws_account_id=AWS_ACCOUNT_ID,
        s3_client=s3_client
    )

    # extract the task arn from the task execution arn
    task_arn = event['resources'][0].split("/execution/")[0]
    directory = DIRECTORY_MAP.get(task_arn)
    
    if len(object_keys) > 0:
        logger.info(f"{len(object_keys)} new {directory} files to process: {object_keys}")

        failed = []
        for key in object_keys:
            path = f"{EFS_MOUNT_PATH}/{directory}/{key}"
            try:
                os.remove(path)
            except OSError as e:
                failed.append(key)
                logger.error(f"Error: {e}")

        if len(failed) == 0:
            logger.info("All files deleted successfully.")
        else:
            logger.error(f"{len(failed)} files failed to delete: {failed}")

    else:
        logger.info(f"No new {directory} files to delete from EFS.") # nosec
    