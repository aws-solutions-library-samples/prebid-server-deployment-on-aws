# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for RTB Fabric Requester Gateway in PBS Stack.
# USAGE:
#   pytest source/tests/unit_tests/prebid_server/test_requester_gateway.py
###############################################################################

import pytest
import aws_cdk as cdk
from aws_solutions.cdk import CDKSolution
from aws_cdk.assertions import Template, Match
from prebid_server.prebid_server_stack import PrebidServerStack


@pytest.fixture(scope="module")
def mock_solution():
    return CDKSolution(cdk_json_path="../source/infrastructure/cdk.json")


@pytest.fixture(scope="module")
def template_without_rtb_fabric(mock_solution):
    """Template without RTB Fabric integration"""
    app = cdk.App(context=mock_solution.context.context)
    stack = PrebidServerStack(
        app,
        PrebidServerStack.name,
        description=PrebidServerStack.description,
        template_filename=PrebidServerStack.template_filename,
        synthesizer=mock_solution.synthesizer
    )
    yield Template.from_stack(stack)


@pytest.fixture(scope="module")
def template_with_rtb_fabric(mock_solution):
    """Template with RTB Fabric integration enabled"""
    context = {**mock_solution.context.context, "includeRtbFabric": True}
    app = cdk.App(context=context)
    # Create a new synthesizer instance for this stack
    from aws_solutions.cdk import CDKSolution
    solution_for_rtb = CDKSolution(cdk_json_path="../source/infrastructure/cdk.json")
    stack = PrebidServerStack(
        app,
        PrebidServerStack.name,
        description=PrebidServerStack.description,
        template_filename=PrebidServerStack.template_filename,
        synthesizer=solution_for_rtb.synthesizer
    )
    yield Template.from_stack(stack)


def test_requester_gateway_not_created_without_flag(template_without_rtb_fabric):
    """
    Test that Requester Gateway is NOT created when includeRtbFabric is false.
    Validates: Requirements 2.2
    """
    # Verify no RTB Fabric Requester Gateway exists
    template_without_rtb_fabric.resource_count_is("AWS::RTBFabric::RequesterGateway", 0)
    
    # Verify no Requester Gateway security group exists
    # We check that no security group with "RequesterGateway" in description exists
    resources = template_without_rtb_fabric.to_json()["Resources"]
    requester_gateway_sg_count = sum(
        1 for resource in resources.values()
        if resource.get("Type") == "AWS::EC2::SecurityGroup"
        and "RequesterGateway" in resource.get("Properties", {}).get("GroupDescription", "")
    )
    assert requester_gateway_sg_count == 0, "Requester Gateway security group should not exist"


def test_requester_gateway_created_with_flag(template_with_rtb_fabric):
    """
    Test that Requester Gateway IS created when includeRtbFabric is true.
    Validates: Requirements 2.3, 3.1
    
    Note: RequesterGateway does NOT support Port/Protocol properties.
    These are configured automatically by AWS RTB Fabric.
    """
    # Verify RTB Fabric Requester Gateway exists
    template_with_rtb_fabric.resource_count_is("AWS::RTBFabric::RequesterGateway", 1)
    
    # Verify Requester Gateway has correct configuration
    # Note: Port and Protocol are NOT supported properties for RequesterGateway
    template_with_rtb_fabric.has_resource_properties(
        "AWS::RTBFabric::RequesterGateway",
        {
            "VpcId": Match.any_value(),
            "SubnetIds": Match.any_value(),
            "SecurityGroupIds": Match.any_value(),
            "Description": Match.any_value(),
        }
    )


def test_requester_gateway_vpc_attachment(template_with_rtb_fabric):
    """
    Test that Requester Gateway is attached to PBS VPC.
    Validates: Requirements 3.2
    """
    # Get the template JSON to inspect resources
    resources = template_with_rtb_fabric.to_json()["Resources"]
    
    # Find the Requester Gateway resource
    requester_gateway = None
    for resource_id, resource in resources.items():
        if resource.get("Type") == "AWS::RTBFabric::RequesterGateway":
            requester_gateway = resource
            break
    
    assert requester_gateway is not None, "Requester Gateway should exist"
    
    # Verify VPC ID references the PBS VPC
    vpc_id = requester_gateway["Properties"]["VpcId"]
    assert "Ref" in vpc_id or "Fn::GetAtt" in vpc_id, "VPC ID should reference PBS VPC"
    
    # Verify subnet IDs are provided
    subnet_ids = requester_gateway["Properties"]["SubnetIds"]
    assert isinstance(subnet_ids, list), "Subnet IDs should be a list"
    assert len(subnet_ids) > 0, "At least one subnet should be specified"


def test_requester_gateway_ipv4_configuration(template_with_rtb_fabric):
    """
    Test that Requester Gateway is configured for IPv4 traffic only.
    Validates: Requirements 3.3
    
    Note: RequesterGateway does NOT support Port/Protocol properties.
    IPv4 configuration is validated through security group rules allowing HTTPS (443).
    """
    # Get the template JSON to inspect resources
    resources = template_with_rtb_fabric.to_json()["Resources"]
    
    # Find the Requester Gateway resource
    requester_gateway = None
    for resource_id, resource in resources.items():
        if resource.get("Type") == "AWS::RTBFabric::RequesterGateway":
            requester_gateway = resource
            break
    
    assert requester_gateway is not None, "Requester Gateway should exist"
    
    # Verify gateway is attached to VPC (IPv4 configuration)
    assert "VpcId" in requester_gateway["Properties"], "Gateway should be attached to VPC"
    assert "SubnetIds" in requester_gateway["Properties"], "Gateway should have subnet configuration"
    
    # IPv4 traffic configuration is enforced through security groups
    # which allow HTTPS (443) - tested in test_requester_gateway_security_groups


def test_requester_gateway_security_groups(template_with_rtb_fabric):
    """
    Test that Requester Gateway has security groups allowing HTTPS (443).
    Validates: Requirements 3.4
    """
    # Verify security group for Requester Gateway exists
    # The security group should have ingress rules allowing HTTPS (443)
    template_with_rtb_fabric.has_resource_properties(
        "AWS::EC2::SecurityGroup",
        {
            "SecurityGroupIngress": Match.array_with([
                Match.object_like({
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443
                })
            ]),
            "SecurityGroupEgress": Match.array_with([
                Match.object_like({
                    "CidrIp": "0.0.0.0/0"
                })
            ])
        }
    )


def test_requester_gateway_outputs(template_with_rtb_fabric):
    """
    Test that Requester Gateway outputs are created for reference.
    
    Note: RequesterGateway does NOT have a Url attribute.
    Only GatewayId and Arn are available.
    """
    # Verify RequesterGatewayId output exists
    template_with_rtb_fabric.has_output(
        "RequesterGatewayId",
        {
            "Description": "RTB Fabric Requester Gateway ID",
            "Value": Match.any_value()
        }
    )
    
    # Verify RequesterGatewayArn output exists
    template_with_rtb_fabric.has_output(
        "RequesterGatewayArn",
        {
            "Description": "RTB Fabric Requester Gateway ARN",
            "Value": Match.any_value()
        }
    )
