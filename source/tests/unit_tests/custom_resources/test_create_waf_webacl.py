# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for infrastructure/custom_resources/create_waf_webacl.
# USAGE:
#   ./run-unit-tests.sh --test-file-name custom_resources/test_create_waf_webacl.py
###############################################################################

from moto import mock_aws
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_aws_services():
    """Mock AWS services"""
    with mock_aws():
        yield


@patch("crhelper.CfnResource")
@patch("custom_resources.waf_webacl_lambda.create_waf_webacl.helper")
def test_event_handler(helper_mock, _):
    from custom_resources.waf_webacl_lambda.create_waf_webacl import event_handler

    event_handler({}, None)
    helper_mock.assert_called_once()


@patch("custom_resources.waf_webacl_lambda.create_waf_webacl.boto3.client")
@patch("crhelper.CfnResource")
def test_on_create(_, mock_boto3):
    expected_resp = {
        "Summary":
            {
                "ARN": 1234,
                "Name": "test_name",
                "Id": 1234,
                "LockToken": "lock_token",
            },
    }
    mock_boto3.return_value.create_web_acl.return_value = expected_resp
    from custom_resources.waf_webacl_lambda.create_waf_webacl import on_create

    with patch("custom_resources.waf_webacl_lambda.create_waf_webacl.helper.Data", {}) as helper_update_mock:
        on_create({
            "StackId": "test/id12345"
        }, None)

    assert helper_update_mock["webacl_arn"] == expected_resp["Summary"]["ARN"]
    assert helper_update_mock["webacl_name"] == expected_resp["Summary"]["Name"]
    assert helper_update_mock["webacl_id"] == expected_resp["Summary"]["Id"]
    assert helper_update_mock["webacl_locktoken"] == expected_resp["Summary"]["LockToken"]
