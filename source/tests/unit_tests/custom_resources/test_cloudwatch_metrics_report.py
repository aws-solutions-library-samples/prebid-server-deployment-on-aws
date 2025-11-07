# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for infrastructure/cloudwatch_metrics/cloudwatch_metrics_report.
# USAGE:
#   ./run-unit-tests.sh --test-file-name custom_resources/test_cloudwatch_metrics_report.py
###############################################################################


import os
import uuid
import json
from datetime import datetime, timedelta

import pytest
import boto3
import responses
from unittest.mock import patch, MagicMock
from moto import mock_aws
from responses import matchers


@pytest.fixture
def event():
    return {
        "ResponseURL": "https://test.com/test",
        "StackId": 12345,
        "RequestId": 67890,
        "LogicalResourceId": 1112131415,
        "RequestType": "Create",
        "ResourceProperties": {
            "UUID": str(uuid.uuid4()),
            "ServiceToken": "some arn"
        },
    }


@pytest.fixture
def context():
    return MagicMock(reason="200", log_stream_name="test log")


def create_secret():
    session = boto3.session.Session(region_name=os.environ["AWS_REGION"])
    secret_client = session.client("secretsmanager")
    secret_id = f"{os.environ['STACK_NAME']}-anonymous-metrics-uuid"
    secret_uuid = str(uuid.uuid4())
    secret_client.create_secret(
        Name=secret_id,
        SecretString=secret_uuid
    )
    return secret_uuid


@patch("crhelper.CfnResource")
@patch("custom_resources.cloudwatch_metrics.cloudwatch_metrics_report.send_metrics")
def test_event_handler(send_metrics_mock, _):
    from custom_resources.cloudwatch_metrics.cloudwatch_metrics_report import event_handler

    event_handler({}, None)
    send_metrics_mock.assert_called_once()


@mock_aws
@patch("requests.put")
@responses.activate
@patch("crhelper.CfnResource")
def test_send_metrics(_, mock_response_put, event, context):
    secret_uuid = create_secret()

    cloudwatch_client = boto3.client(
        "cloudwatch", region_name=os.environ["AWS_REGION"]
    )

    mock_response_put.return_value = MagicMock(reason="200")

    dt_utc_now = datetime.utcnow()
    # minus 6 hours to make MetricData timestamp fall into the StartTime and EndTime range used in `cloudwatch_client.get_metric_statistics()`
    metric_data_timestamp = dt_utc_now - timedelta(hours=6)
    test_metric_sum = {}

    # Generic metrics
    generic_metrics = {
        "Lambda": ["DeleteEfsFiles", "StartGlueJob"],
        "CloudFormation": ["CreateUpdate"],
        "PrebidServer": ["AuctionRequests", "ImpsRequested"]
    }

    test_sum = 20.0

    for metric_tag, metrics in generic_metrics.items():
        for metric in metrics:
            test_metric_sum[f"{metric_tag}-{metric}"] = test_sum
            metric_name = f"{metric_tag}-{metric}" if metric_tag == "CloudFormation" else metric
            cloudwatch_client.put_metric_data(
                Namespace=os.environ["METRICS_NAMESPACE"],
                MetricData=[
                    {
                        "MetricName": metric_name,
                        "Dimensions": [
                            {"Name": "stack-name", "Value": os.environ["STACK_NAME"]}
                        ],
                        "Timestamp": metric_data_timestamp,
                        "Unit": "Count",
                        "StatisticValues": {
                            "SampleCount": 50.0,
                            "Sum": test_sum,
                            "Minimum": 10.0,
                            "Maximum": 20.0
                        }
                    },
                ])

    # NAT gateway
    ec2_client = boto3.client("ec2", region_name=os.environ["AWS_REGION"])
    vpc_resp = ec2_client.create_vpc(CidrBlock="10.0.0.0/16")
    subnet_resp = ec2_client.create_subnet(VpcId=vpc_resp["Vpc"]["VpcId"], CidrBlock="10.0.0.0/16")
    os.environ["SUBNET_IDS"] = json.dumps([subnet_resp["Subnet"]["SubnetId"]])

    nat_gateway_sum = 55.0

    nat_gateway_metrics = [
        "ActiveConnectionCount",
        "BytesInFromDestination",
        "ConnectionAttemptCount",
        "PeakPacketsPerSecond",
        "ConnectionEstablishedCount",
        "PeakBytesPerSecond"
    ]
    test_metric_tag = "NATGateway"
    for subnet_id in [subnet_resp["Subnet"]["SubnetId"]]:
        nat_gateway_response = ec2_client.create_nat_gateway(SubnetId=subnet_id)
        nat_gateway_id = nat_gateway_response["NatGateway"]["NatGatewayId"]
        for nat_gateway_metric in nat_gateway_metrics:
            cloudwatch_client.put_metric_data(
                Namespace=f"AWS/{test_metric_tag}",
                MetricData=[
                    {
                        "MetricName": nat_gateway_metric,
                        "Unit": "Count",
                        "Dimensions": [
                            {
                                "Name": "NatGatewayId",
                                "Value": nat_gateway_id
                            }
                        ],
                        "Timestamp": metric_data_timestamp,
                        "StatisticValues": {
                            "SampleCount": 50.0,
                            "Sum": nat_gateway_sum,
                            "Minimum": 10.0,
                            "Maximum": 20.0
                        }
                    },
                ]
            )
            test_metric_sum[f"{test_metric_tag}-{nat_gateway_metric}"] = nat_gateway_sum

    # Load Balancer
    elb_sum = 10.0
    elb_client = boto3.client("elbv2", region_name=os.environ["AWS_REGION"])
    os.environ["LOAD_BALANCER_NAME"] = "test_prebid_elb"
    elb_client.create_load_balancer(Name=os.environ["LOAD_BALANCER_NAME"], Subnets=[subnet_resp["Subnet"]["SubnetId"]])
    elb_metrics = [
        "ActiveConnectionCount",
        "RequestCount",
        "HealthyHostCount",
        "UnHealthyHostCount",
    ]
    test_metric_tag = "ApplicationELB"
    for elb_metric in elb_metrics:
        cloudwatch_client.put_metric_data(
            Namespace=f"AWS/{test_metric_tag}",
            MetricData=[
                {
                    "MetricName": elb_metric,
                    "Dimensions": [
                        {
                            "Name": "LoadBalancer",
                            "Value": os.environ["LOAD_BALANCER_NAME"]
                        }
                    ],
                    "Timestamp": metric_data_timestamp,
                    "Unit": "Count",
                    "StatisticValues": {
                        "SampleCount": 50.0,
                        "Sum": elb_sum,
                        "Minimum": 10.0,
                        "Maximum": 20.0
                    }
                },
            ]
        )
        test_metric_sum[f"{test_metric_tag}-{elb_metric}"] = elb_sum

    # Cloudfront
    s3 = boto3.client("s3", region_name=os.environ["AWS_REGION"])
    test_bucket_name = "test_bucket"
    s3.create_bucket(Bucket=test_bucket_name)
    cf_client = boto3.client("cloudfront", region_name=os.environ["AWS_REGION"])
    cf_response = cf_client.create_distribution(
        DistributionConfig={
            "DefaultCacheBehavior": {
                "TargetOriginId": test_bucket_name,
                "ViewerProtocolPolicy": "redirect-to-https",
                "TrustedSigners": {
                    "Quantity": 0,
                    "Enabled": False
                },
                "ForwardedValues": {
                    "QueryStringCacheKeys": {
                        "Quantity": 0
                    },
                    "Headers": {
                        "Quantity": 0
                    },
                    "QueryString": False,
                    "Cookies": {
                        "Forward": "all"
                    },
                },
                "DefaultTTL": 86400,
                "MinTTL": 3600
            },
            "Comment": "testing",
            "CallerReference": "test_stack",
            "Origins": {
                "Quantity": 1,
                "Items": [{
                    "Id": test_bucket_name,
                    "DomainName": f"{test_bucket_name}.s3.amazonaws.com",
                    "S3OriginConfig": {
                        "OriginAccessIdentity": ""
                    }
                }]
            },
            "Enabled": True
        })
    os.environ["CF_DISTRIBUTION_ID"] = cf_response["Distribution"]["Id"]
    cf_sum = 100.0
    cf_cw_metrics = ["Requests", "TotalErrorRate"]
    test_metric_tag = "CloudFront"
    for cf_cw_metric in cf_cw_metrics:
        cloudwatch_client.put_metric_data(
            Namespace=f"AWS/{test_metric_tag}",
            MetricData=[
                {
                    "MetricName": cf_cw_metric,
                    "Unit": "Count",
                    "Dimensions": [
                        {
                            "Name": "DistributionId",
                            "Value": os.environ["CF_DISTRIBUTION_ID"]
                        },
                        {"Name": "Region", "Value": "Global"},
                    ],
                    "Timestamp": metric_data_timestamp,
                    "StatisticValues": {
                        "SampleCount": 50.0,
                        "Sum": cf_sum,
                        "Minimum": 10.0,
                        "Maximum": 20.0
                    }
                },
            ]
        )
        test_metric_sum[f"{test_metric_tag}-{cf_cw_metric}"] = cf_sum
        
    #Elasticache
    os.environ["ELASTICACHE_CLUSTER_ID"] = "test-id"

    DT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

    responses.post(
        url="https://metrics.awssolutionsbuilder.com/generic",
        json={},
        status=200,
        match=[
            matchers.json_params_matcher(
                {
                    "Solution": os.environ["SOLUTION_ID"],
                    "Version": os.environ["SOLUTION_VERSION"],
                    "UUID": secret_uuid,
                    "Timestamp": dt_utc_now.strftime(DT_TIME_FORMAT),
                    "Data": test_metric_sum,
                    "StartTime": (dt_utc_now - timedelta(seconds=86400)).strftime(DT_TIME_FORMAT),
                    "EndTime": dt_utc_now.strftime(DT_TIME_FORMAT),
                }
            ),
            matchers.request_kwargs_matcher({
                "timeout": 5
            })
        ],
    )

    fake_date = MagicMock()
    fake_date.utcnow.return_value = dt_utc_now

    with patch("custom_resources.cloudwatch_metrics.cloudwatch_metrics_report.datetime", fake_date) as mock_dt_now:
        from custom_resources.cloudwatch_metrics.cloudwatch_metrics_report import send_metrics, CloudwatchMetricsReport

        send_metrics()

        mock_dt_now.utcnow.assert_called()

        def resolve_test_assertion(data):
            for k, v in data["Data"].items():
                assert test_metric_sum[k] == v

        cloudwatch_metrics_report = CloudwatchMetricsReport()
        for metric_func in [
            "get_lambda_metrics",
            "get_prebid_server_metrics",
            "get_cloudfront_metrics",
            "get_nat_gateway_metrics",
            "get_application_elb_metrics",
            "get_cloudformation_metrics"
        ]:
            resolve_test_assertion(getattr(cloudwatch_metrics_report, metric_func)())

        test_datapoints = {
            "datapoints": {
                "SampleCount": 1128.0,
                "Average": 0.0017730496453900709,
                "Sum": 2.0,
                "Minimum": 1.0,
                "Maximum": 1.0,
                "Unit": "Count",
                "Timestamp": str(dt_utc_now)
            }
        }
        expected_metric = {
            "Test-CloudFront-TotalErrorRate": {
                "sum": 60,
                "dimensions": [
                    {
                        "Name": "DistributionId",
                        "Value": os.environ["CF_DISTRIBUTION_ID"]
                    },
                    {"Name": "Region", "Value": "Global"},
                ],
                **test_datapoints
            },
            "Test-NATGateway-ActiveConnectionCount": {
                "sum": 90,
                "dimensions": [
                    {
                        "Name": "NatGatewayId",
                        "Value": "123455"
                    }
                ],
                **test_datapoints
            },
            "Test-ApplicationELB-RequestCountPerTarget": {
                "sum": 90,
                "dimensions": [
                    {
                        "Name": "LoadBalancer",
                        "Value": os.environ["LOAD_BALANCER_NAME"]
                    }
                ],
                **test_datapoints
            }
        }
        cloudwatch_metrics_report.put_metric_data(expected_metric)

        test_response = cloudwatch_client.list_metrics(
            Namespace=os.environ["METRICS_NAMESPACE"],
        )

        for k, v in expected_metric.items():
            if (
                    len([metric["MetricName"] for metric in test_response["Metrics"] if
                         metric["MetricName"] == k]) == 0 or
                    len([metric["Dimensions"] for metric in test_response["Metrics"] if
                         metric["Dimensions"] == v["dimensions"]]) == 0
            ):
                raise AssertionError()
