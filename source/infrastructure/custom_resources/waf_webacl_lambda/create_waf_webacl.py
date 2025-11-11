# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
This module is a custom lambda for creation of Waf Web ACL
"""

import boto3
import os
import uuid
from botocore import config
from aws_lambda_powertools import Logger
from crhelper import CfnResource

logger = Logger(utc=True, service="waf-custom-lambda")
helper = CfnResource(log_level="ERROR", boto_level="ERROR")

SOLUTION_ID = os.environ["SOLUTION_ID"]
SOLUTION_VERSION = os.environ["SOLUTION_VERSION"]


def event_handler(event, context):
    """
    This is the Lambda custom resource entry point.
    """

    logger.info(event)
    helper(event, context)


def get_4char_uuid() -> str:
    """
    This function is responsible for generating a 4 character UUID
    """
    return str(uuid.uuid4())[:4]


@helper.create
def on_create(event, _) -> None:
    """
    Function to create waf web acl
    """
    # Add the solution identifier to boto3 requests for attributing service API usage
    boto_config = {
        "region_name": "us-east-1",
        "user_agent_extra": f"AwsSolution/{SOLUTION_ID}/{SOLUTION_VERSION}"
    }

    wafv2_client = boto3.client("wafv2", config=config.Config(**boto_config))

    response = wafv2_client.create_web_acl(
        Name=f"PrebidWaf-{event['StackId'].rsplit('/')[-1]}-{get_4char_uuid()}",
        Scope="CLOUDFRONT",
        DefaultAction={"Allow": {}},
        Description="Creating Web ACL for Cloudfront applying AWS managed rule sets",
        Rules=[
            # Allow specific POST operation to /cache endpoint
            {
                "Name": "AllowPostToCache",
                "Priority": 1,
                "Statement": {
                    "AndStatement": {
                        "Statements": [
                            {
                                "ByteMatchStatement": {
                                    "SearchString": "/cache",
                                    "FieldToMatch": {
                                        "UriPath": {}
                                    },
                                    "TextTransformations": [
                                        {
                                            "Priority": 1,
                                            "Type": "NONE"
                                        }
                                    ],
                                    "PositionalConstraint": "EXACTLY"
                                }
                            },
                            {
                                "ByteMatchStatement": {
                                    "SearchString": "POST",
                                    "FieldToMatch": {
                                        "Method": {}
                                    },
                                    "TextTransformations": [
                                        {
                                            "Priority": 1,
                                            "Type": "NONE"
                                        }
                                    ],
                                    "PositionalConstraint": "EXACTLY"
                                }
                            }
                        ]
                    }
                },
                "Action": {
                    "Allow": {}
                },
                "VisibilityConfig": {
                    "SampledRequestsEnabled": True,
                    "CloudWatchMetricsEnabled": True,
                    "MetricName": "AllowPostToCache"
                }
            },
            {
                "Name": "AWS-AWSManagedRulesKnownBadInputsRuleSet",
                "OverrideAction": {"None": {}},
                "Priority": 2,
                "Statement": {
                    "ManagedRuleGroupStatement": {
                        "Name": "AWSManagedRulesKnownBadInputsRuleSet",
                        "VendorName": "AWS",
                    }
                },
                "VisibilityConfig": {
                    "CloudWatchMetricsEnabled": True,
                    "MetricName": "AWSManagedRulesKnownBadInputsRuleSet",
                    "SampledRequestsEnabled": True,
                },
            },
            {
                "Name": "AWS-AWSManagedRulesCommonRuleSet",
                "OverrideAction": {"None": {}},
                "Priority": 3,
                "Statement": {
                    "ManagedRuleGroupStatement": {
                        "Name": "AWSManagedRulesCommonRuleSet",
                        "VendorName": "AWS",
                    }
                },
                "VisibilityConfig": {
                    "CloudWatchMetricsEnabled": True,
                    "MetricName": "AWSManagedRulesCommonRuleSet",
                    "SampledRequestsEnabled": True,
                },
            },
            {
                "Name": "AWS-AWSManagedRulesAnonymousIpList",
                "OverrideAction": {"None": {}},
                "Priority": 4,
                "Statement": {
                    "ManagedRuleGroupStatement": {
                        "Name": "AWSManagedRulesAnonymousIpList",
                        "VendorName": "AWS",
                    }
                },
                "VisibilityConfig": {
                    "CloudWatchMetricsEnabled": True,
                    "MetricName": "AWSManagedRulesAnonymousIpList",
                    "SampledRequestsEnabled": True,
                },
            },
            {
                "Name": "AWS-AWSManagedRulesAmazonIpReputationList",
                "OverrideAction": {"None": {}},
                "Priority": 5,
                "Statement": {
                    "ManagedRuleGroupStatement": {
                        "Name": "AWSManagedRulesAmazonIpReputationList",
                        "VendorName": "AWS",
                    }
                },
                "VisibilityConfig": {
                    "CloudWatchMetricsEnabled": True,
                    "MetricName": "AWSManagedRulesAmazonIpReputationList",
                    "SampledRequestsEnabled": True,
                },
            },
            {
                "Name": "AWS-AWSManagedRulesAdminProtectionRuleSet",
                "OverrideAction": {"None": {}},
                "Priority": 6,
                "Statement": {
                    "ManagedRuleGroupStatement": {
                        "Name": "AWSManagedRulesAdminProtectionRuleSet",
                        "VendorName": "AWS",
                    }
                },
                "VisibilityConfig": {
                    "CloudWatchMetricsEnabled": True,
                    "MetricName": "AWSManagedRulesAdminProtectionRuleSet",
                    "SampledRequestsEnabled": True,
                },
            },
            {
                "Name": "AWS-AWSManagedRulesSQLiRuleSet",
                "OverrideAction": {"None": {}},
                "Priority": 7,
                "Statement": {
                    "ManagedRuleGroupStatement": {
                        "Name": "AWSManagedRulesSQLiRuleSet",
                        "VendorName": "AWS",
                    }
                },
                "VisibilityConfig": {
                    "CloudWatchMetricsEnabled": True,
                    "MetricName": "AWSManagedRulesSQLiRuleSet",
                    "SampledRequestsEnabled": True,
                },
            },
        ],
        VisibilityConfig={
            "SampledRequestsEnabled": True,
            "CloudWatchMetricsEnabled": True,
            "MetricName": "PrebidWebACL",
        },
    )

    logger.info(response)
    helper.Data.update(
        {
            "webacl_arn": response["Summary"]["ARN"],
            "webacl_name": response["Summary"]["Name"],
            "webacl_id": response["Summary"]["Id"],
            "webacl_locktoken": response["Summary"]["LockToken"],
        }
    )
