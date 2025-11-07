# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
This Lambda function that archives the log files upon Fargate container stopping.
This is to capture any log files that may not have the opportunity to go through the periodic archiving process defined in the prebid-logging.xml.
Triggered by EventBridge event STOPPING (SIGTERM) condition is received by the container.
"""

import tarfile
import os
from pathlib import Path
from datetime import datetime, timezone
from aws_lambda_powertools import Logger

from cloudwatch_metrics import metrics

EFS_MOUNT_PATH = os.environ["EFS_MOUNT_PATH"]
EFS_METRICS = os.environ["EFS_METRICS"]
EFS_LOGS = os.environ["EFS_LOGS"]
METRICS_NAMESPACE = os.environ["METRICS_NAMESPACE"]
RESOURCE_PREFIX = os.environ["RESOURCE_PREFIX"]
EFS_ANALYTICS = os.environ["EFS_ANALYTICS"]

logger = Logger(utc=True, service="container-stop-logs")


def event_handler(event, _):
    """
    Entry point into the Lambda function to capture and archives the last active log files on container stop
    """

    metrics.Metrics(
        METRICS_NAMESPACE, RESOURCE_PREFIX, logger
    ).put_metrics_count_value_1(metric_name="ConatinerStopLogs")

    detail = event["detail"]
    container_run_id = detail["containers"][0]["runtimeId"].split('-')[0]
    logger.info(f"Container run id {container_run_id} status {detail['lastStatus']}")

    efs_mount_path = Path(EFS_MOUNT_PATH)
    metrics_log_folder = efs_mount_path.joinpath(EFS_METRICS).joinpath(container_run_id)
    analytics_log_folder = efs_mount_path.joinpath(EFS_ANALYTICS).joinpath(container_run_id)
    compress_log_file(metrics_log_folder, "prebid-metrics.log")
    compress_log_file(analytics_log_folder, "prebid-analytics.log")


def compress_log_file(log_folder_path: Path, log_file_name: str):
    archived_folder = create_or_retreive_archived_folder(log_folder_path)

    log_file_path = log_folder_path / log_file_name
    if not log_file_path.exists():
        logger.warning(f"{log_file_path} does not exist")
        return

    utc_time = datetime.now(timezone.utc)
    file_to_compress = (
        archived_folder
        / f"{log_file_name.split('.')[0]}.{utc_time.year}-{utc_time.month:02d}-{utc_time.day:02d}_{utc_time.hour:02d}.log.gz"
    )

    with tarfile.open(file_to_compress, "w:gz") as tar:
        tar.add(log_file_path)

    logger.info(f"Log file compressed: {file_to_compress}")


def create_or_retreive_archived_folder(log_folder_path) -> Path:
    archived_folder = Path(log_folder_path).joinpath("archived")
    try:
        # only create if folder does not exist
        archived_folder.mkdir(exist_ok=True, parents=True)
    except PermissionError as p:
        logger.error(f"Permission error: {p}")
        raise p

    return archived_folder
