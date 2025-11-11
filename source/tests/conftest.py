# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import pathlib
import pytest
import sys

current_dir = pathlib.Path(__file__).parent.absolute()
project_root = str(current_dir.parent)

metrics_path = os.path.join(project_root, 'infrastructure', 'aws_lambda_layers', 'metrics_layer', 'python')
datasync_path = os.path.join(project_root, 'infrastructure', 'aws_lambda_layers', 'datasync_s3_layer', 'python')

sys.path.append(metrics_path)
sys.path.append(datasync_path)


@pytest.fixture(scope="session", autouse=True)
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "123456789"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "987654321"
    os.environ["AWS_SECURITY_TOKEN"] = "test_securitytoken"
    os.environ["AWS_SESSION_TOKEN"] = "test_session_token"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_REGION"] = os.environ["AWS_DEFAULT_REGION"]


@pytest.fixture(autouse=True)
def handler_env():
    os.environ['METRICS_NAMESPACE'] = "testmetrics"
    os.environ['STACK_NAME'] = "test_stack_name"
    os.environ['RESOURCE_PREFIX'] = "test_stack_name"
    os.environ['SEND_ANONYMIZED_DATA'] = "Yes"
    os.environ['SOLUTION_APPLICATION_TYPE'] = "AWS-Solutions"

