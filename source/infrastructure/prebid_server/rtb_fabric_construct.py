# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import (
    Aws,
    CfnOutput,
    CfnTag,
    CustomResource,
    Duration,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_lambda as awslambda,
    aws_rtbfabric as rtbfabric,
)
from constructs import Construct
from aws_lambda_layers.aws_solutions.layer import SolutionsLayer
from aws_solutions.cdk.aws_lambda.layers.aws_lambda_powertools import PowertoolsLayer
from aws_solutions.cdk.aws_lambda.python.function import SolutionsPythonFunction
import prebid_server.stack_constants as stack_constants

from .vpc_construct import VpcConstruct


class RtbFabricConstruct(Construct):
    """
    Creates RTB Fabric Requester Gateway and optionally a Fabric Link.

    The gateway enables PBS to send bid requests through AWS RTB Fabric's
    private network to bidder simulators.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc_construct: VpcConstruct,
        responder_gateway_id: str = None,
    ) -> None:
        super().__init__(scope, id)

        self._create_requester_gateway(vpc_construct)

        if responder_gateway_id:
            self._create_fabric_link(responder_gateway_id)

    def _create_requester_gateway(self, vpc_construct: VpcConstruct) -> None:
        """
        Create RTB Fabric Requester Gateway.

        Gateway Configuration:
        - Attached to PBS VPC
        - Configured for IPv4 traffic only (HTTPS on port 443)
        - Security group allows HTTPS (443) from PBS application
        - Security group allows HTTPS (443) to RTB Fabric network

        Requirements: 3.1, 3.2, 3.3, 3.4
        """
        # Create security group for Requester Gateway
        self.requester_gateway_security_group = ec2.SecurityGroup(
            self,
            "RequesterGatewaySecurityGroup",
            vpc=vpc_construct.prebid_vpc,
            description="Security group for RTB Fabric Requester Gateway",
            allow_all_outbound=True,
        )

        # Allow HTTPS (443) from PBS application
        self.requester_gateway_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc_construct.prebid_vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS from PBS application",
        )

        # Get private subnets for gateway attachment
        private_subnets = vpc_construct.prebid_vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        # Create RTB Fabric Requester Gateway using the typed L1 construct
        self.requester_gateway = rtbfabric.CfnRequesterGateway(
            self,
            "RequesterGateway",
            vpc_id=vpc_construct.prebid_vpc.vpc_id,
            subnet_ids=[private_subnets.subnets[0].subnet_id],
            security_group_ids=[self.requester_gateway_security_group.security_group_id],
            description="RTB Fabric Requester Gateway for PBS",
            tags=[CfnTag(key="Name", value=f"{Aws.STACK_NAME}-PBS-RequesterGateway")],
        )

        CfnOutput(
            self,
            "RequesterGatewayId",
            key="RequesterGatewayId",
            value=self.requester_gateway.attr_gateway_id,
            description="RTB Fabric Requester Gateway ID",
        )

        CfnOutput(
            self,
            "RequesterGatewayArn",
            key="RequesterGatewayArn",
            value=self.requester_gateway.attr_arn,
            description="RTB Fabric Requester Gateway ARN",
        )

    def _create_fabric_link(self, responder_gateway_id: str) -> None:
        """
        Create RTB Fabric Link connecting Requester Gateway to Responder Gateway.

        Link Configuration:
        - Connects Requester Gateway (PBS) to Responder Gateway (bidder simulator)
        - Link acceptance via custom resource Lambda (required for same-account links)
        - HttpResponderAllowed enables asymmetric security (HTTPS out, HTTP in)

        Requirements: 5.1, 5.2

        Args:
            responder_gateway_id: The Gateway ID of the Responder Gateway from
                                 the bidder simulator stack
        """
        # Wait for the Requester Gateway to be fully ready before creating the Link.
        # CloudFormation reports CREATE_COMPLETE before RTB Fabric finishes internal
        # provisioning, which causes a 409 "not ready" error on Link creation.
        wait_for_gw_function = SolutionsPythonFunction(
            self,
            "WaitForGatewayFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "wait_for_gateway_lambda"
            / "wait_for_gateway.py",
            "event_handler",
            runtime=awslambda.Runtime.PYTHON_3_11,
            description="Wait for RTB Fabric Gateway to be fully provisioned",
            timeout=Duration.seconds(60),
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

        wait_for_gw_function.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']
        })

        wait_for_gw_cr = CustomResource(
            self,
            "WaitForRequesterGatewayCr",
            service_token=wait_for_gw_function.function_arn,
            properties={
                "GatewayId": self.requester_gateway.attr_gateway_id,
            }
        )
        wait_for_gw_cr.node.add_dependency(self.requester_gateway)

        # Create RTB Fabric Link using the typed L1 construct
        self.fabric_link = rtbfabric.CfnLink(
            self,
            "FabricLink",
            gateway_id=self.requester_gateway.attr_gateway_id,
            peer_gateway_id=responder_gateway_id,
            http_responder_allowed=True,
            link_log_settings=rtbfabric.CfnLink.LinkLogSettingsProperty(
                application_logs=rtbfabric.CfnLink.ApplicationLogsProperty(
                    link_application_log_sampling=rtbfabric.CfnLink.LinkApplicationLogSamplingProperty(
                        error_log=100,
                        filter_log=100,
                    )
                )
            ),
            tags=[CfnTag(key="Name", value=f"{Aws.STACK_NAME}-PBS-BidderSimulator-Link")],
        )

        # Add explicit dependency on the wait-for-gateway custom resource
        self.fabric_link.add_dependency(wait_for_gw_cr.node.default_child)

        # Create Lambda function to accept the link
        accept_link_function = SolutionsPythonFunction(
            self,
            "AcceptFabricLinkFunction",
            stack_constants.CUSTOM_RESOURCES_PATH
            / "accept_fabric_link_lambda"
            / "accept_fabric_link.py",
            "event_handler",
            runtime=awslambda.Runtime.PYTHON_3_11,
            description="Lambda function to accept RTB Fabric Link",
            timeout=Duration.seconds(60),
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

        accept_link_function.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["rtbfabric:AcceptLink"],
                resources=[
                    f"arn:aws:rtbfabric:{Aws.REGION}:{Aws.ACCOUNT_ID}:gateway/{responder_gateway_id}/link/*"
                ]
            )
        )

        accept_link_function.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['LAMBDA_INSIDE_VPC', 'LAMBDA_CONCURRENCY_CHECK']
        })

        accept_link_custom_resource = CustomResource(
            self,
            "AcceptFabricLinkCr",
            service_token=accept_link_function.function_arn,
            properties={
                "GatewayId": responder_gateway_id,
                "LinkId": self.fabric_link.attr_link_id,
                "ErrorLogSampling": 100,
                "FilterLogSampling": 100
            }
        )

        accept_link_custom_resource.node.add_dependency(self.fabric_link)

        CfnOutput(
            self,
            "FabricLinkId",
            key="FabricLinkId",
            value=self.fabric_link.attr_link_id,
            description="RTB Fabric Link ID for PBS traffic routing",
        )

        CfnOutput(
            self,
            "FabricLinkArn",
            key="FabricLinkArn",
            value=self.fabric_link.attr_arn,
            description="RTB Fabric Link ARN",
        )
