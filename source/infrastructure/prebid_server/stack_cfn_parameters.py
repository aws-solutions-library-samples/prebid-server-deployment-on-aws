# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import prebid_server.stack_constants as stack_constants
from aws_cdk import (
    CfnParameter
)

# Constants
ECS_AUTOSCALING_GROUP_NAME = "ECS Service Autoscaling Settings"
CDN_GROUP_NAME = "Content Delivery Network (CDN) Settings"

class StackParams:
    def __init__(self, stack) -> None:
        self.deploy_cloudfront_and_waf_param = CfnParameter(
            stack,
            id="InstallCloudFrontAndWAF",
            description="Yes - Use the CloudFront and Web Application Firewall to deliver your content. \n No - Skip CloudFront and WAF deployment and use your own content delivery network instead",
            type="String",
            allowed_values=["Yes", "No"],
            default="Yes"
        )

        self.ssl_certificate_param = CfnParameter(
            stack,
            id="SSLCertificateARN",
            description="The ARN of an SSL certificate in AWS Certificate Manager associated with a domain name. This field is only required if InstallCloudFrontAndWAF is set to \"No\".",
            type="String",
            default="",
            allowed_pattern="^$|^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[a-zA-Z0-9-]+$",
            constraint_description="Must be a valid ACM certificate ARN or empty if using CloudFront"
        )

        stack.solutions_template_options.add_parameter(
            self.deploy_cloudfront_and_waf_param, label="InstallCloudFrontAndWAF",
            group=CDN_GROUP_NAME)
        stack.solutions_template_options.add_parameter(
            self.ssl_certificate_param, label="SSLCertificateARN",
            group=CDN_GROUP_NAME)

        self.ecs_task_min_capacity = CfnParameter(
            stack,
            id="ECSTaskMinCapacity",
            description="The minimum number of tasks to run for the Prebid Server ECS service",
            type="Number",
            default=stack_constants.TASK_MIN_CAPACITY,
            min_value=1,
            constraint_description="Minimum capacity must be at least 1 task"
        )

        self.ecs_task_max_capacity = CfnParameter(
            stack,
            id="ECSTaskMaxCapacity",
            description="The maximum number of tasks to run for the Prebid Server ECS service",
            type="Number",
            default=stack_constants.TASK_MAX_CAPACITY,
            min_value=1,
            constraint_description="Maximum capacity must be at least 1 task"
        )

        self.request_count_threshold = CfnParameter(
            stack,
            id="RequestsPerTargetThreshold",
            description="The number of requests per target to trigger scaling up the Prebid Server ECS service",
            type="Number",
            default=stack_constants.REQUESTS_PER_TARGET_THRESHOLD,
            min_value=100,
            max_value=10000,
            constraint_description="Requests per target threshold must be between 100 and 10000"
        )

        self.spot_instance_weight = CfnParameter(
            stack,
            id="SpotInstanceWeight",
            description="Spot instance weight configuration (On-demand weight fixed at 1). Default Spot weight is 1, adjustable as needed",
            type="Number",
            default=stack_constants.SPOT_INSTANCE_WEIGHT,
            min_value=0,
            constraint_description="Spot instance weight must be a non-negative number"
        )

        stack.solutions_template_options.add_parameter(
            self.ecs_task_min_capacity, label="ECSTaskMinCapacity",
            group=ECS_AUTOSCALING_GROUP_NAME)
        stack.solutions_template_options.add_parameter(
            self.ecs_task_max_capacity, label="ECSTaskMaxCapacity",
            group=ECS_AUTOSCALING_GROUP_NAME)
        stack.solutions_template_options.add_parameter(
            self.request_count_threshold, label="RequestsPerTargetThreshold",
            group=ECS_AUTOSCALING_GROUP_NAME)
        stack.solutions_template_options.add_parameter(
            self.spot_instance_weight, label="SpotInstanceWeight",
            group=ECS_AUTOSCALING_GROUP_NAME)
            
    def validate_parameters(self):
        """
        Validate parameters at runtime before deployment.
        """
        # Check if CloudFront is not used, then SSL certificate must be provided
        if self.deploy_cloudfront_and_waf_param.default == "No" and not self.ssl_certificate_param.default:
            raise ValueError("SSL Certificate ARN is required when CloudFront and WAF are not installed")
