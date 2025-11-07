# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
from constructs import Construct
from aws_cdk import (
    aws_ec2 as ec2,
    aws_elasticache as elasticache,
    aws_lambda as awslambda,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as targets,
    aws_iam as iam,
    Duration,
    CfnOutput,
    Aws,
    Fn
)

from aws_lambda_layers.aws_solutions.layer import SolutionsLayer


class CacheConstruct(Construct):
    def __init__(
        self, 
        scope: Construct, 
        id: str, 
        vpc_construct,
        op_metrics_layer,
        **kwargs
    ):
        super().__init__(scope, id, **kwargs)

        # Create ElasticCache Security Group
        self.cache_security_group = ec2.SecurityGroup(
            self, "CacheSecurityGroup",
            vpc=vpc_construct.prebid_vpc,
            description="Security group for ElasticCache",
            allow_all_outbound=True
        )
        self.cache_security_group.node.find_child(id="Resource").add_metadata(
            "guard", {
                'SuppressedRules': ['EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE',
                                    'SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE']
            }
        )

        # Create ElasticCache Serverless Cache
        cache_name = Fn.join(
            '-',
            [
                "cache",
                Fn.select(0, Fn.split('-', Fn.select(2, Fn.split('/', Aws.STACK_ID))))
            ]
        )

        cache_iam_user_name = cache_name + "user-01"

        self.serverless_cache = elasticache.CfnServerlessCache(
            self, "ServerlessCache",
            engine="valkey",
            major_engine_version="8",
            serverless_cache_name=cache_name,
            description=f"Serverless Cache for {Aws.STACK_NAME}",
            security_group_ids=[self.cache_security_group.security_group_id],
            subnet_ids=[
                subnet.subnet_id for subnet in vpc_construct.prebid_vpc.private_subnets
            ],
        )

        # Create default user
        self.default_user = elasticache.CfnUser(
            self, "DefaultUser",
            user_id=f"{cache_name}-defaultuser-disabled",
            user_name="default",
            engine="valkey",
            authentication_mode={
                "Type": "password",
                "Passwords": ["disabled-password-123"]
            },
            access_string="off +get ~keys*"
        )

        # Create IAM-enabled user for the cache
        self.cache_user = elasticache.CfnUser(
            self, "CacheIAMUser",
            user_id=cache_iam_user_name,
            user_name=cache_iam_user_name,
            engine="valkey",
            authentication_mode={
                "Type": "iam"
            },
            access_string="on ~* +@all"
        )

        # Create user group and add users
        self.cache_user_group = elasticache.CfnUserGroup(
            self, "CacheUserGroup",
            user_group_id=f"{cache_name}-group-01",
            engine="valkey",
            user_ids=[self.default_user.user_id, self.cache_user.user_id]
        )

        # Associate user group with the serverless cache
        self.serverless_cache.user_group_id = self.cache_user_group.user_group_id

        # Add dependency to ensure proper creation order
        self.serverless_cache.add_dependency(self.cache_user_group)
        self.cache_user_group.add_dependency(self.cache_user)
        self.cache_user_group.add_dependency(self.default_user)

        # Create a Lambda layer with redis package
        self.redis_layer = awslambda.LayerVersion(
            self, "RedisLayer",
            code=awslambda.Code.from_asset(
                os.path.join(f"{Path(__file__).parent}", "cache_lambda"),
                bundling={
                    "image": awslambda.Runtime.PYTHON_3_11.bundling_image,
                    "command": [
                        "bash", "-c",
                        "pip install redis cachetools --no-deps -t /asset-output/python && cp -au . /asset-output/python/"
                    ],
                }
            ),
            compatible_runtimes=[awslambda.Runtime.PYTHON_3_11],
            description="Redis package layer"
        )

        # Create Lambda function
        self.cache_lambda_function = awslambda.Function(
            self, "CacheHandler",
            runtime=awslambda.Runtime.PYTHON_3_11,
            handler="cache_access.handler",
            code=awslambda.Code.from_asset(os.path.join(
                f"{Path(__file__).parent}", "cache_lambda")),
            layers=[
                self.redis_layer,
                op_metrics_layer,
                SolutionsLayer.get_or_create(self),
            ],
            environment={
                "REDIS_ENDPOINT": self.serverless_cache.attr_endpoint_address,
                "REDIS_PORT": self.serverless_cache.attr_endpoint_port, 
                "CACHE_NAME": self.serverless_cache.serverless_cache_name,
                "CACHE_USER": cache_iam_user_name,
                "RESOURCE_PREFIX": Aws.STACK_NAME,
                "METRICS_NAMESPACE": self.node.try_get_context("METRICS_NAMESPACE"),
                "SOLUTION_ID": self.node.try_get_context("SOLUTION_ID"),
                "SOLUTION_VERSION": self.node.try_get_context("SOLUTION_VERSION")
            },
            architecture=awslambda.Architecture.ARM_64,
            memory_size=256,
            timeout=Duration.seconds(30),
            vpc=vpc_construct.prebid_vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            description="Lambda function to handle cache operations for Prebid Server"
        )

        self.cache_lambda_function.node.find_child(id="Resource").add_metadata("guard", {
            "SuppressedRules": ["LAMBDA_CONCURRENCY_CHECK"]})
        self.cache_lambda_function.connections.security_groups[0].node.find_child(id="Resource").add_metadata("guard", {
            "SuppressedRules": ["EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE",
                                "SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE"]})

        # Add IAM policy to Lambda to connect to ElastiCache
        self.cache_lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["elasticache:Connect"],
                resources=[
                    f"arn:aws:elasticache:{Aws.REGION}:{Aws.ACCOUNT_ID}:serverlesscache:{self.serverless_cache.serverless_cache_name}",
                    f"arn:aws:elasticache:{Aws.REGION}:{Aws.ACCOUNT_ID}:user:{self.cache_user.user_id}"
                ]
            )
        )
        
        # Add cloudwatch operational metrics permission
        self.cache_lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
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
            )
        )

        self.cache_security_group.add_ingress_rule(
            ec2.Peer.security_group_id(
                self.cache_lambda_function.connections.security_groups[0].security_group_id),
            ec2.Port.tcp(6379),
            "Allow Lambda to access Redis Serverless cache"
        )

        self.create_target_groups()

    def create_target_groups(self):
        # Common health check configuration
        health_check = elbv2.HealthCheck(
            enabled=True,
            path="/cache/health",
            healthy_http_codes="200",
            interval=Duration.seconds(60),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3
        )

        # Create target groups with different configurations
        self.lambda_target_external_cf = elbv2.ApplicationTargetGroup(
            self,
            "CacheLambdaTargetExternalCf",
            target_type=elbv2.TargetType.LAMBDA,
            targets=[targets.LambdaTarget(self.cache_lambda_function)],
            health_check=health_check
        )

        self.lambda_target_external_alb = elbv2.ApplicationTargetGroup(
            self,
            "CacheLambdaTargetExternalAlb",
            target_type=elbv2.TargetType.LAMBDA,
            targets=[targets.LambdaTarget(self.cache_lambda_function)],
            health_check=health_check
        )

        self.lambda_target_internal_cf = elbv2.ApplicationTargetGroup(
            self,
            "CacheLambdaTargetInternalCf",
            target_type=elbv2.TargetType.LAMBDA,
            targets=[targets.LambdaTarget(self.cache_lambda_function)],
            health_check=health_check
        )

        self.lambda_target_internal_alb = elbv2.ApplicationTargetGroup(
            self,
            "CacheLambdaTargetInternalAlb",
            target_type=elbv2.TargetType.LAMBDA,
            targets=[targets.LambdaTarget(self.cache_lambda_function)],
            health_check=health_check
        )

        CfnOutput(
            self,
            "PrebidCache",
            value=self.serverless_cache.serverless_cache_name,
            description="Cache Name",
        )
