# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path

from constructs import Construct
from aws_cdk import (
    CustomResource,
    Duration,
    Aws,
    aws_lambda as awslambda,
    aws_iam as iam,
)
from aws_cdk.aws_iam import Effect, PolicyStatement

from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction
from aws_solutions.cdk.aws_lambda.python.lambda_alarm import (
    SolutionsLambdaFunctionAlarm,
)
from aws_solutions.cdk.aws_lambda.layers.aws_lambda_powertools import PowertoolsLayer
import prebid_server.stack_constants as stack_constants


class OperationalMetricsConstruct(Construct):
    service_name = "operational-metrics"

    def __init__(
        self,
        scope: Construct,
        id: str,
    ) -> None:
        super().__init__(scope, id)

        self._resource_prefix = Aws.STACK_NAME
        self._create_iam_policy_for_custom_resource_lambda()
        self._create_operational_metrics_lambda()
        self._create_operational_metrics_custom_resource()
        self._create_operational_metrics_layer()

    def _create_iam_policy_for_custom_resource_lambda(self):
        secrets_manager_statement = PolicyStatement(
            effect=Effect.ALLOW,
            actions=[
                "secretsmanager:DescribeSecret",
                "secretsmanager:CreateSecret",
                "secretsmanager:DeleteSecret",
                "secretsmanager:UpdateSecret",
                "secretsmanager:PutSecretValue",
                "secretsmanager:GetSecretValue",
            ],
            resources=[
                f"arn:aws:secretsmanager:{Aws.REGION}:{Aws.ACCOUNT_ID}:secret:{Aws.STACK_NAME}-anonymous-metrics-uuid*"
            ],
        )

        self.operational_metrics_lambda_iam_policy = iam.Policy(
            self,
            "OperationalMetricsLambdaIamPolicy",
            statements=[
                secrets_manager_statement,
            ],
        )

    def _create_operational_metrics_lambda(self):
        """
        This function is responsible for creating the anonymous operational metrics uuid in Secrets Manager.
        """

        self._operational_metrics_lambda = SolutionsPythonFunction(
            self,
            "CreateOperationalMetrics",
            stack_constants.CUSTOM_RESOURCES_PATH / "operational_metrics" / "ops_metrics.py",
            "event_handler",
            runtime=awslambda.Runtime.PYTHON_3_11,
            description="Lambda function for custom resource for the creating anonymous operational metrics",
            timeout=Duration.minutes(5),
            memory_size=256,
            architecture=awslambda.Architecture.ARM_64,
            environment={
                "SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
                "SOLUTION_NAME": self.node.try_get_context("SOLUTION_NAME"),
                "SOLUTION_APPLICATION_TYPE": stack_constants.SOLUTION_APPLICATION_TYPE,
                "STACK_NAME": Aws.STACK_NAME,
                "RESOURCE_PREFIX": Aws.STACK_NAME,
                "METRICS_NAMESPACE": self.node.try_get_context("METRICS_NAMESPACE"),
            },
            layers=[
                SolutionsLayer.get_or_create(self),
                PowertoolsLayer.get_or_create(self),
            ],
        )
        # Suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        self._operational_metrics_lambda.node.find_child(id='Resource').add_metadata("guard", {'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        SolutionsLambdaFunctionAlarm(
            self,
            id="operational-metrics-lambda-alarm",
            alarm_name=f"{self._resource_prefix}-operational-metrics-lambda-alarm",
            lambda_function=self._operational_metrics_lambda,
        )

        self.operational_metrics_lambda_iam_policy.attach_to_role(
            self._operational_metrics_lambda.role
        )
        role_l1_construct = self._operational_metrics_lambda.role.node.find_child(id='Resource')
        role_l1_construct.add_metadata('guard', {'SuppressedRules': ['IAM_NO_INLINE_POLICY_CHECK']})


    def _create_operational_metrics_custom_resource(self):
        """
        This function creates the customer resource for creating the anonymous operational metrics.
        """
        self._operational_metrics_custom_resource = CustomResource(
            self,
            "OperationalMetricsCustomResource",
            service_token=self._operational_metrics_lambda.function_arn,
        )

        self._operational_metrics_custom_resource.node.add_dependency(
            self.operational_metrics_lambda_iam_policy
        )
        
    def _create_operational_metrics_layer(self):
        """
        This function creates the op-metrics lambda layer used by lambda functions that collect and report
        custom operational metrics
        """
        self.operational_metrics_layer = awslambda.LayerVersion(
            self,
            "metrics-layer",
            code=awslambda.Code.from_asset(
                path=os.path.join(
                    f"{Path(__file__).parents[1]}", "aws_lambda_layers/metrics_layer/"
                )
            ),
            layer_version_name=f"{Aws.STACK_NAME}-metrics-layer",
            compatible_runtimes=[awslambda.Runtime.PYTHON_3_11],
        )
        
