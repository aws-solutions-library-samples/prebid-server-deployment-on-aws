# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   *  Unit test for infrastructure/custom_resources/operational_metrics/ops_metrics.py
# USAGE:
#   ./run-unit-tests.sh --test-file-name custom_resources/test_ops_metrics.py
###############################################################################

import uuid
import os

import pytest
import boto3
from unittest.mock import patch, MagicMock
from moto import mock_aws


@pytest.fixture
def test_configs():
    return {
        "TEST_METRIC_UUID": str(uuid.uuid4()),
        "SECRET_NAME": f"{os.environ['STACK_NAME']}-anonymous-metrics-uuid",
    }


@pytest.fixture(autouse=True)
def mock_aws_services():
    """Mock AWS services"""
    with mock_aws():
        yield


@patch("custom_resources.operational_metrics.ops_metrics.create_uuid")
def test_on_create(create_uuid_mock):
    from custom_resources.operational_metrics.ops_metrics import on_create

    on_create({}, None)
    create_uuid_mock.assert_called_once()


@patch("custom_resources.operational_metrics.ops_metrics.delete_secret")
def test_on_delete(delete_secret_mock):
    from custom_resources.operational_metrics.ops_metrics import on_delete

    on_delete({"PhysicalResourceId": "1234"}, None)
    delete_secret_mock.assert_called_once()


@patch("crhelper.CfnResource")
@patch("custom_resources.operational_metrics.ops_metrics.helper")
def test_event_handler(helper_mock, _):
    from custom_resources.operational_metrics.ops_metrics import event_handler

    event_handler({}, None)
    helper_mock.assert_called_once()


@patch("crhelper.CfnResource")
def test_create_uuid(_, test_configs):
    session = boto3.session.Session(region_name=os.environ["AWS_REGION"])
    client = session.client("secretsmanager")

    fake_uuid = MagicMock()
    fake_uuid.uuid4() == test_configs["TEST_METRIC_UUID"]

    with patch("custom_resources.operational_metrics.ops_metrics.uuid", fake_uuid) as mock_uuid:
        from custom_resources.operational_metrics.ops_metrics import create_uuid

        create_uuid()
        res = client.get_secret_value(
            SecretId=test_configs["SECRET_NAME"],
        )
        res["SecretString"] == test_configs["TEST_METRIC_UUID"]
        mock_uuid.uuid4.assert_called()


@patch("crhelper.CfnResource.delete")
def test_delete_secret(_, test_configs):
    session = boto3.session.Session(region_name=os.environ["AWS_REGION"])
    client = session.client("secretsmanager")
    from custom_resources.operational_metrics.ops_metrics import delete_secret

    client.create_secret(
        Name=test_configs["SECRET_NAME"],
        SecretString=test_configs["TEST_METRIC_UUID"],
    )

    delete_secret()

    with pytest.raises(Exception) as ex:
        client.get_secret_value(
            SecretId=test_configs["SECRET_NAME"],
        )
    assert "Secrets Manager can't find the specified secret" in str(ex.value)
