# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import shutil

from aws_cdk import Aws, RemovalPolicy, CustomResource, Duration
from aws_cdk import (
    aws_iam as iam,
    aws_lambda,
    aws_s3 as s3,
)

from constructs import Construct
from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
from aws_solutions.cdk.aws_lambda.layers.aws_lambda_powertools import PowertoolsLayer
from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction
import prebid_server.stack_constants as stack_constants


class PrebidConfigsManager(Construct):
    """
    Construct that manages Docker configuration files by creating an S3 bucket,
    copying configuration files, and setting up a Lambda function to handle
    the upload of these configurations.

    Attributes:
        docker_build_location (str): The path to the Docker build directory containing configuration files.
        docker_config_bucket (s3.Bucket): The S3 bucket created for storing Docker configuration files.
        upload_docker_configs_function (SolutionsPythonFunction): Lambda function for uploading Docker configs to S3.
        custom_resource (CustomResource): Custom CloudFormation resource that triggers the Lambda function.
    """

    def __init__(self, scope: Construct, id: str, docker_build_location: str, stored_requests_bucket: s3.Bucket, **kwargs):
        """
        Initializes a new instance of the DockerConfigsManager construct.

        Args:
            scope (Construct): The scope in which this construct is defined.
            id (str): The scoped construct ID.
            docker_build_location (str): The file path of the Docker build location.
            **kwargs: Additional keyword arguments for the construct.
        """
        super().__init__(scope, id, **kwargs)
        self.docker_build_location = docker_build_location
        self.id = id
        self.stored_requests_bucket = stored_requests_bucket
        self.copy_config_files()
        self.docker_config_bucket = self.create_docker_config_bucket()
        self.upload_docker_configs_function = self.create_custom_resource_lambda()
        self.custom_resource = self.create_custom_resource(
            service_token_function=self.upload_docker_configs_function
        )

    def copy_config_files(self) -> None:
        """
        Copy prebid config files from the build location to a predefined
        directory structure required by the lambda function.
        """
        config_dirs = [
            "default-config",
            "current-config", 
            "stored_requests",
            "stored_responses",
            "stored_impressions",
            "stored_accounts"
        ]
        
        for config_dir in config_dirs:
            self._copy_directory(config_dir)

    def _copy_directory(self, config_type: str) -> None:
        """
        Copy the specified config type from the docker build location
        to the custom resources path.
        """
        source_dir = f"{self.docker_build_location}/{config_type}"
        destination_path = f"{stack_constants.CUSTOM_RESOURCES_PATH}/prebid_configs_lambda/{config_type}"
        shutil.copytree(source_dir, destination_path, dirs_exist_ok=True)

    def create_docker_config_bucket(self) -> s3.Bucket:
        """
        Create an S3 bucket for storing docker configuration files with
        specific access control and security settings.
        """
        bucket = s3.Bucket(
            self,
            "Bucket",
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            auto_delete_objects=False,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        # Suppress the cfn_guard rule for S3 bucket logging. Such logging in not useful for this bucket
        # since it is not used to store customer data.
        bucket.node.find_child(id='Resource').add_metadata("guard", {'SuppressedRules': ['S3_BUCKET_LOGGING_ENABLED']})

        return bucket

    def create_custom_resource_lambda(self) -> SolutionsPythonFunction:
        """
        Create a Lambda function for managing docker configs with a
        role to allow logging and access to the S3 bucket.
        """
        custom_resource_role = self._create_custom_resource_role()
        role_l1_construct = custom_resource_role.node.default_child
        role_l1_construct.add_metadata(
            'guard', {
                'SuppressedRules': ['IAM_NO_INLINE_POLICY_CHECK']
            }
        )
        return self._create_lambda_function(custom_resource_role)

    def _create_custom_resource_role(self) -> iam.Role:
        """
        Create a role for the Lambda function to allow it access to
        CloudWatch logs and the S3 bucket.
        """
        role = iam.Role(
            self,
            "UploadRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "LambdaCrLoggingPolicy": self._create_logging_policy(),
                "LambdaDockerConfigS3Policy": self._create_s3_access_policy(),
            },
        )
        role.node.add_dependency(self.docker_config_bucket)
        return role

    def _create_logging_policy(self) -> iam.PolicyDocument:
        """
        Create a policy document for logging in CloudWatch.
        """
        return iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                    ],
                    resources=[
                        f"arn:{Aws.PARTITION}:logs:{Aws.REGION}:{Aws.ACCOUNT_ID}:log-group:/aws/lambda/*"
                    ],
                )
            ]
        )

    def _create_s3_access_policy(self) -> iam.PolicyDocument:
        """
        Create a policy document for the Lambda function to access the S3 bucket.
        """
        return iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "s3:DeleteObject",
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:ListBucket",
                    ],
                    resources=[
                        self.docker_config_bucket.bucket_arn,
                        f"{self.docker_config_bucket.bucket_arn}/*",
                        self.stored_requests_bucket.bucket_arn,
                        f"{self.stored_requests_bucket.bucket_arn}/*",
                    ],
                    conditions={
                        "StringEquals": {"aws:ResourceAccount": [Aws.ACCOUNT_ID]}
                    },
                )
            ]
        )

    def _create_lambda_function(self, role: iam.Role) -> SolutionsPythonFunction:
        """
        Create the Lambda function responsible for uploading docker configs
        to the S3 bucket.
        """
        container_config_files_upload_function = SolutionsPythonFunction(
            self,
            "UploadFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "prebid_configs_lambda"
            / "upload_prebid_configs.py",
            "event_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            role=role,
            description="Lambda to upload prebid configs to S3",
            memory_size=256,
            timeout=Duration.minutes(1),
            architecture=aws_lambda.Architecture.ARM_64,
            layers=[
                PowertoolsLayer.get_or_create(self),
                SolutionsLayer.get_or_create(self),
            ],
            environment={
                "SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
            },
        )
        # Suppress the cfn_guard rules indicating that this function should
        # operate within a VPC and have reserved concurrency. A VPC is not
        # necessary for this function because it does not need to access any
        # resources within a VPC. Reserved concurrency is not necessary
        # because this function is invoked infrequently.
        container_config_files_upload_function.node.default_child.add_metadata(
            "guard", {
                'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']
            }
        )
        return container_config_files_upload_function

    def create_custom_resource(self, service_token_function) -> CustomResource:
        """
        Create a custom resource to trigger the Lambda function to
        upload docker configs to the S3 bucket.
        """
        custom_resource = CustomResource(
            self,
            f"UploadDockerConfigs{self.id}Cr",
            service_token=service_token_function.function_arn,
            properties={
                "docker_configs_bucket_name": self.docker_config_bucket.bucket_name,
                "stored_requests_bucket_name": self.stored_requests_bucket.bucket_name,
                # force an update to defaults/ with each version number change
                "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
            },
        )
        custom_resource.node.add_dependency(service_token_function)

        return custom_resource
