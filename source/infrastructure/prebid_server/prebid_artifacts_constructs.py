# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import Aws, RemovalPolicy, CustomResource
from aws_cdk import aws_iam as iam, aws_lambda, aws_s3 as s3, aws_kms as kms, Duration
from aws_cdk import Stack
from constructs import Construct
from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
from aws_solutions.cdk.aws_lambda.layers.aws_lambda_powertools import PowertoolsLayer
from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction
import prebid_server.stack_constants as stack_constants
import uuid


class ArtifactsManager(Construct):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        self.id = id
        self.artifacts_bucket = self.create_artifact_bucket()
        self.upload_artifacts_function = self.create_custom_resource_lambda()
        self.custom_resource = self.create_custom_resource(
            service_token_function=self.upload_artifacts_function
        )

    def create_artifact_bucket(self) -> s3.Bucket:
        artifact_bucket_key = kms.Key(
            self,
            id="BucketKey",
            description="Artifact Bucket Key",
            enable_key_rotation=True,
            pending_window=Duration.days(30),
            removal_policy=RemovalPolicy.DESTROY,
        )
        kms_bucket_policy = iam.PolicyStatement(
            sid="Allow access to ArtifactBucket",
            principals=[
                iam.ServicePrincipal("s3.amazonaws.com"),
                iam.ServicePrincipal("lambda.amazonaws.com"),
                iam.ServicePrincipal("glue.amazonaws.com"),
            ],
            effect=iam.Effect.ALLOW,
            actions=[
                "kms:Encrypt",
                "kms:Decrypt",
                "kms:ReEncrypt*",
                "kms:GenerateDataKey*",
                "kms:CreateGrant",
                "kms:DescribeKey",
            ],
            resources=["*"],
            conditions={
                "StringEquals": {
                    "aws:SourceAccount": [Aws.ACCOUNT_ID],
                }
            },
        )
        artifact_bucket_key.add_to_resource_policy(kms_bucket_policy)

        # This bucket is used as temporary storage of Glue ETL script, Athena
        # query outputs, and DataSync reports that get used by the EFSCleanup
        # function.
        #
        # This bucket is not used to store customer data.
        bucket = s3.Bucket(
            self,
            id="Bucket",
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption_key=artifact_bucket_key,
            removal_policy=RemovalPolicy.DESTROY,
            versioned=False,  # NOSONAR
            auto_delete_objects=True,
            enforce_ssl=True,
        )

        # Set lifecycle policy for removing datasync reports
        bucket.add_lifecycle_rule(
            expiration=Duration.days(stack_constants.DATASYNC_REPORT_LIFECYCLE_DAYS),
            prefix="datasync",
        )

        # This bucket prefix is used for operation of the glue job in table partitioning
        # Object do not need to be stored and can be removed
        bucket.add_lifecycle_rule(
            expiration=Duration.days(stack_constants.GLUE_ATHENA_OUTPUT_LIFECYCLE_DAYS),
            prefix="athena",
        )

        # Using auto_delete_objects=True causes the S3 construct to generate a Lambda function that handles auto object deletion.
        # We need to suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        Stack.of(bucket).node.try_find_child("Custom::S3AutoDeleteObjectsCustomResourceProvider").node.find_all()[-1].add_metadata("guard", {'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})
        # Suppress the cfn_guard rule for S3 bucket logging. Such logging in not useful for this bucket
        # since it is not used to store customer data.
        bucket.node.find_child(id='Resource').add_metadata("guard", {'SuppressedRules': ['S3_BUCKET_LOGGING_ENABLED']})

        bucket.node.add_dependency(artifact_bucket_key)

        return bucket

    def create_custom_resource_lambda(self) -> SolutionsPythonFunction:
        custom_resource_role = iam.Role(
            self,
            "CrRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "LambdaCrLoggingPolicy": iam.PolicyDocument(
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
                ),
                "LambdaCrS3Policy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "s3:DeleteObject",
                                "s3:GetObject",
                                "s3:PutObject",
                                "s3:ListBucket",
                            ],
                            resources=[
                                self.artifacts_bucket.bucket_arn,
                                f"{self.artifacts_bucket.bucket_arn}/*",
                            ],
                            conditions={
                                "StringEquals": {
                                    "aws:ResourceAccount": [Aws.ACCOUNT_ID]
                                }
                            },
                        )
                    ]
                ),
            },
        )
        custom_resource_role.node.add_dependency(self.artifacts_bucket)
        self.artifacts_bucket.encryption_key.grant_encrypt_decrypt(custom_resource_role)
        role_l1_construct = custom_resource_role.node.find_child(id='Resource')
        role_l1_construct.add_metadata('guard', {'SuppressedRules': ['IAM_NO_INLINE_POLICY_CHECK']})

        upload_artifacts_function = SolutionsPythonFunction(
            self,
            "CrFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "artifacts_bucket_lambda"
            / "upload_files.py",
            "event_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            role=custom_resource_role,
            description="Lambda function for uploading Solution artifacts to S3",
            memory_size=256,
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
        # Suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        upload_artifacts_function.node.find_child(id='Resource').add_metadata("guard", {'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        return upload_artifacts_function

    def create_custom_resource(self, service_token_function) -> CustomResource:
        custom_resource = CustomResource(
            self,
            f"Upload{self.id}Cr",
            service_token=service_token_function.function_arn,
            properties={
                "artifacts_bucket_name": self.artifacts_bucket.bucket_name,
                "custom_resource_uuid": str(uuid.uuid4())  # random uuid to trigger redeploy on stack update
            },
        )
        custom_resource.node.add_dependency(self.upload_artifacts_function)

        return custom_resource
