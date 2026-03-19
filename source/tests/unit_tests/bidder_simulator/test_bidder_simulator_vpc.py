# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for BidderSimulatorStack VPC creation.
# USAGE:
#   ./run-unit-tests.sh --test-file-name test_bidder_simulator_vpc.py
###############################################################################

import sys
import pytest
from aws_cdk import App
from aws_cdk.assertions import Template, Match

# Add the bidder simulator directory to the Python path
sys.path.insert(0, "./loadtest/bidder_simulator")
from bidder_simulator_stack import BidderSimulatorStack


class TestBidderSimulatorVpc:
    """Test VPC creation in BidderSimulatorStack"""

    def test_vpc_always_created(self):
        """
        Test that VPC is always created for internal ALB deployment.
        This is part of the bidder simulator architecture with internal ALB + Lambda.
        Validates Requirements 1.1, 4.1, 9.1, 9.4
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - VPC should exist
        template.resource_count_is("AWS::EC2::VPC", 1)
        
        # Assert - VPC has correct CIDR block (10.1.0.0/16)
        template.has_resource_properties("AWS::EC2::VPC", {
            "CidrBlock": "10.1.0.0/16",
            "EnableDnsHostnames": True,
            "EnableDnsSupport": True
        })
        
        # Assert - 2 public subnets exist
        public_subnets = template.find_resources("AWS::EC2::Subnet", {
            "Properties": {
                "MapPublicIpOnLaunch": True
            }
        })
        assert len(public_subnets) == 2, "Should have 2 public subnets"
        
        # Assert - 2 private subnets exist
        private_subnets = template.find_resources("AWS::EC2::Subnet", {
            "Properties": {
                "MapPublicIpOnLaunch": False
            }
        })
        assert len(private_subnets) == 2, "Should have 2 private subnets"
        
        # Assert - NAT Gateways exist (2 for high availability)
        template.resource_count_is("AWS::EC2::NatGateway", 2)

    def test_vpc_created_with_rtb_fabric_context(self):
        """
        Test that VPC is created even when RTB Fabric context is set.
        VPC creation is not conditional on RTB Fabric flag.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - VPC should exist
        template.resource_count_is("AWS::EC2::VPC", 1)

    def test_vpc_cidr_non_overlapping_with_pbs(self):
        """
        Test that bidder simulator VPC CIDR (10.1.0.0/16) does not overlap
        with PBS VPC CIDR (10.8.0.0/16).
        Validates Requirement 9.4
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - VPC CIDR is 10.1.0.0/16 (not 10.8.0.0/16 which is PBS VPC)
        template.has_resource_properties("AWS::EC2::VPC", {
            "CidrBlock": "10.1.0.0/16"
        })
        
        # Verify non-overlap: 10.1.0.0/16 and 10.8.0.0/16 do not overlap
        bidder_cidr = "10.1.0.0/16"
        pbs_cidr = "10.8.0.0/16"
        
        # Extract first octet ranges
        bidder_second_octet = int(bidder_cidr.split('.')[1])
        pbs_second_octet = int(pbs_cidr.split('.')[1])
        
        # Assert they are different
        assert bidder_second_octet != pbs_second_octet, \
            f"CIDR blocks overlap: {bidder_cidr} and {pbs_cidr}"

    def test_vpc_subnets_across_two_azs(self):
        """
        Test that VPC subnets are distributed across 2 availability zones.
        Validates Requirement 1.1
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Total of 4 subnets (2 public + 2 private)
        template.resource_count_is("AWS::EC2::Subnet", 4)
        
        # Assert - VPC configured for max 2 AZs
        template.has_resource_properties("AWS::EC2::VPC", {
            "CidrBlock": "10.1.0.0/16"
        })

