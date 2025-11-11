# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
This module is a custom resource Lambda for uploading docker config files to an S3 bucket.
"""

import os
from crhelper import CfnResource
from aws_lambda_powertools import Logger
import boto3
from botocore import config

SOLUTION_ID = os.environ["SOLUTION_ID"]
SOLUTION_VERSION = os.environ["SOLUTION_VERSION"]

logger = Logger(service="prebid-configs-bucket-upload-lambda", level="INFO")
helper = CfnResource(log_level="ERROR", boto_level="ERROR")

# Constants for directories and S3 prefixes
CONFIG_DIRECTORIES = [
    ("default-config", "prebid-server/default"),
    ("current-config", "prebid-server/current"),
]
STORED_REQUESTS_DIRECTORIES = [
    ("stored_requests", "stored_requests"),
    ("stored_impressions", "stored_impressions"),
    ("stored_responses", "stored_responses"),
    ("stored_accounts", "stored_accounts")
]


def event_handler(event, context):
    """
    This is the Lambda custom resource entry point.
    """
    logger.info(event)
    helper(event, context)


@helper.create
@helper.update
def on_create_or_update(event, _) -> None:
    try:
        docker_configs_bucket_name = event["ResourceProperties"]["docker_configs_bucket_name"]
        stored_requests_bucket_name = event["ResourceProperties"]["stored_requests_bucket_name"]
        upload_all_files(docker_configs_bucket_name, CONFIG_DIRECTORIES)
        upload_all_files(stored_requests_bucket_name, STORED_REQUESTS_DIRECTORIES)
    except Exception as err:
        logger.error(f"Error uploading files to S3: {err}")
        raise err


def upload_all_files(bucket_name: str, path_mapping) -> None:
    """
    Uploads files from predefined directories to the S3 bucket using respective prefixes.
    """
    for directory, prefix in path_mapping:
        upload_directory_to_s3(bucket_name, directory, prefix)


def upload_directory_to_s3(bucket_name: str, directory: str, prefix: str) -> None:
    """
    Uploads all files from a specified directory to the S3 bucket with the given prefix.
    """
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            object_key = os.path.join(prefix, os.path.relpath(file_path, directory))
            upload_file_to_s3(bucket_name, file_path, object_key)


def upload_file_to_s3(bucket_name: str, file_path: str, object_key: str) -> None:
    """
    Uploads a single file to the specified S3 bucket.
    """
    # Add the solution identifier to boto3 requests for attributing service API usage
    boto_config = {
        "user_agent_extra": f"AwsSolution/{SOLUTION_ID}/{SOLUTION_VERSION}"
    }
    s3_client = boto3.client("s3", config=config.Config(**boto_config))
    s3_client.upload_file(file_path, bucket_name, object_key)
    logger.info(f"Uploaded {file_path} to s3://{bucket_name}/{object_key}")

