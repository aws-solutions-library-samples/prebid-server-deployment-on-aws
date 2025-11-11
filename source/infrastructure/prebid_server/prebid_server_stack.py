# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

from aws_cdk import (
    Aws,
    CfnCondition,
    CfnOutput,
    CustomResource,
    Duration,
    Fn,
    RemovalPolicy,
    aws_ecs as ecs,
    aws_lambda as awslambda,
    aws_s3 as s3
)
from aws_cdk.aws_lambda import LayerVersion, Code, Runtime
from aws_cdk import aws_iam as iam
from constructs import Construct
from aws_solutions.cdk.stack import SolutionStack
from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
from aws_solutions.cdk.aws_lambda.layers.aws_lambda_powertools import PowertoolsLayer
from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction
import prebid_server.stack_constants as stack_constants

from .prebid_datasync_constructs import DataSyncMonitoring
from .prebid_artifacts_constructs import ArtifactsManager
from .operational_metrics_construct import OperationalMetricsConstruct
from .cloudfront_entry_deployment import CloudFrontEntryDeployment
from .alb_entry_deployment import ALBEntryDeployment
from .vpc_construct import VpcConstruct
from .container_image_construct import ContainerImageConstruct
from .prebid_glue_constructs import GlueEtl
from .cloudtrail_construct import CloudTrailConstruct
from .cache_construct import CacheConstruct
from .stack_cfn_parameters import StackParams


class PrebidServerStack(SolutionStack):
    name = "prebid-server-deployment-on-aws"
    description = "Guidance for Deploying a Prebid Server on AWS"
    template_filename = "prebid-server-deployment-on-aws.template"

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.synthesizer.bind(self)

        stack_params = StackParams(self)

         # Validate parameters
        stack_params.validate_parameters()

        deploy_cloudfront_and_waf_condition = CfnCondition(
            self,
            id="DeployCloudFrontWafCondition",
            expression=Fn.condition_equals(stack_params.deploy_cloudfront_and_waf_param.value_as_string, "Yes")
        )

        deploy_alb_https_condition = CfnCondition(
            self,
            id="DeployALBHttpsCondition",
            expression=Fn.condition_equals(stack_params.deploy_cloudfront_and_waf_param.value_as_string, "No")
        )

        # Create bucket for storing prebid application settings
        stored_requests_bucket = self.create_stored_requests_bucket()

        container_image_construct = ContainerImageConstruct(self, "ContainerImage", self.solutions_template_options,
                                                            stored_requests_bucket)

        # Create artifacts resources for storing solution files
        artifacts_construct = ArtifactsManager(self, "Artifacts")

        vpc_construct = VpcConstruct(self, "VPC",
                                     artifacts_construct.artifacts_bucket,
                                     container_image_construct.docker_configs_manager_bucket,
                                     stored_requests_bucket)

        # Create ECS Cluster
        prebid_cluster = ecs.Cluster(
            self, "PrebidCluster", vpc=vpc_construct.prebid_vpc, container_insights=True
        )

        # Create DataSync resources for monitoring tasks in CloudWatch
        datasync_monitor = DataSyncMonitoring(self, "DataSyncMonitor")
        # Suppress cfn_guard rule for CloudWatch log encryption since they are
        # encrypted by default.
        log_group_l1_construct = datasync_monitor.log_group.node.find_child(id="Resource")
        log_group_l1_construct.add_metadata(
            "guard", {
                'SuppressedRules': ['CLOUDWATCH_LOG_GROUP_ENCRYPTED']
            }
        )

        # Create datasync-s3 layer used by efs_cleanup and glue_trigger lambdas
        datasync_s3_layer = LayerVersion(
            self,
            "DataSyncS3Layer",
            code=Code.from_asset(
                path=os.path.join(
                    f"{Path(__file__).parents[1]}",
                    "aws_lambda_layers/datasync_s3_layer/",
                )
            ),
            layer_version_name=f"{Aws.STACK_NAME}-datasync-s3-layer",
            compatible_runtimes=[Runtime.PYTHON_3_11],
        )

        # Operational Metrics
        op_metrics_construct = OperationalMetricsConstruct(self, "operational-metrics")

        # Create Glue resources for ETL of metrics
        glue_etl = GlueEtl(
            self,
            "MetricsEtl",
            artifacts_construct=artifacts_construct,
            script_file_name="metrics_glue_script.py",
            operational_metrics_layer=op_metrics_construct.operational_metrics_layer
        )
        glue_etl.lambda_function.add_layers(datasync_s3_layer)

        # Cloud Trail Logging
        cloudtrail_logging_s3_buckets = [
            artifacts_construct.artifacts_bucket,
            glue_etl.metrics_source_bucket,
            glue_etl.analytics_source_bucket,
            glue_etl.output_bucket,
        ]
        CloudTrailConstruct(
            self,
            "CloudtrailConstruct",
            s3_buckets=cloudtrail_logging_s3_buckets,
        )

        # Custom resource for Cloudfront header secret
        header_secret_gen_function = SolutionsPythonFunction(
            self,
            "HeaderSecretGenFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "header_secret_lambda"
            / "header_secret_gen.py",
            "event_handler",
            runtime=awslambda.Runtime.PYTHON_3_11,
            description="Lambda function for header secret generation",
            timeout=Duration.seconds(30),
            memory_size=128,
            architecture=awslambda.Architecture.ARM_64,
            layers=[
                PowertoolsLayer.get_or_create(self),
                SolutionsLayer.get_or_create(self),
            ],
            environment={
                "SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
            }
        )
        # Suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        header_secret_gen_function.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        header_secret_gen_custom_resource = CustomResource(
            self,
            "HeaderSecretGenCr",
            service_token=header_secret_gen_function.function_arn,
            properties={},
        )
        x_header_secret_value = header_secret_gen_custom_resource.get_att_string("header_secret_value")

        # Create the cache construct
        cache_construct = CacheConstruct(
            self,
            "CacheConstruct",
            vpc_construct=vpc_construct, 
            op_metrics_layer = op_metrics_construct.operational_metrics_layer
        )

        # Get the ElastiCache cluster ID from the serverless cache
        elasticache_cluster_id = cache_construct.serverless_cache.serverless_cache_name

        CfnOutput(
            self,
            "Header-Key",
            value=x_header_secret_value,
            description="Header Key",
        )

        # Deploy CloudFrontEntryDeployment construct when the user selects the option to use CloudFront as their content delivery network (CDN).
        # In this case, WAF resources are deployed along with CloudFront.
        CloudFrontEntryDeployment(
            self,
            "CloudFrontEntryDeployment",
            stack_params,
            deploy_cloudfront_and_waf_condition,
            artifacts_construct,
            datasync_monitor,
            vpc_construct,
            container_image_construct,
            datasync_s3_layer,
            prebid_cluster,
            glue_etl,
            cache_construct.lambda_target_external_cf,
            cache_construct.lambda_target_internal_cf,
            x_header_secret_value,
            stored_requests_bucket,
            cache_construct.cache_lambda_function.function_name,
            elasticache_cluster_id,
            op_metrics_construct.operational_metrics_layer
        )

        # Deploy this construct when the user wants to use their own CDN.
        # In this case, CloudFront and WAF are excluded from the stack deployment.
        ALBEntryDeployment(
            self,
            "ALBEntryDeployment",
            stack_params,
            deploy_alb_https_condition,
            artifacts_construct,
            datasync_monitor,
            vpc_construct,
            container_image_construct,
            prebid_cluster,
            datasync_s3_layer,
            glue_etl,
            cache_construct.lambda_target_external_alb,
            cache_construct.lambda_target_internal_alb,
            stored_requests_bucket,
            cache_construct.cache_lambda_function.function_name,
            elasticache_cluster_id,
            op_metrics_construct.operational_metrics_layer
        )

    def create_access_logs_bucket(self) -> s3.Bucket:
        """
        Create an S3 bucket for storing access logs.
        """
        access_logs_bucket = s3.Bucket(
            self,
            id="StoredRequestsAccessLogsBucket",
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
            auto_delete_objects=False,
            enforce_ssl=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="AccessLogsLifecycle",
                    enabled=True,
                    expiration=Duration.days(90),
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30)
                        )
                    ],
                    noncurrent_version_expiration=Duration.days(30)
                )
            ]
        )
        
        access_logs_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("logging.s3.amazonaws.com")],
                actions=["s3:PutObject"],
                resources=[f"{access_logs_bucket.bucket_arn}/stored-requests-bucket-logs/*"],
                conditions={
                    "StringEquals": {
                        "aws:SourceAccount": Aws.ACCOUNT_ID
                    }
                }
            )
        )
        
        return access_logs_bucket

    def create_stored_requests_bucket(self) -> s3.Bucket:
        """
        Create an S3 bucket for storing prebid stored requests and stored responses.
        Reference:
        https://github.com/prebid/prebid-server-java/blob/master/docs/application-settings.md#setting-account-configuration-in-s3
        """
        access_logs_bucket = self.create_access_logs_bucket()

        bucket = s3.Bucket(
            self,
            id="Bucket",
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
            auto_delete_objects=False,
            enforce_ssl=True,
            server_access_logs_bucket=access_logs_bucket,
            server_access_logs_prefix="stored-requests-bucket-logs/",
        )

        CfnOutput(self, "PrebidStoredRequestsBucket",
                  value=f"https://{Aws.REGION}.console.aws.amazon.com/s3/home?region={Aws.REGION}&bucket={bucket.bucket_name}",
                  description="Bucket for Prebid Server stored requests"
                  )

        return bucket
