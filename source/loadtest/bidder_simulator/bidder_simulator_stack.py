# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

from constructs import Construct
from aws_cdk import (
    Duration,
    Aws,
    CfnTag,
    Fn,
    Stack,
    CfnOutput,
    CfnResource,
    CfnParameter,
    RemovalPolicy,
    aws_lambda as awslambda,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as targets,
    aws_rtbfabric as rtbfabric,
    aws_s3 as s3,
    aws_s3_deployment as s3_deployment,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as cloudfront_origins,
)


class BidderSimulatorStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, include_rtb_fabric: bool = False, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._resource_prefix = Aws.STACK_NAME

        # Create VPC for bidder simulator (required for ALB deployment)
        self._create_vpc()

        self.response_delay_percentage = CfnParameter(
            self,
            "bidResponseDelayPercentage",
            description="Percentage of bid requests to get delayed response",
            type="Number",
            min_value=0,
            max_value=1,
            default=0
        )

        self.response_timeout_percentage = CfnParameter(
            self,
            "bidResponseTimeoutPercentage",
            description="Percentage of bid requests to get timeout response",
            type="Number",
            min_value=0,
            max_value=1,
            default=0
        )

        self.response_delay_probability = CfnParameter(
            self,
            "bidResponseDelayProbability",
            description="Probability for a Bid Response to be delay",
            type="Number",
            min_value=0,
            max_value=1,
            default=0
        )

        self.response_timeout_probability = CfnParameter(
            self,
            "bidResponseTimeoutProbability",
            description="Probability for a Bid Response to be timeout",
            type="Number",
            min_value=0,
            max_value=1,
            default=0
        )

        # Use Lambda to simulate a bidding server
        self._bidder_simulator = awslambda.Function(
                self,
                "bidderSimulator",
                function_name=f"{self._resource_prefix}-bidding-server-simulator",
                code=awslambda.Code.from_asset(os.path.join(f"{Path(__file__).parent}", "lambdas/loadtest_bidder")),
                handler="handler.lambda_handler",
                environment={
                    "BID_RESPONSES_DELAY_PERCENTAGE": self.response_delay_percentage.value_as_string,
                    "BID_RESPONSES_TIMEOUT_PERCENTAGE": self.response_timeout_percentage.value_as_string,
                    "A_BID_RESPONSE_DELAY_PROBABILITY": self.response_delay_probability.value_as_string,
                    "A_BID_RESPONSE_TIMEOUT_PROBABILITY": self.response_timeout_probability.value_as_string,
                },
                description="Simulate a bidding server to send a Bid Response",
                timeout=Duration.minutes(1),
                memory_size=256,
                architecture=awslambda.Architecture.ARM_64,
                runtime=awslambda.Runtime.PYTHON_3_11,
            )

        # Create Application Load Balancer for internal ALB + Lambda architecture
        self._create_alb()
        
        # Conditionally create RTB Fabric Responder Gateway
        if include_rtb_fabric:
            self._create_responder_gateway()

        # Create demo website (CloudFront + S3)
        self._create_demo_website()

        # Export VPC ID and ALB security group for cross-stack references
        # These are needed by Prebid Server stack for VPC peering (when RTB Fabric is disabled)
        CfnOutput(
            self,
            "BidderSimulatorVpcId",
            key="BidderSimulatorVpcId",
            value=self.bidder_vpc.vpc_id,
            description="Bidder Simulator VPC ID for VPC peering",
            export_name=f"{Aws.STACK_NAME}-BidderSimulatorVpcId",
        )
        
        CfnOutput(
            self,
            "BidderSimulatorAlbSecurityGroupId",
            key="BidderSimulatorAlbSecurityGroupId",
            value=self.alb_security_group.security_group_id,
            description="Bidder Simulator ALB Security Group ID for VPC peering",
            export_name=f"{Aws.STACK_NAME}-BidderSimulatorAlbSecurityGroupId",
        )
        
        # Store private subnet route table IDs for VPC peering route creation
        # The Prebid Server stack needs these to add routes in the Bidder Simulator VPC
        private_subnets = self.bidder_vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )
        self.private_route_table_ids = [subnet.route_table.route_table_id for subnet in private_subnets.subnets]

    def _create_vpc(self) -> None:
        """
        Create VPC for bidder simulator to support ALB deployment.
        
        This VPC is required for the internal ALB + Lambda architecture.
        It is separate from the PBS VPC to maintain network isolation.
        
        VPC Configuration:
        - CIDR: 10.1.0.0/16 (non-overlapping with PBS VPC 10.8.0.0/16)
        - 2 public subnets across 2 availability zones (for NAT gateways)
        - 2 private subnets across 2 availability zones (for internal ALB and Lambda)
        - DNS hostnames and DNS support enabled
        - 2 NAT gateways for high availability
        """
        self.bidder_vpc = ec2.Vpc(
            self,
            "BidderSimulatorVpc",
            ip_addresses=ec2.IpAddresses.cidr("10.1.0.0/16"),
            max_azs=2,
            nat_gateways=2,
            enable_dns_hostnames=True,
            enable_dns_support=True,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PUBLIC,
                    name="BidderSimulator-Public",
                    cidr_mask=20,
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name="BidderSimulator-Private",
                    cidr_mask=20,
                ),
            ],
        )

    def _create_alb(self) -> None:
        """
        Create Application Load Balancer for bidder simulator.
        
        The ALB is deployed in the VPC's private subnets and configured to:
        - Internal-only access (not accessible from public internet)
        - Accept HTTP traffic (port 80) from internal sources
        - Route traffic to Lambda functions via target groups
        - Perform health checks on Lambda targets
        
        This replaces the API Gateway architecture to enable VPC-based
        RTB Fabric integration and VPC peering connectivity.
        """
        # Create security group for ALB
        self.alb_security_group = ec2.SecurityGroup(
            self,
            "AlbSecurityGroup",
            vpc=self.bidder_vpc,
            description="Security group for internal bidder simulator ALB",
            allow_all_outbound=True,
        )
        
        # Security group rules for RTB Fabric and VPC peering will be added in later tasks
        # Task 3.2: Add HTTP ingress from Responder Gateway (RTB Fabric mode)
        # Task 4.3: Add HTTP ingress from Prebid Server VPC CIDR (VPC peering mode)
        
        # Create internal Application Load Balancer
        # Explicit lowercase name ensures the DNS name passes RTB Fabric's
        # domain name regex validation (lowercase-only pattern).
        # Suffix with first 8 chars of Stack ID UUID for uniqueness (ALB name max 32 chars).
        stack_uuid = Fn.select(2, Fn.split("/", Aws.STACK_ID))
        alb_unique_suffix = Fn.select(0, Fn.split("-", stack_uuid))
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "BidderSimulatorAlb",
            load_balancer_name=f"bidder-sim-{alb_unique_suffix}",
            vpc=self.bidder_vpc,
            internet_facing=False,
            security_group=self.alb_security_group,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
        )
        
        # Create target group for Lambda function
        # Target type is LAMBDA to register Lambda functions as targets
        self.lambda_target_group = elbv2.ApplicationTargetGroup(
            self,
            "LambdaTargetGroup",
            target_type=elbv2.TargetType.LAMBDA,
            targets=[targets.LambdaTarget(self._bidder_simulator)],
            health_check=elbv2.HealthCheck(
                enabled=True,
                path="/",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=2,
            ),
        )
        
        # Note: LambdaTarget automatically adds the necessary Lambda permissions
        # for ALB invocation via add_permission with elasticloadbalancing.amazonaws.com
        # principal. This is handled by CDK internally when using LambdaTarget.
        
        # Create HTTP listener (port 80)
        # Internal ALB will use HTTP for communication
        self.alb_listener = self.alb.add_listener(
            "HttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_target_groups=[self.lambda_target_group],
        )
        
        # Output ALB DNS name for internal access
        CfnOutput(
            self,
            "BidderSimulatorAlbEndpoint",
            key="BidderSimulatorAlbEndpoint",
            value=f"http://{self.alb.load_balancer_dns_name}",
            description="Internal ALB endpoint URL for bidder simulator (accessible only within VPC or via VPC peering)",
        )

    def _create_responder_gateway(self) -> None:
        """
        Create RTB Fabric Responder Gateway.

        The gateway enables the bidder simulator to receive bid requests 
        through AWS RTB Fabric's private network.

        Gateway Configuration:
        - Attached to bidder simulator VPC
        - Configured for IPv4 traffic only (HTTP on port 80)
        - Security group allows HTTP (80) from RTB Fabric network
        - Security group allows HTTP (80) to ALB

        Requirements: 4.2, 4.3, 4.4, 4.5
        """
        # Create security group for Responder Gateway
        self.responder_gateway_security_group = ec2.SecurityGroup(
            self,
            "ResponderGatewaySecurityGroup",
            vpc=self.bidder_vpc,
            description="Security group for RTB Fabric Responder Gateway",
            allow_all_outbound=True,
        )

        # Allow HTTP (80) from RTB Fabric network
        self.responder_gateway_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.bidder_vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(80),
            description="Allow HTTP from RTB Fabric network",
        )

        # Allow HTTP (80) from Responder Gateway to ALB
        self.alb_security_group.add_ingress_rule(
            peer=self.responder_gateway_security_group,
            connection=ec2.Port.tcp(80),
            description="Allow HTTP from RTB Fabric Responder Gateway",
        )

        # Get private subnets for gateway attachment
        private_subnets = self.bidder_vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        # Create RTB Fabric Responder Gateway using the typed L1 construct
        self.responder_gateway = rtbfabric.CfnResponderGateway(
            self,
            "ResponderGateway",
            port=80,
            protocol="HTTP",
            vpc_id=self.bidder_vpc.vpc_id,
            subnet_ids=[private_subnets.subnets[0].subnet_id],
            security_group_ids=[self.responder_gateway_security_group.security_group_id],
            description="RTB Fabric Responder Gateway for bidder simulator",
            domain_name=self.alb.load_balancer_dns_name,
            tags=[CfnTag(key="Name", value=f"{Aws.STACK_NAME}-BidderSimulator-ResponderGateway")],
        )

        CfnOutput(
            self,
            "ResponderGatewayId",
            key="ResponderGatewayId",
            value=self.responder_gateway.attr_gateway_id,
            description="RTB Fabric Responder Gateway ID",
        )

        CfnOutput(
            self,
            "ResponderGatewayArn",
            key="ResponderGatewayArn",
            value=self.responder_gateway.attr_arn,
            description="RTB Fabric Responder Gateway ARN",
        )


    def _create_demo_website(self) -> None:
        """
        Create demo website infrastructure: S3 bucket, CloudFront distribution,
        and deploy static demo files.

        """
        # S3 bucket for hosting the demo app
        self.demo_bucket = s3.Bucket(
            self,
            "DemoWebsiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            enforce_ssl=True,
        )
        self.demo_bucket.node.default_child.add_metadata("guard", {
            'SuppressedRules': ['S3_BUCKET_LOGGING_ENABLED']})

        # S3 origin with OAC for the demo bucket
        demo_oac = cloudfront.S3OriginAccessControl(
            self,
            "DemoOac",
            signing=cloudfront.Signing.SIGV4_NO_OVERRIDE,
            origin_access_control_name=f"DemoOac-{Aws.STACK_NAME}-{Aws.REGION}",
            description="OAC for demo bucket",
        )
        demo_origin = cloudfront_origins.S3BucketOrigin.with_origin_access_control(
            self.demo_bucket,
            origin_access_control=demo_oac,
        )

        # Create a dedicated CloudFront distribution for the demo website
        self.demo_cloudfront_distribution = cloudfront.Distribution(
            self,
            "DemoCloudFrontDist",
            comment="Demo website for Prebid Server on AWS",
            default_behavior=cloudfront.BehaviorOptions(
                origin=demo_origin,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
        )

        # Deploy demo static files to S3
        demo_path = Path(__file__).absolute().parents[1] / "demo"
        s3_deployment.BucketDeployment(
            self,
            "DemoWebsiteDeployment",
            sources=[s3_deployment.Source.asset(str(demo_path))],
            destination_bucket=self.demo_bucket,
        )

        CfnOutput(
            self,
            "DemoWebsiteUrl",
            key="DemoWebsiteUrl",
            value=f"https://{self.demo_cloudfront_distribution.domain_name}/index.html",
            description="Demo website URL served via CloudFront",
        )

