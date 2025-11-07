# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import json

from constructs import Construct
from aws_cdk import (
    Duration,
    Aws,
    aws_lambda as awslambda,
    aws_iam as iam,
    Fn,
)
from aws_cdk.aws_iam import Effect, PolicyStatement
from aws_cdk.aws_events import CfnRule
from aws_cdk.aws_lambda import CfnPermission

import prebid_server.stack_constants as stack_constants
from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction


class CloudwatchMetricsConstruct(Construct):
    service_name = "cloudwatch-metrics"

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id)

        self._resource_prefix = Aws.STACK_NAME
        self._create_iam_policy()
        self._create_cloudwatch_metrics_function(**kwargs)
        self._create_event_bridge_rule()

    def _create_iam_policy(self):
        secrets_manager_statement = PolicyStatement(
            effect=Effect.ALLOW,
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                f"arn:aws:secretsmanager:{Aws.REGION}:{Aws.ACCOUNT_ID}:secret:{Aws.STACK_NAME}-anonymous-metrics-uuid*"
            ],
        )
        cloudwatch_statement = PolicyStatement(
            effect=Effect.ALLOW,
            actions=[
                "cloudwatch:GetMetricStatistics",
                "cloudwatch:ListMetrics",
                "cloudwatch:PutMetricData",
            ],
            resources=[
                "*"  # NOSONAR
            ],
        )

        ec2_statement = PolicyStatement(
            effect=Effect.ALLOW,
            actions=["ec2:DescribeNatGateways"],
            resources=[
                "*"  # NOSONAR
            ],
        )

        self.cloudwatch_metrics_lambda_iam_policy = iam.Policy(
            self,
            "CloudwatchMetricsLambdaIamPolicy",
            statements=[secrets_manager_statement, cloudwatch_statement, ec2_statement],
        )

    def _create_cloudwatch_metrics_function(self, **kwargs):
        """
        This function is responsible for aggregating and reporting metrics.
        """
        self.cloudwatch_metrics_function = SolutionsPythonFunction(
            self,
            "CloudwatchMetricsFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "cloudwatch_metrics"
            / "cloudwatch_metrics_report.py",
            "event_handler",
            runtime=awslambda.Runtime.PYTHON_3_11,
            description="Lambda function for reporting metrics",
            timeout=Duration.minutes(5),
            memory_size=256,
            architecture=awslambda.Architecture.ARM_64,
            environment={
                "STACK_NAME": Aws.STACK_NAME,
                "SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
                "METRICS_NAMESPACE": self.node.try_get_context("METRICS_NAMESPACE"),
                "CF_DISTRIBUTION_ID": kwargs.get("cloud_front_id", ""),
                "SUBNET_IDS": json.dumps(kwargs["public_subnets"]),
                "LOAD_BALANCER_NAME": kwargs["load_balancer_full_name"],
                "SEND_ANONYMIZED_DATA": self._send_anonymous_usage_data(),
                "ELASTICACHE_CLUSTER_ID": kwargs["elasticache_cluster_id"]
            },
            layers=[SolutionsLayer.get_or_create(self)],
        )
        # Suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        self.cloudwatch_metrics_function.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        self.cloudwatch_metrics_lambda_iam_policy.attach_to_role(self.cloudwatch_metrics_function.role)

    def _create_event_bridge_rule(self):
        send_cloudwatch_metrics_rule = CfnRule(
            self,
            "CloudwatchMetricsRule",
            description="Send metrics daily at 5am UTC",
            schedule_expression="cron(0 5 * * ? *)",
            state="ENABLED",
            targets=[
                CfnRule.TargetProperty(
                    arn=self.cloudwatch_metrics_function.function_arn,
                    id="send-cloudwatch-metrics",
                )
            ],
        )

        CfnPermission(
            self,
            "CloudwatchMetricsPermissions",
            action="lambda:InvokeFunction",
            function_name=self.cloudwatch_metrics_function.function_arn,
            principal="events.amazonaws.com",
            source_arn=send_cloudwatch_metrics_rule.attr_arn,
        )

    def _send_anonymous_usage_data(self) -> str:
        return Fn.find_in_map("Solution", "Data", "SendAnonymizedData", default_value="Yes")
