# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import (
    Aws,
    CfnOutput,
    Tags,
    aws_ec2 as ec2,
)
from constructs import Construct

from .vpc_construct import VpcConstruct


class VpcPeeringConstruct(Construct):
    """
    Creates a VPC peering connection between Prebid Server and Bidder Simulator VPCs.

    VPC Peering Configuration:
    - Automatically accepted (both VPCs in same account)
    - Routes added in BOTH VPCs:
      - Prebid Server VPC private subnets: route 10.1.0.0/16 → peering connection
      - Bidder Simulator VPC private subnets: route 10.8.0.0/16 → peering connection
    - Bidder Simulator ALB security group updated to allow HTTP from Prebid Server VPC CIDR

    Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        vpc_construct: VpcConstruct,
        bidder_simulator_vpc_id: str,
        bidder_simulator_alb_sg_id: str = None,
        bidder_simulator_route_table_ids: list = None,
    ) -> None:
        super().__init__(scope, id)

        # Create VPC peering connection
        # The connection is automatically accepted since both VPCs are in the same account
        self.vpc_peering_connection = ec2.CfnVPCPeeringConnection(
            self,
            "PrebidServerVpcPeering",
            peer_vpc_id=bidder_simulator_vpc_id,
            vpc_id=vpc_construct.prebid_vpc.vpc_id,
        )

        # Add tags using the Tags API
        Tags.of(self.vpc_peering_connection).add("Name", f"{Aws.STACK_NAME}-PrebidServer-VpcPeering")

        # Add routes in Prebid Server VPC private subnets
        # Route Bidder Simulator VPC CIDR (10.1.0.0/16) to the peering connection
        private_subnets = vpc_construct.prebid_vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )

        for i, subnet in enumerate(private_subnets.subnets):
            ec2.CfnRoute(
                self,
                f"PrebidToBidderRoute{i}",
                route_table_id=subnet.route_table.route_table_id,
                destination_cidr_block="10.1.0.0/16",  # Bidder Simulator VPC CIDR
                vpc_peering_connection_id=self.vpc_peering_connection.ref,
            )

        # Add routes in Bidder Simulator VPC private subnets
        # Use the route table IDs passed from the Bidder Simulator stack
        # Route Prebid Server VPC CIDR (10.8.0.0/16) to the peering connection
        if bidder_simulator_route_table_ids:
            for i, route_table_id in enumerate(bidder_simulator_route_table_ids):
                ec2.CfnRoute(
                    self,
                    f"BidderToPrebidRoute{i}",
                    route_table_id=route_table_id,
                    destination_cidr_block="10.8.0.0/16",  # Prebid Server VPC CIDR
                    vpc_peering_connection_id=self.vpc_peering_connection.ref,
                )

        # Update Bidder Simulator ALB security group to allow HTTP from Prebid Server VPC CIDR
        if bidder_simulator_alb_sg_id:
            bidder_alb_sg = ec2.SecurityGroup.from_security_group_id(
                self,
                "ImportedBidderAlbSecurityGroup",
                security_group_id=bidder_simulator_alb_sg_id,
                mutable=True,
            )

            bidder_alb_sg.add_ingress_rule(
                peer=ec2.Peer.ipv4("10.8.0.0/16"),  # Prebid Server VPC CIDR
                connection=ec2.Port.tcp(80),
                description="Allow HTTP from Prebid Server VPC via peering",
            )

        # Output VPC peering connection ID for reference
        CfnOutput(
            self,
            "VpcPeeringConnectionId",
            key="VpcPeeringConnectionId",
            value=self.vpc_peering_connection.ref,
            description="VPC Peering Connection ID between Prebid Server and Bidder Simulator VPCs",
        )
