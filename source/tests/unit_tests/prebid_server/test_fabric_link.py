# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for RTB Fabric Link in PBS Stack.
# USAGE:
#   pytest source/tests/unit_tests/prebid_server/test_fabric_link.py
###############################################################################

import pytest
import aws_cdk as cdk
from aws_solutions.cdk import CDKSolution
from aws_cdk.assertions import Template, Match
from prebid_server.prebid_server_stack import PrebidServerStack


@pytest.fixture(scope="module")
def mock_solution():
    """Mock solution context"""
    return CDKSolution(cdk_json_path="../source/infrastructure/cdk.json")


@pytest.fixture(scope="module")
def template_with_rtb_fabric(mock_solution):
    """Template with RTB Fabric integration enabled"""
    context = {
        **mock_solution.context.context,
        "includeRtbFabric": True,
        "responderGatewayId": "test-gateway-id-12345"  # Mock responder gateway ID
    }
    app = cdk.App(context=context)
    # Create a new synthesizer instance for this stack
    solution_for_rtb = CDKSolution(cdk_json_path="../source/infrastructure/cdk.json")
    stack = PrebidServerStack(
        app,
        PrebidServerStack.name,
        description=PrebidServerStack.description,
        template_filename=PrebidServerStack.template_filename,
        synthesizer=solution_for_rtb.synthesizer,
        responder_gateway_id="test-gateway-id-12345"
    )
    return Template.from_stack(stack)


def test_fabric_link_not_created_without_flag(mock_solution):
    """
    Test that Fabric Link is NOT created when includeRtbFabric is false.
    
    Validates: Requirements 2.2
    """
    # Arrange
    app = cdk.App(context=mock_solution.context.context)
    stack = PrebidServerStack(
        app,
        PrebidServerStack.name,
        description=PrebidServerStack.description,
        template_filename=PrebidServerStack.template_filename,
        synthesizer=mock_solution.synthesizer,
    )
    template = Template.from_stack(stack)
    
    # Assert - Verify no RTB Fabric Link exists
    template.resource_count_is("AWS::RTBFabric::Link", 0)


def test_fabric_link_created_with_flag(template_with_rtb_fabric):
    """
    Test that Fabric Link IS created when includeRtbFabric is true.
    
    Validates: Requirements 5.1, 5.2
    """
    # Assert - Verify RTB Fabric Link exists
    template_with_rtb_fabric.resource_count_is("AWS::RTBFabric::Link", 1)


def test_fabric_link_has_http_responder_allowed(template_with_rtb_fabric):
    """
    Test that Fabric Link has HttpResponderAllowed property set to True.
    
    This enables asymmetric security model:
    - Requester-to-Responder: HTTPS (secure)
    - Responder-to-Requester: HTTP (internal AWS network)
    
    Validates: Requirements 5.1, 5.2, 5.3
    """
    # Assert - Verify Link has HttpResponderAllowed set to True
    template_with_rtb_fabric.has_resource_properties(
        "AWS::RTBFabric::Link",
        {
            "HttpResponderAllowed": True
        }
    )


def test_fabric_link_maintains_log_settings(template_with_rtb_fabric):
    """
    Test that Fabric Link maintains existing LinkLogSettings configuration.
    
    Validates: Requirement 5.4
    """
    # Assert - Verify Link has LinkLogSettings with ApplicationLogs
    template_with_rtb_fabric.has_resource_properties(
        "AWS::RTBFabric::Link",
        {
            "LinkLogSettings": {
                "ApplicationLogs": {
                    "LinkApplicationLogSampling": {
                        "ErrorLog": 100,
                        "FilterLog": 100
                    }
                }
            }
        }
    )


def test_fabric_link_connects_gateways(template_with_rtb_fabric):
    """
    Test that Fabric Link connects Requester Gateway to Responder Gateway.
    
    Validates: Requirements 5.1, 5.5
    """
    # Assert - Verify Link has both GatewayId and PeerGatewayId
    template_with_rtb_fabric.has_resource_properties(
        "AWS::RTBFabric::Link",
        {
            "GatewayId": Match.any_value(),
            "PeerGatewayId": Match.any_value()
        }
    )


def test_fabric_link_has_name_tag(template_with_rtb_fabric):
    """
    Test that Fabric Link has a Name tag for easy identification.
    """
    # Assert - Verify Link has Name tag
    # Note: Value may be a CDK intrinsic function (Fn::Join) so we use Match.any_value()
    template_with_rtb_fabric.has_resource_properties(
        "AWS::RTBFabric::Link",
        {
            "Tags": Match.array_with([
                Match.object_like({
                    "Key": "Name",
                    "Value": Match.any_value()  # Value contains Fn::Join with stack name
                })
            ])
        }
    )
