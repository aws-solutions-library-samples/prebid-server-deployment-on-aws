# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import json
from pathlib import Path

from aws_cdk import Aws, RemovalPolicy, Duration, CustomResource
from aws_cdk import (
    aws_iam as iam,
    aws_s3 as s3,
    aws_glue as glue,
    aws_kms as kms,
    aws_lambda,
    aws_datasync as datasync,
)
from aws_cdk.aws_lambda import LayerVersion, Code, Runtime
from constructs import Construct

from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction
from aws_solutions.cdk.aws_lambda.layers.aws_lambda_powertools import PowertoolsLayer
from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
from .prebid_artifacts_constructs import ArtifactsManager
import prebid_server.stack_constants as stack_constants

PUT_OBJECT_ACTION = "s3:PutObject"
DATASYNC_SERVICE_PRINCIPAL = iam.ServicePrincipal("datasync.amazonaws.com")
S3_READ_ACTIONS = ["s3:GetObject", "s3:ListBucket"]
ACCOUNT_ID_CONDITION = {"StringEquals": {stack_constants.RESOURCE_NAMESPACE: [Aws.ACCOUNT_ID]}}
GLUE_IAM_SERVICE_PRINCIPAL = "glue.amazonaws.com"


class S3Location(Construct):
    def __init__(
            self,
            scope: Construct,
            s3_location_id: str,
            s3_bucket: s3.Bucket,
    ):
        super().__init__(scope, s3_location_id)

        self.s3_bucket = s3_bucket
        self.S3_PERMISSIONS = [
            "s3:GetBucketLocation",
            "s3:ListBucketMultipartUploads",
            "s3:AbortMultipartUpload",
            "s3:DeleteObject",
            "s3:ListMultipartUploadParts",
            "s3:GetObjectTagging",
            "s3:PutObjectTagging",
            PUT_OBJECT_ACTION,
        ]
        self.S3_PERMISSIONS.extend(S3_READ_ACTIONS)

        self.s3_location = self._create_s3_location(s3_location_id)

    def _create_s3_location(self, s3_location_id):
        """
        This function creates an S3 Location resource used for DataSync Tasks involving S3
        """
        # create Datasync role to access S3 bucket
        datasync_s3_role = iam.Role(
            self,
            "Role",
            assumed_by=DATASYNC_SERVICE_PRINCIPAL,
        )
        datasync_s3_policy = iam.Policy(
            self,
            "Policy",
            statements=[
                iam.PolicyStatement(
                    actions=self.S3_PERMISSIONS,
                    resources=[
                        self.s3_bucket.bucket_arn,
                        f"{self.s3_bucket.bucket_arn}/*",
                    ],
                    conditions=ACCOUNT_ID_CONDITION,
                ),
            ],
        )
        datasync_s3_role.attach_inline_policy(datasync_s3_policy)
        self.s3_bucket.encryption_key.grant_encrypt_decrypt(datasync_s3_role)
        datasync_s3_policy.node.add_dependency(self.s3_bucket)

        # Create bucket policy to grant DataSync access
        datasync_bucket_policy_statement = iam.PolicyStatement(
            principals=[iam.ArnPrincipal(datasync_s3_role.role_arn)],
            actions=self.S3_PERMISSIONS,
            resources=[
                self.s3_bucket.bucket_arn,
                f"{self.s3_bucket.bucket_arn}/*",
            ],
            conditions=ACCOUNT_ID_CONDITION,
        )
        bucket_policy = s3.BucketPolicy(
            self,
            "BucketPolicy",
            bucket=self.s3_bucket,
            removal_policy=RemovalPolicy.RETAIN,
        )
        bucket_policy.document.add_statements(datasync_bucket_policy_statement)
        bucket_policy.node.add_dependency(self.s3_bucket)

        # Create DataSync S3 location
        datasync_s3_location = datasync.CfnLocationS3(
            self,
            "Location",
            s3_bucket_arn=self.s3_bucket.bucket_arn,
            s3_config=datasync.CfnLocationS3.S3ConfigProperty(
                bucket_access_role_arn=datasync_s3_role.role_arn
            ),
        )

        if s3_location_id == "S3Location":
            # For backward compatibility, maintain the logical ID of S3 location of the bucket storing Prebid metrics
            # across solution versions to prevent creation of a new S3 location during stack updates.
            # DataSyncMetricsS3Location7EAA1172 is the logical id for the bucket in the v1.0.x solution template.
            datasync_s3_location.override_logical_id("DataSyncMetricsS3Location7EAA1172")

        datasync_s3_location.node.add_dependency(self.s3_bucket)
        datasync_s3_location.node.add_dependency(bucket_policy)

        return datasync_s3_location


class GlueEtl(Construct):
    def __init__(
            self,
            scope: Construct,
            id: str,
            artifacts_construct: ArtifactsManager,
            script_file_name: str,
            operational_metrics_layer: LayerVersion,
    ):
        super().__init__(scope, id)

        self.id = id
        self._resource_prefix = Aws.STACK_NAME
        self.artifacts_construct = artifacts_construct
        self.artifacts_bucket = artifacts_construct.artifacts_bucket
        self.file_name = script_file_name
        self.metrics_layer = operational_metrics_layer

        self.GLUE_RESOURCE_PREFIX = f"{Aws.STACK_NAME}-{Aws.REGION}-{self.id.lower()}"
        self.GLUE_JOB_NAME = f"{self.GLUE_RESOURCE_PREFIX}-job"
        self.GLUE_DATABASE_NAME = f"{self.GLUE_RESOURCE_PREFIX}-database"
        self.GLUE_WORKFLOW_NAME = f"{self.GLUE_RESOURCE_PREFIX}-workflow"

        fp = Path(__file__).absolute().parents[1] / "prebid_server"
        with open(f"{fp}/prebid_metrics_schema.json") as f:
            self.TABLE_SCHEMA_MAP = json.load(f)

        self._create_source_buckets()
        self.metrics_s3_location = S3Location(self, "S3Location", s3_bucket=self.metrics_source_bucket)
        # analytics logic is not implemented for glue yet, but keeping the s3 location obj here for future ETL work
        self.analytics_s3_location = S3Location(self, "AnalyticsS3Location", s3_bucket=self.analytics_source_bucket)
        self._create_lamda_layer()
        self.output_bucket = self._create_output_bucket()
        self._create_glue_database()
        self.glue_job = self._create_glue_job()
        self.lambda_function = self._create_glue_job_trigger()

    def _create_source_buckets(self):
        source_buckets = {}
        for bucket in ["Metrics", "Analytics"]:
            # We initiate this class for the DataSync {bucket} Task
            datasync_logs_bucket_key = kms.Key(
                self,
                id=f"DataSync{bucket}BucketKey",
                description=f"{self.id} Bucket Key",
                enable_key_rotation=True,
                pending_window=Duration.days(30),
                removal_policy=RemovalPolicy.RETAIN,
            )
            kms_bucket_policy = iam.PolicyStatement(
                sid=f"Allow access to {self.id}Bucket",
                principals=[
                    iam.ServicePrincipal("s3.amazonaws.com"),
                    DATASYNC_SERVICE_PRINCIPAL,
                    iam.ServicePrincipal(GLUE_IAM_SERVICE_PRINCIPAL),
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
                        "aws:SourceAccount": [f"{Aws.ACCOUNT_ID}"],
                    }
                },
            )
            datasync_logs_bucket_key.add_to_resource_policy(kms_bucket_policy)

            source_bucket = s3.Bucket(
                self,
                f"DataSync{bucket}Bucket",
                object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
                access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                encryption_key=datasync_logs_bucket_key,
                removal_policy=RemovalPolicy.RETAIN,
                versioned=True,
                enforce_ssl=True,
                object_lock_enabled=True,
            )

            if source_bucket == "Metrics":
                # For backward compatibility, maintain the bucket's logical ID across solution versions to prevent creation of
                # a new bucket to store Prebid metrics data during stack updates.
                # DataSyncMetricsBucket76641540 is the logical id for the bucket in the v1.0.x solution template.
                source_bucket.node.default_child.override_logical_id(f"DataSyncMetricsBucket76641540")

            # Suppress the cfn_guard rule for S3 bucket logging since Cloudtrail logging has been enabled for this bucket.
            source_bucket.node.default_child.add_metadata("guard", {'SuppressedRules': ['S3_BUCKET_LOGGING_ENABLED']})

            source_bucket.node.add_dependency(datasync_logs_bucket_key)

            source_buckets[bucket] = source_bucket

        self.metrics_source_bucket = source_buckets["Metrics"]
        self.analytics_source_bucket = source_buckets["Analytics"]

    def _create_lamda_layer(self):
        self.powertools_layer = PowertoolsLayer.get_or_create(self)

    def _create_output_bucket(self) -> s3.Bucket:
        """
        This function creates the S3 Bucket where Glue outputs transformed metric files
        """
        glue_bucket_key = kms.Key(
            self,
            id="BucketKey",
            description="Metrics ETL Bucket Key",
            enable_key_rotation=True,
            pending_window=Duration.days(30),
            removal_policy=RemovalPolicy.RETAIN,
        )
        kms_bucket_policy = iam.PolicyStatement(
            sid="Allow access to Metrics ETL Bucket",
            principals=[
                iam.ServicePrincipal("s3.amazonaws.com"),
                iam.ServicePrincipal(GLUE_IAM_SERVICE_PRINCIPAL),
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
                    "aws:SourceAccount": [f"{Aws.ACCOUNT_ID}"],
                }
            },
        )
        glue_bucket_key.add_to_resource_policy(kms_bucket_policy)
        bucket = s3.Bucket(
            self,
            id="Bucket",
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption_key=glue_bucket_key,
            removal_policy=RemovalPolicy.RETAIN,
            enforce_ssl=True,
            object_lock_enabled=True,
            versioned=True,
        )
        # Suppress the cfn_guard rule for S3 bucket logging since Cloudtrail logging has been enabled for this bucket.
        bucket.node.default_child.add_metadata("guard", {'SuppressedRules': ['S3_BUCKET_LOGGING_ENABLED']})
        return bucket

    def _create_glue_database(self) -> None:
        """
        This function creates the Glue Database and Tables to catalog the transformed metrics in S3
        """
        # Create glue database
        database = glue.CfnDatabase(
            self,
            "Database",
            catalog_id=Aws.ACCOUNT_ID,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=self.GLUE_DATABASE_NAME
            ),
        )

        # Iterate over the metrics schema to create the tables in Glue Catalog with the proper datatypes
        for table_name, schema in self.TABLE_SCHEMA_MAP.items():
            table_columns = []
            for column_name, data_type in schema.items():
                col = glue.CfnTable.ColumnProperty(name=column_name, type=data_type)
                table_columns.append(col)

            table = glue.CfnTable(
                self,
                f"{table_name}Table",
                catalog_id=Aws.ACCOUNT_ID,
                database_name=self.GLUE_DATABASE_NAME,
                table_input=glue.CfnTable.TableInputProperty(
                    name=table_name.lower(),
                    partition_keys=[
                        glue.CfnTable.ColumnProperty(name="year_month", type="string")
                    ],
                    table_type="EXTERNAL_TABLE",
                    storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                        columns=table_columns,
                        compressed=True,
                        location=f"s3://{self.output_bucket.bucket_name}/type={table_name.lower()}/",
                        stored_as_sub_directories=True,
                        parameters={"classification": "parquet"},
                        input_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                        output_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                        serde_info=glue.CfnTable.SerdeInfoProperty(
                            name="ParquetHiveSerDe",
                            serialization_library="org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                        ),
                    ),
                ),
            )

            table.node.add_dependency(database)

    def _create_glue_job(self) -> glue.CfnJob:
        """
        This function creates an IAM Role for the Glue Job to assume during execution
        """
        # Create role for the glue job
        glue_job_role = iam.Role(
            self,
            "JobRole",
            assumed_by=iam.ServicePrincipal(GLUE_IAM_SERVICE_PRINCIPAL),
        )

        # Iterate over the metrics schema to get all the table names that Glue will need IAM permission to access
        glue_resources = [
            f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:table/{self.GLUE_DATABASE_NAME}/{table_name.lower()}"
            for table_name in self.TABLE_SCHEMA_MAP.keys()
        ]
        glue_resources.extend(
            [
                f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:catalog",
                f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:database/{self.GLUE_DATABASE_NAME}",
            ]
        )

        # Create policy for the glue job role
        glue_job_policy = iam.Policy(
            self,
            "JobPolicy",
            statements=[
                iam.PolicyStatement(
                    actions=S3_READ_ACTIONS,
                    resources=[
                        self.artifacts_bucket.bucket_arn,
                        self.metrics_source_bucket.bucket_arn,
                        self.output_bucket.bucket_arn,
                        f"{self.artifacts_bucket.bucket_arn}/*",
                        f"{self.metrics_source_bucket.bucket_arn}/*",
                        f"{self.output_bucket.bucket_arn}/*",
                    ],
                    conditions=ACCOUNT_ID_CONDITION,
                ),
                iam.PolicyStatement(
                    actions=[
                        PUT_OBJECT_ACTION,
                    ],
                    resources=[
                        self.output_bucket.bucket_arn,
                        f"{self.output_bucket.bucket_arn}/*",
                    ],
                    conditions=ACCOUNT_ID_CONDITION,
                ),
                iam.PolicyStatement(
                    actions=[
                        "glue:GetTable",
                        "glue:GetDatabase",
                        "glue:BatchCreatePartition",
                        "glue:CreatePartition",
                        "glue:GetPartition",
                        "glue:GetPartitions",
                        "glue:UpdatePartition",
                        "glue:DeletePartition",
                        "glue:BatchDeletePartition",
                        "glue:BatchGetPartition",
                    ],
                    resources=glue_resources,
                ),
                iam.PolicyStatement(
                    actions=[
                        "athena:StartQueryExecution",
                    ],
                    resources=[
                        f"arn:aws:athena:{Aws.REGION}:{Aws.ACCOUNT_ID}:workgroup/*"
                    ],
                ),
                iam.PolicyStatement(
                    actions=["s3:GetBucketLocation", PUT_OBJECT_ACTION],
                    resources=[
                        self.artifacts_bucket.bucket_arn,
                        f"{self.artifacts_bucket.bucket_arn}/*",
                    ],
                    conditions=ACCOUNT_ID_CONDITION,
                ),
                iam.PolicyStatement(
                    actions=[
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                    ],
                    resources=[
                        f"arn:{Aws.PARTITION}:logs:{Aws.REGION}:{Aws.ACCOUNT_ID}:log-group:/aws-glue/*"
                    ],
                ),
                iam.PolicyStatement(
                    actions=[
                        "cloudwatch:PutMetricData",
                    ],
                    resources=[
                        "*"  # NOSONAR
                    ],
                ),
            ],
        )

        glue_job_role.attach_inline_policy(glue_job_policy)
        glue_job_policy.node.add_dependency(self.artifacts_bucket)
        glue_job_policy.node.add_dependency(self.metrics_source_bucket)
        glue_job_policy.node.add_dependency(self.output_bucket)
        self.artifacts_bucket.encryption_key.grant_encrypt_decrypt(glue_job_role)
        self.metrics_source_bucket.encryption_key.grant_encrypt_decrypt(glue_job_role)
        self.output_bucket.encryption_key.grant_encrypt_decrypt(glue_job_role)

        # Create the metrics etl glue job
        glue_job = glue.CfnJob(
            self,
            "Job",
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{self.artifacts_bucket.bucket_name}/glue/{self.file_name}",
            ),
            glue_version="4.0",
            role=glue_job_role.role_arn,
            default_arguments={
                "--SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                "--SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
                "--SOURCE_BUCKET": self.metrics_source_bucket.bucket_name,
                "--OUTPUT_BUCKET": self.output_bucket.bucket_name,
                "--DATABASE_NAME": self.GLUE_DATABASE_NAME,
                "--AWS_REGION": Aws.REGION,
                "--ATHENA_QUERY_BUCKET": self.artifacts_bucket.bucket_name,
                "--METRICS_NAMESPACE": self.node.try_get_context("METRICS_NAMESPACE"),
                "--RESOURCE_PREFIX": Aws.STACK_NAME,
                "--enable-continuous-cloudwatch-log": "true",
                "--enable-metrics": "true",
                "--enable-observability-metrics": "true",
            },
            name=self.GLUE_JOB_NAME,
            execution_property=glue.CfnJob.ExecutionPropertyProperty(
                max_concurrent_runs=stack_constants.GLUE_MAX_CONCURRENT_RUNS
            ),
            timeout=stack_constants.GLUE_TIMEOUT_MINS,
        )

        return glue_job

    def _create_glue_job_trigger(self) -> SolutionsPythonFunction:
        """
        This function creates a Lambda function to trigger the Glue Job when DataSync completes a file transfer task for metrics
        """
        # Create metrics etl lambda for triggering the glue job
        lambda_function = SolutionsPythonFunction(
            self,
            "TriggerFunction",
            Path(__file__).absolute().parents[0]
            / "glue_trigger_lambda"
            / "start_glue_job.py",
            "event_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            description="Lambda function for triggering metrics Glue Etl",
            memory_size=256,
            timeout=Duration.minutes(5),
            architecture=aws_lambda.Architecture.ARM_64,
            layers=[
                self.powertools_layer,
                SolutionsLayer.get_or_create(self),
                self.metrics_layer,
            ],
            environment={
                "SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
                "GLUE_JOB_NAME": self.GLUE_JOB_NAME,
                "RESOURCE_PREFIX": Aws.STACK_NAME,
                "METRICS_NAMESPACE": self.node.try_get_context("METRICS_NAMESPACE"),
                "DATASYNC_REPORT_BUCKET": self.artifacts_bucket.bucket_name,
                "AWS_ACCOUNT_ID": Aws.ACCOUNT_ID,
            },
        )
        # Suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        lambda_function.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        # Create metrics etl lambda iam policy permissions
        lambda_policy = iam.Policy(
            self,
            "LambdaPolicy",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "cloudwatch:PutMetricData",
                    ],
                    resources=[
                        "*"  # NOSONAR
                    ],
                    conditions={
                        "StringEquals": {
                            "cloudwatch:namespace": self.node.try_get_context(
                                "METRICS_NAMESPACE"
                            )
                        }
                    },
                ),
                iam.PolicyStatement(
                    actions=[
                        "glue:StartJobRun",
                    ],
                    resources=[
                        f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:job/{self.GLUE_RESOURCE_PREFIX}-job"
                    ],
                ),
                iam.PolicyStatement(
                    actions=S3_READ_ACTIONS,
                    resources=[
                        self.artifacts_bucket.bucket_arn,
                        f"{self.artifacts_bucket.bucket_arn}/*",
                    ],
                    conditions=ACCOUNT_ID_CONDITION,
                ),
            ],
        )
        lambda_function.role.attach_inline_policy(lambda_policy)
        self.artifacts_bucket.encryption_key.grant_encrypt_decrypt(lambda_function.role)

        # Add permission to Lambda to allow eventbridge rule to trigger metrics etl lambda on successful datasync executions of metrics
        lambda_function.add_permission(
            id="InvokeLambda",
            principal=iam.ServicePrincipal("events.amazonaws.com"),
            action="lambda:InvokeFunction",
        )

        return lambda_function
