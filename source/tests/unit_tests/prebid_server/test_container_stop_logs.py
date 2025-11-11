# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# #########################
######################################################
# PURPOSE:
#   * Unit test for infrastructure/prebid_server/efs_cleanup_lambda/container_stop_logs.py.
# USAGE:
#   ./run-unit-tests.sh --test-file-name prebid_server/test_container_stop_logs.py
###############################################################################

import os
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
from datetime import datetime, timezone


test_environ = {
    "EFS_MOUNT_PATH": "/mnt/efs",
    "AWS_ACCOUNT_ID": "9111122223333",
    "EFS_METRICS": "metrics",
    "EFS_ANALYTICS": "analytics",
    "EFS_LOGS": "logs",
    "SOLUTION_VERSION": "v1.9.99",
    "SOLUTION_ID": "SO000123",
    "RESOURCE_PREFIX": "Stack123",
    "METRICS_NAMESPACE": "Metrics123",
}

EVENT_DETAIL = {
    "detail": {"containers": [{"runtimeId": "id123456"}], "lastStatus": "STOPPING"}
}


@patch.dict(os.environ, test_environ, clear=True)
@patch('cloudwatch_metrics.metrics.Metrics.put_metrics_count_value_1')
@patch("prebid_server.efs_cleanup_lambda.container_stop_logs.logger")
@patch("prebid_server.efs_cleanup_lambda.container_stop_logs.Path")
@patch("prebid_server.efs_cleanup_lambda.container_stop_logs.compress_log_file")
def test_event_handler(mock_compress_log_file, mock_path, mock_logger, mock_metrics):
    from prebid_server.efs_cleanup_lambda.container_stop_logs import event_handler

    mock_metrics.return_value = None
    
    event = EVENT_DETAIL
    event_handler(event, None)

    mock_logger.info.assert_called_with(
        "Container run id id123456 status STOPPING")
    mock_path.assert_called_with(test_environ["EFS_MOUNT_PATH"])
    assert mock_compress_log_file.call_count == 2
    mock_metrics.assert_called_once_with(metric_name="ConatinerStopLogs")


@patch.dict(os.environ, test_environ, clear=True)
@patch("prebid_server.efs_cleanup_lambda.container_stop_logs.create_or_retreive_archived_folder")
@patch("prebid_server.efs_cleanup_lambda.container_stop_logs.tarfile.open")
@patch("prebid_server.efs_cleanup_lambda.container_stop_logs.logger")
@patch("pathlib.Path.exists", return_value=True)
def test_compress_log_file( mock_path_exists, mock_logger, mock_tarfile_open, mock_create_or_retreive_archived_folder):
    from prebid_server.efs_cleanup_lambda.container_stop_logs import compress_log_file

    log_folder_path = Path("/path/to/log/folder")
    log_file_name = "example.log"

    mock_create_or_retreive_archived_folder.return_value = Path(
        "/path/to/folder/archived")
    mock_path_exists.return_value = True
    mock_tarfile = MagicMock()
    mock_tarfile_open.return_value.__enter__.return_value = mock_tarfile

    compress_log_file(log_folder_path, log_file_name)

    utc_time = datetime.now(timezone.utc)
    expected_file_to_compress = f"/path/to/folder/archived/example.{utc_time.year}-{utc_time.month:02d}-{utc_time.day:02d}_{utc_time.hour:02d}.log.gz"

    mock_tarfile.add.assert_called_with(Path("/path/to/log/folder/example.log"))
    mock_logger.info.assert_called_with(f"Log file compressed: {expected_file_to_compress}")


@patch.dict(os.environ, test_environ, clear=True)
@patch("prebid_server.efs_cleanup_lambda.container_stop_logs.Path")
@patch("prebid_server.efs_cleanup_lambda.container_stop_logs.logger")
def test_create_or_retreive_archived_folder(mock_logger, mock_path):
    from prebid_server.efs_cleanup_lambda.container_stop_logs import create_or_retreive_archived_folder

    mock_path.return_value = Mock()
    log_folder_path = "test_logs"
    result = create_or_retreive_archived_folder(log_folder_path)

    assert result == mock_path.return_value.joinpath.return_value
    mock_path.return_value.joinpath.assert_called_once_with("archived")
    mock_path.return_value.joinpath.return_value.mkdir.assert_called_once_with(
        exist_ok=True, parents=True)
