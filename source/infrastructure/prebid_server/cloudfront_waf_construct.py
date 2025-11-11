# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import (
    aws_lambda,
    aws_cloudfront as cloudfront,
    aws_kms as kms,
    aws_s3 as s3,
    aws_cloudfront_origins as cloudfront_origins,
    aws_iam as iam
)

from aws_cdk import Aws, CustomResource, Duration, RemovalPolicy
from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
from aws_solutions.cdk.aws_lambda.layers.aws_lambda_powertools import PowertoolsLayer
from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction
from constructs import Construct
import prebid_server.stack_constants as stack_constants


class CloudFrontWafConstruct(Construct):
    def __init__(
            self,
            scope,
            id,
            prebid_alb,
            x_header_secret_value
    ) -> None:
        """
        This construct creates CloudFront and Waf resources
        """
        super().__init__(scope, id)

        # create s3 bucket for cloudfront distribution access logs
        cloudfront_access_logs_bucket_key = kms.Key(
            self,
            id="CloudFrontAccessLogsBucketKey",
            description="CloudFront Access Logging Bucket Key",
            enable_key_rotation=True,
            pending_window=Duration.days(30),
            removal_policy=RemovalPolicy.RETAIN,
        )
        kms_bucket_policy = iam.PolicyStatement(
            principals=[iam.ServicePrincipal("delivery.logs.amazonaws.com")],
            effect=iam.Effect.ALLOW,
            actions=["kms:GenerateDataKey*", "kms:Decrypt"],
            resources=["*"],
            conditions={
                "StringEquals": {
                    "aws:SourceAccount": [Aws.ACCOUNT_ID],
                }
            },
        )
        cloudfront_access_logs_bucket_key.add_to_resource_policy(kms_bucket_policy)

        cloudfront_access_logs_bucket = s3.Bucket(
            self,
            id="CloudFrontAccessLogsBucket",
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            encryption_key=cloudfront_access_logs_bucket_key,
            access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
            enforce_ssl=True,
            object_lock_enabled=True,
        )
        # For backward compatibility, maintain the bucket's logical ID across solution versions to prevent creation of a new log bucket during stack updates.
        # CloudFrontAccessLogsBucket337A74EE is the logical id for the bucket in the v1.0.x solution template.
        cloudfront_access_logs_bucket.node.default_child.override_logical_id("CloudFrontAccessLogsBucket337A74EE")
        # Suppress the cfn_guard rule for S3 bucket logging. Such logging in not useful for this bucket
        # since it is not used to store customer data.
        cloudfront_access_logs_bucket.node.default_child.add_metadata("guard", {
            'SuppressedRules': ['S3_BUCKET_LOGGING_ENABLED']})

        # Create a reference to a managed CloudFront Response Headers Policy
        response_headers_policy = cloudfront.ResponseHeadersPolicy.from_response_headers_policy_id(
            self,
            "CloudFrontResponseHeadersPolicy",
            stack_constants.RESPONSE_HEADERS_POLICY_ID,
        )

        # Custom resource for getting prefix list ID
        get_prefix_id_function = SolutionsPythonFunction(
            self,
            "GetPrefixIdFunction",
            stack_constants.CUSTOM_RESOURCES_PATH / "prefix_id_lambda" / "get_prefix_id.py",
            "event_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            description="Lambda function for getting prefix list ID",
            timeout=Duration.minutes(1),
            memory_size=256,
            architecture=aws_lambda.Architecture.ARM_64,
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
        get_prefix_id_function.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        get_prefix_id_custom_resource = CustomResource(
            self,
            "GetPrefixIdCr",
            service_token=get_prefix_id_function.function_arn,
            properties={},
        )

        get_prefix_id_function_policy = iam.Policy(
            self,
            "GetPrefixIdFunctionPolicy",
            statements=[
                iam.PolicyStatement(
                    actions=["ec2:DescribeManagedPrefixLists"], resources=["*"]
                )
            ],
        )
        get_prefix_id_function.role.attach_inline_policy(get_prefix_id_function_policy)

        get_prefix_id_function.node.add_dependency(get_prefix_id_function_policy)
        get_prefix_id_custom_resource.node.add_dependency(get_prefix_id_function)

        self.prefix_list_id = get_prefix_id_custom_resource.get_att_string("prefix_list_id")

        #  Custom resource creating for Waf Web Acl
        waf_web_acl_function_waf_policy = iam.Policy(
            self,
            "WafWebAclFunctionWafPolicy",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "wafv2:CreateWebACL",
                        "wafv2:DeleteWebACL",
                        "wafv2:UpdateWebACL",
                    ],
                    resources=[
                        f"arn:aws:wafv2:us-east-1:{Aws.ACCOUNT_ID}:global/webacl/PrebidWaf-*",
                        f"arn:aws:wafv2:us-east-1:{Aws.ACCOUNT_ID}:global/managedruleset/*/*",
                    ],
                )
            ],
        )

        create_waf_web_acl_function = SolutionsPythonFunction(
            self,
            "CreateWafWebAclFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "waf_webacl_lambda"
            / "create_waf_webacl.py",
            "event_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            description="Lambda function for creating Waf Web Acl",
            timeout=Duration.minutes(1),
            memory_size=256,
            architecture=aws_lambda.Architecture.ARM_64,
            layers=[
                PowertoolsLayer.get_or_create(self),
                SolutionsLayer.get_or_create(self),
            ],
            environment={
                "SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
                "SOLUTION_APPLICATION_TYPE": stack_constants.SOLUTION_APPLICATION_TYPE,
                "SOLUTION_NAME": self.node.try_get_context("SOLUTION_NAME"),
            }
        )

        # Suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        create_waf_web_acl_function.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        create_waf_web_acl_custom_resource = CustomResource(
            self,
            "WafWebAclCr",
            service_token=create_waf_web_acl_function.function_arn,
            properties={},
        )

        create_waf_web_acl_function.node.add_dependency(waf_web_acl_function_waf_policy)

        create_waf_web_acl_function.role.attach_inline_policy(waf_web_acl_function_waf_policy)

        waf_webacl_arn = create_waf_web_acl_custom_resource.get_att_string("webacl_arn")
        self.waf_webacl_name = create_waf_web_acl_custom_resource.get_att_string("webacl_name")
        waf_webacl_id = create_waf_web_acl_custom_resource.get_att_string("webacl_id")
        waf_webacl_locktoken = create_waf_web_acl_custom_resource.get_att_string("webacl_locktoken")

        # Define the single ALB origin
        origin = cloudfront_origins.LoadBalancerV2Origin(
            prebid_alb,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            custom_headers={stack_constants.X_SECRET_HEADER_NAME: x_header_secret_value},
        )

        # define the default cache behavior
        default_behavior = cloudfront.BehaviorOptions(
            origin=origin,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            response_headers_policy=response_headers_policy,
        )

        # create a custom cache policy
        cache_policy = cloudfront.CachePolicy(
            self,
            "CustomCachePolicy",
            cache_policy_name=f"{Aws.STACK_NAME}CachePolicy-{Aws.REGION}",
            comment="Cache policy for /cache* paths with uuid query string and origin header",
            query_string_behavior=cloudfront.CacheQueryStringBehavior.allow_list("uuid"),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True
        )

        # Create a 30-second cache policy for /cache/health
        health_cache_policy = cloudfront.CachePolicy(
            self,
            "HealthCachePolicy",
            cache_policy_name=f"{Aws.STACK_NAME}HealthCachePolicy-{Aws.REGION}",
            comment="No cache policy for /cache/health path",
            default_ttl=Duration.seconds(30),
            min_ttl=Duration.seconds(30),
            max_ttl=Duration.seconds(30)
        )

        # Define the custom behavior for /cache* paths
        cache_behavior = cloudfront.BehaviorOptions(
            origin=origin,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
            cache_policy=cache_policy,
            response_headers_policy=response_headers_policy,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
        )

        health_cache_behavior = cloudfront.BehaviorOptions(
            origin=origin,
            allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
            cache_policy=health_cache_policy,
            response_headers_policy=response_headers_policy,
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
        )

        # create the cloudfront distribution
        self.prebid_cloudfront_distribution = cloudfront.Distribution(
            self,
            "PrebidCloudFrontDist",
            comment="Guidance for Deploying a Prebid Server on AWS",
            default_behavior=default_behavior,
            additional_behaviors={
                "/cache/health": health_cache_behavior,
                "/cache*": cache_behavior  # path pattern is specified here
            },
            web_acl_id=waf_webacl_arn,
            enable_logging=True,
            log_bucket=cloudfront_access_logs_bucket,
        )

        # Suppress cfn_guard rule requiring TLS certificates. The implementation guide
        # provides guidance for using custom domains and certificates.
        self.prebid_cloudfront_distribution.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['CLOUDFRONT_MINIMUM_PROTOCOL_VERSION_RULE']})

        # Custom resource for deleting Waf Web Acl
        waf_web_acl_function_cloudfront_policy = iam.Policy(
            self,
            "WafWebAclFunctionCloudFrontPolicy",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "cloudfront:GetDistribution",
                        "cloudfront:GetDistributionConfig",
                        "cloudfront:ListDistributions",
                        "cloudfront:ListDistributionsByWebACLId",
                        "cloudfront:UpdateDistribution",
                    ],
                    resources=[
                        f"arn:aws:cloudfront::{Aws.ACCOUNT_ID}:distribution/{self.prebid_cloudfront_distribution.distribution_id}"
                    ],
                ),
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "cloudwatch:ListMetrics",
                        "cloudwatch:GetMetricStatistics",
                        "ec2:DescribeRegions",
                    ],
                    resources=["*"],
                ),
            ],
        )
        create_waf_web_acl_function.role.attach_inline_policy(
            waf_web_acl_function_cloudfront_policy
        )

        del_waf_web_acl_function = SolutionsPythonFunction(
            self,
            "DelWafWebAclFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "waf_webacl_lambda"
            / "delete_waf_webacl.py",
            "event_handler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            description="Lambda function for deleting Waf Web Acl",
            timeout=Duration.minutes(1),
            memory_size=256,
            architecture=aws_lambda.Architecture.ARM_64,
            layers=[
                PowertoolsLayer.get_or_create(self),
                SolutionsLayer.get_or_create(self),
            ],
            environment={"SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                         "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION"),
                         }
        )

        del_waf_web_acl_function.node.add_dependency(waf_web_acl_function_waf_policy)
        del_waf_web_acl_function.node.add_dependency(
            waf_web_acl_function_cloudfront_policy
        )
        del_waf_web_acl_function.role.attach_inline_policy(
            waf_web_acl_function_waf_policy
        )
        del_waf_web_acl_function.role.attach_inline_policy(
            waf_web_acl_function_cloudfront_policy
        )

        # Suppress the cfn_guard rules indicating that this function should operate within a VPC and have reserved concurrency.
        # A VPC is not necessary for this function because it does not need to access any resources within a VPC.
        # Reserved concurrency is not necessary because this function is invoked infrequently.
        del_waf_web_acl_function.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']})

        CustomResource(
            self,
            "DeleteWafWebAclCr",
            service_token=del_waf_web_acl_function.function_arn,
            properties={
                "CF_DISTRIBUTION_ID": self.prebid_cloudfront_distribution.distribution_id,
                "WAF_WEBACL_NAME": self.waf_webacl_name,
                "WAF_WEBACL_ID": waf_webacl_id,
                "WAF_WEBACL_LOCKTOKEN": waf_webacl_locktoken,
            },
        )
