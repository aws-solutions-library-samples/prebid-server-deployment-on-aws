# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import Aws
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct

import prebid_server.stack_constants as stack_constants

S3_GET_OBJECT = "s3:GetObject"


class VpcConstruct(Construct):
    def __init__(
            self,
            scope,
            id,
            artifacts_bucket,
            docker_configs_manager_bucket,
            stored_requests_bucket
    ) -> None:
        """
        This construct creates VPC resources.
        """
        super().__init__(scope, id)

        # Create VPC for Prebid containers
        self.prebid_vpc = ec2.Vpc(
            self,
            "PrebidVpc",
            ip_addresses=ec2.IpAddresses.cidr(stack_constants.VPC_CIDR),
            max_azs=stack_constants.MAX_AZS,
            nat_gateways=stack_constants.NAT_GATEWAYS,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PUBLIC,
                    name=stack_constants.PUB_SUBNET_NAME,
                    cidr_mask=stack_constants.CIDR_MASK,
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name=stack_constants.PVT_SUBNET_NAME,
                    cidr_mask=stack_constants.CIDR_MASK,
                ),
            ],
        )

        # Get Vpc private subnets
        self.prebid_task_subnets = [
            ec2.Subnet.from_subnet_id(self, f"TaskSubnet{i}", subnet_id)
            for (i, subnet_id) in enumerate(
                self.prebid_vpc.select_subnets(
                    subnet_group_name=stack_constants.PVT_SUBNET_NAME
                ).subnet_ids
            )
        ]

        # Add cfn_guard suppression to allow public IP on public subnets
        subnets = self.prebid_vpc.select_subnets(
            subnet_group_name=stack_constants.PUB_SUBNET_NAME
        ).subnets
        for subnet in subnets:
            subnet.node.default_child.cfn_options.metadata = {
                "guard": {'SuppressedRules': ['SUBNET_AUTO_ASSIGN_PUBLIC_IP_DISABLED']}
            }

        # Create a VPC S3 endpoint to prevent private resources from traversing the public internet when accessing S3
        prebid_s3_endpoint = self.prebid_vpc.add_gateway_endpoint(
            "s3_gateway_endpoint", service=ec2.GatewayVpcEndpointAwsService.S3
        )
        # Allow access to aws-managed public bucket for ECS to pull Docker image assets:
        # https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html#ecr-minimum-s3-perms
        prebid_s3_endpoint.add_to_policy(
            iam.PolicyStatement(
                principals=[iam.AnyPrincipal()],  # NOSONAR - required for operation
                actions=[S3_GET_OBJECT],
                resources=[f"arn:aws:s3:::prod-{Aws.REGION}-starport-layer-bucket/*"],
            )
        )
        # Allow access to artifacts bucket for EFS Cleanup Lambda to read DataSync reports
        prebid_s3_endpoint.add_to_policy(
            iam.PolicyStatement(
                principals=[iam.AnyPrincipal()],  # NOSONAR - required for operation
                actions=[S3_GET_OBJECT, "s3:ListBucket"],
                resources=[
                    artifacts_bucket.bucket_arn,
                    f"{artifacts_bucket.bucket_arn}/*",
                ],
                conditions={
                    "StringEquals": {stack_constants.RESOURCE_NAMESPACE: Aws.ACCOUNT_ID}
                },
            )
        )

        # Allow access to docker configs bucket and application settings bucket
        prebid_s3_endpoint.add_to_policy(
            iam.PolicyStatement(
                principals=[iam.AnyPrincipal()],  # NOSONAR - required for operation
                actions=[S3_GET_OBJECT, "s3:ListBucket"],
                resources=[
                    f"{docker_configs_manager_bucket.bucket_arn}/*",
                    docker_configs_manager_bucket.bucket_arn,
                    f"{stored_requests_bucket.bucket_arn}/*",
                    stored_requests_bucket.bucket_arn
                ],
                conditions={
                    "StringEquals": {stack_constants.RESOURCE_NAMESPACE: Aws.ACCOUNT_ID}
                },
            )
        )
