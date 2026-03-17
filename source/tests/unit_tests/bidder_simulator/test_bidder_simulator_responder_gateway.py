# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# ###############################################################################
# PURPOSE:
#   * Unit test for BidderSimulatorStack Responder Gateway creation.
# USAGE:
#   ./run-unit-tests.sh --test-file-name test_bidder_simulator_responder_gateway.py
###############################################################################

import sys
from aws_cdk import App
from aws_cdk.assertions import Template, Match


# Add the bidder simulator directory to the Python path
sys.path.insert(0, "./loadtest/bidder_simulator")
from bidder_simulator_stack import BidderSimulatorStack


class TestBidderSimulatorResponderGateway:
    """Test Responder Gateway creation in BidderSimulatorStack"""

    def test_responder_gateway_not_created_without_flag(self):
        """
        Test that Responder Gateway is NOT created when includeRtbFabric is false.
        
        Validates Requirement 2.2: When the Deploy_Script is executed without 
        the `--include-rtb-fabric` flag, THEN THE CDK_Stack SHALL NOT create 
        any RTB_Fabric resources.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": False,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - No Responder Gateway should be created
        template.resource_count_is("AWS::RTBFabric::ResponderGateway", 0)

    def test_responder_gateway_created_with_flag(self):
        """
        Test that Responder Gateway is created when includeRtbFabric is true.
        
        Validates Requirement 4.2: WHERE the `--include-rtb-fabric` flag is set, 
        WHEN the CDK_Stack is deployed, THEN THE CDK_Stack SHALL create a 
        Responder_Gateway.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Responder Gateway should be created
        template.resource_count_is("AWS::RTBFabric::ResponderGateway", 1)

    def test_responder_gateway_attached_to_vpc(self):
        """
        Test that Responder Gateway is attached to bidder simulator VPC.
        
        Validates Requirement 4.3: WHERE the `--include-rtb-fabric` flag is set, 
        WHEN creating the Responder_Gateway, THEN THE CDK_Stack SHALL attach it 
        to the new Bidder_Simulator VPC.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Responder Gateway should reference VPC
        template.has_resource_properties("AWS::RTBFabric::ResponderGateway", {
            "VpcId": Match.any_value()
        })

    def test_responder_gateway_configured_for_ipv4(self):
        """
        Test that Responder Gateway is configured for IPv4 traffic only.
        
        Validates Requirement 4.4: WHERE the `--include-rtb-fabric` flag is set, 
        WHEN creating the Responder_Gateway, THEN THE CDK_Stack SHALL configure 
        it for IPv4 traffic only.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Responder Gateway should use HTTP protocol on port 80
        template.has_resource_properties("AWS::RTBFabric::ResponderGateway", {
            "Port": 80,
            "Protocol": "HTTP"
        })

    def test_responder_gateway_security_group_allows_http(self):
        """
        Test that Responder Gateway security group allows HTTP on port 80.
        
        Validates Requirement 4.5: WHERE the `--include-rtb-fabric` flag is set, 
        WHEN creating the Responder_Gateway, THEN THE CDK_Stack SHALL configure 
        security groups to allow HTTP traffic on TCP port 80.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Security group should allow HTTP (80)
        template.has_resource_properties("AWS::EC2::SecurityGroup", {
            "GroupDescription": "Security group for RTB Fabric Responder Gateway",
            "SecurityGroupIngress": Match.array_with([
                Match.object_like({
                    "IpProtocol": "tcp",
                    "FromPort": 80,
                    "ToPort": 80
                })
            ])
        })

    def test_responder_gateway_has_domain_name(self):
        """
        Test that Responder Gateway has ALB domain name configured.
        
        This ensures the gateway knows where to forward incoming bid requests.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Responder Gateway should have domain name pointing to ALB
        template.has_resource_properties("AWS::RTBFabric::ResponderGateway", {
            "DomainName": Match.any_value()
        })

    def test_responder_gateway_outputs_created(self):
        """
        Test that Responder Gateway outputs are created for reference.
        
        These outputs are needed for creating the Fabric Link in task 3.3.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - Stack should have Responder Gateway outputs
        template.has_output("ResponderGatewayId", {})
        template.has_output("ResponderGatewayArn", {})

    def test_alb_security_group_allows_traffic_from_gateway(self):
        """
        Test that ALB security group allows traffic from Responder Gateway.
        
        This ensures the gateway can forward bid requests to the ALB.
        Validates part of Requirement 4.5.
        """
        # Arrange
        app = App(context={
            "includeRtbFabric": True,
            "BIDDER_TYPE": "loadtest"
        })
        
        # Act
        stack = BidderSimulatorStack(app, "TestBidderSimulatorStack")
        template = Template.from_stack(stack)
        
        # Assert - There should be a SecurityGroupIngress resource allowing traffic from gateway to ALB
        # CDK creates separate SecurityGroupIngress resources for cross-security-group rules
        template.has_resource_properties("AWS::EC2::SecurityGroupIngress", {
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "SourceSecurityGroupId": Match.any_value(),
            "GroupId": Match.any_value()
        })
