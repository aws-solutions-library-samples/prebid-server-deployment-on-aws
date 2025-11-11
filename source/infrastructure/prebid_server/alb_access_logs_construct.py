# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import Aws, CfnMapping, CustomResource, RemovalPolicy, Duration
from aws_cdk import aws_iam as iam, aws_s3 as s3, aws_lambda
from constructs import Construct
from aws_solutions.cdk.aws_lambda.layers.aws_lambda_powertools import PowertoolsLayer
from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction
from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
import prebid_server.stack_constants as stack_constants


class AlbAccessLogsConstruct(Construct):
    def __init__(
        self,
        scope,
        id,
        alb_arn,
    ) -> None:
        """
        This construct enables ALB access logs through custom resource.
        """
        super().__init__(scope, id)

        self.alb_arn = alb_arn

        self.alb_access_logs_bucket = s3.Bucket(
            self,
            id="AlbAccessLogsBucket",
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
            enforce_ssl=True,
            object_lock_enabled=True,
            server_access_logs_prefix="access-logs/"
        )

        # Reference: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/enable-access-logging.html
        # For deployment on Gov Cloud or Outposts refer documentation for corresponding account ids
        elb_account_id_table = CfnMapping(
            self,
            "ElbAccountIdTable",
            mapping={
                "us-east-1": {"accountid": "127311923021"},
                "us-east-2": {"accountid": "033677994240"},
                "us-west-1": {"accountid": "027434742980"},
                "us-west-2": {"accountid": "797873946194"},
                "af-south-1": {"accountid": "098369216593"},
                "ap-east-1": {"accountid": "754344448648"},
                "ap-south-1": {"accountid": "718504428378"},
                "ap-northeast-3": {"accountid": "383597477331"},
                "ap-northeast-2": {"accountid": "600734575887"},
                "ap-southeast-1": {"accountid": "114774131450"},
                "ap-southeast-2": {"accountid": "783225319266"},
                "ap-northeast-1": {"accountid": "582318560864"},
                "ca-central-1": {"accountid": "985666609251"},
                "eu-central-1": {"accountid": "054676820928"},
                "eu-west-1": {"accountid": "156460612806"},
                "eu-west-2": {"accountid": "652711504416"},
                "eu-south-1": {"accountid": "635631232127"},
                "eu-west-3": {"accountid": "009996457667"},
                "eu-north-1": {"accountid": "897822967062"},
                "me-south-1": {"accountid": "076674570225"},
                "sa-east-1": {"accountid": "507241528517"},
            },
        )

        elb_account_id = elb_account_id_table.find_in_map(Aws.REGION, "accountid")

        self.enable_alb_access_logs_statement = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            principals=[
                iam.ServicePrincipal("logdelivery.elasticloadbalancing.amazonaws.com"),
                iam.ArnPrincipal(f"arn:aws:iam::{elb_account_id}:root"),
            ],
            actions=["s3:PutObject"],
            resources=[
                f"{self.alb_access_logs_bucket.bucket_arn}/AWSLogs/{Aws.ACCOUNT_ID}/*"
            ],
        )
        self.alb_access_logs_bucket.add_to_resource_policy(
            self.enable_alb_access_logs_statement
        )
        enable_s3_access_logs_statement = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            principals=[
                iam.ServicePrincipal("logging.s3.amazonaws.com")
            ],
            actions=["s3:PutObject"],
            resources=[
                f"{self.alb_access_logs_bucket.bucket_arn}/access-logs/*"
            ]
        )
        self.alb_access_logs_bucket.add_to_resource_policy(
            enable_s3_access_logs_statement
        )

        # Lambda function and Custom resource for enabling access logs for ALB
        self.enable_access_logs_function = SolutionsPythonFunction(
            self,
            "EnableAccessLogsFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "enable_access_logs"
            / "enable_access_logs.py",
            "event_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            description="Lambda function for enabling access logs for alb",
            timeout=Duration.minutes(1),
            memory_size=128,
            architecture=aws_lambda.Architecture.ARM_64,
            layers=[
                PowertoolsLayer.get_or_create(self),
                SolutionsLayer.get_or_create(self),
            ],
        )

        self.enable_access_logs_function.add_environment(
            "SOLUTION_ID", self.node.try_get_context("SOLUTION_ID")
        )
        self.enable_access_logs_function.add_environment(
            "SOLUTION_VERSION", self.node.try_get_context("SOLUTION_VERSION")
        )
        # Suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        self.enable_access_logs_function.node.find_child(id='Resource').add_metadata("guard", {'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        self.enable_alb_access_logs_policy = iam.Policy(
            self,
            "EnableAccessLogsPolicy",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "elasticloadbalancing:ModifyLoadBalancerAttributes",
                        "elasticloadbalancing:DescribeLoadBalancerAttributes",
                    ],
                    resources=[self.alb_arn],
                ),
            ],
        )
        self.enable_access_logs_function.node.add_dependency(
            self.enable_alb_access_logs_policy
        )
        self.enable_access_logs_function.role.attach_inline_policy(
            self.enable_alb_access_logs_policy
        )

        self.enable_access_logs_custom_resource = CustomResource(
            self,
            "EnableAccessLogsCr",
            service_token=self.enable_access_logs_function.function_arn,
            properties={
                "ALB_ARN": self.alb_arn,
                "ALB_LOG_BUCKET": self.alb_access_logs_bucket.bucket_name,
            },
        )

        self.enable_access_logs_custom_resource.node.add_dependency(
            self.alb_access_logs_bucket
        )

        bucket_policy = self.alb_access_logs_bucket.node.find_child(id='Policy')
        if bucket_policy:
            self.enable_access_logs_custom_resource.node.add_dependency(bucket_policy)
