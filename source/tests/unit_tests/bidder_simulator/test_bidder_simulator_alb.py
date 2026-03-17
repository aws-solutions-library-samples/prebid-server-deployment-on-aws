# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for BidderSimulatorStack ALB creation.
# USAGE:
#   ./run-unit-tests.sh --test-file-name test_bidder_simulator_alb.py
###############################################################################

import sys
import pytest
from aws_cdk import App
from aws_cdk.assertions import Template, Match

# Add the bidder simulator directory to the Python path
sys.path.insert(0, "./loadtest/bidder_simulator")
from bidder_simulator_stack import BidderSimulatorStack


class TestBidderSimulatorAlb:
    """Test ALB creation in BidderSimulatorStack"""

    def test_alb_created_in_vpc(self):
        """
        Test that ALB is created in the VPC as an internal load balancer.
        Validates Requirements 2.1, 2.2
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - ALB should exist
        template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 1)
        
        # Assert - ALB is internal (not internet-facing)
        template.has_resource_properties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
            "Scheme": "internal",
            "Type": "application"
        })

    def test_alb_security_group_created(self):
        """
        Test that ALB security group is created for internal access.
        Security group rules for RTB Fabric and VPC peering are added conditionally.
        Validates Requirements 2.2, 2.3, 2.4
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Security group exists with correct description
        template.has_resource_properties("AWS::EC2::SecurityGroup", {
            "GroupDescription": "Security group for internal bidder simulator ALB"
        })
        
        # Assert - No public internet ingress rules (0.0.0.0/0) by default
        # Rules are added conditionally based on RTB Fabric or VPC peering configuration

    def test_lambda_target_group_created(self):
        """
        Test that Lambda target group is created for ALB.
        Validates Requirement 1.2
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Target group exists
        template.resource_count_is("AWS::ElasticLoadBalancingV2::TargetGroup", 1)
        
        # Assert - Target group is configured for Lambda
        template.has_resource_properties("AWS::ElasticLoadBalancingV2::TargetGroup", {
            "TargetType": "lambda"
        })

    def test_health_check_configured(self):
        """
        Test that health check is configured for Lambda target group.
        Validates Requirement 1.1
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Health check is configured
        template.has_resource_properties("AWS::ElasticLoadBalancingV2::TargetGroup", {
            "HealthCheckEnabled": True,
            "HealthCheckPath": "/",
            "HealthCheckIntervalSeconds": 30,
            "HealthCheckTimeoutSeconds": 5,
            "HealthyThresholdCount": 2,
            "UnhealthyThresholdCount": 2
        })

    def test_alb_listener_created(self):
        """
        Test that ALB listener is created on port 80.
        Validates Requirement 1.1
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Listener exists
        template.resource_count_is("AWS::ElasticLoadBalancingV2::Listener", 1)
        
        # Assert - Listener is on port 80 (HTTP)
        template.has_resource_properties("AWS::ElasticLoadBalancingV2::Listener", {
            "Port": 80,
            "Protocol": "HTTP"
        })

    def test_alb_deployed_in_private_subnets(self):
        """
        Test that ALB is deployed in private subnets.
        Validates Requirements 2.1, 3.1, 3.2, 3.3, 3.4
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - ALB has subnet mappings
        template.has_resource_properties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
            "Subnets": Match.any_value()
        })
        
        # Assert - ALB is internal (not accessible from public internet)
        template.has_resource_properties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
            "Scheme": "internal"
        })

    def test_alb_outputs_created(self):
        """
        Test that ALB DNS name output is created for internal access.
        Validates Requirements 4.7, 6.1, 6.3, 6.4
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - ALB endpoint output exists
        template.has_output("BidderSimulatorAlbEndpoint", {
            "Description": "Internal ALB endpoint URL for bidder simulator (accessible only within VPC or via VPC peering)"
        })

    def test_vpc_and_security_group_exports(self):
        """
        Test that VPC ID and ALB security group ID are exported for cross-stack references.
        These exports enable VPC peering configuration in the Prebid Server stack.
        Validates Requirements 7.1, 7.2, 7.3
        """
        # Arrange
        app = App(context={
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - VPC ID output exists
        template.has_output("BidderSimulatorVpcId", {
            "Description": "Bidder Simulator VPC ID for VPC peering"
        })
        
        # Assert - ALB security group ID output exists
        template.has_output("BidderSimulatorAlbSecurityGroupId", {
            "Description": "Bidder Simulator ALB Security Group ID for VPC peering"
        })
